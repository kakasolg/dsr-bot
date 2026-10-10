"""Floor map check (docs/design-floor-check.md §5-1) — NavMesh alone vs NavMesh + walked cells (ground.py), each run
checked against a map built WITHOUT that run (leave-one-run-out), so a run's own steps can't vouch for themselves. No game.

  python experiments/floor_map_check.py

  1 false "no floor": steps the bot really took (on mesh, ≥ 0.5 m in 0.5 s, same level) where nav.ground_ahead(1.2 m) said
    there is no floor ahead — design §2-d: 2.1 % with the NavMesh alone
  2 real drops still seen: the unintended falls (experiments/floor_probe.py, asylum's deliberate drops left out) — from the last
    frame before the fall, toward where it fell, ground_ahead must still say "no floor"
  3 the ramp-ledge pushes (P-49, 10-06a 84–91 s and 09-28 bandit-c 93–95 s): foe → me, 1.5 m — "no floor" must stay
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import glob
import json
import math
import types

import ground
import motion
import nav
import walk_replay as WR

ROOT = _pl.Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"
_CACHE: dict = {}


def g_for(nm, map_id: str, run: str):
    key = (map_id, run)
    if key not in _CACHE:
        _CACHE[key] = ground.Ground(nm, ground.Walked(ground.load(map_id), exclude=(run,)))
    return _CACHE[key]


def mesh_at(nms: dict, x, y, z):
    return next(((k, m) for k, m in nms.items() if (f := m.floor_at(x, z, y)) is not None and abs(f[0] - y) < 2.0), (None, None))


def P(x, y, z):
    return types.SimpleNamespace(gx=x, gy=y, gz=z)


def false_voids(nms: dict) -> None:
    walks = WR.load_walks(sorted(glob.glob(str(SAMPLES / "*.track.jsonl"))))
    n, nav_no, map_no = 0, 0, 0
    still = collections.Counter()
    for w in walks:
        run = w["file"].split(".")[0]
        for a, b in zip(w["fr"], w["fr"][1:]):
            dx, dz = b["p"][0] - a["p"][0], b["p"][2] - a["p"][2]
            if math.hypot(dx, dz) < 0.5 or abs(b["p"][1] - a["p"][1]) > 1.0:
                continue
            x, y, z = a["p"]
            k, nm = mesh_at(nms, x, y, z)
            if nm is None:
                continue
            n += 1
            bad_nav = not nav.ground_ahead(nm, P(x, y, z), dx, dz, reach=1.2)
            bad_map = not nav.ground_ahead(g_for(nm, k, run), P(x, y, z), dx, dz, reach=1.2)
            nav_no += bad_nav
            map_no += bad_map
            if bad_map:
                still[(round(x), round(y), round(z))] += 1
    print(f"1 false 'no floor' on {n} real steps: NavMesh {nav_no} ({nav_no / n:.1%}) → NavMesh + walked {map_no} ({map_no / n:.1%})")
    for q, c in still.most_common(5):
        print(f"    still: {q} × {c}")


def falls():
    """(run, frame before, frame after) for every unintended fall in the bot tracks (floor_probe's rule)."""
    out = []
    for path in sorted(glob.glob(str(SAMPLES / "*.track.jsonl"))):
        if "asylum" in path:
            continue
        snaps = [d for d in map(json.loads, open(path, encoding="utf-8", errors="replace")) if d.get("type") == "snap"]
        for i in range(1, len(snaps)):
            a, b = snaps[i - 1]["player"], snaps[i]["player"]
            if (0 < snaps[i]["rt"] - snaps[i - 1]["rt"] <= 1.5 and a["y"] - b["y"] > 2.5
                    and math.hypot(b["x"] - a["x"], b["z"] - a["z"]) < 6
                    and not (i >= 2 and snaps[i - 2]["player"]["y"] - a["y"] > 2.5)):
                out.append((_pl.Path(path).name.split(".")[0], snaps[i - 1]["rt"], a, b))
    return out


def real_drops(nms: dict) -> None:
    rows = []
    for run, t, a, b in falls():
        k, nm = mesh_at(nms, a["x"], a["y"], a["z"])
        if nm is None:
            k, nm = next(((k_, m) for k_, m in nms.items() if m.nearest_walkable(a["x"], a["y"], a["z"], r=8, dy=3)), (None, None))
        if nm is None:
            continue
        dx, dz = b["x"] - a["x"], b["z"] - a["z"]
        p = P(a["x"], a["y"], a["z"])
        rows.append((run, t, not nav.ground_ahead(nm, p, dx, dz, reach=1.2), not nav.ground_ahead(g_for(nm, k, run), p, dx, dz, reach=1.2)))
    print(f"2 real drops seen as 'no floor' toward the fall: NavMesh {sum(r[2] for r in rows)}/{len(rows)} · NavMesh + walked {sum(r[3] for r in rows)}/{len(rows)}")
    for run, t, a_, b_ in rows:
        print(f"    {run[:38]:38} {t:6.1f} s  NavMesh {'no floor' if a_ else 'floor'} · + walked {'no floor' if b_ else 'floor'}")


def ledge_pushes(nms: dict) -> None:
    n, nav_no, map_no = 0, 0, 0
    for name, t0, t1 in (("burg-bonfire-2026-10-06a", 84.0, 91.0), ("burg-bonfire-2026-09-28-bandit-c", 93.0, 95.3)):
        for d in map(json.loads, open(SAMPLES / f"{name}.track.jsonl", encoding="utf-8")):
            if d.get("type") != "snap" or not t0 <= d["rt"] <= t1:
                continue
            p = d["player"]
            k, nm = "m10_02_00_00", nms["m10_02_00_00"]
            g = g_for(nm, k, name)
            for c in d["chars"]:
                h = math.hypot(c["x"] - p["x"], c["z"] - p["z"])
                if c["hp"] <= 0 or h >= 3 or h < 0.1:
                    continue
                ux, uz = (p["x"] - c["x"]) / h, (p["z"] - c["z"]) / h
                n += 1
                nav_no += not nav.ground_ahead(nm, P(p["x"], p["y"], p["z"]), ux, uz, reach=1.5)
                map_no += not nav.ground_ahead(g, P(p["x"], p["y"], p["z"]), ux, uz, reach=1.5)
    print(f"3 ramp-ledge pushes (foe → me, 1.5 m) seen as 'no floor': NavMesh {nav_no}/{n} · NavMesh + walked {map_no}/{n}")


if __name__ == "__main__":
    nms = motion.load_navmeshes()
    false_voids(nms)
    real_drops(nms)
    ledge_pushes(nms)
