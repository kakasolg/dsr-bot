"""duel.free_or_blocking — my anim counts as 'free or blocking' for every weapon (Battle Axe 140, Claymore 20140)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from souls.duel import free_or_blocking


def test_free_and_blocking_for_both_weapons():
    for a in (None, -1, 140, 20140):
        assert free_or_blocking(a), a


def test_busy_anims_stay_busy():
    # attacks (axe 303000/303150, Claymore 253000/253001), hit stun, roll, backstep, estus, falling
    for a in (303000, 303150, 253000, 253001, 2002, 2006, 710, 690, 7587, 1500):
        assert not free_or_blocking(a), a


if __name__ == "__main__":
    test_free_and_blocking_for_both_weapons()
    test_busy_anims_stay_busy()
    print("ok")
