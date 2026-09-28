"""duel._backstab offline test — lock on, strafe round at body contact, R1 once behind (human demos, ROADMAP 1-f). No game.

  python tests/backstab_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import translate
from field_fakes import World
from souls import duel as D
from souls import moves as M

D.BACKSTAB_TICK = 0.0          # no sleeping; the fake world moves one tick per snap
DT, SPEED = 0.05, 3.0          # human 2.5–3.9 m/s at full stick


class LockWorld(World):
    """Locked on: the player always faces the foe, left stick x = strafe (right +), y = toward it."""
    def __init__(self, **kw):
        super().__init__(**kw)
        self.lock, self.stick, self.r1 = -1, (0.0, 0.0), 0
        self.on_r1 = None

    def face(self, c):
        p = self.player
        p.heading = math.atan2(c.x - p.x, c.z - p.z) - math.pi       # facing = heading + π

    def step(self):
        c = next(iter(self.chars.values()))
        p = self.player
        if self.lock != -1:
            self.face(c)
        phi = p.heading + math.pi
        x, y = self.stick
        p.x += SPEED * DT * (x * math.sin(phi + math.pi / 2) + y * math.sin(phi))
        p.z += SPEED * DT * (x * math.cos(phi + math.pi / 2) + y * math.cos(phi))


class Pad:
    def __init__(self, w):
        self.w, self.calls = w, []

    def move(self, x, y):
        self.w.stick = (x, y)
        self.calls.append(("move", x, y))

    def lock_on(self):
        c = next(iter(self.w.chars.values()))
        self.w.lock = -1 if self.w.lock != -1 else self.w.handles[c.ptr]
        self.calls.append(("lock",))

    def attack(self):
        self.w.r1 += 1
        self.calls.append(("r1",))
        if self.w.on_r1:
            self.w.on_r1()


class Mv:
    def __init__(self, w):
        self.w, self.pad, self.cam_busy = w, Pad(w), False

    def snap(self, within=8.0):
        self.w.step()
        return self.w.snapshot(within)

    @staticmethod
    def find(s, ptr):
        return next((x for x in s.chars if x.ptr == ptr), None) if s else None

    def lock_state(self, ptr):
        return "none" if self.w.lock == -1 else ("target" if self.w.lock == self.w.handles[ptr] else "other")

    def lock_target(self, ptr, tries=3, aim=True):       # the real one also turns the camera; here R3 either grabs it or not
        if self.lock_state(ptr) != "target":
            self.pad.lock_on()
        return self.lock_state(ptr) == "target"

    def unlock(self):
        if self.w.lock != -1:
            self.pad.lock_on()


def setup(side: float):
    """Foe at the origin facing +z; player 1.0 m in front of it, a little to one side (side = +x or −x)."""
    w = LockWorld(player=(0.25 * side, 0.0, 1.0))
    c = w.add(3, 0x1003, 254000, (0.0, 0.0, 0.0), hp=75)
    c.heading = math.pi                                       # facing +z (facing = heading + π)
    w.face(c)
    return w, c, Mv(w)


def test_circles_either_way_and_stabs() -> None:
    for side in (1.0, -1.0):
        w, c, mv = setup(side)
        start = abs(math.degrees(M.rel_angle(c, w.player)))
        w.on_r1 = lambda: setattr(c, "hp", 0)
        r = D._backstab(mv, w.snapshot(), c, lambda: False)
        behind = abs(math.degrees(M.rel_angle(c, w.player)))
        assert r == "stabbed", (side, r)
        assert w.r1 == 1 and behind >= D.BACKSTAB_DEG and M.horiz(w.player, c) <= D.BACKSTAB_MAX_R, (behind, M.horiz(w.player, c))
        assert start < 30, start
        strafes = [q[1] for q in mv.pad.calls if q[0] == "move" and q[1] != 0.0]
        assert strafes and all(abs(x) == 1.0 for x in strafes)          # full stick, like the human
        assert w.lock == -1 and mv.pad.calls[-1][0] in ("move", "lock") and mv.cam_busy is False
        print(f"ok  side {side:+.0f}: {start:.0f}° → {behind:.0f}° in {len(strafes) * DT:.2f} s, R1 once, unlocked")


def test_aborts_when_it_moves() -> None:
    w, c, mv = setup(1.0)
    c.anim = sorted(M.DOWNED)[0]                              # knocked down → stop (a swing no longer stops it: drill kills were mid-swing)
    assert D._backstab(mv, w.snapshot(), c, lambda: False) == "moved"
    assert w.r1 == 0 and w.lock == -1 and w.stick == (0.0, 0.0)
    print("ok  foe knocked down → no R1, stick centered, unlocked")


def test_no_lock() -> None:
    w, c, mv = setup(1.0)
    mv.pad.lock_on = lambda: None                             # lock-on doesn't take
    assert D._backstab(mv, w.snapshot(), c, lambda: False) == "no_lock" and w.r1 == 0
    print("ok  can't lock on → give up")


def test_stick_direction() -> None:
    w, c, mv = setup(1.0)
    x, y, _ = D.backstab_stick(c, w.player)
    assert x == (-1.0 if M.rel_angle(c, w.player) >= 0 else 1.0) and 0 < y <= 0.8   # 1.03 m → close in a bit
    assert translate.line("뒤잡기 → stabbed") == "backstab → stabbed"
    print("ok  stick: strafe + small forward correction; log translates")


if __name__ == "__main__":
    test_circles_either_way_and_stabs()
    test_aborts_when_it_moves()
    test_no_lock()
    test_stick_direction()


def test_room_behind() -> None:
    """A wall/drop behind the foe (no NavMesh floor there) → no backstab (user 2026-09-28)."""
    import types
    class NM:
        def __init__(self, ok): self.ok = ok
        def floor_at(self, x, z, y): return (y, 0) if self.ok(x, z) else None
    p = types.SimpleNamespace(x=0.0, y=0.0, z=-2.0, gx=0.0, gy=0.0, gz=-2.0)
    c = types.SimpleNamespace(x=0.0, y=0.0, z=0.0, heading=0.0)       # faces world yaw π → its back points toward +z
    assert D._room_behind(NM(lambda x, z: True), p, c)
    assert not D._room_behind(NM(lambda x, z: z < 0.5), p, c)          # nothing behind it (z > 0.5) — back against a wall
    assert D._room_behind(None, p, c)                                   # no NavMesh → don't block
    print("ok  wall/drop behind the foe → no backstab")


test_room_behind()


def test_footing() -> None:
    """After a backstab: floor all round us, else step back (27t: fell 25 m off the ramp edge right after one)."""
    import types
    class NM:
        def __init__(self, ok): self.ok = ok
        def floor_at(self, x, z, y): return (y, 0) if self.ok(x, z) else None
    p = types.SimpleNamespace(x=0.0, y=0.0, z=0.0, gx=0.0, gy=0.0, gz=0.0)
    assert D._footing_ok(NM(lambda x, z: True), p)
    assert not D._footing_ok(NM(lambda x, z: x < 0.5), p)                # drop 1 m to one side
    c = types.SimpleNamespace(x=0.0, y=0.0, z=0.0, heading=0.0)          # back toward +z
    assert not D._room_behind(NM(lambda x, z: z < 1.2), p, c)            # floor at 1 m behind, not at 1.5·2 m → no backstab now
    print("ok  footing after a backstab; floor checked 0.5–2 m behind the foe")


test_footing()
