"""Field.pick_drops against a fake world: walking, pulses, A presses and the item-get window list are simulated. No game.

  python tests/pick_drops_test.py

The fake follows what loop10 (2026-11-01) showed: A picks a drop only within 1.0 m (the nearest one), a picked drop's record
stays in memory, and a closing A can pick a neighbour instead of closing (r03). Not a game check.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys
import types
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import drops as D
from souls import field as F

SHORTSWORD, AXE, LONGSWORD, ARMOR = 200000, 701000, 201000, 0x10000000 | 521000


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


class Clock:
    def __init__(self):
        self.t = 0.0

    def time(self):
        self.t += 0.01
        return self.t

    def sleep(self, s):
        self.t += s


class World:
    """Player, ground drops (rec, on_ground), window list, foes. pad.move toward the last stick_to target moves the player."""

    def __init__(self, drops, me=(-28.0, -49.3, 27.0), close_picks=False, unreadable=False, frozen=False):
        self.me = list(me)
        self.ground = {r.addr: [r, True] for r in drops}
        self.win: list = []
        self.close_picks = close_picks      # r03: a closing A picks the next drop in reach (once per drop)
        self.unreadable = unreadable
        self.frozen = frozen                # pulses don't move the player (stuck on the corpse)
        self.presses = 0
        self.foes: list = []
        self.aim = None
        self.walks: list = []

    def snap(self, within=40.0):
        p = NS(x=self.me[0], y=self.me[1], z=self.me[2], hp=500, max_hp=500)
        chars = [NS(ptr=0x1C000000 + i, hp=0, npc_param=254000, team=6, dist=9.0, x=0, y=0, z=0) for i in range(3)]
        chars += self.foes
        return NS(player=p, chars=chars, cam_yaw=0.0, hostile=lambda r: [c for c in self.foes if c.dist <= r])

    def in_reach(self):
        live = [(math.hypot(r.pos[0] - self.me[0], r.pos[2] - self.me[2]), r) for r, on in self.ground.values() if on]
        live = [x for x in live if x[0] <= 1.0]
        return min(live, key=lambda x: x[0])[1] if live else None

    def press(self, button, hold=0.1, gap=0.1):
        self.presses += 1
        if self.win:
            r = self.in_reach() if self.close_picks else None
            if r is not None:
                self.ground[r.addr][1] = False
                self.win = [(r.item, r.cnt)] + self.win
                self.close_picks = False
            else:
                self.win = []
            return
        r = self.in_reach()
        if r is not None:
            self.ground[r.addr][1] = False
            self.win = [(r.item, r.cnt)]

    def window(self):
        return None if self.unreadable else list(self.win)

    def scan(self):
        return [r for r, _on in self.ground.values()]      # picked records stay in memory

    def stick_to(self, s, x, z, scale=1.0):
        self.aim = (x, z, scale)
        return (1.0, 0.0)

    def move(self, x, y):
        if (x or y) and self.aim and not self.frozen:
            ax, az, sc = self.aim
            dx, dz = ax - self.me[0], az - self.me[2]
            d = math.hypot(dx, dz)
            step = 0.23 if sc <= 0.4 else 0.4
            if d > 0:
                self.me[0] += dx / d * min(step, d)
                self.me[2] += dz / d * min(step, d)
            self.aim = None


def field_for(w: World):
    pad = NS(move=w.move)
    mv = NS(tm=NS(), pad=pad, snap=w.snap, stick_to=w.stick_to, press=w.press)
    f = types.SimpleNamespace(mv=mv, log=lambda *a: logs.append(" ".join(map(str, a))), alive=lambda: True)

    def walk_to(goal, nm, tag, done=None, **k):
        w.walks.append((tag, tuple(goal)))
        if done is not None and done(w.snap()):
            return "done"
        w.me = [goal[0], goal[1], goal[2]]
        return "arrived"
    f.walk_to = walk_to
    f._foes_by = F.Field._foes_by
    for name in ("pick_drops", "_drop_visit", "_creep_to", "_press_for_window", "_close_window", "_show_drops"):
        setattr(f, name, types.MethodType(getattr(F.Field, name), f))
    return f


NM = NS(on_mesh=lambda x, y, z, dy=1.0: y > -100)
F.time = Clock()
logs: list = []


def run(w: World, recs, base=(), back=(-30.0, -49.25, 29.0)):
    book = D.DropBook()
    book.observe(list(base), 0.0)
    book.observe_chars([NS(ptr=0x1C000000 + i, hp=100) for i in range(3)], 0.5)
    f = field_for(w)
    out = f.pick_drops(NM, book, back=back, scan=w.scan, window=w.window)
    return out, book


def rec(addr, pos, item, owner=0x1C000000):
    return D.Rec(addr, pos, item, 1, owner)


# ── one drop: walk short, pulse in, A, close ──
a = rec(0xA0, (-31.0, -49.3, 30.0), ARMOR)
w = World([a])
out, book = run(w, [a])
check("single drop taken, window closed, back to the arena", out["taken"] == 1 and book.drops[a.ident].state == "taken"
      and w.win == [] and w.walks[-1][0] == "드롭 뒤 제자리로")
check("walked only to DROP_STAND_M short of the drop, then pulsed", math.dist(w.walks[0][1][::2], a.pos[::2]) > 1.5)

# ── a stale record (picked before the baseline) is never visited ──
old = rec(0xA8, (-31.0, -49.3, 30.0), ARMOR, owner=0x1E000000)      # its owner is not among the foes killed now
w = World([old])
w.ground[old.addr][1] = False
out, book = run(w, [old], base=[old])
check("record from before the baseline: no walk, no press", out["visits"] == 0 and w.presses == 0)
w = World([a])
w.ground[a.addr][1] = False
out, book = run(w, [a], base=[a])                                  # same bytes, but its owner died since the baseline
check("same bytes as baseline + owner died: one visit only, then given up", out["visits"] == 1
      and book.drops[a.ident].state == "failed")

# ── r03: three within 1 m; A takes the nearest (not the aimed), closing A takes another ──
s_ = rec(0xB0, (-33.3, -50.4, 30.5), SHORTSWORD, owner=0x1C000000)
x_ = rec(0xC0, (-33.0, -50.4, 30.3), AXE, owner=0x1C000001)
l_ = rec(0xD0, (-33.6, -50.4, 31.0), LONGSWORD, owner=0x1C000002)
w = World([s_, x_, l_], close_picks=True)
out, book = run(w, [s_, x_, l_])
st = {d.rec.item: d.state for d in book.drops.values()}
check("r03: all three taken, none by guesswork", st == {SHORTSWORD: "taken", AXE: "taken", LONGSWORD: "taken"}
      and out["unexpected"] == 0)
check("r03: no visit spent on an already-picked record", out["visits"] <= 3 and w.win == [])

# ── window unreadable → nothing marked, visits capped, no blind closing A ──
w = World([a], unreadable=True)
out, book = run(w, [a])
d = book.drops[a.ident]
check("unreadable window: not taken, given up after MAX_TRIES", d.state == "failed" and out["taken"] == 0
      and out["visits"] == D.MAX_TRIES)
check("unreadable window: the item is on the ground no more but the bot does not claim it", not w.ground[a.addr][1]
      and any("목록 못 읽음" in l or "못 읽음" in l for l in logs))

# ── stuck pulses (body in the way) → approach fails, bounded ──
w = World([a], frozen=True)
out, book = run(w, [a])
check("stuck approach: given up after MAX_TRIES visits, no A pressed", book.drops[a.ident].state == "failed"
      and w.presses == 0 and out["visits"] == D.MAX_TRIES)

# ── a living foe near the drop → stop, no walk ──
w = World([a])
w.foes = [NS(ptr=0x1D000000, hp=80, npc_param=255010, team=6, dist=6.0, x=-31.0, y=-49.3, z=33.0)]
out, book = run(w, [a])
check("foe near: stops before walking, drop stays pending", out["result"] == "foes_near" and not w.walks
      and book.drops[a.ident].state == "pending")

# ── fell out of the map → gone, never walked ──
f_ = rec(0xF0, (-131.7, -2496.8, -39.3), 0x40000000 | 292)
w = World([f_])
out, book = run(w, [f_])
check("fallen record: gone, no walk to it", book.drops[f_.ident].state == "gone" and not [x for x in w.walks if x[0] == "드롭"])

# ── a window left open before we start is closed first ──
w = World([a])
w.win = [(0x40000000 | 330, 6)]
out, book = run(w, [a])
check("open window closed first, then the drop taken", book.drops[a.ident].state == "taken" and w.win == [])

print("pick_drops_test: all ok")
