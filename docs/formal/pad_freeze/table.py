"""out/results.tsv → markdown tables for REPORT.md (properties by variant; probes by variant). Prints to stdout."""
import csv
from pathlib import Path

rows = list(csv.DictReader(open(Path(__file__).parent / "out" / "results.tsv", encoding="utf-8"), delimiter="\t"))
VARIANTS = ["current", "block", "ownerNeutral", "both", "minimal"]


def key(r):
    flags = ("noguard " if r["nguard"] == "False" else "") + ("hold " if r["nhold"] == "True" else "")
    return f"{r['prop']} · {r['script']} · m{r['maxops']}" + (f" · {flags.strip()}" if flags else "")


def cell(r):
    if r is None:
        return "—"
    v = {"HOLDS": "성립", "VIOLATED": "**위반**"}.get(r["verdict"], r["verdict"])
    return f"{v} {int(r['distinct']):,}" + ("" if r["verdict"] == "HOLDS" else f" (trace {r['trace']})")


for title, pred in (("성질", lambda r: not r["prop"].startswith("R")), ("도달 탐침", lambda r: r["prop"].startswith("R"))):
    keys = []
    by = {}
    for r in rows:
        if not pred(r):
            continue
        k = key(r)
        if k not in keys:
            keys.append(k)
        by[(k, r["variant"])] = r
    print(f"\n### {title}\n")
    print("| 실행 (성질 · 스크립트 · 호출 상한 · 설정) | " + " | ".join(VARIANTS) + " |")
    print("|---|" + "---|" * len(VARIANTS))
    for k in keys:
        print(f"| {k} | " + " | ".join(cell(by.get((k, v))) for v in VARIANTS) + " |")
errors = [r["name"] for r in rows if r["verdict"] not in ("HOLDS", "VIOLATED")]
print(f"\n실행 {len(rows)}회, 정상 완료 아님(ERROR/TYPE-ERROR) {len(errors)}회" + (f": {errors}" if errors else ""))
