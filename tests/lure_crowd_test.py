"""missions.crowd_near — a lure target with another live foe close on its level is knife-lured, not run at (P-78, 10-12 zone 4).
python tests/lure_crowd_test.py"""
import sys
from pathlib import Path
from types import SimpleNamespace as N

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from souls.missions import crowd_near


def foe(ptr, x, y=0.0, z=0.0, hp=75, npc=254010):
    return N(ptr=ptr, x=x, y=y, z=z, hp=hp, npc_param=npc)


def snap(*cs):
    return N(hostile=lambda r: list(cs))


def test_zone4_cluster():
    t = foe(1, 0.0)
    s = snap(t, foe(2, 2.3, npc=254012), foe(3, 1.9, z=1.0, npc=254011))   # 10-12 zone 4: 1.9–3.4 m apart
    assert {o.ptr for o in crowd_near(s, t, 1)} == {2, 3}


def test_alone_dead_or_other_level():
    t = foe(1, 0.0)
    assert crowd_near(snap(t, foe(2, 6.0)), t, 1) == []            # 6 m off
    assert crowd_near(snap(t, foe(2, 1.0, hp=0)), t, 1) == []      # dead
    assert crowd_near(snap(t, foe(2, 1.0, y=4.0)), t, 1) == []     # ledge above
    assert crowd_near(None, t, 1) == []


if __name__ == "__main__":
    test_zone4_cluster()
    test_alone_dead_or_other_level()
    print("ok")
