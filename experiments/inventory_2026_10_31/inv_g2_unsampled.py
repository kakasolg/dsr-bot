"""Runs in g2_ctl_presence.json with no tracked *settings.json whose name holds the run stamp (sample.py may add a label):
metadata from data/runs/<run>.settings.json. Read only. python experiments/inventory_2026_10_31/inv_g2_unsampled.py <repo> <outdir>"""
import json, subprocess, sys
from pathlib import Path

repo, out = Path(sys.argv[1]), Path(sys.argv[2])
runs = [r["run"] for r in json.loads((out / "g2_ctl_presence.json").read_text(encoding="utf-8"))["runs"]]
tracked = [f for f in subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True, text=True).stdout.split()
           if f.endswith("settings.json")]
rows = []
for run in runs:
    if any(run[:15] in f for f in tracked):
        continue
    p = repo / "data/runs" / f"{run}.settings.json"
    r = {"run": run, "settings": f"data/runs/{run}.settings.json"}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        code, a, g = d.get("code") or {}, d.get("args") or {}, d.get("game") or {}
        hp = g.get("hp")
        r.update(date=d.get("started") or run[:8], commit=code.get("commit"), dirty=code.get("dirty"),
                 diff_sha1=code.get("diff_sha1"), cmd=a.get("cmd"), seg=a.get("seg"), weapon=g.get("weapon"),
                 max_hp=hp[1] if isinstance(hp, list) and len(hp) > 1 else None,
                 missing=[k for k, v in (("code", code), ("args", a), ("game", g)) if not v])
    except FileNotFoundError:
        r["read_error"] = "settings.json not found"
    except Exception as e:
        r["read_error"] = repr(e)[:200]
    rows.append(r)
(out / "g2_unsampled_meta.json").write_text(json.dumps({
    "scope": "g2_ctl_presence.json runs with no git-tracked *settings.json whose file name contains the run stamp (YYYYMMDD_HHMMSS)",
    "count": len(rows), "runs": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(rows), [r.get("read_error") for r in rows if r.get("read_error")])
for r in rows: print(r["run"], r.get("cmd"), r.get("seg"), r.get("commit", "")[:7] if r.get("commit") else None, r.get("dirty"), r.get("weapon"), r.get("max_hp"), r.get("missing"))
