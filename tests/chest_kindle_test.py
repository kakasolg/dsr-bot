"""구역 5 문 → 宝箱01 황금송진 · 성벽 마을 화톳불 불 지피기 · 사다리 옆 안개벽 A 금지 — 오프라인 테스트 (11-01 MoKa 요청 세 가지).

  python tests/chest_kindle_test.py

Fake pads / telemetry and the Burg NavMesh only — not a game check.
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

import kindle
import navmesh
from field_fakes import World, make_field
from souls import field as F
from souls import missions as MS

NPZ = Path(__file__).resolve().parent.parent / "data" / "samples" / "navmesh_m10_01_00_00.npz"
CHEST = MS.UPPER["zones"][4]["after"][0]["chest"]


def test_chest_data_on_navmesh() -> None:
    nm = navmesh.Navmesh.from_npz(NPZ)
    assert math.dist(CHEST["door_front"], CHEST["door"]) < 1.0
    assert math.hypot(CHEST["stand"][0] - CHEST["chest"][0], CHEST["stand"][2] - CHEST["chest"][2]) < 2.0
    assert len(nm.find_path(tuple(MS.UPPER["zones"][4]["safe"]), tuple(CHEST["door_front"]))) >= 2
    assert len(nm.find_path(tuple(CHEST["door_front"]), tuple(CHEST["stand"]))) >= 2
    print("ok  zone 5 after-step: door front < 1 m from the door, chest stand < 2 m from the chest, both reachable on the NavMesh")


class Tm:
    def __init__(self, door=False, taken=False):
        self.flags = {61010510: door, 51010460: taken}
        self.resin, self.quick = 0, [201, -1, -1, -1, -1]

    def event_flag(self, fid):
        return self.flags.get(fid)

    def goods_count(self, item):
        return self.resin if item == 311 else 0

    def equip_quick_item(self, item):
        self.quick[1] = item
        return 1


def chest_run(tm, at=(24.1, -5.7, -99.0)):
    f = make_field(World(player=at))
    m = MS.Missions.__new__(MS.Missions)
    m.f, m.mv, m.log = f, f.mv, f.log
    f.mv.tm = tm
    f.mv.snap = lambda *a, **k: NS(player=NS(x=CHEST["chest"][0], z=CHEST["chest"][2]), cam_yaw=0.0, hostile=lambda r: [])
    f.mv.stick_to = lambda *a, **k: (0.0, 0.0)
    f.walk_to = lambda q, nm, tag, **k: f.walks.append(tuple(q)) or "arrived"
    f.alive = lambda: True
    f._settle = lambda *a, **k: None
    presses = []

    def interact():
        presses.append(len(f.walks))
        if f.walks and tuple(f.walks[-1]) == tuple(CHEST["door_front"]):
            tm.flags[61010510] = True                 # door swings open
        elif len(presses) >= 2 and tm.flags[61010510]:
            tm.flags[51010460], tm.resin = True, 3    # second A at the chest takes the resin
    f.mv.pad.interact = interact
    sleep = MS.time.sleep
    MS.time.sleep = lambda s: None
    import drops
    import steam_state
    nodes, check = drops.itemget_nodes, steam_state.check
    drops.itemget_nodes = lambda tm: [(0x40000137, 3)] if tm.flags[51010460] else []
    steam_state.check = lambda: {"offline": True}
    try:
        r = MS.Missions._chest(m, CHEST, None, "구역5")
    finally:
        MS.time.sleep, drops.itemget_nodes, steam_state.check = sleep, nodes, check
    return r, f, presses


def test_chest_opens_shut_door_then_takes() -> None:
    tm = Tm(door=False)
    r, f, presses = chest_run(tm)
    assert r == "taken" and tm.resin == 3 and tm.quick[1] == 311, (r, tm.resin, tm.quick, f.logs)
    assert f.walks[0] == tuple(CHEST["door_front"]) and f.walks[1] == tuple(CHEST["stand"])
    print(f"ok  chest: shut door → walk to its front, A, then chest A×2 → resin 0→3, quick slot 311, window closed ({len(presses)} A)")


def test_chest_open_door_no_a() -> None:
    tm = Tm(door=True)
    r, f, presses = chest_run(tm)
    assert r == "taken" and tuple(CHEST["door_front"]) not in f.walks and presses and presses[0] == 1
    print("ok  chest: door already open (state flag True) → no door A (A would shut it), straight to the chest")


def test_chest_already_taken() -> None:
    tm = Tm(door=False, taken=True)
    r, f, presses = chest_run(tm)
    assert r == "already" and not presses and not f.walks
    print("ok  chest: flag 51010460 already True → nothing pressed, nowhere walked")


def test_chest_nudge_walks_in() -> None:
    # 11-01 183919: stick 0.3 only turned the body (1.34 m, 8 pulses, no move) → pulses must be a walking stick
    box = CHEST["chest"]
    for moves, want in ((True, "reach"), (False, "stuck")):
        tm = Tm(door=True)
        p = {"x": 30.06, "z": -111.47}
        sticks = []
        r, f, presses = None, None, None
        f = make_field(World(player=(30.06, -7.5, -111.47)))
        m = MS.Missions.__new__(MS.Missions)
        m.f, m.mv, m.log = f, f.mv, f.log
        f.mv.tm = tm
        f.mv.snap = lambda *a, **k: NS(player=NS(x=p["x"], z=p["z"]), cam_yaw=0.0, hostile=lambda r: [])
        f.mv.stick_to = lambda s, x, z, mag: (mag, 0.0)

        def move(sx, sy, p=p, moves=moves):
            if sx:
                sticks.append(sx)
            if moves and sx >= 0.5:                         # a walking stick moves the body 0.25 m toward the chest
                dx, dz = box[0] - p["x"], box[2] - p["z"]
                d = math.hypot(dx, dz)
                p["x"], p["z"] = p["x"] + dx / d * 0.25, p["z"] + dz / d * 0.25
        f.mv.pad.move = move
        f.walk_to = lambda q, nm, tag, **k: "arrived"
        f.alive = lambda: True
        f._settle = lambda *a, **k: None
        f.mv.pad.interact = lambda: None
        sleep, MS.time.sleep = MS.time.sleep, (lambda s: None)
        try:
            MS.Missions._chest(m, CHEST, None, "구역5")
        finally:
            MS.time.sleep = sleep
        d = math.hypot(p["x"] - box[0], p["z"] - box[2])
        nudges = [s for s in sticks if s == MS.CHEST_NUDGE_STICK]
        if want == "reach":
            assert d <= MS.CHEST_REACH_M and nudges, (d, sticks)
        else:
            assert len(nudges) <= 3, sticks                # blocked → stop pushing after 2 pulses with no gain
    print("ok  chest: nudge stick 0.7 walks 1.34 m → ≤ 0.75 m; against collision (no gain) stops after 2 pulses")


def test_zone5_opens_door_before_kills() -> None:
    z = MS.UPPER["zones"][4]
    assert z["after"][0]["chest"].get("door_first")
    tm = Tm(door=False)
    f = make_field(World(player=tuple(z["safe"])))
    m = MS.Missions.__new__(MS.Missions)
    m.f, m.mv, m.log = f, f.mv, f.log
    m.nms = {MS.MAP_B: None}
    f.mv.tm = tm
    order = []
    f.home = None
    f.careful_walk_to = lambda q, nm, tag, **k: order.append(("walk", tag)) or "arrived"
    m._firebomb_ledge = lambda tag: None
    m._loot = lambda nb, tag: None
    m._top_up = lambda nb, tag: True

    def door(st, nb, tag):
        order.append(("door",))
        tm.flags[61010510] = True
        return "open"
    m._open_door = door
    m._pull_to_safe = lambda npc, *a, **k: order.append(("kill", npc)) or "killed"
    m._chest = lambda st, nb, tag: order.append(("chest",)) or "taken"
    r = m.upper_zone(5)
    kinds = [o[0] for o in order]
    assert r == "cleared" and kinds.index("door") < kinds.index("kill") and kinds[-1] == "chest", order
    # door already open → no zone-start door step
    tm2 = Tm(door=True)
    f.mv.tm = tm2
    order.clear()
    m.upper_zone(5)
    assert ("door",) not in order, order
    print("ok  zone 5: shut door → open it (then back to the safe spot) before luring 255000; open door → straight to the kills")


class KTm:
    def __init__(self, humanity=0, items=4, estus=5, bonfire=1012962):
        self.h, self.items, self.estus, self.bonfire = humanity, items, estus, bonfire
        self.quick, self.sel = [201, -1, -1, -1, -1], 201

    def humanity(self):
        return self.h

    def goods_count(self, i):
        return self.items if i == 500 else (self.estus if i == 201 else 0)

    def quick_items(self):
        return self.quick

    def equip_quick_item(self, i):
        self.quick[1] = i
        return 1

    def selected_item(self):
        return self.sel

    def last_bonfire(self):
        return self.bonfire


def kindle_run(tm):
    taps, stood, sat = [], [], []

    def wheel():
        filled = [q for q in tm.quick if q != -1]
        tm.sel = filled[(filled.index(tm.sel) + 1) % len(filled)]

    def press_r():
        if tm.sel == 500:
            tm.h, tm.items = tm.h + 1, tm.items - 1
        else:
            tm.estus -= 1                                  # the 11-01 mistake: use on Estus

    def tap(k):
        taps.append(k)
        if taps[-6:] == ["DOWN", "DOWN", "DOWN", "A", "LEFT", "A"]:
            tm.h -= 1                                      # reverse Hollowing
        elif taps[-5:] == ["DOWN", "DOWN", "A", "LEFT", "A"] and len(taps) != 5 or taps == ["DOWN", "DOWN", "A", "LEFT", "A"]:
            tm.h, tm.estus = tm.h - 1, 10                  # kindle
    import control
    import steam_state
    saved = (kindle._wheel_down, kindle._press_r, kindle.time.sleep, control.focus_game, steam_state.check)
    kindle._wheel_down, kindle._press_r, kindle.time.sleep = wheel, press_r, (lambda s: None)
    control.focus_game, steam_state.check = (lambda: True), (lambda: {"offline": True})
    kindle.ON = True
    try:
        r = kindle.maybe(tm, tap, lambda: stood.append(1) or True, lambda: sat.append(1) or True, log=lambda m: None)
    finally:
        kindle._wheel_down, kindle._press_r, kindle.time.sleep, control.focus_game, steam_state.check = saved
        kindle.ON = False
    return r, taps, stood, sat


def test_kindle_full() -> None:
    tm = KTm()
    r, taps, stood, sat = kindle_run(tm)
    assert tm.estus == 10 and tm.h == 0 and tm.items == 2 and tm.sel == 201, (r, vars(tm))
    assert stood and sat and taps == ["DOWN", "DOWN", "DOWN", "A", "LEFT", "A", "DOWN", "DOWN", "A", "LEFT", "A"], taps
    print(f"ok  kindle: stand, wheel to Humanity, R ×2 (counter 0→2), wheel back to Estus, sit, reverse, kindle → Estus 10 ({r})")


def test_kindle_skips() -> None:
    for tm, why in ((KTm(estus=10), "Estus already 10"), (KTm(bonfire=1022960), "not the Burg bonfire")):
        r, taps, stood, sat = kindle_run(tm)
        assert not taps and not stood, (why, r, taps)
    tm = KTm(items=1)
    r, taps, stood, sat = kindle_run(tm)
    assert tm.estus == 5 and tm.h == 0 and tm.items == 1 and not taps, (r, taps, vars(tm))
    print("ok  kindle: Estus 10 / Firelink → nothing; too few Humanity items → stop before using any")


class LadderNm:
    def __init__(self, d):
        self.d = d

    def ladder_dist(self, *a):
        return self.d

    def find_path(self, *a):
        return []


def test_no_fog_a_by_ladder() -> None:
    for d, want in ((0.1, False), (10.0, True)):
        f = make_field(World(player=(6.9, -4.5, -100.4)))
        f._smash_blocking = lambda *a, **k: False
        f._detour = True
        calls = []
        f.fog_through = lambda q, known=False: calls.append(q) or False
        plan = NS(tag="t", path=[(6.9, -4.5, -100.4), (12.4, -5.7, -96.5), (14.0, -5.7, -96.0)], i=1)
        st = NS(fails=1, doored=set(), smashed=set())
        F.Field._walk_missed(f, plan, st, (12.4, -5.7, -96.5), "stuck", LadderNm(d), None, None)
        assert bool(calls) is want, (d, calls, f.logs)
    nm = navmesh.Navmesh.from_npz(NPZ)
    assert nm.ladder_dist(6.9, -4.5, -100.4) < F.LADDER_NO_A_M and nm.ladder_dist(20.2, -6.0, -103.4) > F.LADDER_NO_A_M
    assert nm.ladder_dist(-49.8, -21.81, -33.2) > F.LADDER_NO_A_M      # the town fog wall keeps its A
    print("ok  ladder: stuck by the zone 5 ladder (NavMesh Ladder face ≤ 2.5 m) → no unknown-fog A; elsewhere A as before")


if __name__ == "__main__":
    test_chest_data_on_navmesh()
    test_chest_opens_shut_door_then_takes()
    test_chest_open_door_no_a()
    test_chest_already_taken()
    test_chest_nudge_walks_in()
    test_zone5_opens_door_before_kills()
    test_kindle_full()
    test_kindle_skips()
    test_no_fog_a_by_ladder()
    print("전부 통과")
