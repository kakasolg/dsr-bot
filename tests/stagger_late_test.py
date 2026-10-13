"""P-80: duel._stagger_late — a stagger counter whose blade would land after the foe's stagger ends is not started.
python tests/stagger_late_test.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from souls import foes, weapons
from souls.duel import _stagger_late

SHIELD = foes.of(255001)
HOLLOW = foes.of(254010)
CLAY, AXE = weapons.CLAYMORE, weapons.BATTLE_AXE


def test_tradefix1_death_is_late():
    # 255001 staggered 0.89 s before the press, Claymore startup 0.68 → lands at 1.57 s, stagger ~1.38 s
    assert _stagger_late(SHIELD, CLAY, 0.89)


def test_right_after_shield_recoil_is_in_time():
    # my shield recoil (20140) ends ~0.3–0.43 s after the bounce — pressing then still lands inside a hollow's 1.5 s stagger
    assert not _stagger_late(HOLLOW, CLAY, 0.35)
    assert not _stagger_late(SHIELD, CLAY, 0.4)
    assert not _stagger_late(HOLLOW, AXE, 0.6)


def test_late_in_a_hollow_stagger():
    assert _stagger_late(HOLLOW, CLAY, 0.8)


def test_unknown_age_or_unmeasured_weapon_keeps_old_behaviour():
    assert not _stagger_late(SHIELD, CLAY, None)
    assert not _stagger_late(SHIELD, weapons.BROADSWORD, 2.0)


if __name__ == "__main__":
    test_tradefix1_death_is_late()
    test_right_after_shield_recoil_is_in_time()
    test_late_in_a_hollow_stagger()
    test_unknown_age_or_unmeasured_weapon_keeps_old_behaviour()
    print("ok")
