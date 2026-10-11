"""How well nav.footing_state's 'danger' separates the fights that ended in a fall from the rest (P-58 / P-49, design-floor-check §3-A).

  python experiments/footing_probe.py

Floor = NavMesh + walked cells with the run itself left out (floor_map_check.g_for), as rule_footing reads it ([MoKa] 2026-10-11).
1. Falls in a fight (a foe within 3 m in the 3 s before): was 'danger' on in those 3 s, and from how long before the drop?
2. Fight frames (a foe within 3 m, same level, not in the 5 s before a fall): how often 'danger' is on — where, and how long a stretch.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))

import collections
import glob
import json
import math

import motion
import nav
import floor_map_check as C

MAP = "m10_02_00_00"


def snaps(path: str) -> list:
    return [d for d in map(json.loads, open(path, encoding="utf-8", errors="replace")) if d.get("type") == "snap"]


def near_foes(d: dict) -> list:
    p = d["player"]
    return [(c["x"], c["y"], c["z"]) for c in d["chars"]
            if c.get("hp", 0) > 0 and math.hypot(c["x"] - p["x"], c["z"] - p["z"]) < nav.PUSH_FOE_R and abs(c["y"] - p["y"]) < 1.2]


def main() -> None:
    nm = motion.load_navmeshes()[MAP]
    falls = [f for f in C.falls() if nm.nearest_walkable(f[2]["x"], f[2]["y"], f[2]["z"], r=8, dy=3)]
    fall_t = collections.defaultdict(list)
    for run, t, a, b in falls:
        fall_t[run].append(t)

    print("1. falls in a fight")
    caught = n = 0
    for run, t, a, b in falls:
        path = C.SAMPLES / f"{run}.track.jsonl"
        before = [d for d in snaps(str(path)) if t - 3.0 <= d["rt"] <= t]
        if not any(near_foes(d) for d in before):
            continue
        n += 1
        g = C.g_for(nm, MAP, run)
        on = [d["rt"] for d in before
              if nav.footing_state(g, C.P(d["player"]["x"], d["player"]["y"], d["player"]["z"]), near_foes(d))["danger"]]
        caught += bool(on)
        print(f"   {run[:44]:44} {t:6.1f} s  danger {'from ' + format(t - min(on), '.1f') + ' s before' if on else 'never'}")
    print(f"   → {caught}/{n} fights that ended in a fall had 'danger' on in the 3 s before")

    print("2. fight frames (not within 5 s before a fall)")
    tot = dang = 0
    where = collections.Counter()
    for path in sorted(glob.glob(str(C.SAMPLES / "*.track.jsonl"))):
        if "asylum" in path:
            continue
        run = _pl.Path(path).name.split(".")[0]
        g = C.g_for(nm, MAP, run)
        for d in snaps(path):
            foes = near_foes(d)
            p = d["player"]
            if not foes or any(0 <= t - d["rt"] <= 5.0 for t in fall_t[run]) or nm.nearest_walkable(p["x"], p["y"], p["z"], r=8, dy=3) is None:
                continue
            tot += 1
            if nav.footing_state(g, C.P(p["x"], p["y"], p["z"]), foes)["danger"]:
                dang += 1
                where[(round(p["x"]), round(p["y"]), round(p["z"]))] += 1
    print(f"   → 'danger' on {dang}/{tot} fight frames ({100 * dang / max(tot, 1):.1f} %); top spots (x, y, z rounded):")
    for k, v in where.most_common(8):
        print(f"      {k}  {v}")


if __name__ == "__main__":
    main()
