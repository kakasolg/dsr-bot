"""Runs 10-09..10-27 whose settings args have ctl or ctl_scenes true: ctl.jsonl presence and record counts. python inv_g2.py <repo> <out>"""
import collections, json, sys
from pathlib import Path
repo, out = Path(sys.argv[1]), Path(sys.argv[2])
rows, skipped = [], []
for s in sorted((repo / "data/runs").glob("*.settings.json")):
    run = s.name[: -len(".settings.json")]
    day = run[:8]
    if not ("20261009" <= day <= "20261027"):
        continue
    try:
        d = json.loads(s.read_text(encoding="utf-8"))
    except Exception as e:
        skipped.append({"run": run, "why": f"settings read failed: {e!r}"[:200]})
        continue
    a = d.get("args") or {}
    if not (a.get("ctl") or a.get("ctl_scenes")):
        continue
    p = repo / "data/runs" / f"{run}.ctl.jsonl"
    row = {"run": run, "cmd": a.get("cmd"), "args_ctl": a.get("ctl"), "args_ctl_scenes": a.get("ctl_scenes"),
           "args_ctl_spans": a.get("ctl_spans"), "ctl_file": f"data/runs/{run}.ctl.jsonl", "exists": p.is_file()}
    if p.is_file():
        c, broken = collections.Counter(), 0
        try:
            for l in p.read_bytes().decode("utf-8", "replace").splitlines():
                try:
                    c[json.loads(l).get("k")] += 1
                except Exception:
                    broken += 1
            row.update(bytes=p.stat().st_size, scene=c.get("scene", 0), pad=c.get("pad", 0), dec_rule=c.get("dec.rule", 0),
                       end_record=c.get("end", 0) > 0, broken_lines=broken)
        except Exception as e:
            row["read_error"] = repr(e)[:200]
    rows.append(row)
tot = {"runs": len(rows), "with_ctl_file": sum(r["exists"] for r in rows),
       "scene": sum(r.get("scene", 0) for r in rows), "pad": sum(r.get("pad", 0) for r in rows),
       "dec_rule": sum(r.get("dec_rule", 0) for r in rows), "with_end_record": sum(bool(r.get("end_record")) for r in rows)}
(out / "g2_ctl_presence.json").write_text(json.dumps({
    "scope": "data/runs/*.settings.json dated 20261009..20261027 with args.ctl or args.ctl_scenes true",
    "note": "runs without a settings.json (or with a broken one) are not covered; counts parse every line's k",
    "totals": tot, "settings_unreadable": skipped, "runs": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
print(tot, len(skipped))
