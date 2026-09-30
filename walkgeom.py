"""Walk geometry — where the bot is along a planned path, no game (ROADMAP 6-a step 1).

Today's walk (nav.goto) only knows "distance to the next point" and switches to the following point inside an arrival
radius. The rules we want to test (ROADMAP 6-a) are about the *segment* instead:
  progress s  how far along segment A→B the bot is (projection, 0 at A, 1 at B; <0 behind A, >1 past B)
  lateral e   signed horizontal distance off the A→B line (+ = left of travel on a map drawn x right, z up)
  along       metres along the whole path

Two different "which segment" questions, kept apart on purpose:
  locate()  measurement — which segment does this position belong to (a replay of the old controller cuts corners,
            so it must be allowed to move on before s reaches 0.95)
  Gate      the rule — the controller's target may only move from A→B to B→C once s ≥ SWITCH_S

Only x/z (horizontal). Heights are for the caller (nav.ARRIVE_DY etc.).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

SWITCH_S = 0.95          # A→B progress needed before the target may move on to B→C
LOOKAHEAD_M = 1.5        # look-ahead distance on straight stretches
LOOKAHEAD_MIN_M = 0.5    # … shrunk to this at a sharp corner
SHARP_DEG = 35.0         # same threshold as nav.CORNER_DEG
CORNER_SPAN = 1.5        # same as nav.CORNER_SPAN
LOCATE_AHEAD_M = 4.0     # locate() window ahead: one 2 Hz frame at a run is ~1.85 m (3.7 m/s), doubled for a dropped frame
LOCATE_BACK_M = 1.5      # … and behind: pushed back a little by a hit / knock-back
LOCATE_LOST_M = 3.0      # nearest segment in the window farther than this = lost track → search the whole path


@dataclass
class Progress:
    seg: int             # segment index k: path[k] → path[k+1]
    s: float             # progress on that segment (unclamped)
    lat: float           # signed lateral error, m (+ = left of travel, map x right / z up)
    along: float         # m along the whole path (clamped to the segment)
    total: float         # path length, m

    @property
    def frac(self) -> float:
        return self.along / self.total if self.total > 0 else 1.0


def _xz(q) -> tuple[float, float]:
    return (float(q[0]), float(q[2])) if len(q) > 2 else (float(q[0]), float(q[1]))


def seg_lengths(path: list) -> list[float]:
    return [math.dist(_xz(path[k]), _xz(path[k + 1])) for k in range(len(path) - 1)]


def project(path: list, p, k: int, lens: list[float] | None = None) -> Progress:
    """Progress of p on segment k (k is clamped to a valid segment). One-point path: s = 1, lat = distance."""
    lens = seg_lengths(path) if lens is None else lens
    total = sum(lens)
    px, pz = _xz(p)
    if len(path) < 2:
        ax, az = _xz(path[0])
        return Progress(0, 1.0, math.hypot(px - ax, pz - az), 0.0, 0.0)
    k = max(0, min(len(path) - 2, k))
    (ax, az), (bx, bz) = _xz(path[k]), _xz(path[k + 1])
    dx, dz = bx - ax, bz - az
    L = lens[k]
    if L < 1e-9:
        return Progress(k, 1.0, math.hypot(px - ax, pz - az), sum(lens[:k]), total)
    ux, uz = dx / L, dz / L
    t = (px - ax) * ux + (pz - az) * uz
    # + = the side (-uz, ux) points to: left of travel on a map drawn with x right and z up
    lat = (px - ax) * (-uz) + (pz - az) * ux
    s = t / L
    return Progress(k, s, lat, sum(lens[:k]) + max(0.0, min(L, t)), total)


def locate(path: list, p, k_hint: int = 0, lens: list[float] | None = None, along_hint: float | None = None,
           back_m: float = LOCATE_BACK_M, ahead_m: float = LOCATE_AHEAD_M, relocate_m: float = LOCATE_LOST_M) -> Progress:
    """Measurement: the segment p is nearest to (inside the segment, ties go to the later one), among the segments
    overlapping [along_hint − back_m, along_hint + ahead_m] along the path, plus k_hint itself. along_hint is the last
    measured `along`; without it (first frame) the whole path is searched.
    Bounded so a path crossing itself (stairs, switchbacks) doesn't jump to the wrong pass; bounded in **metres**, not
    segments, because recorded routes have points every few tens of cm and NavMesh paths every few metres — a count
    of 3 segments fell behind on dense routes (31 of 5043 recorded frames, 2026-09-30).
    Lost track: if even the nearest segment in the window is farther than relocate_m (walk started mid-path, pushed
    far by a fight), search the whole path and take the global nearest when it is at least 1 m nearer. Switchback legs
    lie ~1 m apart, so they never trigger this."""
    lens = seg_lengths(path) if lens is None else lens
    if len(path) < 2:
        return project(path, p, 0, lens)
    k_hint = max(0, min(len(path) - 2, k_hint))
    cum = [0.0]
    for L in lens:
        cum.append(cum[-1] + L)
    if along_hint is None:
        ks = range(len(lens))                  # first frame, no history: the whole path (a walk may start mid-path)
    else:
        lo_a, hi_a = along_hint - back_m, along_hint + ahead_m
        ks = [k for k in range(len(lens)) if (cum[k] <= hi_a and cum[k + 1] >= lo_a) or k == k_hint]
    best, best_d = _nearest(path, p, ks, lens)
    if best_d > relocate_m:
        g, g_d = _nearest(path, p, range(len(lens)), lens)
        if g_d < best_d - 1.0:
            return g
    return best


def _nearest(path: list, p, ks, lens: list[float]) -> tuple[Progress, float]:
    best, best_d = None, math.inf
    px, pz = _xz(p)
    for k in ks:
        pr = project(path, p, k, lens)
        s = max(0.0, min(1.0, pr.s))
        (ax, az), (bx, bz) = _xz(path[k]), _xz(path[k + 1])
        d = math.hypot(px - (ax + (bx - ax) * s), pz - (az + (bz - az) * s))
        if d <= best_d + 1e-9:
            best, best_d = pr, d
    return best, best_d


class Gate:
    """The switching rule: target segment k moves to k+1 only once progress on k reaches switch_s.
    update(p) → Progress on the current target segment. release_lat: see _on_next. With k=None the first update starts at the segment p is on
    (locate over the whole path) — a walk may start mid-path (after a fight, a re-plan)."""

    def __init__(self, path: list, switch_s: float = SWITCH_S, k: int | None = 0, release_lat: float | None = None):
        self.path, self.switch_s, self.k, self.release_lat = path, switch_s, k, release_lat
        self.lens = seg_lengths(path)

    @property
    def last(self) -> int:
        return max(0, len(self.path) - 2)

    def update(self, p) -> Progress:
        if self.k is None:
            self.k = locate(self.path, p, 0, self.lens).seg
        pr = project(self.path, p, self.k, self.lens)
        while self.k < self.last and (pr.s >= self.switch_s or self._on_next(p)):
            self.k += 1
            pr = project(self.path, p, self.k, self.lens)
        return pr

    def _on_next(self, p) -> bool:
        """Release (off unless release_lat is set): already inside the next segment (0 < s < 1) and within
        release_lat of its line — the corner was cut, but walking back to s ≥ switch_s would only lose ground.
        Without it the replay shows Gate never letting go once a recorded walk cut a corner (ROADMAP 6-a)."""
        if self.release_lat is None:
            return False
        nx = project(self.path, p, self.k + 1, self.lens)
        return 0.0 < nx.s < 1.0 and abs(nx.lat) <= self.release_lat


def turn_deg(path: list, i: int, span: float = CORNER_SPAN) -> float:
    """How sharply the path turns at point i (same measure as nav.turn_deg, kept here so this module needs no game code)."""
    q = _xz(path[i])
    a = next((_xz(path[j]) for j in range(i - 1, -1, -1) if math.dist(q, _xz(path[j])) >= span), _xz(path[0]))
    b = next((_xz(path[j]) for j in range(i + 1, len(path)) if math.dist(q, _xz(path[j])) >= span), _xz(path[-1]))
    v1, v2 = (q[0] - a[0], q[1] - a[1]), (b[0] - q[0], b[1] - q[1])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return 0.0
    c = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(c))


def lookahead_dist(path: list, pr: Progress, base: float = LOOKAHEAD_M, short: float = LOOKAHEAD_MIN_M,
                   sharp_deg: float = SHARP_DEG, lens: list[float] | None = None) -> float:
    """Look-ahead distance: base, shrunk to `short` when a sharp corner (turn > sharp_deg) is within base metres ahead."""
    lens = seg_lengths(path) if lens is None else lens
    pos = pr.along
    acc = 0.0
    for i in range(pr.seg + 1, len(path) - 1):
        acc = sum(lens[:i])
        if acc - pos > base:
            break
        if acc >= pos - 1e-9 and turn_deg(path, i) > sharp_deg:
            return max(short, min(base, acc - pos))
    return base


def point_at(path: list, along: float, lens: list[float] | None = None) -> tuple:
    """The path point `along` metres from the start (clamped to the ends), with height interpolated if present."""
    lens = seg_lengths(path) if lens is None else lens
    if along <= 0 or len(path) < 2:
        return tuple(path[0])
    acc = 0.0
    for k, L in enumerate(lens):
        if acc + L >= along:
            u = (along - acc) / L if L > 0 else 1.0
            a, b = path[k], path[k + 1]
            return tuple(a[j] + (b[j] - a[j]) * u for j in range(len(a)))
        acc += L
    return tuple(path[-1])


def corner_cuts(path: list, positions: list, min_deg: float = SHARP_DEG) -> list[dict]:
    """For each sharp corner point i, how the track went round it: nearest distance to the corner and on which side.
    inside = the bot passed on the inside of the turn (turned early — P-17, ROADMAP 1-f). positions: x/z(/y) tuples.
    → [{i, deg, dist, inside}] — only corners the track came within 3 m of."""
    out = []
    for i in range(1, len(path) - 1):
        deg = turn_deg(path, i)
        if deg <= min_deg:
            continue
        c = _xz(path[i])
        a, b = _xz(path[i - 1]), _xz(path[i + 1])
        near = [q for q in positions if math.dist(_xz(q), c) < 3.0]
        if not near:
            continue
        q = min(near, key=lambda q: math.dist(_xz(q), c))
        # turn direction: cross of in (a→c) and out (c→b); the inside of the turn is that side of the corner
        cross = (c[0] - a[0]) * (b[1] - c[1]) - (c[1] - a[1]) * (b[0] - c[0])
        bis = ((a[0] - c[0]) / max(1e-9, math.dist(a, c)) + (b[0] - c[0]) / max(1e-9, math.dist(b, c)),
               (a[1] - c[1]) / max(1e-9, math.dist(a, c)) + (b[1] - c[1]) / max(1e-9, math.dist(b, c)))
        qx, qz = _xz(q)
        inside = (qx - c[0]) * bis[0] + (qz - c[1]) * bis[1] > 0     # the inside of a turn is along the bisector of the two legs
        out.append({"i": i, "deg": round(deg, 1), "dist": round(math.dist((qx, qz), c), 2), "inside": inside,
                    "left": cross > 0})
    return out
