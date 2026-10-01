"""walksim.py offline test — the bot's nav.goto steering the simulated character (motion model + World). No game.

  python tests/walksim_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import motion
import nav
import walksim as W

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


class Corridor:
    """Flat floor y 0: x 0~20, z 0~2, plus z 0~20 at x 18~20 (an L). Nothing else (walls)."""
    map_id = "fake"

    def floor_at(self, x, z, y):
        h = self.floor_tri_at(x, z, y)
        return (h[0], h[1]) if h else None

    def floor_tri_at(self, x, z, y):
        if (0 <= x <= 20 and 0 <= z <= 2) or (18 <= x <= 20 and 0 <= z <= 20):
            return (0.0, 0, 1)
        return None

    def on_mesh(self, x, y, z, dy=1.0):
        return self.floor_tri_at(x, z, y) is not None

    def nearest_walkable(self, x, y, z, r=8.0, dy=2.5):
        return None


nm = Corridor()
world = motion.World(nm)
path = [(5.0, 0.0, 1.0), (10.0, 0.0, 1.0), (19.0, 0.0, 1.0), (19.0, 0.0, 10.0), (19.0, 0.0, 18.0)]
r = W.walk(nm, world, path, (1.0, 0.0, 1.0), math.pi / 2, cam_yaw=0.7)
check("nav.goto walks the L in the simulation: arrived, every point reached", r.result == "arrived"
      and all(p == "arrived" for p in r.points))
check("… in about the walking time (27 m at ~3.4 m/s ≈ 8 s, < 14 s), no stall", 6.0 < r.secs < 14.0 and r.stalls == [])
check("… the real clock wasn't used (nav.time restored after)", nav.time.__name__ == "time")
check("… never left the floor", all(nm.on_mesh(x, y, z) for _, x, y, z in r.track))
check("the camera yaw doesn't matter (stick is camera-relative)",
      abs(W.walk(nm, motion.World(nm), path, (1.0, 0.0, 1.0), math.pi / 2, cam_yaw=-2.0).secs - r.secs) < 0.5)
blocked = W.walk(nm, motion.World(nm), [(1.0, 0.0, 10.0)], (1.0, 0.0, 1.0), 0.0, 0.0, timeout=4.0)
check("a point through the wall: not reached, stalls recorded", blocked.result != "arrived" and blocked.stalls)
check("stalls(): 1 s+ under 0.3 m/s", W.stalls([(0.0, 0, 0, 0), (0.5, 0, 0, 0), (1.0, 0, 0, 0), (1.5, 1, 0, 0)])
      == [(0.0, 1.0, (0, 0, 0))])

print("passage entrance (the point-70 fix, ROADMAP 1-f) — 2 runs per route")
res = W.entrance_trial(2, 0)
before = [sum(s[1] for s in W.at_entrance(x)) for x in res["runs"]["before"]]
after = [sum(s[1] for s in W.at_entrance(x)) for x in res["runs"]["after"]]
check("before the fix (69 → a0 diagonal): stalls at the entrance every run (game: 15/15)", all(s > 1.0 for s in before))
check("after (point 70 + the human's way in): no entrance stall (game: 0)", all(s == 0 for s in after))
check("after: top → 3 points inside in ~4 s (game drill: 4.2 s each time)",
      all(3.0 < x.secs < 6.0 for x in res["runs"]["after"]))

print(f"\n{'all ok' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
