"""field.retreat offline test — shield up while an awake foe is still close (ROADMAP P-7(c)). No game.

  python field_retreat_test.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World, make_field
from souls import field as F


def test_retreat_mode() -> None:
    w = World(player=(0.0, 0.0, 0.0))
    shield = w.add(10, 110, 255000, (1.85, 0.0, 0.0), anim=3000)
    assert F.Field._retreat_mode(w.snapshot()) == "guard"                 # P-7(c): 1.85 m, attacking
    shield.anim = -1
    assert F.Field._retreat_mode(w.snapshot()) == "guard"                 # awake-but-standing still counts (not downed)
    w.move(10, (6.0, 0.0, 0.0))
    assert F.Field._retreat_mode(w.snapshot()) == "walk"                  # far enough
    w.move(10, (1.5, 0.0, 0.0))
    shield.anim = 9010
    assert F.Field._retreat_mode(w.snapshot()) == "walk"                  # downed
    shield.anim, shield.hp = 3000, 0
    assert F.Field._retreat_mode(w.snapshot()) == "walk"                  # dead
    shield.hp = 100
    w.move(10, (1.5, -4.0, 0.0))
    assert F.Field._retreat_mode(w.snapshot()) == "walk"                  # other level
    print("ok  retreat: guard while an awake foe is within 4 m at our level, walk otherwise")


def test_retreat_uses_mode_fn() -> None:
    w = World(player=(0.0, 0.0, 0.0))
    f = make_field(w)
    seen = {}

    def walk_path(path, nm, mode="walk", stop=None, **kw):
        seen["mode"] = mode
        return "stopped"

    f.mv.walk_path = walk_path
    nm = type("Nm", (), {"find_path": lambda self, a, b: [a, (5.0, 0.0, 0.0), b]})()
    assert f.retreat(nm, (10.0, 0.0, 0.0)) == "stopped"
    assert seen["mode"] is F.Field._retreat_mode, seen
    print("ok  retreat passes the guard/walk mode function to walk_path")


if __name__ == "__main__":
    test_retreat_mode()
    test_retreat_uses_mode_fn()
    print("전부 통과")
