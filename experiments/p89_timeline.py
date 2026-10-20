"""P-89: the big hit while 255041 cuts into the 255042 fight — one timeline per run from existing records only.

  python experiments/p89_timeline.py [--before 3.0] [--after 0.6]

Sources per run (data/runs/<run>.*): hits.jsonl (blackbox bundle around the HP drop, ~60 Hz: my hp · sp · anim, foes' anim · d ·
face), ctl.jsonl (dec.rule / dec.reflex with the snapshot wall time; pad lines with the caller, wall = wall0 + (pc − sync_pc)),
scene lines (decision inputs: tick target, rule, Fight.swung). Read-only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ["20261019_205059_parish-group1", "20261019_205348_parish-group1", "20261019_205644_parish-route"]
BTN = {0x100: "LB", 0x200: "RB", 0x2000: "B", 0x4000: "X", 0x80: "RS", 0x1000: "A"}


def arg(name, default):
    return float(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def btns(b):
    return "+".join(n for k, n in BTN.items() if b & k) or "-"


def run(name, before, after):
    base = ROOT / "data" / "runs" / name
    bundles = [json.loads(x) for x in (base.with_suffix(".hits.jsonl")).read_text(encoding="utf-8").splitlines() if x.strip()]
    big = max(bundles, key=lambda b: b["hp0"] - b["lo"])
    fr = big["frames"]
    drop_t = next(f["t"] for a, f in zip(fr, fr[1:]) if f["hp"] < a["hp"] and a["hp"] - f["hp"] > 20)
    lo, hi = drop_t - before, drop_t + after
    ptr_npc = {}
    for f in fr:
        for e in f["foes"]:
            ptr_npc[e["ptr"]] = e["npc"]
    ctl = [json.loads(x) for x in base.with_suffix(".ctl.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    sy = next(x for x in ctl if x.get("k") == "sync")
    wall = lambda pc: (sy["wall0"] + (pc - sy["sync_pc"])) / 1e9  # noqa: E731
    ev = []
    prev = None
    for f in fr:
        if not lo <= f["t"] <= hi:
            continue
        fo = {ptr_npc.get(e["ptr"], e["npc"]) if False else e["ptr"]: e for e in f["foes"]}
        key = (f["hp"], f["anim"], tuple((e["npc"], e["anim"]) for e in f["foes"] if e["npc"] in (255041, 255042)))
        if key != prev:
            foes = " ".join(f"{e['npc']}@{e['ptr'] % 100000}:{e['anim']} {e['d']:.2f}m {e['face']:+d}°" for e in f["foes"]
                            if e["npc"] in (255041, 255042))
            ev.append((f["t"], "frame", f"me hp {f['hp']} sp {f['sp']} anim {f['anim']} | {foes}"))
            prev = key
        _ = fo
    for x in ctl:
        k = x.get("k")
        if k in ("dec.rule", "dec.reflex") and lo <= x["snap_t"] <= hi:
            who = ptr_npc.get(x.get("ptr"), x.get("ptr"))
            if k == "dec.rule":
                ev.append((x["snap_t"], "rule", f"{x['rule']} → {x['out']} (target {who}@{(x.get('ptr') or 0) % 100000})"))
            else:
                ev.append((x["snap_t"], "reflex", f"{x['act']} vs {x.get('npc')} anim {x.get('eanim')} age {x.get('age')}"))
        elif k == "scene" and lo - 1 <= x["t_wall"] <= hi:
            sw = {p % 100000: round(v["_t"], 2) for p, v in x["fight"]["swung"]["_dict"]}
            ev.append((x["t_wall"], "scene", f"rule {x['rule']} → {x['out']} · tick target {ptr_npc.get(x['tick']['ptr'])}@{x['tick']['ptr'] % 100000} "
                                              f"anim {x['tick']['a']} h {x['tick']['h']:.2f} · swung(s ago) {sw}"))
    pb = None
    for x in ctl:
        if x.get("k") != "pad":
            continue
        t = wall(x["pc"])
        if lo <= t <= hi and x["btn"] != pb:
            ev.append((t, "pad", f"{btns(x['btn'])} ({x['caller']})"))
        pb = x["btn"]
    ev.sort(key=lambda e: e[0])
    out = [f"== {name}: bundle n{big['n']}, HP {big['hp0']} → {big['lo']}, blame {big['blame']}", f"   drop at t0 = {drop_t:.3f}"]
    for t, k, s in ev:
        out.append(f"   {t - drop_t:+6.3f}  {k:6} {s}")
    return "\n".join(out)


def main():
    before, after = arg("--before", 3.0), arg("--after", 0.6)
    text = "\n\n".join(run(r, before, after) for r in RUNS)
    print(text)
    if "--out" in sys.argv:
        Path(sys.argv[sys.argv.index("--out") + 1]).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
