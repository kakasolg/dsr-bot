"""navmesh.Navmesh.from_npz offline test — [win]'s exported NavMeshes (data/samples/navmesh_<map>.npz) load without the
game folder and line up with the bot's recorded walks (data/samples/radar_walk_*.jsonl). No game.

  python tests/navmesh_npz_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import navmesh

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


S = Path(__file__).resolve().parent.parent / "data" / "samples"
nms = {m: navmesh.Navmesh.from_npz(S / f"navmesh_{m}.npz") for m in ("m10_01_00_00", "m10_02_00_00", "m18_01_00_00")}
burg, link, asy = nms["m10_01_00_00"], nms["m10_02_00_00"], nms["m18_01_00_00"]
check("Burg / Firelink / Asylum: triangle counts as exported (7217 / 2126 / 2706)",
      (len(burg), len(link), len(asy)) == (7217, 2126, 2706))
check("MCG gates come back grouped (129 / 59 / 23)", (len(burg.gates()), len(link.gates()), len(asy.gates())) == (129, 59, 23))
check("map_id kept", burg.map_id == "m10_01_00_00")
check("Asylum is in game coordinates (MSB placement applied: floors near y 185~210, not ~8)",
      170 < float(asy.centroid[:, 1].mean()) < 230)


def positions(name):
    out = []
    for line in open(S / name, encoding="utf-8"):
        m = json.loads(line)
        if m.get("type") == "snap":
            p = m["player"]
            out.append((p["x"], p["y"], p["z"]))
    return out


def on(nm, pts):
    return sum(nm.on_mesh(*p) for p in pts) / max(1, len(pts))


ramp, store, exit_ = positions("radar_walk_ramp_top.jsonl"), positions("radar_walk_storeroom.jsonl"), \
    positions("radar_walk_passage_exit.jsonl")
check("ramp-top walks lie on Firelink's mesh (≥ 95 %), not Burg's", on(link, ramp) >= 0.95 and on(burg, ramp) < 0.05)
check("storeroom walks lie on Burg's mesh (≥ 70 % — the rest is indoors off the mesh)", on(burg, store) >= 0.7)
check("passage exit: 82 % on Firelink's mesh — the secret passage itself has no NavMesh (ROADMAP 1-f)",
      0.7 < on(link, exit_) < 0.95)
a, b = store[0], store[len(store) // 3]
check("find_path works on the loaded mesh (storeroom, two recorded positions)", len(burg.find_path(a, b)) >= 2)

print(f"\n{'all ok' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
