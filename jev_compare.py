"""
판단 모델 백엔드 비교 — 같은 조건의 그림자 런들을 백엔드(local / typesafe)별로 나란히 놓는다.

  python jev_compare.py

읽는 것: results.jsonl(에피소드·백엔드) → 에피소드 파일의 "jev" 행(판단)과 "damage"/"end" 이벤트(결과).
보는 것:
  · 생존: n, 중앙값, 최대, 사망 수
  · 판단 분포: 이동 모드 비율, 규칙과 일치율, 신뢰도 게이트 통과율
  · 신호가 결과를 가르는가: 응답 뒤 5 s 안에 피격이 있었던 경우 vs 없었던 경우의 평균 threat / retreat
      (둘이 비슷하면 "적이 있으면 켜지는 램프"일 뿐, 차이가 크면 실제 위험을 구분하는 것)
  · 조기 경보: 사망 전 10 s 안에 retreat≥0.5 또는 threat≥2 가 있었는가 / 경보 중 피격으로 이어지지 않은 비율(오경보)
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
HORIZON = 5.0     # 응답 뒤 이 시간 안의 피격을 "맞았다" 로 본다
WARN_T, WARN_R = 2.0, 0.5


def mean(xs):
    return statistics.mean(xs) if xs else float("nan")


def main() -> None:
    groups: dict[str, dict] = {}
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("jev", "off") == "off" or r["seconds"] <= 0:
            continue
        key = r.get("jev_backend") or "?"
        g = groups.setdefault(key, {"secs": [], "deaths": 0, "resp": [], "warn_death": 0, "alarms": 0, "alarms_hit": 0})
        g["secs"].append(r["seconds"])
        g["deaths"] += r["reason"] == "death"
        p = EPISODES / f"{r['episode']}.jsonl"
        if not p.exists():
            continue
        rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        dmg_t = [x["t"] for x in rows if x.get("event") == "damage"]
        end = next((x for x in rows if x.get("event") == "end"), None)
        t_death = end["t"] if end and end.get("reason") == "death" else None
        warned = False
        for x in rows:
            j = x.get("jev")
            if not j:
                continue
            hit = any(x["t"] < t <= x["t"] + HORIZON for t in dmg_t)
            alarm = (j.get("retreat") or 0) >= WARN_R or (j.get("threat") or 0) >= WARN_T
            g["resp"].append({**j, "hit": hit, "alarm": alarm})
            if alarm:
                g["alarms"] += 1
                g["alarms_hit"] += hit
            if t_death and alarm and t_death - 10 <= x["t"] <= t_death:
                warned = True
        if t_death:
            g["warn_death"] += warned

    for key, g in groups.items():
        rs = g["resp"]
        print(f"═══ {key}  (에피소드 {len(g['secs'])}, 판단 {len(rs)}건) ═══")
        print(f"  생존: median {statistics.median(g['secs']):.0f}s  max {max(g['secs']):.0f}s  사망 {g['deaths']}")
        if not rs:
            continue
        modes = {m: sum(1 for r in rs if r["mode"] == m) for m in ("sprint", "guardjump", "walk")}
        print(f"  이동모드: {modes}  규칙과 일치 {mean([r['mode'] == r['rule_mode'] for r in rs]):.0%}  "
              f"게이트 통과(conf≥0.6) {mean([(r.get('mode_conf') or 0) >= 0.6 for r in rs]):.0%}")
        hit, miss = [r for r in rs if r["hit"]], [r for r in rs if not r["hit"]]
        print(f"  5 s 안 피격 O ({len(hit)}건): threat {mean([r['threat'] or 0 for r in hit]):.2f}  retreat {mean([r['retreat'] or 0 for r in hit]):.2f}")
        print(f"  5 s 안 피격 X ({len(miss)}건): threat {mean([r['threat'] or 0 for r in miss]):.2f}  retreat {mean([r['retreat'] or 0 for r in miss]):.2f}")
        if g["deaths"]:
            print(f"  조기 경보: 사망 {g['deaths']}건 중 {g['warn_death']}건 경보 있음")
        if g["alarms"]:
            print(f"  오경보: 경보 {g['alarms']}건 중 {g['alarms'] - g['alarms_hit']}건은 5 s 안 피격 없음 ({(g['alarms'] - g['alarms_hit']) / g['alarms']:.0%})")


if __name__ == "__main__":
    main()
