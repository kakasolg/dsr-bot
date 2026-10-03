"""잠든 적 첫 타 강공 오프라인 테스트 (P-39, [MoKa] 2026-10-03) — 배틀 액스로 이 싸움 내내 가만히 누워 있던(애니 −1, 안 움직임,
안 맞음) 적을 처음 칠 때, 강공 한 방에 죽을 HP면 한손이어도 강공. 수용소 위층 망자 둘: 약공 2연타가 5 남겨 둘이 같이 침.

  python tests/duel_sleeper_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from duel_wall_heavy_test import run
from souls import duel as D
from souls import weapons


def seen(s):
    """Run with SLEEP_SEEN_S = s (0: the first tick already counts as having watched it long enough)."""
    class _Ctx:
        def __enter__(self):
            self.old = D.SLEEP_SEEN_S
            D.SLEEP_SEEN_S = s

        def __exit__(self, *a):
            D.SLEEP_SEEN_S = self.old
    return _Ctx()


def test_sleeper_heavy() -> None:
    with seen(0.0):
        mv, logs = run(weapons.BATTLE_AXE, wall=3.0, npc=250022, hp=69, grip=1, ticks=1)
    assert mv.heavies == [2] and not mv.lights, (mv.heavies, mv.lights, logs[-5:])
    assert any("잠든 적" in l for l in logs), logs[-5:]
    print("ok  sleeping hollow HP 69, one-handed, open ground → heavy")


def test_too_tough_light() -> None:
    with seen(0.0):
        mv, logs = run(weapons.BATTLE_AXE, wall=3.0, npc=250022, hp=D.SLEEPER_HEAVY_HP + 1, grip=1, ticks=1)
    assert mv.lights and not mv.heavies, (mv.heavies, mv.lights)
    print(f"ok  HP {D.SLEEPER_HEAVY_HP + 1} (one heavy won't kill) → light")


def test_not_watched_long_enough_light() -> None:
    mv, logs = run(weapons.BATTLE_AXE, wall=3.0, npc=250022, hp=69, grip=1, ticks=1)   # default 1.0 s: tick 1 is too soon
    assert mv.lights and not mv.heavies, (mv.heavies, mv.lights)
    print("ok  struck on the first tick (not watched SLEEP_SEEN_S yet) → light as before")


def test_awake_light() -> None:
    with seen(0.0):
        mv, logs = run(weapons.BATTLE_AXE, wall=3.0, npc=250022, hp=69, grip=1, ticks=4, anim=3000)
    assert not mv.heavies, (mv.heavies, logs[-5:])
    print("ok  foe animating (awake) → no sleeper heavy")


def test_hurt_light() -> None:
    from field_fakes import World                            # already hit once (HP below max) → not asleep
    import duel_wall_heavy_test as W
    old = W.World
    W.World = lambda **k: _Hurt(old(**k))
    try:
        with seen(0.0):
            mv, logs = run(weapons.BATTLE_AXE, wall=3.0, npc=250022, hp=69, grip=1, ticks=1)
    finally:
        W.World = old
    assert mv.lights and not mv.heavies, (mv.heavies, mv.lights)
    print("ok  foe below max HP (already hit) → light")


class _Hurt:
    def __init__(self, w):
        self.w = w

    def add(self, *a, **k):
        k["max_hp"] = k.get("hp", 69) + 10
        return self.w.add(*a, **k)

    def __getattr__(self, name):
        return getattr(self.w, name)


def test_basic_and_other_weapon_light() -> None:
    old = D.HEAVY
    D.HEAVY = False                                          # run.py --basic
    try:
        with seen(0.0):
            mv, _ = run(weapons.BATTLE_AXE, wall=3.0, npc=250022, hp=69, grip=1, ticks=1)
        assert not mv.heavies, mv.heavies
    finally:
        D.HEAVY = old
    with seen(0.0):
        mv, _ = run(weapons.BROADSWORD, wall=3.0, npc=250022, hp=69, grip=1, ticks=1)
    assert not mv.heavies and mv.lights, (mv.heavies, mv.lights)
    print("ok  --basic or a weapon without heavy_vertical → light")


if __name__ == "__main__":
    test_sleeper_heavy()
    test_too_tough_light()
    test_not_watched_long_enough_light()
    test_awake_light()
    test_hurt_light()
    test_basic_and_other_weapon_light()
    print("전부 통과")
