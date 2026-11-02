"""P-112: the crossbowman's (255002) 3004 lands 2.08–2.11 s after it starts — it must not count as over at 1.6 s.

  python tests/crossbow_windup_test.py
"""
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

from souls import duel as D
from souls import foes


def test_3004_not_over_before_it_lands():
    xb = foes.BY_NPC[255002]
    assert not D.swing_over(xb, 3004, 1.94)        # 11-02 014223: backstep at 1.94 s → −330
    assert not D.swing_over(xb, 3004, 2.2)
    assert D.swing_over(xb, 3004, 2.4)


def test_other_attacks_unchanged():
    xb = foes.BY_NPC[255002]
    assert D.swing_over(xb, 3000, 1.7)             # firing motions still end at SWING_S
    assert not D.swing_over(xb, 3009, 5.0)         # unblockable never ends by age


if __name__ == "__main__":
    test_3004_not_over_before_it_lands()
    test_other_attacks_unchanged()
    print("ok")
