"""P-121 swing backstep: B when the foe comes to ~2.3 m or just starts swinging there, R1 queued 0.6 s later (no game).
  python tests/swing_bs_test.py

[MoKa] 2026-11-03: "적이 무기를 휘두를때 백스텝으로 피하면 적이 휘청 거리는데, 바로 공격이 들어가는게 핵심인데"
값은 MoKa 직접 시범 155254 (성공 3번: 2.2–2.3 m에서 B, R1 B+0.53–0.73 s).
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
import time
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import duel as D
from souls import swing_windows as SW


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


class Mv:
    def __init__(self, lock="target"):
        self.calls, self.lock = [], lock

    def lock_state(self, ptr):
        return self.lock

    def backstep(self):
        self.calls.append(("backstep",))

    def guard(self, on):
        self.calls.append(("guard", on))

    def backstep_attack(self, s, c, nm=None, front=2.2, r1_at=None, swing=None):
        self.calls.append(("bs", round(r1_at - time.time(), 2), swing))
        return NS(presses=2, skipped=None, dmg=40, taken=0, dead=False, my_anims=[(0.1, 690)], e_anims=[(0.0, swing)])


def fight(mv):
    F = NS(flags=D.Flags(), mv=mv, nm=None, log=lambda *_: None, events=lambda *_a, **_k: None, notes=[])
    F.note = lambda what, *_a: F.notes.append(what)
    F.record = lambda hit: None
    F.killed_if = lambda dead: "killed" if dead else D.CONT
    return F


def tick(F, anim, age, h=2.2, npc=254000, sp=98, v=0.0, now=100.0):
    c = NS(ptr=7, npc_param=npc, x=0.0, y=0.0, z=h, anim=anim, hp=80)
    F._hv = {7: (time.time() - 0.1, h + v * 0.1, v)}
    T = NS(s=NS(player=NS(sp=sp)), c=c, h=h, a=anim, age=age, now=now)
    return D.rule_swing_backstep(F, T)


def bs(F):
    return [x for x in F.mv.calls if x[0] == "bs"]


def main() -> None:
    w = SW.window(254000, 3000)
    check(f"망자 3000 판정 구간 ({w})", w == (0.8667, 1.0333))
    saved = D.COMBO_ONLY, D.DRILL
    D.COMBO_ONLY, D.DRILL = True, "backstep_r1"
    try:
        F = fight(Mv())
        r = tick(F, -1, None, h=2.35, v=2.8)
        check(f"2.35 m에서 2.8 m/s로 다가옴 → 다음 틱 전 2.3 m: B, R1은 0.6 s 뒤, 이어짐 상관없음 ({bs(F)})",
              r == D.CONT and bs(F) and abs(bs(F)[0][1] - D.SWING_BS_R1) < 0.03 and bs(F)[0][2] is None)
        check("같은 놈 1.5 s 안엔 다시 안 함", tick(F, -1, None, h=2.2, v=2.8, now=101.0) is None and len(bs(F)) == 1)
        check("1.5 s 지나면 다시", tick(F, -1, None, h=2.2, v=2.8, now=101.6) == D.CONT and len(bs(F)) == 2)
        F = fight(Mv())
        now = time.time()
        F._hs = {7: [(now - 0.3, 5.0), (now - 0.2, 4.4), (now - 0.1, 3.8)]}
        c = NS(ptr=7, npc_param=255010, x=0.0, y=0.0, z=3.2, anim=-1, hp=80)
        r = D.rule_swing_backstep(F, NS(s=NS(player=NS(sp=98)), c=c, h=3.2, a=-1, age=None, now=100.0))
        check(f"6 m/s로 뛰어옴 (시범 291 s 255010), 3.2 m → 0.15 s 뒤 2.3 m: 장전해서 B ({bs(F)})", r == D.CONT and len(bs(F)) == 1)
        F = fight(Mv())
        F._hs = {7: [(now - 0.3, 6.2), (now - 0.2, 5.6), (now - 0.1, 5.0)]}
        r = D.rule_swing_backstep(F, NS(s=NS(player=NS(sp=98)), c=NS(**{**c.__dict__, "z": 4.4}), h=4.4, a=-1, age=None, now=100.0))
        check("6 m/s, 4.4 m → 0.35 s 뒤라 아직", r is None and not bs(F))
        v = D._closing(fight(Mv()), c, 3.2)
        check(f"표본 하나뿐·예전 기록 없음 → 속도 0 ({v})", v == 0.0)
        # 장전 ([MoKa] 11-03 "몇가지 경우를 준비하고 … 그 중 하나를 작동") — 장전 중 보는 snap이 차례로 돌려줌
        for name, seq, want in (("그대로 옴 → 2.3 m 안 → B", [2.4, 2.25], "near"),
                                ("휘두르기 시작 → 바로 B", [2.4, ("swing", 2.38)], "swing"),
                                ("멈추고 물러남 → 취소", [2.6, 3.0], "cancel")):
            mv = Mv()
            frames = iter(seq)
            def snap(r, frames=frames):
                x = next(frames, None)
                if x is None:
                    return None
                anim, d = x if isinstance(x, tuple) else (-1, x)
                return NS(player=NS(x=0.0, y=0.0, z=0.0, sp=98, heading=0.0), c=NS(ptr=7, npc_param=254000, x=0.0, y=0.0, z=d,
                                                                                     anim=3000 if anim == "swing" else -1, hp=80))
            mv.snap, mv.find = snap, (lambda s, ptr: s.c if s is not None else None)
            F = fight(mv)
            r = tick(F, -1, None, h=2.6, v=3.0)              # (2.6−2.3)/3.0 = 0.1 s ≤ 0.12 → 장전
            ok = (r == D.CONT and len(bs(F)) == 1) if want != "cancel" else (r is None and not bs(F))
            check(f"장전 2.6 m 3 m/s: {name} ({bs(F)})", ok)
        F = fight(Mv())
        check("3.0 m 다가옴 → 아직", tick(F, -1, None, h=3.0, v=2.0) is None and F.mv.calls == [])
        F = fight(Mv())
        check("2.0 m 서 있음 (휘두름 없음) → 안 함 (표대로)", tick(F, -1, None, h=2.0, v=0.0) is None and F.mv.calls == [])
        F = fight(Mv())
        r = tick(F, 3000, 0.2, h=1.6)
        check(f"3000 시작 +0.2 s 1.6 m → B ({bs(F)})", r == D.CONT and len(bs(F)) == 1)
        # P-130 ([MoKa] 11-04 "Yes, guard"): 시범 267.9 s의 2.2 m도 이제 가드 — 11-04 집계 1.8 m 넘어 B는 3 피함 · 9 맞음
        F = fight(Mv())
        r = tick(F, 3000, 0.2)
        check(f"P-130: 3000 시작 +0.2 s 2.2 m → B 안 누르고 가드 ({F.mv.calls})", r is None and not bs(F) and ("guard", True) in F.mv.calls)
        F = fight(Mv())
        check("0.9 m 휘두름 시작 → 안 함 (160317 −160)", tick(F, 3003, 0.0, h=0.9) is None and F.mv.calls == [])
        F = fight(Mv())
        check("휘두름 +0.5 s → 늦음, 안 함 (시범 183 · 198 · 206 s 맞음)", tick(F, 3002, 0.5, h=1.6) is None and F.mv.calls == [])
        F = fight(Mv())
        check("뛰어드는 찌르기 3005 → 안 함 (막기에 맡김)", tick(F, 3005, 0.1, v=5.0) is None and F.mv.calls == [])
        F = fight(Mv())
        check("큰 병사 255010 3000 +0.09 s 2.3 m → 안 함 (173404 −385)", tick(F, 3000, 0.09, h=2.3, npc=255010) is None and F.mv.calls == [])
        F = fight(Mv())
        check("255010 다가옴 1.9 m → B (160734 피함+맞힘)", tick(F, -1, None, h=1.9, npc=255010, v=2.0) == D.CONT and len(bs(F)) == 1)
        F = fight(Mv())
        check("기력 30 → 안 함", tick(F, 3000, 0.2, h=1.6, sp=30) is None and F.mv.calls == [])
        F = fight(Mv(lock="none"))
        check("락온 없음 → 안 함", tick(F, 3000, 0.2, h=1.6) is None and not bs(F))
        D.DRILL = "roll_r1"
        F = fight(Mv())
        check("구르기 드릴 중엔 안 함", tick(F, 3000, 0.2, h=1.6) is None and F.mv.calls == [])
        D.COMBO_ONLY, D.DRILL = False, None
        F = fight(Mv())
        check("콤보 시험 아니면 안 함 (평소 싸움 그대로)", tick(F, 3000, 0.2, h=1.6) is None and F.mv.calls == [])
    finally:
        D.COMBO_ONLY, D.DRILL = saved


if __name__ == "__main__":
    main()
