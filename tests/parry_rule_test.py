"""souls/parry.py — which attacks the fight's parry rule takes (MoKa 11-15 M1115-13). Game files only (tae_turn.json ·
throw_params.json); no game."""
from __future__ import annotations

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

from types import SimpleNamespace as NS

from souls import parry as P

W = P.load_windows()
assert W[("c2540", 3000)] == [(0.8667, 1.0333)] and W[("c2550", 13004)] == [(2.0333, 2.1667)]
assert {"c2540", "c2550", "c2560"} <= P.ripostable() and "c2570" not in P.ripostable()
assert P.candidate(254010, 3000) == [(0.8667, 1.0333)]               # Burg hollow sword
assert P.candidate(255041, 3004) == [(2.0333, 2.1667)]               # a01 section
assert P.candidate(256002, 3000) == [(0.7333, 1.0)]                  # a02 section
assert P.candidate(255001, 3009) is None                             # NO_PARRY
assert P.candidate(255002, 3000) is None and P.candidate(256001, 3000) is None   # crossbow / bow
assert P.candidate(257002, 3000) is None                             # c2570: no riposte row
assert P.candidate(254010, 3500) is None and P.candidate(254010, -1) is None
print("ok  candidate: sword foes' melee attacks from the game files; 3009 · ranged · c2570 · non-attacks left out")


def ch(ptr, x, z, anim, hp=50, y=0.0):
    return NS(ptr=ptr, x=x, y=y, z=z, anim=anim, hp=hp)


class S:
    def __init__(self, chars):
        self.player = NS(x=0.0, y=0.0, z=0.0)
        self.chars = chars

    def hostile(self, r):
        return [c for c in self.chars if (c.x ** 2 + c.z ** 2) ** 0.5 <= r]


s = S([ch(1, 1.0, 0, 3000), ch(2, 3.0, 0, -1), ch(3, 4.0, 0, 3001), ch(4, 8.0, 0, 3000), ch(5, 2.0, 0, 3000, y=5.0)])
assert [c.ptr for c in P.awake_others(s, 1)] == [3]                  # asleep (−1), far (8 m), other floor (dy 5) not counted
print("ok  awake_others: only awake foes within 5 m on our floor count against 1:1")

# 11-15 경사로 1회차 고침: 같은 공격 연속 실패 → 포기, 각도
import types as _t
P._TALLY.clear()
assert not P.given_up(255010, 3005)
P.tally(255010, 3005, "fail"); P.tally(255010, 3005, "fail")
assert P.given_up(255010, 3005)
P.tally(254000, 3003, "ok"); P.tally(254000, 3003, "fail"); P.tally(254000, 3003, "fail")
assert not P.given_up(254000, 3003)          # a success keeps it
P._TALLY.clear()
me = _t.SimpleNamespace(x=0.0, z=0.0, heading=0.0)      # world yaw = heading + π → facing −z
assert abs(P.off_deg(me, _t.SimpleNamespace(x=0.0, z=-2.0))) < 1
assert abs(abs(P.off_deg(me, _t.SimpleNamespace(x=2.0, z=0.0))) - 90) < 1
assert P.MAX_PARRY_M <= 2.0 and P.MAX_DY < 1.2
print("ok  given_up after 2 fails without a success; off_deg; gates 2.0 m / dy 0.8")
