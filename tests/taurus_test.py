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
t, mv, pad = make([snap(b, me=(47.25, 15.8, -118.65), sp=98), snap(None, me=(47.25, 15.8, -118.65))])
mv.light = light
r = t._fight()
check("fight: killed (it just drops out of the snapshot, no quit-out)", r == "killed")
check("fight: three lights at full stamina (MoKa 11-09 \"3대를 연속으로\"), guard off while swinging", hits and hits[0] == (3, False))
check("fight: guard_ok restored afterwards", mv.guard_ok is True)
check("fight: LB released at the start", ("guard", (False,)) in pad.calls)

# P-141 ([MoKa] 11-08 "양잡 가드 하면서 다리 밑으로 들어가봐"): off the spot → LB held while walking in; at the spot → LB let go, then the lights
b = boss(x=47.0, y=15.8, z=-119.0, anim=-1)
t, mv, pad = make([snap(b, me=(50.0, 15.8, -119.0), sp=98), snap(b, me=(47.25, 15.8, -118.65), sp=98),
                   snap(None, me=(47.25, 15.8, -118.65))])
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

# P-144 (MoKa 11-09 "에스트를 왜 마셔 … 스테미나가 다 떨어져가서 할게 없으면 에스트 마셔도 되겠지만, 다른 케이스는 스테미나가
# 더 중요한 상황"): low HP but stamina for two → keep hitting between the legs, no sip
def _on(bb, me=(47.3, -119.3)):
    x, z = T.crotch_spot(bb, NS(x=me[0], z=me[1]))
    return (x, 15.8, z)
calm = boss(x=47.0, y=15.8, z=-119.0, anim=-1)
# (HP 136 → 300: 136 is now ≤ one hit, which drinks — MoKa 11-09 "한 대 남으면 마셔"; 300 is low but takes one more hit)
t, mv, pad = make([snap(calm, me=_on(calm), hp=300, sp=98), snap(None, me=_on(calm), hp=300)])
mv.light = lambda s, c, n=1, sp_second=40: (pad.calls.append(("light", (n,))), NS(dmg=0, taken=0))[1]
mv.drink = lambda ok: pad.calls.append(("drink", ())) or {"ok": True}
t.nm = None
t._fight()
names = [c[0] for c in pad.calls if c[0] in ("light", "drink")]
check(f"P-144: HP 300 (low, > one hit), stamina 98, on the spot, boss calm → lights, no sip ({names})", names[:1] == ["light"] and "drink" not in names)

# stamina short (30): boss swinging (3006, then 4100) → no sip, no light, guard, stay on the spot; calm → sip there
b = boss(x=47.0, y=15.8, z=-119.0, anim=3006)
b2 = boss(x=47.0, y=15.8, z=-119.0, anim=4100)
t, mv, pad = make([snap(b, me=_on(b), hp=136, sp=30), snap(b2, me=_on(b2), hp=136, sp=30),
                   snap(calm, me=_on(calm), hp=136, sp=30), snap(None, me=_on(calm), hp=400)])
mv.light = lambda s, c, n=1, sp_second=40: (pad.calls.append(("light", (n,))), NS(dmg=0, taken=0))[1]
mv.drink = lambda ok: pad.calls.append(("drink", ())) or {"ok": True}
t.nm = None
t._fight()
names = [c[0] for c in pad.calls if c[0] in ("guard", "light", "drink")]
i_drink = names.index("drink") if "drink" in names else None
check(f"P-144: stamina 30, boss in 3006 / 4100 → no sip, no light, guard; boss calm → sip on the spot ({names[:10]})",
      i_drink is not None and "light" not in names and ("guard", (True,)) in pad.calls[:pad.calls.index(("drink", ()))])
# P-142 2nd (065619): 4100 / 4101 / 4106 are attacks too (TAE) — no sip while the boss is in one
check("P-142: 4000–4006 · 4100–4106 count as boss attacks (TAE c2250), 3000–3499 too; 2255 (death) does not",
      all(a in T.BOSS_ATTACK for a in (3006, 4000, 4006, 4100, 4101, 4106)) and 2255 not in T.BOSS_ATTACK and 4107 not in T.BOSS_ATTACK)

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
_sp = T.crotch_spot(b, NS(x=47.0, z=-119.0))           # MoKa 11-09: sips happen between its legs
t, mv, pad = make([snap(b, me=(_sp[0], 15.8, _sp[1]), hp=320, sp=30), snap(None, me=(_sp[0], 15.8, _sp[1]))])
t.tm = NS(goods_count=lambda i: 2)
t.events = lambda *a, **k: None
mv.drink = lambda ok: drank.append(1) or {"ok": True}
mv.light = light
t._fight()
check(f"close fight: HP 320 (one hit left before death), stamina short, boss not swinging → Estus twice in a row (MoKa 11-09 \"두번\") ({drank})", drank == [1, 1])
# [MoKa] 11-09 "한 대 남으면 마셔" (073200: HP 3 · SP 98 swung → died, P-147): one hit from death → drink even with full stamina
drank = []; hits.clear()
t, mv, pad = make([snap(b, me=(_sp[0], 15.8, _sp[1]), hp=200, sp=98), snap(None, me=(_sp[0], 15.8, _sp[1]))])
t.tm = NS(goods_count=lambda i: 2)
t.events = lambda *a, **k: None
mv.drink = lambda ok: drank.append(1) or {"ok": True}
mv.light = light
t._fight()
check(f"close fight: HP 200 (≤ one hit), stamina 98, boss calm → Estus, no swing ({drank}, {hits})", drank == [1, 1] and hits == [])
drank = []; hits.clear()
b3006 = boss(x=48.5, y=15.8, z=-119.0, anim=3006, hp=400)
t, mv, pad = make([snap(b3006, me=(_sp[0], 15.8, _sp[1]), hp=200, sp=98)] * 3 + [snap(None, me=(_sp[0], 15.8, _sp[1]))])
t.tm = NS(goods_count=lambda i: 2)
t.events = lambda *a, **k: None
mv.drink = lambda ok: drank.append(1) or {"ok": True}
mv.light = light
t._fight()
check(f"close fight: HP 200, stamina 98, boss in 3006 → neither sip nor swing (waits on the spot) ({drank}, {hits})", drank == [] and hits == [])

# MoKa 11-09 "에스트를 마셔도 다리 사이에서 마셔야지": sip window open but 2 m off the spot → walk to it first, no sip yet
drank = []
b = boss(x=48.5, y=15.8, z=-119.0, anim=-1, hp=400)
t, mv, pad = make([snap(b, me=(46.0, 15.8, -121.0), hp=320, sp=30)] * 3 + [snap(None, me=(46.0, 15.8, -121.0))])
t.tm = NS(goods_count=lambda i: 2)
t.events = lambda *a, **k: None
t.nm = None
mv.drink = lambda ok: drank.append(1) or {"ok": True}
mv.light = light
T.nav.safe_heading = lambda nm, p, dx, dz, reach=1.0: (dx, dz)
try:
    t._fight()
finally:
    T.nav.safe_heading = T.nav_safe
_sp = T.crotch_spot(b, NS(x=46.0, z=-121.0))
_mv = [c[1] for c in pad.calls if c[0] == "move" and c[1] != (0.0, 0.0)]
check(f"low HP, sip window, 2 m off the between-legs spot → no sip yet, guard up, moves toward the spot ({drank}, {_mv[:2]})",
      drank == [] and ("guard", (True,)) in pad.calls and len(_mv) > 0)
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
# 11-09 "살짝 더 안쪽으로 … 두 다리 사이" (072235 sat 1–2 m in front = front foot): spot moved in to 0.0 front · 0.25 side
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
      hits == [] and moved and abs(sx - (47.0 - T.SPOT_SIDE)) < 0.01 and abs(sz - (-119.0 - T.SPOT_FWD)) < 0.01)
hits.clear()
t, mv, pad = make([snap(boss(x=47.0, y=15.8, z=-119.0, anim=-1, hp=500), me=(46.75, 15.8, -118.65), sp=98),
                   snap(None, me=(46.75, 15.8, -118.65))])
mv.light = light
t._fight()
check(f"close fight: between its legs (SPOT_FWD front, SPOT_SIDE side — MoKa 11-09 \"더 안쪽\") → swings three ({hits})", hits and hits[0][0] == 3)
check("crotch spot: player on its left → spot on its left",
      T.ang_off(boss(x=47.0, y=15.8, z=-119.0), NS(x=47.0 + 0.5, z=-119.3)) < 0
      and T.crotch_spot(boss(x=47.0, y=15.8, z=-119.0), NS(x=47.5, z=-119.3))[0] > 47.0)

# [MoKa] 11-09 "다리에 붙었으면 바로 공격하고 3대를 연속으로 때려봐" (was 11-03: wait for two-hit stamina 80 — 071032 waited 6 s
# with the guard up): on the spot with stamina 60 → three at once; stamina 30 (below HIT_SP 40) → no swing yet
hits.clear()
t, mv, pad = make([snap(boss(x=47.0, y=15.8, z=-119.0, anim=-1, hp=500), me=(46.75, 15.8, -118.65), sp=60)] * 3
                  + [snap(None, me=(46.75, 15.8, -118.65))])
mv.light = light
t._fight()
check(f"close fight: on the spot, stamina 60 → three lights right away ({hits})", hits and hits[0][0] == 3)
hits.clear()
t, mv, pad = make([snap(boss(x=47.0, y=15.8, z=-119.0, anim=-1, hp=500), me=(46.75, 15.8, -118.65), sp=30)] * 3
                  + [snap(None, me=(46.75, 15.8, -118.65))])
mv.light = light
t._fight()
check(f"close fight: on the spot, stamina 30 → no swing yet ({hits})", hits == [])
# [MoKa] 11-09 "다리에 붙으면 0.5초 내에 공격 들어가봐": stamina 30 but on the spot for SPOT_ATTACK_S → swings
hits.clear()
import time as _tt
_on_frames = [snap(boss(x=47.0, y=15.8, z=-119.0, anim=-1, hp=500), me=(46.75, 15.8, -118.65), sp=30)]
t, mv, pad = make(_on_frames * 40 + [snap(None, me=(46.75, 15.8, -118.65))])
mv.light = light
_t0 = _tt.time()
t._fight()
check(f"close fight: on the spot, stamina 30 → swings once SPOT_ATTACK_S has passed ({hits}, {_tt.time() - _t0:.2f} s)",
      hits and hits[0][0] == 3 and T.SPOT_ATTACK_S == 0.5)

# [MoKa] 11-09 "701엔 기다려" (073200 #1 · 075309 #1: lights started in 701 → boss walked off, 0 damage): on the spot, stamina 98,
# boss in 701 → no swing; once it leaves 701 → swings
hits.clear()
t, mv, pad = make([snap(boss(x=47.0, y=15.8, z=-119.0, anim=701, hp=500), me=(46.75, 15.8, -118.65), sp=98)] * 3
                  + [snap(None, me=(46.75, 15.8, -118.65))])
mv.light = light
t._fight()
check(f"close fight: on the spot, stamina 98, boss in 701 → waits, no swing ({hits})", hits == [])
hits.clear()
t, mv, pad = make([snap(boss(x=47.0, y=15.8, z=-119.0, anim=701, hp=500), me=(46.75, 15.8, -118.65), sp=98)] * 2
                  + [snap(boss(x=47.0, y=15.8, z=-119.0, anim=3005, hp=500), me=(46.75, 15.8, -118.65), sp=98)]
                  + [snap(None, me=(46.75, 15.8, -118.65))])
mv.light = light
t._fight()
check(f"close fight: 701 ends (boss now 3005) → three lights ({hits})", hits and hits[0][0] == 3)

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
