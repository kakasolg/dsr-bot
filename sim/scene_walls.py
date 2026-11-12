"""NavMesh-edge walls from a room scene's own floor — the fallback when the Sketchfab walls are not there.

The rooms built by sim/burg_scene.py (burg, firelink_taurus, firelink_demon, firelink_loop) take their walls from the
Sketchfab "Dark Souls Map", which is local only ([win], CC BY-NC). A fresh clone (cloud) has no such file, so those rooms
had no walls at all. This writes `edge_walls` into the scene with the same rule sim/ramp_scene.py uses for the ramp
room's `walls`: an open floor edge (a triangle side no other floor triangle shares) gets a wall when there is no floor
0.8 m beyond it at or below its height + 0.5 m — a void, a building side or a face up to higher ground; an edge with floor
anywhere below stays open (you step or fall down). The wall stands WALL_OUT past the edge (a NavMesh ends an agent radius
short of the real wall). ramp.gd uses `edge_walls` only when the scene asks for Sketchfab walls and the file is missing.

Needs only the scene file (its `nav` triangles and `floor_patch` strips) — no game folder, no Sketchfab file.
  python sim/scene_walls.py [scene …]      default: every scene with sk_walls in sim/godot/assets/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "sim" / "godot" / "assets"
WALL_OUT = 0.4      # as ramp_scene.WALL_OUT [guess] — NavMesh agent radius
BEYOND = 0.8        # look for floor this far past the edge (ramp_scene)
UP = 0.5            # floor beyond counts if at most this above the edge (ramp_scene)
CELL = 2.0          # grid cell for the floor lookup (m)
ROUTE_GAP = 5.0     # cam_path points farther apart than this are not joined (a jump in the list, not a walk)
ROUTE_DY = 3.0      # a route segment crosses a wall only if its height is within this of the wall's (m)
KEY = 2             # vertex rounding (1 cm) to find shared sides — the two NavMesh sheets have separate vertex lists whose
                    # copies of one point differ by < 1 cm (mm rounding walled the Burg route at (12.2, −6.0, −93.5), 11-12)


def _tris(scene: dict) -> np.ndarray:
    v = np.asarray(scene["nav"]["v"], dtype=float)
    t = np.asarray(scene["nav"]["t"], dtype=int)
    tris = v[t]
    patch = scene.get("floor_patch") or []
    if patch:
        tris = np.concatenate([tris, np.asarray(patch, dtype=float)], axis=0)
    return tris


def _grid(tris: np.ndarray) -> dict:
    g: dict = {}
    lo = np.floor(tris[:, :, [0, 2]].min(axis=1) / CELL).astype(int)
    hi = np.floor(tris[:, :, [0, 2]].max(axis=1) / CELL).astype(int)
    for i in range(len(tris)):
        for gx in range(lo[i, 0], hi[i, 0] + 1):
            for gz in range(lo[i, 1], hi[i, 1] + 1):
                g.setdefault((gx, gz), []).append(i)
    return g


def _heights(tris: np.ndarray, grid: dict, x: float, z: float) -> list[float]:
    out = []
    for i in grid.get((int(np.floor(x / CELL)), int(np.floor(z / CELL))), ()):
        a, b, c = tris[i]
        d = (b[2] - c[2]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[2] - c[2])
        if abs(d) < 1e-9:
            continue
        l1 = ((b[2] - c[2]) * (x - c[0]) + (c[0] - b[0]) * (z - c[2])) / d
        l2 = ((c[2] - a[2]) * (x - c[0]) + (a[0] - c[0]) * (z - c[2])) / d
        l3 = 1 - l1 - l2
        if min(l1, l2, l3) >= -1e-6:
            out.append(l1 * a[1] + l2 * b[1] + l3 * c[1])
    return out


def _cross(a0, a1, b0, b1) -> bool:
    """Do segments a and b cross in x-z?"""
    def o(p, q, r):
        return (q[0] - p[0]) * (r[2] - p[2]) - (q[2] - p[2]) * (r[0] - p[0])
    return o(a0, a1, b0) * o(a0, a1, b1) < 0 and o(b0, b1, a0) * o(b0, b1, a1) < 0


def _route(scene: dict) -> list:
    """The scene's route as segments (cam_path: the walked / planned route the room camera follows)."""
    pts = [np.asarray(p[:3], dtype=float) for p in scene.get("cam_path") or []]
    return [(a, b) for a, b in zip(pts, pts[1:]) if float(np.hypot(*(b - a)[[0, 2]])) <= ROUTE_GAP]


def edge_walls(scene: dict) -> list[list[float]]:
    """[x0, y0, z0, x1, y1, z1] per wall segment — same shape as a scene's `walls`. A wall that would cross the scene's own
    route (cam_path) is left out: the route was walked in the game, and where it leaves the NavMesh floor (steps the
    NavMesh doesn't cover — ramp top at (−18.5…−20, −39 → −36, 14 → 12.7), 11-12) the floor data alone looks like a void."""
    route = _route(scene)
    tris = _tris(scene)
    n_nav = len(scene["nav"]["t"])
    grid = _grid(tris)
    key = lambda p: tuple(np.round(p, KEY))
    count: dict = {}
    for i in range(len(tris)):
        for a, b in ((0, 1), (1, 2), (2, 0)):
            k = frozenset((key(tris[i, a]), key(tris[i, b])))
            count[k] = count.get(k, 0) + 1
    walls = []
    for i in range(n_nav):                                  # walls only on NavMesh triangles' sides, not on patch strips
        cen = tris[i].mean(axis=0)
        for a, b in ((0, 1), (1, 2), (2, 0)):
            p0, p1 = tris[i, a], tris[i, b]
            if count[frozenset((key(p0), key(p1)))] > 1:
                continue
            mid = (p0 + p1) / 2.0
            d = mid - cen
            n = float(np.hypot(d[0], d[2]))
            if n < 1e-6:
                continue
            q = mid + np.array([d[0] / n * BEYOND, 0.0, d[2] / n * BEYOND])
            if any(y - mid[1] <= UP for y in _heights(tris, grid, float(q[0]), float(q[2]))):
                continue                                    # floor beyond at or below the edge: stays open
            e = p1 - p0
            nx, nz = e[2], -e[0]
            ln = float(np.hypot(nx, nz)) or 1.0
            sgn = 1.0 if nx * d[0] + nz * d[2] > 0 else -1.0
            off = np.array([nx / ln * sgn * WALL_OUT, 0.0, nz / ln * sgn * WALL_OUT])
            w0, w1 = p0 + off, p1 + off
            ylo, yhi = min(w0[1], w1[1]) - ROUTE_DY, max(w0[1], w1[1]) + ROUTE_DY
            if any(_cross(w0, w1, a, b) and ylo <= (a[1] + b[1]) / 2 <= yhi for a, b in route):
                continue                                    # on the scene's route — leave it open
            walls.append([round(float(x), 3) for x in (*w0, *w1)])
    return walls


def main() -> None:
    files = [Path(a) for a in sys.argv[1:]] or sorted(p for p in ASSETS.glob("*_scene.json")
                                                     if json.loads(p.read_text(encoding="utf-8")).get("sk_walls"))
    for f in files:
        sc = json.loads(f.read_text(encoding="utf-8"))
        sc["edge_walls"] = edge_walls(sc)
        f.write_text(json.dumps(sc), encoding="utf-8")
        print(f"{f.name}: {len(sc['nav']['t'])} floor triangles + {len(sc.get('floor_patch') or [])} patch → "
              f"{len(sc['edge_walls'])} edge walls")


if __name__ == "__main__":
    main()
