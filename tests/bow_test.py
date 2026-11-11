"""souls/bow.py skeleton (ROADMAP bow): switching checks memory after each press and never presses blind; a shot needs the bow in
hand and lock-on. Fakes only — the memory offsets, ids and fire button are candidates, unmeasured in game."""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))

from types import SimpleNamespace as NS

from souls import bow as BW


def check(what: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        raise SystemExit(1)


import time as _time
BW.time = NS(time=_time.time, sleep=lambda s: None)           # this module only — not the real time.sleep


class Hand:
    """Left-hand slots cycled by D-pad ←; `read` None = memory read fails."""
    def __init__(self, slots, read=True):
        self.slots, self.k, self.read, self.presses = slots, 0, read, []

    def press(self, b, hold):
        self.presses.append(b)
        if b == BW.SWITCH_LEFT:
            self.k = (self.k + 1) % len(self.slots)


def rig(slots, read=True, lock=True, foe_hp=(75, 40)):
    h = Hand(slots, read)
    hps = list(foe_hp)
    foe = NS(ptr=7, x=0.0, y=0.0, z=8.0, hp=hps[0])

    def snap(r=40.0):
        if len(hps) > 1 and BW.FIRE in h.presses:
            foe.hp = hps[1]
        return NS(player=NS(x=0.0, y=0.0, z=0.0), chars=[foe])
    mv = NS(tm=NS(), pad=h, snap=snap, find=lambda s, ptr: next((c for c in s.chars if c.ptr == ptr), None),
            lock_target=lambda ptr: lock)
    b = BW.Bow(mv, log=lambda *a: None, read_left=lambda tm: (h.slots[h.k] if h.read else None))
    return b, h


SHIELD, BOW = 1400000, 1200000
b, h = rig([SHIELD, BOW])
check("shield in hand → one D-pad ← → bow, checked in memory", b.switch(True) == "ok" and h.presses == [BW.SWITCH_LEFT])
check("… and back to the shield", b.switch(False) == "ok" and h.presses == [BW.SWITCH_LEFT] * 2)
b, h = rig([SHIELD, 0])
check(f"no bow in either slot → not_found after {BW.SWITCH_TRIES} presses", b.switch(True) == "not_found"
      and len(h.presses) == BW.SWITCH_TRIES)
b, h = rig([SHIELD, BOW], read=False)
check("left hand unreadable → no press at all", b.switch(True) == "unreadable" and h.presses == [])
b, h = rig([BOW])
r = b.shoot(7)
check(f"bow in hand, locked → fires once, damage read ({r})", r["ok"] and r["hit"] == 35 and h.presses == [BW.FIRE])
b, h = rig([BOW], lock=False)
r = b.shoot(7)
check("no lock-on → no shot", not r["ok"] and h.presses == [] and r["why"] == "락온 안 됨")
b, h = rig([SHIELD])
check("bow not in hand → no shot", not b.shoot(7)["ok"] and h.presses == [])
print("bow_test: 전부 통과")
