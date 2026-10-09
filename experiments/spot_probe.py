"""Safe-spot probe (docs/design-multi-foe-spot.md §2-b) — MoKa's burg-upper safe spots: open arc / bodies that fit around the
spot vs nearby random spots, and path distance to the foes each spot serves and to the ignored ledge firebombs. No game.

  python experiments/spot_probe.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import json
import math
import random

import numpy as np

import navmesh

ROOT = _pl.Path(__file__).resolve().parent.parent
nm = navmesh.Navmesh.from_npz(ROOT / "data" / "samples" / "navmesh_m10_01_00_00.npz")
BODY = 0.85                      # P-29: hollows on us at 0.84–0.85 m


def ring(q, r=1.2, n=24) -> list[bool]:
    """Can we walk straight out to each of n points on a circle of radius r round q."""
    return [nm.clear_line(q, (q[0] + math.sin(2 * math.pi * k / n) * r, q[1], q[2] + math.cos(2 * math.pi * k / n) * r), step=0.3)
            for k in range(n)]


def bodies(ok: list[bool], r=1.2) -> int:
    """How many foes fit round q: each open run of the ring seats floor(length / BODY) + 1."""
    n = len(ok)
    if all(ok):
        return int(2 * math.pi * r / BODY)
    i0 = ok.index(False)
    seq, s, run = ok[i0:] + ok[:i0] + [False], 0, 0
    for v in seq:
        if v:
            run += 1
        elif run:
            s, run = s + int(run * (2 * math.pi * r / n) / BODY) + 1, 0
    return s


def path_len(a, b):
    p = nm.find_path(tuple(a), tuple(b))
    return sum(math.dist(x, y) for x, y in zip(p, p[1:])) if p else None


def main() -> None:
    d = json.loads((ROOT / "data" / "burg-upper-map.json").read_text(encoding="utf-8"))
    ledge = [tuple(p) for _, p in d["ignore"]]
    random.seed(1)
    for z in d["zones"]:
        q = tuple(z["safe"])
        ok = ring(q)
        near = []
        while len(near) < 30:
            w = nm.nearest_walkable(q[0] + random.uniform(-8, 8), q[1], q[2] + random.uniform(-8, 8), r=1.0, dy=1.0)
            if w and math.dist(w, q) < 8:
                near.append(bodies(ring(w)))
        foes = " ".join(f"{k[0]}:{(lambda L: f'{L:.0f}' if L else '–')(path_len(q, k[1]))}m" for k in z["kills"])
        print(f"zone {z['n']}: arc {sum(ok) / len(ok) * 360:4.0f}°  bodies {bodies(ok)}  (nearby median {np.median(near):.0f})  "
              f"wall {nm.wall_dist(*q):.1f} m  drop {nm.drop_dist(*q):.1f} m  ledge firebomb {min(math.dist(q, p) for p in ledge):.1f} m  | {foes}")


if __name__ == "__main__":
    main()
