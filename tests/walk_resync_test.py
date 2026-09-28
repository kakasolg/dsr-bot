"""field.resync offline test — after a fight on a ledge, don't carry on toward a waypoint on another level (ROADMAP 1-e hotspot #4). No game.

  python tests/walk_resync_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import translate
from souls import field as F

# the #4 hotspot shape: path runs along the lower floor (y -11.3), the fight left us on the ledge above (y -9.8)
PATH = [(float(x), -11.3, -60.0 - x) for x in range(12)]


class FakeNm:
    def __init__(self, result):
        self.result, self.calls = result, []

    def find_path(self, start, goal):
        self.calls.append((start, goal))
        return self.result


def test_same_level_keeps_path() -> None:
    nm = FakeNm([(0, 0, 0)])
    path, i, dy = F.resync(PATH, (5.2, -11.2, -65.0), nm, 2, 10)
    assert path is PATH and i == 5 and dy == 0.0 and not nm.calls
    print("ok  same level: nearest point, no re-plan")


def test_other_level_replans() -> None:
    here = (5.0, -9.8, -65.2)
    new = [here, (6.0, -9.8, -66.0), (8.0, -10.5, -68.0), (10.0, -11.3, -70.0), (11.0, -11.3, -71.0), (13.0, -11.3, -73.0)]
    nm = FakeNm(new)
    path, i, dy = F.resync(PATH, here, nm, 2, 10)
    assert nm.calls == [(here, PATH[-1])]
    assert i == 0 and abs(dy - 1.5) < 1e-9
    assert path[0] == new[1]                          # starts after our own spot
    assert path[-1] == PATH[-1]                       # trimmed to the old goal (no overshoot)
    print("ok  other level (Δy +1.5): re-planned from here to the goal")


def test_other_level_no_path_falls_back() -> None:
    for nm in (None, FakeNm([])):
        path, i, dy = F.resync(PATH, (5.0, -9.8, -65.2), nm, 2, 10)
        assert path is PATH and i == 5 and dy == 0.0
    print("ok  no navmesh / no path: keep the old path")


def test_log_translates() -> None:
    s = translate.line("   #4 이동: 경로 재탐색 — 이어갈 점이 다른 층 (Δy +1.5 m), 5점")
    assert s == "   #4 move: re-plan path — resume point on another level (Δy +1.5 m), 5 points", s
    print("ok  log line translates")


def test_walkplan_resync() -> None:
    here = (5.0, -9.8, -65.2)
    new = [here, (6.0, -9.8, -66.0), (10.0, -11.3, -70.0), (11.0, -11.3, -71.0)]
    plan = F.WalkPlan(PATH, "#4 이동")
    plan.i = 4
    dy = plan.resync(here, FakeNm(new), window=True)
    assert dy and plan.i == 0 and plan.path[0] == new[1] and len(plan.tols) == len(plan.path)
    plan2 = F.WalkPlan(PATH, "#4 이동", tol=0.8)
    plan2.resync((5.2, -11.2, -65.0), FakeNm(new), window=False)
    assert plan2.path is not None and plan2.i == 5 and plan2.tols[0] == 0.8
    print("ok  WalkPlan.resync: re-plan swaps path and tolerances, same level keeps them")


if __name__ == "__main__":
    test_same_level_keeps_path()
    test_other_level_replans()
    test_other_level_no_path_falls_back()
    test_log_translates()
    test_walkplan_resync()

