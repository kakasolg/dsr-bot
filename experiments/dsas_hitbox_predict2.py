"""tae-verify B-22d: side-boundary trials with the TURN model and the COLLISION model kept apart (MoKa 10-19).

  python experiments/dsas_hitbox_predict2.py fit            check the turn candidates and the prior simulator on run 184031
  python experiments/dsas_hitbox_predict2.py map TAU         prior min-gap map (shift 0 / +1) for spot candidates
  python experiments/dsas_hitbox_predict2.py freeze OUT     write the frozen rules + spot table (commit BEFORE the run)
  python experiments/dsas_hitbox_predict2.py predict F L TAU   HIT / MISS / UNKNOWN (+ reason) — the predictor after B-22d

TURN model (candidates from run 184031's 20 side trials — to be checked, not taken as known):
  R1 rate     at most RATE = 3.0° per game frame (1/60 s)                              [184031: 80 steps of 2.98–3.04°]
  R2 window   turning only in frames with anim time ≤ TURN_END = 0.8833 (the frame the hitbox turns on); none after
              [184031: last step at 0.8833 in 20/20; placed at 0.8167 only → "until 0.8833" vs "4 frames after placement"
              is not told apart — this batch alternates τ 0.80 / 0.75 to tell them apart]
  R3 target   toward the player's bearing, a step never past it (min(RATE, |bearing|))   [front spots: 0.52° steps ≈ bearing]
  first frame turning: the frame after the placement read (184031: placed read 0.8167, first step at 0.8333)
COLLISION model (B-22b/c, unchanged): gap = finite segment distance(capsule axis at anim time t + shift, player's vertical line
  0–1.7 m) − 0.2 over the live frames 0.8833–1.05; effective collision threshold interval per alignment:
  shift 0: [0.199, 0.398)      shift +1: [0.337, 0.431)
  min_gap < low → HIT · ≥ high → MISS · between → DISC (판별용: no prediction, narrows the threshold)
PRIOR prediction (placement-time information only): the spot (F, L) relative to the hollow's pose at τ; the hollow then moves
  by the anim's root motion along its CURRENT heading and turns by the TURN model; the player stands still.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dsas_hitbox_gap as G  # noqa: E402

RATE, TURN_END = 3.0, 0.8833
LIVE = [round(k / 60, 4) for k in range(53, 64)]             # frames 53…63 = 0.8833 … 1.05
THR = {0: (0.199, 0.398), 1: (0.337, 0.431)}
RM = {round(float(r["t"]), 4): np.array([float(r["rm_x"]), float(r["rm_z"])]) for r in csv.DictReader(open(G.CAP_CSV))}
FULL = ROOT / "data" / "samples" / "20261019_dsas-hitbox-c2540-3000_wide.csv"


def rm(t):
    k = min(RM, key=lambda x: abs(x - t))
    return RM[k]


def frames(t0, t1):
    return [round(k / 60, 4) for k in range(int(round(t0 * 60)), int(round(t1 * 60)) + 1)]


def simulate(F, L, tau, turn=True, rate=RATE, turn_end=TURN_END):
    """World frame = the hollow's pose at τ: hollow at (0, 0) facing +f. Returns per live frame (t, player in model x/z, heading°)."""
    hx, hz, hd = 0.0, 0.0, 0.0                                   # hollow position (right, fwd), heading (deg, + = to its right)
    px, pz = L, F                                                # player in the τ frame (right, fwd)
    t_tau = round(round(tau * 60) / 60, 4)                       # the pose the spot is measured from (gate release read)
    place = round((round(tau * 60) + 1) / 60, 4)                 # placement read (184031: τ 0.80 → 0.8167)
    out, prev = {}, t_tau
    for t in frames(t_tau, LIVE[-1]):
        if t > t_tau:
            d = rm(t) - rm(prev)                                 # model x (right = −x), z (fwd = −z)
            dr, df = -d[0], -d[1]
            a = math.radians(hd)
            hx += dr * math.cos(a) + df * math.sin(a)
            hz += -dr * math.sin(a) + df * math.cos(a)
            if turn and place < t <= turn_end + 1e-4:
                rx, rz = px - hx, pz - hz
                b = math.degrees(math.atan2(rx * math.cos(a) - rz * math.sin(a), rx * math.sin(a) + rz * math.cos(a)))
                hd += max(-rate, min(rate, b))
            prev = t
        a = math.radians(hd)
        rx, rz = px - hx, pz - hz
        right, fwd = rx * math.cos(a) - rz * math.sin(a), rx * math.sin(a) + rz * math.cos(a)
        out[t] = (np.array([-right, 0.0, -fwd]), hd)
    return out


def prior_gaps(F, L, tau, shift, **kw):
    sim = simulate(F, L, tau, **kw)
    gs = []
    for t in LIVE:
        m, _hd = sim[t]
        cap = G.capsule(t + shift / 60)
        gs.append(G.seg_seg(cap[0], cap[1], m, m + np.array([0, G.PH, 0])) - G.RADIUS)
    return gs


def klass(g, shift):
    lo, hi = THR[shift]
    return "HIT" if g < lo else "MISS" if g >= hi else "DISC"


def fit():
    """Run 184031 side trials: predicted heading (turn model) vs recorded, and prior min gap vs reconstructed min gap."""
    import tae_verify as V
    L_ = [json.loads(l) for l in open(ROOT / "data" / "samples" / "20261019_184031_tae-probe4.jsonl", encoding="utf-8") if l.strip()]
    _h, fr = V._frames(L_)
    ons = [i for i, f in enumerate(fr) if "gate_on" in f]
    for gi, i0 in enumerate(ons):
        tg = V._near(fr[i0], V.ISO_R, V.P3_TARGET)[0]
        if len(tg) != 1:
            continue
        ptr = tg[0]["ptr"]
        off = next((j for j in range(i0, len(fr)) if fr[j].get("gate_why") == "tau"), None)
        if off is None or "spot" not in fr[off]:
            continue
        F, L = fr[off]["spot"]
        h0 = next(f["h"] for f in fr[off]["foes"] if f["ptr"] == ptr)
        rec = {}
        for j in range(off, min(off + 400, len(fr))):
            f = next((q for q in fr[j]["foes"] if q["ptr"] == ptr), None)
            if not f or f["anim"] != 3000 or f.get("at") is None or f["at"] > 1.06:
                break
            rec[round(f["at"], 4)] = (math.degrees((f["h"] - h0 + math.pi) % (2 * math.pi) - math.pi), j)
        sim = simulate(F, L, 0.80)
        err = [abs(sim[t][1] - rec[t][0]) for t in LIVE if t in rec]
        recon = {s: min(g for g in (G.gap(fr[rec[t][1]], ptr, s / 60) for t in LIVE if t in rec) if g is not None) for s in (0, 1)}
        prior = {s: min(prior_gaps(F, L, 0.80, s)) for s in (0, 1)}
        print(f"g{gi:2} spot ({F:.1f},{L:+.1f}) turn err max {max(err) if err else None:.2f}°  "
              f"min gap recon/prior: s0 {recon[0]:.3f}/{prior[0]:.3f}  s1 {recon[1]:.3f}/{prior[1]:.3f}")


def spot_table(spots, taus=(0.80, 0.75)):
    rows = []
    for F, L in spots:
        for tau in taus:
            r = {"F": F, "L": L, "tau": tau}
            for s in (0, 1):
                g = min(prior_gaps(F, L, tau, s))
                r[f"gap_s{s}"], r[f"class_s{s}"] = round(g, 3), klass(g, s)
            r["turn_deg"] = round(simulate(F, L, tau)[LIVE[-1]][1], 2)
            r["agree_shifts"] = r["class_s0"] == r["class_s1"]
            rows.append(r)
    return rows


MARGIN = 0.05            # prior vs reconstruction differed by ≤ 0.04 m on 184031 (fit) → HIT / MISS need this much room
SPOTS = [(1.2, -1.2), (1.2, -1.4), (1.2, -1.6), (1.2, -1.8),      # left: expected hit → boundary → boundary → expected miss
         (1.0, 0.8), (1.0, 1.0), (1.0, 1.2), (1.0, 1.4)]           # right
TAUS = (0.80, 0.75)
HOME = (1.0, -10.02, -62.0, -0.956)   # NavMesh: 93 % of a 3.5 m disk flat & clear; the 8 spots pass at all 61 recorded poses
RULES = {
    "turn_model": {"R1_rate_deg_per_frame": RATE, "R2_last_turn_frame": TURN_END, "R3": "toward the player's bearing, never past it",
                   "first_turn_frame": "the frame after the placement read (τ + 2/60)",
                   "alternative_R2prime": "turning for 4 frames after the placement read, whatever τ (differs from R2 at τ 0.75)",
                   "status": "candidates from 184031 (20 side trials) — checked by this batch, not assumed"},
    "collision_model": {"gap": "finite segment distance(capsule axis DummyPoly 1→11 at anim t + shift, player's vertical line 0–1.7 m) − 0.2",
                        "live_frames": "0.8833 … 1.05 (1/60 s)", "thresholds": {"shift0": THR[0], "shift1": THR[1]},
                        "name": "effective collision threshold (not the player's radius)"},
    "classes": {"HIT": "min gap < low − MARGIN under shift 0 AND shift +1", "MISS": "min gap ≥ high + MARGIN under both",
                "DISC": "anything else (판별용: no prediction; narrows the threshold)",
                "shift_differ": "raw class (no margin) differs between shift 0 and +1 → reported separately", "margin": MARGIN},
    "scoring": {"A_turn": "per trial: predicted heading change (R2, and R2′) vs recorded at each live frame; pass = max |error| ≤ 1.0°",
                "B_reconstruction": "recorded positions + RECORDED heading → min live gap under shift 0 / +1 → class (same margins) vs outcome",
                "C_prior": "the frozen (spot, τ) class below (placement-time info + turn model R2) vs outcome",
                "outcome": "HIT = an HP drop from the placement read to the end of that 3000 run, else MISS"},
    "exclusions_in_order": {
        "terrain": "the runtime guard skipped the placement (NavMesh: floor ±0.15, flat ±0.10 at 0.3 m, wall ≥ 0.5)",
        "timing_end": "any tae_verify.timing_end exclusion reason", "no_hb": "no hitbox state on the record",
        "not_placed": "player > 0.15 m (x-z) from the planned spot computed from the hollow's pose at τ (foe_at_place)",
        "late": "placement read after anim time 0.8833",
        "height": "player y differs from the hollow's by > 0.15 m at the placement read, or changes by > 0.15 m before 1.05",
        "moved": "player moves > 0.3 m (x-z) before an HP drop or anim time 1.05"},
    "run": {"cmd": "probe4 480 --refill 400 793 --taus 0.8 --lock --terrain --home 1.0 -10.02 -62.0 -0.956 --prep backup-20261016-234951-options-pilot-ready-A-only --spots <each spot at τ 0.80 then 0.75>",
            "no_rerun": "one batch; the rules are not re-tuned and re-run after it (MoKa 10-19)"},
}


def freeze(out: Path):
    tab = spot_table(SPOTS, TAUS)
    for r in tab:
        lo0, hi0 = THR[0]
        lo1, hi1 = THR[1]
        c0 = "HIT" if r["gap_s0"] < lo0 - MARGIN else "MISS" if r["gap_s0"] >= hi0 + MARGIN else "DISC"
        c1 = "HIT" if r["gap_s1"] < lo1 - MARGIN else "MISS" if r["gap_s1"] >= hi1 + MARGIN else "DISC"
        r["class"] = c0 if c0 == c1 and c0 != "DISC" else "DISC"
        r["shift_differ"] = r["class_s0"] != r["class_s1"]
        place = round((round(r["tau"] * 60) + 1) / 60, 4)
        alt_end = round((round(place * 60) + 4) / 60, 4)
        r["R2prime_turn_deg"] = round(simulate(r["F"], r["L"], r["tau"], turn_end=alt_end)[LIVE[-1]][1], 2)
        for sft in (0, 1):
            g = min(prior_gaps(r["F"], r["L"], r["tau"], sft, turn_end=alt_end))
            r[f"R2prime_gap_s{sft}"] = round(g, 3)
    out.write_text(json.dumps({"rules": RULES, "doc": __doc__, "spots": tab}, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in tab:
        print(f"({r['F']},{r['L']:+.1f}) τ{r['tau']}  s0 {r['gap_s0']:6.3f}/{r['class_s0']:4}  s1 {r['gap_s1']:6.3f}/{r['class_s1']:4}  → {r['class']:4}"
              f"{'  shift-differ' if r['shift_differ'] else ''}  turn R2 {r['turn_deg']:+.0f}° R2′ {r['R2prime_turn_deg']:+.0f}°")


# ── predictor output after B-22d (MoKa 10-19): HIT / MISS / UNKNOWN only — UNKNOWN is never forced into hit or miss ──
NPC_OK, ANIM_OK = (254000, 254010), 3000          # c2540 hollow, BehaviorVariationID 25400 (A = 254010 is what was played)
TAU_OK = (0.75, 0.80)                             # placement times the turn model was checked at (B-22d)


def in_validated_range(F: float, L: float, tau: float) -> bool:
    """Where B-22c / B-22d actually checked the predictions: front L = 0, F 1.4–2.4 at τ 0.80 (B-22c), sides F 1.0–1.2,
    |L| 0.8–1.8 at τ 0.75 / 0.80 (B-22d). Anything else → UNKNOWN (out of range), even if the numbers look clear."""
    if not (TAU_OK[0] - 1e-6 <= tau <= TAU_OK[1] + 1e-6):
        return False
    if abs(L) < 1e-6:
        return abs(tau - 0.80) < 1e-6 and 1.4 - 1e-6 <= F <= 2.4 + 1e-6
    return 1.0 - 1e-6 <= F <= 1.2 + 1e-6 and 0.8 - 1e-6 <= abs(L) <= 1.8 + 1e-6


def predict(F: float, L: float, tau: float, npc: int = 254010, anim: int = 3000, player_moves: bool = False) -> dict:
    """→ {"label": HIT | MISS | UNKNOWN, "reason", "gap_s0", "gap_s1"}. UNKNOWN reasons: out_of_range (NPC, attack, τ,
    position not validated), assumption (player moves · body contact · turn stops on the bearing before 0.8833 — R3's cap
    was only seen at the front), discriminating (min gap inside the threshold band ± margin under shift 0 or +1)."""
    out = {"F": F, "L": L, "tau": tau}
    if npc not in NPC_OK or anim != ANIM_OK or not in_validated_range(F, L, tau):
        return {**out, "label": "UNKNOWN", "reason": "out_of_range"}
    if player_moves:
        return {**out, "label": "UNKNOWN", "reason": "assumption: the player stands still"}
    sim = simulate(F, L, tau)
    if min(math.hypot(m[0], m[2]) for m, _h in sim.values()) < 0.8:
        return {**out, "label": "UNKNOWN", "reason": "assumption: no body contact (closer than 0.8 m)"}
    full = (round((TURN_END - round((round(tau * 60) + 1) / 60, 4)) * 60)) * RATE
    if abs(L) > 0 and abs(sim[LIVE[0]][1]) < full - 0.5:
        return {**out, "label": "UNKNOWN", "reason": "assumption: turn capped by the bearing (R3 cap not checked at the sides)"}
    g = {s: min(prior_gaps(F, L, tau, s)) for s in (0, 1)}
    c = {}
    for s in (0, 1):
        lo, hi = THR[s]
        c[s] = "HIT" if g[s] < lo - MARGIN else "MISS" if g[s] >= hi + MARGIN else "UNKNOWN"
    label = c[0] if c[0] == c[1] and c[0] != "UNKNOWN" else "UNKNOWN"
    reason = None if label != "UNKNOWN" else ("discriminating" if "UNKNOWN" in c.values() else "shift 0 / +1 disagree")
    return {**out, "label": label, "reason": reason, "gap_s0": round(g[0], 3), "gap_s1": round(g[1], 3)}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fit"
    if cmd == "predict":
        F, L, tau = (float(v) for v in sys.argv[2:5])
        print(predict(F, L, tau))
        return
    if cmd == "freeze":
        freeze(Path(sys.argv[2]))
        return
    if cmd == "fit":
        fit()
    elif cmd == "map":
        tau = float(sys.argv[2]) if len(sys.argv) > 2 else 0.80
        Ls = [-2.0, -1.6, -1.4, -1.2, -1.0, -0.8, 0.8, 1.0, 1.2, 1.4, 1.6, 2.0]
        for s in (0, 1):
            print(f"shift {s:+d}, τ {tau}: prior min gap (m); rows F, cols L")
            print("F/L  " + " ".join(f"{L:+6.1f}" for L in Ls))
            for F in (0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.4):
                print(f"{F:4.1f} " + " ".join(f"{min(prior_gaps(F, L, tau, s)):6.2f}" for L in Ls))


if __name__ == "__main__":
    main()
