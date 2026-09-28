"""NavMesh faces near the player for the radar — where the floor is, where it ends (wall or drop), ladders and doors.

radar_server.py runs on the PC with the game, so it reads the NavMesh straight from the install folder through
navmesh.Navmesh (nothing is exported or committed). /state gets "mesh": faces within MESH_R m and MESH_DY m of height:
  [ax, az, bx, bz, cx, cz, dy, edges, flags]
  dy     face height minus the player's (m, 1 decimal) — the page shades by it (same floor / above / below)
  edges  bit k set = edge k ((a,b), (b,c), (a,c)) has no face on the other side = the end of the floor
         (computed from shared vertex positions over the whole map, so seams between NavMesh pieces aren't shown as walls)
  flags  NavMesh flags (navmesh.FLAGS: 1024 ladder, 4096 door, 2048 hole …)
"""
from __future__ import annotations

import math

import numpy as np

MESH_R = 30.0
MESH_DY = 6.0
CELL = 2.0            # the answer is cached per 2 m cell of the player's position (and 0.5 m of height)


class MeshView:
    def __init__(self, meshes: list):
        self.parts = []
        for m in meshes:
            v, t = m.v, m.t
            a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
            cen = (a + b + c) / 3.0
            key = lambda p: (round(float(p[0]), 2), round(float(p[1]), 1), round(float(p[2]), 2))
            count: dict[tuple, int] = {}
            edges = []
            for i in range(len(t)):
                pts = (key(a[i]), key(b[i]), key(c[i]))
                es = [tuple(sorted((pts[0], pts[1]))), tuple(sorted((pts[1], pts[2]))), tuple(sorted((pts[0], pts[2])))]
                edges.append(es)
                for e in es:
                    count[e] = count.get(e, 0) + 1
            border = np.array([sum(1 << k for k, e in enumerate(es) if count[e] == 1) for es in edges], dtype=int)
            self.parts.append((a, b, c, cen, border, np.asarray(m.flags, dtype=int)))
        self._cache_key = None
        self._cache: list = []

    def near(self, x: float, y: float, z: float) -> list[list]:
        k = (math.floor(x / CELL), round(y * 2), math.floor(z / CELL))     # height to 0.5 m: dy is relative to it
        if k == self._cache_key:
            return self._cache
        out = []
        for a, b, c, cen, border, flags in self.parts:
            sel = np.where((np.abs(cen[:, 0] - x) < MESH_R) & (np.abs(cen[:, 2] - z) < MESH_R)
                           & (np.abs(cen[:, 1] - y) < MESH_DY))[0]
            for i in sel:
                out.append([round(float(a[i, 0]), 2), round(float(a[i, 2]), 2), round(float(b[i, 0]), 2), round(float(b[i, 2]), 2),
                            round(float(c[i, 0]), 2), round(float(c[i, 2]), 2), round(float(cen[i, 1] - y), 1),
                            int(border[i]), int(flags[i])])
        self._cache_key, self._cache = k, out
        return out


def load(map_ids: list[str]) -> "MeshView | None":
    """MeshView over the maps whose NavMesh can be read here (game install found), or None."""
    meshes = []
    try:
        import navmesh
    except Exception:
        return None
    for mid in map_ids:
        try:
            meshes.append(navmesh.Navmesh(mid))
        except BaseException:          # navmesh raises SystemExit when the file is missing
            continue
    return MeshView(meshes) if meshes else None


def rect_mesh(rects: list[tuple[float, float, float, float, float]]):
    """A tiny flat NavMesh-like object from rectangles (x0, z0, x1, z1, y) — for --demo and tests."""
    class _M:
        pass
    verts, tris, vid = [], [], {}

    def vx(x, y, z):
        if (x, y, z) not in vid:
            vid[(x, y, z)] = len(verts)
            verts.append((x, y, z))
        return vid[(x, y, z)]
    for x0, z0, x1, z1, y in rects:
        p = vx(x0, y, z0), vx(x1, y, z0), vx(x1, y, z1), vx(x0, y, z1)
        tris += [(p[0], p[1], p[2]), (p[0], p[2], p[3])]
    m = _M()
    m.v, m.t, m.flags = np.array(verts, float), np.array(tris), np.zeros(len(tris), int)
    return m
