"""souls/asylum 오프라인 테스트 — 구간 자르기, 방향 계산, 단계 실행 순서·멈춤, 사다리 오르기 판정. 게임 없음.

  python tests/asylum_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World, make_field
from souls import asylum as A

A.control.focus_game = lambda: True      # ctypes.windll (Windows only) — steps call it before pressing / menu keys

STEPS = [
    {"type": "walk", "pts": [[0, 0, 0]]},
    {"type": "menu", "keys": ["START", "START"], "label": "감방"},          # intro skip — must be dropped
    {"type": "press", "pos": [1, 0, 0], "hd": 0.0, "n": 2, "label": "감방: 열쇠"},
    {"type": "menu", "keys": ["START", "RIGHT"], "label": "감방"},          # after a press — kept
    {"type": "walk", "pts": [[1, 0, 0], [5, 0, 0]]},
    {"type": "press", "pos": [5, 0, 0], "hd": 1.0, "n": 1, "label": "첫 화톳불 (1812960) 불 붙이기"},
    {"type": "walk", "pts": [[5, 0, 0], [9, 0, 0]]},
    {"type": "press", "pos": [9, 0, 0], "hd": 1.0, "n": 1, "label": "큰 방 문"},
]


def test_segment() -> None:
    s1 = A.segment(STEPS, 1)
    assert [x["type"] for x in s1] == ["walk", "press", "menu", "walk", "press"], s1
    assert s1[-1]["label"].startswith("첫 화톳불")
    try:
        A.segment(STEPS, 2)
        raise AssertionError("segment 2 has no end label yet")
    except (KeyError, ValueError):
        pass
    real = A.segment(A.load(), 1)
    assert real[-1]["label"].startswith("첫 화톳불") and not any(x["type"] == "menu" for x in real), real
    assert any(x["type"] == "climb" for x in real), "segment 1 climbs the ladder"
    print(f"ok  segment 1 = cell → ladder → first bonfire ({len(real)} steps), intro menu dropped")
    s2 = A.segment(A.load(), 2)
    assert s2[1]["label"].startswith("큰 방 문") and s2[-1]["type"] == "menu" and "배틀 액스" in s2[-1]["label"], (s2[0], s2[-1])
    assert sum(1 for x in s2 if x["type"] == "menu") == 2, "shield and Battle Axe menus"
    print(f"ok  segment 2 = big door → flee → second bonfire → shield → Battle Axe menu ({len(s2)} steps)")


def test_heading() -> None:
    assert abs(A.heading_off(0.1, -0.1) + math.degrees(0.2)) < 1e-6
    assert abs(abs(A.heading_off(3.1, -3.1)) - math.degrees(2 * math.pi - 6.2)) < 1e-6   # wraps around ±π
    dx, dz = A.heading_vec(0.0)                                          # world yaw = heading + π → facing −z
    assert abs(dx) < 1e-9 and abs(dz + 1.0) < 1e-9, (dx, dz)
    print("ok  heading_off wraps, heading_vec(0) faces −z (world yaw = heading + π)")


def test_run_order_and_stop() -> None:
    f = make_field(World(player=(0.0, -49.4, 0.0)))
    f.alive = lambda: True
    a = A.Asylum(f, nm=None, log=f.log)
    done = []
    for kind in ("walk", "press", "menu", "climb", "fight", "mark", "jump"):
        setattr(a, "_" + kind, (lambda k: lambda st, tag: done.append(k) or ("fail" if st.get("x") else "ok"))(kind))
    r = a.run([{"type": "walk"}, {"type": "press"}, {"type": "climb", "x": 1, "label": "사다리"}, {"type": "walk"}])
    assert done == ["walk", "press", "climb"] and r.startswith("fail at 3 climb 사다리"), (done, r)
    print(f"ok  steps run in order, stops at the first failure → '{r}'")


def test_flee_and_gear() -> None:
    f = make_field(World(player=(0.0, -49.4, 0.0)))
    f.alive = lambda: True
    a = A.Asylum(f, nm=None, log=f.log)
    seen = []
    a._walk = lambda st, tag: seen.append((st.get("run"), set(f.ignore_npcs))) or "ok"
    a._press = lambda st, tag: seen.append(("press", set(f.ignore_npcs))) or "ok"
    a.run([{"type": "walk"}, {"type": "press", "label": "큰 방 문 x"}, {"type": "walk"},
           {"type": "press", "label": "도망친 방 화톳불 x"}, {"type": "walk"}])
    assert seen == [(None, set()), ("press", {A.DEMON}), (True, {A.DEMON}), ("press", {A.DEMON}), (None, set())], seen
    eq = {"왼손1": 900000}
    a.tm = type("T", (), {"equipment": lambda self: dict(eq)})()
    a.mv = type("M", (), {"press": lambda self, b, hold=0.1, gap=0.1: eq.update({"왼손1": 1462000})})()
    sleep = A.time.sleep
    A.time.sleep = lambda s: None
    try:
        assert a._menu({"keys": ["START", "A"], "label": "시작 장비 줍기 1: 방패 + 메뉴 장착"}, "t") == "ok"
        eq["오른손1"] = 212000
        a.mv = type("M", (), {"press": lambda self, b, hold=0.1, gap=0.1: None})()
        assert a._menu({"keys": ["START"], "label": "시작 장비 줍기 2: 배틀 액스"}, "t") == "fail"
    finally:
        A.time.sleep = sleep
    print("ok  fleeing: sprint + demon ignored from the big door to the second bonfire; gear menus checked (shield ok, axe not equipped → fail)")


def test_menu_waits_for_screen() -> None:
    """START / A / B wait for the memory screen value to change, then MENU_SETTLE; a START that opens nothing is pressed again (P-40)."""
    f = make_field(World(player=(0.0, -49.4, 0.0)))
    a = A.Asylum(f, nm=None, log=f.log)
    scr = {"v": 1, "swallow": 1}
    log = []

    class Pm:
        def read_uint(self, addr):
            return scr["v"]

    def press(self, b, hold=0.1, gap=0.1):
        name = next(k for k, v in A.BTN.items() if v == b)
        log.append(("press", name))
        if name == "START" and scr["swallow"]:
            scr["swallow"] -= 1                          # first START swallowed
        elif name in ("START", "A"):
            scr["v"] += 1
            if name == "A":
                eq["왼손1"] = 1462000
    eq = {"왼손1": 900000}
    a.tm = type("T", (), {"pm": Pm(), "base": 0, "equipment": lambda self: dict(eq)})()
    a.mv = type("M", (), {"press": press})()
    sleep, clock = A.time.sleep, A.time.time
    now = [0.0]
    A.time.sleep = lambda s: (log.append(("sleep", round(s, 2))) if s >= 0.1 else None, now.__setitem__(0, now[0] + s))
    A.time.time = lambda: now[0]
    try:
        assert a._menu({"keys": ["START", "RIGHT", "A"], "dt": [0, 0.3, 0.3], "label": "메뉴 시험"}, "t") == "ok"
    finally:
        A.time.sleep, A.time.time = sleep, clock
    presses = [x[1] for x in log if x[0] == "press"]
    assert presses == ["START", "START", "RIGHT", "A"], presses
    settles = [x[1] for x in log if x[0] == "sleep" and x[1] >= A.MENU_SETTLE]
    assert len(settles) >= 2, log                        # after the START that opened the menu and after A
    print("ok  menu: swallowed START pressed again; START / A wait for the screen to change + settle")


class FakeMenu:
    """The equipment menu as seen on 10-03: START → items, RIGHT → equipment tab, A → equipment screen on 오른손1,
    DOWN → next slot, A → that slot's list with the cursor at `start` (an item name, or the one held), DOWN wraps, A equips
    (an item held in the other hand swaps), B goes back one screen."""
    ROWS = ["오른손1", "왼손1"]

    def __init__(self, eq, lists, start):
        self.eq, self.lists, self.start = eq, lists, start
        self.state, self.row, self.cur, self.opens = "world", 0, 0, 0

    def key(self, k):
        s = self.state
        if s == "world" and k == "START":
            self.state = "items"
        elif s == "items" and k == "RIGHT":
            self.state = "tab"
        elif s == "tab" and k == "A":
            self.state, self.row = "screen", 0
        elif s == "screen" and k == "DOWN":
            self.row = (self.row + 1) % len(self.ROWS)
        elif s == "screen" and k == "A":
            items = self.lists[self.ROWS[self.row]]
            first = self.start.pop(0) if self.start else self.eq[self.ROWS[self.row]]
            self.state, self.cur, self.opens = "list", items.index(first) if first in items else 0, self.opens + 1
        elif s == "list" and k == "DOWN":
            self.cur = (self.cur + 1) % len(self.lists[self.ROWS[self.row]])
        elif s == "list" and k == "A":
            slot, it = self.ROWS[self.row], self.lists[self.ROWS[self.row]][self.cur]
            other = next((o for o in self.ROWS if o != slot and self.eq[o] == it), None)
            if other:
                self.eq[other] = 900000
            self.eq[slot], self.state = it, "screen"
        elif k == "B":
            self.state = {"list": "screen", "screen": "tab", "tab": "items", "items": "world"}.get(s, s)

    def screen(self):
        return {"world": 1, "items": 2, "tab": 2, "screen": 3, "list": 4}[self.state]


def test_equip_closed_loop() -> None:
    """Gear menus pick by result: whichever item the list opens on, the shield ends up in 왼손1 and the menu is closed (P-40)."""
    for start, want_opens in ((212000, 2), (1462000, 1)):
        f = make_field(World(player=(0.0, -49.4, 0.0)))
        a = A.Asylum(f, nm=None, log=f.log)
        eq = {"오른손1": 212000, "왼손1": 900000}
        m = FakeMenu(eq, {"오른손1": [212000, 1462000], "왼손1": [212000, 1462000]}, [start])
        names = {v: k for k, v in A.BTN.items()}
        a.mv = type("M", (), {"press": lambda self, b, hold=0.1, gap=0.1: m.key(names[b])})()
        a.tm = type("T", (), {"equipment": lambda self: dict(eq), "menu_open": lambda self: m.state != "world",
                              "pm": type("P", (), {"read_uint": lambda self, addr: m.screen()})(), "base": 0})()
        sleep = A.time.sleep
        A.time.sleep = lambda s: None
        try:
            r = a._menu({"keys": ["START", "RIGHT", "A", "DOWN", "A", "DOWN", "A", "B", "B", "B", "B"],
                         "label": "시작 장비 줍기 1: 방패 + 메뉴 장착"}, "t")
        finally:
            A.time.sleep = sleep
        assert r == "ok" and eq["왼손1"] == 1462000 and m.state == "world", (start, r, eq, m.state)
        assert m.opens == want_opens, (start, m.opens)
    # the axe: the right-hand list also holds the shield — stepping through it takes the shield out of 왼손1 → equipped again
    f = make_field(World(player=(0.0, -49.4, 0.0)))
    a = A.Asylum(f, nm=None, log=f.log)
    eq = {"오른손1": 212000, "왼손1": 1462000}
    m = FakeMenu(eq, {"오른손1": [212000, 1462000, 701000], "왼손1": [212000, 1462000, 701000]}, [])
    names = {v: k for k, v in A.BTN.items()}
    a.mv = type("M", (), {"press": lambda self, b, hold=0.1, gap=0.1: m.key(names[b])})()
    a.tm = type("T", (), {"equipment": lambda self: dict(eq), "menu_open": lambda self: m.state != "world",
                          "pm": type("P", (), {"read_uint": lambda self, addr: m.screen()})(), "base": 0})()
    sleep = A.time.sleep
    A.time.sleep = lambda s: None
    try:
        r = a._menu({"keys": ["START", "RIGHT", "A", "A", "DOWN", "A", "B", "B", "A"], "label": "시작 장비 줍기 2: 배틀 액스 + 메뉴"}, "t")
    finally:
        A.time.sleep = sleep
    assert r == "ok" and eq == {"오른손1": 701000, "왼손1": 1462000} and m.state == "world", (r, eq, m.state)
    assert any("왼손1 빠짐" in l for l in f.logs), f.logs[-4:]
    print("ok  gear menu: list opening on the hilt or on the shield → shield in 왼손1, menu closed; axe pass that knocks the shield out re-equips it")


def test_guard_walk_with_shield() -> None:
    """Shield in the left hand → walks go with the guard up; fleeing still sprints; no shield (or unreadable) → plain walk."""
    f = make_field(World(player=(0.0, -49.4, 0.0)))
    a = A.Asylum(f, nm=None, log=f.log)
    modes = []
    f.walk = lambda pts, nm, tag, mode="walk", **k: modes.append(mode) or "ok"
    eq = {"왼손1": 900000}
    a.tm = type("T", (), {"equipment": lambda self: dict(eq)})()
    st = {"type": "walk", "pts": [[0, -49.4, 0], [1, -49.4, 0]]}
    a._walk(st, "t")
    eq["왼손1"] = 1462000
    a._walk(st, "t")
    a._walk(dict(st, run=True), "t")
    a.tm = type("T", (), {"equipment": lambda self: 1 / 0})()
    a._walk(st, "t")
    assert modes == ["walk", "guard", "sprint", "walk"], modes
    print("ok  walks: guard up once the shield is on, sprint while fleeing, plain walk without a shield")


def test_rush_to_axe() -> None:
    """Shield on, no Battle Axe yet → walks sprint and fight nobody; once the axe is in the right hand → guard walk, fights again."""
    f = make_field(World(player=(0.0, -49.4, 0.0)))
    f.alive = lambda: True
    a = A.Asylum(f, nm=None, log=f.log)
    eq = {"왼손1": 1462000, "오른손1": 212000}
    a.tm = type("T", (), {"equipment": lambda self: dict(eq)})()
    seen = []
    f.walk = lambda pts, nm, tag, mode="walk", **k: seen.append((mode, 250021 in f.ignore_npcs)) or "ok"
    a._press = lambda st, tag: eq.update({"오른손1": 701000}) or "ok"
    walk = {"type": "walk", "pts": [[0, -49.4, 0], [1, -49.4, 0]]}
    a.run([walk, {"type": "press", "label": "시작 장비 줍기 2: 배틀 액스"}, walk])
    assert seen == [("sprint", True), ("guard", False)], seen
    print("ok  shield but no axe: sprint, fight nobody; axe in hand: guard walk, fights again")


def test_keeps_human_pause() -> None:
    f = make_field(World(player=(0.0, -49.4, 0.0)))
    f.alive = lambda: True
    a = A.Asylum(f, nm=None, log=f.log)
    a._press = a._menu = a._walk = lambda st, tag: "ok"
    waits = []
    sleep = A.time.sleep
    A.time.sleep = lambda s: waits.append(round(s, 1))
    try:
        a.run([{"type": "press", "pos": [0, 0, 0], "t": 212.3}, {"type": "walk", "pts": [[0, 0, 0]]},
               {"type": "press", "pos": [0, 0, 0], "t": 215.8},                      # pickup → dismiss: human waited 3.5 s
               {"type": "menu", "pos": [0, 0, 0], "t": 219.2, "keys": ["START"], "dt": [0.0]},
               {"type": "walk", "pts": [[0, 0, 0], [9, 0, 0]]},
               {"type": "press", "pos": [9, 0, 0], "t": 230.0}])                     # after a real walk: no wait
    finally:
        A.time.sleep = sleep
    assert waits[:2] == [3.5, 3.4], waits
    assert len(waits) == 2, waits
    print(f"ok  presses/menu at the same spot keep the human's pauses {waits}; not after a real walk")


def test_ready_and_last_stand() -> None:
    w = World(player=(0.0, -49.4, 0.0), hp=152)
    w.player.max_hp = 616
    f = make_field(w)
    f.estus_left = lambda: 0
    a = A.Asylum(f, nm=None, log=f.log)
    assert a.ready() == "HP 152/616, 에스트 없음", a.ready()
    f.estus_left = lambda: 3
    assert a.ready() is None
    w.add(2, 0x1018, 250022, (1.5, -49.4, 0.0), anim=3000)                # awake, swinging, close
    w.add(3, 0x1019, 250021, (3.0, -49.4, 0.0), anim=-1)                  # standing still — not engaged
    a._walk = lambda st, tag: "fail"
    r = a.run([{"type": "walk", "pts": [[0, 0, 0], [5, 0, 0]]}])
    assert r.startswith("fail") and [x["ptr"] for x in f.fights] == [2], (r, f.fights)
    print("ok  won't start at 152/616 without Estus; a failing step fights the awake foe next to us before stopping")


def test_resume_and_segments() -> None:
    allst = A.load()
    assert A.segment(allst, 4)[-1]["label"].startswith("위층 기사 뒤"), "segment 4 stops before the upper fog"
    s5 = A.segment(allst, 5)
    assert s5[-1]["type"] == "jump" and any(x.get("label", "").startswith(A.PLUNGE_AT) for x in s5), s5[-1]
    here = (33.76, 193.15, -25.27)                                        # respawned at the second bonfire
    j, cut = A.resume(A.segment(allst, 2), here)
    assert cut[0]["type"] == "press" and cut[0]["label"].startswith("도망친 방 화톳불"), cut[0]
    steps = [{"type": "walk", "pts": [[0, 0, 0], [5, 0, 0], [10, 0, 0]]}, {"type": "press", "pos": [20, 0, 0]}]
    j, cut = A.resume(steps, (6.0, 0.0, 0.0))
    assert j == 0 and cut[0]["pts"] == [[5, 0, 0], [10, 0, 0]], cut
    print("ok  segment 4 ends before the upper fog, 5 runs to the crow; resume from the second bonfire / mid-walk")


def test_two_hand() -> None:
    f = make_field(World(player=(0.0, -49.4, 0.0)))
    a = A.Asylum(f, nm=None, log=f.log)
    g = {"v": 1, "toggles": 0}
    a.tm = type("T", (), {"grip": lambda self: g["v"]})()
    a.pad = type("P", (), {"two_hand_right": lambda self: g.update(v=3, toggles=g["toggles"] + 1)})()
    sleep = A.time.sleep
    A.time.sleep = lambda s: None
    try:
        assert a._two_hand("t") and g["toggles"] == 1 and f.grip_want == A.TWO_HAND
        assert a._two_hand("t") and g["toggles"] == 1                     # already two-handed: no toggle (it would go back to one hand)
    finally:
        A.time.sleep = sleep
    print("ok  two hands before the plunge (one toggle, none when already two-handed), kept for the duel via grip_want")


def test_fog_center_used() -> None:
    f = make_field(World(player=(0.0, -49.4, 0.0)))
    f.alive = lambda: True
    heals = []
    f.heal = lambda frac=0.7, sips=3: heals.append(frac)                  # topped up before the boss room
    a = A.Asylum(f, nm=None, log=f.log)
    got = []
    a._fog = lambda center, beyond, tag: got.append((center, beyond)) or "ok"
    a._press = lambda st, tag: got.append("press") or "ok"
    flags = []
    a._plunge = lambda tag: flags.append((f.esc.quit_ok, f.esc.nudge_ok)) or "ok"
    a._demon = lambda tag: flags.append((f.esc.quit_ok, f.esc.nudge_ok)) or "fail"   # stop after the boss
    a._walk = lambda st, tag: "ok"
    r = a.run([{"type": "press", "label": A.PLUNGE_AT + " x", "pos": [4.18, 210.1, -34.8]},
               {"type": "walk", "pts": [[3.6, 210.1, -33.0], [3.64, 210.11, -32.68]]}])
    assert got == [(A.FOG_CENTER[A.PLUNGE_AT], [3.64, 210.11, -32.68])], got
    assert heals == [0.9], heals
    assert flags == [(False, False), (False, False)] and f.esc.quit_ok is True and f.esc.nudge_ok is True, (flags, f.esc.quit_ok)
    print("ok  the demon's upper fog goes through _fog at the door's center (not the recorded press spot), facing the next walk's end")


class DemonMv:
    """Moves for the demon fight: records light swings and stick targets; the demon dies after `lethal` swings."""
    def __init__(self, world, lethal=3):
        self.w, self.lethal, self.lights, self.moves = world, lethal, [], []
        self.guard_ok = True
        self.pad = self
        self.drinks = 0

    def snap(self, within=40.0):
        return self.w.snapshot(within)

    def face(self, s, c, deg=20.0):
        return True

    def light(self, s, c, n=1, sp_second=40):
        from souls import moves as M
        self.lights.append((round(M.horiz(s.player, c), 2), self.guard_ok))
        if len(self.lights) >= self.lethal:
            self.w.chars[c.ptr].hp = 0
        return M.Hit("light", presses=1, dmg=101)

    def stick_to(self, s, x, z, scale=1.0):
        self.moves.append((round(x, 2), round(z, 2)))
        return (0.0, 0.0)

    def move(self, x, y): pass
    def sprint(self, on): pass
    def neutral(self): pass

    def drink(self, safe):
        self.drinks += 1
        return {"ok": True}


def _demon_world(pos, heading, anim=-1, me=(0.0, 198.0, 0.0), hp=616):
    w = World(player=me, hp=hp)
    w.player.max_hp = 616
    w.add(9, 0x2000, A.DEMON, pos, hp=194, max_hp=813, anim=anim)
    w.chars[9].heading = heading
    return w


def test_demon_fight() -> None:
    sleep = A.time.sleep
    A.time.sleep = lambda s: None
    try:
        # behind it (demon faces −z at heading 0; we are at +z), 2.5 m → hit and run, no guard, until it dies
        w = _demon_world((0.0, 198.0, -2.5), 0.0)
        f = make_field(w); f.alive = lambda: True
        a = A.Asylum(f, nm=None, log=f.log)
        a.mv = DemonMv(w, lethal=1); a.pad = a.mv
        assert a._demon("t") == "ok" and len(a.mv.lights) == 1 and not a.mv.lights[0][1], a.mv.lights
        assert a.mv.guard_ok is True                                         # guard setting restored afterwards
        # right in front of it (it faces us, we're at −z): circle wide toward its back, 45° per tick, at DEMON_WIDE_R
        w = _demon_world((0.0, 198.0, 2.5), 0.0)
        f = make_field(w)
        a = A.Asylum(f, nm=None, log=f.log)
        a.mv = DemonMv(w); a.pad = a.mv
        a._demon_move(w.snapshot(), w.chars[9], "in", A.DEMON_IN_R)
        tx, tz = a.mv.moves[-1]
        assert abs(math.hypot(tx, tz - 2.5) - A.DEMON_WIDE_R) < 0.05, (tx, tz)
        assert abs(abs(math.degrees(math.atan2(tx, tz - 2.5))) - 135.0) < 1.0, (tx, tz)   # from −z (180°) 45° round
        # already behind (we at +z of a demon facing −z... i.e. demon at −2.5 facing −z): go in right behind at DEMON_IN_R
        w = _demon_world((0.0, 198.0, -2.5), 0.0, me=(0.5, 198.0, 3.0))
        a.mv = DemonMv(w); a.pad = a.mv
        a._demon_move(w.snapshot(), w.chars[9], "in", A.DEMON_IN_R)
        tx, tz = a.mv.moves[-1]
        assert abs(tx) < 0.05 and abs(tz - (-2.5 + A.DEMON_IN_R)) < 0.05, (tx, tz)
        # butt slam / after a swing → straight out
        a._demon_move(w.snapshot(), w.chars[9], "out", A.DEMON_SLAM_R + 1.0)
        tx, tz = a.mv.moves[-1]
        assert math.hypot(tx, tz + 2.5) > A.DEMON_SLAM_R, (tx, tz)
    finally:
        A.time.sleep = sleep
    print("ok  demon: hit and run from behind with no guard; in front → circles wide (5.5 m, 45°/tick) toward its back; behind → in to 2.6 m")


class ClimbMv:
    """Snapshots whose y rises while the stick is pushed up."""
    def __init__(self, world, rate):
        self.w, self.rate = world, rate
        self.pushing = False
        self.pad = self
        self.tm = None
        self.presses = 0

    def move(self, x, y):
        self.pushing = y > 0.5

    def neutral(self):
        self.pushing = False

    def snap(self, within=3.0):
        if self.pushing:
            self.w.player.y += self.rate
        return self.w.snapshot(within)

    def press(self, button, hold=0.1, gap=0.1):
        self.presses += 1


def test_climb() -> None:
    A.CLIMB_S = 4.0
    import time as _t
    sleep = A.time.sleep
    A.time.sleep = lambda s: None                                        # no real waiting; loop is bounded by CLIMB_S on wall time
    try:
        for rate, want in ((0.05, "ok"), (0.0, "fail")):
            w = World(player=(0.0, 190.5, 0.0))
            f = make_field(w)
            a = A.Asylum(f, nm=None, log=f.log)
            a.mv = ClimbMv(w, rate)
            a.pad = a.mv
            t0 = _t.time()
            r = a._climb({"from": [0, 190.5, 0], "to": [0, 195.6, 0]}, "t")
            assert r == want, (rate, r, f.logs[-2:])
            if want == "fail":
                assert a.mv.presses == 1, a.mv.presses                   # one A retry when it doesn't start climbing
    finally:
        A.time.sleep = sleep
    print("ok  ladder: climbs to the top → ok; y never rises → one A retry, then fail")


if __name__ == "__main__":
    test_segment()
    test_heading()
    test_run_order_and_stop()
    test_flee_and_gear()
    test_menu_waits_for_screen()
    test_equip_closed_loop()
    test_guard_walk_with_shield()
    test_rush_to_axe()
    test_keeps_human_pause()
    test_ready_and_last_stand()
    test_resume_and_segments()
    test_two_hand()
    test_fog_center_used()
    test_demon_fight()
    test_climb()
    print("전부 통과")
