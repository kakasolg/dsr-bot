"""Terrain the game itself has — reads the NavMesh (.nvmbnd) from the DSR install folder.

Replaces having the bot warp point by point to measure floor height (mapmem.scan). It contains as-is what FromSoftware built
for enemy AI pathfinding — **walkable triangles + adjacency + semantic flags (ladder/door/hole/wall)** — in the same space as
coordinates read from runtime memory (measured: Firelink Shrine bonfire y −59.9 vs NavMesh −59.79, 0.11 m difference. MSB placement
transforms are all 0, so it is used directly without transform).

  python navmesh.py info  <mapID>            triangle count, bounds, flag distribution
  python navmesh.py render <mapID> [out]     top-down terrain map HTML (height = color)
  python navmesh.py at <mapID> <x> <z>       floor height candidates at that spot
  python navmesh.py path <mapID> <x y z> <x y z> [out]   A* path between two points (pieces connected via MCG gates)

Map IDs: m10_02_00_00 = Firelink Shrine (+graveyard), m10_01_00_00 = Undead Burg, m18_01_00_00 = Northern Undead Asylum, etc.

── Known limitations ──────────────────────────────
 · The NavMesh is **surfaces enemy AI can traverse**, so it doesn't cover everywhere the player can go.
 · It is a simplified approximation of real terrain, flattening things like stairs into one flat surface (measured: median 0.25 m difference from warp scan,
   up to several m at multi-level spots).
 · Adjacency exists only within one piece (NVM). Connections between pieces are in the .mcg (gate nodes) in the same folder.
"""
from __future__ import annotations

import math
import os
import sys
import types
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

# the soulstruct wheel lacks the emedf JSON so importing events breaks — we only read terrain, so replace with empty modules
for _n in ("soulstruct.darksouls1r.events", "soulstruct.darksouls1ptde.events",
           "soulstruct.darksouls1r.ai", "soulstruct.darksouls1r.ezstate"):
    sys.modules.setdefault(_n, types.ModuleType(_n))

GAME_DIR = Path(os.environ.get("DSR_GAME_DIR") or r"D:/SteamLibrary/steamapps/common/DARK SOULS REMASTERED")

FLAGS = {1: "Disable", 2: "Exit", 4: "Obstacle", 8: "Wall", 16: "Degenerate", 32: "FloorBeneathWall",
         64: "LandingPoint", 128: "Event", 256: "Edge", 512: "LargeSpace", 1024: "Ladder", 2048: "Hole",
         4096: "Door", 8192: "ClosedDoor", 16384: "BlockExit", 32768: "InsideWall"}
BLOCKED = 1 | 16          # Disable, Degenerate — excluded from pathfinding
# Edge cost for fall avoidance — **currently disabled (1.0)**.
# The NavMesh alone can't distinguish cliffs from walls: both just look like "no surface".
# Measured (Firelink Shrine): of 2111 walkable faces, 1629 are border, of which 1365 were judged "cliff" — most are walls.
# Doing it properly needs real collision data (Havok meshes in map/*.hkxbhd) or a warp scan of just that section (solid/void is collision-based, so accurate).
EDGE_PENALTY = 1.0
MAX_SIMPLIFY_SLOPE = 0.25
PUSH_MAX_DY = 1.0           # if the floor height at the point keep_inside pushed changes by more than this, it's another level — don't push
CLIFF_MARGIN = 2.2          # keep the path this far from measured cliff points (cliffscan.py)   # sections steeper than this are not simplified and keep original points (must follow stairs/slopes)
CELL = 0.5


class Navmesh:
    """Whole NavMesh of one map (pieces merged into one)."""

    def __init__(self, map_id: str, game_dir: Path | str = GAME_DIR):
        from soulstruct.darksouls1r.maps.navmesh import NVMBND
        path = Path(game_dir) / "map" / map_id / f"{map_id}.nvmbnd.dcx"
        if not path.exists():
            raise SystemExit(f"내비메시 없음: {path}")
        bnd = NVMBND.from_path(path)
        # apply MSB placement (translate, Y rotation) per piece — Firelink Shrine/Undead Burg are all 0 so it went unnoticed, but in the Asylum (m18_01)
        # every piece sits at y +200, 200 m off from game coordinates (data 8.4 vs actual 184.7)
        place: dict[str, tuple] = {}
        try:
            from soulstruct.darksouls1r.maps import MSB
            msb = MSB.from_path(Path(game_dir) / "map" / "MapStudio" / f"{map_id}.msb")
            for p in msb.navmeshes:
                place[p.model.name] = ((p.translate.x, p.translate.y, p.translate.z), p.rotate.y)
        except Exception:
            pass
        verts, tris, flags, piece, adj = [], [], [], [], []
        self.model_tri_offset: dict[str, int] = {}   # piece model name → global triangle index start
        off = t_off = 0
        for i, entry in enumerate(bnd.entries):
            stem = entry.name.replace(".nvm", "")
            nvm = bnd.get_nvm(stem)
            v = np.asarray(nvm.vertices, dtype=np.float64)
            pl = next((place[k] for k in place if stem.startswith(k)), None)
            if pl is not None:
                (tx, ty, tz), ry = pl
                if abs(ry) > 1e-6:
                    a = np.radians(ry)
                    ca, sa = np.cos(a), np.sin(a)
                    x, z = v[:, 0].copy(), v[:, 2].copy()
                    v[:, 0], v[:, 2] = ca * x + sa * z, -sa * x + ca * z
                v = v + np.array([tx, ty, tz])
            verts.append(v)
            self.model_tri_offset[stem] = t_off
            for t in nvm.triangles:
                tris.append([j + off for j in t.vertex_indices])
                flags.append(t.flags)
                piece.append(i)
                adj.append([(c + t_off) if c >= 0 else -1 for c in t.connected_indices])
            off += len(v)
            t_off += len(nvm.triangles)
        self.map_id = map_id
        self.v = np.vstack(verts)
        self.t = np.array(tris)
        self.flags = np.array(flags)
        self.piece = np.array(piece)
        self.adj = np.array(adj)                                  # neighbor triangles **within** a piece (MCG connects pieces)
        self.centroid = (self.v[self.t[:, 0]] + self.v[self.t[:, 1]] + self.v[self.t[:, 2]]) / 3.0
        self._gates: list[list[int]] | None = None
        self.a, self.b, self.c = self.v[self.t[:, 0]], self.v[self.t[:, 1]], self.v[self.t[:, 2]]

    def __len__(self) -> int:
        return len(self.t)

    def walkable(self) -> np.ndarray:
        return (self.flags & BLOCKED) == 0

    def tris_at(self, x: float, z: float) -> list[tuple[float, int, int]]:
        """Triangles covering (x,z) seen from above → [(floor height, flags, triangle index)] highest first."""
        a, b, c = self.a, self.b, self.c
        d1 = (b[:, 0] - a[:, 0]) * (z - a[:, 2]) - (b[:, 2] - a[:, 2]) * (x - a[:, 0])
        d2 = (c[:, 0] - b[:, 0]) * (z - b[:, 2]) - (c[:, 2] - b[:, 2]) * (x - b[:, 0])
        d3 = (a[:, 0] - c[:, 0]) * (z - c[:, 2]) - (a[:, 2] - c[:, 2]) * (x - c[:, 0])
        idx = np.where(((d1 >= 0) & (d2 >= 0) & (d3 >= 0)) | ((d1 <= 0) & (d2 <= 0) & (d3 <= 0)))[0]
        out = []
        for i in idx:
            p0 = self.v[self.t[i, 0]]
            n = np.cross(self.v[self.t[i, 1]] - p0, self.v[self.t[i, 2]] - p0)
            y = p0[1] if abs(n[1]) < 1e-9 else p0[1] - (n[0] * (x - p0[0]) + n[2] * (z - p0[2])) / n[1]
            out.append((float(y), int(self.flags[i]), int(i)))
        return sorted(out, reverse=True)

    def floor_at(self, x: float, z: float, near_y: float) -> tuple[float, int] | None:
        """Floor closest to near_y — picks the current level in multi-level structures (e.g. under a bridge)."""
        hit = self.floor_tri_at(x, z, near_y)
        return (hit[0], hit[1]) if hit else None

    def floor_tri_at(self, x: float, z: float, near_y: float) -> tuple[float, int, int] | None:
        """Same as floor_at but with the triangle index — needed to check whether two points are on actually connected faces."""
        cands = [(y, f, i) for y, f, i in self.tris_at(x, z) if not (f & BLOCKED)]
        return min(cands, key=lambda c: abs(c[0] - near_y)) if cands else None

    def gates(self, game_dir: Path | str = GAME_DIR) -> list[list[int]]:
        """MCG gates — doors connecting pieces (NVM). Each gate is a group of mutually connected triangles.

        NVM connected_indices only knows neighbors within the same piece. Between pieces, the .mcg in the same folder has it:
        per edge it gives (piece traversed, both end nodes, triangles touching each node). Triangles gathered at one node are
        mutually connected — that is the passage between pieces."""
        if self._gates is not None:
            return self._gates
        from soulstruct.darksouls1r.maps.navmesh import MCG
        from soulstruct.darksouls1r.maps import MSB
        game_dir = Path(game_dir)
        mcg = MCG.from_path(game_dir / "map" / self.map_id / f"{self.map_id}.mcg")
        msb = MSB.from_path(game_dir / "map" / "MapStudio" / f"{self.map_id}.msb")
        models = [p.model.name for p in msb.navmeshes]            # MCG navmesh_index follows MSB part order
        node_tris: dict[int, set[int]] = {}
        for e in mcg.edges:
            ni = e.navmesh_index
            if ni is None or ni >= len(models):
                continue
            base = None
            for stem, off in self.model_tri_offset.items():
                if stem.startswith(models[ni]):
                    base = off
                    break
            if base is None:
                continue
            for node, local_tris in ((e.node_a, e.node_a_triangles), (e.node_b, e.node_b_triangles)):
                key = id(node)
                node_tris.setdefault(key, set()).update(base + t for t in local_tris)
        self._gates = [sorted(v) for v in node_tris.values() if len(v) > 1]
        return self._gates

    def border(self) -> np.ndarray:
        """Faces with no neighbor = end of the NavMesh = cliff or wall. Pathfinding makes them expensive so it goes through the middle of passages."""
        return (self.adj < 0).any(axis=1) | ((self.flags & 256) != 0)   # 256 = Edge

    def cliffs(self, drop: float = 3.0, out: float = 0.8) -> np.ndarray:
        """**Faces touching a cliff**. Step out m outside each neighborless edge; if the floor there is more than drop m below
        or absent, treat as cliff. Meant to distinguish from wall borders — 77 % of NavMesh faces are border in some way,
        so avoiding all borders leaves no path. Result is cached to a file (computed once per map)."""
        import json
        cache = Path(__file__).parent / "data" / "maps" / f"{self.map_id}-cliffs.json"
        if cache.exists():
            idx = json.loads(cache.read_text(encoding="utf-8"))
            m = np.zeros(len(self.t), dtype=bool)
            m[idx] = True
            return m
        mask = np.zeros(len(self.t), dtype=bool)
        for i in range(len(self.t)):
            vi = self.t[i]
            c = self.centroid[i]
            for e, (a, b) in enumerate(((0, 1), (1, 2), (0, 2))):
                if self.adj[i][e] >= 0:
                    continue
                mid = (self.v[vi[a]] + self.v[vi[b]]) / 2.0
                d = mid - c
                n = float(np.hypot(d[0], d[2]))
                if n < 1e-6:
                    continue
                q = mid + np.array([d[0] / n * out, 0.0, d[2] / n * out])
                below = [y for y, f, _ in self.tris_at(float(q[0]), float(q[2])) if y < mid[1] + 0.5]
                if not below or (mid[1] - max(below)) > drop:
                    mask[i] = True
                    break
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps([int(i) for i in np.where(mask)[0]]), encoding="utf-8")
        return mask

    def seams(self, tol: float = 0.6) -> list[tuple[int, int]]:
        """**Join touching pieces** — if open edges of different NVM pieces are at nearly the same spot, treat them as connected.

        MCG gates alone aren't enough. Gates only connect routes enemy AI actually walks, so even when pieces physically
        touch, the graph is cut — measured: Undead Parish split into 58 connected components, Darkroot into 20,
        and no path could be drawn from the piece the character stood on (183). Firelink Shrine just happened to connect via MCG alone."""
        if getattr(self, "_seams", None) is not None:
            return self._seams
        buckets: dict = {}
        for i in range(len(self.t)):
            vi = self.t[i]
            for e, (a, b) in enumerate(((0, 1), (1, 2), (0, 2))):
                if self.adj[i][e] >= 0:
                    continue                                  # edge already connected within the piece
                mid = (self.v[vi[a]] + self.v[vi[b]]) / 2.0
                key = (round(float(mid[0]) / tol), round(float(mid[1]) / tol), round(float(mid[2]) / tol))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for dz in (-1, 0, 1):
                            buckets.setdefault((key[0]+dx, key[1]+dy, key[2]+dz), []).append((i, mid))
        out, seen = [], set()
        for grp in buckets.values():
            for a in range(len(grp)):
                for b in range(a + 1, len(grp)):
                    i, mi = grp[a]
                    j, mj = grp[b]
                    if self.piece[i] == self.piece[j] or (i, j) in seen or (j, i) in seen:
                        continue
                    if float(np.linalg.norm(mi - mj)) < tol:
                        seen.add((i, j))
                        out.append((i, j))
        self._seams = out
        return out

    def graph(self, edge_penalty: float = EDGE_PENALTY) -> dict[int, list[tuple[int, float]]]:
        """Triangle-level pathfinding graph — NVM adjacency within pieces, MCG gates between pieces.

        The cost of entering **faces touching a cliff** is multiplied by edge_penalty, so it doesn't hug the outer side
        of cliff paths — DS1 has many narrow paths so falling deaths are common, and the bot can't recover by jumping (user warning).
        Avoiding wall borders too leaves no path, so cliffs() picks only real cliffs."""
        ok = (self.flags & (BLOCKED | 8 | 2048)) == 0             # exclude Disable/Degenerate/Wall/Hole
        edge = self.cliffs()
        g: dict[int, list[tuple[int, float]]] = {}
        for i in range(len(self.t)):
            if not ok[i]:
                continue
            out = []
            for j in self.adj[i]:
                if j >= 0 and ok[j]:
                    w = float(np.linalg.norm(self.centroid[i] - self.centroid[j]))
                    out.append((int(j), w * (edge_penalty if edge[j] else 1.0)))
            g[i] = out
        for i, j in self.seams():                              # join touching pieces
            if i in g and j in g:
                w = float(np.linalg.norm(self.centroid[i] - self.centroid[j]))
                g[i].append((j, w))
                g[j].append((i, w))
        for grp in self.gates():
            members = [i for i in grp if i in g]
            for i in members:
                for j in members:
                    if i != j:
                        g[i].append((j, float(np.linalg.norm(self.centroid[i] - self.centroid[j]))))
        return g

    # ── Recovery (2026-09-25 layer design step 1: "layer 0 is responsible for recovery") ──
    def walkable_mask(self) -> np.ndarray:
        return (self.flags & (BLOCKED | 8 | 2048)) == 0             # exclude Disable/Degenerate/Wall/Hole

    def on_mesh(self, x: float, y: float, z: float, dy: float = 1.0) -> bool:
        """Is there walkable floor within dy under that spot. Under the ramp (-24.5,-48.3,26.0) is False (pocket outside the NavMesh)."""
        f = self.floor_at(x, z, y)
        return f is not None and abs(f[0] - y) <= dy and (int(f[1]) & (BLOCKED | 8 | 2048)) == 0

    def border_dist(self, x: float, y: float, z: float, dy: float = 2.0) -> float:
        """Horizontal distance to the nearest NavMesh border edge (a face edge with no neighbor = wall or drop) on this level
        (edge within dy in height). inf if none. props.steer_around keeps its detour points off walls with it."""
        if getattr(self, "_bedges", None) is None:
            ti, ei = np.nonzero(self.adj < 0)
            pairs = np.array([(0, 1), (1, 2), (0, 2)])[ei]
            vi = self.t[ti]
            self._bedges = (self.v[vi[np.arange(len(ti)), pairs[:, 0]]], self.v[vi[np.arange(len(ti)), pairs[:, 1]]])
        p0, p1 = self._bedges
        if len(p0) == 0:
            return float("inf")
        seg = p1 - p0
        L2 = seg[:, 0] ** 2 + seg[:, 2] ** 2
        t = np.clip(((x - p0[:, 0]) * seg[:, 0] + (z - p0[:, 2]) * seg[:, 2]) / np.where(L2 < 1e-9, 1.0, L2), 0.0, 1.0)
        near = p0 + seg * t[:, None]
        d = np.hypot(near[:, 0] - x, near[:, 2] - z)
        d[np.abs(near[:, 1] - y) > dy] = np.inf
        return float(d.min())

    def nearest_walkable(self, x: float, y: float, z: float, r: float = 8.0, dy: float = 2.5):
        """Centroid of the nearest walkable triangle within height difference dy and radius r → (x, y, z) or None.
        Where to return when standing off the mesh. Why height difference: a triangle on a ledge 2.3 m above looked closer in 3D."""
        ok = self.walkable_mask()
        c = self.centroid
        d = np.linalg.norm(c - np.array([x, y, z]), axis=1)
        d[~ok] = np.inf
        d[np.abs(c[:, 1] - y) > dy] = np.inf
        i = int(d.argmin())
        if not np.isfinite(d[i]) or d[i] > r:
            return None
        return tuple(float(v) for v in c[i])

    @staticmethod
    def ledge_step(path: list, dy_min: float = 1.0, slope_min: float = 1.2) -> int | None:
        """Is there a height step on the path that can't be climbed on foot → that segment index. Ramps (slope ~1) pass; a ledge 2.3 m up (slope >1.2) is caught."""
        for i in range(1, len(path)):
            a, b = path[i - 1], path[i]
            dy = b[1] - a[1]
            horiz = max(0.05, ((b[0] - a[0]) ** 2 + (b[2] - a[2]) ** 2) ** 0.5)
            if dy > dy_min and dy / horiz > slope_min:
                return i
        return None

    def nearest_tri(self, x: float, y: float, z: float) -> int:
        """Among triangles covering the point, the one closest in height. If none, the triangle with the nearest centroid."""
        cands = [(abs(ty - y), ti) for ty, f, ti in self.tris_at(x, z) if not (f & BLOCKED)]
        if cands:
            return min(cands)[1]
        d = np.linalg.norm(self.centroid - np.array([x, y, z]), axis=1)
        return int(d.argmin())

    def find_path(self, start: tuple[float, float, float], goal: tuple[float, float, float]) -> list[tuple[float, float, float]]:
        """A* — list of path points joining triangle centroids. Empty list if there is no path."""
        import heapq
        # if start/end are off the mesh, snap to the nearest walkable point at the same height (no path if none).
        # previously it grabbed the nearest triangle in 3D, producing a path starting from a ledge 2.3 m above (pocket under the ramp, 2026-09-24)
        start, goal = tuple(start), tuple(goal)
        if not self.on_mesh(*start):
            s2 = self.nearest_walkable(*start)
            if s2 is None:
                return []
            start = s2
        if not self.on_mesh(*goal):
            g2 = self.nearest_walkable(*goal)
            if g2 is None:
                return []
            goal = g2
        g = self.graph()
        s, t = self.nearest_tri(*start), self.nearest_tri(*goal)
        if s not in g or t not in g:
            return []
        h = lambda i: float(np.linalg.norm(self.centroid[i] - self.centroid[t]))
        dist = {s: 0.0}
        prev: dict[int, int] = {}
        pq = [(h(s), s)]
        seen = set()
        while pq:
            _, cur = heapq.heappop(pq)
            if cur == t:
                break
            if cur in seen:
                continue
            seen.add(cur)
            for nxt, w in g[cur]:
                nd = dist[cur] + w
                if nd < dist.get(nxt, float("inf")):
                    dist[nxt] = nd
                    prev[nxt] = cur
                    heapq.heappush(pq, (nd + h(nxt), nxt))
        if t not in prev and t != s:
            return []
        seq = [t]
        while seq[-1] != s:
            seq.append(prev[seq[-1]])
        seq.reverse()
        pts = [tuple(float(c) for c in self.centroid[i]) for i in seq]
        out = self.simplify(self.keep_inside([start] + pts + [goal]))
        from souls import props as props_
        try:
            out = props_.steer_around(out, self)              # the NavMesh doesn't know crates — bend around learned props (P-12 e)
        except Exception as e:                                # never lose a path over it — keep the unbent one
            if getattr(self, "steer_log", None):
                self.steer_log(f"      물건 비켜 가기 실패 ({e!r}) — 원래 경로로")
        if self.ledge_step(out) is not None:                  # height step that can't be climbed on foot — treat as no path (so upper layers find another move)
            return []
        return out

    def clear_line(self, p0, p1, step: float = 0.5, max_dy: float = 0.8, max_step: float = 0.5) -> bool:
        """Is it OK to walk along the straight line joining two points.

        At every step, (a) there is walkable floor there, (b) its height is within max_dy of the line height,
        (c) the height difference from the previous sample is within max_step, and (d) **it is actually connected to the previous sample's triangle**.

        (d) is the key. Looking only at height (c), the floor on a terrace and the floor below seem to continue smoothly,
        missing the vertical wall between. Measured: a straight line across the stone tier around the bonfire plaza passed, and the bot,
        which can't jump, got stuck at a ledge 8 m ahead (confirmed by screen capture). Checking triangle adjacency reveals that wall."""
        p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
        d = float(np.linalg.norm(p1[[0, 2]] - p0[[0, 2]]))
        n = max(2, int(d / step))
        start = self.floor_tri_at(float(p0[0]), float(p0[2]), float(p0[1]))
        if start is None:
            return False
        prev_y, prev_tri = start[0], start[2]
        for k in range(1, n + 1):
            q = p0 + (p1 - p0) * (k / n)
            hit = self.floor_tri_at(float(q[0]), float(q[2]), float(q[1]))
            if hit is None or abs(hit[0] - q[1]) > max_dy or abs(hit[0] - prev_y) > max_step:
                return False
            if hit[2] != prev_tri and prev_tri not in self.adj[hit[2]] and hit[2] not in self.adj[prev_tri]:
                return False          # jumped to a non-neighbor face = a wall/step in between
            prev_y, prev_tri = hit[0], hit[2]
        return True

    def keep_inside(self, path: list, margin: float = 1.2) -> list:
        """**Keep path points away from** the NavMesh border — walk down the middle of passages.

        Whether a border is a wall or a cliff can't be told from the NavMesh alone (both are "no surface"), but there's no need to.
        For walls it reduces getting stuck, for cliffs it reduces falling deaths. Paths joining triangle centroids tend to hug the border,
        and DS1 has many narrow paths while the bot can't recover by jumping (user: repeated falling deaths).

        At each point, if a border edge is within margin, push away from that edge. Only half, so it doesn't leave the triangle."""
        try:
            import cliffscan
            known = cliffscan.load(self.map_id)
        except Exception:
            known = []
        out = []
        for q in path:
            # first push away from measured cliff points (NavMesh borders alone can't be distinguished from walls)
            for cx, _cy, cz in known:
                d = math.hypot(q[0] - cx, q[2] - cz)
                if d < CLIFF_MARGIN and d > 1e-6:
                    q = (q[0] + (q[0] - cx) / d * (CLIFF_MARGIN - d) * 0.8, q[1],
                         q[2] + (q[2] - cz) / d * (CLIFF_MARGIN - d) * 0.8)
            hit = self.floor_tri_at(q[0], q[2], q[1])
            if hit is None:
                out.append(q)
                continue
            ti = hit[2]
            vi = self.t[ti]
            push = np.zeros(3)
            for e, (a, b) in enumerate(((0, 1), (1, 2), (0, 2))):
                if self.adj[ti][e] >= 0:
                    continue                      # edge with a neighbor = inside
                p0, p1 = self.v[vi[a]], self.v[vi[b]]
                seg = p1 - p0
                L2 = float(seg[0] ** 2 + seg[2] ** 2)
                t = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, ((q[0] - p0[0]) * seg[0] + (q[2] - p0[2]) * seg[2]) / L2))
                near = p0 + seg * t
                d = math.hypot(q[0] - near[0], q[2] - near[2])
                if d < margin:
                    away = np.array([q[0] - near[0], 0.0, q[2] - near[2]])
                    n = math.hypot(away[0], away[2])
                    if n > 1e-6:
                        push += away / n * (margin - d) * 0.5
            nq = (q[0] + float(push[0]), q[1], q[2] + float(push[2]))
            inside = self.floor_tri_at(nq[0], nq[2], q[1])
            # if there is no same-level floor at the pushed spot, don't push — pushed off beside stairs it grabbed the walkway floor 8 m above,
            # and ledge_step saw it as an unclimbable ledge and discarded the whole path (Undead Burg #4~6 no_path, 2026-09-25 compared against the user's route)
            ok = inside is not None and abs(inside[0] - q[1]) <= PUSH_MAX_DY
            out.append((nq[0], inside[0], nq[2]) if ok else q)
        return out

    def simplify(self, path: list, step: float = 0.5, max_dy: float = 0.8,
                 max_slope: float = MAX_SIMPLIFY_SLOPE) -> list:
        """Straighten the zigzag joining triangle centroids (string pulling).

        **Sections going up/down are not straightened.** Collapsing stairs/slopes into one long diagonal makes the bot push
        diagonally into a wall instead of following the stairs — measured: a section rising 4.6 m over 11.8 m horizontal merged into one point,
        and the bot couldn't climb further in front of it (y≈−48) (user remark: "it has no awareness of where to go up and down")."""
        if len(path) <= 2:
            return list(path)

        def slope(a, b):
            h = math.hypot(b[0] - a[0], b[2] - a[2])
            return abs(b[1] - a[1]) / max(h, 1e-6)

        out = [path[0]]
        i = 0
        while i < len(path) - 1:
            j = len(path) - 1
            while j > i + 1 and (slope(path[i], path[j]) > max_slope
                                 or not self.clear_line(path[i], path[j], step, max_dy)):
                j -= 1
            out.append(path[j])
            i = j
        return out

    def flag_counts(self) -> dict[str, int]:
        out = {}
        for bit, name in FLAGS.items():
            n = int(((self.flags & bit) != 0).sum())
            if n:
                out[name] = n
        return out

    def render_html(self, out: Path | str | None = None, mark: tuple[float, float] | None = None,
                    px_per_m: float = 4.0, path: list | None = None) -> str:
        """Top-down terrain map — triangles colored by height (for a human to compare against wiki maps)."""
        w_ok = self.walkable()
        ys = self.v[:, 1]
        lo, hi = float(np.percentile(ys, 2)), float(np.percentile(ys, 98))
        x0, x1 = float(self.v[:, 0].min()), float(self.v[:, 0].max())
        z0, z1 = float(self.v[:, 2].min()), float(self.v[:, 2].max())
        W, H = (z1 - z0) * px_per_m + 20, (x1 - x0) * px_per_m + 20

        def color(y):
            t = 0.0 if hi - lo < 1e-6 else max(0.0, min(1.0, (y - lo) / (hi - lo)))
            stops = [(0.0, (26, 44, 92)), (0.35, (22, 106, 120)), (0.6, (60, 150, 90)),
                     (0.8, (170, 170, 90)), (1.0, (222, 208, 170))]
            for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
                if t <= t1:
                    f = 0 if t1 == t0 else (t - t0) / (t1 - t0)
                    return "#%02x%02x%02x" % tuple(int(p + (q - p) * f) for p, q in zip(c0, c1))
            return "#ded0aa"

        def sx(p): return (p[2] - z0) * px_per_m + 10
        def sy(p): return (p[0] - x0) * px_per_m + 10

        polys = []
        for i in range(len(self.t)):
            p0, p1, p2 = self.v[self.t[i, 0]], self.v[self.t[i, 1]], self.v[self.t[i, 2]]
            my = float((p0[1] + p1[1] + p2[1]) / 3)
            fill = color(my) if w_ok[i] else "#3a3a40"
            extra = ""
            f = int(self.flags[i])
            for bit, col in ((1024, "#e0a13a"), (4096, "#c85fd0"), (8192, "#c85fd0"), (2048, "#d04545")):
                if f & bit:
                    extra = f' stroke="{col}" stroke-width="1.5"'
                    break
            tip = f"y {my:.1f}" + ("  " + ", ".join(n for b, n in FLAGS.items() if f & b) if f else "")
            polys.append(f'<polygon points="{sx(p0):.1f},{sy(p0):.1f} {sx(p1):.1f},{sy(p1):.1f} {sx(p2):.1f},{sy(p2):.1f}" '
                         f'fill="{fill}" fill-opacity="0.85"{extra}><title>{tip}</title></polygon>')
        route = ""
        if path:
            pts = " ".join(f"{sx(p):.1f},{sy(p):.1f}" for p in path)
            route = (f'<polyline points="{pts}" fill="none" stroke="#ff3b3b" stroke-width="2.5" stroke-opacity="0.9"/>'
                     f'<circle cx="{sx(path[0]):.1f}" cy="{sy(path[0]):.1f}" r="6" fill="#4ade80"/>'
                     f'<circle cx="{sx(path[-1]):.1f}" cy="{sy(path[-1]):.1f}" r="6" fill="#ff3b3b"/>')
        marker = ""
        if mark:
            marker = (f'<circle cx="{(mark[1]-z0)*px_per_m+10:.1f}" cy="{(mark[0]-x0)*px_per_m+10:.1f}" r="7" '
                      f'fill="none" stroke="#ff5a5a" stroke-width="2.5"/>')
        legend = "".join(f'<rect x="{i*44}" y="0" width="44" height="14" fill="{color(lo+(hi-lo)*i/5)}"/>'
                         f'<text x="{i*44+22}" y="28" fill="#aaa" font-size="11" text-anchor="middle">{lo+(hi-lo)*i/5:.0f}</text>'
                         for i in range(6))
        counts = ", ".join(f"{k} {v}" for k, v in sorted(self.flag_counts().items(), key=lambda kv: -kv[1]))
        html = f"""<!doctype html><meta charset="utf-8"><title>{self.map_id} 내비메시</title>
<style>body{{background:#141416;color:#ddd;font:14px/1.6 system-ui,sans-serif;margin:24px}}
svg{{background:#1a1a1d;border:1px solid #333}} .meta{{margin:10px 0;color:#999}}</style>
<h2>{self.map_id} — 게임 내비메시 (적 AI 길찾기용 보행면)</h2>
<div class="meta">삼각형 {len(self.t)} (조각 {int(self.piece.max())+1}개) · x {x0:.0f}~{x1:.0f}, z {z0:.0f}~{z1:.0f}, y {ys.min():.0f}~{ys.max():.0f}
 · 가로=z, 세로=x · 삼각형에 마우스를 올리면 높이·플래그<br>플래그: {counts}</div>
<svg width="{W:.0f}" height="{H:.0f}">{''.join(polys)}{route}{marker}</svg>
<div class="meta">높이(m) <svg width="270" height="34">{legend}</svg>
 &nbsp; 회색 = 길찾기 제외(Disable/Degenerate) &nbsp;
 <span style="color:#e0a13a">━</span> 사다리 &nbsp; <span style="color:#c85fd0">━</span> 문 &nbsp; <span style="color:#d04545">━</span> 구멍</div>"""
        path = Path(out) if out else (Path(__file__).parent / "data" / "maps" / f"{self.map_id}-navmesh.html")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        return str(path)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "info" and len(sys.argv) >= 3:
        nm = Navmesh(sys.argv[2])
        print(f"{nm.map_id}: 삼각형 {len(nm)} (조각 {int(nm.piece.max())+1})  정점 {len(nm.v)}")
        print("범위: x %.1f..%.1f  y %.1f..%.1f  z %.1f..%.1f" % (
            nm.v[:, 0].min(), nm.v[:, 0].max(), nm.v[:, 1].min(), nm.v[:, 1].max(), nm.v[:, 2].min(), nm.v[:, 2].max()))
        print("플래그:", nm.flag_counts())
    elif cmd == "render" and len(sys.argv) >= 3:
        nm = Navmesh(sys.argv[2])
        print(nm.render_html(sys.argv[3] if len(sys.argv) >= 4 else None))
    elif cmd == "path" and len(sys.argv) >= 9:
        nm = Navmesh(sys.argv[2])
        start = tuple(float(v) for v in sys.argv[3:6])
        goal = tuple(float(v) for v in sys.argv[6:9])
        pts = nm.find_path(start, goal)
        if not pts:
            print("경로 없음")
        else:
            d = sum(float(np.linalg.norm(np.array(pts[i + 1]) - np.array(pts[i]))) for i in range(len(pts) - 1))
            print(f"경로점 {len(pts)}개  총 {d:.1f} m")
            print(nm.render_html(sys.argv[9] if len(sys.argv) >= 10 else None, path=pts))
    elif cmd == "at" and len(sys.argv) >= 5:
        nm = Navmesh(sys.argv[2])
        for y, f, i in nm.tris_at(float(sys.argv[3]), float(sys.argv[4])):
            print(f"  y {y:8.2f}  tri {i:5}  flags {f}  {', '.join(n for b, n in FLAGS.items() if f & b)}")
    else:
        print(__doc__)
