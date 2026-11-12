"""run.py merchant → Missions.merchant_trip: below the ramp with live ramp foes → pass_ramp first, then to_merchant (P-172, M1112-07).
074631: started beside the Firelink bonfire ('A0 58.0 m'), walked up past the ramp foes, 3 chased, HP 12%. Fake snapshots only."""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))

from types import SimpleNamespace

from souls import missions as MS

top, route, R = MS._route()


def where(p):
    return MS.nearest_route_point(p, route, R)


# real positions from runs
FIRELINK = (-46.5, -59.3, 58.4)          # beside the bonfire (cell_to_bonfire arrival, 11-12)
MERCHANT = (-39.17, -19.8, -67.81)       # merchant stand spot
seg, k, d = where(FIRELINK)
assert MS.below_ramp(seg, k, d), (seg, k, d)
assert not MS.below_ramp(*where(MERCHANT)), where(MERCHANT)
assert not MS.below_ramp(*where(route[5])), where(route[5])     # inside the passage
assert not MS.below_ramp(*where(top)), where(top)               # at the stair top (ramp passed)
print(f"ok  below_ramp: Firelink bonfire ({seg}{k} {d:.0f} m) yes · stair top / passage / merchant no")


def fake(pos, alive, ramp=(True, "cleared")):
    m = object.__new__(MS.Missions)
    m.lines, m.calls = [], []
    m.log = m.lines.append
    m.f = SimpleNamespace(snap_settled=lambda t: SimpleNamespace(player=SimpleNamespace(x=pos[0], y=pos[1], z=pos[2])))
    m.ramp_survivors = lambda: alive
    m.pass_ramp = lambda lure=None: m.calls.append("pass_ramp") or ramp
    m.to_merchant = lambda *a, **k: m.calls.append("to_merchant") or "도착"
    return m


FOE = [SimpleNamespace(npc_param=254000)]
m = fake(FIRELINK, FOE)
assert m.merchant_trip() == "도착" and m.calls == ["pass_ramp", "to_merchant"], (m.calls, m.lines)
m = fake(FIRELINK, None)                                         # world unreadable → clear anyway
assert m.calls == [] and m.merchant_trip() == "도착" and m.calls == ["pass_ramp", "to_merchant"]
m = fake(FIRELINK, [])                                           # ramp already cleared
assert m.merchant_trip() == "도착" and m.calls == ["to_merchant"], m.calls
m = fake(FIRELINK, FOE, ramp=(False, "died"))
assert m.merchant_trip() == "경사로 died" and m.calls == ["pass_ramp"], m.calls
m = fake(MERCHANT, FOE)                                          # past the ramp: never walks back to clear it
assert m.merchant_trip() == "도착" and m.calls == ["to_merchant"], m.calls
print("ok  merchant_trip: Firelink + ramp foes → pass_ramp then to_merchant · cleared/past the ramp → to_merchant · ramp fail stops")
