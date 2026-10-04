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
    f.fog_through = lambda toward: calls.append(("fog", tuple(toward))) or fog_ok
    f.walk = lambda pts, nm, tag, **k: calls.append(("front", tuple(pts[0]))) or "arrived"
    f._follow = lambda q, *a, **k: calls.append(("go", tuple(q))) or "arrived"
    r = F.Field._walk(f, list(path), Nm(), "#4 이동")
    return r, calls, f.logs


def test_walk_crosses_once() -> None:
    r, calls, logs = run_walk([BEYOND, (-49.0, -21.8, -36.0)])             # already at the wall (10-03a spot)
    assert r == "arrived" and [c[0] for c in calls] == ["fog", "go", "go"], calls
    assert any("안개벽" in l and "통과" in l for l in logs), logs[-3:]
    r, calls, logs = run_walk([BEYOND], me=(-50.4, -22.7, -26.0))           # 6 m back: walk to the front spot first
    assert [c[0] for c in calls] == ["front", "fog", "go"], calls
    front = calls[0][1]
    assert 0.9 < ((front[0] - F.FOG_WALLS[0][0]) ** 2 + (front[2] - F.FOG_WALLS[0][2]) ** 2) ** 0.5 < 1.5 and front[2] > F.FOG_WALLS[0][2], front
    print("ok  walk: at the wall → fog_through once; farther back → walk to the spot before the wall first; then the points as before")


def test_no_wall_left_walks_on() -> None:
    r, calls, logs = run_walk([BEYOND], fog_ok=False)                       # no prompt (wall gone) → just walk on
    assert r == "arrived" and [c[0] for c in calls] == ["fog", "go"], calls
    assert any("못 지나감" in l for l in logs), logs[-3:]
    print("ok  no wall any more → one try, then the walk carries on")


def test_walk_elsewhere_untouched() -> None:
    f = make_field(World(player=(0.0, -49.4, 0.0)))
    calls = []
    f.fog_through = lambda toward: calls.append("fog") or True
    f._follow = lambda q, *a, **k: calls.append("go") or "arrived"
    assert F.Field._walk(f, [(1.0, -49.4, 0.0), (2.0, -49.4, 0.0)], Nm(), "t") == "arrived"
    assert calls == ["go", "go"], calls
    print("ok  paths that cross no known wall walk exactly as before")


if __name__ == "__main__":
    test_geometry()
    test_walk_crosses_once()
    test_no_wall_left_walks_on()
    test_walk_elsewhere_untouched()
    print("전부 통과")
