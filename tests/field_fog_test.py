"""아는 안개벽 오프라인 테스트 (P-41) — 걷기 길이 FOG_WALLS를 가로지르면 그 점으로 걷기 전에 벽 앞에 서서 fog_through, 걷기 한 번에
한 번만. 성벽 마을 마을 구역 끝 → `#4 이동` 안개벽: 10-03a 봇이 21 s 비비다 [MoKa]가 A.

  python tests/field_fog_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World, make_field
from souls import field as F


class Nm:
    def floor_at(self, *a, **k):
        return None

    def __getattr__(self, name):
        return lambda *a, **k: None


ME = (-50.2, -22.7, -30.3)            # where the bot rubbed against the wall (10-03a)
BEYOND = (-49.6, -21.8, -33.2)        # '#4 이동' point 3, behind the wall


def test_geometry() -> None:
    wall = F.FOG_WALLS[0]
    assert F.fog_ahead(ME, BEYOND) == wall and F.fog_ahead(BEYOND, ME) == wall
    assert F.fog_ahead(ME, (-50.2, -22.7, -28.0)) is None                   # a point on this side
    assert F.fog_ahead((-50.2, -60.0, -30.3), (-49.6, -60.0, -33.2)) is None  # another floor
    assert F.fog_ahead((10.0, -22.0, 0.0), (20.0, -22.0, 0.0)) is None
    print("ok  fog_ahead: the 10-03a line crosses the wall (both ways); this side, other floor, elsewhere → none")


def run_walk(path, fog_ok=True, me=ME):
    f = make_field(World(player=me))
    calls = []
    f.fog_through = lambda toward, known=False: calls.append(("fog", tuple(toward), known)) or fog_ok
    f.walk = lambda pts, nm, tag, **k: calls.append(("front", tuple(pts[0]))) or "arrived"
    f._follow = lambda q, *a, **k: calls.append(("go", tuple(q))) or "arrived"
    r = F.Field._walk(f, list(path), Nm(), "#4 이동")
    return r, calls, f.logs


def test_walk_crosses_once() -> None:
    r, calls, logs = run_walk([BEYOND, (-49.0, -21.8, -36.0)], me=(-49.95, -22.0, -32.6))  # already at the wall
    assert r == "arrived" and [c[0] for c in calls] == ["fog", "go", "go"], calls
    assert calls[0][2] is True, calls[0]                                     # known wall: A without the prompt check
    assert any("안개벽" in l and "통과" in l for l in logs), logs[-3:]
    r, calls, logs = run_walk([BEYOND], me=(-50.4, -22.7, -26.0))           # 6 m back: walk to the front spot first
    assert [c[0] for c in calls] == ["front", "fog", "go"], calls
    front = calls[0][1]
    c = F.FOG_WALLS[0]
    assert 0.4 < ((front[0] - c[0]) ** 2 + (front[2] - c[2]) ** 2) ** 0.5 < 0.8 and front[2] > c[2], front
    print("ok  walk: at the wall → fog_through once; farther back → walk to the spot before the wall first; then the points as before")


def test_no_wall_left_walks_on() -> None:
    r, calls, logs = run_walk([BEYOND], fog_ok=False, me=(-49.95, -22.0, -32.6))   # A did nothing (wall gone) → just walk on
    assert r == "arrived" and [c[0] for c in calls] == ["fog", "go"], calls
    assert any("못 지나감" in l for l in logs), logs[-3:]
    print("ok  no wall any more → one try, then the walk carries on")


def test_walk_elsewhere_untouched() -> None:
    f = make_field(World(player=(0.0, -49.4, 0.0)))
    calls = []
    f.fog_through = lambda toward, known=False: calls.append("fog") or True
    f._follow = lambda q, *a, **k: calls.append("go") or "arrived"
    assert F.Field._walk(f, [(1.0, -49.4, 0.0), (2.0, -49.4, 0.0)], Nm(), "t") == "arrived"
    assert calls == ["go", "go"], calls
    print("ok  paths that cross no known wall walk exactly as before")


def test_known_wall_presses_without_prompt() -> None:
    import screen_prompt as L
    old = L.prompt_px
    L.prompt_px = lambda: 0                                                  # the dark-box check never fires (10-03b)
    sleep = F.time.sleep
    F.time.sleep = lambda s: None
    try:
        for known, want in ((True, True), (False, False)):
            f = make_field(World(player=(-50.1, -22.7, -31.2)))
            presses = []
            f.mv.stick_to = lambda s, x, z, scale: (0.0, scale)
            f.mv.pad.move = lambda *a: None

            def press(b, hold=0.1, gap=0.1, f=f):
                presses.append(b)
                f.mv.w.player.x, f.mv.w.player.y, f.mv.w.player.z = -49.6, -21.8, -34.5   # A at the wall → through it
            f.mv.press = press
            ok = f.fog_through(BEYOND, known=known)
            assert ok is want and (len(presses) == 1) is want, (known, ok, presses)
    finally:
        L.prompt_px = old
        F.time.sleep = sleep
    print("ok  fog_through: known wall → A without the prompt and passes; unknown wall without a prompt → no A")


def test_known_wall_turns_before_a() -> None:
    import math
    import screen_prompt as L
    old = L.prompt_px
    L.prompt_px = lambda: 0
    sleep = F.time.sleep
    F.time.sleep = lambda s: None
    try:
        f = make_field(World(player=(-50.1, -22.7, -31.2)))               # facing +z: the wall (−z) is 180° behind (161915: 89–111°)
        order = []
        f.mv.stick_to = lambda s, x, z, scale: (0.0, scale)

        def move(x, y, f=f):
            if y == 0.55:                                                     # the turn stick: body now faces the next point
                p = f.mv.w.player
                p.heading = math.atan2(BEYOND[0] - p.x, BEYOND[2] - p.z) - math.pi
                order.append("turn")
        f.mv.pad.move = move
        f.mv.press = lambda b, hold=0.1, gap=0.1: order.append("A")
        f.fog_through(BEYOND, known=True)
        assert order[:2] == ["turn", "A"], order
        assert any("누를 때 몸 +0°" in l or "누를 때 몸 -0°" in l for l in f.logs), f.logs[-2:]
    finally:
        L.prompt_px = old
        F.time.sleep = sleep
    print("ok  fog_through: known wall 180° behind → turn until facing the next point, then A (the log says the angle at A)")


def test_fog_flag() -> None:
    import types
    seen = {}
    for flag, want in ((True, ["go"]), (False, ["fog", "go"]), (None, ["fog", "go"])):
        f = make_field(World(player=(-49.95, -22.0, -32.6)))
        f.mv.tm = types.SimpleNamespace(event_flag=lambda fid, v=flag: seen.setdefault("fid", fid) and v)
        calls = []
        f.fog_through = lambda toward, known=False: calls.append("fog") or True
        f.walk = lambda pts, nm, tag, **k: calls.append("front") or "arrived"
        f._follow = lambda q, *a, **k: calls.append("go") or "arrived"
        assert F.Field._walk(f, [BEYOND], Nm(), "#4 이동") == "arrived"
        assert calls == want, (flag, calls)
        assert any("플래그 11010090" in l for l in f.logs), f.logs[-3:]
    assert seen["fid"] == 11010090
    print("ok  fog flag 11010090: True (passed) → walk on without A; False / unreadable → stand at the wall and A as before")


def test_door_retry() -> None:
    import types
    door = F.DOORS[0]
    for r, at, state, want_a in (("stuck", door, False, True), ("timeout", door, False, True), ("stuck", door, None, True),
                                 ("stuck", door, True, False), ("arrived", door, False, False), ("stuck", (0.0, -6.0, 0.0), False, False)):
        f = make_field(World(player=at))
        f.mv.tm = types.SimpleNamespace(event_flag=lambda fid, v=state: v if fid == 61010510 else True)
        presses = []
        f.mv.pad.interact = lambda: presses.append("A")
        sleep = F.time.sleep
        F.time.sleep = lambda s: None
        try:
            out = F.Field._door_retry(f, r, (24.1, -5.7, -99.0), "t", lambda: "arrived")
        finally:
            F.time.sleep = sleep
        assert (presses == ["A"]) is want_a and out == ("arrived" if want_a else r), (r, at, state, presses, out)
    f = make_field(World(player=door))
    f.mv.tm = types.SimpleNamespace(event_flag=lambda fid: fid == 11010140)
    assert F.Field.door_flags(f, door) == {11010140: True, 61010510: False}
    assert F.Field.door_open(f, door) is False and F.Field.door_open(f, (0.0, 0.0, 0.0)) is None
    print("ok  door: walk back stuck next to a shut door (state flag False / unreadable) → A once, walk again; "
          "open (True) → no A (A shuts it, 11-01); arrived or no door → nothing")


if __name__ == "__main__":
    test_geometry()
    test_walk_crosses_once()
    test_no_wall_left_walks_on()
    test_walk_elsewhere_untouched()
    test_known_wall_presses_without_prompt()
    test_known_wall_turns_before_a()
    test_fog_flag()
    test_door_retry()
    print("전부 통과")
