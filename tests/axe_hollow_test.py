"""Ramp #4 (254001, two-handed axe hollow): the 3004 that follows a blocked 3003 lands ~1.7 s after it starts. At 1.6 s the
duel used to call it idle (prep_linger, SWING_S) and hit first — −118 in ramp runs r1·r4 ([MoKa] 2026-10-01: "가드를 너무
일찍 내렸음"). Now the shield stays up until it lands; the sword hollow (254000) keeps its old behaviour.

  python tests/axe_hollow_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import duel_golden_test as G
from field_fakes import World
from souls import duel as D
from souls import foes, weapons


class Reflex(G.Reflex):
    def __init__(self, age, trace):
        super().__init__(False, trace)
        self.age = age

    def attack_age(self, ptr):
        return self.age


def first_action(npc: int, anim: int, age: float) -> str:
    trace = []
    w = World(player=(0.0, -49.4, 0.0), sp=99)
    w.player.heading = -math.pi
    c = w.add(2, 0x1002, npc, (0.0, -49.4, 0.9), hp=75, max_hp=75, anim=anim)
    c.heading = 0.0
    mv = G.Mv(w, trace)
    mv.tm.grip = lambda: 1
    n = {"t": 0}

    def cancel():
        n["t"] += 1
        return n["t"] > 1

    saved = D.time.sleep
    D.time.sleep = lambda s: None
    try:
        D.duel(mv, weapons.BATTLE_AXE, 2, None, log=lambda *a: None, cancel=cancel, reflex=Reflex(age, trace), style="guard")
    finally:
        D.time.sleep = saved
    return next(x[0] for x in trace if x[0] not in ("log", "face", "move"))


def main() -> None:
    assert foes.of(254001).windup == (3004,) and foes.of(254001).windup_act_s == 1.0
    # the r1/r4 moment: 3004 at 1.65 s, 0.9 m, SP 99 — shield, not a strike
    assert first_action(254001, 3004, 1.65) in ("guard", "pad_guard"), first_action(254001, 3004, 1.65)
    assert first_action(254001, 3004, 1.2) in ("guard", "pad_guard")
    # sword hollow in the same spot: unchanged (it lingers in 3004 past SWING_S and gets hit first)
    assert first_action(254000, 3004, 1.65) == "light", first_action(254000, 3004, 1.65)
    print("ok  #4 axe hollow: shield held through the late 3004; sword hollow unchanged")


if __name__ == "__main__":
    main()
