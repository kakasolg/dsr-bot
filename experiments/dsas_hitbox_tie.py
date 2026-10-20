"""tae-verify B-22d close: the "same gap, different outcome" cases, from the record only (no new run, no rule change).

  python experiments/dsas_hitbox_tie.py [gate …]     default: right (1.0, 1.2) τ 0.75 → g13 (HIT) · g45 (MISS);
                                                      left (1.2, −1.6) τ 0.75 → g5 (HIT) · g37 (MISS)
Per live read of the gated run: anim time, hitbox state, player in the hollow's model frame, and for capsule time shifts
−1 / 0 / +1 / +2 frames the unrounded gap with the closest points (capsule parameter s, heights on both segments).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tae_verify as V  # noqa: E402
import dsas_hitbox_gap as G  # noqa: E402

REC = ROOT / "data" / "samples" / "20261019_190148_tae-probe4.jsonl"


def closest(p1, q1, p2, q2):
    d1, d2, r = q1 - p1, q2 - p2, p1 - p2
    a, e, f = d1 @ d1, d2 @ d2, d2 @ r
    c, b = d1 @ r, d1 @ d2
    den = a * e - b * b
    s = float(np.clip((b * f - c * e) / den, 0, 1)) if den > 1e-12 else 0.0
    t = (b * s + f) / e
    if t < 0:
        t, s = 0.0, float(np.clip(-c / a, 0, 1))
    elif t > 1:
        t, s = 1.0, float(np.clip((b - c) / a, 0, 1))
    pa, pb = p1 + d1 * s, p2 + d2 * t
    return float(np.linalg.norm(pa - pb)), s, pa, pb


def per_frame(fr, ptr, i0, i1):
    """One row per game frame (distinct anim time) from the placement read: the LAST read of that frame (player position as
    the frame ends), hitbox state, HP, and per shift −1…+2 the unrounded gap with the closest-point heights."""
    off = next(j for j in range(i0, i1) if fr[j].get("gate_why") == "tau")
    pb = fr[off]["p_back"]
    k = next(j for j in range(off, off + 60) if V._dxz(fr[j]["p"], pb) <= V.ARRIVE_R)
    drop = next((j for j, _l in V._drops(fr) if k <= j < i1), None)
    rows = {}
    for j in range(k, i1):
        m, fwd, lat, at, hb = G.to_model(fr[j], ptr)
        if at is None or at > 1.0667:
            break
        r = {"j": j, "at": at, "hb": hb, "hp": fr[j]["hp"], "fwd": fwd, "lat": lat, "dy": m[1],
             "reads": rows.get(round(at, 4), {}).get("reads", 0) + 1, "first_j": rows.get(round(at, 4), {}).get("first_j", j)}
        for s_ in (-1, 0, 1, 2):
            cap = G.capsule(at + s_ / 60)
            if cap is not None:
                d, sp, pa, pp = closest(cap[0], cap[1], m, m + np.array([0, G.PH, 0]))
                r[s_] = (d - G.RADIUS, sp, pa[1], pp[1])
        rows[round(at, 4)] = r
    return k, drop, rows


def show(fr, ptr, i0, i1, out):
    k, drop, rows = per_frame(fr, ptr, i0, i1)
    dat = G.to_model(fr[drop], ptr)[3] if drop else None
    out.append(f"  placed read j{k}; HP drop first seen at read j{drop} (anim {dat})" if drop else f"  placed read j{k}; no HP drop")
    out.append("  frame   reads hb      hp   player fwd/lat     | gap s−1   s0       s+1      s+2   (capsule closest-point height · player-line height)")
    for at, r in sorted(rows.items()):
        if at < 0.8667:
            continue
        g = "  ".join(f"{r[s_][0]:+.5f}({r[s_][2]:.2f}·{r[s_][3]:.2f})" if s_ in r else "   —   " for s_ in (-1, 0, 1, 2))
        out.append(f"  {at:.4f} {r['reads']:3}  {str(r['hb']):7} {r['hp']:4}  {r['fwd']:.4f}/{r['lat']:+.4f} | {g}")
    live = [r for r in rows.values() if r["hb"] not in (None, -1)]
    for s_ in (0, 1):
        best = min((r for r in live if s_ in r), key=lambda r: r[s_][0])
        out.append(f"  min over live frames, shift {s_:+d}: {best[s_][0]:+.5f} at {best['at']:.4f} "
                   f"(capsule point height {best[s_][2]:.3f}, capsule param {best[s_][1]:.3f})")


def main():
    lines = [json.loads(l) for l in REC.read_text(encoding="utf-8").splitlines() if l.strip()]
    _h, fr = V._frames(lines)
    ons = [i for i, x in enumerate(fr) if "gate_on" in x]
    runs = V.anim_runs(fr)
    gates = [int(x) for x in sys.argv[1:]] or [13, 45, 5, 37]
    out = []
    for g in gates:
        i0 = ons[g]
        ptr = V._near(fr[i0], V.ISO_R, V.P3_TARGET)[0][0]["ptr"]
        run = V._run_at(runs[ptr], i0)
        off = next(j for j in range(i0, run["i1"]) if fr[j].get("gate_why") == "tau")
        out.append(f"g{g} spot {fr[off]['spot']} tau {fr[i0]['tau']} foe_at_place {fr[off]['foe_at_place']}")
        show(fr, ptr, i0, run["i1"], out)
    print("\n".join(out))


if __name__ == "__main__":
    main()
