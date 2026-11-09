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

# 11-02 002807: on the top at 32 % HP with the boss 4.3 m below the ladder → drink first (it plunged and died with the boss at HP 9)
t, mv, pad = make([snap(boss(x=46.0, y=15.8, z=-118.0, anim=-1), me=(49.1, 24.7, -117.4), hp=225)])
drinks = []
mv.drink = lambda ok: drinks.append(1) or {"ok": True}
t.tm = NS(goods_count=lambda i: 0)
t.events = lambda *a, **k: None
t._on_top()
check("top: HP 32 % with the boss right below → Estus anyway", drinks == [1])
t, mv, pad = make([snap(boss(x=46.0, y=15.8, z=-118.0, anim=-1), me=(49.1, 24.7, -117.4), hp=600)])
drinks = []
mv.drink = lambda ok: drinks.append(1) or {"ok": True}
t.tm = NS(goods_count=lambda i: 0)
t.events = lambda *a, **k: None
t._on_top()
check("top: HP 81 % → no Estus", drinks == [])

hits = []


def light(s, c, n=1, sp_second=40):
    hits.append((n, mv.guard_ok))
    c.hp = 0
    return NS(dmg=91 * n, taken=0)


b = boss(x=47.0, y=15.8, z=-119.0, anim=-1)
t, mv, pad = make([snap(b, me=(47.3, 15.8, -119.3), sp=98), snap(None, me=(47.3, 15.8, -119.3))])
mv.light = light
r = t._fight()
check("fight: killed (it just drops out of the snapshot, no quit-out)", r == "killed")
check("fight: two lights at full stamina, guard off while swinging", hits and hits[0] == (2, False))
check("fight: guard_ok restored afterwards", mv.guard_ok is True)
check("fight: LB released at the start", ("guard", (False,)) in pad.calls)

# P-141 ([MoKa] 11-08 "양잡 가드 하면서 다리 밑으로 들어가봐"): off the spot → LB held while walking in; at the spot → LB let go, then the lights
b = boss(x=47.0, y=15.8, z=-119.0, anim=-1)
t, mv, pad = make([snap(b, me=(50.0, 15.8, -119.0), sp=98), snap(b, me=(47.3, 15.8, -119.3), sp=98),
                   snap(None, me=(47.3, 15.8, -119.3))])
mv.light = lambda s, c, n=1, sp_second=40: (pad.calls.append(("light", (n,))), setattr(c, "hp", 0), NS(dmg=91 * n, taken=0))[2]
t.nm = None
T.nav_safe = T.nav.safe_heading
T.nav.safe_heading = lambda nm, p, dx, dz, reach=1.0: (dx, dz)
try:
    t._fight()
finally:
    T.nav.safe_heading = T.nav_safe
seq = [c for c in pad.calls if c[0] in ("guard", "light")]
i_on = seq.index(("guard", (True,))) if ("guard", (True,)) in seq else None
i_hit = next((i for i, c in enumerate(seq) if c[0] == "light"), None)
check(f"fight (P-141): guard up walking to the spot, down right before the lights ({seq})",
      T.GUARD_CLOSE and i_on is not None and i_hit is not None and i_on < i_hit and seq[i_hit - 1] == ("guard", (False,)))

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

# [MoKa] 11-02 "낙하 공격 한 번 하고 황금 송진 유효할때 계속 때려. 에스트 마시면서 … 계단 올라가는 것도 위험해 보여"
t, mv, pad = make([snap(boss(x=47.0, y=15.8, z=-119.0, anim=-1, hp=714), me=(48.0, 15.8, -119.0))])
went = []
t._punish = lambda: went.append("punish")
t._back_up = lambda cycle: went.append("back_up") or "ok"
t._fight = lambda: went.append("fight") or "killed"
r = t._loop("ok", True)
check(f"one plunge: after landing → punish → close fight, no climb back ({went})", r == "killed" and went == ["punish", "fight"])

# [MoKa] 11-02 "송진 다시 바르면 절대 않되. 그러다가 죽어" — the close fight never rubs the resin, even worn off and 5 m away
rubbed = []
b = boss(x=52.0, y=15.8, z=-119.0, anim=-1, hp=500)
t, mv, pad = make([snap(b, me=(47.0, 15.8, -119.0)), snap(None, me=(47.0, 15.8, -119.0))])
t.tm = NS(goods_count=lambda i: 2)
t.events = lambda *a, **k: None
t.resin_t = None
t._resin = lambda wait=1.0: rubbed.append(wait)
t._fight()
check("close fight: resin worn off, boss 5 m away and idle → still no rub", rubbed == [])

# 11-02 051424: 320/698 after one −242 → no drink (40 % rule) → next −242 → 78 → died. Below two hits (490) → drink
drank = []
b = boss(x=48.5, y=15.8, z=-119.0, anim=-1, hp=400)
t, mv, pad = make([snap(b, me=(47.0, 15.8, -119.0), hp=320), snap(None, me=(47.0, 15.8, -119.0))])
t.tm = NS(goods_count=lambda i: 2)
t.events = lambda *a, **k: None
mv.drink = lambda ok: drank.append(1) or {"ok": True}
mv.light = light
t._fight()
check(f"close fight: HP 320 (one hit left before death) and boss not swinging → Estus ({drank})", drank == [1])
drank.clear()
t, mv, pad = make([snap(boss(x=48.5, y=15.8, z=-119.0, anim=-1, hp=400), me=(47.0, 15.8, -119.0), hp=562),
                   snap(None, me=(47.0, 15.8, -119.0))])
t.tm = NS(goods_count=lambda i: 2)
t.events = lambda *a, **k: None
mv.drink = lambda ok: drank.append(1) or {"ok": True}
mv.light = light
t._fight()
check("close fight: HP 562 (takes two hits) → hits, no Estus", drank == [])

# [MoKa] 11-03: "나는 보스 가랑이 사이에서 공격 한거야" (try 21 클립: "봇은 보스의 앞쪽에서 공격하는 것이 차이")
# boss heading 0 faces −z. try 22 died on its center line 0.6 m in front (−244 × 2) → no swing there, walk to the spot;
# MoKa's swings (taurus_watch 20261103_064407): 0.2–1.0 m in front, 0.5–0.8 m to the side → swing there
_nav = T.nav.safe_heading
T.nav.safe_heading = lambda nm, p, dx, dz, reach=1.0: (dx, dz)
hits.clear()
t, mv, pad = make([snap(boss(x=47.0, y=15.8, z=-119.0, anim=-1, hp=500), me=(47.0, 15.8, -119.6), sp=98)] * 3
                  + [snap(None, me=(47.0, 15.8, -119.6))])
t.nm = None
mv.light = light
moved = []
mv.stick_to = lambda s, x, z, sc=1.0: moved.append((round(x, 2), round(z, 2))) or (0.0, sc)
t._fight()
sx, sz = T.crotch_spot(boss(x=47.0, y=15.8, z=-119.0), NS(x=47.0, z=-119.6))
check(f"close fight: center line 0.6 m in front → no swing, walks to the spot ({hits}, spot {sx:.2f},{sz:.2f}, moves {moved[:1]})",
      hits == [] and moved and abs(sx - 46.4) < 0.01 and abs(sz - -119.4) < 0.01)
hits.clear()
t, mv, pad = make([snap(boss(x=47.0, y=15.8, z=-119.0, anim=-1, hp=500), me=(46.4, 15.8, -119.45), sp=98),
                   snap(None, me=(46.4, 15.8, -119.45))])
mv.light = light
t._fight()
check(f"close fight: between its legs (0.4 front, 0.6 side) → swings ({hits})", hits and hits[0][0] == 2)
check("crotch spot: player on its left → spot on its left",
      T.ang_off(boss(x=47.0, y=15.8, z=-119.0), NS(x=47.0 + 0.5, z=-119.3)) < 0
      and T.crotch_spot(boss(x=47.0, y=15.8, z=-119.0), NS(x=47.5, z=-119.3))[0] > 47.0)

# [MoKa] 11-03 "2대 때리고 다시 가랑이에 붙어봐 … 스테미나도 채워야해": on the spot with stamina 60 (one light's worth) → no swing
hits.clear()
t, mv, pad = make([snap(boss(x=47.0, y=15.8, z=-119.0, anim=-1, hp=500), me=(46.4, 15.8, -119.45), sp=60)] * 3
                  + [snap(None, me=(46.4, 15.8, -119.45))])
mv.light = light
t._fight()
check(f"close fight: on the spot, stamina 60 → waits for two-hit stamina, no single light ({hits})", hits == [])

# [MoKa] 11-03 "때릴때 마다 뒤로 밀려" — pushed 1.2 m back off the spot after a swing → full stick back in
T.nav.safe_heading = lambda nm, p, dx, dz, reach=1.0: (dx, dz)
t, mv, pad = make([snap(boss(x=47.0, y=15.8, z=-119.0, anim=-1, hp=500), me=(46.4, 15.8, -120.6), sp=30)] * 3
                  + [snap(None, me=(46.4, 15.8, -120.6))])
t.nm = None
scales = []
mv.stick_to = lambda s, x, z, sc=1.0: scales.append(sc) or (0.0, sc)
t._fight()
check(f"close fight: pushed back 1.2 m off the spot → full stick back in ({scales[:2]})", scales and scales[0] == 1.0)
T.nav.safe_heading = _nav

print("all ok" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
