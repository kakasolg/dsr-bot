"""스타일(guard / backstep)별 판 비교 — 백스텝은 한두 판으로 못 정한다 (사용자 2026-09-24: "계속 반복시켜 최적을 오랫동안 찾아야").

  python style_report.py [--since 20260924_1530]

읽는 것: data/runs/<시각>_clear-ramp.jsonl (+ .log)
  · style 사건 (없으면 guard)  · duel (killed·secs·taken)  · escape  · evade (반사가 피한 것 — kind, 그 뒤 1.3 s 안에 맞았나)
  · .log 의 "헛친 뒤 → light×n 피해 X, 내 피해 Y" (백스텝 뒤 치기: 맞혔나 / 안 맞았나)
보는 것 (스타일별): 판 수, 처치, 처치당 받은 피해, 처치 시간 중앙값, 강종, 회피 성공률, 헛친 뒤 치기 성공률
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RUNS = Path(__file__).resolve().parent / "data" / "runs"
PUNISH = re.compile(r"헛친 뒤 → \w+×\d+ 피해 (\d+), 내 피해 (\d+)")
BSATK = re.compile(r"백스텝 공격 → 피해 (\d+), 내 피해 (\d+)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="20260924_1500")
    a = ap.parse_args()
    G: dict = defaultdict(lambda: {"runs": 0, "kills": 0, "duels": 0, "taken": 0, "ksecs": [], "escapes": 0,
                                   "evade": 0, "evade_ok": 0, "evade_kind": defaultdict(int), "punish": 0, "punish_hit": 0, "punish_safe": 0,
                                   "run_secs": []})
    for js in sorted(RUNS.glob("2026*_clear-ramp.jsonl")):
        if js.stem < a.since:
            continue
        rows = [json.loads(l) for l in js.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not any(r["ev"] == "result" for r in rows):
            continue                                   # 중단된 판은 뺀다
        style = next((r["style"] for r in rows if r["ev"] == "style"), None)
        if style is None:                                  # style 사건이 없던 초기 판 — .log 의 "스타일:" 줄로
            lg = js.with_suffix(".log")
            txt = lg.read_text(encoding="utf-8", errors="replace") if lg.exists() else ""
            style = "backstep" if "스타일: backstep" in txt else "guard"
        g = G[style]
        g["runs"] += 1
        g["run_secs"].append(max(r["t"] for r in rows))
        for r in rows:
            if r["ev"] == "duel":
                g["duels"] += 1
                g["taken"] += r["taken"]
                if r["result"] == "killed" and r["secs"] > 0:
                    g["kills"] += 1
                    g["ksecs"].append(r["secs"])
            elif r["ev"] == "escape":
                g["escapes"] += 1
            elif r["ev"] == "evade":
                g["evade"] += 1
                g["evade_ok"] += r.get("taken", 0) == 0
                g["evade_kind"][r["kind"]] += 1
        log = js.with_suffix(".log")
        if log.exists():
            txt = log.read_text(encoding="utf-8", errors="replace")
            for m in PUNISH.finditer(txt):
                g["punish"] += 1
                g["punish_hit"] += int(m.group(1)) > 0
                g["punish_safe"] += int(m.group(2)) == 0
            for m in BSATK.finditer(txt):
                g["bs"] = g.get("bs", 0) + 1
                g["bs_hit"] = g.get("bs_hit", 0) + (int(m.group(1)) > 0)
                g["bs_safe"] = g.get("bs_safe", 0) + (int(m.group(2)) == 0)
    if not G:
        print("판 없음")
        return
    print(f"{'스타일':9s} {'판':>3s} {'처치':>4s} {'처치당 피해':>8s} {'처치 s 중앙':>8s} {'판 s 중앙':>7s} {'강종':>4s} {'회피 n/성공':>10s} {'헛친뒤치기 n/맞힘/무피해':>16s}")
    for st, g in G.items():
        print(f"{st:9s} {g['runs']:3d} {g['kills']:4d} {g['taken'] / max(1, g['kills']):8.0f} "
              f"{statistics.median(g['ksecs']) if g['ksecs'] else 0:8.1f} {statistics.median(g['run_secs']):7.0f} {g['escapes']:4d} "
              f"{g['evade']:4d}/{(g['evade_ok'] / g['evade'] if g['evade'] else 0):4.0%}  "
              f"{g['punish']:3d}/{g['punish_hit']:3d}/{g['punish_safe']:3d}  백스텝공격 {g.get('bs',0)}/{g.get('bs_hit',0)}/{g.get('bs_safe',0)}  {dict(g['evade_kind']) if g['evade'] else ''}")


if __name__ == "__main__":
    main()
