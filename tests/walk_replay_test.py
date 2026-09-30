"""walk_replay offline test — stop checks on synthetic walks, perturbation scoring, the committed sample. No game.

  python tests/walk_replay_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import random
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import walk_replay as R

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


PATH = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 0.0, 10.0)]


def walk(stop_at: float = 5.0, stop_s: float = 3.0, foe: bool = False, anim=-1, dt: float = 0.5, v: float = 2.0,
         lateral: float = 0.0) -> dict:
    """Walk the L at v m/s, 2 Hz; stand still stop_s seconds at x = stop_at on leg 1 (optionally with a foe near / anim)."""
    fr, t, x = [], 0.0, 0.0
    stopped = 0.0
    while x < 10.0:
        still = abs(x - stop_at) < 1e-6 and stopped < stop_s
        fr.append({"t": t, "p": (x, 0.0, lateral), "foe": foe and still, "anim": anim if still else -1,
                   "tag": "t", "path": PATH})
        t += dt
        if still:
            stopped += dt
        else:
            x = min(10.0, round(x + v * dt, 6))
    for z in (2.0, 4.0, 6.0, 8.0, 10.0):
        fr.append({"t": t, "p": (10.0, 0.0, z), "foe": False, "anim": -1, "tag": "t", "path": PATH})
        t += dt
    return {"tag": "t", "path": PATH, "fr": fr}


def kinds(ev, k):
    return [e for e in ev if e["kind"] == k]


print("checks on clean synthetic walks")
ev = R.run_checks(walk(stop_s=0.0), R.Params())
check("smooth walk → no events", ev == [])
ev = R.run_checks(walk(stop_s=3.0), R.Params())
np_ = kinds(ev, "no_progress")
check("3 s stop → one no-progress stop, 2 s into it", len(np_) == 1 and abs(np_[0]["t"] - 4.5) < 1e-9)
ev = R.run_checks(walk(stop_s=6.0), R.Params())
check("6 s stop → fires once per window (3)", len(kinds(ev, "no_progress")) == 3)
check("stop beside a foe (fighting) → no stop", kinds(R.run_checks(walk(stop_s=6.0, foe=True), R.Params()), "no_progress") == [])
ev = R.run_checks(walk(stop_s=3.0, anim=2002), R.Params())
check("hit-stun anim 2002 → one 'stun', and no no-progress while stunned",
      len(kinds(ev, "stun")) == 1 and kinds(ev, "no_progress") == [])
check("estus (7586) → no stun, no stop", R.run_checks(walk(stop_s=3.0, anim=7586), R.Params()) == [])
ev = R.run_checks(walk(stop_s=0.0, lateral=2.0), R.Params())
check("walking 2 m beside the line → one 'off_line' (lat +2… sign kept)", len(kinds(ev, "off_line")) == 1)
check("window/min_gain are parameters (window 4 s → 3 s stop not caught)",
      kinds(R.run_checks(walk(stop_s=3.0), R.Params(window=4.0)), "no_progress") == [])

print("bad observations")
w = walk(stop_s=0.0)
fr = [dict(f) for f in w["fr"]]
fr[4] = {**fr[4], "p": (fr[4]["p"][0], 0.0, 7.0)}                  # one frame 7 m off
ev = R.run_checks({**w, "fr": fr}, R.Params())
bad = kinds(ev, "bad_obs")
check("single jumped frame → flagged once, next frame fine", len(bad) == 1 and bad[0]["t"] == fr[4]["t"])
check("… and it doesn't cause a no-progress stop", kinds(ev, "no_progress") == [])
fr = [dict(f) for f in w["fr"]]
for k in range(4, len(fr)):                                         # teleport: everything from frame 4 on is 30 m away
    fr[k] = {**fr[k], "p": (fr[k]["p"][0] + 30.0, 0.0, fr[k]["p"][2])}
bad = kinds(R.run_checks({**w, "fr": fr}, R.Params()), "bad_obs")
check("real teleport (two frames agree) → one flag, then accepted", len(bad) == 1)
fr = [f for k, f in enumerate(w["fr"]) if k not in (3, 4, 5, 6)]
check("2 s with no frame → 'gap'", [e["why"] for e in kinds(R.run_checks({**w, "fr": fr}, R.Params()), "bad_obs")] == ["gap"])

print("perturbation + scoring")
w = walk(stop_s=4.0)
fr2, jumps = R.perturb(w["fr"], R.Variant(jumps=2, jump_m=8.0), random.Random(1))
check("perturb injects the jumps it reports", len(jumps) == 2 and len(fr2) == len(w["fr"]))
fr3, _ = R.perturb(w["fr"], R.Variant(drop=0.5), random.Random(1))
check("drop keeps first and last", fr3[0]["t"] == w["fr"][0]["t"] and fr3[-1]["t"] == w["fr"][-1]["t"] and len(fr3) < len(w["fr"]))
fr4, _ = R.perturb(w["fr"], R.Variant(speed=0.5), random.Random(1))
check("speed 0.5 halves the duration", abs((fr4[-1]["t"] - fr4[0]["t"]) - (w["fr"][-1]["t"] - w["fr"][0]["t"]) / 2) < 1e-9)
st = R.truth(w)
check("truth = the 4 s stall", len(st) == 1 and st[0]["s"] >= 4.0)
r = R.score_variant(w, st, R.Params(), R.Variant(), random.Random(0))
check("clean variant: stall caught, no false stop", r["stalls"] == 1 and r["hit"] == 1 and r["false"] == 0)
r = R.score_variant(w, st, R.Params(), R.Variant(speed=1.25, jumps=1, jump_m=9.0), random.Random(3))
check("slower + one jump: stall still caught, jump caught", r["hit"] == 1 and r["caught"] == 1 and r["bad_false"] == 0)
a = R.evaluate([w], R.Params(), n=30, seed=7)
b = R.evaluate([w], R.Params(), n=30, seed=7)
check("evaluate is reproducible with a seed", a == b)
check("synthetic 4 s stall: recall ≥ 0.9 over 30 variants", a["recall"] is not None and a["recall"] >= 0.9)

print("Gate on recorded walks (open loop)")
LL = [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 0.0, 5.0), (10.0, 0.0, 10.0)]   # L with mid points


def lwalk(pts) -> dict:
    return {"tag": "g", "path": LL, "fr": [{"t": 0.5 * i, "p": p, "foe": False, "anim": -1} for i, p in enumerate(pts)]}


exact = lwalk([(x, 0.0, 0.0) for x in range(0, 11)] + [(10.0, 0.0, z) for z in range(1, 11)])
r = R.gate_replay(exact, 0.95, release_lat=None)
check("walk through the corner → no point short, not held, not stuck",
      r["points"] == 3 and r["short"] == 0 and r["held_s"] == 0 and not r["stuck"])
cut = lwalk([(x, 0.0, 0.0) for x in range(0, 9)] + [(9.0, 0.0, z) for z in range(1, 11)])   # turns at x 9, walks leg 2 1 m inside
back = lwalk([(x, 0.0, 0.0) for x in range(0, 9)] + [(9.0, 0.0, 1.5), (9.5, 0.0, 3.0)] + [(10.0, 0.0, z) for z in range(4, 11)])
r = R.gate_replay(back, 0.95, release_lat=None)
check("cut then back on leg 2's line → Gate lets go by itself (points on that line project to s 1.0)",
      not r["stuck"] and r["held_s"] <= 1.0)
r = R.gate_replay(cut, 0.95, release_lat=None)                   # plain rule
check("cut the corner at x 9 → the corner point is short (reach < 0.95), sharp", r["short"] == 1 and r["short_sharp"] == 1)
check("… Gate held ≥ 2 m behind, and stuck at the end (never lets go)", r["held_s"] > 0 and r["stuck"] and r["lag_max"] > 5)
check("… held at the corner point (10, 0, 0)", r["held_at"][0][0] == 2 and r["held_at"][0][1] == 10.0)
r = R.gate_replay(cut, 0.95, release_lat=1.0)
check("… with release_lat 1.0 → not stuck, same 'short' (that's the recording)", not r["stuck"] and r["short"] == 1)
check("switch_s 0.75 → the cut (reach 0.8 on the 5 m segment) is enough", R.gate_replay(cut, 0.75, release_lat=None)["short"] == 0)
e = R.gate_eval([exact, cut], 0.95, n=3, seed=1)
check("gate_eval counts walks × (1 + n) and is reproducible", e["walks"] == 8 and e == R.gate_eval([exact, cut], 0.95, n=3, seed=1))
check("gate_places lists the cut corner (plain rule)", R.gate_places([cut], 0.95, None)[0][2] == 2)
check("default gate_replay uses release 1.0 m → the cut walk is not stuck", not R.gate_replay(cut, 0.95)["stuck"])

print("look-ahead on recorded walks (open loop)")
check("parse_la: '1.5' fixed, '1.5/0.5' shrunk", R.parse_la("1.5") == (1.5, 1.5) and R.parse_la("2.5/0.5") == (2.5, 0.5))
steps = [(x / 4, 0.0, 0.0) for x in range(0, 41)] + [(10.0, 0.0, z / 4) for z in range(1, 41)]   # 0.25 m steps round the L
lw = lwalk(steps)
fix25 = R.lookahead_replay(lw, 2.5, 2.5)
shr = R.lookahead_replay(lw, 1.5, 0.5)
check("only frames within 3 m of the sharp corner count (13 on leg 1 + 12 on leg 2)", fix25["frames"] == 25 and len(fix25["passes"]) == 1)
check("fixed 2.5 m at a 90° corner: the aim chord cuts > 0.25 m inside (geometry: up to ~0.9 m)",
      0.25 < fix25["passes"][0][1] < 1.0)
check("shrunk 1.5/0.5: worst cut ≤ 0.2 m", shr["passes"][0][1] <= 0.2)
check("… but the aim swings harder: max turn rate higher than fixed 2.5", max(shr["turn"]) > max(fix25["turn"]))
check("a walk off to the side isn't a 'cut' by itself (own offset subtracted)",
      max(R.lookahead_replay(lwalk([(x / 4, 0.0, 0.8) for x in range(0, 36)]), 1.5, 1.5)["cut"]) < 0.3)
e = R.lookahead_eval([lw], 2.5, 2.5, n=2, seed=3)
check("lookahead_eval: passes from 1 + n runs, reproducible", e["passes"] == 3 and e == R.lookahead_eval([lw], 2.5, 2.5, n=2, seed=3))

print("committed sample (data/samples/*.track.jsonl)")
files = sorted(str(p) for p in (Path(__file__).resolve().parent.parent / "data" / "samples").glob("*.track.jsonl"))
ws = R.load_walks(files)
check("sample loads walks (1-point paths included)", len(ws) >= 10 and sum(len(w["path"]) >= 2 for w in ws) > len(ws) // 2)
e = R.evaluate(ws, R.Params(), n=3, seed=0)
check("evaluate runs over the sample (stalls counted, rates finite)", e["stalls"] > 0 and e["false_per_min"] >= 0)
check("per-walk table prints one line per walk", len(R.walk_table(ws).splitlines()) == len(ws))

print(f"\n{'all ok' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
