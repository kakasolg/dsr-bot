"""corner offline test — turning corners: arrival radius at corners (nav.path_tolerances), and that path straightening
(navmesh.simplify) already keeps off the inside corner. A synthetic L-shaped corridor NavMesh, no game files.

  python tests/corner_test.py
"""
from __future__ import annotations

import math
import sys

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

import nav
import navmesh

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


def rect_mesh(rects: list[tuple[float, float, float, float]]) -> navmesh.Navmesh:
    """Flat NavMesh (y = 0) from rectangles (x0, z0, x1, z1) sharing whole edges, two big faces each (like real NavMesh
    faces, larger than the 0.5 m check step). Adjacency by shared edges."""
    vid: dict[tuple[float, float], int] = {}
    verts, tris = [], []

    def v(x, z):
        if (x, z) not in vid:
            vid[(x, z)] = len(verts)
            verts.append((x, 0.0, z))
        return vid[(x, z)]

    for x0, z0, x1, z1 in rects:
        a, b, c, d = v(x0, z0), v(x1, z0), v(x1, z1), v(x0, z1)
        tris += [(a, b, c), (a, c, d)]
    edges: dict[tuple[int, int], list[int]] = {}
    for ti, t in enumerate(tris):
        for e in ((t[0], t[1]), (t[1], t[2]), (t[0], t[2])):
            edges.setdefault(tuple(sorted(e)), []).append(ti)
    adj = []
    for ti, t in enumerate(tris):
        n = []
        for e in ((t[0], t[1]), (t[1], t[2]), (t[0], t[2])):
            n += [x for x in edges[tuple(sorted(e))] if x != ti]
        adj.append((n + [-1, -1, -1])[:3])
    m = navmesh.Navmesh.__new__(navmesh.Navmesh)
    m.map_id = "test_L"
    m.v, m.t = np.array(verts, float), np.array(tris)
    m.flags, m.piece, m.adj = np.zeros(len(tris), int), np.zeros(len(tris), int), np.array(adj)
    m.centroid = (m.v[m.t[:, 0]] + m.v[m.t[:, 1]] + m.v[m.t[:, 2]]) / 3.0
    m.a, m.b, m.c = m.v[m.t[:, 0]], m.v[m.t[:, 1]], m.v[m.t[:, 2]]
    m._gates = []
    m.model_tri_offset = {}
    return m


# L corridor 3 m wide: east arm x 0..10, z 0..3, then north arm x 7..10, z 0..10. Inside corner at (7, 3).
L = rect_mesh([(0.0, 0.0, 7.0, 3.0), (7.0, 0.0, 10.0, 3.0), (7.0, 3.0, 10.0, 10.0)])   # east arm, corner square, north arm
INNER = (7.0, 3.0)
mid = [(x + 0.63, 0.0, 1.63) for x in range(0, 8)] + [(8.63, 0.0, z + 0.63) for z in range(1, 10)]   # corridor centre, off the grid lines


def seg_dist(p, a, b):
    ax, az, bx, bz = a[0], a[2], b[0], b[2]
    dx, dz = bx - ax, bz - az
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - az) * dz) / (dx * dx + dz * dz or 1)))
    return math.hypot(ax + t * dx - p[0], az + t * dz - p[1])


def clearance(path):
    return min(seg_dist(INNER, path[k], path[k + 1]) for k in range(len(path) - 1))


print("경로 펴기 (navmesh.simplify)")
out = L.simplify(mid)
check(f"L자 통로: 짧게 펴지고 모퉁이 안쪽에서 몸 폭 이상 떨어짐 ({len(mid)} → {len(out)}점, {clearance(out):.2f} m)",
      len(out) <= 4 and clearance(out) >= 0.4)
check("곧은 통로는 그대로 한 줄", L.simplify([(0.63, 0.0, 1.63), (3.63, 0.0, 1.63), (6.63, 0.0, 1.63)]) == [(0.63, 0.0, 1.63), (6.63, 0.0, 1.63)])
check("모퉁이를 가로지르는 선은 거절 (연결 안 된 면으로 건너뜀)", not L.clear_line((5.0, 0, 2.8), (8.0, 0, 3.4)))

print("모퉁이 도착 판정 (nav.path_tolerances)")
t = nav.path_tolerances(mid, 1.0)
corner_i = [i for i, x in enumerate(t) if x == nav.CORNER_TOL]
check(f"꺾이는 곳만 {nav.CORNER_TOL} m ({corner_i})", corner_i and all(6 <= i <= 10 for i in corner_i))
check("곧은 곳은 기본값, 마지막 점은 TIGHT_TOL", t[2] == 1.0 and t[-2] == 1.0 and t[-1] == nav.TIGHT_TOL)
rec = nav.path_tolerances([(0, 5.0, 0), (1, 0.0, 0), (2, 0.0, 0), (3, 0.0, 0)], 0.8, steep=False)
check("녹화 경로(steep=False)는 계단 규칙 없이 0.8 m", rec[:3] == [0.8, 0.8, 0.8])
check("turn_deg: 직각 90°, 직선 0°", abs(nav.turn_deg(mid, 8) - 90) < 50 and nav.turn_deg(mid, 3) < 1)

print("전부 통과" if not fails else f"실패 {fails}")
sys.exit(1 if fails else 0)
