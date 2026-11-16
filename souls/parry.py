"""Parry in a real fight — duel.rule_parry (MoKa 11-15 M1115-13 · 11-16 M1116-01).

MoKa: "정규 루트에 패링을 우선 순위로 넣고 해봐. 일단 칼을 든 적들은 다 가능 할거야. … 패링 한다고 뛰어들면 않되고 …
가급적 1:1 상황을 유도". [cloud]가 전한 11-16: "나보다 타이밍을 더 잘 잡으니 해 봐도 될 것 같다. 문제가 되면 내가 다시 원복하라고 하겠다."

Off with one line: PARRY_ON = False here, or run.py --no-parry (the run's settings.json records which).

When it acts (all must hold; otherwise the rule passes and the usual rules run):
 · the target plays a melee attack (3000–3999) whose hit windows are in the game files (data/gamefiles/tae_turn.json, TAE
   type 1), the model can be riposted (data/gamefiles/throw_params.json ripostable_models), and the attack is not in NO_PARRY;
 · no other foe within ALONE_R is awake (anim ≠ −1) — one-on-one only;
 · the target is within MAX_PARRY_M — the rule never walks in to parry ("뛰어들면 않되고");
 · the first hit window starts within ENTER_S from now.
Then it holds the pad (Pad.freeze, so the guard keeper does not hold LB over it), faces the foe, and presses L2 when the hit
window is LEAD_S away (MIN_LEFT_S at least). Parried (2100) → close to RIPOSTE_M and R1. Every press → one "parry" event:
npc · anim · anim time · distance · awake foes ≤ 5 m · result · riposte damage, and "parry_after" 3 s later with HP lost.

── 타이밍 근거 (11-15 MoKa 시범 23번 중 12번 · 드릴 5판 판정 21번 중 11번, parry_drill.py) ────────────
 · 패링 애니 485102는 L2 뒤 0~17 ms에 시작. 성공은 적 판정 시작이 패링 애니 0.02~0.19 s 째일 때.
 · 같은 메모리 애니 번호라도 NPC마다 TAE 섹션이 다름 (SECTION). 표에 없는 NPC는 a00으로 봄 — Burg 망자·병사는 아직 확인 안 함.
 · 2.2 m 넘는 곳의 c2560 3003은 3번 모두 실패 (가설: 거리). 앞잡이 표(ThrowParam 22540…)는 1.5 m.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

PARRY_ON = True
PARRIED = {2100, 2101, 2102}
LEAD_S = 0.12
MIN_LEFT_S = 0.03
ENTER_S = 0.9          # take the pad this long before the hit window at most (c2540 3000: 0.867 s from the start)
MAX_PARRY_M = 2.0      # 11-15 경사로 1회차: 성공 1.16~1.83 m, 실패 2.1 · 2.19 m (드릴: 성공 ≤ 1.91, 실패 2.31~2.87)
MAX_DY = 0.8           # 같은 날: 높이 차 1.2 m에서 패링은 됐지만 앞잡이가 안 들어감 (일반 공격으로 나감)
FACE_DEG = 45.0        # 같은 날: 적이 옆(−97°), 0.65 m에서 누른 패링 실패 — 이 각 밖이면 누르지 않음
MAX_FAILS = 2          # 같은 (NPC, 공격)이 성공 없이 이만큼 실패하면 이번 실행에선 그 공격은 패링 안 함
RIPOSTE_M = 1.2        # ThrowParam 1.5 m; drill 1.63 m gave a normal hit
ALONE_R = 5.0
MIN_SP = 15
JUDGE_S = 0.6
AFTER_S = 3.0
SECTION = {255041: 1, 256002: 2}
NO_PARRY = {("c2550", 3009)}
NO_PARRY_NPC = {255002, 255042, 255006, 256001}   # crossbow / bow (ranged; melee only at point blank — not in the drill)

_ROOT = Path(__file__).resolve().parent.parent / "data" / "gamefiles"
_WIN: dict | None = None
_RIPOSTE: set | None = None
_TALLY: dict = {}      # (npc, anim) → [ok, fail] this process (= this run)


def model_of(npc: int) -> str:
    return f"c{str(npc)[:4]}"


def load_windows() -> dict:
    """{(model, full anim id): [(start, end), …]} from tae_turn.json (a01 = 1xxxx, a02 = 2xxxx)."""
    global _WIN
    if _WIN is None:
        _WIN = {}
        try:
            d = json.loads((_ROOT / "tae_turn.json").read_text(encoding="utf-8"))
            for m, anims in d["models"].items():
                for a, r in anims.items():
                    if r.get("hit"):
                        _WIN[(m, int(a))] = [tuple(w) for w in r["hit"]]
        except (OSError, ValueError, KeyError):
            _WIN = {}
    return _WIN


def ripostable() -> set:
    global _RIPOSTE
    if _RIPOSTE is None:
        try:
            _RIPOSTE = set(json.loads((_ROOT / "throw_params.json").read_text(encoding="utf-8"))["ripostable_models"])
        except (OSError, ValueError, KeyError):
            _RIPOSTE = set()
    return _RIPOSTE


def windows_for(win: dict, npc: int, anim: int):
    m, sec = model_of(npc), SECTION.get(npc, 0)
    if anim < 10000 and sec and (m, sec * 10000 + anim) in win:
        return win[(m, sec * 10000 + anim)]
    return win.get((m, anim))


def parry_due(windows, at, offset: float = 0.0, done=()):
    if at is None:
        return None
    for i, (w0, _) in enumerate(windows):
        if i in done:
            continue
        if MIN_LEFT_S <= w0 + offset - at <= LEAD_S:
            return i
    return None


def candidate(npc: int, anim, win: dict | None = None, models: set | None = None):
    """Hit windows of this attack when it may be parried, else None. Pure apart from the cached tables."""
    if anim is None or not 3000 <= anim < 4000 or npc in NO_PARRY_NPC:
        return None
    m = model_of(npc)
    if (m, anim) in NO_PARRY or m not in (models if models is not None else ripostable()):
        return None
    return windows_for(load_windows() if win is None else win, npc, anim)


def given_up(npc: int, anim: int) -> bool:
    ok, fail = _TALLY.get((npc, anim), (0, 0))
    return ok == 0 and fail >= MAX_FAILS


def tally(npc: int, anim: int, result: str) -> None:
    t = _TALLY.setdefault((npc, anim), [0, 0])
    if result == "ok":
        t[0] += 1
    elif result == "fail":
        t[1] += 1


def off_deg(p, c):
    if p.heading is None:
        return None
    fwd = p.heading + math.pi
    return math.degrees((math.atan2(c.x - p.x, c.z - p.z) - fwd + math.pi) % (2 * math.pi) - math.pi)


def awake_others(s, ptr, r: float = ALONE_R) -> list:
    p = s.player
    return [x for x in s.hostile(r + 1.0)
            if x.ptr != ptr and x.hp > 0 and x.anim not in (-1, None) and abs(x.y - p.y) < 2.0
            and ((x.x - p.x) ** 2 + (x.z - p.z) ** 2) ** 0.5 <= r]


class Parry:
    """One per fight loop (duel.Fight keeps it). try_() runs a whole parry when the conditions hold → 'kill' | 'cont' | None."""

    def __init__(self, mv, log=print, events=None):
        self.mv, self.log = mv, log
        self.events = events or (lambda *_a, **_k: None)
        self.after: list = []          # (due time, hp then, npc, anim) — "parry_after"
        self.last_t = 0.0

    def _flush_after(self, hp_now) -> None:
        now = time.time()
        keep = []
        for due, hp0, npc, anim in self.after:
            if now >= due and hp_now is not None:
                self.events("parry_after", npc=npc, anim=anim, lost_3s=max(0, hp0 - hp_now))
            else:
                keep.append((due, hp0, npc, anim))
        self.after = keep

    def try_(self, s, c, a) -> str | None:
        p = s.player
        self._flush_after(p.hp)
        if not PARRY_ON or c is None:
            return None
        wins = candidate(c.npc_param, a)
        if not wins or given_up(c.npc_param, a):
            return None
        tm = self.mv.tm
        at = getattr(tm, "anim_time", lambda _p: None)(c.ptr)
        if at is None:
            return None
        h = ((c.x - p.x) ** 2 + (c.z - p.z) ** 2) ** 0.5
        nxt = [i for i, (w0, _) in enumerate(wins) if w0 - at >= MIN_LEFT_S]
        if not nxt or wins[nxt[0]][0] - at > ENTER_S:
            return None
        if h > MAX_PARRY_M or abs((c.y or 0) - (p.y or 0)) > MAX_DY or (p.sp or 0) < MIN_SP or awake_others(s, c.ptr) or time.time() - self.last_t < 0.8:
            return None
        return self._run(c, a, wins, nxt[0], p.hp, len(awake_others(s, c.ptr)))

    def _run(self, c, a, wins, i, hp0, others) -> str:
        mv, pad, tm = self.mv, self.mv.pad, self.mv.tm
        pad.freeze()
        res = {"npc": c.npc_param, "anim": a, "win": list(wins[i]), "others_5m": others, "hp": hp0}
        try:
            pad.neutral()
            t_end = time.time() + ENTER_S + 0.3
            pressed = None
            while time.time() < t_end:
                s = mv.snap(8.0)
                k = mv.find(s, c.ptr) if s else None
                if k is None or k.hp <= 0 or k.anim != a:
                    res["result"] = "anim_changed"
                    return "cont"
                at = tm.anim_time(c.ptr)
                h = ((k.x - s.player.x) ** 2 + (k.z - s.player.z) ** 2) ** 0.5
                if h > MAX_PARRY_M + 0.3:
                    res.update(result="moved_off", d=round(h, 2))
                    return "cont"
                off = off_deg(s.player, k)
                if parry_due(wins, at, done=range(i)) == i:
                    if off is None or abs(off) > FACE_DEG:
                        res.update(result="off_angle", off=None if off is None else round(off), d=round(h, 2))
                        return "cont"
                    pad.parry()
                    self.last_t = pressed = time.time()
                    res.update(at=round(at, 3), d=round(h, 2), off=round(off), dy=round(k.y - s.player.y, 2))
                    break
                mv.face(s, k, deg=20.0)
                time.sleep(0.003)
            if pressed is None:
                res["result"] = "no_press"
                return "cont"
            while time.time() - pressed < JUDGE_S:
                s = mv.snap(8.0)
                k = mv.find(s, c.ptr) if s else None
                if k is not None and k.anim in PARRIED:
                    return self._riposte(k, res)
                time.sleep(0.005)
            res["result"] = "fail"
            pad.guard(True)
            return "cont"
        finally:
            pad.unfreeze()
            tally(c.npc_param, a, res.get("result", ""))
            self.after.append((time.time() + AFTER_S, hp0, c.npc_param, a))
            self.events("parry", **res)
            self.log(f"      패링 {res.get('result')} — {c.npc_param} {a} at {res.get('at')} d {res.get('d')} "
                     f"옆 {others} 앞잡이 {res.get('riposte', '-')}")

    def _riposte(self, k, res) -> str:
        mv, pad = self.mv, self.mv.pad
        res["result"] = "ok"
        t0 = time.time()
        while time.time() - t0 < 0.5:
            s = mv.snap(8.0)
            k2 = mv.find(s, k.ptr) if s else None
            if k2 is None:
                break
            h = ((k2.x - s.player.x) ** 2 + (k2.z - s.player.z) ** 2) ** 0.5
            if h <= RIPOSTE_M:
                break
            pad.move(*mv.stick_to(s, k2.x, k2.z, 1.0))
            time.sleep(0.01)
        pad.move(0.0, 0.0)
        khp0 = k.hp
        pad.attack()
        t1 = time.time()
        # 앞잡이 피해는 찌르기(12~16) 뒤 약 2.4 s에 큰 한 방 (11-15 경사로: 첫 감소에서 멈춰 '앞잡이 16', 2.4 s 뒤 죽음 ·
        # Burg: 1 s 조용하면 멈췄더니 '12', 1.4 s 뒤 죽음) → 죽거나 3.5 s 다 볼 때까지 봄
        last_hp = khp0
        while time.time() - t1 < 3.5:
            pad.release_due()
            s = mv.snap(8.0)
            k2 = mv.find(s, k.ptr) if s else None
            hp = 0 if k2 is None else k2.hp
            if s and s.player.hp is not None and s.player.hp < res["hp"]:   # 앞잡이가 안 들어가고 맞는 중 → 손 놓음
                last_hp = hp
                res["hit_during"] = res["hp"] - s.player.hp
                break
            if hp <= 0:
                last_hp = 0
                break
            last_hp = hp
            time.sleep(0.01)
        k2 = None if last_hp <= 0 else k2
        res["riposte"] = khp0 - last_hp
        return "kill" if k2 is None or k2.hp <= 0 else "cont"
