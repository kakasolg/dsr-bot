"""Map objects from the game files — which breakable props (crates, barrels, furniture) stand in the way.

Data: data/gamefiles/<mapID>.json from msb_extract.py (evidence grade "file"; positions and breakability checked in play
2026-09-27, ROADMAP 2). The NavMesh doesn't know about props, so a path can run straight through a crate:
burg-bonfire got stuck 2.6 m short of a path point with breakable crates 0.7 m and 1.3 m from it (ROADMAP P-6).

  blocking(map_id, me, goal)   → breakable props between me and the next path point, nearest first

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
