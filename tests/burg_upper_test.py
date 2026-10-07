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


def make(foe, woke_on_walk=True):
    """foe: Chr or None. woke_on_walk: careful_walk_to's done() fires (foe woke) instead of arriving."""
    calls = []
    world = {"foe": foe}

    def find_at(npc, pos, r=3.0, dy_max=3.0):
        c = world["foe"]
        return c if c is not None and c.npc_param == npc and math.dist((c.x, c.y, c.z), pos) < r else None

    def careful_walk_to(goal, nm_, tag, done=None):
        calls.append(("walk", tag, done is not None))
        if done is None:
            return "arrived"
        if woke_on_walk and foe is not None:
            foe.anim = 3000
            return "done" if done(NS(player=NS(x=foe.x + 5, y=foe.y, z=foe.z))) else "arrived"
        return "arrived"

    def fight(ptr, nm_, tag, wait_far=False, **kw):
        calls.append(("fight", ptr, wait_far, tuple(f.home) if f.home else None, tuple(getattr(f, "extra_zones", ()))))
        world["foe"].hp = 0
        return NS(result="killed")

    f = NS(home=(0.0, 0.0, 0.0), find_at=find_at, careful_walk_to=careful_walk_to, fight=fight,
           retreat=lambda nm_, home: calls.append(("retreat", tuple(home))) or "arrived",
           recover=lambda *a, **k: True, estus_left=lambda: 5, alive=lambda: True)
    mv = NS(snap=lambda r=5.0: NS(), find=lambda s, ptr: world["foe"] if world["foe"] and world["foe"].ptr == ptr else None)
    f.mv = mv
    m = MS.Missions.__new__(MS.Missions)
    m.f, m.mv, m.nms, m.log = f, mv, {MS.MAP_B: None}, lambda *a: None
    return m, f, calls


safe = (-7.0, -10.0, -73.5)
foe = Chr(npc_param=255001, ptr=11, x=-1.3, y=-10.1, z=-95.4, hp=85, anim=-1)
m, f, calls = make(foe)
r = m._pull_to_safe(255001, (-1.3, -10.1, -95.4), safe, None, "t")
check("woke while walking → retreat to the safe spot, then fight waiting for it",
      r == "killed" and [c[0] for c in calls] == ["walk", "retreat", "fight"] and calls[1][1] == safe and calls[2][2] is True)

foe = Chr(npc_param=254010, ptr=12, x=2.9, y=-9.9, z=-98.3, hp=75, anim=-1)
m, f, calls = make(foe, woke_on_walk=False)
r = m._pull_to_safe(254010, (2.9, -9.9, -98.3), safe, None, "t")
check("still asleep on arrival → fight there, no retreat", r == "killed" and [c[0] for c in calls] == ["walk", "fight"])

ledge = MS.UPPER_IGNORE[0]
foe = Chr(npc_param=254012, ptr=13, x=ledge[0] + 1.0, y=ledge[1], z=ledge[2], hp=75, anim=-1)
m, f, calls = make(foe)
r = m._pull_to_safe(254012, ledge, safe, None, "t")
check("ledge firebomb hollow → not a target, nothing walked or fought", r == "gone" and calls == [])

m, f, calls = make(None)
check("foe not seen → gone", m._pull_to_safe(254010, (2.6, -9.9, -102.2), safe, None, "t") == "gone" and calls == [])

z2 = zones[1]
first = z2["kills"][0]
foe = Chr(npc_param=first[0], ptr=14, x=first[1][0], y=first[1][1], z=first[1][2], hp=85, anim=-1)
m, f, calls = make(foe)
home0 = f.home
r = m.upper_zone(2)
fights = [c for c in calls if c[0] == "fight"]
check("upper_zone: home = the zone's safe spot during the fight, restored after",
      r == "cleared" and fights and fights[0][3] == tuple(z2["safe"]) and f.home == home0)
check("upper_zone: the safe spot is a marked fall-back spot during the zone, cleared after (10-06b)",
      fights and fights[0][4] == (tuple(z2["safe"]),) and getattr(f, "extra_zones", ()) == ())

# 10-06b: a chaser caught mid-walk 13 m before the zone 2 safe spot → the walk's chaser fight must fall back there first
from souls import field as F
here = NS(player=NS(x=-7.67, y=-10.09, z=-86.5))
fake = NS(extra_zones=(tuple(z2["safe"]),))
check("Field._near_zone offers the zone's safe spot 13 m back (death spot of 10-06b)",
      F.Field._near_zone(fake, here, nm) == tuple(z2["safe"]))
check("…and not without it", F.Field._near_zone(NS(), here, nm) is None)


# tether ([MoKa]: "적이 붙으면 그 다음에 안전 구역으로 가야 … 그냥 있으면 화염폭탄에 맞아서 죽지")
def tethered(results, start, spot=tuple(z2["safe"]), move=True):
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

print(f"\n{'all ok' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
