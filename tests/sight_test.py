"""Throw spots need a clear line to the target (docs/throwables.md, [board→cloud] 2026-10-12). No game.

  python tests/sight_test.py

Bot lock-on on the way, 2–10 m: 6/41 — body and camera were aligned, but every failure with a position had the straight line
blocked (a building, a wall). Checks:
  · Navmesh.clear_sight on recorded knife throws (both positions in the run's track): the locked ones pass — a ledge 3–6 m up
    included, which clear_line (can I walk it) calls blocked — and the failed ones are blocked, except 060343 구역1-4 n2
    (5 m, flat, floor all the way: a railing or a prop, not in the NavMesh)
  · burg-upper spawns: a throw spot is a point along the path 6–10 m out with the target in sight; none → no throw
  · Field._lure: walks to the spot in sight, not the first one in range; blocked everywhere → 'no_sight', nothing thrown;
    a preset lure_at spot never walks on; a mesh without clear_sight (test stubs) = as before
  · Missions._firebomb: blocked line → not thrown (an unlocked firebomb did 0, 8/8)
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import motion
from field_fakes import World, make_field
from souls import field as F
from souls import missions as MS

ROOT = Path(__file__).resolve().parent.parent
NMS = motion.load_navmeshes()


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


# (locked, map, run, tag, logged dist, player, target) — positions from the run's .track.jsonl at the log line
THROWS = [
    (False, "m10_01_00_00", "20261012_060343", "구역1-1 254010", 11.2, (-0.55, -10.02, -62.38), (-10.06, -11.5, -68.09)),
    (False, "m10_01_00_00", "20261012_060343", "구역1-4 254010", 9.7, (-13.11, -13.46, -67.72), (-15.95, -13.37, -58.66)),
    (False, "m10_01_00_00", "seg3-basic-10-01", "#1 254010", 11.1, (-63.93, -23.27, -22.52), (-53.06, -22.71, -23.95)),
    (False, "m10_01_00_00", "seg3-basic-10-01", "#1 254010", 6.5, (-55.2, -22.78, -29.75), (-52.75, -22.66, -23.86)),
    (False, "m10_01_00_00", "seg3-basic-10-01", "#2 254010", 8.5, (-60.17, -23.28, -27.5), (-52.7, -22.66, -23.8)),
    (True, "m10_02_00_00", "seg1-basic-10-01d", "#5 (+3.6 m)", 10.7, (-23.67, -42.86, 22.32), (-21.1, -39.27, 13.07)),
    (True, "m10_02_00_00", "seg1-basic-10-01d", "#5 (+3.1 m)", 10.2, (-23.56, -42.5, 21.79), (-17.51, -39.42, 16.27)),
    (True, "m10_02_00_00", "seg1-basic-10-01d", "#6 (+6.3 m)", 12.6, (-20.88, -40.29, 18.64), (-16.57, -33.95, 11.96)),
    (True, "m10_02_00_00", "clear-ramp-r1", "#5 (+3.6 m)", 10.7, (-23.7, -42.83, 22.28), (-21.1, -39.27, 13.07)),
    (True, "m10_02_00_00", "clear-ramp-r1", "#5 (+3.1 m)", 10.2, (-23.52, -42.52, 21.84), (-17.26, -39.37, 16.03)),
    (True, "m10_02_00_00", "clear-ramp-r1", "#6 (+6.3 m)", 12.5, (-20.74, -40.23, 18.61), (-16.48, -33.95, 11.73)),
]
RAILING = ("m10_01_00_00", (-17.56, -13.37, -63.83), (-16.31, -13.37, -58.94))   # 060343 구역1-4 n2, 5.4 m, not locked


def test_recorded_throws() -> None:
    for locked, m, run, tag, d, p, c in THROWS:
        nm = NMS[m]
        check(f"{run} {tag} {d} m: lock-on {'yes' if locked else 'no'} → clear_sight {locked}", nm.clear_sight(p, c) == locked)
    m, p, c = RAILING
    check("060343 구역1-4 5.4 m: floor all the way — the NavMesh can't see this one (known miss)", NMS[m].clear_sight(p, c))
    nm = NMS["m10_02_00_00"]
    _, _, _, _, _, p, c = THROWS[7]
    check("ledge 6 m up: in sight, though not walkable (clear_line)", nm.clear_sight(p, c) and not nm.clear_line(p, c))
    for i, la in MS.RAMP_LURE_AT.items():
        check(f"ramp #{i}: MoKa's preset throw spot has it in sight", nm.clear_sight(la["spot"], tuple(MS.RAMP[i - 1]["pos"])))


def test_spawn_spots() -> None:
    nm = NMS["m10_01_00_00"]
    zones = {z["n"]: z for z in json.loads((ROOT / "data" / "burg-upper-map.json").read_text(encoding="utf-8"))["zones"]}
    f = F.Field.__new__(F.Field)

    def spot(zn, k):
        z = zones[zn]
        safe, pos = tuple(z["safe"]), tuple(z["kills"][k - 1][1])
        path = nm.find_path(safe, pos)
        return pos, path, f._sight_spot(nm, path, pos, F.LURE_R)

    pos, path, sp = spot(4, 1)
    check(f"z4-1 254010: spot along the path {math.dist(sp, pos):.1f} m out, in sight",
          sp is not None and F.LURE_MIN <= math.dist(sp, pos) <= F.LURE_R and nm.clear_sight(sp, pos))
    pos, path, sp = spot(1, 3)
    first = f._sight_spot(nm, path, pos, F.LURE_R, sight=False)
    check("z1-3 254010: points 6–10 m out on the path, none in sight → no spot", sp is None and first is not None
          and not nm.clear_sight(first, pos))
    pos, path, sp = spot(1, 4)
    near = f._sight_spot(nm, path, pos, F.LURE_R, sight=False)
    check(f"z1-4 254010: the first point in range is blocked, a later one ({math.dist(sp, pos):.1f} m) is not",
          near is not None and not nm.clear_sight(near, pos) and sp is not None and sp != near)


class SightNm:
    """Straight path; the target is in sight only from z ≥ open_z (a wall corner before it)."""
    def __init__(self, open_z: float | None):
        self.open_z = open_z

    def find_path(self, a, b):
        return [tuple(a), tuple(b)]

    def clear_sight(self, a, b):
        return self.open_z is not None and a[2] >= self.open_z - 1e-6


class StubNm:                                              # no clear_sight — the old behaviour
    def find_path(self, a, b):
        return [tuple(a), tuple(b)]


def lure_rig(nm, start=(0.0, 0.0, 0.0), lure_at=None, arena=None):
    w = World(player=start)
    w.add(7, 0x1007, 254010, (0.0, 0.0, 20.0))
    f = make_field(w)
    del f.lure                                             # the real lure/_lure
    f._asleep = lambda ptr, hold=0.4: True
    f._settle = lambda spot, tol=None, tries=10: 0.0
    f.mv.tm.goods_count = lambda item: 20
    throws = []

    def throw(ptr, **kw):
        throws.append((w.player.x, w.player.y, w.player.z))
        return {"ok": True, "locked": True, "hit": 30, "woke": True}
    f.mv.throw_knife = throw

    def walk_to(goal, nm_, tag, mode="walk", tol=None, done=None):
        f.walks.append((tuple(goal), tag))
        w.player.x, w.player.y, w.player.z = goal
        return "arrived"
    f.walk_to = walk_to
    r = F.Field.lure(f, 7, [0.0, 0.0, 20.0], nm, "#7", arena=arena, lure_at=lure_at)
    return r, f, throws


def test_lure() -> None:
    r, f, throws = lure_rig(SightNm(open_z=13.0))
    check(f"lure: walks to the first spot in sight (z {f.walks[0][0][2] if f.walks else None}, 7 m) and throws there",
          r == "lured" and len(throws) == 1 and abs(throws[0][2] - 13.0) < 0.01)
    r, f, throws = lure_rig(SightNm(open_z=None))
    check("lure: no spot in sight on the path → 'no_sight', no walk, nothing thrown",
          r == "no_sight" and not throws and not f.walks and any("트인 던질 자리 없음" in s for s in f.logs))
    r, f, throws = lure_rig(SightNm(open_z=13.0), start=(0.0, 0.0, 6.0),
                            lure_at={"spot": (0.0, 0.0, 6.0), "min": 0.0, "max": 15.0})
    check("lure: preset lure_at spot blocked → 'no_sight', never walks closer", r == "no_sight" and not throws and not f.walks)
    r, f, throws = lure_rig(SightNm(open_z=13.0), arena=(0.0, 0.0, 9.0))
    check("lure: arena in range but blocked → a spot in sight on the path instead",
          r == "lured" and throws and throws[0][2] >= 13.0)
    r, f, throws = lure_rig(StubNm())
    check("lure: a mesh without clear_sight → line not checked (first point 6–10 m out on the path, z 10)",
          r == "lured" and len(throws) == 1 and abs(throws[0][2] - 10.0) < 0.01)


def test_into_sight_on_the_way() -> None:
    """Spot was in sight, the target stepped behind the corner by the time we got there → walk on to where it is in sight."""
    w = World(player=(0.0, 0.0, 10.0))
    w.add(7, 0x1007, 254010, (0.0, 0.0, 20.0))
    f = make_field(w)
    f._asleep = lambda ptr, hold=0.4: True

    def walk_to(goal, nm_, tag, mode="walk", tol=None, done=None):
        f.walks.append((tuple(goal), tag))
        w.player.x, w.player.y, w.player.z = goal
        return "arrived"
    f.walk_to = walk_to
    s = f.mv.snap(40.0)
    r = f._into_sight(7, SightNm(open_z=12.0), "#7", s, f.mv.find(s, 7), None)
    check("into_sight: blocked here → walks along the path to the first spot in sight, then throws (None)",
          r is None and f.walks and abs(f.walks[0][0][2] - 12.0) < 0.01)


def test_firebomb_blocked() -> None:
    pl = NS(x=0.0, y=0.0, z=0.0)
    foe = NS(ptr=9, x=0.0, y=0.0, z=8.0, hp=75, npc_param=254000)
    thrown, logs, evs = [], [], []
    m = MS.Missions.__new__(MS.Missions)
    m.mv = NS(snap=lambda r=5.0: NS(player=pl), find=lambda s, ptr: foe,
              throw_firebomb=lambda ptr: thrown.append(ptr) or {"ok": True, "hit": 80})
    m.f = NS(events=lambda kind, **kw: evs.append((kind, kw)))
    m.log = logs.append
    m.nms = {MS.MAP_B: SightNm(open_z=None)}
    r = m._firebomb(9, "구역1", "test")
    check("firebomb: line blocked → not thrown, logged", not r.get("ok") and not thrown and any("직선이 막힘" in s for s in logs))
    m.nms = {MS.MAP_B: SightNm(open_z=-1.0)}
    r = m._firebomb(9, "구역1", "test")
    check("firebomb: line clear → thrown", r.get("ok") and thrown == [9])


if __name__ == "__main__":
    test_recorded_throws()
    test_spawn_spots()
    test_lure()
    test_into_sight_on_the_way()
    test_firebomb_blocked()
    print("all passed")
