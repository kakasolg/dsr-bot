"""Which way to back off — toward where the foes are not ([MoKa] 2026-10-10).

  "20m 이내에 적이 어디 있는지 파악 하고, 없는 쪽으로 가야 하는게 기본이지. 보통 진입했던 반대 방향인데, 그것도 체크는 해야지.
   사람이라면 특히 고수라면 그렇게 하지."

Field.retreat used to walk the path home (the bonfire) whatever stood on it. pick() looks at every foe within SCAN_R
(awake ones, and idle / asleep ones that may wake), and scores places to back off to:
  T  the way we came — points on our own trail OUT_MIN … OUT_MAX m back (cleared ground; the usual answer, but checked)
  R  radial points around us at OUT_MIN / OUT_MAX on the NavMesh (another way out when the way we came is taken)
  H  the first leg of the path home (the old behaviour) — a candidate like the others
A candidate is dropped when no path reaches it, its path passes within PASS_R of an awake foe (other than the ones already
on us, near the start), or a drop edge is closer than DROP_R. The rest are scored on how far they are from the foes (awake
counts fully, idle half), with a bonus for the way we came. Path lengths come from one bounded Dijkstra from where we
stand (no find_path per candidate — 117 ms each, design-multi-foe-spot §2-c).
Pure: NavMesh + positions in, a choice out (tests/escape_test.py).
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

SCAN_R = 20.0          # foes within this (horizontal) are looked at
SCAN_DY = 4.0          # … and this height difference
OUT_MIN, OUT_MAX = 6.0, 12.0   # back off to a place this far (path)
PASS_R = 2.5           # a path through this close to an awake foe goes through them …
ON_US_R = 2.5          # … except the ones already on us (this close): they follow whichever way we go — only 'away from them' counts
DROP_R = 2.0           # a drop edge this close to the place → not there (P-14 / P-49)
TRAIL_BONUS = 3.0      # the way we came: cleared ground, the usual answer
HOME_BONUS = 1.0
IDLE_W = 0.5           # an idle / asleep foe counts this much of an awake one (it may wake as we pass)
FIELD_R = OUT_MAX * 2.0  # Dijkstra bound (path cost; cliff-side faces cost more)


@dataclass
class Choice:
    point: tuple | None              # where to back off to (None: nothing better than staying — the caller keeps its old way)
    src: str = ""                    # T (trail) · R (radial) · H (home)
    path: list = field(default_factory=list)   # centroid path from us to it
    table: list = field(default_factory=list)  # every candidate: (src, point, score or None, why dropped)

    def line(self) -> str:
        kept = sum(1 for t in self.table if t[2] is not None)
        if self.point is None:
            return f"물러날 쪽 없음 (후보 {len(self.table)}, 쓸 수 있는 것 {kept})"
        best = next(t for t in self.table if t[1] == self.point)
        name = {"T": "온 길", "R": "옆길", "H": "화톳불 쪽"}[self.src]
        return f"물러날 쪽: {name} ({self.point[0]:.1f},{self.point[1]:.1f},{self.point[2]:.1f}), 점수 {best[2]:.1f} — 후보 {len(self.table)}, 쓸 수 있는 것 {kept}"


def _hd(a, b) -> float:
    return math.hypot(a[0] - b[0], a[2] - b[2])


def _field(nm, start, max_d: float):
    """Bounded Dijkstra over nm.graph() from the triangle under `start` → (dist, prev) by triangle, or (None, None)."""
    try:
        g = nm.graph()
        s = nm.nearest_tri(*start)
    except Exception:
        return None, None
    dist, prev, pq = {s: 0.0}, {}, [(0.0, s)]
    while pq:
        d, c = heapq.heappop(pq)
        if d > dist.get(c, 1e18) or d > max_d:
            continue
        for n, w in g.get(c, ()):
            nd = d + w
            if nd < dist.get(n, 1e18):
                dist[n], prev[n] = nd, c
                heapq.heappush(pq, (nd, n))
    return dist, prev


def _path(nm, prev, start_tri, tri) -> list:
    seq = [tri]
    while seq[-1] != start_tri and seq[-1] in prev and len(seq) < 400:
        seq.append(prev[seq[-1]])
    return [tuple(float(v) for v in nm.centroid[i]) for i in reversed(seq)]


def _trail_points(trail: list, me) -> list:
    """Points on our own trail (newest last) OUT_MIN … OUT_MAX m back along it."""
    out, acc, last = [], 0.0, tuple(me)
    for q in reversed(trail):
        acc += _hd(q, last)
        last = q
        if acc >= OUT_MIN and (not out or acc - out[-1][1] >= 2.0):
            out.append((tuple(q), acc))
        if acc > OUT_MAX:
            break
    return [q for q, _ in out]


def candidates(nm, me, trail: list, home_path: list | None = None) -> list[tuple[str, tuple]]:
    cands = [("T", q) for q in _trail_points(trail or [], me)]
    for r in (OUT_MIN, OUT_MAX):
        for k in range(12):
            a = 2 * math.pi * k / 12
            try:
                w = nm.nearest_walkable(me[0] + math.sin(a) * r, me[1], me[2] + math.cos(a) * r, r=2.0, dy=0.7 * r)   # ramps
            except Exception:
                w = None
            if w is not None:
                cands.append(("R", tuple(w)))
    if home_path:
        acc, last = 0.0, tuple(me)
        for q in home_path:
            acc += _hd(q, last)
            last = q
            if acc >= OUT_MIN:
                cands.append(("H", tuple(q)))
                break
    return cands


def pick(nm, me, foes: list, trail: list | None = None, home_path: list | None = None, avoid: list | None = None) -> Choice:
    """foes: [(x, y, z, awake)] — every live hostile; those beyond SCAN_R / SCAN_DY are ignored here.
    avoid: [(x, y, z, r)] — a thrower and its reach (duel 'shot'): candidates within r of it are dropped ('in_fire'), unless
    that drops them all (then the farthest from it wins on score as usual)."""
    me = tuple(me)
    near = [f for f in foes if _hd(f, me) <= SCAN_R and abs(f[1] - me[1]) <= SCAN_DY]
    awake = [f for f in near if f[3]]
    blocking = [f for f in awake if _hd(f, me) > ON_US_R]           # awake but not on us yet — don't walk into them
    idle = [f for f in near if not f[3]]
    dist, prev = _field(nm, me, FIELD_R)
    start_tri = nm.nearest_tri(*me) if dist is not None else None
    table, best = [], None
    for src, q in candidates(nm, me, trail or [], home_path):
        why = None
        path = []
        if dist is not None:
            try:
                t = nm.nearest_tri(*q)
            except Exception:
                t = None
            if t is None or t not in dist:
                why = "no_path"
            else:
                path = _path(nm, prev, start_tri, t)
        if why is None:
            if any(_hd(p, f) < PASS_R for p in path + [q] for f in blocking):
                why = "through_foe"
        if why is None and avoid and any(_hd(q, a) < a[3] for a in avoid):
            why = "in_fire"
        if why is None:
            try:
                if nm.drop_dist(*q) < DROP_R:
                    why = "drop"
            except Exception:
                pass
        if why is not None:
            table.append((src, q, None, why))
            continue
        ca = min([_hd(q, f) for f in awake] + [_hd(q, a) for a in (avoid or [])], default=SCAN_R)
        ci = min((_hd(q, f) for f in idle), default=SCAN_R)
        gain = ca - min((_hd(me, f) for f in awake), default=SCAN_R)   # how much farther from the awake ones than now
        score = min(ca, SCAN_R) + IDLE_W * min(ci, SCAN_R) + 0.5 * gain \
            + (TRAIL_BONUS if src == "T" else HOME_BONUS if src == "H" else 0.0)
        table.append((src, q, score, None))
        if best is None or score > best[0]:
            best = (score, src, q, path)
    if best is None and avoid and any(t[3] == "in_fire" for t in table):
        ch = pick(nm, me, foes + [(a[0], a[1], a[2], True) for a in avoid], trail, home_path)   # nowhere out of its reach — as far as we can
        return Choice(ch.point, ch.src, ch.path, table)
    if best is None:
        return Choice(None, table=table)
    return Choice(best[2], best[1], best[3], table)


# ── a way out of a ring ([MoKa] 2026-10-10) ────────────────────────────────────────────────────────────────────────
#  "주변에 적이 애워싸면, 빈틈이 있다면 그 방향으로 구르고, 없으면 한 두대 약공 때리고 상대가 틈을 만들어 주면 그 방향으로
#   비벼 들어가서 빠져 나가야지."
GAP_R = 3.0            # a foe this close blocks …
GAP_W = 1.1            # … the directions within atan(GAP_W / its distance) of it — its body and ours (P-29: bodies 0.84 m apart):
                       # ±48° at 1 m, ±29° at 2 m, ±20° at 3 m (unless it staggers / lies down — that is the opening it gives)
GAP_STEPS = 24
BREAK_HITS = 2         # no gap: this many single light attacks, looking for one after each


def gap_dir(me, close: list, ground_ok, prefer=None):
    """A direction to roll out through → (dx, dz) unit, or None when every way is blocked or has no floor.
    close: [(x, z, blocks)] — foes near us; blocks=False for one that staggers / is down. ground_ok(dx, dz) → floor that way.
    prefer: a point we'd like to head for (escape.pick) — among the open directions the one nearest to it, else the one
    farthest (in angle) from every blocking foe."""
    block = [(math.atan2(x - me[0], z - me[2]), math.atan(GAP_W / max(0.3, math.hypot(x - me[0], z - me[2]))))
             for x, z, b in close if b and math.hypot(x - me[0], z - me[2]) < GAP_R]
    want = math.atan2(prefer[0] - me[0], prefer[2] - me[2]) if prefer is not None else None
    angd = lambda a, b: abs((a - b + math.pi) % (2 * math.pi) - math.pi)
    best = None
    for k in range(GAP_STEPS):
        a = 2 * math.pi * k / GAP_STEPS
        clear = min((angd(a, b) - w for b, w in block), default=math.pi)   # angle to the nearest blocking body's edge
        if clear <= 0.0:
            continue
        dx, dz = math.sin(a), math.cos(a)
        if not ground_ok(dx, dz):
            continue
        score = clear + (2.0 * math.cos(angd(a, want)) if want is not None else 0.0)
        if best is None or score > best[0]:
            best = (score, dx, dz)
    return None if best is None else (best[1], best[2])
