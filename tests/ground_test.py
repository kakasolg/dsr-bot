"""Floor map = NavMesh + walked cells (ground.py, docs/design-floor-check.md §3-C). No game.

  python tests/ground_test.py

Checks: a NavMesh hole where someone stood reads as floor (same level only, within FILL_R) · a floor far below still reads
as a drop when nobody stood there · a NavMesh floor at this level wins · on_mesh / nearest_walkable · everything else goes to
the NavMesh · leave-one-run-out · falling frames aren't floor · save / load · the real maps still see the 5 recorded falls.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import shutil
import sys
import tempfile
import types
from pathlib import Path

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import ground
import nav


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


class Nm:
    """Flat floor at y 0 for x < 0; for x ≥ 0 only a floor 16 m below (the bridge-arch case). map_id for delegation checks."""
    map_id = "fake"

    def floor_at(self, x, z, near_y):
        return (0.0, 0) if x < 0 else (-16.0, 0)

    def on_mesh(self, x, y, z, dy=1.0):
        return x < 0 and abs(y) <= dy

    def nearest_walkable(self, x, y, z, r=8.0, dy=2.5):
        return (-0.1, 0.0, z) if x < r else None

    def wall_dist(self, x, y, z, dy=2.0):
        return 4.2


def walked(pts, runs):
    return {"x": np.array([p[0] for p in pts], np.float32), "y": np.array([p[1] for p in pts], np.float32),
            "z": np.array([p[2] for p in pts], np.float32), "run": np.array([p[3] for p in pts], np.int32), "runs": runs}


def main() -> None:
    w = walked([(1.0, 0.0, 0.0, 0), (1.3, 0.0, 0.0, 0), (5.0, 0.0, 0.0, 1)], ["a", "b"])
    g = ground.Ground(Nm(), w)
    p = lambda x: types.SimpleNamespace(gx=x, gy=0.0, gz=0.0)
    check("hole where someone stood → floor at that level", g.floor_at(1.1, 0.0, 0.0) == (0.0, 0))
    check("… but not 0.5 m away from any walked position (FILL_R 0.35)", g.floor_at(2.0, 0.0, 0.0) == (-16.0, 0))
    check("… and not from 3 m above (another level)", g.floor_at(1.1, 0.0, 3.0) == (-16.0, 0))
    check("NavMesh floor at this level wins", g.floor_at(-1.0, 0.0, 0.0) == (0.0, 0))
    check("ground_ahead: NavMesh alone says no floor into the hole, the map says floor",
          not nav.ground_ahead(Nm(), p(0.6), 1.0, 0.0, reach=0.6) and nav.ground_ahead(g, p(0.6), 1.0, 0.0, reach=0.6))
    check("ground_ahead beyond the walked strip: still no floor", not nav.ground_ahead(g, p(1.3), 1.0, 0.0, reach=1.2))
    check("on_mesh: true on a walked spot, false off it", g.on_mesh(1.0, 0.0, 0.0) and not g.on_mesh(3.0, 0.0, 0.0))
    check("nearest_walkable: the NavMesh's answer first", g.nearest_walkable(1.0, 0.0, 0.0) == (-0.1, 0.0, 0.0))
    check("other calls go to the NavMesh (wall_dist, map_id)", g.wall_dist(0, 0, 0) == 4.2 and g.map_id == "fake")
    g2 = ground.Ground(Nm(), ground.Walked(w, exclude=("a",)))
    check("leave-one-run-out: run a's cells gone, run b's kept", g2.floor_at(1.1, 0.0, 0.0) == (-16.0, 0) and g2.floor_at(5.0, 0.0, 0.0) == (0.0, 0))
    check("no walked data: behaves exactly like the NavMesh", ground.Ground(Nm(), None).floor_at(1.1, 0.0, 0.0) == (-16.0, 0))

    fr = [("r", 0.0, 0, 0, 0, -1, 500), ("r", 0.5, 1, 0, 0, -1, 500), ("r", 1.0, 2, 0, 0, -1, 500),   # standing
          ("r", 1.5, 3, -4, 0, -1, 500), ("r", 2.0, 3, -8, 0, 1550, 500), ("r", 2.5, 3, -8, 0, -1, 0)]   # falls, dies
    check("standing(): the frame before a drop, mid-fall, fall anims and dead frames are left out",
          [f[2] for f in ground.standing(fr)] == [0, 1])

    tmp = Path(tempfile.mkdtemp(prefix="ground_"))
    try:
        ground.save({"fake": w}, tmp)
        back = ground.load("fake", tmp)
        check("save / load round trip", back["runs"] == ["a", "b"] and len(back["x"]) == 3 and back["run"].tolist() == [0, 0, 1])
        check("load of a map with no file → None", ground.load("nope", tmp) is None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # the real maps (data/walked/, python ground.py build): the recorded unintended falls stay "no floor", each run left out
    exp = Path(__file__).resolve().parent.parent / "experiments"
    _sys.path.insert(0, str(exp))
    import floor_map_check as C
    import motion
    nms = motion.load_navmeshes()
    rows = C.falls()
    seen = 0
    for run, t, a, b in rows:
        k, nm = C.mesh_at(nms, a["x"], a["y"], a["z"])
        if nm is None:                                     # standing off the mesh (the ramp ledge) — the map with walkable floor near
            k, nm = next((k_, m) for k_, m in nms.items() if m.nearest_walkable(a["x"], a["y"], a["z"], r=8, dy=3))
        g_ = C.g_for(nm, k, run)
        seen += not nav.ground_ahead(g_, C.P(a["x"], a["y"], a["z"]), b["x"] - a["x"], b["z"] - a["z"], reach=1.2)
    check(f"real maps: all {len(rows)} recorded falls still read 'no floor' toward the drop (own run left out)",
          len(rows) >= 5 and seen == len(rows))
    print("ground_test: 전부 통과")


if __name__ == "__main__":
    main()
