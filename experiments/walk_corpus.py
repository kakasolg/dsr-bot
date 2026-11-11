"""Walk corpus probe (docs/design-walk-follow.md §2) — no game.

  python experiments/walk_corpus.py            every foe-free recorded walk (data/samples/*.track.jsonl) re-walked in the
                                               layer-2 harness (walksim.walk = today's nav.goto) vs what the game did:
                                               arrivals, stalls, and corner cuts as 2 Hz track frames see them
  python experiments/walk_corpus.py --radar    corner cuts in the 10 Hz radar walks (data/samples/radar_walk_*.jsonl),
                                               at 10 Hz and thinned to 2 Hz
  -n N                                         only the first N walks (shuffled, seed 0)

Corner cut = walkgeom.corner_cuts: nearest frame within 3 m of a sharp (> 35°) path corner lies on the inside, > 0.5 m off.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import glob
import json
import math
import random

import motion
import walk_replay as WR
import walkgeom as G
import walksim

ROOT = _pl.Path(__file__).resolve().parent.parent


def cut_share(cuts: list) -> str:
    n = len(cuts)
    k = sum(1 for c in cuts if c["inside"] and c["dist"] > 0.5)
    return f"corners {n}, inside > 0.5 m {k} ({k / max(1, n):.0%})"


def mesh_for(nms: dict, path: list):
    """The NavMesh most of the path's points stand on (≥ 80 %), else None."""
    best = max(((sum(1 for q in path if (f := nm.floor_at(q[0], q[2], q[1])) is not None and abs(f[0] - q[1]) < 1.0), k)
                for k, nm in nms.items()), default=(0, None))
    return best[1] if best[0] >= 0.8 * len(path) else None


def corpus(n: int | None) -> None:
    nms = motion.load_navmeshes()
    walks = WR.load_walks(sorted(glob.glob(str(ROOT / "data" / "samples" / "*.track.jsonl"))))
    for w in walks:
        w["mesh"] = mesh_for(nms, w["path"]) if len(w["path"]) >= 3 else None
    fill = collections.defaultdict(list)                   # every recorded position is floor (other walks only — motion.World)
    for w in walks:
        if w["mesh"]:
            fill[w["mesh"]] += [(f["p"][0], f["p"][1], f["p"][2], id(w)) for f in w["fr"]]
    sel = [w for w in walks if w["mesh"] and not any(f["foe"] for f in w["fr"])]
    rng = random.Random(0)
    rng.shuffle(sel)
    sel = sel[:n] if n else sel
    cuts = {"game 2 Hz": [], "sim 10 Hz": [], "sim 2 Hz": []}
    rows = []
    for w in sel:
        nm = nms[w["mesh"]]
        world = motion.World(nm, [f for f in fill[w["mesh"]] if f[3] != id(w)])
        path = [tuple(q) for q in w["path"]]
        p0 = w["fr"][0]["p"]
        r = walksim.walk(nm, world, path, tuple(p0), math.atan2(path[0][0] - p0[0], path[0][2] - p0[2]),
                         rng.uniform(-math.pi, math.pi), tol=1.0)
        game = [(f["t"], *f["p"]) for f in w["fr"]]
        cuts["game 2 Hz"] += G.corner_cuts(path, [f["p"] for f in w["fr"]])
        cuts["sim 10 Hz"] += G.corner_cuts(path, [q[1:] for q in r.track])
        cuts["sim 2 Hz"] += G.corner_cuts(path, [q[1:] for q in r.track[::5]])
        rows.append((r, sum(s[1] for s in r.stalls), sum(s[1] for s in walksim.stalls(game)), w))
    print(f"{len(rows)} foe-free walks: sim arrived {sum(r.result == 'arrived' for r, *_ in rows)}, falls {sum(r.falls for r, *_ in rows)}")
    print(f"  walks with a stall (≥ 1 s below 0.3 m/s): sim {sum(s > 0 for _, s, _, _ in rows)} ({sum(s for _, s, _, _ in rows):.0f} s)"
          f" · game {sum(g > 0 for *_, g, _ in rows)} ({sum(g for *_, g, _ in rows):.0f} s)"
          f" · both {sum(s > 0 and g > 0 for _, s, g, _ in rows)}")
    for k, v in cuts.items():
        print(f"  corner cuts, {k}: {cut_share(v)}")
    print("  longest game stalls (sim result alongside):")
    for r, s, g, w in sorted(rows, key=lambda x: -x[2])[:12]:
        print(f"    {g:5.1f} s game · sim {r.result} {s:.1f} s | {w['file'][:34]} {w['tag'][:22]} start {tuple(round(v, 1) for v in w['fr'][0]['p'])}")


def radar() -> None:
    cuts = {"10 Hz": [], "2 Hz": []}
    where = collections.Counter()
    for fn in sorted(glob.glob(str(ROOT / "data" / "samples" / "radar_walk_*.jsonl"))):
        path, pts, tag = None, [], ""

        def flush():
            if path and len(pts) > 3:
                c10 = G.corner_cuts(path, pts)
                cuts["10 Hz"] += c10
                cuts["2 Hz"] += G.corner_cuts(path, pts[::5])
                for c in c10:
                    if c["inside"] and c["dist"] > 0.5:
                        where[(tag, tuple(round(v, 1) for v in path[c["i"]]))] += 1
        for line in open(fn, encoding="utf-8"):
            d = json.loads(line)
            if d.get("type") == "walk":
                flush()
                path, pts, tag = None, [], d.get("tag") or ""
            elif d.get("type") == "snap":
                if path is None and d.get("path"):
                    path = [tuple(q) for q in d["path"]]
                pl = d["player"]
                pts.append((pl["x"], pl["y"], pl["z"]))
        flush()
    for k, v in cuts.items():
        print(f"radar walks, {k}: {cut_share(v)}")
    for (tag, q), k in where.most_common():
        print(f"  {k} × {tag} corner {q}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--radar", action="store_true")
    ap.add_argument("-n", type=int, default=None)
    a = ap.parse_args()
    radar() if a.radar else corpus(a.n)
