"""souls/taurus.py — what tries 1–4 on 2026-10-12 got wrong, as fakes (no game).  python tests/taurus_test.py

  · awake: on its perch the boss reads y 27.0, anim 9001 — not called yet (tries 1–2 ran to the ladder and it never came);
    moving (4004) or down at bridge height is called
  · plunge wait: knocked off the top → stop waiting at once and fight (try 3 stood below it waiting and died)
  · fight: no guard while two-handed (try 4: LB held after each swing, the axe soaked its hits, 1 of 4 lights landed);
    two lights in a row from HIT_SP2 stamina
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import taurus as T

fails = 0


def check(name, ok):
    global fails
    print(("  ok   " if ok else "  FAIL ") + name)
    fails += 0 if ok else 1


def snap(boss=None, me=(50.5, 24.8, -117.1), hp=680, sp=98):
    pl = NS(x=me[0], y=me[1], z=me[2], gx=me[0], gy=me[1], gz=me[2], hp=hp, max_hp=742, sp=sp, anim=-1, heading=0.0)
    return NS(player=pl, chars=[boss] if boss else [], cam_yaw=0.0)


def boss(x=-6.7, y=27.0, z=-110.4, anim=9001, hp=1215):
    return NS(npc_param=T.TAURUS, x=x, y=y, z=z, anim=anim, hp=hp, heading=0.0, ptr=7)


check("perch: y 27.0, anim 9001 → not called", not T.Taurus.awake(snap(boss())))
check("running (4004) → called", T.Taurus.awake(snap(boss(anim=4004))))
check("down on the bridge (y 15.8, idle) → called", T.Taurus.awake(snap(boss(y=15.8, anim=-1))))
check("no boss in the snapshot → not called", not T.Taurus.awake(snap()))


class Pad:
    def __init__(self):
        self.calls = []

    def __getattr__(self, k):
        return lambda *a, **kw: self.calls.append((k, a))


def make(snaps, alive=True):
    seq = list(snaps)
    pad = Pad()
    mv = NS(tm=NS(), pad=pad, guard_ok=True, snap=lambda r=40.0: seq.pop(0) if len(seq) > 1 else seq[0],
            stick_to=lambda s, x, z, sc=1.0: (0.0, sc), face=lambda s, c, deg=20.0: True, estus_left=lambda: 4)
    f = NS(mv=mv, alive=lambda: alive, esc=NS(quit_ok=True, nudge_ok=True, gen=0))
    t = T.Taurus(f, None, None, log=lambda *a: None)
    return t, mv, pad


t, mv, pad = make([snap(boss(x=45.0, y=15.8, z=-119.0, anim=3001), me=(47.0, 15.9, -119.6))])
check("plunge wait: already down from the top → 'off_top' at once (fight next)", t._plunge() == "off_top")

hits = []


def light(s, c, n=1, sp_second=40):
    hits.append((n, mv.guard_ok))
    c.hp = 0
    return NS(dmg=91 * n, taken=0)


b = boss(x=47.0, y=15.8, z=-119.0, anim=-1)
t, mv, pad = make([snap(b, me=(47.5, 15.8, -119.5), sp=98), snap(None, me=(47.5, 15.8, -119.5))])
mv.light = light
r = t._fight()
check("fight: killed (it just drops out of the snapshot, no quit-out)", r == "killed")
check("fight: two lights at full stamina, guard off while swinging", hits and hits[0] == (2, False))
check("fight: guard_ok restored afterwards", mv.guard_ok is True)
check("fight: LB released at the start", ("guard", (False,)) in pad.calls)

# try 11: a fall quit-out reloaded us in front of the fog wall — the boss (HP 150) just dropped out of the snapshot
t, mv, pad = make([snap(boss(x=47.0, y=15.8, z=-119.0, anim=3005, hp=150), me=(47.5, 15.8, -119.5), sp=10),
                   snap(None, me=(51.9, 17.2, -118.6))])
t.f.esc.gen = 0
mv.snap_calls = 0
_s0 = mv.snap
def _snap(r=40.0):
    mv.snap_calls += 1
    if mv.snap_calls == 2:
        t.f.esc.gen = 1                                # the quit-out happens between the two looks
    return _s0(r)
mv.snap = _snap
check("fight: boss gone without HP 0 (quit-out) → 'gone', not 'killed'", t._fight() == "gone")

# AttackLog ([MoKa] 10-12 "이런 경우는 피해진다 / 반드시 피격 당한다는 데이타"): idle → 3003 starts 2 m in front → HP drops →
# anim ends → one event with where we stood, what we were doing and the damage
import time as _time
frames = [snap(boss(x=0.0, y=15.8, z=2.0, anim=-1), me=(0.0, 15.8, 0.0))] * 3     + [snap(boss(x=0.0, y=15.8, z=2.0, anim=3003), me=(0.0, 15.8, 0.0))] * 3     + [snap(boss(x=0.0, y=15.8, z=2.0, anim=3003), me=(0.0, 15.8, 0.0), hp=447)] * 2     + [snap(boss(x=0.0, y=15.8, z=2.0, anim=-1), me=(0.0, 15.8, 0.0), hp=447)] * 40
for fr in frames:
    fr.chars[0].heading = math.pi                     # world yaw = heading + π = 0 → it faces +z, away from us at z 0
evs = []
q = list(frames)
alog = T.AttackLog(NS(snapshot=lambda within=40.0: q.pop(0) if len(q) > 1 else q[0]),
                   lambda kind, **kw: evs.append((kind, kw)), lambda *a: None)
alog.start()
_time.sleep(1.2)
alog.stop_ev.set()
alog.join(2.0)
att = [kw for k, kw in evs if k == "taurus" and kw.get("what") == "attack"]
check(f"AttackLog: one 3003, −233, 2 m, our anim kind recorded ({att})",
      len(att) == 1 and att[0]["anim"] == 3003 and att[0]["dmg"] == 233 and abs(att[0]["h"] - 2.0) < 0.01
      and att[0]["me"] == "서 있음/걷기")
check(f"AttackLog: angle = where we stand off its facing (it faces away from us here → behind, ±180)",
      att and abs(abs(att[0]["ang"]) - 180) <= 1)

print("all ok" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
