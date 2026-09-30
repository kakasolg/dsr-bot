"""Ramp result 'left #N?' (identity lost after a quit-out) no longer ends the mission (ROADMAP P-18, #7).
28y: crowd quit-out at 43 s → all six identities lost → #3 not found at spawn twice → 'left #3?' → stopped at the ramp."""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))

from types import SimpleNamespace

from souls import missions as MS


def fake(ramp, alive=()):
    """ramp: one result, or a list (one per clear_ramp call, the last repeats); alive: live ramp foes seen after each call (same shape)."""
    m = object.__new__(MS.Missions)
    m.lines = []
    m.log = m.lines.append
    m.f = SimpleNamespace(alive=lambda: True)
    m.start_fresh = lambda: True
    rs, al, m.calls = list(ramp) if isinstance(ramp, list) else [ramp], list(alive) if isinstance(alive, list) and alive and isinstance(alive[0], list) else [alive], 0

    def clear(lure=None):
        r = rs[min(m.calls, len(rs) - 1)]
        m.calls += 1
        return r
    m.clear_ramp = clear
    m.ramp_survivors = lambda: al[min(m.calls - 1, len(al) - 1)]
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


# P-25 (#14): a quit-out can revive killed foes, so 'left #N?' is not proof of death — look before going on.
ALIVE = [SimpleNamespace(npc_param=254000)]
assert fake("left #3?", alive=[]).pass_ramp() == (True, "left #3?")
ok, r = fake(["left #3?", "cleared"], alive=[ALIVE, []]).pass_ramp()
assert (ok, r) == (True, "cleared"), (ok, r)
m = fake(["left #3?", "left #3?", "left #3?"], alive=[ALIVE])
ok, r = m.pass_ramp()
assert ok is False and "살아 있는 적 남음" in r and m.calls == 1 + MS.RAMP_RETRIES, (ok, r, m.calls)
assert any("P-25" in x for x in m.lines), m.lines
m = fake("left #3", alive=[ALIVE])                 # '#3' (tried and lived) stops as before — no retry
assert m.pass_ramp() == (False, "left #3") and m.calls == 1
m = fake("cleared", alive=[ALIVE])
assert m.pass_ramp() == (True, "cleared") and m.calls == 1
print("ok  pass_ramp: 'left #N?' + live ramp foes → clear again (max RAMP_RETRIES) then stop; none alive → pass; cleared/'#N' unchanged")

m = fake("left #3?", alive=ALIVE)
assert m.burg_bonfire().startswith("경사로 left #3?"), "still alive after the retries → the mission stops at the ramp"
m = fake("left #3?", alive=[])
assert m.burg_bonfire() == "lit"
print("ok  burg_bonfire: '?' with survivors stops at the ramp, without survivors goes on")

# ramp_survivors itself: same type near a spawn of that type, same level, alive
from field_fakes import World
e0 = MS.RAMP[0]
w = World(player=(0.0, e0["pos"][1], 0.0))
near = w.add(2, 0x1002, e0["npc"], (e0["pos"][0] + 3, e0["pos"][1], e0["pos"][2]), hp=50)
w.add(3, 0x1003, e0["npc"], (e0["pos"][0] + 40, e0["pos"][1], e0["pos"][2]), hp=50)          # far from every spawn of its type
w.add(4, 0x1004, e0["npc"], (e0["pos"][0], e0["pos"][1] + 50, e0["pos"][2]), hp=50)          # other level (no spawn of the type is that high)
w.add(5, 0x1005, e0["npc"], (e0["pos"][0], e0["pos"][1], e0["pos"][2] + 2), hp=0)            # dead
w.add(6, 0x1006, 999999, (e0["pos"][0], e0["pos"][1], e0["pos"][2]), hp=50)                  # not a ramp type
m = object.__new__(MS.Missions)
m.mv = SimpleNamespace(snap=lambda within=200.0: w.snapshot(within))
got = m.ramp_survivors()
assert [c.ptr for c in got] == [2], [c.ptr for c in got]
m.mv = SimpleNamespace(snap=lambda within=200.0: None)
assert m.ramp_survivors() is None
print("ok  ramp_survivors: live + same type near its spawn + same level only; unreadable world → None")
