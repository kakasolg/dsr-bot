"""Floor probe (docs/design-floor-check.md §2) — no game.

  python experiments/floor_probe.py            falls in the track files (asylum's deliberate drops left out), fighting off
                                               the NavMesh (time, damage), how far my body moves per 0.5 s in hit / guard /
                                               attack / roll anims, and how often ground_ahead(1.2 m) says "no floor" on a
                                               step the bot really took
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import glob
import json
import math
import types

import motion
import nav
import walk_replay as WR

ROOT = _pl.Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"


def tracks(asylum: bool = False) -> list[str]:
    return [f for f in sorted(glob.glob(str(SAMPLES / "*.track.jsonl"))) if asylum or "asylum" not in f]


def lines(fn: str):
    for line in open(fn, encoding="utf-8", errors="replace"):
        yield json.loads(line)


def falls() -> None:
    print("falls (≥ 2.5 m down between two frames, < 6 m sideways):")
    for fn in tracks():
        snaps, says = [], []
        for d in lines(fn):
            (snaps if d["type"] == "snap" else says).append(d)
        for i in range(1, len(snaps)):
            a, b = snaps[i - 1], snaps[i]
            pa, pb = a["player"], b["player"]
            if not (0 < b["rt"] - a["rt"] <= 1.5) or pa["y"] - pb["y"] <= 2.5 or math.hypot(pb["x"] - pa["x"], pb["z"] - pa["z"]) >= 6:
                continue
            if i >= 2 and snaps[i - 2]["player"]["y"] - pa["y"] > 2.5:
                continue                                   # still the same fall
            near = [(c["npc"], round(math.hypot(c["x"] - pa["x"], c["z"] - pa["z"]), 1), c["anim"]) for c in a["chars"]
                    if c["hp"] > 0 and math.hypot(c["x"] - pa["x"], c["z"] - pa["z"]) < 4]
            print(f"  {_pl.Path(fn).name[:40]} {a['rt']:.1f} s ({pa['x']:.1f},{pa['y']:.1f},{pa['z']:.1f}) → y {pb['y']:.1f}, "
                  f"my anim {pa['anim']}, foes {near}")


def off_mesh(nms: dict) -> None:
    secs, dmg, where = collections.Counter(), collections.Counter(), collections.Counter()
    for fn in tracks():
        prev = None
        for d in lines(fn):
            if d["type"] != "snap":
                continue
            p = d["player"]
            fight = any(c["hp"] > 0 and math.hypot(c["x"] - p["x"], c["z"] - p["z"]) < 3 and abs(c["y"] - p["y"]) < 2 for c in d["chars"])
            if prev is not None and fight:
                k = "on" if any(nm.on_mesh(p["x"], p["y"], p["z"]) for nm in nms.values()) else "off"
                dt = min(d["rt"] - prev["rt"], 1.0)
                secs[k] += dt
                dmg[k] += max(0, prev["player"]["hp"] - p["hp"])
                if k == "off":
                    where[(round(p["x"] / 3) * 3, round(p["y"]), round(p["z"] / 3) * 3)] += dt
            prev = d
    print("fighting (a foe within 3 m):")
    for k in ("on", "off"):
        print(f"  {k:3} the NavMesh {secs[k]:6.0f} s, damage taken {dmg[k]:6d} ({dmg[k] / max(1.0, secs[k]):.1f}/s)")
    for q, s in where.most_common(6):
        print(f"    off-mesh spot ~{q}: {s:.1f} s")


def body_moves() -> None:
    kinds = {"hit 2000-2099": lambda a: 2000 <= a < 2100, "guard hit 140": lambda a: a == 140,
             "light 303000": lambda a: a == 303000, "roll 7xx": lambda a: 700 <= a < 800}
    st = collections.defaultdict(list)
    for fn in tracks(asylum=True) + sorted(glob.glob(str(SAMPLES / "radar_walk_*.jsonl"))):
        prev = None
        for d in lines(fn):
            if d.get("type") != "snap":
                continue
            p, t = d["player"], d.get("rt", d.get("t", 0.0))
            if prev is not None and 0.3 < t - prev[0] < 0.7 and prev[4] not in (None, -1) and abs(p["y"] - prev[2]) < 1.0:
                for k, f in kinds.items():
                    if f(prev[4]):
                        st[k].append(math.hypot(p["x"] - prev[1], p["z"] - prev[3]) / (t - prev[0]) * 0.5)
            prev = (t, p["x"], p["y"], p["z"], p.get("anim"))
    print("my body moves per 0.5 s (2 Hz tracks — coarse):")
    for k, v in st.items():
        v.sort()
        print(f"  {k:14} n={len(v):4d}  p50 {v[len(v) // 2]:.2f} m  p90 {v[int(len(v) * 0.9)]:.2f}  max {v[-1]:.2f}")


def false_voids(nms: dict) -> None:
    walks = WR.load_walks(tracks(asylum=True))
    n, blocked, where = 0, 0, collections.Counter()
    for w in walks:
        for a, b in zip(w["fr"], w["fr"][1:]):
            dx, dz = b["p"][0] - a["p"][0], b["p"][2] - a["p"][2]
            if math.hypot(dx, dz) < 0.5 or abs(b["p"][1] - a["p"][1]) > 1.0:
                continue
            x, y, z = a["p"]
            nm = next((m for m in nms.values() if (f := m.floor_at(x, z, y)) is not None and abs(f[0] - y) < 2.0), None)
            if nm is None:
                continue                                   # Field._walk turns terrain off when we're off the mesh
            n += 1
            if not nav.ground_ahead(nm, types.SimpleNamespace(gx=x, gy=y, gz=z), dx, dz, reach=1.2):
                blocked += 1
                where[(round(x), round(y), round(z))] += 1
    print(f"steps the bot really took (on mesh, ≥ 0.5 m, level): {n}; ground_ahead(1.2 m) says no floor: {blocked} ({blocked / max(1, n):.1%})")
    for q, k in where.most_common(6):
        print(f"    {q}: {k}")


if __name__ == "__main__":
    nms = motion.load_navmeshes()
    falls()
    off_mesh(nms)
    body_moves()
    false_voids(nms)
