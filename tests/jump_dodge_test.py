"""P-121 jump drill: a close swing gets a plain backstep (no R1) so its whiff leaves room for the jump; no backstab while drilling (no game).
  python tests/jump_dodge_test.py

[MoKa] 2026-11-03: "점프 드릴이라고 하면서 뒤잡만 하고 있네" (190741: 붙은 놈 → 드릴 포기 → 표대로 → 뒤잡기).
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import duel as D


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def fight():
    mv = NS(calls=[])
    mv.backstep = lambda: mv.calls.append("B")
    F = NS(mv=mv, nm=None, log=lambda *_: None, events=lambda *_a, **_k: None, note=lambda *_a: None)
    return F


def tick(F, anim, age, h, npc=254000, now=100.0, sp=98, rule=None):
    c = NS(ptr=7, npc_param=npc, x=0.0, y=0.0, z=h, anim=anim, hp=80)
    return (rule or D.rule_jump_dodge)(F, NS(s=NS(player=NS(heading=0.0, sp=sp)), c=c, h=h, a=anim, age=age, now=now))


def main() -> None:
    saved = D.DRILL
    D.DRILL = "jump_r2"
    try:
        F = fight()
        check("점프 드릴 · 망자 3000 시작 +0.1 s 1.8 m → 백스텝만", tick(F, 3000, 0.1, 1.8) == D.CONT and F.mv.calls == ["B"])
        check("1.5 s 안엔 다시 안 함", tick(F, 3000, 0.1, 1.8, now=101.0) is None and F.mv.calls == ["B"])
        F = fight()
        check("휘두름 +0.5 s (늦음) → 안 함", tick(F, 3000, 0.5, 1.8) is None and F.mv.calls == [])
        F = fight()
        check("0.9 m → 안 함 (못 벗어남)", tick(F, 3003, 0.0, 0.9) is None and F.mv.calls == [])
        F = fight()
        check("1.4 m → 안 함 (225538 1.4 m 백스텝 −83)", tick(F, 3000, 0.0, 1.4) is None and F.mv.calls == [])
        F = fight()
        check("255010 휘두름 → 안 함", tick(F, 3000, 0.1, 1.8, npc=255010) is None and F.mv.calls == [])
        F = fight()
        check("서 있음 → 안 함", tick(F, -1, None, 1.8) is None and F.mv.calls == [])
        F = fight()
        check(f"기력 {D.JUMP_DODGE_SP - 1} → 백스텝 안 함 (224853 헛친 틈에 기력 21)",
              tick(F, 3000, 0.1, 1.8, sp=D.JUMP_DODGE_SP - 1) is None and F.mv.calls == [])
        F = fight()
        check("같은 놈 기력 모자라 건너뛴 뒤 기력 차면 바로 백스텝", tick(F, 3000, 0.1, 1.8, sp=40) is None
              and tick(F, 3000, 0.15, 1.8, sp=98, now=100.05) == D.CONT and F.mv.calls == ["B"])
        F = fight()
        F.mv.guard = lambda on: F.mv.calls.append(("guard", on))
        F.mv.face = lambda s, c: True
        check("기력 40 · 서 있음 → 방패 내리고 섬", tick(F, -1, None, 1.8, sp=40, rule=D.rule_jump_save) == D.CONT
              and F.mv.calls == [("guard", False)])
        F = fight()
        check("기력 40 · 휘두름 → 기력 모으기 안 함 (막기에 맡김)", tick(F, 3000, 0.1, 1.8, sp=40, rule=D.rule_jump_save) is None)
        F = fight()
        check("기력 98 → 기력 모으기 안 함", tick(F, -1, None, 1.8, sp=98, rule=D.rule_jump_save) is None)
        T = NS(backstab_chance=True)
        names = {r.__name__ for r in D.RULES}
        check("뒤잡기 규칙은 RULES에 그대로 (이름)", {"rule_backstab", "rule_backstab_swing", "prep_backstab_chance"} <= names)
        bs = next(r for r in D.RULES if r.__name__ == "rule_backstab")
        check("드릴 중 뒤잡기 → 안 함", bs(NS(), T) is None)
        D.DRILL = "backstep_r1"
        F = fight()
        check("다른 드릴이면 안 함", tick(F, 3000, 0.1, 1.8) is None and F.mv.calls == [])
        check("다른 드릴이면 기력 모으기도 안 함", tick(F, -1, None, 1.8, sp=40, rule=D.rule_jump_save) is None)
    finally:
        D.DRILL = saved


if __name__ == "__main__":
    main()
