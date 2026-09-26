"""
0층 — 블랙박스. 피드가 읽는 프레임(~58 Hz)을 최근 BUFFER_S 초만큼 쥐고 있다가, 크게 맞으면 그 앞뒤를 통째로 남긴다.

왜 (2026-09-25 burg-loop 094803): wait_far 로 기다리는 11 s 동안 HP 490 → 242 가 깎였는데 누가 때렸는지 모른다.
로그는 1 Hz 요약이고 추적 목표만 적는다 — 추적 안 하던 놈의 공격은 어디에도 안 남았다.

남기는 것 (run.py 의 Log 와 같은 이름으로):
  · <run>.jsonl  "vital" 사건 VITAL_S 마다 — HP·최대 HP·가까운 적 수. 판 위험 채점(risk_report.py)의 재료.
  · <run>.jsonl  "hit" 사건 — 한 번의 피격 묶음 요약 (잃은 HP, 남은 HP, 범인 추정)
  · <run>.hits.jsonl 한 줄 = 피격 묶음 하나의 전체 프레임 (앞 BUFFER_S 초 + 뒤 TAIL_S 초, 주변 NEAR_M 안 적 전부)

피격 묶음: HP 가 줄기 시작해 GAP_S 동안 더 안 줄면 끝. 합이 HIT_HP 이상이거나 HP 가 LOW_FRAC 아래로 떨어진 묶음만 남긴다.
범인 추정: 첫 감소 전 BLAME_S 안에 애니가 바뀐(-1 이 아닌) 적 중, 날 보고 있고(±60°) 가장 가까운 놈. 어디까지나 추정 —
확실한 건 .hits.jsonl 프레임을 직접 보는 것 (`python risk_report.py --hits <run>`).

파일 쓰기는 따로 스레드 — 피드 스레드(읽기 주기)를 막지 않는다.
"""
from __future__ import annotations

import collections
import json
import math
import queue
import threading
from pathlib import Path
from typing import Optional

BUFFER_S = 8.0      # 피격 전 몇 초를 남기나 — 11 s 긴 소모도 묶음 여러 개로 잡힌다
TAIL_S = 1.0
GAP_S = 1.5
HIT_HP = 80         # 이보다 적게 잃은 묶음은 안 남긴다 (약 10 %, 최대 HP 793 기준)
LOW_FRAC = 0.25
BLAME_S = 1.5
NEAR_M = 12.0
VITAL_S = 0.5
AWAKE_M = 5.0       # vital 의 "가까운 적" 반경
HOSTILE = (6, 7, 24, 25, 27, 33)   # telemetry.Snapshot.hostile 과 같은 팀


def _facing_me(c, p) -> Optional[float]:
    """c 가 날 보는 각 (rad, 0 = 정면). moves.rel_angle 과 같은 규약 (월드 yaw = heading + π)."""
    if c.heading is None:
        return None
    fwd = c.heading + math.pi
    return abs((math.atan2(p.x - c.x, p.z - c.z) - fwd + math.pi) % (2 * math.pi) - math.pi)


def _frame(s) -> dict:
    p = s.player
    foes = []
    for c in s.chars:
        if c.team not in HOSTILE or c.hp <= 0 or c.dist > NEAR_M:
            continue
        f = _facing_me(c, p)
        foes.append({"npc": c.npc_param, "ptr": c.ptr, "hp": c.hp, "d": round(c.dist, 2), "dy": round(c.y - p.y, 2),
                     "anim": c.anim, "face": None if f is None else round(math.degrees(f))})
    return {"t": round(s.t, 3), "hp": p.hp, "max": p.max_hp, "anim": p.anim, "sp": p.sp,
            "pos": [round(p.x, 2), round(p.y, 2), round(p.z, 2)], "foes": foes}


class BlackBox:
    def __init__(self, feed, run_path: Path, events, log=None):
        self.feed, self.events, self.log = feed, events, log or (lambda *_: None)
        self.hits_path = run_path.with_name(run_path.stem + ".hits.jsonl")
        self.buf: collections.deque = collections.deque()
        self._q: queue.Queue = queue.Queue()
        self._th = threading.Thread(target=self._writer, daemon=True, name="blackbox")
        self._last_hp: Optional[int] = None
        self._ep: Optional[dict] = None      # 진행 중인 피격 묶음
        self._t_vital = 0.0
        self.n_hits = 0

    def start(self) -> "BlackBox":
        if not hasattr(self.feed, "listeners"):
            self.log("   블랙박스: 피드가 없다 (BOT_FEED=0?) — 안 켬")
            return self
        self._th.start()
        self.feed.listeners.append(self.on_frame)
        return self

    def stop(self) -> None:
        if hasattr(self.feed, "listeners") and self.on_frame in self.feed.listeners:
            self.feed.listeners.remove(self.on_frame)
        if self._ep is not None:
            self._close(self._ep)
            self._ep = None
        self._q.put(None)
        if self._th.is_alive():
            self._th.join(timeout=3.0)

    # ── 피드 스레드에서 불림: 가볍게 ────────────────────────────
    def on_frame(self, s) -> None:
        if s is None or s.player is None or not s.player.max_hp:
            self._last_hp = None             # 로딩 — 퀵 종료·부활 전후 HP 차이를 피격으로 오인하지 않게
            return
        fr = _frame(s)
        t, hp = fr["t"], fr["hp"]
        self.buf.append(fr)
        while self.buf and t - self.buf[0]["t"] > BUFFER_S + TAIL_S + GAP_S:
            self.buf.popleft()
        if t - self._t_vital >= VITAL_S:
            self._t_vital = t
            near = sum(1 for f in fr["foes"] if f["d"] <= AWAKE_M)
            self._q.put(("ev", "vital", {"hp": hp, "max": fr["max"], "near": near}))
        prev, self._last_hp = self._last_hp, hp
        if prev is not None and hp < prev:
            if self._ep is None:
                self._ep = {"t0": t, "hp0": prev, "t_last": t, "lo": hp}
            self._ep["t_last"], self._ep["lo"] = t, min(self._ep["lo"], hp)
        if self._ep is not None and t - self._ep["t_last"] >= max(GAP_S, TAIL_S):
            self._close(self._ep)
            self._ep = None

    def _close(self, ep: dict) -> None:
        lost = ep["hp0"] - ep["lo"]
        mx = self.buf[-1]["max"] if self.buf else 1
        if lost < HIT_HP and ep["lo"] >= LOW_FRAC * mx:
            return
        frames = [f for f in self.buf if ep["t0"] - BUFFER_S <= f["t"] <= ep["t_last"] + TAIL_S]
        self._q.put(("hit", ep, lost, mx, frames))

    # ── 쓰기 스레드 ────────────────────────────────────────
    def _writer(self) -> None:
        with self.hits_path.open("a", encoding="utf-8") as fh:
            while True:
                item = self._q.get()
                if item is None:
                    return
                try:
                    if item[0] == "ev":
                        self.events(item[1], **item[2])
                        continue
                    _, ep, lost, mx, frames = item
                    self.n_hits += 1
                    who = blame(frames, ep["t0"])
                    dur = round(ep["t_last"] - ep["t0"], 2)
                    self.events("hit", n=self.n_hits, lost=lost, hp=ep["lo"], max=mx, secs=dur, blame=who)
                    self.log(f"   ▣ 블랙박스 #{self.n_hits}: {dur} s 동안 -{lost} → HP {ep['lo']}/{mx}, 추정 {fmt_blame(who)}")
                    fh.write(json.dumps({"n": self.n_hits, "t0": ep["t0"], "hp0": ep["hp0"], "lo": ep["lo"], "max": mx,
                                         "blame": who, "frames": frames}, ensure_ascii=False) + "\n")
                    fh.flush()
                except Exception as ex:          # 기록기가 봇을 멈추게 하면 안 된다
                    self.log(f"   블랙박스 쓰기 실패: {ex!r}")


def blame(frames: list, t0: float) -> list:
    """첫 감소 직전 BLAME_S 안에 공격 애니(-1 아님)를 시작한 적들 — 가까운 순. 각 {npc, ptr, anim, d, face}."""
    win = [f for f in frames if t0 - BLAME_S <= f["t"] <= t0]
    seen: dict = {}
    for fr in win:
        for f in fr["foes"]:
            if f["anim"] not in (None, -1):
                seen[f["ptr"]] = f                # 마지막(피격에 가장 가까운) 모습
    out = sorted(seen.values(), key=lambda f: (f["face"] is not None and f["face"] > 60, f["d"]))
    return [{k: f[k] for k in ("npc", "ptr", "anim", "d", "dy", "face")} for f in out[:3]]


def fmt_blame(who: list) -> str:
    if not who:
        return "공격 애니 중인 적 없음 (투사체·낙하·범위 밖?)"
    return ", ".join(f"{w['npc']} 애니 {w['anim']} {w['d']} m 정면±{w['face']}°" for w in who)
