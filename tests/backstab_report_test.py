"""backstab_report offline test — on the three human backstab demos in data/samples.

  python tests/backstab_report_test.py
"""
from __future__ import annotations

import glob
import sys

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import backstab_report as B

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


paths = sorted(glob.glob("data/samples/observe_backstab_*.jsonl"))
check(f"샘플 {len(paths)}개", len(paths) >= 3)
for p in paths:
    w, pads = B.rows_of(p)
    bs = B.backstabs(w)
    check(f"{p.split('/')[-1]}: 뒤잡기 1번 찾음", len(bs) == 1)
    t = bs[0][0]
    press = [ms for ms in B.r1_presses(pads) if 0 < t - ms <= 1200]
    r = min(w, key=lambda r: abs(r["ms"] - press[-1]))
    e = next(e for e in r["e"] if e["id"] == bs[0][1])
    g = B.geometry(r, e)
    check(f"  R1 은 킬 0.8~1.0 s 전, 락온, 뒤 ≥ 130°", press and 800 <= t - press[-1] <= 1000 and g["lock"] and g["behind"] >= 130)
rep = B.report(paths[0])
check("리포트에 접근 요약", "circling ≤1 m" in rep and "lock-on 11/11" in rep)

print("전부 통과" if not fails else f"실패 {fails}")
sys.exit(1 if fails else 0)
