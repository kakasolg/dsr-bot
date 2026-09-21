"""
Jev 그림자/실전 결과 비교 — 규칙만 vs Jev 를 같은 잣대(생존 중앙값)로 놓고 본다.

  python jev_report.py

  · results.jsonl 을 jev 모드(off/shadow/live)별로 묶어 n·중앙값·최대
  · 에피소드 행의 "jev" 기록에서: 규칙 모드와의 일치율, 사망 전 10초 안에 retreat≥0.5 또는 threat≥2 가 있었는지(조기 경보율)
채택 기준: live 의 중앙값이 off/shadow 보다 높고, 조기 경보율이 유의미하게 높을 때만.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
EPISODES = ROOT / "data" / "episodes"
RESULTS = ROOT / "data" / "playbook" / "results.jsonl"


def main() -> None:
    by_mode: dict[str, list[float]] = {}
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            m = (r.get("extra") or {}).get("jev", "off")
            by_mode.setdefault(m, []).append(r["seconds"])
    print("생존시간 (jev 모드별):")
    for m, secs in sorted(by_mode.items()):
        print(f"  {m:6s} n={len(secs):3d} median={statistics.median(secs):6.0f}s max={max(secs):5.0f}s")

    agree = total = 0
    deaths = warned = 0
    for p in sorted(EPISODES.glob("*.jsonl")):
        rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        jrows = [r for r in rows if "jev" in r]
        if not jrows:
            continue
        for r in jrows:
            total += 1
            agree += r["jev"]["mode"] == r["jev"]["rule_mode"]
        end = next((r for r in rows if r.get("event") == "end"), None)
        if end and end.get("reason") == "death":
            deaths += 1
            t_death = end["t"]
            warned += any((r["jev"]["retreat"] >= 0.5 or (r["jev"]["threat"] or 0) >= 2)
                          for r in jrows if t_death - 10 <= r["t"] <= t_death)
    if total:
        print(f"Jev 응답 {total}건: 규칙 모드와 일치 {agree/total:.0%}")
    if deaths:
        print(f"사망 {deaths}건 중 사망 전 10초 안에 Jev 경보(retreat≥0.5 or threat≥2): {warned} ({warned/deaths:.0%})")
    if not total:
        print("Jev 기록 없음 — learn.py ... --jev shadow 로 먼저 돌리세요")


if __name__ == "__main__":
    main()
