"""
A/B 결과 — 팔(arm)별 생존 성적을 나란히. learn.py --arm 으로 만든 data/playbook/arms/<이름>/ 을 읽는다.

  python ab_report.py jev rules

보는 것: 에피소드별 생존초 · 중앙값/평균/최대 · 전반 vs 후반 중앙값(학습이 되고 있나) · 버전별 중앙값 · 플레이북 변경/롤백 이력.
두 팔이면 중앙값 차이의 순열검정 p 값도 찍는다 — n=10 이면 대개 유의하지 않다. 그게 정상이고, 그래서 더 돌려야 한다.
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ARMS = Path(__file__).resolve().parent / "data" / "playbook" / "arms"


def load(arm: str) -> tuple[list[dict], list[str]]:
    d = ARMS / arm
    rows = [json.loads(l) for l in (d / "results.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    log = (d / "learn.log").read_text(encoding="utf-8").splitlines() if (d / "learn.log").exists() else []
    return rows, log


def perm_test(a: list[float], b: list[float], n: int = 10000) -> float:
    """중앙값 차이 |med(a)-med(b)| 가 라벨을 섞었을 때 얼마나 자주 나오나."""
    obs = abs(statistics.median(a) - statistics.median(b))
    pool, k, hits = a + b, len(a), 0
    rng = random.Random(0)
    for _ in range(n):
        rng.shuffle(pool)
        if abs(statistics.median(pool[:k]) - statistics.median(pool[k:])) >= obs:
            hits += 1
    return hits / n


def main() -> None:
    arms = sys.argv[1:] or sorted(p.name for p in ARMS.iterdir() if p.is_dir())
    secs_by_arm = {}
    for arm in arms:
        rows, log = load(arm)
        stalls = sum(r.get("reason") == "stall" for r in rows)
        secs = [r["seconds"] for r in rows if r["seconds"] > 0 and r.get("reason") != "stall"]
        secs_by_arm[arm] = secs
        print(f"═══ {arm}  (에피소드 {len(secs)}{f', 멈춤 제외 {stalls}' if stalls else ''}, jev={rows[0].get('jev') if rows else '?'}) ═══")
        print("  생존초:", " ".join(f"{s:.0f}" for s in secs))
        if not secs:
            continue
        half = len(secs) // 2
        print(f"  중앙값 {statistics.median(secs):.0f}s  평균 {statistics.mean(secs):.0f}s  최대 {max(secs):.0f}s  "
              f"사망 {sum(r['reason'] == 'death' for r in rows)}/{len(rows)}")
        if half >= 2:
            print(f"  전반 {half}개 중앙값 {statistics.median(secs[:half]):.0f}s → 후반 {len(secs) - half}개 중앙값 {statistics.median(secs[half:]):.0f}s")
        by_v: dict[int, list[float]] = {}
        for r in rows:
            by_v.setdefault(r["version"], []).append(r["seconds"])
        print("  버전별:", "  ".join(f"v{v} n={len(s)} med={statistics.median(s):.0f}s" for v, s in sorted(by_v.items())))
        for line in log:
            if "★ 플레이북" in line or "✖ 롤백" in line or "복기 선택" in line:
                print("   ", line)
    if len(arms) == 2 and all(secs_by_arm.values()):
        a, b = (secs_by_arm[x] for x in arms)
        print(f"\n중앙값 차이 {arms[0]} − {arms[1]} = {statistics.median(a) - statistics.median(b):+.0f}s  순열검정 p = {perm_test(a, b):.2f}")


if __name__ == "__main__":
    main()
