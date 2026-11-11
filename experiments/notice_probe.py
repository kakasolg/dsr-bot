"""At what distance does a foe notice us? — from the recorded runs (body pull step 1, MoKa 2026-10-11). No game.

  python experiments/notice_probe.py                 # table by foe type and by which way it faced us
  python experiments/notice_probe.py --events        # every wake event, one line each
  python experiments/notice_probe.py --json data/notice.json   # write the table the bot reads (souls/pull.py)

Reads data/samples/*.track.jsonl (2 Hz snapshots; characters within 12 m only — a foe that woke farther out is never seen
calm, so the table can't say anything beyond ~11 m).

A foe is "calm" while it has no anim (−1) or a dormant one (9000–9099), stays within CALM_M of where it was first seen
and has full HP. It "woke" on the first snapshot that breaks one of these — or whose body turned to face us (heading
within TURN_TO of our bearing after being TURN_FROM off). Heading convention (checked on 3,042 moving-foe frames, 92 %):
forward = (−sin h, −cos h).

Each event is classed:
  clean  — nothing else explains it: no knife thrown in the 3 s before (log "끌어오기"), no other foe within GROUP_R
           already awake, HP full (not hit first)
  group  — another foe close by was already awake (they wake each other / it followed the noise)
  knife  — a knife lure was thrown
  hit    — it lost HP first
Only clean events count in the table, and a body turn only when the foe then came at us (moved > 1 m or attacked within
FOLLOW_S): on the 2026-10-11 data only 15 of 104 clean turns did — a turn alone is not "noticed" (idle turning, or it saw
us and stayed on its leash). "closest calm" = how close we got while it stayed calm (a lower bound on how near
one can walk past it unnoticed — censored, the run may have walked away).
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import math
import statistics
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
HOSTILE = (6, 7, 24, 25, 27, 33)
CALM_M = 0.7          # moved this far from where first seen → awake
TURN_FROM = 45.0      # body this far off our bearing …
TURN_TO = 25.0        # … and then within this → it turned to us (noticed)
GROUP_R = 8.0         # another awake foe this close to it → a group wake, not a clean one
KNIFE_S = 3.0         # a knife thrown this long before → knife
DY_MAX = 3.0          # height difference above this → left out (another level)
FOLLOW_S = 4.0        # after waking: it counts as having come at us if it moved > 1 m or attacked within this


def dormant(a) -> bool:
    return a is not None and 9000 <= a < 9100


def calm_anim(a) -> bool:
    return a in (-1, None) or dormant(a)


def facing(c, p) -> float | None:
    """Angle (deg) between the foe's forward and the direction to us: 0 = looking at us, 180 = back to us."""
    h = c.get("heading")
    if h is None:
        return None
    fx, fz = -math.sin(h), -math.cos(h)
    dx, dz = p["x"] - c["x"], p["z"] - c["z"]
    n = math.hypot(dx, dz) or 1e-6
    return math.degrees(math.acos(max(-1.0, min(1.0, (fx * dx + fz * dz) / n))))


def side(f: float | None) -> str:
    if f is None:
        return "?"
    return "front" if f < 60 else "side" if f < 120 else "back"


def events_of(path: str) -> tuple[list[dict], list[dict]]:
    """→ (wake events, never-woke records) for one run."""
    run = Path(path).name.replace(".track.jsonl", "")
    knives: list[float] = []
    st: dict = {}            # ptr → state while calm
    check: dict = {}         # ptr → its wake event, for 'came' 
    out, quiet = [], []
    for line in open(path, encoding="utf-8"):
        d = json.loads(line)
        if d.get("type") == "say":
            if "끌어오기" in d.get("line", "") or "나이프" in d.get("line", ""):
                knives.append(d["rt"])
            continue
        if d.get("type") != "snap":
            continue
        p, t = d["player"], d["rt"]
        chars = [c for c in d["chars"] if c["team"] in HOSTILE]
        for c in chars:                                    # did a woken foe then come at us (or attack) within FOLLOW_S?
            e = check.get(c["ptr"])
            if e is not None and t - e["t"] <= FOLLOW_S:
                dist = math.hypot(c["x"] - p["x"], c["z"] - p["z"])
                if (c["anim"] is not None and 3000 <= c["anim"] < 3500) or math.hypot(c["x"] - e["_x"], c["z"] - e["_z"]) > 1.0:
                    e["came"] = True
        woke_now = {c["ptr"] for c in chars if c["hp"] > 0 and not calm_anim(c["anim"])}
        for c in chars:
            k = c["ptr"]
            if c["hp"] <= 0:
                st.pop(k, None)
                continue
            dist = math.hypot(c["x"] - p["x"], c["z"] - p["z"])
            dy = c["y"] - p["y"]
            f = facing(c, p)
            s = st.get(k)
            if s is None:
                if calm_anim(c["anim"]) and c["hp"] >= (c.get("max_hp") or c["hp"]) and k not in [e["ptr"] for e in out]:
                    st[k] = {"x": c["x"], "z": c["z"], "last": (t, dist, dy, f, c["anim"]), "min": (dist, dy, f),
                             "npc": c["npc"], "max_f": f or 0.0}
                continue
            if s is False:
                continue
            moved = math.hypot(c["x"] - s["x"], c["z"] - s["z"]) > CALM_M
            hurt = c["hp"] < (c.get("max_hp") or c["hp"])
            turned = (f is not None and s["last"][3] is not None and s["last"][3] > TURN_FROM and f < TURN_TO)
            if calm_anim(c["anim"]) and not moved and not hurt and not turned:
                s["last"] = (t, dist, dy, f, c["anim"])
                if dist < s["min"][0]:
                    s["min"] = (dist, dy, f)
                continue
            lt, ld, ldy, lf, la = s["last"]
            group = any(o["ptr"] != k and o["ptr"] in woke_now and math.hypot(o["x"] - c["x"], o["z"] - c["z"]) < GROUP_R
                        for o in chars)
            kind = ("hit" if hurt else "knife" if any(0 <= t - kt <= KNIFE_S for kt in knives)
                    else "group" if group else "clean")
            how = "turn" if turned and calm_anim(c["anim"]) and not moved else "move" if moved and calm_anim(c["anim"]) else "anim"
            out.append({"run": run, "t": round(t, 1), "ptr": k, "npc": s["npc"], "kind": kind, "how": how,
                        "anim": c["anim"], "was": "dormant" if dormant(la) else "idle",
                        # distance at the last calm snapshot (it noticed somewhere between that and this one) and now
                        "d_calm": round(ld, 2), "d_woke": round(dist, 2), "dy": round(ldy, 2),
                        "facing": None if lf is None else round(lf), "side": side(lf), "closest_calm": round(s["min"][0], 2),
                        "came": False, "_x": c["x"], "_z": c["z"]})
            check[k] = out[-1]
            st[k] = False
    for e in out:
        e.pop("_x"), e.pop("_z")
    for k, s in st.items():
        if s:
            quiet.append({"run": run, "ptr": k, "npc": s["npc"], "closest": round(s["min"][0], 2), "dy": round(s["min"][1], 2),
                          "side": side(s["min"][2])})
    return out, quiet


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))]


def table(evs: list[dict], quiet: list[dict]) -> dict:
    """npc → side → {n, d (median of the distance it noticed at), lo, hi, closest_quiet}"""
    out: dict = {}
    by = collections.defaultdict(list)
    for e in evs:
        if e["kind"] == "clean" and abs(e["dy"]) <= DY_MAX and (e["how"] != "turn" or e["came"]):
            # it noticed somewhere between d_calm and d_woke; take the midpoint
            by[(e["npc"], e["side"])].append((e["d_calm"] + e["d_woke"]) / 2)
            by[(e["npc"], "all")].append((e["d_calm"] + e["d_woke"]) / 2)
    qq = collections.defaultdict(list)
    for r in quiet:
        if abs(r["dy"]) <= DY_MAX:
            qq[r["npc"]].append(r["closest"])
    for (npc, sd), ds in by.items():
        out.setdefault(str(npc), {})[sd] = {"n": len(ds), "d": round(statistics.median(ds), 1),
                                             "lo": round(q(ds, 0.1), 1), "hi": round(q(ds, 0.9), 1)}
    for npc, ds in qq.items():
        out.setdefault(str(npc), {})["quiet_closest"] = {"n": len(ds), "d": round(min(ds), 1), "median": round(statistics.median(ds), 1)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args()
    evs, quiet = [], []
    for f in sorted(glob.glob(str(ROOT / "data" / "samples" / "*.track.jsonl"))):
        e, qr = events_of(f)
        evs += e
        quiet += qr
    if a.events:
        for e in evs:
            print(json.dumps(e, ensure_ascii=False))
    kinds = collections.Counter(e["kind"] for e in evs)
    hows = collections.Counter((e["how"]) for e in evs if e["kind"] == "clean")
    came = {h: f"{sum(e['came'] for e in evs if e['kind'] == 'clean' and e['how'] == h)}/{n}" for h, n in hows.items()}
    print(f"wake events {len(evs)}: {dict(kinds)} · clean ones woke by {dict(hows)}, then came at us {came} · never woke (seen calm, then out of range or run end) {len(quiet)}")
    t = table(evs, quiet)
    print(f"{'npc':>7} {'side':>6} {'n':>3} {'median':>6} {'p10':>5} {'p90':>5}")
    for npc in sorted(t):
        for sd in ("front", "side", "back", "?", "all"):
            if sd in t[npc]:
                r = t[npc][sd]
                print(f"{npc:>7} {sd:>6} {r['n']:>3} {r['d']:>6} {r['lo']:>5} {r['hi']:>5}")
        if "quiet_closest" in t[npc]:
            r = t[npc]["quiet_closest"]
            print(f"{npc:>7} {'quiet':>6} {r['n']:>3}  closest calm {r['d']} m (median {r['median']})")
    if a.json:
        Path(a.json).write_text(json.dumps({"_source": "experiments/notice_probe.py on data/samples/*.track.jsonl (2 Hz, chars ≤ 12 m)",
                                            "table": t}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"→ {a.json}")


if __name__ == "__main__":
    main()
