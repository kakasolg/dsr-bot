"""성벽 마을 화톳불 → 타우로스 안개벽 구역 오프라인 테스트 — souls/missions.py UPPER·upper_zone·_pull_to_safe (ROADMAP 1-m).

  data/burg-upper-map.json ([MoKa] 2026-10-06 녹화의 안전 자리·처치 순서)가 NavMesh와 맞는지, 그리고
  깨우러 감 → 깨면 안전 자리로 물러남 → 거기서 싸움 · 턱 위 화염병은 목표로 안 삼음 · 구역 동안만 home = 안전 자리

  python tests/burg_upper_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys
from pathlib import Path
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import navmesh
from souls import missions as MS

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


def length(p):
    return sum(math.dist(a, b) for a, b in zip(p, p[1:]))


# ── data vs NavMesh ─────────────────────────────────────────
nm = navmesh.Navmesh.from_npz(Path(__file__).resolve().parent.parent / "data" / "samples" / "navmesh_m10_01_00_00.npz")
zones = MS.UPPER["zones"]
check("7 zones, zone 7 (fog wall) has no foes", len(zones) == 7 and zones[6]["kills"] == [])
prev = MS.BURG_BONFIRE_SIDE
for z in zones:
    safe = tuple(z["safe"])
    check(f"zone {z['n']} safe spot is on the floor", nm.on_mesh(*safe, dy=1.5))
    p = nm.find_path(prev, safe)
    check(f"zone {z['n']} safe spot reachable from the previous one ({length(p):.0f} m)", len(p) >= 2)
    near = min((math.dist(q, s) for q in p for s in MS.UPPER_IGNORE), default=99.0)
    check(f"zone {z['n']} walk keeps off the firebomb ledge (closest {near:.1f} m)", near > MS.UPPER_IGNORE_R)
    for npc, pos in z["kills"]:
        p = nm.find_path(safe, tuple(pos))
        check(f"zone {z['n']} {npc} reachable from the safe spot ({length(p):.0f} m)", len(p) >= 2)
    prev = safe
check("ignored ledge foes are none of the zone targets",
      all(math.dist(tuple(pos), s) > MS.UPPER_IGNORE_R for z in zones for _n, pos in z["kills"] for s in MS.UPPER_IGNORE))


# ── pull-to-safe logic with fakes ───────────────────────────
class Chr(NS):
    pass


class LineNm:
    def find_path(self, a, b):
        return [tuple(a), tuple(b)]


MS.UPPER_NOTICE_S = 0.0     # no real waiting in the fakes


def make(foe, wake="moves", hp=742, results=("killed",), estus=5, other=None):
    """foe: Chr or None. wake: 'moves' = it wakes and steps toward us while we run in · 'asleep' = never wakes ·
    'idle_anim' = it plays an anim without leaving its spot (not awake). results: what each fight returns."""
    calls = []
    world = {"foe": foe, "hp": hp, "results": list(results), "near": False, "other": other}
    me = {"p": (-7.0, -10.0, -73.5)}

    def find_at(npc, pos, r=3.0, dy_max=3.0):
        c = world["foe"]
        return c if c is not None and c.npc_param == npc and math.dist((c.x, c.y, c.z), pos) < r else None

    def chars():
        return [c for c in (world["foe"], world["other"]) if c is not None and c.hp > 0]

    def snap(r=5.0):
        pl = NS(x=me["p"][0], y=me["p"][1], z=me["p"][2], hp=world["hp"], max_hp=742)
        return NS(player=pl, hostile=lambda rr: [c for c in chars() if math.hypot(c.x - pl.x, c.z - pl.z) < rr])

    def walk_path(path, nm_, mode="walk", stop=None, **kw):
        goal = tuple(path[-1])
        calls.append(("sprint", goal, mode))
        if goal != safe and foe is not None:               # running in
            if world["other"] is not None and world["other"].hp > 0 and world["other"].anim == -1:
                o = world["other"]                         # someone else wakes on the way, 6 m ahead of us
                o.anim = 3000
                me["p"] = (o.x, o.y, o.z - 6.0)
                return "stopped" if stop(snap()) else "arrived"
            if wake == "moves":
                foe.anim, foe.z = 3000, foe.z + 1.0
            elif wake == "idle_anim":
                foe.anim = 7000
            me["p"] = (foe.x, foe.y, foe.z - (6.0 if wake == "moves" else 2.0))
            return "stopped" if stop(snap()) else "arrived"
        me["p"] = goal
        if world["other"] is not None and world["other"].hp > 0 and world["other"].anim != -1:
            o = world["other"]                             # it followed us back
            o.x, o.z = goal[0], goal[2] - 3.0
        return "arrived"

    def fight(ptr, nm_, tag, wait_far=False, **kw):
        calls.append(("fight", ptr, wait_far, tuple(f.home) if f.home else None, tuple(getattr(f, "extra_zones", ())),
                      getattr(f, "tether", None)))
        r = world["results"].pop(0)
        if r == "killed":
            (world["other"] if world["other"] is not None and ptr == world["other"].ptr else world["foe"]).hp = 0
        return NS(result=r)

    def drink(safe_fn):
        calls.append(("drink", safe_fn(None)))
        world["hp"] = min(742, world["hp"] + 300)
        return {"ok": True}

    def heal(frac=0.7, sips=3):
        calls.append(("heal",))
        if not world["near"] and estus:
            world["hp"] = 742

    def retreat(nm_, home):
        calls.append(("retreat", tuple(home)))
        world["near"] = False
        return "arrived"

    f = NS(home=(0.0, 0.0, 0.0), find_at=find_at, fight=fight, careful_walk_to=lambda *a, **k: "arrived",
           recover=lambda *a, **k: calls.append(("recover",)) or True, estus_left=lambda: estus, alive=lambda: True,
           heal=heal, retreat=retreat, events=lambda *a, **k: None)
    mv = NS(snap=snap, walk_path=walk_path, pad=NS(guard=lambda on: None), drink=drink,
            find=lambda s, ptr: world["foe"] if world["foe"] and world["foe"].ptr == ptr else None)
    f.mv = mv
    m = MS.Missions.__new__(MS.Missions)
    m.f, m.mv, m.nms, m.log = f, mv, {MS.MAP_B: LineNm()}, lambda *a: None
    return m, f, calls, world


safe = (-7.0, -10.0, -73.5)
kinds = lambda calls: [c[0] for c in calls]
foe = Chr(npc_param=255001, ptr=11, x=-1.3, y=-10.1, z=-95.4, hp=85, anim=-1)
m, f, calls, w = make(foe)
r = m._pull_to_safe(255001, (-1.3, -10.1, -95.4), safe, LineNm(), "t")
check("run in, it wakes → run (no guard) back to the safe spot → fight waiting for it ([MoKa] '빠르게 나와야')",
      r == "killed" and kinds(calls) == ["sprint", "sprint", "fight"]
      and calls[0][2] == calls[1][2] == "sprint" and calls[1][1] == safe and calls[2][2] is True)

foe = Chr(npc_param=254010, ptr=12, x=2.9, y=-9.9, z=-98.3, hp=75, anim=-1)
m, f, calls, w = make(foe, wake="asleep")
r = m._pull_to_safe(254010, (2.9, -9.9, -98.3), safe, LineNm(), "t")
check("still asleep 3 m from it → guard a moment, then run back anyway and take it at the spot",
      r == "killed" and kinds(calls) == ["sprint", "sprint", "fight"] and calls[1][1] == safe)

foe = Chr(npc_param=254010, ptr=15, x=2.9, y=-9.9, z=-98.3, hp=75, anim=-1)
m, f, calls, w = make(foe, wake="idle_anim")
r = m._pull_to_safe(254010, (2.9, -9.9, -98.3), safe, LineNm(), "t")
check("an anim without leaving its spot is not 'awake' (still guard-wait, then back)",
      r == "killed" and kinds(calls) == ["sprint", "sprint", "fight"])

# 10-06d: 254011 already awake 4.4 m from the spot — the bot ran at it and then 'ran back' 2 m from the spot, hit 3 times
foe = Chr(npc_param=254011, ptr=16, x=-7.1, y=-10.0, z=-77.9, hp=75, anim=3000)
m, f, calls, w = make(foe)
c = m._lure(foe, 16, safe, LineNm(), "t")
check("already coming / near the spot → no running out, take it at the spot (10-06d)", c == "here" and calls == [])

foe = Chr(npc_param=254011, ptr=17, x=-6.0, y=-10.0, z=-79.0, hp=75, anim=-1)    # asleep but 5.6 m from the spot
m, f, calls, w = make(foe)
check("asleep but within 8 m of the spot → wait there too", m._lure(foe, 17, safe, LineNm(), "t") == "here" and calls == [])

foe = Chr(npc_param=255001, ptr=18, x=-1.3, y=-10.1, z=-95.4, hp=85, anim=-1)
m, f, calls, w = make(foe, results=("low_hp", "killed"))
r = m._pull_to_safe(255001, (-1.3, -10.1, -95.4), safe, LineNm(), "t")
check("low_hp → recover, and the same foe again until it dies (10-06d left 255001 alive)",
      r == "killed" and kinds(calls).count("fight") == 2 and "recover" in kinds(calls))

foe = Chr(npc_param=254010, ptr=19, x=2.9, y=-9.9, z=-98.3, hp=75, anim=-1)
m, f, calls, w = make(foe, hp=300)
r = m._pull_to_safe(254010, (2.9, -9.9, -98.3), safe, LineNm(), "t")
check("HP 300/742 → Estus before running out ([MoKa] '에스트를 마셔야 하는 것이 우선')", r == "killed" and kinds(calls)[0] == "heal")

foe = Chr(npc_param=254010, ptr=20, x=2.9, y=-9.9, z=-98.3, hp=75, anim=-1)
m, f, calls, w = make(foe, hp=300)
w["near"] = True                                       # a foe too close to drink
r = m._pull_to_safe(254010, (2.9, -9.9, -98.3), safe, LineNm(), "t")
check("low HP and a foe too close to drink → back off to the bonfire (home), then drink",
      r == "killed" and kinds(calls)[:3] == ["heal", "retreat", "heal"])

foe = Chr(npc_param=254010, ptr=21, x=2.9, y=-9.9, z=-98.3, hp=75, anim=-1)
m, f, calls, w = make(foe, hp=300, estus=0)
check("low HP and no Estus → stop the zone", m._pull_to_safe(254010, (2.9, -9.9, -98.3), safe, LineNm(), "t") == "no_estus")

# [MoKa]: "적을 조우하면 안전구역으로 돌아오는 것이 우선" — someone else wakes on the way in → back at once, fight it at the spot first
foe = Chr(npc_param=255001, ptr=22, x=-1.3, y=-10.1, z=-95.4, hp=85, anim=-1)
oth = Chr(npc_param=254011, ptr=23, x=-7.3, y=-9.9, z=-88.0, hp=75, anim=-1)
m, f, calls, w = make(foe, wake="asleep", results=("killed", "killed"), other=oth)
r = m._pull_to_safe(255001, (-1.3, -10.1, -95.4), safe, LineNm(), "t")
fp = [c[1] for c in calls if c[0] == "fight"]
check("another foe wakes on the way in → run back, fight it at the safe spot first, then the target",
      r == "killed" and fp == [23, 22] and calls[1] == ("sprint", safe, "sprint"))

# "무조건 에스트부터" — back at the spot with HP down (not low enough for _top_up), drink before fighting, foe near or not
foe = Chr(npc_param=255001, ptr=24, x=-1.3, y=-10.1, z=-95.4, hp=85, anim=-1)
m, f, calls, w = make(foe, hp=600)
r = m._pull_to_safe(255001, (-1.3, -10.1, -95.4), safe, LineNm(), "t")
k = kinds(calls)
check("back at the spot with HP 600/742 → Estus first (ignoring the foe-near check), then fight",
      r == "killed" and "drink" in k and k.index("drink") < k.index("fight") and ("drink", True) in calls)
foe = Chr(npc_param=255001, ptr=25, x=-1.3, y=-10.1, z=-95.4, hp=85, anim=-1)
m, f, calls, w = make(foe, hp=742)
m._pull_to_safe(255001, (-1.3, -10.1, -95.4), safe, LineNm(), "t")
check("full HP → no drink", "drink" not in kinds(calls))

ledge = MS.UPPER_IGNORE[0]
foe = Chr(npc_param=254012, ptr=13, x=ledge[0] + 1.0, y=ledge[1], z=ledge[2], hp=75, anim=-1)
m, f, calls, w = make(foe)
r = m._pull_to_safe(254012, ledge, safe, LineNm(), "t")
check("ledge firebomb hollow → not a target, nothing walked or fought", r == "gone" and calls == [])

m, f, calls, w = make(None)
check("foe not seen → gone", m._pull_to_safe(254010, (2.6, -9.9, -102.2), safe, LineNm(), "t") == "gone" and calls == [])

z2 = zones[1]
first = z2["kills"][0]
foe = Chr(npc_param=first[0], ptr=14, x=first[1][0], y=first[1][1], z=first[1][2], hp=85, anim=-1)
m, f, calls, w = make(foe)
home0 = f.home
r = m.upper_zone(2)
fights = [c for c in calls if c[0] == "fight"]
check("upper_zone: home = the Undead Burg bonfire during the zone (where recover drinks), restored after",
      r == "cleared" and fights and fights[0][3] == MS.BURG_BONFIRE_SIDE and f.home == home0)
check("upper_zone: the safe spot is the marked fall-back spot and the tether during the zone, cleared after",
      fights and fights[0][4] == (tuple(z2["safe"]),) and fights[0][5] == tuple(z2["safe"])
      and getattr(f, "extra_zones", ()) == () and getattr(f, "tether", None) is None)

# 10-06b: a chaser caught mid-walk 13 m before the zone 2 safe spot → the walk's chaser fight must fall back there first
from souls import field as F
here = NS(player=NS(x=-7.67, y=-10.09, z=-86.5))
fake = NS(extra_zones=(tuple(z2["safe"]),))
check("Field._near_zone offers the zone's safe spot 13 m back (death spot of 10-06b)",
      F.Field._near_zone(fake, here, nm) == tuple(z2["safe"]))
check("…and not without it", F.Field._near_zone(NS(), here, nm) is None)


# tether ([MoKa]: "적이 붙으면 그 다음에 안전 구역으로 가야 … 그냥 있으면 화염폭탄에 맞아서 죽지")
def tethered(results, start, spot=tuple(z2["safe"]), move=True, npc=None):
    """results: what each _fight_once returns; the player stands at `start` and is moved to the spot by a retreat."""
    pos = {"p": start}
    log = []

    def once(ptr, nm_, tag, arena, desperate, limit, wait_far, leash, may_approach, far=None):
        log.append(("fight", wait_far, far is not None, far() if far else None))
        return NS(result=results.pop(0))

    def retreat(zone, nm_):
        log.append(("retreat", tuple(zone)))
        if move:
            pos["p"] = zone
        return "arrived"

    me = NS(tether=spot, esc=NS(escaping=False), alive=lambda: True, log=lambda *a: None, events=lambda *a, **k: None,
            _fight_once=once, _retreat_to_zone=retreat,
            mv=NS(snap=lambda r=5.0: NS(player=NS(x=pos["p"][0], y=pos["p"][1], z=pos["p"][2]))))
    me._tether_far = lambda s: F.Field._tether_far(me, s)
    if npc is not None:
        me.mv.find = lambda s, ptr: NS(npc_param=npc)
    r = F.Field.fight(me, 1, None, "t")
    return r, log


r, log = tethered(["cancel", "killed"], (-7.67, -10.09, -86.5))
check("fight 13 m from the safe spot is cut → guard back to the spot → fought again there, waiting for it",
      r.result == "killed" and [x[0] for x in log] == ["fight", "retreat", "fight"]
      and log[0][3] is True and log[2][1] is True and log[2][3] is False)
r, log = tethered(["cancel"], (-7.0, -10.0, -75.0))
check("a cancel near the spot (another leash / escape) is passed on, no retreat", r.result == "cancel" and len(log) == 1)
r, log = tethered(["killed"], (0.0, 0.0, 0.0), spot=None)
check("no tether outside the zones → one plain fight", r.result == "killed" and log == [("fight", False, False, None)])
r, log = tethered(["cancel"] * F.TETHER_TRIES + ["killed"], (-7.67, -10.09, -86.5), move=False)
fights = [x for x in log if x[0] == "fight"]
check(f"after {F.TETHER_TRIES} cuts the last fight is untethered", r.result == "killed" and fights[-1][2] is False)
r, log = tethered(["killed"], (-7.67, -10.09, -86.5), npc=255002)
check("ranged foe (crossbow 255002) is not tethered — 10-06c cut it 3 times for 15 s",
      r.result == "killed" and log == [("fight", False, False, None)])
r, log = tethered(["cancel", "killed"], (-7.67, -10.09, -86.5), npc=255001)
check("melee foe (255001) still tethered", [x[0] for x in log] == ["fight", "retreat", "fight"])

print(f"\n{'all ok' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
