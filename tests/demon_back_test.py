"""demon_back — gaps from tae_turn, the hit decision and gap rows (M1116-10). Pure; fake snapshots."""
from __future__ import annotations

import math
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
from types import SimpleNamespace as NS

import demon_back as DB

G = DB.load_gaps()
for a, (o, e) in {3004: (1.3, 2.7667), 3005: (1.8, 3.2), 3006: (1.8667, 3.7333), 3003: (1.7333, 3.0),
                  3008: (4.1, 6.9), 3012: (2.1, 3.9667)}.items():
    assert abs(G[a][0] - o) < 1e-3 and abs(G[a][1] - e) < 1e-3, (a, G[a])

DB.DZ_WIN.update({3004: [[1.0667, 1.3]], 3002: [[1.1667, 1.4333]], 3011: [[1.0333, 1.2333]]})
out = []
plan = DB.BackPlan(lambda k, **f: out.append((k, f)), G)
# demon at the origin facing +z (heading −π); we are right behind it at 3 m
c = NS(ptr=1, x=0.0, z=0.0, heading=-math.pi, anim=3004, hp=813, max_hp=813)
me = NS(x=0.0, z=-3.0, hp=600, sp=100, anim=-1)
assert DB.band(DB.DZ.signed_off(c, me)) == "back"
plan.feed(10.0, me, c, 0.0)                        # 3004 starts at t 10
assert plan.decide(10.5, me, c, False) == ("no", 0)          # gap not open yet
plan.feed(11.35, me, c, 1.35)                      # past 1.30 → open, 1.42 s left
assert plan.decide(11.35, me, c, False) == ("hit", 1)
plan.struck(11.35, 40)
front = NS(x=0.0, z=3.0, hp=600, sp=100, anim=-1)
assert plan.decide(11.4, front, c, False) == ("no", 0) and plan.gap["skip"] == "front"
plan.feed(12.8, me, c, 2.8)                        # past 2.77 → closed, waits for "lost after"
assert plan.gap is None and len(plan.pend) == 1
c.anim = -1
plan.feed(19.0, NS(x=0.0, z=-3.0, hp=500, sp=100, anim=-1), c, None)   # no next attack → GAP_TAIL_S ends it
g = [f for k, f in out if k == "gap"][0]
assert g["used"] and g["dmg"] == 40 and g["lost_after"] == 100 and g["off_open"] in (180, -180) and g["d_open"] == 3.0

# chain head 3002 followed by 3011 before CHAIN_WAIT → its gap is cut, not used
out.clear()
plan2 = DB.BackPlan(lambda k, **f: out.append((k, f)), G)
c2 = NS(ptr=1, x=0.0, z=0.0, heading=-math.pi, anim=3002, hp=813, max_hp=813)
plan2.feed(0.0, me, c2, 0.0)
assert plan2.gap["t_open"] == G[3002][0] + DB.CHAIN_WAIT
c2.anim = 3011
plan2.feed(1.6, me, c2, 0.0)
plan2.close()
gaps = [f for k, f in out if k == "gap"]
assert gaps[0]["anim"] == 3002 and not gaps[0]["used"] and gaps[0]["why"] == "chain_cut", gaps[0]

# 3008: running while before its last hit end; one "slam" row with the start distance
out.clear()
plan3 = DB.BackPlan(lambda k, **f: out.append((k, f)), G)
c3 = NS(ptr=1, x=0.0, z=0.0, heading=-math.pi, anim=3008, hp=813, max_hp=813)
plan3.feed(0.0, NS(x=0.0, z=-2.0, hp=600, sp=100, anim=-1), c3, 0.0)
assert plan3.slam_running(1.0) and not plan3.slam_running(4.3)
plan3.close()
sl = [f for k, f in out if k == "slam"][0]
assert sl["d_start"] == 2.0 and sl["hit"] is False

zt = DB.ZoneTime()
zt.tick(0.0, c, me); zt.tick(1.0, c, me); zt.tick(2.0, c, front); zt.tick(2.5, c, front)
sm = zt.summary(2.5)
assert sm["secs"]["back"] == 1.0 and sm["secs"]["front"] == 1.5 and sm["stay_list"] == [2.0]
DB.DZ_WIN.clear()
print("ok  demon_back: gaps from tae flag 7, hit only behind/side in a gap, chain head waits, slam row, zone time")
