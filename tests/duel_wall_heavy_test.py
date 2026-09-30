"""벽·좁은 통로 강공 오프라인 테스트 — 배틀 액스(heavy_vertical)는 나나 적이 NavMesh 경계(벽)에서 WALL_R 안이면 약공 대신 강공.
[MoKa] 2026-09-28: 강공이 수직이라 가로 휘두르기처럼 벽에 안 걸림, 배틀 액스만의 특징. 산적은 강인도가 약해 새로 보인 상황.
[MoKa] 2026-09-30: 양손 잡기일 때만 (duel._slam). 방패를 든 적에게도 양손 강공 — 가드를 깸, 한손이면 발차기.

  python tests/duel_wall_heavy_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from duel_shadow_test import DuelMv          # also sets BACKSTAB_ONLY / CIRCLE_MAX_SWEEPS off so the attack rule is reached
from field_fakes import World
from souls import duel as D
from souls import moves as M
from souls import weapons


class Mv(DuelMv):
    def __init__(self, world, target_ptr):
        super().__init__(world, target_ptr)
        self.heavies = []

    def heavy(self, s, c):
        self.heavies.append(c.ptr)
        return M.Hit("heavy", presses=1)


class Nm:
    def __init__(self, wall):
        self.wall = wall

    def border_dist(self, x, y, z, dy=2.0):
        return self.wall

    def __getattr__(self, name):                 # anything else the duel asks the NavMesh: "don't know"
        return lambda *a, **k: None


def run(weapon, wall, sp=90, ticks=8, npc=254000, hp=75, grip=3, anim=-1):
    w = World(player=(0.0, -49.4, 0.0), sp=sp, max_sp=98, hp=698)
    w.add(2, 0x1018, npc, (0.0, -49.4, 1.2), anim=anim, hp=hp, max_hp=hp)
    mv = Mv(w, 2)
    g = {"now": grip}
    mv.tm.grip = lambda: g["now"]                # 3 = two hands, 1 = one
    mv.pad.two_hand_right = lambda: (mv.pad.calls.append(("two_hand",)), g.update(now={1: 3, 3: 1}.get(g["now"], g["now"])))
    n = {"k": 0}

    def cancel():
        n["k"] += 1
        return n["k"] > ticks
    logs = []
    D.duel(mv, weapon, 2, Nm(wall), log=logs.append, cancel=cancel, reflex=None, gen=0, events=lambda *a, **k: None)
    return mv, logs


def test_wall_heavy() -> None:
    mv, logs = run(weapons.BATTLE_AXE, wall=0.6)
    assert mv.heavies and not mv.lights, (mv.heavies, mv.lights, logs[-5:])
    assert any("강공(수직)" in l for l in logs), logs[-5:]
    print(f"ok  Battle Axe, wall 0.6 m → heavy ×{len(mv.heavies)}, no light")


def test_open_ground_light() -> None:
    mv, logs = run(weapons.BATTLE_AXE, wall=3.0)
    assert mv.lights and not mv.heavies, (mv.heavies, mv.lights, logs[-5:])
    print("ok  Battle Axe, wall 3.0 m → light as before")


def test_low_sp_light() -> None:
    mv, logs = run(weapons.BATTLE_AXE, wall=0.6, sp=D.WALL_HEAVY_SP - 1)
    assert not mv.heavies, (mv.heavies, logs[-5:])
    print("ok  Battle Axe by a wall with SP below WALL_HEAVY_SP → no heavy")


def test_wall_before_backstab_and_kick() -> None:
    old = D.CIRCLE_MAX_SWEEPS
    D.CIRCLE_MAX_SWEEPS = 3                                              # backstab on (hollows circle behind)
    try:
        mv, logs = run(weapons.BATTLE_AXE, wall=0.6)
        assert mv.heavies and not any("뒤잡기" in l and "→" in l for l in logs), logs[-5:]
    finally:
        D.CIRCLE_MAX_SWEEPS = old
    print("ok  by a wall the heavy comes before the backstab")


def test_shield_combo() -> None:
    mv, logs = run(weapons.BATTLE_AXE, wall=0.6, npc=255010, hp=85, ticks=1)   # two hands already: heavy → light, no toggle
    assert mv.heavies == [2] and mv.lights == [2] and not mv.kicks, (mv.heavies, mv.lights, mv.kicks, logs[-5:])
    assert ("two_hand",) not in mv.pad.calls
    mv, logs = run(weapons.BATTLE_AXE, wall=0.6, npc=255010, hp=85, grip=1, ticks=1)   # one hand: switch to two, then heavy → light
    assert mv.pad.calls.count(("two_hand",)) == 1 and mv.heavies == [2] and mv.lights == [2], (mv.pad.calls, mv.heavies, mv.lights)
    assert mv.tm.grip() == 3 and any("양손으로" in l for l in logs), logs[-5:]
    mv, logs = run(weapons.BATTLE_AXE, wall=0.6, npc=255010, hp=85, grip=None, ticks=1)   # grip unreadable: no blind toggle, light
    assert ("two_hand",) not in mv.pad.calls and not mv.heavies, (mv.pad.calls, mv.heavies)
    mv, logs = run(weapons.BATTLE_AXE, wall=3.0, npc=255010, hp=85, grip=1, ticks=1)   # no wall: kick as before
    assert mv.kicks and not mv.heavies and ("two_hand",) not in mv.pad.calls, (mv.kicks, mv.heavies)
    print("ok  shield soldier by a wall: two hands (switch if one-handed) → heavy → light; unknown grip or no wall → no heavy")


def test_one_handed_light() -> None:
    mv, logs = run(weapons.BATTLE_AXE, wall=0.6, grip=1)
    assert mv.lights and not mv.heavies, (mv.heavies, mv.lights, logs[-5:])
    mv, logs = run(weapons.BATTLE_AXE, wall=0.6, grip=None)              # grip unreadable → treated as one hand
    assert not mv.heavies, (mv.heavies, logs[-5:])
    print("ok  one-handed (or unknown grip) by a wall → light, no heavy")


def test_other_weapon_unchanged() -> None:
    mv, logs = run(weapons.BROADSWORD, wall=0.6)
    assert not mv.heavies and mv.lights, (mv.heavies, mv.lights)
    print("ok  Broadsword by a wall → light (heavy_vertical is per weapon)")


if __name__ == "__main__":
    test_wall_heavy()
    test_open_ground_light()
    test_low_sp_light()
    test_wall_before_backstab_and_kick()
    test_shield_combo()
    test_one_handed_light()
    test_other_weapon_unchanged()
    print("전부 통과")
