"""moka_ledger.py — every ledger line is listed every run (built or not, with or without a detector), and the detectors
count from log lines the bot writes (lines copied from runs 225520 / 230509 / 231825). No game.  python tests/moka_ledger_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

import moka_ledger as L

LOG = """\
[  211.7]    구역4-1 254011: 옆에 2명 — 나이프 없이 안 달려듦, 안전 자리에서 기다리니 옴
[  211.8]    전투 계획 2놈 — 자리: 여기 — 낭떠러지 0.3 m
[  213.9]       무기가 벽에 튕김 (내 애니 [140, 303000, 303150, -1]) — 이 자리에서 다시 안 휘두름 (P-139)
[  214.7]       벽 튕긴 자리 — 뒤로 백스텝 (넓은 데로 끌어냄)
[  228.6]    구역4-1 254011: 옆에 1명 — 안전 자리에서 8 s 기다려도 안 옴 (8 s 기다려도 안 옴) — 몸으로
[  230.0]    전투 계획 2놈 — 자리: (14.7, -95.9) 1.5 m 옮김
[  231.0]       [ 1.0s] 거리 1.4 높이 +0.0 그놈 애니 3003 HP 75 | 나 HP 582 SP 90 애니 -1 각 -1° | 반사×3
[  232.0]       [ 2.0s] 거리 1.4 높이 +0.0 그놈 애니 3500 HP 16 | 나 HP 582 SP 70 애니 -1 각 -1° | 마무리×1
[  232.3]       목표 바꿈: 254011 (1.4 m, 애니 3006) — 원래 목표 2.3 m
[  234.6]    ▣ 블랙박스 #4: 0.0 s 동안 -100 → HP 482/682, 추정 254010 애니 3003 1.1 m 정면±0°
[  233.7]       방패에 맞음 (140) → light×1 254011 1.3 m 피해 0, 내 피해 100 내 애니 [(0.0, 140)]
[  259.4]       방패에 맞음 (140) → light×1 254010 1.0 m 피해 74, 내 피해 0 내 애니 [(0.0, 140)]
[  267.9]       방패에 맞음 (140) — 반격 안 함: 기력 29
[  286.7]    구역4-1 254011 low_hp: 적이 가깝고 HP 58/682 — 물러남: arrived
[  286.8]       에스트: 근처에 적 — 안 마심
[  287.0]       에스트: {'ok': True, 'hp': [58, 358], 'left': 8, 'why': None}
[  290.0]       light×1 → 피해 59, 내 피해 0, 그놈 애니 []
""".splitlines()


def main() -> None:
    ledger = L.load_ledger()
    ids = [e["id"] for e in ledger]
    assert len(ids) == len(set(ids)), "duplicate ids"
    for e in ledger:
        assert e["status"] in L.STATUS, e
        assert e.get("quote"), e
        assert e["status"] in ("built", "principle") or e.get("why"), f"{e['id']}: not built / held / noted needs a why"
        assert e.get("detector") is None or e["detector"] in L.DETECTORS, e
    rows = {r["id"]: r for r in L.report(LOG, ledger)}
    assert len(rows) == len(ledger)
    print(f"ok  ledger {len(ledger)} lines, ids unique, every not-built line says why, every row reported")

    g = rows["M1108-01"]
    assert (g["came"], g["followed"]) == (3, 2) and "끊김 1" in g["outcome"] and "기력 # ×1" in g["outcome"], g
    w = rows["M1108-06"]
    assert (w["came"], w["followed"]) == (1, 1), w
    c = rows["M1108-08"]
    assert (c["came"], c["followed"]) == (2, 2) and "기다리니 옴 1" in c["outcome"], c
    e = rows["M1108-07"]
    assert (e["came"], e["followed"]) == (2, 1) and "근처에 적 ×1" in e["outcome"], e
    d = rows["M1108-10"]
    assert (d["came"], d["followed"]) == (1, 0) and "100" in d["outcome"], d
    assert rows["M1108-05"]["came"] is None and "감지기 없음" in rows["M1108-05"]["outcome"]
    print("ok  guard counter 3/2 (1 cut, 1 SP) · wall bounce 1/1 · crowd wait 2/2 · low-HP estus 2/1 · "
          "switch off a damaged target 1 (−100 after) · no-detector line still listed")


if __name__ == "__main__":
    main()
