"""Floor map = NavMesh + walked cells (docs/design-floor-check.md §3-C). The NavMesh has holes where there is floor — the
secret passage, the bridge arch above the ramp, the ladder top — and every floor check that reads only the NavMesh calls
those "no floor" (2.1 % of the steps the bot really took). Where the bot (or a human demo) has stood, there is floor.

  python ground.py build        recorded positions → data/walked/<map>.npz (bot tracks data/samples/*.track.jsonl and radar walks
                                data/samples/radar_walk_*.jsonl; falling / dead frames left out)
  python ground.py              how many cells per map

  Ground(nm, walked)            drop-in for a Navmesh where floor checks read it (floor_at · on_mesh · nearest_walkable);
                                everything else (find_path, wall_dist, drop_dist …) goes to the NavMesh unchanged.
                                Not wired into the bot yet (design §6 step 1 — [win] check first).

floor_at(x, z, near_y) → NavMesh floor when it is at this level (± STEP_DY), else a walked cell within FILL_R and ± STEP_DY
(flags 0), else whatever the NavMesh says (a floor far below = a drop, None = nothing). FILL_R 0.35 m is the walk harness's
value (motion.World, 6-a: 0.75 m already made the passage wider than it is).
"""
from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "walked"
FILL_R = 0.35            # a walked position makes floor within this (horizontal) — motion.FILL_R
STEP_DY = 0.6            # … at its height ± this (stairs, slopes) — motion.STEP_DY
CELL_M = 0.5             # lookup grid
MAP_R, MAP_DY = 8.0, 3.0  # a position belongs to the map whose NavMesh has walkable floor this close (horizontal, height)
FALL_ANIMS = {1500, 1510, 1550, 1580, 1750, 1760}   # falling / landing / knocked down — not standing on floor
FALL_DROP = 1.5          # m down within one frame (≤ 0.6 s) = falling, left out
SOURCES = ("data/samples/*.track.jsonl", "data/samples/radar_walk_*.jsonl")


def _frames(path: str):
    """(run id, t, x, y, z, anim, hp) for every snapshot of a track / radar-walk file."""
    run = Path(path).name.split(".")[0]
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "snap" or not d.get("player"):
            continue
        p = d["player"]
        yield run, d.get("rt", d.get("t", 0.0)), p["x"], p["y"], p["z"], p.get("anim"), p.get("hp")


def standing(frames: list) -> list:
    """Frames that stood on floor: alive, not a fall/landing anim, no big drop to the next frame, not right after one."""
    out = []
    for i, f in enumerate(frames):
        _, t, x, y, z, anim, hp = f
        if hp is not None and hp <= 0 or anim in FALL_ANIMS:
            continue
        nxt = frames[i + 1] if i + 1 < len(frames) else None
        prv = frames[i - 1] if i else None
        if nxt and 0 < nxt[1] - t <= 0.6 and y - nxt[3] > FALL_DROP:
            continue                                        # about to fall
        if prv and 0 < t - prv[1] <= 0.6 and prv[3] - y > FALL_DROP:
            continue                                        # mid-fall
        out.append(f)
    return out


def build(nms: dict, patterns=SOURCES) -> dict:
    """{map id: {"x","y","z","run": arrays, "runs": [names]}} — each standing frame on the map whose NavMesh is near it."""
    pts = {k: [] for k in nms}
    for pat in patterns:
        for path in sorted(glob.glob(str(ROOT / pat))):
            for run, t, x, y, z, anim, hp in standing(list(_frames(path))):
                best = None
                for k, nm in nms.items():
                    w = nm.nearest_walkable(x, y, z, r=MAP_R, dy=MAP_DY)
                    if w is not None:
                        d = math.hypot(w[0] - x, w[2] - z)
                        if best is None or d < best[0]:
                            best = (d, k)
                if best is not None:
                    pts[best[1]].append((x, y, z, run))
    out = {}
    for k, ps in pts.items():
        runs = sorted({p[3] for p in ps})
        idx = {r: i for i, r in enumerate(runs)}
        out[k] = {"x": np.array([p[0] for p in ps], np.float32), "y": np.array([p[1] for p in ps], np.float32),
                  "z": np.array([p[2] for p in ps], np.float32), "run": np.array([idx[p[3]] for p in ps], np.int32), "runs": runs}
    return out


def save(walked: dict, folder: Path = OUT) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for k, w in walked.items():
        p = folder / f"{k}.npz"
        np.savez_compressed(p, x=w["x"], y=w["y"], z=w["z"], run=w["run"], runs=np.array(w["runs"]))
        out.append(p)
    return out


def load(map_id: str, folder: Path = OUT) -> dict | None:
    p = folder / f"{map_id}.npz"
    if not p.exists():
        return None
    d = np.load(p)
    return {"x": d["x"], "y": d["y"], "z": d["z"], "run": d["run"], "runs": [str(r) for r in d["runs"]]}


class Walked:
    """Walked positions on a grid. exclude: run names left out (leave-one-run-out checks)."""

    def __init__(self, w: dict | None, exclude=()):
        self.cells: dict[tuple[int, int], list[tuple[float, float, float]]] = {}
        if not w:
            return
        skip = {i for i, r in enumerate(w["runs"]) if r in set(exclude)}
        for x, y, z, r in zip(w["x"].tolist(), w["y"].tolist(), w["z"].tolist(), w["run"].tolist()):
            if r in skip:
                continue
            self.cells.setdefault((math.floor(x / CELL_M), math.floor(z / CELL_M)), []).append((x, y, z))

    def __len__(self) -> int:
        return len(self.cells)

    def height(self, x: float, z: float, near_y: float, r: float = FILL_R, dy: float = STEP_DY) -> float | None:
        """Height of the nearest walked position within r (horizontal) and dy of near_y, or None."""
        cx, cz = math.floor(x / CELL_M), math.floor(z / CELL_M)
        n = math.ceil(r / CELL_M)
        best, best_d = None, r
        for i in range(-n, n + 1):
            for j in range(-n, n + 1):
                for px, py, pz in self.cells.get((cx + i, cz + j), ()):
                    if abs(py - near_y) > dy:
                        continue
                    d = math.hypot(px - x, pz - z)
                    if d <= best_d:
                        best, best_d = py, d
        return best


class Ground:
    """A Navmesh with walked cells filled in for floor checks. Pass where nav / duel take `terrain` / `nm`."""

    def __init__(self, nm, walked: Walked | dict | None = None):
        self.nm = nm
        self.walked = walked if isinstance(walked, Walked) else Walked(walked)
        self.filled = 0                                     # floor answers that came from walked cells (for logs)

    def floor_at(self, x: float, z: float, near_y: float):
        f = self.nm.floor_at(x, z, near_y)
        if f is not None and abs(f[0] - near_y) <= STEP_DY:
            return f
        h = self.walked.height(x, z, near_y)
        if h is not None:
            self.filled += 1
            return (h, 0)
        return f

    def on_mesh(self, x: float, y: float, z: float, dy: float = 1.0) -> bool:
        return self.nm.on_mesh(x, y, z, dy) or self.walked.height(x, z, y, dy=min(dy, STEP_DY)) is not None

    def nearest_walkable(self, x: float, y: float, z: float, r: float = 8.0, dy: float = 2.5):
        """NavMesh's answer — walked cells only stand in when the NavMesh has nothing within r (keeps returns to the mesh as before)."""
        w = self.nm.nearest_walkable(x, y, z, r=r, dy=dy)
        if w is not None:
            return w
        h = self.walked.height(x, z, y, r=min(r, 1.0), dy=dy)
        return None if h is None else (x, h, z)

    def __getattr__(self, name):                            # find_path, wall_dist, drop_dist, edge_kinds, map_id …
        return getattr(self.nm, name)


def for_map(nm, exclude=()) -> Ground:
    """Ground for a NavMesh with its map's walked cells (none yet → behaves exactly like the NavMesh)."""
    return Ground(nm, Walked(load(getattr(nm, "map_id", "")), exclude))


def main() -> None:
    if sys.argv[1:2] == ["build"]:
        import motion
        nms = motion.load_navmeshes()
        w = build(nms)
        for p in save(w):
            k = p.stem
            print(f"  {p.relative_to(ROOT)}: {len(w[k]['x'])} positions from {len(w[k]['runs'])} runs, "
                  f"{len(Walked(w[k]))} cells, {p.stat().st_size // 1024} KB")
        return
    for p in sorted(OUT.glob("*.npz")):
        w = load(p.stem)
        print(f"  {p.stem}: {len(w['x'])} positions, {len(w['runs'])} runs, {len(Walked(w))} cells")


if __name__ == "__main__":
    main()
