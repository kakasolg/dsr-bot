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



def test_no_throw_from_another_height() -> None:
    old = F.CAREFUL_LOOK_S
    F.CAREFUL_LOOK_S = 0.0
    try:
        w = World(player=(0.0, -13.4, 0.0), hp=793)
        w.add(3, 0x1019, 250000, (4.0, -11.9, 10.0), anim=-1)            # 1.5 m higher (top of the stairs)
        f, seen = setup(w)
        f.careful_walk_to((0.0, -13.4, 3.0), Nm(), "#2 이동")
        assert ("lure", 3) not in seen, seen
    finally:
        F.CAREFUL_LOOK_S = old
    print("ok  a foe 1.5 m higher is not thrown at from below — walk on up first")


if __name__ == "__main__":
    test_order()
    test_no_knife_walks_on()
    test_ignored_foe_on_us_is_a_chaser()
    test_no_throw_from_another_height()
    print("전부 통과")
