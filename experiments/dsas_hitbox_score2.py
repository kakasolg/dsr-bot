"""tae-verify B-22d: score a side-boundary probe 4 record with the rules frozen in data/samples/20261019_b22d_rules.json.
Three scorings kept apart: A turn model · B collision model on the RECORDED heading (geometry reconstruction) · C prior
prediction (placement-time information + turn model). Every trial is listed, excluded ones with their reasons.

  python experiments/dsas_hitbox_score2.py <probe4.jsonl> [--csv OUT]
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
import dsas_hitbox_predict2 as P  # noqa: E402

FROZEN = json.loads((ROOT / "data" / "samples" / "20261019_b22d_rules.json").read_text(encoding="utf-8"))
TAB = {(r["F"], r["L"], r["tau"]): r for r in FROZEN["spots"]}
MARGIN = FROZEN["rules"]["classes"]["margin"]


def wrap_deg(a):
    return (a + 180) % 360 - 180


def klass_m(g, s):
    lo, hi = P.THR[s]
    return "HIT" if g < lo - MARGIN else "MISS" if g >= hi + MARGIN else "DISC"


def trials(path: Path) -> list[dict]:
    lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    r = V.timing_end(V.load(V.TAE), V.load(V.COMBAT), lines)
    _h, fr = V._frames(lines)
    has_hb = any(f.get("hb") is not None for x in fr for f in x["foes"])
    runs, drops = V.anim_runs(fr), V._drops(fr)
    out = []
    for g, (i0, row) in enumerate(zip([i for i, x in enumerate(fr) if "gate_on" in x], r["rows"])):
        tg = V._near(fr[i0], V.ISO_R, V.P3_TARGET)[0]
        ptr = tg[0]["ptr"] if len(tg) == 1 else None
        run = V._run_at(runs.get(ptr, []), i0) if ptr else None
        i1 = run["i1"] if run and run["i1"] is not None else len(fr)
        off = next((j for j in range(i0, min(i1 + 1, len(fr))) if fr[j].get("gate_why") == "tau"), None)
        tau = fr[i0].get("tau") or 0.80
        t = {"gate": g, "tau": tau, "excluded": []}
        if off is None or "spot" not in fr[off]:
            t["excluded"].append("no_release")
            out.append(t)
            continue
        F, L = fr[off]["spot"]
        key = (F, L, tau)
        t.update(F=F, L=L, side="left" if L < 0 else "right", frozen=TAB.get(key))
        if "terrain" in fr[off]:
            t["excluded"].append("terrain:" + fr[off]["terrain"])
        if row["reasons"]:
            t["excluded"].append("timing_end:" + row["reasons"][0])
        if not has_hb:
            t["excluded"].append("no_hb")
        pb = fr[off].get("p_back")
        k = next((j for j in range(off, min(off + 60, i1)) if pb and V._dxz(fr[j]["p"], pb) <= V.ARRIVE_R), None) if pb else None
        if k is None:
            if not any(e.startswith("terrain") for e in t["excluded"]):
                t["excluded"].append("not_placed")
            out.append(t)
            continue
        fa = fr[off]["foe_at_place"]
        fx, fz, fh = (fa[0], fa[2], fa[3]) if len(fa) == 4 else (fa[0], fa[1], fa[2])   # B-22c records: (x, z, h)
        yaw = fh + math.pi
        plan = (fx + F * math.sin(yaw) + L * math.cos(yaw), fz + F * math.cos(yaw) - L * math.sin(yaw))
        t["place_err"] = round(math.hypot(fr[k]["p"][0] - plan[0], fr[k]["p"][2] - plan[1]), 3)
        if t["place_err"] > 0.15:
            t["excluded"].append("not_placed")
        at_k = G.to_model(fr[k], ptr)[3]
        t["at_place"] = at_k
        if at_k is None or at_k > P.TURN_END + 1e-3:
            t["excluded"].append("late")
        upto = [j for j in range(k, i1) if (G.to_model(fr[j], ptr)[3] or 9) <= 1.05 + 1e-3]
        hy = next(f["y"] for f in fr[k]["foes"] if f["ptr"] == ptr)
        y0 = fr[k]["p"][1]
        dy = max(abs(fr[j]["p"][1] - y0) for j in upto) if upto else 0.0
        t["height"] = [round(y0 - hy, 3), round(dy, 3)]
        if abs(y0 - hy) > 0.15 or dy > 0.15:
            t["excluded"].append("height")
        hs = [j for j, _l in drops if k <= j < i1]
        t["outcome"] = "HIT" if hs else "MISS"
        if hs:
            t["hit_at"] = G.to_model(fr[hs[0]], ptr)[3]
        stop = hs[0] if hs else i1
        if any(V._dxz(fr[j]["p"], fr[k]["p"]) > 0.3 for j in upto if j < stop):
            t["excluded"].append("moved")
        # A: turn model — recorded heading change from the τ pose vs R2 / R2'
        rec = {}
        for j in upto:
            f = next(q for q in fr[j]["foes"] if q["ptr"] == ptr)
            rec[round(f["at"], 4)] = wrap_deg(math.degrees(f["h"] - fh))
        place = round((round(tau * 60) + 1) / 60, 4)
        alt_end = round((round(place * 60) + 4) / 60, 4)
        simR2, simR2p = P.simulate(F, L, tau), P.simulate(F, L, tau, turn_end=alt_end)
        live = [x for x in P.LIVE if x in rec]
        t["turn_rec"] = round(rec[live[-1]], 2) if live else None
        t["turn_err_R2"] = round(max(abs(simR2[x][1] - rec[x]) for x in live), 2) if live else None
        t["turn_err_R2p"] = round(max(abs(simR2p[x][1] - rec[x]) for x in live), 2) if live else None
        # B: reconstruction — recorded positions and heading
        for s in (0, 1):
            gs = [G.gap(fr[j], ptr, s / 60) for j in upto if G.live(fr[j], ptr, has_hb) and j <= stop]
            gs = [x for x in gs if x is not None]
            t[f"recon_gap_s{s}"] = round(min(gs), 3) if gs else None
            t[f"recon_class_s{s}"] = klass_m(min(gs), s) if gs else None
        c0, c1 = t["recon_class_s0"], t["recon_class_s1"]
        t["recon_class"] = c0 if c0 == c1 and c0 in ("HIT", "MISS") else "DISC"
        # C: prior — frozen class
        t["prior_class"] = t["frozen"]["class"] if t["frozen"] else None
        t["shift_differ"] = t["frozen"]["shift_differ"] if t["frozen"] else None
        out.append(t)
    return out


def main():
    path = Path(sys.argv[1])
    ts = trials(path)
    ok = [t for t in ts if not t["excluded"]]
    print(f"all gates {len(ts)} · scored {len(ok)} · excluded {len(ts) - len(ok)}")
    ex = {}
    for t in ts:
        for e in t["excluded"]:
            ex[e.split(":")[0]] = ex.get(e.split(":")[0], 0) + 1
    print("exclusion reasons (all reasons, a trial can have several):", ex)
    print("\nevery trial:")
    for t in ts:
        print(f"  g{t['gate']:2} {t.get('side', '?'):5} ({t.get('F')},{t.get('L')}) τ{t['tau']}  out {t.get('outcome', '-'):4}  prior {t.get('prior_class')}  "
              f"recon {t.get('recon_class')} (s0 {t.get('recon_gap_s0')} s1 {t.get('recon_gap_s1')})  turn {t.get('turn_rec')}° "
              f"errR2 {t.get('turn_err_R2')} errR2' {t.get('turn_err_R2p')}  {'EXCL ' + ','.join(t['excluded']) if t['excluded'] else ''}")
    print("\nA. turn model (scored trials): max |error| ≤ 1.0° →")
    for tau in (0.80, 0.75):
        xs = [t for t in ok if t["tau"] == tau and t["turn_err_R2"] is not None]
        print(f"  τ {tau}: R2 pass {sum(t['turn_err_R2'] <= 1.0 for t in xs)}/{len(xs)} · R2' pass {sum(t['turn_err_R2p'] <= 1.0 for t in xs)}/{len(xs)}"
              f" · recorded turn {sorted({t['turn_rec'] for t in xs})}")
    for name, key in (("B. reconstruction (recorded heading)", "recon_class"), ("C. prior (placement-time info + R2)", "prior_class")):
        print(f"\n{name}:")
        for side in ("left", "right"):
            xs = [t for t in ok if t["side"] == side and t[key] in ("HIT", "MISS")]
            agree = sum(t[key] == t["outcome"] for t in xs)
            print(f"  {side:5}: {agree}/{len(xs)} agree" + "".join(
                f"   [{c}: {sum(t[key] == t['outcome'] for t in xs if t[key] == c)}/{sum(t[key] == c for t in xs)}]" for c in ("HIT", "MISS")))
            for t in xs:
                if t[key] != t["outcome"]:
                    print(f"     DISAGREE g{t['gate']} ({t['F']},{t['L']}) τ{t['tau']} {key}={t[key]} outcome={t['outcome']} recon s0/s1 {t['recon_gap_s0']}/{t['recon_gap_s1']}")
    print("\nshift-differ spots (prior raw class differs between shift 0 and +1):")
    for t in ok:
        if t["shift_differ"]:
            fz = t["frozen"]
            print(f"  g{t['gate']} ({t['F']},{t['L']}) τ{t['tau']}: s0 {fz['class_s0']} / s1 {fz['class_s1']} → outcome {t['outcome']} "
                  f"(recon s0 {t['recon_gap_s0']} s1 {t['recon_gap_s1']})")
    print("\nthreshold evidence from DISC trials (recorded geometry):")
    for s in (0, 1):
        h = [t[f"recon_gap_s{s}"] for t in ok if t["outcome"] == "HIT" and t[f"recon_gap_s{s}"] is not None]
        m = [t[f"recon_gap_s{s}"] for t in ok if t["outcome"] == "MISS" and t[f"recon_gap_s{s}"] is not None]
        print(f"  shift {s:+d}: hits max {max(h) if h else None} · misses min {min(m) if m else None} · frozen interval {P.THR[s]}")
    if "--csv" in sys.argv:
        o = Path(sys.argv[sys.argv.index("--csv") + 1])
        keys = sorted({k for t in ts for k in t if k != "frozen"})
        with o.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            w.writerows(ts)
        print(f"→ {o}")


if __name__ == "__main__":
    main()
