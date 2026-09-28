"""Ramp result 'left #N?' (identity lost after a quit-out) no longer ends the mission (ROADMAP P-18, #7).
28y: crowd quit-out at 43 s → all six identities lost → #3 not found at spawn twice → 'left #3?' → stopped at the ramp."""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))

from types import SimpleNamespace

from souls import missions as MS


def fake(ramp: str):
    m = object.__new__(MS.Missions)
    m.lines = []
    m.log = m.lines.append
    m.f = SimpleNamespace(alive=lambda: True)
    m.start_fresh = lambda: True
    m.clear_ramp = lambda: ramp
    m.to_merchant = lambda: "도착"
    m.light_burg_bonfire = lambda: "lit"
    return m


for r, ok in [("cleared", True), ("left #3?", True), ("left #3? #5?", True),
              ("left #3", False), ("left #3~", False), ("left #3? #5", False), ("left #2~ #3?", False),
              ("died", False), ("no_estus", False), ("partial deferred_unreachable #2", False),
              ("partial deferred_unreachable #2 left #3?", False), ("left", False)]:
    assert fake(r).ramp_passed(r) is ok, (r, ok)
print("ok  ramp_passed: only 'cleared' or all-'?' leftovers go on")

m = fake("left #3?")
assert m.burg_bonfire() == "lit", m.lines
assert any("살았는지 모름" in x for x in m.lines), m.lines
assert fake("left #3").burg_bonfire() == "경사로 left #3"
assert fake("left #3~").burg_bonfire() == "경사로 left #3~"
print("ok  burg_bonfire: 'left #3?' goes on to the merchant and bonfire; 'left #3' / '#3~' still stop at the ramp")
