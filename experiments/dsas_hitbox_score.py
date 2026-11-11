"""tae-verify B-22c: score a placed-spot probe 4 record against the predictions frozen in data/samples/20261019_b22c_predictions.json
(committed b38fcfb before the run). Applies the exclusion rules written there, nothing else.

  python experiments/dsas_hitbox_score.py <probe4.jsonl> [--csv OUT]
"""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tae_verify as V  # noqa: E402
import dsas_hitbox_gap as G  # noqa: E402

PRED = json.loads((ROOT / "data" / "samples" / "20261019_b22c_predictions.json").read_text(encoding="utf-8"))
PLACE_TOL, TURN_DEG, MOVED, LIVE_END, LIVE_START = 0.15, 5.0, 0.3, 1.05, 0.8833


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def score(path: Path) -> list[dict]:
    lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    r = V.timing_end(V.load(V.TAE), V.load(V.COMBAT), lines)
    _h, frames = V._frames(lines)
    has_hb = any(f.get("hb") is not None for fr in frames for f in fr["foes"])
    runs, drops = V.anim_runs(frames), V._drops(frames)
    preds = {(p["F"], p["L"]): p for p in PRED["spots"]}
    out = []
    for g, (i0, row) in enumerate(zip([i for i, fr in enumerate(frames) if "gate_on" in fr], r["rows"])):
        tg = V._near(frames[i0], V.ISO_R, V.P3_TARGET)[0]
        ptr = tg[0]["ptr"] if len(tg) == 1 else None
        run = V._run_at(runs.get(ptr, []), i0) if ptr else None
        i1 = (run["i1"] if run and run["i1"] is not None else len(frames))
        off = next((j for j in range(i0, i1 + 1) if j < len(frames) and frames[j].get("gate_why") == "tau"), None)
        spot = tuple(frames[off]["spot"]) if off is not None and "spot" in frames[off] else None
        t = {"gate": g, "spot": spot, "predict": preds[spot]["predict"] if spot in preds else None,
             "pred_gap": preds[spot]["min_gap"] if spot in preds else None, "excluded": []}
        if row["reasons"]:
            t["excluded"].append("timing_end:" + row["reasons"][0])
        if not has_hb:
            t["excluded"].append("no_hb")
        if spot is None or ptr is None:
            t["excluded"].append("no_spot")
            out.append(t)
            continue
        pb = frames[off].get("p_back")
        k = next((j for j in range(off, min(off + 60, i1)) if pb and V._dxz(frames[j]["p"], pb) <= V.ARRIVE_R), None)
        if k is None:
            t["excluded"].append("not_placed")
            out.append(t)
            continue
        m, fwd, lat, at_k, _hb = G.to_model(frames[k], ptr)
        t.update(at_back=at_k, placed=[round(fwd, 3), round(lat, 3)])
        if math.hypot(fwd - spot[0], lat - spot[1]) > PLACE_TOL:
            t["excluded"].append("not_placed")
        if at_k is None or at_k > LIVE_START + 1e-3:
            t["excluded"].append("late")
        hs = [j for j, _l in drops if k <= j < i1]
        t["hit"] = bool(hs)
        if hs:
            t["hit_at"] = G.to_model(frames[hs[0]], ptr)[3]
        h_k = next(f["h"] for f in frames[k]["foes"] if f["ptr"] == ptr)
        upto = [j for j in range(k, i1) if (G.to_model(frames[j], ptr)[3] or 9) <= LIVE_END + 1e-3]
        dh = max((abs(math.degrees(wrap(next(f["h"] for f in frames[j]["foes"] if f["ptr"] == ptr) - h_k))) for j in upto), default=0)
        t["turn_deg"] = round(dh, 1)
        if dh > TURN_DEG:
            t["excluded"].append("turned")
        first_hit = hs[0] if hs else i1
        if any(V._dxz(frames[j]["p"], frames[k]["p"]) > MOVED for j in upto if j < first_hit):
            t["excluded"].append("moved")
        gs = [G.gap(frames[j], ptr) for j in upto if G.live(frames[j], ptr, has_hb)]
        gs = [x for x in gs if x is not None]
        t["live_gap"] = round(min(gs), 3) if gs else None
        if hs:
            j = hs[0]
            hg = [G.gap(frames[x], ptr) for x in (j - 1, j) if x >= k]
            hg = [x for x in hg if x is not None]
            t["hit_gap"] = round(min(hg), 3) if hg else None
        t["outcome"] = "HIT" if t["hit"] else "MISS"
        t["agree"] = None if t["predict"] in (None, "none") or t["excluded"] else (t["predict"] == t["outcome"])
        out.append(t)
    return out


def main():
    path = Path(sys.argv[1])
    ts = score(path)
    print(f"gates {len(ts)}")
    ex = {}
    for t in ts:
        for e in t["excluded"][:1]:
            ex[e] = ex.get(e, 0) + 1
    print(f"excluded (first reason): {ex}")
    ok = [t for t in ts if not t["excluded"]]
    print(f"scored trials: {len(ok)}")
    print("spot (F, L)     pred  pred_gap | n  outcomes            | live_gap (actual, min over live reads)")
    for sp in [tuple((p["F"], p["L"])) for p in PRED["spots"]]:
        xs = [t for t in ok if t["spot"] == sp]
        p = next(q for q in PRED["spots"] if (q["F"], q["L"]) == sp)
        print(f"{str(sp):14} {p['predict']:5} {p['min_gap']:7.3f} | {len(xs)}  "
              + " ".join(t["outcome"] for t in xs).ljust(20) + " | " + " ".join(str(t.get("live_gap")) for t in xs))
    sc = [t for t in ok if t["agree"] is not None]
    print(f"\nverification (predicted HIT / MISS spots): {sum(t['agree'] for t in sc)} / {len(sc)} agree")
    for side, f in (("front L=0", lambda s: s[1] == 0), ("left L<0", lambda s: s[1] < 0), ("right L>0", lambda s: s[1] > 0)):
        xs = [t for t in sc if f(t["spot"])]
        print(f"  {side:10} {sum(t['agree'] for t in xs)} / {len(xs)}")
    for t in sc:
        if not t["agree"]:
            print("  DISAGREE", t)
    hits = [t["hit_gap"] for t in ok if t["outcome"] == "HIT" and t.get("hit_gap") is not None]   # gap at the drop (2 reads)
    miss = [t["live_gap"] for t in ok if t["outcome"] == "MISS" and t.get("live_gap") is not None]
    print(f"\neffective threshold (this record, actual positions, shift 0): hits' gap at the drop, max {max(hits) if hits else None}; "
          f"misses' min live gap ≥ {min(miss) if miss else None}")
    if "--csv" in sys.argv:
        o = Path(sys.argv[sys.argv.index("--csv") + 1])
        keys = sorted({k for t in ts for k in t})
        with o.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(ts)
        print(f"→ {o}")


if __name__ == "__main__":
    main()
