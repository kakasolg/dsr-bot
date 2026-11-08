"""dsr_telemetry.sitting_state (True / False / None) and sitting() unchanged — fake memory, no game.  python tests/sitting_state_test.py
feed.Feed forwards it to the telemetry underneath (__getattr__); the feed thread is never started."""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import dsr_telemetry as T
import feed

SEATED, SITTING_DOWN = 7711, 7720


class PM:
    """read_int / read_uchar at OFF_ANIM2 / +4; None = that read raises."""

    def __init__(self, anim, flag):
        self.anim, self.flag = anim, flag

    def _err(self):
        raise T.pymem.exception.PymemError("fake read failure")

    def read_int(self, a):
        return self._err() if self.anim is None else self.anim

    def read_uchar(self, a):
        return self._err() if self.flag is None else self.flag


def tm(ptr=0x1000, anim=SEATED, flag=1):
    t = object.__new__(T.DSRTelemetry)                     # no __init__: it would attach to the game
    t.pm = PM(anim, flag)
    t.player_ptr = lambda: ptr
    return t


def check(t, state, old):
    assert t.sitting_state() is state, (t.sitting_state(), state)
    assert t.sitting() is old, (t.sitting(), old)


def test_seated():
    check(tm(), True, True)


def test_not_seated():
    check(tm(anim=SITTING_DOWN, flag=0), False, False)
    check(tm(anim=SEATED, flag=0), False, False)
    check(tm(anim=1000, flag=1), False, False)


def test_unknown_is_none_but_sitting_stays_false():
    check(tm(ptr=None), None, False)
    check(tm(ptr=0), None, False)
    check(tm(anim=None), None, False)
    check(tm(flag=None), None, False)


def test_feed_forwards_sitting_state():
    assert "sitting_state" not in vars(feed.Feed)          # no own copy that could drift — goes through __getattr__
    for state in (True, False, None):
        under = type("U", (), {"sitting_state": lambda self, s=state: s})()
        assert feed.Feed(under).sitting_state() is state
    f = feed.Feed(tm(ptr=None))
    assert f.sitting_state() is None and f.sitting() is False


if T.pymem is None:                                         # PymemError is needed for the read-failure fakes
    del test_unknown_is_none_but_sitting_stays_false


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
