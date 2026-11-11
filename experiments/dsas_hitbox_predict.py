"""tae-verify B-22c: prediction for placed, standing players — fixed BEFORE the boundary trials (MoKa 10-19 "새 실험 전에 예측
규칙을 고정"). Uses only the DSAS capsule CSV (B-22) and the rule below; no game data.

  python experiments/dsas_hitbox_predict.py grid          min predicted gap over a forward × lateral grid
  python experiments/dsas_hitbox_predict.py spots OUT     the chosen spots with predictions → OUT (json, committed before the run)

Setup it predicts: probe 4 warp gate, out at the 3000's start, back at anim time TAU to a spot (F m ahead, L m to the hollow's
right; L < 0 = its left) measured from the hollow's pose at that moment, then the player stands still. Assumed (not
checked): the hollow keeps its heading after TAU (no turning), moves by the anim's root motion, and its body does not push
the player (spots whose centre distance comes under BODY_D at any live frame are flagged and not used).
Rule (fixed): gap(t) = segment–segment distance(capsule axis at anim time t, player's vertical line 0–1.7 m) − 0.2, over the
live frames of +0x2E0 (0.8833–1.05, 1/60 s). min_gap = min over them.
  min_gap <  LO → predict HIT        (LO = largest gap a hit has had, B-22b shift 0: 0.140)
  min_gap ≥  HI → predict MISS       (HI = smallest live gap a miss has had, B-22b shift 0: 0.737)
  between      → no prediction: the outcome narrows the effective collision threshold (estimation, not verification)
Outcome of a trial: HIT = any HP drop from the read the player is back at the spot to the end of that 3000 run; else MISS.
Trials left out of the score (fixed in advance, each counted and reported):
  not_placed     the first read back is > 0.15 m (x-z) from the planned spot relative to the hollow's pose at that read
  turned         the hollow's heading changes > 5° between that read and anim time 1.05 (the no-turning assumption breaks)
  moved          the player moves > 0.3 m (x-z) before anim time 1.05 without an HP drop (push, home warp)
  late           the first read back is after anim time 0.8833 (the hitbox may already be live)
  timing_end     any exclusion reason tae_verify.timing_end gives the gate (isolation, start unseen, restart, refill, …)
  no_hb          no hitbox state (+0x2E0) on the record
Score: predicted HIT / MISS spots → agree or disagree per trial. "none" spots → bounds on the effective threshold only.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dsas_hitbox_gap as G  # noqa: E402

TAU = 0.80
LIVE = [round(0.8833 + k / 60, 4) for k in range(11)]          # 0.8833 … 1.05
LO, HI = 0.140, 0.737
BODY_D = 0.8              # player centre this close to the hollow's root → body contact likely (both ~0.4 m; not checked)
RM = {}
import csv as _csv  # noqa: E402
for r in _csv.DictReader(open(G.CAP_CSV)):
    RM[round(float(r["t"]), 4)] = (float(r["rm_x"]), float(r["rm_z"]))


def rm(t):
    k = min(RM, key=lambda x: abs(x - t))
    return np.array(RM[k])


def predict(F: float, L: float) -> dict:
    p0 = np.array([-L, -F])                                   # model x, z at TAU (right = −X, forward = −Z)
    gaps, close = [], math.inf
    for t in LIVE:
        dx, dz = rm(t) - rm(TAU)
        px, pz = p0[0] - dx, p0[1] - dz
        cap = G.capsule(t)
        g = G.seg_seg(cap[0], cap[1], np.array([px, 0.0, pz]), np.array([px, G.PH, pz])) - G.RADIUS
        gaps.append(round(g, 3))
        close = min(close, math.hypot(px, pz))
    m = min(gaps)
    return {"F": F, "L": L, "min_gap": m, "at": LIVE[gaps.index(m)], "closest_body": round(close, 3), "body_contact": close < BODY_D,
            "predict": "HIT" if m < LO else "MISS" if m >= HI else "none", "gaps": gaps}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "grid"
    if cmd == "grid":
        Ls = [-1.6, -1.2, -0.8, -0.4, 0.0, 0.4, 0.8, 1.2, 1.6]
        print("min predicted gap (m); * = body contact likely.  rows F (ahead), cols L (+ = hollow's right)")
        print("F/L  " + " ".join(f"{L:+6.1f}" for L in Ls))
        for F in (0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.4):
            print(f"{F:4.1f} " + " ".join(f"{p['min_gap']:6.2f}{'*' if p['body_contact'] else ' '}"[:7] for p in (predict(F, L) for L in Ls)))
    elif cmd == "spots":
        spots = json.loads(sys.argv[3]) if len(sys.argv) > 3 else SPOTS
        out = {"rule": __doc__, "tau": TAU, "LO": LO, "HI": HI, "body_d": BODY_D, "capsule_csv": str(G.CAP_CSV.name),
               "spots": [predict(F, L) for F, L in spots]}
        Path(sys.argv[2]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        for p in out["spots"]:
            print(f"F {p['F']:4.2f} L {p['L']:+5.2f}  min_gap {p['min_gap']:6.3f} at {p['at']}  body {p['closest_body']}  → {p['predict']}")


SPOTS: list = [(1.4, 0.0), (1.6, 0.0), (1.8, 0.0), (2.0, 0.0), (2.4, 0.0),
         (1.0, -1.2), (1.2, -1.2), (1.2, -1.6), (1.8, -1.6), (2.4, -1.2),
         (1.4, 0.4), (1.0, 0.8), (1.0, 1.2), (1.6, 1.2), (1.0, 1.6)]

if __name__ == "__main__":
    main()
