"""게임이 갖고 있는 지형 — DSR 설치 폴더의 내비메시(.nvmbnd)를 읽는다.

봇이 워프로 한 점씩 찍어 바닥 높이를 재던 것(mapmem.scan)을 대체한다. 프롬소프트가 적 AI 길찾기용으로 만든
**보행 가능 삼각형 + 인접 관계 + 의미 플래그(사다리·문·구멍·벽)**가 그대로 들어 있고, 좌표가 런타임 메모리에서
읽는 좌표와 같은 공간이다 (실측: 불의 제전 화톳불 y −59.9 vs 내비메시 −59.79, 차이 0.11 m. MSB 의 배치 변환이
전부 0 이라 변환 없이 바로 쓴다).

  python navmesh.py info  <맵ID>            삼각형 수·범위·플래그 분포
  python navmesh.py render <맵ID> [out]     위에서 내려다본 지형도 HTML (높이=색)
  python navmesh.py at <맵ID> <x> <z>       그 자리의 바닥 높이 후보
  python navmesh.py path <맵ID> <x y z> <x y z> [out]   두 지점 사이 A* 경로 (조각 사이는 MCG 게이트로 연결)

맵 ID: m10_02_00_00 = 불의 제전(+묘지), m10_01_00_00 = 성벽 마을, m18_01_00_00 = 북쪽 불사자 아스라이 등.

── 알려진 한계 ──────────────────────────────
 · 내비메시는 **적 AI 가 다닐 수 있는 면**이라 플레이어가 갈 수 있는 모든 곳을 덮지는 않는다.
 · 실제 지형을 단순화한 근사라 계단 같은 곳은 평평한 면 하나로 뭉갠다 (실측: 워프 스캔과 중앙값 0.25 m 차이,
   다층 구조 지점에선 몇 m 까지 벌어짐).
 · 조각(NVM) 하나 안에서만 인접 정보가 있다. 조각끼리의 연결은 같은 폴더의 .mcg(게이트 노드) 가 갖고 있다.
"""
from __future__ import annotations

import math
import sys
import types
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

# soulstruct 휠에 emedf JSON 이 빠져 있어 events 임포트가 깨진다 — 지형만 읽으므로 빈 모듈로 대체
for _n in ("soulstruct.darksouls1r.events", "soulstruct.darksouls1ptde.events",
           "soulstruct.darksouls1r.ai", "soulstruct.darksouls1r.ezstate"):
    sys.modules.setdefault(_n, types.ModuleType(_n))

GAME_DIR = Path(r"D:/SteamLibrary/steamapps/common/DARK SOULS REMASTERED")

FLAGS = {1: "Disable", 2: "Exit", 4: "Obstacle", 8: "Wall", 16: "Degenerate", 32: "FloorBeneathWall",
         64: "LandingPoint", 128: "Event", 256: "Edge", 512: "LargeSpace", 1024: "Ladder", 2048: "Hole",
         4096: "Door", 8192: "ClosedDoor", 16384: "BlockExit", 32768: "InsideWall"}
BLOCKED = 1 | 16          # Disable, Degenerate — 길찾기에서 제외
# 낙사 회피용 가장자리 비용 — **지금은 꺼 둔다(1.0)**.
# 내비메시만으로는 낭떠러지와 벽을 구분할 수 없다: 둘 다 그냥 "면이 없음"으로 보인다.
# 실측(불의 제전): 걸을 수 있는 면 2111 중 1629 가 경계, 그중 1365 가 "낭떠러지"로 판정됐다 — 대부분은 벽이다.
# 제대로 하려면 실제 충돌 데이터(map/*.hkxbhd 의 Havok 메시)나, 그 구간만 워프 스캔(고체/허공은 충돌 기반이라 정확)이 필요하다.
EDGE_PENALTY = 1.0
MAX_SIMPLIFY_SLOPE = 0.25
PUSH_MAX_DY = 1.0           # keep_inside 가 민 점의 바닥 높이가 이보다 바뀌면 다른 층 — 밀지 않는다
CLIFF_MARGIN = 2.2          # 실측된 낭떠러지 점에서 경로를 이만큼 떼어 놓는다 (cliffscan.py)   # 이보다 가파른 구간은 단순화하지 않고 원래 점을 남긴다 (계단·경사를 따라가야 한다)
CELL = 0.5


class Navmesh:
    """한 맵의 내비메시 전체 (조각들을 하나로 합침)."""

    def __init__(self, map_id: str, game_dir: Path | str = GAME_DIR):
        from soulstruct.darksouls1r.maps.navmesh import NVMBND
        path = Path(game_dir) / "map" / map_id / f"{map_id}.nvmbnd.dcx"
        if not path.exists():
            raise SystemExit(f"내비메시 없음: {path}")
        bnd = NVMBND.from_path(path)
        # 조각마다 MSB 배치(이동·Y 회전)를 적용한다 — 불의 제전·성벽 마을은 전부 0 이라 몰랐는데, 수용소(m18_01)는
        # 조각이 전부 y +200 에 놓여 있어 게임 좌표와 200 m 어긋났다 (데이터 8.4 vs 실제 184.7)
        place: dict[str, tuple] = {}
        try:
            from soulstruct.darksouls1r.maps import MSB
            msb = MSB.from_path(Path(game_dir) / "map" / "MapStudio" / f"{map_id}.msb")
            for p in msb.navmeshes:
                place[p.model.name] = ((p.translate.x, p.translate.y, p.translate.z), p.rotate.y)
        except Exception:
            pass
        verts, tris, flags, piece, adj = [], [], [], [], []
        self.model_tri_offset: dict[str, int] = {}   # 조각 모델 이름 → 전역 삼각형 번호 시작점
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
        self.adj = np.array(adj)                                  # 조각 **안**에서의 이웃 삼각형 (조각끼리는 MCG 가 잇는다)
        self.centroid = (self.v[self.t[:, 0]] + self.v[self.t[:, 1]] + self.v[self.t[:, 2]]) / 3.0
        self._gates: list[list[int]] | None = None
        self.a, self.b, self.c = self.v[self.t[:, 0]], self.v[self.t[:, 1]], self.v[self.t[:, 2]]

    def __len__(self) -> int:
        return len(self.t)

    def walkable(self) -> np.ndarray:
        return (self.flags & BLOCKED) == 0

    def tris_at(self, x: float, z: float) -> list[tuple[float, int, int]]:
        """(x,z) 을 위에서 내려다봤을 때 걸치는 삼각형들 → [(바닥 높이, 플래그, 삼각형 번호)] 높은 순."""
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
        """near_y 에 가장 가까운 바닥 — 다층 구조(육교 아래 등)에서 지금 있는 층을 고른다."""
        hit = self.floor_tri_at(x, z, near_y)
        return (hit[0], hit[1]) if hit else None

    def floor_tri_at(self, x: float, z: float, near_y: float) -> tuple[float, int, int] | None:
        """floor_at 과 같되 삼각형 번호까지 — 두 지점이 실제로 이어진 면인지 보려면 번호가 필요하다."""
        cands = [(y, f, i) for y, f, i in self.tris_at(x, z) if not (f & BLOCKED)]
        return min(cands, key=lambda c: abs(c[0] - near_y)) if cands else None

    def gates(self, game_dir: Path | str = GAME_DIR) -> list[list[int]]:
        """MCG 게이트 — 조각(NVM)끼리 이어 주는 문. 각 게이트는 서로 통하는 삼각형 묶음이다.

        NVM 의 connected_indices 는 같은 조각 안에서만 이웃을 안다. 조각 사이는 같은 폴더의 .mcg 가 갖고 있고,
        엣지마다 (지나가는 조각, 양 끝 노드, 각 노드에 닿는 삼각형들)을 준다. 한 노드에 모이는 삼각형끼리는
        서로 통한다 — 그게 곧 조각 사이의 통로다."""
        if self._gates is not None:
            return self._gates
        from soulstruct.darksouls1r.maps.navmesh import MCG
        from soulstruct.darksouls1r.maps import MSB
        game_dir = Path(game_dir)
        mcg = MCG.from_path(game_dir / "map" / self.map_id / f"{self.map_id}.mcg")
        msb = MSB.from_path(game_dir / "map" / "MapStudio" / f"{self.map_id}.msb")
        models = [p.model.name for p in msb.navmeshes]            # MCG 의 navmesh_index 는 MSB 부품 순서
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
        """이웃이 없는 면 = 내비메시의 끝 = 낭떠러지 아니면 벽. 길찾기는 여기를 비싸게 쳐서 통로 가운데로 간다."""
        return (self.adj < 0).any(axis=1) | ((self.flags & 256) != 0)   # 256 = Edge

    def cliffs(self, drop: float = 3.0, out: float = 0.8) -> np.ndarray:
        """**낭떠러지에 닿은 면**. 이웃 없는 변 바깥으로 out m 나가 봐서, 거기 바닥이 drop m 넘게 아래거나
        아예 없으면 낭떠러지로 본다. 벽 경계와 구분하려는 것 — 내비메시 면의 77 %가 어떤 식으로든 경계라
        경계 전체를 피하면 길이 없어진다. 결과는 파일에 캐시한다 (한 맵 한 번만 계산)."""
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
        """**맞닿은 조각을 잇는다** — 서로 다른 NVM 조각의 열린 변이 거의 같은 자리에 있으면 통한다고 본다.

        MCG 게이트만으로는 부족하다. 게이트는 적 AI 가 실제로 다니는 길만 잇기 때문에, 조각이 물리적으로
        맞닿아 있어도 그래프가 끊긴다 — 실측: 성벽 교회는 연결 성분 58개, 어둠숲은 20개로 쪼개져
        캐릭터가 선 조각(183개)에서 어디로도 길을 못 뽑았다. 불의 제전은 우연히 MCG 만으로 이어졌을 뿐."""
        if getattr(self, "_seams", None) is not None:
            return self._seams
        buckets: dict = {}
        for i in range(len(self.t)):
            vi = self.t[i]
            for e, (a, b) in enumerate(((0, 1), (1, 2), (0, 2))):
                if self.adj[i][e] >= 0:
                    continue                                  # 조각 안에서 이미 이어진 변
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
        """삼각형 단위 길찾기 그래프 — 조각 안은 NVM 인접, 조각 사이는 MCG 게이트.

        **낭떠러지에 닿은 면**으로 들어가는 비용에 edge_penalty 를 곱한다. 벼랑길에서 굳이 바깥쪽으로
        붙지 않게 — DS1 은 좁은 길이 많아 낙사가 흔하고, 봇은 점프로 복구할 수단이 없다 (사용자 경고).
        벽 경계까지 피하면 길이 없어지므로 cliffs() 로 진짜 낭떠러지만 고른다."""
        ok = (self.flags & (BLOCKED | 8 | 2048)) == 0             # Disable/Degenerate/Wall/Hole 제외
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
        for i, j in self.seams():                              # 맞닿은 조각 잇기
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

    # ── 복구 (2026-09-25 층 설계 1단계: "0층이 복구를 책임진다") ──
    def walkable_mask(self) -> np.ndarray:
        return (self.flags & (BLOCKED | 8 | 2048)) == 0             # Disable/Degenerate/Wall/Hole 제외

    def on_mesh(self, x: float, y: float, z: float, dy: float = 1.0) -> bool:
        """그 자리 발밑에 걸을 수 있는 바닥이 dy 안에 있나. 경사로 아래 (-24.5,-48.3,26.0) 은 False (내비메시 밖 주머니)."""
        f = self.floor_at(x, z, y)
        return f is not None and abs(f[0] - y) <= dy and (int(f[1]) & (BLOCKED | 8 | 2048)) == 0

    def nearest_walkable(self, x: float, y: float, z: float, r: float = 8.0, dy: float = 2.5):
        """높이차 dy 안, 반경 r 안에서 가장 가까운 걸을 수 있는 삼각형 무게중심 → (x, y, z) 또는 None.
        메시 밖에 서 있을 때 돌아갈 곳. 높이차를 보는 이유: 2.3 m 위 턱의 삼각형이 3D 로는 더 가까워 보였다."""
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
        """경로에 걸어서 못 오르는 단차가 있나 → 그 구간 번호. 경사로(기울기 ~1)는 통과, 2.3 m 위 턱(기울기 >1.2)은 걸린다."""
        for i in range(1, len(path)):
            a, b = path[i - 1], path[i]
            dy = b[1] - a[1]
            horiz = max(0.05, ((b[0] - a[0]) ** 2 + (b[2] - a[2]) ** 2) ** 0.5)
            if dy > dy_min and dy / horiz > slope_min:
                return i
        return None

    def nearest_tri(self, x: float, y: float, z: float) -> int:
        """그 지점을 덮는 삼각형 중 높이가 가장 가까운 것. 없으면 무게중심이 가장 가까운 삼각형."""
        cands = [(abs(ty - y), ti) for ty, f, ti in self.tris_at(x, z) if not (f & BLOCKED)]
        if cands:
            return min(cands)[1]
        d = np.linalg.norm(self.centroid - np.array([x, y, z]), axis=1)
        return int(d.argmin())

    def find_path(self, start: tuple[float, float, float], goal: tuple[float, float, float]) -> list[tuple[float, float, float]]:
        """A* — 삼각형 무게중심을 잇는 경로점 목록. 길이 없으면 빈 목록."""
        import heapq
        # 시작·끝이 메시 밖이면 같은 높이의 가장 가까운 걸을 수 있는 점으로 보정 (없으면 길 없음).
        # 예전엔 3D 로 가장 가까운 삼각형을 잡아 2.3 m 위 턱에서 출발하는 경로가 나왔다 (경사로 아래 주머니, 2026-09-24)
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
        if self.ledge_step(out) is not None:                  # 걸어서 못 오르는 단차 — 길 없음으로 (위 층이 다른 수를 찾게)
            return []
        return out

    def clear_line(self, p0, p1, step: float = 0.5, max_dy: float = 0.8, max_step: float = 0.5) -> bool:
        """두 점을 잇는 직선 위를 걸어도 되는가.

        step 마다 (a) 그 자리에 걸을 수 있는 바닥이 있고 (b) 그 높이가 직선 높이에서 max_dy 안이며
        (c) 바로 앞 샘플과의 높이 차가 max_step 안이고 (d) **바로 앞 샘플의 삼각형과 실제로 이어져 있어야** 한다.

        (d) 가 핵심이다. 높이만 보면(c) 테라스 위 바닥에서 아래 바닥으로 값이 부드럽게 이어지는 것처럼 보여서
        사이의 수직 벽을 못 본다. 실측: 화톳불 광장을 둘러싼 돌 단을 가로지르는 직선이 통과돼서, 점프를 못 하는
        봇이 8 m 앞 턱에 걸려 멈췄다 (화면 캡처로 확인). 삼각형이 이웃인지 보면 그 벽이 드러난다."""
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
                return False          # 이웃이 아닌 면으로 건너뛰었다 = 사이에 벽/단차가 있다
            prev_y, prev_tri = hit[0], hit[2]
        return True

    def keep_inside(self, path: list, margin: float = 1.2) -> list:
        """경로점을 내비메시 **경계에서 떼어 놓는다** — 통로 한가운데로 걷게 한다.

        경계가 벽인지 낭떠러지인지는 내비메시만으로 구분할 수 없지만(둘 다 "면이 없음"), 구분할 필요가 없다.
        벽이면 끼임이 줄고 낭떠러지면 낙사가 준다. 삼각형 무게중심을 잇는 경로는 경계에 바짝 붙기 쉬운데,
        DS1 은 좁은 길이 많고 봇은 점프로 복구할 수단이 없다 (사용자: 낙사 반복).

        각 점에서 경계 변이 margin 안에 있으면 그 변의 반대쪽으로 민다. 삼각형 밖으로 나가지 않게 절반만."""
        try:
            import cliffscan
            known = cliffscan.load(self.map_id)
        except Exception:
            known = []
        out = []
        for q in path:
            # 실측으로 확인된 낭떠러지 점에서 먼저 밀어낸다 (내비메시 경계만으로는 벽과 구분이 안 된다)
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
                    continue                      # 이웃이 있는 변 = 안쪽
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
            # 민 자리에 같은 층 바닥이 없으면 밀지 않는다 — 계단 옆에서 밀려 나가 8 m 위 통로 바닥을 잡았고,
            # ledge_step 이 그걸 못 오르는 턱으로 보고 길 전체를 버렸다 (성벽 마을 #4~6 no_path, 2026-09-25 사용자 경로 대조)
            ok = inside is not None and abs(inside[0] - q[1]) <= PUSH_MAX_DY
            out.append((nq[0], inside[0], nq[2]) if ok else q)
        return out

    def simplify(self, path: list, step: float = 0.5, max_dy: float = 0.8,
                 max_slope: float = MAX_SIMPLIFY_SLOPE) -> list:
        """삼각형 무게중심을 이은 지그재그를 곧게 편다 (string pulling).

        **오르내리는 구간은 펴지 않는다.** 계단·경사를 긴 대각선 하나로 뭉치면 봇이 계단을 따라가는 대신
        비스듬히 벽으로 밀게 된다 — 실측: 수평 11.8 m 를 가며 4.6 m 오르는 구간이 한 점으로 합쳐져
        봇이 그 앞(y≈−48)에서 더 못 올라갔다 (사용자 지적: "어디서 올라가고 내려가는지 인식이 없다")."""
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
        """위에서 내려다본 지형도 — 삼각형을 높이 색으로 칠한다 (사람이 위키 지도와 대조하는 용도)."""
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
