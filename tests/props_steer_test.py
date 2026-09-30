"""NavMesh paths bend around breakable props they run through (ROADMAP P-12 e).
28x·28z: the #6 walk's point 12 sat 0.36 m from crate o1321_0021 → the bot stopped 1.2 m short, smashed it, 2.5~3 s stall every run.
Fake floors (rectangles) stand in for the NavMesh: on_mesh / border_dist / clear_line, like navmesh.Navmesh."""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))

import math

import numpy as np

from souls import props as P


class Floor:
    """Walkable = union of axis-aligned rectangles (x0, x1, z0, z1) at height y."""
    map_id = None

    def __init__(self, rects, y=-13.37):
        self.rects, self.y = rects, y

    def _in(self, x, z):
        return any(x0 <= x <= x1 and z0 <= z <= z1 for x0, x1, z0, z1 in self.rects)

    def on_mesh(self, x, y, z, dy=1.0):
        return self._in(x, z) and abs(y - self.y) <= dy

    def border_dist(self, x, y, z, dy=2.0):          # distance to the nearest point just off the floor (grid search is enough here)
        best = math.inf
        for r in np.arange(0.05, 3.0, 0.05):
            for a in np.arange(0, 2 * math.pi, math.pi / 16):
                if not self._in(x + r * math.cos(a), z + r * math.sin(a)):
                    return float(r)
        return best

    def clear_line(self, p0, p1, step=0.25, **_):
        n = max(2, int(math.dist((p0[0], p0[2]), (p1[0], p1[2])) / step))
        return all(self._in(p0[0] + (p1[0] - p0[0]) * k / n, p0[2] + (p1[2] - p0[2]) * k / n) for k in range(n + 1))


CRATE = {"name": "o1321_0021", "model": "o1321", "pos": [-22.734, -13.37, -64.325]}
PATH = [(-15.35, -13.41, -68.23), (-19.87, -13.36, -64.35), (-21.16, -13.37, -64.79), (-22.82, -13.37, -63.98),
        (-24.33, -13.37, -63.65), (-27.54, -14.61, -68.8)]            # 28z #6 walk, points 9..14 (track at 323.96 s)
q = CRATE["pos"]


def min_pass(path):
    return min(P._seg_dist(q, a, b) for a, b in zip(path, path[1:]))


assert min_pass(PATH) < 0.3                                         # the recorded path runs over the crate

open_floor = Floor([(-35, -5, -75, -55)])
lines = []
out = P.steer_around(PATH, open_floor, [CRATE], log=lines.append)
assert out[0] == PATH[0] and out[-1] == PATH[-1], out
assert min_pass(out) >= P.CLEAR * 0.9, (min_pass(out), out)
assert all(math.hypot(p[0] - q[0], p[2] - q[2]) >= P.CLEAR for p in out), out
assert len(lines) == 1 and "o1321_0021" in lines[0], lines
print(f"ok  28z #6 path: passes the crate at {min_pass(PATH):.2f} m → {min_pass(out):.2f} m after steering, ends kept")

# wall right beside the path on the crate's north side (z > -63.2): the detour goes south
south = Floor([(-35, -5, -75, -63.2)])
out = P.steer_around(PATH, south, [CRATE])
assert min_pass(out) >= P.CLEAR * 0.9 and all(p[2] < q[2] for p in out if p not in PATH), out
print("ok  wall on one side: the detour takes the other side")

# a narrow lane (1.5 m) through the crate: no room either side → path unchanged (field.walk smashes it as before)
lane = Floor([(-35, -5, -65.1, -63.6), (-16, -14, -69, -63), (-28, -26, -70, -63)])
assert P.steer_around(PATH, lane, [CRATE]) == PATH
print("ok  no room beside the crate: path unchanged (smash stays the fallback)")

# far from the path / on another level / stairs / path ending on the crate: unchanged
assert P.steer_around(PATH, open_floor, [dict(CRATE, pos=[-10.0, -13.37, -60.0])]) == PATH
assert P.steer_around(PATH, open_floor, [dict(CRATE, pos=[q[0], q[1] + 3.0, q[2]])]) == PATH
stairs = [(-20.0, -13.37, -64.3), (-25.0, -12.3, -64.3)]
assert P.steer_around(stairs, open_floor, [CRATE]) == stairs
ends = [(-19.0, -13.37, -64.3), (-22.7, -13.37, -64.3)]
assert P.steer_around(ends, open_floor, [CRATE]) == ends
assert P.steer_around(PATH, open_floor, []) == PATH
print("ok  unchanged: prop off the path, on another level, on stairs, at the path's end, no props")

# navmesh.Navmesh.border_dist on a 4 m x 4 m square of two triangles (all outer edges are border)
import navmesh as NM
nm = object.__new__(NM.Navmesh)
nm.v = np.array([[0, 0, 0], [4, 0, 0], [4, 0, 4], [0, 0, 4]], float)
nm.t = np.array([[0, 1, 2], [0, 2, 3]])
nm.adj = np.array([[-1, -1, 1], [0, -1, -1]])                      # edges (0,1),(1,2),(0,2): the diagonal (0,2) is shared
nm._bedges = None
assert abs(nm.border_dist(2.0, 0.0, 2.0) - 2.0) < 1e-9
assert abs(nm.border_dist(0.5, 0.0, 3.0) - 0.5) < 1e-9
assert nm.border_dist(2.0, 5.0, 2.0) == math.inf                    # other level
print("ok  Navmesh.border_dist: distance to neighborless edges only, same level")

# learned(): props smashed in ≥ 2 different runs (copies of one run count once) — the only ones steered around by default
import tempfile, os
d = tempfile.mkdtemp()
line = "[  245.6]       #6 이동: 길 막은 o1321 (o1321_0021) 부숨 시도 — (-22.7,-13.4,-64.3)\n"
once = "[  100.0]       #3 이동: 길 막은 o1150 (o1150_01) 부숨 시도 — (-59.1,-22.9,-25.4)\n"
paths = []
for name, body in [("a.log", line + once), ("a_copy.txt", line + once), ("b.log", "[  300.1]       #6 이동: 길 막은 o1321 (o1321_0021) 부숨 시도 — (-22.7,-13.4,-64.3)\n")]:
    p = os.path.join(d, name)
    open(p, "w", encoding="utf-8").write(body)
    paths.append(p)
assert P.learned(2, paths) == {"o1321_0021"}, P.learned(2, paths)      # o1150_01: one run (a + its copy) — not yet
assert P.learned(2, paths[:2]) == set()
print("ok  learned: o1321_0021 smashed in 2 runs → steered; o1150_01 in 1 run (+ a copy) → not yet")

# default props = this map's props named in nm.steer only (state lives on the Navmesh, not in the props module)
class MapFloor(Floor):
    map_id = "m10_01_00_00"
assert not hasattr(P, "STEER") and not hasattr(P, "LOG"), "no module-level steering state"
nm = MapFloor([(-35, -5, -75, -55)])
assert P.steer_around(PATH, nm) == PATH                                # nm.steer not set → nothing steered
nm.steer = set()
assert P.steer_around(PATH, nm) == PATH
nm.steer = {"o1321_0021"}
assert min_pass(P.steer_around(PATH, nm)) >= P.CLEAR * 0.9
other = MapFloor([(-35, -5, -75, -55)])                                # a second Navmesh in the same process is unaffected
assert P.steer_around(PATH, other) == PATH
print("ok  default: nothing steered until nm.steer names a prop; with it, the map file's crate is steered around; other Navmesh unaffected")

# attach(): learned names + log go on every Navmesh (list or dict); a failing learn() leaves them empty and says so
a, b = MapFloor([]), MapFloor([])
lines = []
assert P.attach([a, b], lines.append, learn=lambda n: {"o1321_0021"}) == {"o1321_0021"}
assert a.steer == b.steer == {"o1321_0021"} and a.steer_log == lines.append
assert any("o1321_0021" in x for x in lines), lines
c = MapFloor([])
lines.clear()


def boom(n):
    raise OSError("no logs")
assert P.attach({"m": c}, lines.append, learn=boom) == set() and c.steer == set() and any("기록 못 읽음" in x for x in lines), lines
print("ok  attach: names and log set on each Navmesh (list or dict); a failing learn() → empty set + a log line")

# a path that passes the crate, goes 10 m away and comes back past it: the points in between are not dropped
loop = [(-19.0, -13.37, -64.3), (-21.5, -13.37, -64.0), (-21.5, -13.37, -58.0), (-15.0, -13.37, -58.0), (-15.0, -13.37, -70.0),
        (-21.5, -13.37, -70.0), (-21.5, -13.37, -64.8), (-25.0, -13.37, -64.8)]
out = P.steer_around(loop, open_floor, [CRATE])
assert all(p in out for p in loop[2:6]), out
print("ok  a loop passing the crate twice keeps the points between")
