"""Shrink the local fight-decision records (data/runs/*.ctl.jsonl, gitignored, ~650 MB) into one small file
[cloud] can read: data/samples/ctl_trim_<date>.jsonl.gz.

    python ctl_trim.py [out.jsonl.gz]

Cloud request c83f86f4 (11-15): count stretches where the tick rules repeat the same choice without progress, and A-B-A-B
alternations. Kept per fight decision only what that count needs; the full records stay in data/runs/.

Rows (one JSON object per line; "k" says which):
  run   {k, run, cmd, argv, commit, scenes: bool}                     one per run, before its rows
  s     scene (--ctl-scenes): {t, rule, out, tp (target ptr, short id), npc, a (target anim), h (dist m), dy,
        thp (target hp), hp, sp, my (player anim), near (live foes ≤ 5 m), hits [kind…], dealt, decl (rule ids)}
  r     dec.rule only (runs without scenes; in runs with scenes the scene rows replace them): {t, rule, out, tp, n}
  hold  rule_hold event from the run's event log (.jsonl): {t, rule, secs, hp0, hp1, on0, on1, npc, zone}
        — its t is the event log's own clock (run elapsed), not the ctl clock of s/r rows
  rules {k: "rules", names: [...]}   last row: index → rule name for "decl"
t = seconds since the run's first record (perf_counter). tp = small per-run number for the target ptr.
"decl" is the scene's 'declined' list as recorded (only in runs from about 11-11 on); its exact meaning is in
souls/duel.py, not decided here.
"""
from __future__ import annotations

import gzip
import json
import sys
import time
from pathlib import Path

RUNS = Path("data/runs")


def trim_run(ctl: Path, out, rule_ids: dict) -> dict:
    run = ctl.name[: -len(".ctl.jsonl")]
    pc0 = None
    ptrs: dict = {}
    n = {"s": 0, "r": 0, "hold": 0}
    lines = []
    hdr = {}
    has_scene = False

    def tp(p):
        if p is None:
            return None
        return ptrs.setdefault(p, len(ptrs) + 1)

    for line in open(ctl, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        k = d.get("k")
        pc = d.get("pc")
        if pc0 is None and pc is not None:
            pc0 = pc
        t = None if pc is None or pc0 is None else round((pc - pc0) / 1e9, 3)
        if k == "hdr":
            hdr = {"cmd": d.get("cmd"), "argv": d.get("argv"), "commit": (d.get("commit") or "")[:9]}
        elif k == "scene":
            has_scene = True
            tick = d.get("tick") or {}
            snap = d.get("snap") or {}
            pl = snap.get("player") or {}
            ptr = tick.get("ptr")
            tgt = next((c for c in snap.get("chars") or [] if c.get("ptr") == ptr), {})
            near = sum(1 for c in snap.get("chars") or []
                       if c.get("team") == 6 and c.get("hp", 0) > 0 and c.get("dist", 99) <= 5.0)
            res = d.get("res") or {}
            row = {"k": "s", "t": t, "rule": d.get("rule"), "out": d.get("out"), "tp": tp(ptr),
                   "npc": tgt.get("npc_param") or res.get("npc"), "a": tick.get("a"),
                   "h": None if tick.get("h") is None else round(tick["h"], 2),
                   "dy": None if tick.get("dy") is None else round(tick["dy"], 2),
                   "thp": tgt.get("hp"), "hp": pl.get("hp"), "sp": pl.get("sp"), "my": pl.get("anim"), "near": near,
                   "hits": [h.get("kind") for h in res.get("hits") or []], "dealt": res.get("dealt")}
            if "declined" in d:
                row["decl"] = [rule_ids.setdefault(r, len(rule_ids)) for r in d["declined"]]
            lines.append(row); n["s"] += 1
        elif k == "dec.rule":
            lines.append({"k": "r", "t": t, "rule": d.get("rule"), "out": d.get("out"), "tp": tp(d.get("ptr")),
                          "n": d.get("n")})
            n["r"] += 1
    if has_scene:                       # scenes carry the same decisions with state → drop the bare dec.rule rows
        lines = [r for r in lines if r["k"] != "r"]
        n["r"] = 0
    ev = RUNS / f"{run}.jsonl"
    if ev.exists():
        for line in open(ev, encoding="utf-8", errors="replace"):
            if '"rule_hold"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            row = {"k": "hold", **{x: d.get(x) for x in ("t", "rule", "secs", "hp0", "hp1", "on0", "on1", "npc", "zone")}}
            lines.append(row); n["hold"] += 1
    if not lines:
        return n
    out.write(json.dumps({"k": "run", "run": run, **hdr, "scenes": has_scene}, ensure_ascii=False) + "\n")
    for r in lines:
        out.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    return n


def main() -> None:
    dst = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(f"data/samples/ctl_trim_{time.strftime('%Y%m%d')}.jsonl.gz")
    rule_ids: dict = {}
    tot = {"runs": 0, "s": 0, "r": 0, "hold": 0}
    with gzip.open(dst, "wt", encoding="utf-8") as out:
        for ctl in sorted(RUNS.glob("*.ctl.jsonl")):
            n = trim_run(ctl, out, rule_ids)
            if sum(n.values()):
                tot["runs"] += 1
                for x in n:
                    tot[x] += n[x]
        out.write(json.dumps({"k": "rules", "names": sorted(rule_ids, key=rule_ids.get)}) + "\n")
    print(f"{dst}  {dst.stat().st_size / 1e6:.1f} MB  {tot}")


if __name__ == "__main__":
    main()
