"""Combo decision table report (P-121): per situation cell, what was tried, how it went, and why.

  python combo_report.py [<run> ...]      runs = 20261103_123006_clear-ramp (data/runs or data/samples); newest run if none

Reads the "combo" events that run.py --combo-only writes (souls/duel._combo_strike, souls/combo_table). One block per cell
(distance band / foe kind / foe state / floor behind / floor toward it): the table's plan and its source, tries, verdicts,
damage dealt and taken, and the reasons counted. Cells whose source is 미정 are the bot's default — not judged by MoKa yet.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent


def events_of(run: str) -> list[dict]:
    name = Path(run).name.removesuffix(".jsonl").removesuffix(".log").removesuffix(".txt")
    for d in (ROOT / "data" / "runs", ROOT / "data" / "samples"):
        f = d / f"{name}.jsonl"
        if f.exists():
            return [r for r in map(json.loads, f.read_text(encoding="utf-8").splitlines()) if r.get("ev") == "combo"]
    raise SystemExit(f"{name}: no .jsonl in data/runs or data/samples")


def cell(r: dict) -> str:
    f = lambda v: "O" if v else "X" if v is False else "?"
    return (("진입 " if r.get("phase") == "entry" else "")
            + f"{r['dist']}/{r['kind']}/{r['state']} 뒤{f(r.get('back'))} 앞{f(r.get('front'))}")


def report(rows: list[dict]) -> list[str]:
    by = defaultdict(list)
    for r in rows:
        by[cell(r)].append(r)
    out = []
    for k in sorted(by, key=lambda k: -len(by[k])):
        rs = by[k]
        v = Counter(r["verdict"] for r in rs)
        out.append(f"[{k}] {len(rs)}번 — " + " · ".join(f"{n} {c}" for n, c in v.most_common())
                   + f" | 준 피해 {sum(r['dmg'] for r in rs)}, 받은 피해 {sum(r['taken'] for r in rs)}")
        out.append(f"   표: {' → '.join(rs[-1]['plan']) or '없음'}  ({rs[-1]['src']})")
        used = Counter(r["used"] or "없음" for r in rs)
        out.append("   쓴 것: " + " · ".join(f"{n} {c}" for n, c in used.most_common()))
        for (vd, why), c in Counter((r["verdict"], r["reason"].split(" | ")[0]) for r in rs).most_common():
            out.append(f"   {vd} ×{c}: {why}")
        nc = Counter(r["no_combo"].split(" — ")[-1] for r in rs if r.get("no_combo"))
        for why, c in nc.most_common():
            out.append(f"   약공 ×{c} — 콤보 안 한 이유: {why}")
    return out


def main() -> int:
    runs = sys.argv[1:]
    if not runs:
        newest = max((ROOT / "data" / "runs").glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        runs = [newest.name]
    rows = [r for run in runs for r in events_of(run)]
    print(f"{', '.join(Path(r).name for r in runs)}: 콤보 {len(rows)}번")
    for line in report(rows):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
