"""P-89 game A/B (first group only): baseline runs (before f36afcd) vs runs with the 255041 windup entry. Read-only.

  python experiments/p89_ab.py --base RUN [RUN …] --new RUN [RUN …] [--out FILE]

Per run, from data/runs/<run>.*:
  · scenes (ctl, decision inputs — strikes always kept, pose rules while the target staggers / winds up): every decision whose
    target is 255041 in 3004, with the recorded attack age → strikes before landing (age < 2.3 s) vs late_windup_block
  · dec.rule records on 255041 (late_windup_block ticks, folded n)
  · blackbox bundles (hits.jsonl): every drop ≥ 150 in the group fight, with the nearest 255041's anim and how long it had
    been in that anim (from the bundle's 60 Hz frames — if the bundle starts after the anim began, '≥')
  · the log's group summary line (left alive · results · seconds · taken · estus) and 255042 bolt-like hits (drop with 255042 in
    a 3000-series anim ≥ 2 m away) counted apart
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAND = 2.3          # windup_land_s 2.1 + duel.LAND_PAD 0.2
STRIKES = {"after_swing", "hit_first", "attack", "stagger_punish", "finish", "finish_first", "backstab_swing"}


def args(flag):
    if flag not in sys.argv:
        return []
    i = sys.argv.index(flag) + 1
    out = []
    while i < len(sys.argv) and not sys.argv[i].startswith("--"):
        out.append(sys.argv[i])
        i += 1
    return out


def lines(p: Path):
    return [json.loads(x) for x in p.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()] if p.exists() else []


def one(run: str) -> dict:
    base = ROOT / "data" / "runs" / run
    ctl = lines(base.with_suffix(".ctl.jsonl"))
    ptr41 = set()
    for b in lines(base.with_suffix(".hits.jsonl")):
        for f in b["frames"]:
            for e in f["foes"]:
                if e["npc"] == 255041:
                    ptr41.add(e["ptr"])
    scenes = []
    for x in ctl:
        if x.get("k") != "scene":
            continue
        c = next((c for c in x["snap"]["chars"] if c["ptr"] == x["tick"]["ptr"]), None)
        if c and c["npc_param"] == 255041:
            ptr41.add(c["ptr"])
            if x["tick"]["a"] == 3004:
                age = (x.get("reflex") or {}).get("age")
                scenes.append((x["rule"], None if age is None else round(age, 2)))
    lwb = sum(x.get("n", 1) for x in ctl if x.get("k") == "dec.rule" and x.get("rule") == "late_windup_block" and x.get("ptr") in ptr41)
    early = [s for s in scenes if s[0] in STRIKES and s[1] is not None and s[1] < LAND]
    drops = []
    for b in lines(base.with_suffix(".hits.jsonl")):
        fr = b["frames"]
        for a, f in zip(fr, fr[1:]):
            d = a["hp"] - f["hp"]
            if d < 20:
                continue
            f41 = [e for e in f["foes"] if e["npc"] == 255041 and e["hp"] > 0]
            f42 = [e for e in f["foes"] if e["npc"] == 255042 and e["hp"] > 0]
            near = min(f41, key=lambda e: e["d"]) if f41 else None
            info = {"dmg": d}
            if near:
                an = near["anim"]
                t0 = f["t"]
                for g in reversed(fr[:fr.index(f) + 1]):
                    e = next((e for e in g["foes"] if e["ptr"] == near["ptr"]), None)
                    if e is None or e["anim"] != an:
                        break
                    t0 = g["t"]
                info.update(n41_anim=an, n41_d=near["d"], n41_age=round(f["t"] - t0, 2), age_from_bundle_start=t0 == fr[0]["t"])
            if f42:
                e = min(f42, key=lambda e: e["d"])
                info.update(n42_anim=e["anim"], n42_d=e["d"])
            drops.append(info)
    log = (base.with_suffix(".log")).read_text(encoding="utf-8", errors="replace") if base.with_suffix(".log").exists() else ""
    m = re.search(r"── 첫 무리: (.*)", log)
    return {"run": run, "summary": m.group(1).strip() if m else None, "scenes_255041_3004": scenes, "early_strikes": len(early),
            "late_windup_block_ticks": lwb, "drops": drops,
            "big_3004": sum(1 for d in drops if d["dmg"] >= 150 and d.get("n41_anim") == 3004),
            "bolt_like": sum(1 for d in drops if d.get("n42_anim", -1) in range(3000, 3500) and d.get("n42_d", 0) >= 2.0
                             and d.get("n41_anim") != 3004)}


def main():
    out = []
    for tag, runs in (("baseline", args("--base")), ("new", args("--new"))):
        out.append(f"== {tag}")
        for r in runs:
            x = one(r)
            out.append(f"{r}: {x['summary']}")
            out.append(f"   255041·3004 decisions (rule, age): {x['scenes_255041_3004']} → strikes before {LAND} s: {x['early_strikes']}, "
                       f"late_windup_block ticks on 255041: {x['late_windup_block_ticks']}")
            out.append(f"   drops ≥20: {x['drops']}")
            out.append(f"   big hits during 255041 3004: {x['big_3004']} · 255042-bolt-like: {x['bolt_like']}")
    text = "\n".join(out)
    print(text)
    if "--out" in sys.argv:
        Path(sys.argv[sys.argv.index("--out") + 1]).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
