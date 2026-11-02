"""taurus.ladder_way — the way back to the ladder foot follows the NavMesh, not a straight line. No game.

230917 and 20261101_000849: after the 3012 roll the bot stood on the fog-wall ramp (49.5–50.6, 16.8–17.2, −118.3…−118.6); a
straight stick at the ladder foot (49.16, 15.97, −117.1) was blocked for 8 s while it was hit. On the real Burg NavMesh the
ramp only joins the floor by going down it and round to the west.
"""
import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("BOT_GAME", "dsr")

import navmesh  # noqa: E402
from souls import taurus as T  # noqa: E402

NM = navmesh.Navmesh.from_npz(Path(__file__).resolve().parent.parent / "data" / "samples" / "navmesh_m10_01_00_00.npz")
FOOT = T.LADDER["bottom"]


def way(p):
    return T.ladder_way(NM, NS(x=p[0], y=p[1], z=p[2]), FOOT)


def test_ramp_goes_down_the_ramp_not_at_the_foot():
    w = way((49.76, 16.94, -118.3))                   # 20261101_000849 72.05 s, where the roll stopped
    assert w != FOOT and w[1] < 16.6 and w[2] < -118.6, w   # down the ramp, away from the blocked straight line


def test_normal_landing_ledge_heads_straight_for_the_foot():
    w = way((47.84, 16.97, -117.91))                  # the ledge every plunge lands on (235622 70.01 s)
    assert math.hypot(w[0] - FOOT[0], w[2] - FOOT[2]) < 0.6, w


def test_near_the_foot_or_no_mesh_is_the_foot():
    assert way((48.68, 15.95, -117.2)) == FOOT
    assert T.ladder_way(None, NS(x=40.0, y=15.8, z=-120.0), FOOT) == FOOT


if __name__ == "__main__":
    test_ramp_goes_down_the_ramp_not_at_the_foot()
    test_normal_landing_ledge_heads_straight_for_the_foot()
    test_near_the_foot_or_no_mesh_is_the_foot()
    print("ok")
