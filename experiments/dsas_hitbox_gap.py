"""tae-verify B-22b: the validation sample behind B-22, sorted out before going further (MoKa 10-19 "검증 표본부터 정리").

  python experiments/dsas_hitbox_gap.py            per-trial table + class counts + time-shift table → stdout
  python experiments/dsas_hitbox_gap.py --csv OUT  also the per-trial table as CSV

One trial = one gated 3000 run of hollow A in a front-mode probe 4 record (one attack swing, its own anim-ID run). Columns:
  cls        valid · inactive (hitbox state off from the return to the run's end) · rehit_limited (an HP drop in this run before
             the return — an attack lands once per target) · player_reacting (player anim 2000–2003 at the return: a damage
             reaction, whether it carries invincibility is not known) · unknown_active (no `hb` on the record: active only by the
             TAE + 1 frame rule of B-19)
  gap        closest distance between two FINITE segments — capsule axis DummyPoly 1 → 11 (DSAS path, B-22) and the vertical line
             0..PH m at the player's position — minus the capsule radius 0.2. Not the player's hurtbox (unknown): a probe line.
  hit_gap    min gap over the two reads around the HP drop (the collision happened between them)
  live_gap   miss: min gap over reads from the return while the hitbox is live

Frames (B-22b):
  game → hollow model space, per read:  d = p_player − p_hollow (x, z);  yaw = heading + π (dsr_telemetry.face);
    f = (sin yaw, cos yaw), r = (cos yaw, −sin yaw)  [assumed: model → world is a rotation, no mirror];
    model = (−(d·r), y_player − y_hollow, −(d·f))   (model forward −Z, right −X)
  capsule: model space WITHOUT root motion (CSV ax..bz). The game's hollow position already moved by the root motion, and the
  anim's bones carry none of it (Master stays at x = z = 0, dsas_hitbox.ps1 DSAS_BONES) → root motion counted once.
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
import tae_verify as V  # noqa: E402

CAP_CSV = ROOT / "data" / "samples" / "20261019_dsas-hitbox-c2540-3000_wide.csv"
RECORDS = ("20261019_144513", "20261019_173608")
RADIUS = 0.2
PH = 1.7
FRAME = 1 / 60
HB_RULE = (0.8833, 1.05)          # B-19: +0x2E0 on from TAE start + 1 frame to TAE end + 1 frame (3000)
REACT = range(2000, 2100)
MOVED = 0.3                       # m (x-z): the player counts as relocated after the return beyond this


def load_capsule(path=CAP_CSV):
    rows = list(csv.DictReader(open(path)))
    ts = np.array([float(r["t"]) for r in rows])
    a = np.array([[float(r[k]) for k in ("ax", "ay", "az")] for r in rows])
    b = np.array([[float(r[k]) for k in ("bx", "by", "bz")] for r in rows])
    return ts, a, b


TS, CA, CB = load_capsule()


def capsule(t):
    if t < TS[0] - 1e-9 or t > TS[-1] + 1e-9:
        return None
    i = min(int(np.searchsorted(TS, t, side="right")) - 1, len(TS) - 2)
    u = (t - TS[i]) / (TS[i + 1] - TS[i])
    return CA[i] * (1 - u) + CA[i + 1] * u, CB[i] * (1 - u) + CB[i + 1] * u


def seg_seg(p1, q1, p2, q2) -> float:
    """Closest distance between finite segments p1q1, p2q2 (Ericson, Real-Time Collision Detection 5.1.9)."""
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
    return float(np.linalg.norm((p1 + d1 * s) - (p2 + d2 * t)))


def seg_seg_brute(p1, q1, p2, q2, n=400) -> float:
    s = np.linspace(0, 1, n)[:, None]
    A, B = p1 + (q1 - p1) * s, p2 + (q2 - p2) * s
    return float(np.sqrt(((A[:, None, :] - B[None, :, :]) ** 2).sum(-1)).min())


def to_model(line, ptr):
    f = next(x for x in line["foes"] if x["ptr"] == ptr)
    yaw = f["h"] + math.pi
    fw, rt = (math.sin(yaw), math.cos(yaw)), (math.cos(yaw), -math.sin(yaw))
    dx, dz = line["p"][0] - f["x"], line["p"][2] - f["z"]
    fwd, lat = dx * fw[0] + dz * fw[1], dx * rt[0] + dz * rt[1]
    return np.array([-lat, line["p"][1] - f["y"], -fwd]), fwd, lat, f.get("at"), f.get("hb")


def gap(line, ptr, shift=0.0, check=None):
    m, _f, _l, at, _hb = to_model(line, ptr)
    cap = capsule(at + shift) if at is not None else None
    if cap is None:
        return None
    p2, q2 = m, m + np.array([0, PH, 0])
    d = seg_seg(cap[0], cap[1], p2, q2)
    if check is not None:
        check.append(abs(d - seg_seg_brute(cap[0], cap[1], p2, q2)))
    return d - RADIUS


def live(line, ptr, has_hb):
    _m, _f, _l, at, hb = to_model(line, ptr)
    if has_hb:
        return hb is not None and hb != -1
    return at is not None and HB_RULE[0] - 1e-3 <= at <= HB_RULE[1] + 1e-3


def trials():
    out = []
    for name in RECORDS:
        lines = [json.loads(l) for l in open(ROOT / "data" / "samples" / f"{name}_tae-probe4.jsonl", encoding="utf-8") if l.strip()]
        r = V.timing_end(V.load(V.TAE), V.load(V.COMBAT), lines)
        _head, frames = V._frames(lines)
        has_hb = any(f.get("hb") is not None for fr in frames for f in fr["foes"])
        runs = V.anim_runs(frames)
        drops = V._drops(frames)
        ons = [i for i, fr in enumerate(frames) if "gate_on" in fr]
        for g, (i0, row) in enumerate(zip(ons, r["rows"])):
            if row["kind"] == "hold" or row["reasons"]:
                continue
            ptr = V._near(frames[i0], V.ISO_R, V.P3_TARGET)[0][0]["ptr"]
            run = V._run_at(runs[ptr], i0)
            i1 = run["i1"] if run["i1"] is not None else len(frames)
            off = next((j for j in range(i0, i1 + 1) if frames[j].get("gate_why") == "tau"), None)
            if off is None:
                continue
            pb = frames[off].get("p_back")
            k = next((j for j in range(off, min(off + 60, i1)) if pb is None or V._dxz(frames[j]["p"], pb) <= V.ARRIVE_R), None)
            if k is None:
                continue
            at_k = to_model(frames[k], ptr)[3]
            if at_k is None or at_k > HB_RULE[1] + 1e-3:
                continue                     # back after the hitbox (by the rule) — not one of B-22's 46
            hs = [j for j, _lost in drops if run["i0"] < j < i1]
            if hs and hs[0] >= k and any(V._dxz(frames[j]["p"], frames[k]["p"]) > MOVED for j in range(k, hs[0])):
                hs = []                      # (not seen: a hit only after the player was moved away is not this trial's)
            t = {"rec": name[-6:], "gate": g, "run_i0": run["i0"], "ptr": ptr, "kind": row["kind"], "tau": row["tau"],
                 "back_at": at_k, "hb_recorded": has_hb, "hit": bool(hs), "pa_back": frames[k].get("pa"),
                 "prior_hit": any(j < k for j in hs), "k": k, "i1": i1, "frames": frames, "hit_j": hs[0] if hs else None}
            # the player must stay where it came back: cut at the first read > MOVED m away (the probe's home warp, a push)
            p0 = frames[k]["p"]
            cut = next((j for j in range(k, i1) if V._dxz(frames[j]["p"], p0) > MOVED), i1)
            t["moved_at"] = to_model(frames[cut], ptr)[3] if cut < i1 else None
            t["why_cut"] = (("home" if any("home" in frames[j] for j in range(k, cut + 1)) else "moved") if cut < i1 else None)
            t["i1"] = cut
            seg = frames[k:cut]
            t["live_reads"] = sum(live(x, ptr, has_hb) for x in seg)
            if t["prior_hit"]:
                t["cls"] = "rehit_limited"
            elif t["live_reads"] == 0 and not t["hit"]:
                t["cls"] = "inactive"
            elif t["pa_back"] in REACT:
                t["cls"] = "player_reacting"
            elif not has_hb:
                t["cls"] = "unknown_active"
            else:
                t["cls"] = "valid"
            out.append(t)
    return out


def pre_hit(t, shift=0.0):
    """Hit trials: min gap over live reads in game frames strictly before the hit read's frame — no HP drop there yet.
    Counts against the threshold only if damage shows in the frame of contact (not known: the B-19 one-frame question)."""
    if not t["hit"]:
        return None
    fr, ptr, j = t["frames"], t["ptr"], t["hit_j"]
    at_hit = to_model(fr[j], ptr)[3]
    gs = [gap(x, ptr, shift) for x in fr[t["k"]:j] if live(x, ptr, t["hb_recorded"]) and to_model(x, ptr)[3] < at_hit - 1e-3]
    gs = [x for x in gs if x is not None]
    return min(gs) if gs else None


def measure(t, shift=0.0, check=None):
    fr, ptr = t["frames"], t["ptr"]
    if t["hit"]:
        j = t["hit_j"]
        gs = [gap(fr[x], ptr, shift, check) for x in (j - 1, j) if x >= t["k"]]
        gs = [x for x in gs if x is not None]
        return ("hit", min(gs) if gs else None)
    gs = [gap(x, ptr, shift, check) for x in fr[t["k"]:t["i1"]] if live(x, ptr, t["hb_recorded"])]
    gs = [x for x in gs if x is not None]
    return ("miss", min(gs) if gs else None)


def main():
    ts = trials()
    check = []
    print(f"trials (B-22's rows): {len(ts)} — distinct (record, hollow, run start): {len({(t['rec'], t['ptr'], t['run_i0']) for t in ts})}")
    by = {}
    for t in ts:
        by.setdefault(t["cls"], []).append(t)
    cuts = [t for t in ts if t["why_cut"]]
    print(f"  player relocated after the return, before the run ended: {len(cuts)} trials "
          f"(home warp {sum(t['why_cut'] == 'home' for t in cuts)}, other {sum(t['why_cut'] == 'moved' for t in cuts)}; "
          f"at anim time {sorted({t['moved_at'] for t in cuts})}) — reads from there on are left out")
    for c, xs in by.items():
        print(f"  {c:16} {len(xs):3}  hit {sum(x['hit'] for x in xs)} / miss {sum(not x['hit'] for x in xs)}  "
              f"records {sorted({x['rec'] for x in xs})}  kinds {sorted({x['kind'] for x in xs})}")
    rows = []
    for t in ts:
        o, g0 = measure(t, 0.0, check)
        rows.append({k: t[k] for k in ("rec", "gate", "run_i0", "kind", "tau", "back_at", "hb_recorded", "pa_back", "prior_hit",
                                        "live_reads", "why_cut", "moved_at", "cls")} | {"outcome": o, "gap": None if g0 is None else round(g0, 3),
                                        "pre_hit_live_gap": None if pre_hit(t) is None else round(pre_hit(t), 3)})
    print(f"segment distance vs brute force (400×400 samples): max |diff| {max(check):.4f} m over {len(check)} pairs")
    print("\ntime shift of the capsule pose vs the record's anim time (game frames of 1/60 s); gaps in m")
    print("shift | class          | hits: max hit_gap | misses: min live_gap | separable | interval    | + live frames before a hit (no drop yet): min | interval with them")
    for cls in ("valid", "valid+unknown_active"):
        sel = [t for t in ts if t["cls"] == "valid" or (cls != "valid" and t["cls"] == "unknown_active")]
        for s in (-2, -1, 0, 1, 2):
            ms = [measure(t, s * FRAME) for t in sel]
            hg = [g for o, g in ms if o == "hit" and g is not None]
            mg = [g for o, g in ms if o == "miss" and g is not None]
            mh, mm = (max(hg) if hg else None), (min(mg) if mg else None)
            sep = mh is not None and mm is not None and mh < mm
            ph = [g for g in (pre_hit(t, s * FRAME) for t in sel) if g is not None]
            mp = min(ph) if ph else None
            up = min(x for x in (mm, mp) if x is not None)
            print(f"{s:+d}    | {cls:14} | n {len(hg):2} max {mh:6.3f} | n {len(mg):2} min {mm:6.3f} | {'yes' if sep else 'NO':3} | "
                  + (f"[{mh:.3f}, {mm:.3f})" if sep else "—".ljust(14)) + f" | n {len(ph):2} min {mp if mp is None else round(mp, 3)} | "
                  + (f"[{mh:.3f}, {up:.3f})" if mh < up else "— (not separable)"))
    if "--csv" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--csv") + 1])
        with out.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"→ {out}")


if __name__ == "__main__":
    main()
