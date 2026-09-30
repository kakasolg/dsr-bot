"""Field.walk loop offline test — pins how the walk reacts to what the follower (nav.goto) reports, so the walk can be
split into pieces without changing behavior (ROADMAP 0-c). No game.

  python tests/walk_loop_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World, make_field
from souls import field as F

PATH = [(float(x), 0.0, 0.0) for x in range(0, 12, 2)]      # 6 points along +x


class Nm:
    map_id = None

    def __init__(self, detour=False):
        self.detour = detour

    def floor_at(self, x, z, y):
        return (0.0,)

    def find_path(self, a, b):
        return [a, b] if self.detour else []


def run(script, nm=None, chase=None, gen_bump_at=None, fog=None):
    """script: results nav.goto returns in order (then 'arrived'). 'arrived' moves the player onto the point.
    chase: at the call with this index a hollow stands next to us and goto says 'retreat'."""
    w = World(player=(0.0, 0.0, 0.0))
    f = make_field(w)
    f._detour = False
    f.fog_through = fog or (lambda q: False)
    f._near_zone = lambda s, nm: None
    f.reflex.hold = lambda: None
    f.reflex.threat_now = lambda s: False
    calls = []
    script = list(script)

    def goto(tm, pad, q, tolerance, timeout, log, terrain, mover, on_stuck, mode_fn):
        n = len(calls)
        calls.append((round(q[0], 1), round(tolerance, 2)))
        if gen_bump_at == n:
            f.esc.gen += 1
            w.player.x = q[0]
            return "arrived"
        if chase == n:
            w.add(9, 0x109, 254000, (w.player.x + 1.0, 0.0, 0.0), anim=3000)
            return "retreat"
        r = script.pop(0) if script else "arrived"
        if isinstance(r, tuple):                   # (result, where the player ends up) — e.g. stuck 1 m short
            r, (w.player.x, w.player.y, w.player.z) = r
        if r == "arrived":
            w.player.x, w.player.z = q[0], q[2]
        return r

    orig, F.nav.goto = F.nav.goto, goto
    try:
        res = f.walk(PATH, nm or Nm(), "#t 이동")
    finally:
        F.nav.goto = orig
    return res, [c[0] for c in calls], f


def test_all_arrive() -> None:
    res, xs, _ = run([])
    assert res == "arrived" and xs == [0, 2, 4, 6, 8, 10], xs
    print("ok  every point once, in order")


def test_fail_once_moves_on() -> None:
    res, xs, f = run(["arrived", "timeout"])
    assert res == "arrived" and xs == [0, 2, 4, 6, 8, 10], xs          # a single miss goes on to the next point
    assert any("못 감 (timeout, 1번째)" in l for l in f.logs)
    print("ok  one miss: logged, next point")


def test_three_fails_stuck() -> None:
    res, xs, _ = run(["arrived", "timeout", "timeout", "timeout"])
    assert res == "stuck" and xs == [0, 2, 4, 6], xs
    print("ok  three misses in a row: stuck")


def test_detour_once() -> None:
    res, xs, f = run(["arrived", "timeout"], nm=Nm(detour=True))
    assert res == "arrived" and f.walks == [((2.0, 0.0, 0.0), "#t 이동 돌아서")] and xs == [0, 2, 4, 6, 8, 10], (xs, f.walks)
    print("ok  first miss with a navmesh path: detour walk_to, then next point")


def test_almost_there_moves_on() -> None:
    res, xs, f = run(["arrived", ("stuck", (1.0, 0.3, 0.2))], nm=Nm(detour=True))   # point 1 (x 2), stuck ~1 m short
    assert res == "arrived" and xs == [0, 2, 4, 6, 8, 10], xs
    assert f.walks == [], f.walks                                                    # no detour
    assert any("1번 점 거의 도착 (1.1 m, Δy +0.3)" in l for l in f.logs), f.logs
    res, xs, f = run(["arrived", ("stuck", (1.0, 0.0, 0.0)), ("stuck", (3.0, 0.0, 0.0)), ("stuck", (5.0, 0.0, 0.0))])
    assert res == "arrived", (res, xs)                                               # almost-there misses don't add up to 'stuck'
    res, xs, f = run(["arrived", ("stuck", (0.4, 0.0, 0.0))], nm=Nm(detour=True))    # 1.6 m short: still almost there
    assert any("거의 도착" in l for l in f.logs) and f.walks == []
    res, xs, f = run(["arrived", ("stuck", (0.2, 0.0, 0.0))], nm=Nm(detour=True))    # 1.8 m short: the usual chain
    assert not any("거의 도착" in l for l in f.logs) and f.walks
    res, xs, f = run(["arrived", ("stuck", (1.0, 1.2, 0.0))], nm=Nm(detour=True))    # 1.2 m higher: not almost there
    assert f.walks == [((2.0, 0.0, 0.0), "#t 이동 돌아서")] and not any("거의 도착" in l for l in f.logs), f.walks
    res, xs, f = run(["arrived", ("unreachable", (1.5, 0.0, 0.0))], nm=Nm(detour=True))
    assert not any("거의 도착" in l for l in f.logs)                                 # unreachable: not this rule
    res, xs, f = run(["arrived"] * 5 + [("stuck", (9.0, 0.0, 0.0))], nm=Nm(detour=True))
    assert not any("거의 도착" in l for l in f.logs) and f.walks, f.walks            # last point: the usual chain
    fogs = []
    res, xs, f = run(["arrived", ("stuck", (1.0, 0.0, 0.0)), "stuck"], fog=lambda q: (fogs.append(q), True)[1])
    assert fogs == [(4.0, 0.0, 0.0)], fogs          # fog wall: almost there at point 1, a real miss at point 2 → fog at once
    print("ok  almost there (≤ 1.7 m, |dy| ≤ 0.8, not the last point): next point, no detour; fog wall right after")


def test_chaser_fight_then_resync() -> None:
    res, xs, f = run([], chase=2)
    assert res == "arrived" and len(f.fights) == 1 and f.fights[0]["wait_far"]
    assert xs == [0, 2, 4, 2, 4, 6, 8, 10], xs                            # after the fight: nearest point (we were at 2)
    print("ok  chaser: fight, then carry on from the nearest point")


def test_quit_out_resync() -> None:
    res, xs, _ = run([], gen_bump_at=3)
    assert res == "arrived" and xs == [0, 2, 4, 6, 6, 8, 10], xs
    print("ok  quit-out: carry on from the nearest point")


def test_corner_tolerance() -> None:
    global PATH
    old, PATH = PATH, [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 0.0, 4.0)]
    try:
        w = World(player=(0.0, 0.0, 0.0))
        tols = []
        f = make_field(w)
        f._detour = False
        orig = F.nav.goto
        F.nav.goto = lambda tm, pad, q, tolerance, **k: (tols.append(tolerance), "arrived")[1]
        try:
            f.walk(PATH, Nm(), "#t")
        finally:
            F.nav.goto = orig
        assert tols[1] == 0.5 and tols[0] == 1.0, tols
    finally:
        PATH = old
    print("ok  corner point gets the tight tolerance")


if __name__ == "__main__":
    for fn in (test_all_arrive, test_fail_once_moves_on, test_three_fails_stuck, test_detour_once,
               test_almost_there_moves_on, test_chaser_fight_then_resync, test_quit_out_resync, test_corner_tolerance):
        fn()
