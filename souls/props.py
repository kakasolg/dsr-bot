"""Map objects from the game files — which breakable props (crates, barrels, furniture) stand in the way.

Data: data/gamefiles/<mapID>.json from msb_extract.py (evidence grade "file"; positions and breakability checked in play
2026-09-27, ROADMAP 2). The NavMesh doesn't know about props, so a path can run straight through a crate:
burg-bonfire got stuck 2.6 m short of a path point with breakable crates 0.7 m and 1.3 m from it (ROADMAP P-6).

  blocking(map_id, me, goal)   → breakable props between me and the next path point, nearest first
  steer_around(path, nm)       → the same path, bent around the props in STEER it runs through (navmesh.find_path calls it)
  learned(min_runs)            → props earlier runs had to smash in ≥ min_runs runs (Field fills STEER with it at start)

A prop broken now respawns after resting, so nothing here remembers what was broken — field.walk keeps a per-walk
tally of swings instead. Strong props (min_attack ≥ msb_extract.STRONG_MIN_ATTACK) are left out: light attacks may not break them.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "gamefiles"
STRONG_MIN_ATTACK = 50      # same as msb_extract.py
REACH = 3.5                 # m — only props this close to me (horizontal) can be what's blocking. P-6: stopped 2.6 m short of
                            #     the point, crates 2.7 m / 3.05 m away sitting on it — so not only props touching me
LANE = 1.3                  # m — and within this of the straight line me → next point
DY = 1.5                    # m — same level
CLEAR = 1.2                 # m — a path passing a prop closer than this is bent around it. 28x·28z: the #6 walk's point sat 0.36 m
                            #     from crate o1321_0021, the bot stopped 1.2 m from its centre and smashed it (2.5~3 s stall each run, P-12 e)
DETOUR_R = 1.6              # m — the two detour points sit this far from the prop's centre, beside it
LOG = None                  # Field sets its log here — find_path has none to pass
STEER: set[str] = set()     # names of props to steer around — Field sets learned() at start. Only props past runs really had to
                            # smash: all breakables look alike in the files (ObjectHP 1, CharacterCollision 1), and steering around every one
                            # would have bent 12 more places in 28z alone where nothing stalled (MoKa: rule changes that spread break other places)
LEARN_MIN_RUNS = 2
ROOM = 0.6                  # m — and at least this far from the NavMesh border (wall or drop); otherwise keep the path and smash as before

_cache: dict[str, list] = {}


def load(map_id: str) -> list[dict]:
    """Breakable, not-strong props of the map. [] if the file is missing (map not extracted yet)."""
    if map_id not in _cache:
        path = DATA / f"{map_id}.json"
        try:
            objs = json.loads(path.read_text(encoding="utf-8"))["objects"]
        except (OSError, ValueError, KeyError):
            objs = []
        _cache[map_id] = [o for o in objs if o.get("breakable") is True
                          and (o.get("min_attack") or 0) < STRONG_MIN_ATTACK]
    return _cache[map_id]


def _seg_dist(p, a, b) -> float:
    """Horizontal distance from p to the segment a→b (x, z)."""
    ax, az, bx, bz, px, pz = a[0], a[2], b[0], b[2], p[0], p[2]
    dx, dz = bx - ax, bz - az
    L2 = dx * dx + dz * dz
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / L2))
    return math.hypot(ax + t * dx - px, az + t * dz - pz)


def blocking(map_id: str | None, me, goal, props: list[dict] | None = None) -> list[dict]:
    """Breakable props near me and on the lane toward goal, nearest first. props overrides the map file (tests)."""
    if props is None:
        props = load(map_id) if map_id else []
    out = []
    for o in props:
        q = o["pos"]
        h = math.hypot(q[0] - me[0], q[2] - me[2])
        if h <= REACH and abs(q[1] - me[1]) <= DY and _seg_dist(q, me, goal) <= LANE:
            out.append((h, o))
    return [o for _, o in sorted(out, key=lambda t: t[0])]


def learned(min_runs: int = LEARN_MIN_RUNS, logs: list[str] | None = None) -> set[str]:
    """Props smashed ("길 막은 … 부숨 시도") in at least min_runs different runs — from the same logs hotspots.py reads
    (data/samples/*.txt, data/runs/*.log; copies of one run count once). The bot learns its crates from its own runs:
    a new one enters after it blocked twice, without anyone editing a list."""
    import glob
    import hotspots
    root = Path(__file__).resolve().parent.parent
    if logs is None:
        logs = glob.glob(str(root / "data" / "samples" / "*.txt")) + glob.glob(str(root / "data" / "runs" / "*.log"))
    runs = hotspots.dedupe({p: hotspots.parse(p) for p in logs})
    seen: dict[str, set] = {}
    for p, evs in runs.items():
        for e in evs:
            if e["kind"] == "smash":
                seen.setdefault(e["why"], set()).add(p)
    return {name for name, ps in seen.items() if len(ps) >= min_runs}


def _detour(a, b, q, side: int, y: float):
    """Two points beside prop q, DETOUR_R off the a→b line on `side`, spread along it — a lane past the prop."""
    dx, dz = b[0] - a[0], b[2] - a[2]
    L = math.hypot(dx, dz)
    ux, uz = dx / L, dz / L
    px, pz = -uz * side, ux * side
    return [(q[0] + px * DETOUR_R + ux * k * DETOUR_R * 0.7, y, q[2] + pz * DETOUR_R + uz * k * DETOUR_R * 0.7) for k in (-1, 1)]


def _ok(pts: list, nm, props: list, dy: float) -> bool:
    for c in pts[1:-1]:
        if not nm.on_mesh(*c) or nm.border_dist(*c) < ROOM:
            return False
    for a, b in zip(pts, pts[1:]):
        if not nm.clear_line(a, b):
            return False
        if any(abs(o["pos"][1] - a[1]) <= dy and _seg_dist(o["pos"], a, b) < CLEAR * 0.9 for o in props):
            return False
    return True


def steer_around(path: list, nm, props: list[dict] | None = None, log=None) -> list:
    """Bend a NavMesh path around breakable props it runs through (the NavMesh doesn't know props, so a path can cross a crate).
    props: default = this map's props named in STEER (learned from earlier runs); tests pass their own.

    For each prop within CLEAR of the path on the same level: the points a (before) and b (after) the close stretch, both
    outside CLEAR, are joined through two points DETOUR_R beside the prop — first on the side away from the prop (shorter), then
    the other. Kept only if the new points are on the mesh, ROOM from its border, and every new leg is a clear line that doesn't
    pass a prop. Otherwise the path stays as it was (field.walk still smashes what blocks it). Stairs (a→b climbing > DY/2) are left alone."""
    if props is None:
        mid = getattr(nm, "map_id", None)
        props = [o for o in load(mid) if o["name"] in STEER] if mid and STEER else []
    log = log or LOG
    if len(path) < 2 or not props:
        return path
    out = [tuple(q) for q in path]
    for o in props:
        q = o["pos"]
        near = [i for i in range(1, len(out)) if abs(q[1] - out[i][1]) <= DY and _seg_dist(q, out[i - 1], out[i]) < CLEAR]
        if not near:
            continue
        inside = lambda p: math.hypot(p[0] - q[0], p[2] - q[2]) < CLEAR
        j, k = near[0] - 1, near[-1]
        while j >= 0 and inside(out[j]):
            j -= 1
        while k < len(out) and inside(out[k]):
            k += 1
        if j < 0 or k >= len(out) or k - j > 4:            # starts/ends at the prop (stepping aside can't help), or passes it twice
            continue                                       # far apart (a loop — don't drop the points in between)
        a, b = out[j], out[k]
        if math.hypot(b[0] - a[0], b[2] - a[2]) < 0.5 or abs(b[1] - a[1]) > DY / 2:
            continue
        cross = (b[0] - a[0]) * (q[2] - a[2]) - (b[2] - a[2]) * (q[0] - a[0])     # > 0: prop left of a→b
        y = (a[1] + b[1]) / 2
        for side in ((-1, 1) if cross > 0 else (1, -1)):
            new = [a] + _detour(a, b, q, side, y) + [b]
            if _ok(new, nm, props, DY):
                if log:
                    log(f"      경로가 {o['model']} ({o['name']}) 위를 지나감 — 옆 {DETOUR_R} m로 비켜 감")
                out = out[:j] + new + out[k + 1:]
                break
    return out
