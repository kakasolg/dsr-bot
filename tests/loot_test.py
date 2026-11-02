"""souls/loot.Loot and the mission stop points that call it, against a fake world (same model as pick_drops_test: A picks a drop
within 1.0 m, a picked record stays in memory, a closing A may pick a neighbour). No game — not a game check.

  python tests/loot_test.py
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
from souls import loot as L
from souls import missions as MS

SHORTSWORD, AXE, LONGSWORD, ARMOR = 200000, 701000, 201000, 0x10000000 | 521000
OWNERS = [0x1C000000 + i for i in range(3)]


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


def foe(ptr, x, z, y=-49.3, anim=3000, hp=80, team=6):
    return NS(ptr=ptr, hp=hp, npc_param=255010, team=team, dist=0.0, x=x, y=y, z=z, anim=anim)


class World:
    """Player, drop records (rec, on_ground), item-get window, foes, killed owners. Records appear when their owner dies
    (kill()), so a baseline taken before the kill does not hold them."""

    def __init__(self, me=(-28.0, -49.3, 27.0), close_picks=False):
        self.me = list(me)
        self.ground: dict = {}
        self.win: list = []
        self.close_picks = close_picks
        self.presses = 0
        self.foes: list = []
        self.npcs: list = []
        self.owner_hp = {p: 100 for p in OWNERS}
        self.aim = None
        self.walks: list = []
        self.events: list = []          # ('walk'|'press'|'fight'|'scan', …) in order
        self.on_walk = None             # called once at the next walk (a foe turns up mid-approach)
        self.on_pulse = None            # (n, fn): fn() at the n-th stick pulse
        self.pulses = 0
        self.scans = 0
        self.hp = 500

    def kill(self, *recs):
        for r in recs:
            self.owner_hp[r.owner] = 0
            self.ground[r.addr] = [r, True]

    def snap(self, within=40.0):
        p = NS(x=self.me[0], y=self.me[1], z=self.me[2], hp=self.hp, max_hp=500)
        for c in self.foes + self.npcs:
            c.dist = math.dist((c.x, c.y, c.z), self.me)
        chars = [NS(ptr=o, hp=h, npc_param=254000, team=6, dist=80.0, x=0, y=0, z=0, anim=-1) for o, h in self.owner_hp.items()]
        chars += self.foes + self.npcs
        return NS(player=p, chars=chars, cam_yaw=0.0,
                  hostile=lambda r: [c for c in chars if c.team == 6 and c.hp > 0 and c.dist <= r])

    def in_reach(self):
        live = [(math.hypot(r.pos[0] - self.me[0], r.pos[2] - self.me[2]), r) for r, on in self.ground.values() if on]
        live = [x for x in live if x[0] <= 1.0]
        return min(live, key=lambda x: x[0])[1] if live else None

    def press(self, button, hold=0.1, gap=0.1):
        self.presses += 1
        self.events.append(("press",))
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
        return list(self.win)

    def scan(self):
        self.scans += 1
        self.events.append(("scan",))
        return [r for r, _on in self.ground.values()]

    def stick_to(self, s, x, z, scale=1.0):
        self.aim = (x, z, scale)
        return (1.0, 0.0)

    def move(self, x, y):
        if (x or y) and self.aim:
            self.pulses += 1
            if self.on_pulse and self.pulses == self.on_pulse[0]:
                self.on_pulse[1]()
                self.on_pulse = None
            ax, az, sc = self.aim
            dx, dz = ax - self.me[0], az - self.me[2]
            d = math.hypot(dx, dz)
            step = 0.23 if sc <= 0.4 else 0.4
            if d > 0:
                self.me[0] += dx / d * min(step, d)
                self.me[2] += dz / d * min(step, d)
            self.aim = None


def field_for(w: World, fight_result="killed"):
    pad = NS(move=w.move)
    mv = NS(tm=NS(), pad=pad, snap=w.snap, stick_to=w.stick_to, press=w.press)
    f = types.SimpleNamespace(mv=mv, log=lambda *a: logs.append(" ".join(map(str, a))), alive=lambda: w.hp > 0,
                              esc=NS(gen=0), bonfires=[(-60.0, -49.3, 60.0)])

    def walk_to(goal, nm, tag, done=None, **k):
        w.walks.append((tag, tuple(goal)))
        w.events.append(("walk", tag))
        if w.on_walk is not None:
            w.on_walk(), setattr(w, "on_walk", None)
        if done is not None and done(w.snap()):
            return "done"
        w.me = [goal[0], goal[1], goal[2]]
        return "arrived"

    def fight(ptr, nm, tag, **k):
        w.events.append(("fight", ptr))
        res = fight_result(ptr) if callable(fight_result) else fight_result
        if res == "killed":
            for c in w.foes:
                if c.ptr == ptr:
                    c.hp = 0
            w.foes = [c for c in w.foes if c.hp > 0]
        elif res == "me_dead":
            w.hp = 0
        return NS(result=res)
    f.walk_to, f.fight = walk_to, fight
    f._foes_by = F.Field._foes_by
    for name in ("pick_drops", "_drop_visit", "_creep_to", "_press_for_window", "_close_window", "_show_drops", "_chaser"):
        setattr(f, name, types.MethodType(getattr(F.Field, name), f))
    f.loot = L.Loot(f, scan=w.scan, window=w.window)
    f.loot.on = True
    f.loot.reset("test start")                    # baseline before the kills, like run.py
    return f


NM = NS(on_mesh=lambda x, y, z, dy=1.0: y > -100)
F.time = Clock()
logs: list = []


def rec(addr, pos, item, owner=OWNERS[0]):
    return D.Rec(addr, pos, item, 1, owner)


def kinds(w):
    return [e[0] for e in w.events]


A = rec(0xA0, (-31.0, -49.3, 30.0), ARMOR)

# ── 1. foe near the drop and coming at us: fought first, then the drop ──
w = World()
f = field_for(w)
w.kill(A)
w.foes = [foe(0x1D000000, -27.0, 28.5)]                    # 1.8 m from me, swinging
w.events.clear()
out = f.loot.collect(NM, "t1")
ev = kinds(w)
check("1 foe first: fight before any walk or A", "fight" in ev and ev.index("fight") < min(
    (i for i, e in enumerate(ev) if e in ("walk", "press")), default=99))
check("1 after the fight the drop is picked (collect resumes)", out["taken"] == 1 and out["fights"] == 1
      and f.loot.book.drops[A.ident].state == "taken" and out["result"] == "done")

# ── 2. a foe turns up while walking to the drop: stop, fight, then pick ──
w = World()
f = field_for(w)
w.kill(A)
w.on_walk = lambda: w.foes.append(foe(0x1D000001, w.me[0] + 1.0, w.me[2]))
w.events.clear()
out = f.loot.collect(NM, "t2")
ev = kinds(w)
check("2 foe mid-walk: no A before the fight", ev.index("fight") < ev.index("press"))
check("2 picked after the fight", out["taken"] == 1 and out["fights"] == 1)

# ── 2b. a foe turns up while creeping in (stick pulses): stop before A ──
w = World()
f = field_for(w)
w.kill(A)
w.on_pulse = (1, lambda: w.foes.append(foe(0x1D000002, w.me[0] - 1.0, w.me[2])))
w.events.clear()
out = f.loot.collect(NM, "t2b")
ev = kinds(w)
check("2b foe while creeping: fight before the first A, then picked", ev.index("fight") < ev.index("press")
      and out["taken"] == 1)

# ── 3. a sleeping / distant foe near the drop: not woken, drop put off; twice → given up; then no more stops ──
w = World()
f = field_for(w)
w.kill(A)
w.foes = [foe(0x1D000003, -31.0, 36.0, anim=-1)]           # 6 m from the drop, idle — not coming at us
o1 = f.loot.collect(NM, "t3")
o2 = f.loot.collect(NM, "t3")
w.events.clear()
o3 = f.loot.collect(NM, "t3")
d = f.loot.book.drops[A.ident]
check("3 not coming at us: no fight, no walk, no A — held", o1["result"] == "held" and o1["fights"] == 0
      and w.presses == 0 and not w.walks)
check("3 held twice → given up (MAX_HOLDS)", o2["result"] == "held" and d.state == "failed" and "held" in d.why)
check("3 a given-up drop no longer stops the mission", o3["result"] == "done" and o3["held"] == 0
      and "walk" not in kinds(w) and "press" not in kinds(w))

# ── 3b. a held drop is picked up later in the same run once the foe is gone (no new baseline in between) ──
w = World()
f = field_for(w)
w.kill(A)
w.foes = [foe(0x1D000004, -31.0, 36.0, anim=-1)]
o1 = f.loot.collect(NM, "t3b")
w.foes = []
o2 = f.loot.collect(NM, "t3b")
check("3b same run: the drop held once is taken at the next stop", o1["result"] == "held" and o2["taken"] == 1)

# ── 3c. a foe that keeps coming: at most LOOT_FIGHTS fights, then held ──
w = World()
f = field_for(w, fight_result="disengaged")
w.kill(A)
w.foes = [foe(0x1D000005, -27.0, 28.5)]
out = f.loot.collect(NM, "t3c")
check("3c fight not won: held, no A, one fight only", out["result"] == "held" and out["fights"] == 1 and w.presses == 0)

# ── 4. r03 overlap: three within 1 m, a closing A takes a neighbour; lingering records not visited again ──
S_ = rec(0xB0, (-33.3, -50.4, 30.5), SHORTSWORD, owner=OWNERS[0])
X_ = rec(0xC0, (-33.0, -50.4, 30.3), AXE, owner=OWNERS[1])
L_ = rec(0xD0, (-33.6, -50.4, 31.0), LONGSWORD, owner=OWNERS[2])
w = World(close_picks=True)
f = field_for(w)
w.kill(S_, X_, L_)
o1 = f.loot.collect(NM, "t4")
p1 = w.presses
w.events.clear()
o2 = f.loot.collect(NM, "t4")                               # records still in memory after pickup
check("4 overlap: all three taken from the window list", o1["taken"] == 3
      and {d.state for d in f.loot.book.drops.values()} == {"taken"})
check("4 lingering records: the next stop walks to none and presses nothing", o2["visits"] == 0 and w.presses == p1
      and "walk" not in kinds(w))

# ── 5. resets: rest · respawn after a death · quit-out (esc.gen) → records from before are never candidates ──
w = World()
f = field_for(w)
w.kill(A)
f.mv.rest = lambda nm, bf: True
f.forget_foes = lambda: None
F.Field.rest_at(f, NM, {"stand": w.me})
out = f.loot.collect(NM, "t5")
check("5 rest: new baseline, the drop from before the rest is not walked to", out["visits"] == 0 and w.presses == 0
      and any("reset: rest" in x for x in f.loot.book.log))
w = World()
f = field_for(w)
w.kill(A)
w.hp = 0
seq = iter([0, 500, 500])
f.mv.snap = lambda within=40.0, _s=w.snap: (setattr(w, "hp", next(seq, 500)), _s())[1]
f.forget_foes = lambda: None
F.Field.wait_respawn(f, timeout=5.0)
f.mv.snap = w.snap
check("5 respawn after a death resets the book", any("reset: respawn" in x for x in f.loot.book.log)
      and f.loot.collect(NM, "t5")["visits"] == 0)
w = World()
f = field_for(w)
f.forget_foes = lambda: None
n0 = len(f.loot.book.log)
F.Field.wait_respawn(f, timeout=5.0)                        # standing, full HP: no death → no reset
check("5 wait_respawn while alive does not reset", len(f.loot.book.log) == n0)
w = World()
f = field_for(w)
w.kill(A)
f.esc.gen = 1                                               # a quit-out happened
out = f.loot.collect(NM, "t5")
check("5 quit-out since the baseline: result reset, nothing pressed", out["result"] == "reset" and w.presses == 0)

# ── 6. off: nothing scanned, walked or pressed; the mission stop points don't call it ──
w = World()
f = field_for(w)
w.kill(A)
f.loot.on = False
s0 = w.scans
out = f.loot.collect(NM, "t6")
check("6 off: collect does nothing (no scan, walk or A)", out["result"] == "off" and w.scans == s0 and not w.walks
      and w.presses == 0)

# ── 7. no re-entry: collect inside collect returns at once ──
w = World()
inner: list = []
f = field_for(w, fight_result=lambda ptr: (inner.append(f.loot.collect(NM, "inner")), "killed")[1])
w.kill(A)
w.foes = [foe(0x1D000006, -27.0, 28.5)]
out = f.loot.collect(NM, "t7")
check("7 re-entry: inner collect → busy, outer goes on", inner and inner[0]["result"] == "busy" and out["taken"] == 1)

# ── 8. never next to a bonfire (A would sit = every foe revives) or a non-hostile character (A would talk) ──
w = World()
f = field_for(w)
B_ = rec(0xE0, (-58.0, -49.3, 58.0), ARMOR)                 # 2.8 m from the bonfire
w.kill(B_)
out = f.loot.collect(NM, "t8")
check("8 bonfire: no walk, no A", f.loot.book.drops[B_.ident].state == "gone" and w.presses == 0 and not w.walks)
w = World()
f = field_for(w)
w.npcs = [NS(ptr=0x1E000001, hp=300, npc_param=6000, team=1, dist=0.0, x=-31.5, y=-49.3, z=30.5, anim=-1)]
w.kill(A)
out = f.loot.collect(NM, "t8")
check("8 non-hostile character next to the drop: never a candidate", A.ident not in f.loot.book.drops and w.presses == 0)

# ── 9. mission stop points: the stop goes on as before after pickups; off → the call is skipped ──
calls: list = []


class FakeLoot:
    on = True

    def collect(self, nm, tag, back=None):
        calls.append(("loot", tag, back))
        return {"result": "done"}


fake = NS(alive=lambda: True, log=lambda *a: None, loot=FakeLoot())
fake.rest_at = lambda nm, spot: calls.append(("rest",)) or True
fake.walk_to = lambda goal, nm, tag, **k: calls.append(("walk", tag)) or "arrived"
fake.find_at = lambda npc, pos, r=3.0, dy_max=3.0: NS(ptr=0x1D)
fake.fight = lambda ptr, nm, tag, **k: calls.append(("fight",)) or NS(result="killed")
fake.clear = lambda targets, nm, **k: calls.append(("clear",)) or "cleared"
ms = MS.Missions.__new__(MS.Missions)
ms.f, ms.nms, ms.log, ms.lure, ms.throw = fake, {MS.MAP_A: NM, MS.MAP_B: NM}, (lambda *a: None), True, False
ms.mv = NS()
r = ms.hunt_one(1)
check("9 hunt_one: fight → pickups → the walk back still happens", [c[0] for c in calls] == ["rest", "walk", "fight", "loot", "walk"]
      and r.startswith("killed"))
calls.clear()
r = ms.clear_ramp()
check("9 clear_ramp: pickups after the clear, back to the ramp arena", calls == [("clear",), ("loot", "경사로", MS.RAMP_ARENA)]
      and r == "cleared")
calls.clear()
fake.loot.on = False
r = ms.clear_ramp()
check("9 off: clear_ramp is the clear alone, same result", calls == [("clear",)] and r == "cleared")
fake.loot.on = True
calls.clear()
fake.snap_settled = lambda within=5.0: None
r = ms.clear_burg_town(only=set())
check("9 clear_burg_town: pickups at its end, result unchanged", calls == [("loot", "성벽 마을", None)] and r == "cleared")
calls.clear()
fake.home, fake.extra_zones, fake.tether = None, (), None
fake.careful_walk_to = lambda goal, nm, tag, done=None: calls.append(("walk", tag)) or "arrived"
r = ms.upper_zone(7)                                        # zone 7: no kills, no 'before' steps
check("9 upper_zone: pickups at the zone's end (no walk back), result unchanged",
      calls == [("walk", "구역7 안전 자리"), ("loot", "구역7", None)] and r == "cleared")
calls.clear()
check("9 zone 8 is skipped (narrow tower ledge, Taurus fog ahead)", 8 in MS.LOOT_SKIP_ZONES)

# ── 10. one named fixed treasure (Firelink humanity ×3): flag + count decide, nothing pressed when already taken ──
TR = L.TREASURES["firelink-humanity"]


def treasure_world(taken=False, unreadable=False):
    w = World(me=(-47.5, -59.8, 53.4))
    r = D.Rec(0x77, TR["pos"], 0x40000000 | TR["item"], TR["count"], None)
    w.ground[r.addr] = [r, not taken]
    f = field_for(w)
    f.bonfires = [(-47.5, -59.8, 53.4)]
    base = {"goods": 1}
    f.mv.tm.event_flag = lambda fid: None if unreadable else (not w.ground[0x77][1])
    f.mv.tm.goods_count = lambda item: base["goods"] + (0 if w.ground[0x77][1] else TR["count"])
    return w, f


w, f = treasure_world()
w.events.clear()
r = F.Field.pick_treasure(f, NM, TR, window=w.window)
check("10 humanity corpse: walked, A, flag False→True and count 1→4 → got", r["result"] == "got"
      and r["flag"] == [False, True] and r["goods"] == [1, 4] and w.presses >= 1)
w, f = treasure_world(taken=True)
r = F.Field.pick_treasure(f, NM, TR, window=w.window)
check("10 already taken (flag True): no walk, no A", r["result"] == "already" and not w.walks and w.presses == 0)
w, f = treasure_world(unreadable=True)
r = F.Field.pick_treasure(f, NM, TR, window=w.window)
check("10 flag unreadable: nothing pressed", r["result"] == "unknown" and w.presses == 0 and not w.walks)
w, f = treasure_world()
w.foes = [foe(0x1D000009, -40.0, 50.0, anim=-1)]
r = F.Field.pick_treasure(f, NM, TR, window=w.window)
check("10 foe near the corpse: not walked to", r["result"] == "foes_near" and not w.walks and w.presses == 0)
ms.f = NS(loot=NS(on=False), alive=lambda: True)
check("10 loot off: firelink_humanity does nothing", ms.firelink_humanity() is None)

print("loot_test: all ok")
