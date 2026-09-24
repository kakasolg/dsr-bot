"""4층 보조 — 판단 루프와 따로 도는 감시: 긴급 탈출(퀵 종료)과 핏자국 기록.

퀵 종료(메뉴 → Quit Game → 이어하기)는 **적의 위치·경계만 리셋하고 죽은 적은 살리지 않는다** (사용자 확인 2026-09-24).
쉬면(화톳불) 적이 전부 살아난다. 그래서 적을 떼어낼 땐 쉬지 말고 이걸 쓴다.
"""
from __future__ import annotations

import collections
import json
import threading
import time
from pathlib import Path

import env
import navmesh
import quitout


ROOT = Path(__file__).resolve().parent.parent
BLOODSTAIN = ROOT / "data" / "bloodstain.json"
FALL_ANIMS = (1550, 121500)
NO_GROUND = (1500, 1550, 121500, 1600, 6074, 6174)


class Escape:
    """긴급 탈출. 50 Hz 로 보고, 쏠 때는 패드를 얼려(Pad.freeze) 판단 루프의 입력이 메뉴 입력에 섞이지 않게 한다.
      · 낙사: 떨어지는 중(모션 1550, 또는 0.4 s 에 2.5 m 넘게 내려감)이고 발밑 바닥이 8 m 넘게 아래
        → 종료하면 떨어지기 전 가장자리에서 다시 선다
      · 곧 죽음: 3.5 m 안에 둘 이상이고 **2.8 s 뒤 예상 HP**가 15 % 아래 (60 s 에 한 번 — 그 자리에서 다시 시작하므로)
        — 종료 입력에 2.4~2.5 s 걸리는 동안에도 맞는다 (298 → 24 로 끝난 적이 있다). 그래서 들어오는 피해 속도를 본다
    gen 은 나갔다 올 때마다 +1 — 적 포인터가 전부 바뀌니 위층은 gen 이 바뀌면 적을 다시 찾는다."""
    LETHAL_DROP = 8.0         # 15 m 로 뒀더니 경사로 옆(약 10~12 m)에서 HP 413 인 채 떨어져 죽었다 (2026-09-24)
    FALL_V = 2.5              # 0.4 s 에 이만큼 내려가면 떨어지는 중 — 애니 번호(1550)가 안 뜨는 추락(가드가 깨져 밀려남)도 잡는다
    FALL_COOLDOWN = 4.0       # 예전 30 s: 가장자리에서 다시 서자마자 또 떨어지는 걸 못 막았다
    CROWD_COOLDOWN = 60.0     # 같은 자리에서 반복하지 않게
    QUIT_S = 2.8

    def __init__(self, pad, nms: list, log=print, events=None):
        self.pad, self.nms, self.log, self.events = pad, nms, log, events
        self.escaping = False
        self.gen = 0
        self.last_fall = self.last_crowd = 0.0
        self.last_fall_pos = None     # 낙사 탈출 직후 위층이 가장자리에서 물러나게
        self._lock = threading.Lock()
        self._stop = False
        self._hp = collections.deque(maxlen=60)
        self._y = collections.deque(maxlen=40)
        self.th = threading.Thread(target=self._run, daemon=True)

    def floor_drop(self, p) -> float:
        below = [y for nm in self.nms for y, f, _i in nm.tris_at(p.x, p.z) if not (f & navmesh.BLOCKED) and y <= p.y + 0.3]
        return p.y - max(below) if below else 99.0

    def _dps(self, now: float) -> float:
        pts = [(t, hp) for t, hp in self._hp if now - t <= 1.5]
        if len(pts) < 2:
            return 0.0
        lost = sum(max(0, a[1] - b[1]) for a, b in zip(pts, pts[1:]))
        return lost / max(0.3, pts[-1][0] - pts[0][0])

    def _run(self) -> None:
        tm = env.make_telemetry({})
        while not self._stop:
            try:
                s = tm.snapshot(within=5.0)
            except Exception:
                s = None
            if s is None or s.player.hp is None or s.player.hp <= 0 or self.escaping:
                time.sleep(0.05)
                continue
            now, p = time.time(), s.player
            self._hp.append((now, p.hp))
            self._y.append((now, p.y))
            why = None
            ys = [y for t, y in self._y if now - t <= 0.4]
            falling = p.anim in FALL_ANIMS or (len(ys) >= 3 and max(ys) - p.y > self.FALL_V)
            if falling and now - self.last_fall > self.FALL_COOLDOWN:
                drop = self.floor_drop(p)
                if drop > self.LETHAL_DROP:
                    why, kind = f"낙사 (발밑 바닥 {drop:.0f} m 아래)", "fall"
            elif now - self.last_crowd > self.CROWD_COOLDOWN:
                near = [c for c in s.hostile(3.5) if c.hp > 0 and not (9000 <= (c.anim or 0) < 9100)]
                future = p.hp - self._dps(now) * self.QUIT_S
                # 퀵 종료는 **그 자리에서** 다시 시작한다 — 적 스폰 옆이면 곧바로 다시 붙는다 (2026-09-24: 5 번 반복, 659 → 24,
                # 사용자: "지금 위치 강종하기 안 좋아"). 그래서 '곧 죽는다' 일 때만 — 둘러싸임 자체는 4층이 물러나기·다크사인으로
                if len(near) >= 2 and future < p.max_hp * 0.15:
                    why, kind = f"둘러싸임 {len(near)}명, HP {p.hp}/{p.max_hp}, 2.8 s 뒤 예상 {future:.0f}", "crowd"
            if why:
                self.fire(why, kind, tm, p)
            time.sleep(0.02)

    def fire(self, why: str, kind: str, tm=None, p=None) -> dict:
        """메뉴로 나갔다 온다. 위층이 적을 떼어낼 때도 이걸 부른다 (kind='shake'). → 결과"""
        with self._lock:
            tm = tm or env.make_telemetry({})
            if p is None:
                s0 = tm.snapshot(within=5.0)
                p = s0.player if s0 else None
            pos0 = None if p is None else [round(p.x, 2), round(p.y, 2), round(p.z, 2)]
            self.log(f"   ⚠ 퀵 종료: {why} @ {pos0}")
            self.escaping = True
            self.pad.freeze()
            res: dict = {"why": why, "kind": kind, "pos0": pos0}
            try:
                q = quitout.quit_out(tm, self.pad, gap=quitout.MENU_GAP, settle=0.1, ready_wait=0.05)
                res["quit_s"] = None if q is None else round(q, 2)
                if q is None:
                    quitout.close_menu(tm, self.pad)
                else:
                    r = quitout.reload(self.pad)
                    res["reload_s"] = None if r is None else round(r, 1)
                    time.sleep(1.0)
            finally:
                self.pad.neutral()
                self.pad.unfreeze()
            tm2 = env.make_telemetry({})
            s = tm2.snapshot(within=5.0)
            if s:
                res["pos"] = [round(s.player.x, 2), round(s.player.y, 2), round(s.player.z, 2)]
                res["hp"] = s.player.hp
            now = time.time()
            if kind == "fall":
                self.last_fall, self.last_fall_pos = now, pos0
            elif kind == "crowd":
                self.last_crowd = now
            self._hp.clear()
            self._y.clear()
            self.gen += 1
            self.escaping = False
            self.log(f"   ⚠ 퀵 종료 결과: {res}")
            if self.events:
                self.events("escape", **res)
            return res

    def start(self) -> "Escape":
        self.th.start()
        return self

    def stop(self) -> None:
        self._stop = True
        self.th.join(timeout=2.0)


class Blood:
    """핏자국 — 죽으면 소울·인간성을 그 자리(떨어졌으면 떨어지기 직전 가장자리)에 남긴다.
    예전엔 HP 가 0 으로 읽히는 순간 바로 기록해서, 퀵 종료·로딩 중 가짜 '죽음' 이 화톳불 자리 핏자국으로 남았고,
    그걸 주우러 가서 A 를 누르면 화톳불에 앉아 잡은 적이 전부 살아났다 (2026-09-24 실측 두 번).
    그래서 **부활한 뒤 소울이 실제로 줄었을 때만** 기록한다. 살아 있는 동안 소울이 핏자국만큼 한 번에 늘면 회수로 보고 지운다."""

    def __init__(self, log=print):
        self.log = log
        self._stop = False
        self.th = threading.Thread(target=self._run, daemon=True)

    @staticmethod
    def read() -> dict | None:
        try:
            return json.loads(BLOODSTAIN.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _run(self) -> None:
        tm = env.make_telemetry({})
        last, pending, prev_souls, last_attach = None, None, None, time.time()
        while not self._stop:
            try:
                s = tm.snapshot(within=1.0)
            except Exception:
                s = None
            if s is None:
                if time.time() - last_attach > 3.0:
                    last_attach = time.time()
                    try:
                        tm = env.make_telemetry({})
                    except Exception:
                        pass
                time.sleep(0.2)
                continue
            p = s.player
            if p.hp is not None and p.hp > 0:
                souls = tm.souls() or 0
                if pending is not None:                    # 살아 있다 — 진짜 죽었었나?
                    if souls < pending["souls"] or (pending["souls"] == 0 and (tm.humanity() or 0) < pending["humanity"]):
                        rec = {**pending, "t": time.strftime("%Y-%m-%d %H:%M:%S")}
                        BLOODSTAIN.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
                        self.log(f"   ✝ 죽음 — 핏자국 {rec['pos']} (소울 {rec['souls']}, 인간성 {rec['humanity']})")
                    pending = None
                    prev_souls = souls
                rec = self.read()
                # 적을 잡아도 소울이 는다 — 핏자국 3 m 안에서 그만큼 늘었을 때만 회수로 본다
                if (rec and prev_souls is not None and souls - prev_souls >= max(1, rec["souls"])
                        and ((p.x - rec["pos"][0]) ** 2 + (p.z - rec["pos"][2]) ** 2) ** 0.5 < 3.0):
                    BLOODSTAIN.unlink(missing_ok=True)
                    self.log(f"   핏자국 회수됨: 소울 {prev_souls} → {souls}")
                prev_souls = souls
                if p.anim not in NO_GROUND:
                    last = {"pos": [round(p.x, 2), round(p.y, 2), round(p.z, 2)], "souls": souls, "humanity": tm.humanity() or 0}
            elif pending is None and last is not None and (last["souls"] > 0 or last["humanity"] > 0):
                pending = dict(last)
            time.sleep(0.2)

    def start(self) -> "Blood":
        self.th.start()
        return self

    def stop(self) -> None:
        self._stop = True
