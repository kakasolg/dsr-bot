"""tae-verify B-22: the DSAS capsule (experiments/dsas_hitbox.ps1 CSV) vs the player's recorded spot in front-mode probe 4 rows.
Gap = closest distance between the capsule axis and a vertical line 0–1.7 m at the player's position, minus the 0.2 m capsule
radius. A probe line, not the player's hurtbox (unknown). Prints one line per gate.
  python experiments/dsas_hitbox_gap.py"""
import csv, json, math, sys
sys.path.insert(0, "D:/dev/dsr-bot")
import tae_verify as V
CAP = list(csv.DictReader(open("D:/dev/dsr-bot/data/samples/20261019_dsas-hitbox-c2540-3000.csv")))
TS = [float(r["t"]) for r in CAP]
def capsule(t):
    if t < TS[0] or t > TS[-1]: return None
    i = max(j for j in range(len(TS)) if TS[j] <= t + 1e-9); i = min(i, len(TS) - 2)
    u = (t - TS[i]) / (TS[i + 1] - TS[i])
    g = lambda k: float(CAP[i][k]) * (1 - u) + float(CAP[i + 1][k]) * u
    return (g("ax"), g("ay"), g("az")), (g("bx"), g("by"), g("bz"))
def seg_seg(p1, q1, p2, q2):
    # closest distance between segments p1q1 and p2q2 (3D)
    import numpy as np
    p1, q1, p2, q2 = map(np.array, (p1, q1, p2, q2))
    d1, d2, r = q1 - p1, q2 - p2, p1 - p2
    a, e, f = d1 @ d1, d2 @ d2, d2 @ r
    c, b = d1 @ r, d1 @ d2
    den = a * e - b * b
    s = np.clip((b * f - c * e) / den, 0, 1) if den > 1e-12 else 0.0
    t = (b * s + f) / e
    if t < 0: t, s = 0.0, np.clip(-c / a, 0, 1)
    elif t > 1: t, s = 1.0, np.clip((b - c) / a, 0, 1)
    return float(np.linalg.norm((p1 + d1 * s) - (p2 + d2 * t)))
def to_model(line, ptr):
    f = next(x for x in line["foes"] if x["ptr"] == ptr)
    yaw = f["h"] + math.pi                                   # body faces heading + π (dsr_telemetry.face)
    fw = (math.sin(yaw), math.cos(yaw)); rt = (math.cos(yaw), -math.sin(yaw))   # ASSUMED: model→world is a rotation (no mirror)
    dx, dz = line["p"][0] - f["x"], line["p"][2] - f["z"]
    fwd, lat = dx * fw[0] + dz * fw[1], dx * rt[0] + dz * rt[1]
    return (-lat, line["p"][1] - f["y"], -fwd), fwd, lat, f.get("at"), f.get("hb")   # model: right = −X, forward = −Z
PH = 1.7  # vertical test line 0..PH above the player's position (not a hurtbox — a probe line)
out = []
for name in ("20261019_144513", "20261019_173608"):
    L = [json.loads(l) for l in open(f"D:/dev/dsr-bot/data/samples/{name}_tae-probe4.jsonl", encoding="utf-8") if l.strip()]
    r = V.timing_end(V.load(V.TAE), V.load(V.COMBAT), L)
    head, frames = V._frames(L)
    ons = [i for i, fr in enumerate(frames) if "gate_on" in fr]
    rows = iter(r["rows"])
    for i0 in ons:
        row = next(rows)
        if row["kind"] == "hold" or row["reasons"]: continue
        ptr = V._near(frames[i0], V.ISO_R, V.P3_TARGET)[0][0]["ptr"]
        off = next((j for j in range(i0, len(frames)) if frames[j].get("gate_why") == "tau"), None)
        if off is None and row["kind"] != "early": continue
        back = (off if off is not None else i0)
        pb = frames[off].get("p_back") if off is not None else None
        k = next((j for j in range(back, min(back + 60, len(frames))) if pb is None or V._dxz(frames[j]["p"], pb) <= V.ARRIVE_R), None)
        if k is None: continue
        pts = []
        for j in range(k, min(k + 200, len(frames))):
            fr = frames[j]
            if not any(x["ptr"] == ptr for x in fr["foes"]): break
            m, fwd, lat, at, hb = to_model(fr, ptr)
            if at is None or at > 1.0667: break
            cap = capsule(at)
            gap = None if cap is None else seg_seg(cap[0], cap[1], (m[0], m[1], m[2]), (m[0], m[1] + PH, m[2])) - 0.2
            pts.append((at, round(fwd, 3), round(lat, 3), hb, None if gap is None else round(gap, 3), fr["hp"]))
        hit_at = row.get("hit_age")
        out.append({"rec": name[-6:], "kind": row["kind"], "tau": row["tau"], "back": row.get("release_anim"), "hit": row["hit"], "hit_at": hit_at, "pts": pts})

for o in out:
    p = [x for x in o["pts"] if x[4] is not None]
    if not p: print(o["rec"], o["kind"], o["tau"], "no capsule overlap in time"); continue
    if o["hit"]:
        h = o["hit_at"][1]; near = [x for x in p if abs(x[0] - h) < 0.02 or (x[0] <= h and x[0] >= h - 0.0334)]
        print(o["rec"], o["kind"], o["tau"], "HIT at", o["hit_at"], "  reads around:", [(x[0], x[4], x[1], x[2]) for x in near][-3:])
    else:
        mn = min(p, key=lambda x: x[4])
        live = [x for x in p if x[3] not in (None, -1)]
        print(o["rec"], o["kind"], o["tau"], "miss  back", o["back"], " min gap", mn[4], "at", mn[0], "fwd/lat", mn[1], mn[2],
              " min gap while hb on:", min((x[4] for x in live), default=None))
