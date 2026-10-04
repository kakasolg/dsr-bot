"""천천히 걷기 오프라인 테스트 — Field.careful_walk_to ([MoKa] 2026-10-01: 성벽 마을 #4 이동 "천천히 가고, 대기하면서 한 명씩 끌어당겨야 함").

  오는 놈(깨어 움직임, 12 m 안) → 그 자리에서 기다려 싸움 · 던질 거리 안 서 있는 놈 → 나이프로 하나 끌어와 싸움 ·
  아무도 없으면 4 m만 걷고 멈춰 지켜봄 · 도착하면 끝

  python tests/careful_walk_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World, make_field
from souls import field as F
from souls import duel as D


class Nm:
    def find_path(self, a, b):
        n = max(2, int(math.dist(a, b) / 1.0) + 1)
        return [tuple(a[k] + (b[k] - a[k]) * i / (n - 1) for k in range(3)) for i in range(n)]


def setup(world):
    f = make_field(world)
    f.events = lambda *a, **k: None
    f.alive = lambda: True
    f.wait_escape = lambda: None
    f.estus_left = lambda: 5
    f.recover = lambda *a, **k: True
    seen = []

    def fight(ptr, nm, tag, wait_far=False, limit=45.0, **kw):
        seen.append(("fight", ptr, wait_far))
        world.chars[ptr].hp = 0
        return D.DuelResult("killed")

    def lure(ptr, spawn, nm, tag, arena=None, lure_at=None):
        seen.append(("lure", ptr))
        world.chars[ptr].anim = 3000
        return "lured"

    def walk(path, nm, tag, mode="walk", **kw):
        seen.append(("walk", round(sum(math.dist(a, b) for a, b in zip([(world.player.x, world.player.y, world.player.z)] + path, path)), 1), mode))
        world.player.x, world.player.y, world.player.z = path[-1]
        return "arrived"
    f.fight, f.lure, f.walk = fight, lure, walk
    return f, seen


def test_order() -> None:
    old = F.CAREFUL_LOOK_S
    F.CAREFUL_LOOK_S = 0.0
    try:
        w = World(player=(0.0, -13.4, 0.0), hp=793)
        w.add(2, 0x1018, 254010, (0.0, -13.4, 8.0), anim=3003)          # awake, coming
        w.add(3, 0x1019, 250000, (4.0, -13.4, 10.0), anim=-1)           # idle, 10.8 m — pull it
        w.add(4, 0x101A, 254010, (0.0, -13.4, 40.0), anim=-1)           # far — not yet
        w.add(5, 0x101B, 254010, (3.0, -6.0, 5.0), anim=-1)             # another level — never
        f, seen = setup(w)
        r = f.careful_walk_to((0.0, -13.4, 30.0), Nm(), "#4 이동")
        assert r == "arrived", (r, seen)
        assert seen[0] == ("fight", 2, True), seen                       # the coming one first, waited for
        assert seen[1] == ("lure", 3) and seen[2] == ("fight", 3, True), seen
        walks = [x for x in seen if x[0] == "walk"]
        assert walks and all(x[1] <= F.CAREFUL_LEG + 1.01 and x[2] == "walk" for x in walks), walks
        k = seen.index(("lure", 4)) if ("lure", 4) in seen else None
        assert k is not None and any(x[0] == "walk" for x in seen[:k]), "the far one is pulled only after walking closer"
        assert ("lure", 5) not in seen, "a foe on another level must not be pulled"
    finally:
        F.CAREFUL_LOOK_S = old
    print(f"ok  careful_walk_to: coming one fought in place → idle one in range pulled → {len(walks)} legs ≤ {F.CAREFUL_LEG} m "
          f"(walk, not run) → far one pulled once closer; other level left alone")


def test_no_knife_walks_on() -> None:
    old = F.CAREFUL_LOOK_S
    F.CAREFUL_LOOK_S = 0.0
    try:
        w = World(player=(0.0, -13.4, 0.0), hp=793)
        w.add(3, 0x1019, 250000, (4.0, -13.4, 10.0), anim=-1)
        f, seen = setup(w)
        f.lure = lambda *a, **k: (seen.append(("lure", 3)), "no_knife")[1]
        r = f.careful_walk_to((0.0, -13.4, 6.0), Nm(), "#4 이동")
        assert r == "arrived" and seen.count(("lure", 3)) == 1, (r, seen)
    finally:
        F.CAREFUL_LOOK_S = old
    w2 = World(player=(0.0, -13.4, 0.0), hp=793)
    w2.add(3, 0x1019, 255002, (4.0, -13.4, 10.0), anim=-1)              # crossbowman on a ledge: no throw spot
    f2, seen2 = setup(w2)
    f2.lure = lambda *a, **k: (seen2.append(("lure", 3)), "no_spot")[1]
    f2.careful_walk_to((0.0, -13.4, 3.0), Nm(), "#4 이동")
    f2.careful_walk_to((0.0, -13.4, 6.0), Nm(), "#5 이동")             # next walk: not tried again
    assert seen2.count(("lure", 3)) == 1, seen2
    print("ok  no knife / no throw spot → stop trying to pull that one (also on later walks), keep walking")



def test_ignored_foe_on_us_is_a_chaser() -> None:
    """10-01c: a foe the walk ignored after a 'stuck' fight hit us from 0.8 m for 10 s with no counter, then we fell into a gap."""
    w = World(player=(0.0, -23.3, 0.0), hp=793)
    c = w.add(2, 0x1018, 254010, (0.0, -23.3, 0.8), anim=3003)
    f = make_field(w)
    s = w.snapshot()
    assert f._chaser(s, {2}) is not None, "ignored foe swinging at 0.8 m must be fought"
    c.anim = 3500
    assert f._chaser(w.snapshot(), {2}) is not None, "…and when it is staggered next to us"
    w.move(2, (0.0, -23.3, 3.5))
    c.anim = 3003
    assert f._chaser(w.snapshot(), {2}) is None, "an ignored foe 3.5 m off stays ignored"
    print("ok  ignored foe swinging / staggered within 2.5 m is a chaser again; farther stays ignored")



def test_throw_at_another_height() -> None:
    old = F.CAREFUL_LOOK_S
    F.CAREFUL_LOOK_S = 0.0
    try:
        w = World(player=(0.0, -13.4, 0.0), hp=793)
        w.add(3, 0x1019, 250000, (4.0, -11.9, 10.0), anim=-1)            # 1.5 m higher (top of the stairs)
        f, seen = setup(w)
        f.careful_walk_to((0.0, -13.4, 3.0), Nm(), "#2 이동")
        assert ("lure", 3) in seen, seen                                  # height was not the problem (MoKa) — alignment was
    finally:
        F.CAREFUL_LOOK_S = old
    print("ok  a foe 1.5 m higher is still pulled (the height limit is reverted)")



def test_recover_rolls_off_a_close_chaser() -> None:
    """Zone 1 --basic death: backing off on foot with a hollow 0.95 m behind took four more hits. Roll away first; drop behind → stay."""
    import nav as nav_
    w = World(player=(0.0, -49.4, 0.0), hp=300)
    w.add(2, 0x1018, 254001, (0.0, -49.4, 0.9), anim=3003)
    f = make_field(w)
    rolls = []
    f.mv.roll_toward = lambda s, x, z: rolls.append((round(x, 1), round(z, 1)))
    f.retreat = lambda nm, home: "stopped"
    f.heal = lambda *a, **k: None
    f.home = (0.0, -49.4, -20.0)
    old = nav_.ground_ahead
    try:
        nav_.ground_ahead = lambda *a, **k: True
        F.Field.recover(f, "t low_hp", nm=object())
        assert rolls and rolls[0][1] < 0, rolls                            # away from the foe (it is at +z)
        rolls.clear()
        nav_.ground_ahead = lambda *a, **k: False
        assert F.Field.recover(f, "t low_hp", nm=object()) is False and not rolls, rolls
    finally:
        nav_.ground_ahead = old
    print("ok  recover: hollow 0.9 m away → roll away first; drop behind → no roll, fight on (False)")


def test_leg_moves_forward() -> None:
    """10-03c Burg #4: the navmesh path began at a portal 2.2 m behind; measured along the path the 4 m leg ended where we
    stood, so careful_walk_to stepped back and forth 15 times in 60 s. Now: skip that point, measure the leg straight."""
    from souls import field as F
    here = (-42.0, -18.7, -37.1)
    path = [here, (-43.2, -18.8, -35.2), (-41.9, -18.7, -37.3), (-41.4, -18.7, -37.9), (-40.1, -18.0, -39.4),
            (-39.0, -17.0, -40.7), (-36.0, -15.3, -44.0)]
    leg = F.careful_leg(here, path)
    assert leg[0] == (-41.9, -18.7, -37.3), leg
    assert ((leg[-1][0] - here[0]) ** 2 + (leg[-1][2] - here[2]) ** 2) ** 0.5 >= F.CAREFUL_LEG - 0.2, leg
    straight = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0), (5.0, 0.0, 0.0), (9.0, 0.0, 0.0)]
    assert F.careful_leg(straight[0], straight) == straight[1:5], F.careful_leg(straight[0], straight)
    corner = [(0.0, 0.0, 0.0), (0.0, 0.0, 3.0), (2.5, 0.0, 3.0), (6.0, 0.0, 3.0)]   # a real corner: 2nd point is not within 1 m
    assert F.careful_leg(corner[0], corner)[0] == (0.0, 0.0, 3.0), F.careful_leg(corner[0], corner)
    print("ok  careful leg: a portal point behind us is skipped, the leg reaches 4 m straight from here; plain paths as before")


if __name__ == "__main__":
    test_leg_moves_forward()
    test_order()
    test_no_knife_walks_on()
    test_ignored_foe_on_us_is_a_chaser()
    test_throw_at_another_height()
    test_recover_rolls_off_a_close_chaser()
    print("전부 통과")
