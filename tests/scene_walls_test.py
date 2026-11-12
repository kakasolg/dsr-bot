"""NavMesh-edge walls for rooms without the Sketchfab file (sim/scene_walls.py). No game, no Godot.

  python tests/scene_walls_test.py

Checks on made-up floors: a lone square gets walls on all four open sides, pushed out WALL_OUT · a side two triangles
share (even with copies of the corner points < 1 cm apart, as two NavMesh sheets have) gets none · a side with floor
below beyond it stays open, one facing higher floor (> 0.5 m up) gets a wall · floor_patch counts as floor beyond ·
a wall across the scene's own route (cam_path) is left out.
On the committed scenes: every scene that asks for Sketchfab walls carries edge_walls (a fresh clone has no Sketchfab
file), the ramp room's rule agrees with ramp_scene.py's `walls` for most segments, ramp.gd falls back to them.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first, then sim/
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent.parent / "sim")]

import json
import sys
from pathlib import Path

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import scene_walls as W

ROOT = Path(__file__).resolve().parent.parent
FAILS = []


def check(what: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        FAILS.append(what)


def square(x0, z0, s, y=0.0):
    return [[x0, y, z0], [x0 + s, y, z0], [x0 + s, y, z0 + s], [x0, y, z0 + s]]


def scene(quads, patch=None, jitter=0.0):
    v, t = [], []
    for q in quads:
        b = len(v)
        v += [list(p) for p in q]
        t += [[b, b + 1, b + 2], [b, b + 2, b + 3]]
    if jitter:
        v = [[p[0] + jitter, p[1], p[2]] for p in v]
    return {"nav": {"v": v, "t": t}, "floor_patch": patch or []}


def main() -> None:
    w = np.array(W.edge_walls(scene([square(0, 0, 4)])))
    mids = (w[:, :3] + w[:, 3:]) / 2
    check("a lone 4 m square: walls on its 4 open sides (2 triangles share the diagonal)", len(w) == 4)
    check("walls stand WALL_OUT past the edge", np.allclose(sorted(np.round(np.abs(mids[:, [0, 2]] - 2.0).max(axis=1), 3)),
                                                            [2.0 + W.WALL_OUT] * 4))
    two = scene([square(0, 0, 4), square(4, 0, 4)])
    two["nav"]["v"][4][1] += 0.004                         # second square's own copy of a shared corner, 4 mm off
    w2 = W.edge_walls(two)
    check("two squares side by side (separate vertex copies < 1 cm apart): no wall on the seam", len(w2) == 6)
    w3 = W.edge_walls(scene([square(0, 0, 4), square(4, 0, 4, y=-3.0)]))
    check("floor 3 m below beyond an edge: stays open (fall / step down)", len(w3) == 7)
    w4 = W.edge_walls(scene([square(0, 0, 4), square(4, 0, 4, y=2.0)]))
    check("floor 2 m above beyond an edge: walled from below (and open from above)", len(w4) == 8 - 1)
    patch = [[[4.0, 0.0, 0.0], [8.0, 0.0, 0.0], [8.0, 0.0, 4.0]], [[4.0, 0.0, 0.0], [8.0, 0.0, 4.0], [4.0, 0.0, 4.0]]]
    w5 = W.edge_walls(scene([square(0, 0, 4)], patch=patch))
    check("a floor_patch strip beyond an edge counts as floor (no wall there; patches get no walls of their own)", len(w5) == 3)

    sc6 = scene([square(0, 0, 4)])
    sc6["cam_path"] = [[2.0, 0.0, 2.0, 0, "default"], [6.0, 0.0, 2.0, 0, "default"]]   # the route leaves over the +x side
    w6 = np.array(W.edge_walls(sc6))
    check("a wall that would cross the scene's own route (cam_path) is left out — 3 walls, none on the +x side",
          len(w6) == 3 and not any(min(r[0], r[3]) > 4.0 for r in w6))

    assets = ROOT / "sim" / "godot" / "assets"
    sk = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in assets.glob("*_scene.json") if not p.name.startswith("_")}
    asks = {n: d for n, d in sk.items() if d.get("sk_walls")}
    check(f"every scene that asks for Sketchfab walls carries edge_walls ({sorted(asks)})",
          bool(asks) and all(len(d.get("edge_walls", [])) > 100 for d in asks.values()))
    ramp = sk["ramp_scene.json"]
    a, b = np.array(W.edge_walls(ramp)), np.array(ramp["walls"])
    ma, mb = (a[:, :3] + a[:, 3:]) / 2, (b[:, :3] + b[:, 3:]) / 2
    same = sum(np.min(np.linalg.norm(ma - m, axis=1)) <= 0.1 for m in mb)
    check(f"ramp room: this rule matches ramp_scene.py's walls for {same}/{len(b)} segments (≥ 85 %; ramp_scene reads the "
          f"game NavMesh's adjacency and blocked flags, the scene file has neither)", same >= 0.85 * len(b))
    gd = (ROOT / "sim" / "godot" / "ramp.gd").read_text(encoding="utf-8")
    check("ramp.gd: Sketchfab file missing → the scene's edge_walls, a printed note instead of engine errors",
          'sc.get("edge_walls", []) if sk_missing' in gd and "not FileAccess.file_exists(sk_file)" in gd)
    check("burg_scene.py writes edge_walls when it builds a scene",
          'out["edge_walls"] = scene_walls.edge_walls(out)' in (ROOT / "sim" / "burg_scene.py").read_text(encoding="utf-8"))

    if FAILS:
        print(f"scene_walls_test: {len(FAILS)} 실패")
        sys.exit(1)
    print("scene_walls_test: 전부 통과")


if __name__ == "__main__":
    main()
