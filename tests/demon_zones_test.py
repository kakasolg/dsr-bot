"""demon_zones — cell geometry and the per-window recorder (M1116-08). Pure; fake snapshots."""
from __future__ import annotations

import math
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
from types import SimpleNamespace as NS

import demon_zones as DZ

# demon at the origin facing +z (heading −π → world yaw 0)
c = NS(ptr=7, npc_param=DZ.DEMON, x=0.0, z=0.0, heading=-math.pi, anim=-1)
assert abs(DZ.signed_off(c, NS(x=0.0, z=3.0))) < 1e-6                 # straight in front
assert abs(abs(DZ.signed_off(c, NS(x=0.0, z=-3.0))) - 180) < 1e-6    # behind
right = DZ.signed_off(c, NS(x=3.0, z=0.0))                            # + side = moves.rel_angle + = "its right" (duel)
assert abs(right - 90) < 1e-6, right
x, z = DZ.cell_point(c, 3.0, 90)
assert abs(x - 3.0) < 1e-6 and abs(z) < 1e-6 and DZ.in_cell(c, NS(x=x, z=z), 3.0, 90)
assert not DZ.in_cell(c, NS(x=0.0, z=3.0), 3.0, 90)

out = []
rec = DZ.ZoneRec(lambda k, **f: out.append((k, f)), lambda npc, anim: [(1.0, 1.5)] if anim == 3004 else None)
rec.cell = "붙음-정면"
me = NS(x=0.0, z=3.0, hp=600, sp=100, anim=-1)
c.anim = 3004
rec.tick(0.0, me, c, 0.2)                                             # attack starts → "attack" row, no window yet
assert out[-1][0] == "attack" and out[-1][1]["anim"] == 3004
rec.tick(0.85, me, c, 1.05)                                           # window 0 opens
rec.tick(0.9, me, c, 1.1)                                             # same play → not twice
assert len(rec.open) == 1
rec.tick(1.2, NS(x=0.0, z=3.0, hp=450, sp=100, anim=9000), c, 1.35)  # hit
rec.tick(1.4, NS(x=0.0, z=3.0, hp=450, sp=100, anim=9000), c, 1.55)
rec.tick(1.9, NS(x=0.0, z=3.0, hp=450, sp=100, anim=-1), c, 2.05)    # past w1 + HIT_S → row out
row = [f for k, f in out if k == "win"][0]
assert row["lost"] == 150 and row["off"] == 0 and row["d"] == 3.0 and row["d_body"] == 0.5 and 9000 in row["my_anims"]
assert row["cell"] == "붙음-정면" and row["hurt_2s"] == 0 and rec.rows == 1
print("ok  demon_zones: signed angle (+ = its right), cell point, one row per window with HP lost to w1 + HIT_S")
