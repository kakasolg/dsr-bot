"""souls.turn_watch — one record per hit window, angle off the foe's facing, hit or not (M1116-03). Pure; fake tm and snapshots."""
from __future__ import annotations

import math
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
from types import SimpleNamespace as NS

from souls import parry as P
from souls import turn_watch as TW

P._WIN = {("c2540", 3000): [(0.8667, 1.0333)]}               # keep the test off the game-file table
out = []
tw = TW.TurnWatch(lambda k, **f: out.append((k, f)))


class TM:
    at = 0.5

    def anim_time(self, _ptr):
        return self.at


tm = TM()
# foe at the origin facing +z (world yaw = heading + π → heading −π); we stand 1 m to its right side (+x) → 90° off
foe = NS(ptr=1, npc_param=254010, anim=3000, x=0.0, z=0.0, heading=-math.pi)
me = NS(x=1.0, z=0.0, hp=600)
tw.tick(tm, NS(player=me), foe, now=0.0)                      # before the window → nothing
assert not tw.pending
tm.at = 0.9
tw.tick(tm, NS(player=me), foe, now=1.0)                      # window opened → one pending row
tw.tick(tm, NS(player=me), foe, now=1.05)                     # same window again → not twice
assert len(tw.pending) == 1 and tw.pending[0][1]["off"] == 90 and tw.pending[0][1]["d"] == 1.0
tw.tick(tm, NS(player=NS(x=1.0, z=0.0, hp=480)), None, now=1.5)  # 0.5 s later, HP 600 → 480
assert out == [("turn_dodge", {**out[0][1]})] and out[0][1]["lost"] == 120 and out[0][1]["anim"] == 3000
# straight in front → 0°; no HP lost → lost 0 via close()
tw2 = TW.TurnWatch(lambda k, **f: out.append((k, f)))
tw2.tick(tm, NS(player=NS(x=0.0, z=1.0, hp=600)), foe, now=0.0)
tw2.close(600)
assert out[-1][1]["off"] == 0 and out[-1][1]["lost"] == 0
P._WIN = None
print("ok  turn_watch: once per hit window, off-facing angle and distance at its start, HP lost within HIT_S")
