"""Field.smash_ok False (souls/altar_andre): a blocking prop ends the walk with Field.denial — fakes only, no game, no pad device.
Both ways into _smash_blocking: _walk_missed (a point not reached) and nav.goto's on_stuck (real goto, short STUCK_WINDOW).
python tests/field_smash_deny_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

from contextlib import contextmanager
from types import SimpleNamespace as NS

import nav
from souls import field as F

DENIED = ("denied",)                                       # marker put into pad.calls when the denial event is emitted
RELEASE = {("neutral", ()), ("move", (0.0, 0.0)), ("sprint", (False,)), ("guard", (False,)), ("release_due", ())}
PROP = {"name": "o1129", "model": "crate", "pos": (0.0, 0.0, 0.5)}


class Pad:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):                           # every pad call is recorded, none goes anywhere
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **k: self.calls.append((name, tuple(a)))


class TM:
    def snapshot(self, within=30.0):                       # standing still at the origin: goto sees no progress → stuck
        p = NS(x=0.0, y=0.0, z=0.0, gx=0.0, gy=0.0, gz=0.0, hp=100, max_hp=100, heading=0.0, anim=-1)
        return NS(player=p, cam_yaw=0.0, hostile=lambda r: [], chars=[], t=0.0, fseq=0)


class NM:
    map_id = "m10_01_00_00"

    def floor_at(self, x, z, y):
        return None

    def find_path(self, a, b):
        return [tuple(a), tuple(b)]


def field(smash_ok=False):
    pad, tm = Pad(), TM()
    f = object.__new__(F.Field)                            # no __init__: no Reflex / Loot / style
    events = []

    def ev(name, **k):
        events.append((name, k))
        if name == "denied":
            pad.calls.append(DENIED)
    f.mv = NS(pad=pad, tm=tm, snap=lambda r=5.0: tm.snapshot(r), show_path=None, show_smash=None,
              stick_to=lambda s, x, z, k: (0.0, 0.5), face=lambda s, spot, deg=15.0: True)
    f.esc = NS(escaping=False, gen=0)
    f.reflex = NS(nm=None, threat_now=lambda s: False, hold=lambda: None)
    f.log, f.events, f.walk_heal, f._detour = (lambda *a: None), ev, False, False
    f.smash_ok, f.denial = smash_ok, None
    f.safe, f.estus_left = (lambda s: True), (lambda: 0)
    f.gameplay = []
    for name in ("fight", "recover", "heal", "retreat", "fall_back", "open_door", "fog_through"):
        setattr(f, name, (lambda n: lambda *a, **k: f.gameplay.append(n) or False)(name))
    return f, pad, events


@contextmanager
def patched(blocking=lambda f: [PROP], fog=None, stuck_window=None):
    """props_.blocking / fog_ahead / door_near / npc_near → fakes (and nav.STUCK_WINDOW short) for one test."""
    saved = (F.props_, F.fog_ahead, F.door_near, F.npc_near, nav.STUCK_WINDOW)
    try:
        F.props_ = NS(blocking=lambda map_id, me, goal: blocking(None))
        F.fog_ahead = fog or (lambda p, q: None)
        F.door_near = lambda p: None
        F.npc_near = lambda s, me, pos: None
        if stuck_window is not None:
            nav.STUCK_WINDOW = stuck_window
        yield
    finally:
        F.props_, F.fog_ahead, F.door_near, F.npc_near, nav.STUCK_WINDOW = saved


def after_denial(pad):
    assert pad.calls.count(DENIED) == 1, pad.calls
    return pad.calls[pad.calls.index(DENIED) + 1:]


def assert_no_gameplay_after_denial(f, pad):
    rest = after_denial(pad)
    assert all(c in RELEASE for c in rest), rest           # only input release after the refusal
    assert not any(c[0] == "attack" for c in pad.calls), pad.calls
    assert f.gameplay == [], f.gameplay                    # no fight / recover / heal / retreat / door / fog


def test_denied_through_walk_missed():
    f, pad, events = field()
    f._follow = lambda *a, **k: "timeout"                  # goto gave up on the point without calling on_stuck
    f.walk_to = lambda *a, **k: f.gameplay.append("detour") or "arrived"
    with patched():
        r = f.walk([(5.0, 0.0, 0.0)], NM(), "t")
    assert r == "denied" and f.denial["op"] == "smash" and f.denial["detail"]["prop"] == "o1129"
    assert "점 못 감" in f.denial["detail"]["why"]
    assert_no_gameplay_after_denial(f, pad)


def test_denied_through_goto_on_stuck():
    f, pad, events = field()
    f.walk_to = lambda *a, **k: f.gameplay.append("detour") or "arrived"
    with patched(stuck_window=0.1):                        # real nav.goto: stationary player → on_stuck → _smash_blocking
        r = f.walk([(5.0, 0.0, 0.0)], NM(), "t")
    assert r == "denied" and f.denial["op"] == "smash"
    assert "막힘 감지" in f.denial["detail"]["why"]          # came in through on_stuck, not _walk_missed
    assert_no_gameplay_after_denial(f, pad)
    assert not any(n == "walk_fail" for n, _ in events)    # goto ended on mode_fn 'retreat', _walk_missed never ran


def test_denial_kept_across_detour_walk():
    f, pad, events = field()
    f._follow = lambda *a, **k: "timeout"
    with patched(blocking=lambda _: [PROP] if f._detour else []):   # the prop shows up only inside the detour's walk
        r = f.walk([(5.0, 0.0, 0.0)], NM(), "t")
    assert r == "denied" and f.denial["op"] == "smash" and not f._detour
    assert_no_gameplay_after_denial(f, pad)


def test_denial_kept_across_fog_front_walk():
    f, pad, events = field()
    f._follow = lambda *a, **k: "timeout"
    f.fog_gone = lambda fog: False
    seen = []

    def fog(p, q):                                         # the outer walk meets a known fog wall once
        seen.append(q)
        return (10.0, 0.0, 0.0) if len(seen) == 1 else None
    with patched(fog=fog):
        r = f.walk([(20.0, 0.0, 0.0)], NM(), "t")
    assert r == "denied" and f.denial["op"] == "smash"
    assert "fog_through" not in f.gameplay                 # _fog_cross gave up after the nested walk's refusal
    assert_no_gameplay_after_denial(f, pad)


def test_denial_is_not_cleared_by_a_later_walk():
    f, pad, events = field()
    f._follow = lambda *a, **k: "timeout"
    with patched():
        f.walk([(5.0, 0.0, 0.0)], NM(), "t")
        first = f.denial
        n = len(pad.calls)
        assert f.walk([(6.0, 0.0, 0.0)], NM(), "t2") == "denied"
    assert f.denial is first and all(c in RELEASE for c in pad.calls[n:]), pad.calls[n:]


def test_unrestricted_caller_still_smashes():
    f, pad, events = field(smash_ok=True)
    results = iter(["timeout", "arrived"])
    f._follow = lambda *a, **k: next(results)
    with patched():
        r = f.walk([(5.0, 0.0, 0.0)], NM(), "t")
    assert r == "arrived" and f.denial is None and DENIED not in pad.calls
    assert sum(1 for c in pad.calls if c[0] == "attack") == 2 and any(n == "smash" for n, _ in events)


def test_unrestricted_caller_without_prop_unchanged():
    f, pad, events = field(smash_ok=True)
    f._follow = lambda *a, **k: "timeout"
    f.walk_to = lambda *a, **k: "arrived"                  # the detour still runs as before
    with patched(blocking=lambda _: []):
        r = f.walk([(5.0, 0.0, 0.0)], NM(), "t")
    assert r == "arrived" and f.denial is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
