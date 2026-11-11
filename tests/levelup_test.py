"""레벨업 비용 오프라인 테스트 — levelup.py ([MoKa] 10-31 "다음에 필요한 소울 양이 나오잖아").

  python tests/levelup_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import levelup as L


def test_cost_matches_game() -> None:
    # ReqSouls on the level screen, 2026-10-31: SL4 → 724, 5 → 741, 6 → 758, 7 → 775
    assert [L.cost(t) for t in (5, 6, 7, 8)] == [724, 741, 758, 775]
    assert L.cost(12) == 847 and L.cost(13) > L.cost(12)                 # table → formula without a drop
    assert L.affordable(4, 2280) == 3 and L.affordable(4, 2223) == 3 and L.affordable(4, 2222) == 2
    assert L.affordable(7, 57) == 0
    print("ok  cost: SL 4→8 = 724 741 758 775 (game screen) · 2280 souls at SL 4 → 3 levels, 57 left")


if __name__ == "__main__":
    test_cost_matches_game()
    print("전부 통과")
