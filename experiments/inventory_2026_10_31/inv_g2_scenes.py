"""G2 scene links: one line per scene (no snapshot body) for the runs in g2_ctl_presence.json. Read only.
python experiments/inventory_2026_10_31/inv_g2_scenes.py <repo> <outdir>

Definitions (as requested, 2026-10-31):
  fight key  = "<fight.orig_ptr or fight.ptr>@<t_wall + fight.t0._t, 2 dp>" (G2 scenes carry no fight id)
  hostile    = snap.chars with hp > 0 and team != player team; counts by chars[].dist (scene list is <= 25 m)
  scene's dec.rule = last MainThread dec.rule before the scene with the same rule and snap_t equal (1e-4 s) to the scene's
                     t_wall or t_wall + snap.t (match "snap_t"); else the dec.rule right before the scene (no scene or
                     dec.rule between) when it has the same rule (match "adjacent_same_rule" - its snap_t differs);
                     else null with a reason
  prev dec.rule    = last MainThread dec.rule before the scene (any rule)
  pad window = MainThread pad records with seq strictly between (the last scene or dec.rule before the scene's dec.rule)
               and the scene's dec.rule
  next hits  = res.hits of the next scene of the same fight key, items past this scene's hits length
"""
import collections, json, sys
from pathlib import Path

repo, out = Path(sys.argv[1]), Path(sys.argv[2])
runs = [r["run"] for r in json.loads((out / "g2_ctl_presence.json").read_text(encoding="utf-8"))["runs"]]


def tval(v):
    return v.get("_t") if isinstance(v, dict) else v


def caller_fn(c):
    return ":".join(c.split(":")[:2]) if c else None


stats = collections.Counter()
with open(out / "g2_scene_links.jsonl", "w", encoding="utf-8", newline="\n") as fo:
    for run in runs:
        p = repo / "data/runs" / f"{run}.ctl.jsonl"
        try:
            R = [json.loads(l) for l in p.read_bytes().decode("utf-8").splitlines() if l.strip()]
        except Exception as e:
            fo.write(json.dumps({"run": run, "read_error": repr(e)[:200]}) + "\n"); stats["read_error"] += 1
            continue
        main = [x for x in R if x.get("th") == "MainThread"]
        decs = [x for x in main if x["k"] == "dec.rule"]
        marks = [x for x in main if x["k"] in ("dec.rule", "scene")]
        pads = [x for x in main if x["k"] == "pad"]
        scenes = [x for x in R if x["k"] == "scene"]
        keys = []
        for s in scenes:
            f = s.get("fight") or {}
            t0 = tval(f.get("t0"))
            keys.append(f"{f.get('orig_ptr') or f.get('ptr')}@{(s['t_wall'] + t0):.2f}" if t0 is not None else None)
        for i, s in enumerate(scenes):
            snap = s.get("snap") or {}
            pl = snap.get("player") or {}
            hostile = [c for c in snap.get("chars") or [] if (c.get("hp") or 0) > 0 and c.get("team") != pl.get("team")]
            hits = (s.get("res") or {}).get("hits") or []
            before = [d for d in decs if d["seq"] < s["seq"]]
            prev = before[-1] if before else None
            st = (s["t_wall"], s["t_wall"] + (snap.get("t") or 0.0))
            mine = next((d for d in reversed(before) if d.get("rule") == s.get("rule") and d.get("snap_t") is not None
                         and min(abs(d["snap_t"] - v) for v in st) < 1e-4), None)
            how = "snap_t" if mine is not None else None
            if mine is None and prev is not None and prev.get("rule") == s.get("rule")                     and not any(prev["seq"] < m["seq"] < s["seq"] for m in marks):
                mine, how = prev, "adjacent_same_rule"
            nomatch = None if mine is not None else (
                "no dec.rule before the scene" if prev is None else
                "same rule only earlier, not adjacent and snap_t differs" if any(d.get("rule") == s.get("rule") for d in before) else
                "no dec.rule with this rule before the scene")
            nxt = next((j for j in range(i + 1, len(scenes)) if keys[j] == keys[i] and keys[i] is not None), None)
            if nxt is not None:
                nh = (scenes[nxt].get("res") or {}).get("hits") or []
                grown, why = nh[len(hits):], None
            else:
                grown, why = None, ("no_next_scene" if i == len(scenes) - 1 else "fight_end")
            win = None
            if mine is not None:
                lo = max((m["seq"] for m in marks if m["seq"] < mine["seq"]), default=-1)
                w = [x for x in pads if lo < x["seq"] < mine["seq"]]
                bits = 0
                for x in w:
                    bits |= x.get("btn") or 0
                win = {"from_seq": lo, "to_seq": mine["seq"], "n": len(w),
                       "callers": sorted({caller_fn(x.get("caller")) for x in w if x.get("caller")}),
                       "btn_or": bits, "first_pc": w[0]["pc"] if w else None, "last_pc": w[-1]["pc"] if w else None}
                stats["window_empty" if not w else "window_nonempty"] += 1
                stats["match_" + how] += 1
            else:
                stats["no_scene_dec_rule: " + nomatch] += 1
            tick = s.get("tick") or {}
            row = {"run": run, "scene_seq": s["seq"], "scene_pc": s.get("pc"), "schema": s.get("schema"),
                   "snap_t": s["t_wall"] + (snap.get("t") or 0.0), "fight": keys[i], "rule": s.get("rule"), "out": s.get("out"),
                   "target_npc": (s.get("res") or {}).get("npc"), "target_h": tick.get("h"),
                   "hostile_25m": sum(1 for c in hostile if (c.get("dist") or 1e9) <= 25.0),
                   "hostile_4m": sum(1 for c in hostile if (c.get("dist") or 1e9) <= 4.0),
                   "hits_len": len(hits),
                   "prev_dec_rule": ({"seq": prev["seq"], "rule": prev.get("rule"), "same_as_scene": prev.get("rule") == s.get("rule")}
                                     if prev else None),
                   "scene_dec_rule_seq": mine["seq"] if mine else None, "scene_dec_rule_match": how,
                   "scene_dec_rule_null_reason": nomatch,
                   "next_scene_new_hits": grown, "next_scene_null_reason": why, "pad_window": win}
            fo.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            stats["scenes"] += 1
        stats["runs"] += 1
print(dict(stats))
