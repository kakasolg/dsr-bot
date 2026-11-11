"""P-82: field.npc_near — no prop swing with a non-hostile character (the merchant) close by.  python tests/smash_npc_test.py"""
import sys
from pathlib import Path
from types import SimpleNamespace as N

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from souls.field import npc_near

ME = (-37.9, -19.8, -67.9)
CRATE = (-38.6, -19.8, -67.3)                  # o1129 next to the Undead Merchant (10-13 merchant-buy)


def ch(npc, team, x, z, hp=300):
    return N(npc_param=npc, team=team, x=x, y=-19.8, z=z, hp=hp, dist=0.8)


def test_merchant_next_to_crate_blocks_swing():
    s = N(chars=[ch(251001, 6, -38.02, -66.5)])           # merchant reads team 6 (= hostile) in DSR
    assert npc_near(s, ME, CRATE) is not None


def test_hostile_or_far_or_dead_does_not_block():
    assert npc_near(N(chars=[ch(254010, 6, -38.0, -66.5)]), ME, CRATE) is None    # hollow, not a friendly NPC
    assert npc_near(N(chars=[ch(251001, 1, -30.0, -60.0)]), ME, CRATE) is None    # 10 m away
    assert npc_near(N(chars=[ch(251001, 1, -38.0, -66.5, hp=0)]), ME, CRATE) is None
    assert npc_near(None, ME, CRATE) is None


if __name__ == "__main__":
    test_merchant_next_to_crate_blocks_swing()
    test_hostile_or_far_or_dead_does_not_block()
    print("ok")
