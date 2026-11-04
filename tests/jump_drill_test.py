"""P-121 jump drill (run.py --drill jump_r2): jump attack when the foe will be 2.4–4.3 m away as it lands, or in a whiff's recovery (no game).
  python tests/jump_drill_test.py

[MoKa] 2026-11-03: "점프 공격으로 넘어가자" — 중거리에서 순간 전진, 헛친 뒤 후딜레이에 파고듦, 헛치면 후딜레이가 길다.
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


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


class Mv:
    def __init__(self, lock="target"):
        self.calls, self.lock = [], lock

    def lock_state(self, ptr):
        return self.lock

    def combo(self, name, s, c, nm=None, need_back=0.0, need_front=3.0, r1_at=None, swing=None):
        self.calls.append((name, need_front))
        return NS(presses=1, skipped=None, dmg=40, taken=0, dead=False, my_anims=[(0.0, 303600)], e_anims=[(0.6, 9910)])


def fight(mv):
    F = NS(mv=mv, nm=None, log=lambda *_: None, events=lambda *_a, **_k: None, notes=[])
    F.note = lambda what, *_a: F.notes.append(what)
    F.record = lambda hit: None
    F.killed_if = lambda dead: "killed" if dead else D.CONT
    return F


def tick(F, h, anim=-1, age=None, v=0.0, sp=98, npc=254000, now=100.0):
    c = NS(ptr=7, npc_param=npc, x=0.0, y=0.0, z=h, anim=anim, hp=80)
    F._hv = {7: (time.time() - 0.1, h + v * 0.1, v)}
    T = NS(s=NS(player=NS(sp=sp)), c=c, h=h, a=anim, age=age, now=now, dy=0.0)
    return D.rule_jump_drill(F, T)


def jumps(F):
    return [x for x in F.mv.calls if x[0] == "jump_r2"]


def main() -> None:
    saved = D.DRILL
    D.DRILL = "jump_r2"
    try:
        F = fight(Mv())
        check("서 있는 놈 3.5 m → 점프, 앞 바닥 4.3 m 확인", tick(F, 3.5) == D.CONT and jumps(F) == [("jump_r2", D.JUMP_FRONT)])
        check("같은 놈 2 s 안엔 다시 안 함", tick(F, 3.5, now=101.0) is None and len(jumps(F)) == 1)
        F = fight(Mv())
        check("서 있는 놈 5.0 m → 아직 (기다림)", tick(F, 5.0) is None and not jumps(F))
        F = fight(Mv())
        check("서 있는 놈 2.0 m → 너무 가까움 (넘어 감)", tick(F, 2.0) is None and not jumps(F))
        F = fight(Mv())
        check("4.0 m에서 1 m/s로 다가옴 → 안 함 (191414 가속해 넘어감)", tick(F, 4.0, v=1.0) is None and not jumps(F))
        F = fight(Mv())
        check("서 있는 놈 2.3 m → 너무 가까움", tick(F, 2.3) is None and not jumps(F))
        F = fight(Mv())
        check("휘두르는 중 (3000 +0.3 s, 판정 전) → 안 함", tick(F, 3.0, anim=3000, age=0.3) is None and not jumps(F))
        F = fight(Mv())
        r = tick(F, 3.8, anim=3000, age=1.3, v=1.0)      # 3000 판정 0.87–1.03 s 지남 (헛침 땐 다가와도 함)
        check(f"헛침 3000 +1.3 s (판정 끝 지남) 3.8 m → 점프 ({jumps(F)})", r == D.CONT and len(jumps(F)) == 1)
        F = fight(Mv(lock="none"))
        check("락온 없음 → 안 함", tick(F, 3.5) is None and not jumps(F))
        F = fight(Mv())
        check("기력 30 → 안 함", tick(F, 3.5, sp=30) is None and not jumps(F))
        D.DRILL = "backstep_r1"
        F = fight(Mv())
        check("다른 드릴이면 안 함", tick(F, 3.5) is None and not jumps(F))
    finally:
        D.DRILL = saved


if __name__ == "__main__":
    main()
