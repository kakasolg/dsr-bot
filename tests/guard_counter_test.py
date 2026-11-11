"""방패에 맞으면 바로 약공 (duel.rule_guard_counter, [MoKa] 2026-11-08 "방패에 뭔가 부딪히면, 자동으로 약공이 나가야").
Fakes only — no game, no pad.  python tests/guard_counter_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

from types import SimpleNamespace as NS

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

from souls import duel as D
from souls import moves as M
from souls import reflex as R


def chr_(ptr, x, z, anim, y=0.0, hp=75, npc=254010):
    return NS(ptr=ptr, x=x, y=y, z=z, anim=anim, hp=hp, npc_param=npc)


def setup(my_anim, foes, sp=100):
    p = NS(x=0.0, y=0.0, z=0.0, anim=my_anim, sp=sp, hp=1000)
    s = NS(player=p, hostile=lambda r: [c for c in foes if M.horiz(p, c) <= r])
    lights, logs = [], []
    mv = NS(weapon=NS(reach=1.6, sp_min=30), light=lambda s_, c, n=1: lights.append((c.ptr, n)) or M.Hit("light", presses=1))
    F = NS(ptr=foes[0].ptr if foes else 1, weapon=mv.weapon, mv=mv, reflex=R.Reflex(mv),
           record=lambda h: None, note=lambda *a: None, log=logs.append, killed_if=lambda dead: "killed" if dead else D.CONT)
    T = NS(p=p, s=s)
    return F, T, lights, logs


def main() -> None:
    sw = next(iter(a for a in (3000, 3005, 3010) if a in M.ATTACK))
    # 1) Claymore guard hit (20140) from the target swinging at 1.2 m → one light at once
    F, T, lights, _ = setup(20140, [chr_(5, 0.0, -1.2, sw)])
    r = D.rule_guard_counter(F, T)
    assert r == D.CONT and lights == [(5, 1)], (r, lights)
    print("ok  20140 (Claymore) hit by the target at 1.2 m → light ×1")
    # 2) same block, next tick → no second press; leave 140, hit again → presses again (each block once)
    r = D.rule_guard_counter(F, T)
    assert r is None and lights == [(5, 1)], (r, lights)
    T.p.anim = -1; D.rule_guard_counter(F, T)
    T.p.anim = 140; D.rule_guard_counter(F, T)
    assert lights == [(5, 1), (5, 1)], lights
    print("ok  one light per block: none on the next tick of the same block, again on the next block (Battle Axe 140)")
    # 2b) 205219 구역 1: the hitter already bounced off the shield (3500) on the guard-hit tick → still a light
    F, T, lights, _ = setup(140, [chr_(5, 0.0, -0.9, 3500)])
    assert D.rule_guard_counter(F, T) == D.CONT and lights == [(5, 1)], lights
    print("ok  hitter already bounced (3500) on the guard-hit tick → light")
    # 3) arrow on the shield: nobody swinging within reach → no light
    F, T, lights, logs = setup(140, [chr_(7, 0.0, -9.0, sw, npc=255040)])
    assert D.rule_guard_counter(F, T) is None and not lights and "닿는 거리" in logs[-1], (lights, logs)
    print("ok  shot on the shield (shooter 9 m) → no light")
    # 4) MoKa 11-08 "첫 번째 방패 부딪혔을때 반응해서 약공": 225520 SP 29 → light now; stamina 0 → the game can't swing
    F, T, lights, logs = setup(20140, [chr_(5, 0.0, -1.2, sw)], sp=29)
    assert D.rule_guard_counter(F, T) == D.CONT and lights == [(5, 1)], lights
    F, T, lights, logs = setup(20140, [chr_(5, 0.0, -1.2, sw)], sp=0)
    assert D.rule_guard_counter(F, T) is None and not lights, lights
    print("ok  stamina 29 (225520, under the axe's sp_min 55) → light; stamina 0 → no light")
    # 5) another foe swinging next to us → still a light, at the one we fight ([MoKa] "모든 공격에서 기본")
    F, T, lights, logs = setup(20140, [chr_(5, 0.0, -1.2, sw), chr_(6, 1.0, -0.5, sw)])
    assert D.rule_guard_counter(F, T) == D.CONT and lights == [(5, 1)], (lights, logs)
    print("ok  a second foe swinging within 2.5 m → light anyway, at the target")
    # 6) not a guard hit (own attack 253000, standing -1) → nothing
    for a in (253000, -1, 690):
        F, T, lights, _ = setup(a, [chr_(5, 0.0, -1.2, sw)])
        assert D.rule_guard_counter(F, T) is None and not lights, (a, lights)
    print("ok  own attack / standing / backstep → rule does nothing")
    # 7) it sits right after prep_reflex, before every acting rule
    i = D.RULES.index(D.rule_guard_counter)
    assert D.RULES[i - 1] is D.prep_reflex, D.RULES[:i + 1]
    print("ok  RULES: prep_reflex → rule_guard_counter (before reflex's block-only tick)")
    # 8) outside duel: Reflex.tick itself counters (walking hold, defend in place) — once per block
    F, T, lights, _ = setup(140, [chr_(5, 0.0, -1.2, sw)])
    rf = F.reflex
    assert rf.tick(T.s) is True and lights == [(5, 1)] and rf.gc_last[3] is None, (lights, rf.gc_last)
    assert rf.guard_counter(T.s) is None          # the same block: decided already
    assert lights == [(5, 1)], lights
    print("ok  Reflex.tick: guard hit → light (same block once) — every caller of tick, not only duel")


if __name__ == "__main__":
    main()
