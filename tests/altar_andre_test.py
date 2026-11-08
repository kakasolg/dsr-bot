"""souls/altar_andre offline: start contract, bounded leg handling, bonfire arrival ≠ interaction ≠ confirmed rest.

Fakes only (fake telemetry / field / pad / NavMesh, synthetic route fixtures in a temp dir that is removed right after the
mission object reads it). The route points here are **made-up test geometry, not route data** — data/routes/altar-to-andre.json
does not exist. Buttons are injected as strings, so nothing imports control / vgamepad.

What these tests cannot show: that Field.walk follows a real route or honours done= (the fake does not model ticks), that
fights on the way go well, that the Andre bonfire lights with these A presses, that sitting() / last_bonfire() / menu_open()
behave this way at that bonfire, or anything about the current map. Every test that gets past the start check gives the fake
telemetry a current_map() the real telemetry does not have — they check this module's logic, not the game. The bonfire
state-machine tests turn INTERACT_ENABLED on and add a synthetic "object" to a copy of spots.json; both are off / absent for real.
"""
import json
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from souls import altar_andre as AA  # noqa: E402
from souls import route_fp  # noqa: E402

AUTO = "<fixture: fingerprint of the files build() writes>"

SPOTS = json.loads((ROOT / "data" / "spots.json").read_text(encoding="utf-8"))
START = tuple(SPOTS[AA.START_SPOT]["stand"])
END = tuple(SPOTS[AA.END_SPOT]["stand"])
MID = ((START[0] + END[0]) / 2, (START[1] + END[1]) / 2, (START[2] + END[2]) / 2)   # synthetic
BTN = NS(XUSB_GAMEPAD_A="A", XUSB_GAMEPAD_B="B")


def route(**over):
    R = {"schema": route_fp.SCHEMA, "_source": "synthetic test fixture", "map": AA.MAP,
         "validation": {"traversal": {"status": "validated", "by": "test", "date": "2026-11-03", "evidence": "fixture",
                                      "route_sha256": AUTO},
                        "rest": {"status": "unvalidated"}},
         "requires": [],
         "legs": [{"tag": "a", "mode": "walk", "points": [list(START), list(MID)]},
                  {"tag": "b", "mode": "walk", "points": [list(MID), list(END)]}]}
    R.update(over)
    return R


@contextmanager
def interacting():
    """Bonfire state-machine tests only: allow A (real default False)."""
    AA.INTERACT_ENABLED = True
    try:
        yield
    finally:
        AA.INTERACT_ENABLED = False


class Lock:
    def __init__(self, held=True, path=None):
        self._f = object() if held else None
        self.path = path


class Pad:
    def __init__(self):
        self.calls = []

    def neutral(self, why=None):
        self.calls.append("neutral")

    def sprint(self, on):
        self.calls.append(("sprint", on))

    def guard(self, on):
        self.calls.append(("guard", on))


class World:
    """Player position, foes, clock and the bonfire state the fake telemetry reads."""

    def __init__(self, pos=START, hp=500):
        self.pos, self.hp, self.foes = list(pos), hp, []
        self.menu, self.sit, self.last = False, False, AA.START_BONFIRE
        self.map = AA.MAP
        self.t = 0.0
        self.sit_on_press = None          # sit after this many A presses (None = never)
        self.sit_unknown_on_press = False # the first A makes sitting unreadable (None)
        self.last_after_sit = AA.END_BONFIRE
        self.b_stands = True              # B gets up from the bonfire

    def snap(self, within=5.0):
        p = NS(x=self.pos[0], y=self.pos[1], z=self.pos[2], hp=self.hp)
        foes = self.foes
        return NS(player=p, hostile=lambda r: [c for c in foes if ((c.x - p.x) ** 2 + (c.z - p.z) ** 2) ** 0.5 < r])


class TM:
    def __init__(self, w, has_map=True, has_sit_state=True):
        self.w = w
        if has_map:
            self.current_map = lambda: w.map
        if has_sit_state:
            self.sitting_state = lambda: w.sit          # True / False / None, like dsr_telemetry.sitting_state

    def menu_open(self):
        return self.w.menu

    def sitting(self):
        return bool(self.w.sit)                        # the old reader: unknown reads as False — the mission must not use it

    def last_bonfire(self):
        return self.w.last

    def event_flag(self, flag):
        return True


class Mv:
    def __init__(self, w, tm, pad):
        self.w, self.tm, self.pad, self.presses = w, tm, pad, []

    def snap(self, within=5.0):
        return self.w.snap(within)

    def press(self, button, hold=0.1, gap=0.1):
        self.presses.append(button)
        w = self.w
        if button == "A" and w.sit_unknown_on_press:
            w.sit, w.last = None, w.last_after_sit
        if button == "A" and w.sit_on_press is not None and self.presses.count("A") >= w.sit_on_press:
            w.sit, w.menu = True, True
            w.last = w.last_after_sit
        if button == "B" and w.sit and w.b_stands:
            w.sit, w.menu = False, False


class NM:
    def floor_at(self, x, z, y):
        return (y,)


class Field:
    """walk / walk_to: move the player `step` m toward the goal ('stuck') or onto it ('arrived'), or die, or return `result`.
    Each call takes `walk_s` seconds of the fake clock. Results are ones the real Field returns."""

    def __init__(self, w, mv, step=None, die_on_walk=None, result=None, walk_s=0.0, deny_on_walk=None):
        self.w, self.mv, self.step, self.die_on_walk, self.result, self.walk_s = w, mv, step, die_on_walk, result, walk_s
        self.walks, self.dones, self.ignore_npcs = [], [], {"caller's"}
        self.smash_ok, self.denial, self.smash_seen = True, None, []
        self.deny_on_walk = deny_on_walk  # (n, result): the n-th walk hits a blocking prop under smash_ok False

    def _move(self, goal):
        self.walks.append(tuple(goal))
        self.smash_seen.append(self.smash_ok)
        if self.deny_on_walk is not None and len(self.walks) == self.deny_on_walk[0] and not self.smash_ok:
            self.denial = {"kind": "denied", "op": "smash", "reason": "자동 장애물 부수기 금지 (smash_ok False)",
                           "detail": {"prop": "o1129"}}
            return self.deny_on_walk[1]
        self.w.t += self.walk_s
        if self.die_on_walk is not None and len(self.walks) >= self.die_on_walk:
            self.w.hp = 0
            return "dead"
        if self.result is not None:
            return self.result
        p = self.w.pos
        if self.step is None:
            self.w.pos = list(goal)
            return "arrived"
        dx, dz = goal[0] - p[0], goal[2] - p[2]
        n = (dx * dx + dz * dz) ** 0.5
        k = min(1.0, self.step / n) if n else 0.0
        self.w.pos = [p[0] + dx * k, p[1] + (goal[1] - p[1]) * k, p[2] + dz * k]
        return "stuck"

    def walk(self, path, nm, tag, tol=None, tight=None, mode="walk", done=None):
        self.dones.append(done)
        return self._move(path[-1])

    def walk_to(self, goal, nm, tag, mode="walk", tol=None, done=None):
        self.dones.append(done)
        return self._move(goal)

    def alive(self):
        return self.w.hp > 0

    def safe(self, s):
        return not s.hostile(6.0)


def build(R="default", lock=None, has_map=True, nm="fake", end_object=False, w=None, has_sit_state=True, **field_kw):
    w = w or World()
    tm, pad = TM(w, has_map, has_sit_state), Pad()
    mv = Mv(w, tm, pad)
    f = Field(w, mv, **field_kw)
    events = []

    def sleep(s):
        w.t += s

    R = route() if R == "default" else R
    with tempfile.TemporaryDirectory(prefix="altar_andre_") as d:   # the mission reads route + spots only in __init__
        d = Path(d)
        (d / "routes").mkdir()
        spots = json.loads((ROOT / "data" / "spots.json").read_text(encoding="utf-8"))
        if end_object:
            spots[AA.END_SPOT]["object"] = list(END)               # synthetic — the real spots.json has none
        (d / "spots.json").write_text(json.dumps(spots), encoding="utf-8")
        if R is not None:
            R = stamp(R, json.dumps(spots))
            (d / "routes" / AA.ROUTE).write_text(json.dumps(R), encoding="utf-8")
        m = AA.AltarToAndre(f, NM() if nm == "fake" else nm, d, lock=lock or Lock(), log=lambda *a: None,
                            events=lambda *a, **k: events.append(k), clock=lambda: w.t, sleep=sleep,
                            awake=lambda c: True, buttons=BTN)
    m.events_seen = events
    return m, w, f, mv, pad


def stamp(R, spots_text):
    """AUTO → the fingerprint route_fp computes for this route + spots (what a MoKa validation would record)."""
    t = (R.get("validation") or {}).get("traversal") if isinstance(R.get("validation"), dict) else None
    if not isinstance(t, dict) or t.get("route_sha256") != AUTO:
        return R
    R = json.loads(json.dumps(R))
    try:
        fp = route_fp.parse(json.dumps(R), spots_text, AA.START_SPOT, AA.END_SPOT).fingerprint
    except route_fp.RouteError:
        return R                                           # a malformed fixture keeps AUTO — the mission refuses it anyway
    R["validation"]["traversal"]["route_sha256"] = fp
    return R


def no_input(f, mv, pad):
    assert f.walks == [] and mv.presses == [] and pad.calls == []


def released(f, pad):
    assert pad.calls[-1] == "neutral" and f.ignore_npcs == {"caller's"} and not AA.ACTIVE


# ── rejected starts: no controller input ─────────────────────────────

def test_missing_route_refused():
    m, w, f, mv, pad = build(R=None)
    r = m.run()
    assert r.startswith("refused") and "경로 데이터 없음" in r
    no_input(f, mv, pad)


def test_unvalidated_route_refused():
    R = route(validation={"traversal": {"status": "reviewed", "by": "MoKa", "evidence": "looked at it"}})
    m, w, f, mv, pad = build(R=R)
    r = m.run()
    assert r.startswith("refused") and "이동 경로 검증 안 됨" in r
    no_input(f, mv, pad)


def test_old_flat_validation_refused():
    R = route(validation={"status": "validated", "by": "MoKa", "date": "2026-11-03", "evidence": "x"})
    m, w, f, mv, pad = build(R=R)
    r = m.run()
    assert r.startswith("refused") and "옛 형식" in r and "이동 경로 검증 안 됨" in r   # not read as traversal
    no_input(f, mv, pad)


def test_rest_validated_does_not_stand_in_for_traversal():
    R = route(validation={"traversal": {"status": "reviewed", "by": "MoKa", "evidence": "x"},
                          "rest": {"status": "validated", "by": "MoKa", "evidence": "x"}})
    m, w, f, mv, pad = build(R=R)
    r = m.run()
    assert r.startswith("refused") and "이동 경로 검증 안 됨" in r
    no_input(f, mv, pad)


def test_route_shape_and_unknown_flag_refused():
    R = route(requires=[{"what": "door", "flag": None}])
    R["legs"][0]["points"] = [list(START)]
    m, w, f, mv, pad = build(R=R)
    r = m.run()
    assert r.startswith("refused") and "requires[0].flag: 정수 아님" in r and "점 두 개 이상" in r
    assert m.route is None
    no_input(f, mv, pad)


def test_matching_fingerprint_starts():
    m, w, f, mv, pad = build()
    assert m.problems == [] and m.check().facts["route_sha256"] == m.route.fingerprint
    assert not m.run().startswith("refused")


def test_missing_fingerprint_refused():
    R = route()
    del R["validation"]["traversal"]["route_sha256"]
    m, w, f, mv, pad = build(R=R)
    r = m.run()
    assert r.startswith("refused") and "경로 지문 없음" in r
    no_input(f, mv, pad)


def test_mismatched_fingerprint_refused():
    R = route()
    R["validation"]["traversal"]["route_sha256"] = "0" * 64
    m, w, f, mv, pad = build(R=R)
    r = m.run()
    assert r.startswith("refused") and "경로 지문 다름" in r
    no_input(f, mv, pad)


def stale(change_route=None, change_spots=None):
    """Validate (fingerprint) the fixture, then change route / spots before the mission loads them."""
    spots = json.loads(json.dumps(SPOTS))
    R = stamp(route(), json.dumps(spots))
    if change_route:
        change_route(R)
    if change_spots:
        change_spots(spots)
    with tempfile.TemporaryDirectory(prefix="altar_andre_") as d:
        d = Path(d)
        (d / "routes").mkdir()
        (d / "spots.json").write_text(json.dumps(spots), encoding="utf-8")
        (d / "routes" / AA.ROUTE).write_text(json.dumps(R), encoding="utf-8")
        return AA.load_route(d)


def test_execution_changes_invalidate_validation():
    def pt(R):
        R["legs"][0]["points"][1][0] += 0.01
    def mode(R):
        R["legs"][1]["mode"] = "sprint"
    def ign(R):
        R["legs"][0]["ignore_npcs"] = [123]
    def stand(S):
        S[AA.END_SPOT]["stand"][2] += 0.01
    def heading(S):
        S[AA.END_SPOT]["heading"] = 1.0
    def bid(S):
        S[AA.START_SPOT]["bonfire_id"] += 1
    for kw in ({"change_route": pt}, {"change_route": mode}, {"change_route": ign},
               {"change_spots": stand}, {"change_spots": heading}, {"change_spots": bid}):
        route_, R, problems = stale(**kw)
        assert route_ is not None and any("경로 지문 다름" in q for q in problems), (kw, problems)


def test_metadata_changes_keep_validation():
    def meta(R):
        R["_source"], R["note"], R["review"] = "other recording", "a note", {"by": "MoKa"}
        R["validation"]["rest"] = {"status": "validated", "by": "MoKa", "evidence": "x"}
        R["validation"]["traversal"]["date"] = "2026-11-05"
    def spot_meta(S):
        S[AA.END_SPOT]["note"] = "changed"
        S["darkroot-bonfire"]["note"] = "unused spot"
    route_, R, problems = stale(change_route=meta, change_spots=spot_meta)
    assert problems == [], problems


def test_link_and_map_checks_kept():
    def far(R):
        R["legs"][-1]["points"][-1][0] += AA.LINK_R + 1.0
    route_, R, problems = stale(change_route=far)
    assert any("끝 점이 안드레 화톳불에서 멂" in q for q in problems)
    def other_map(R):
        R["map"] = "m12_00_00_00"
    route_, R, problems = stale(change_route=other_map)
    assert any("≠ route.map" in q for q in problems)    # the spots are on m10_01 — route_fp refuses the pair


def test_files_changed_after_load_do_not_reach_check_or_walks():
    w = World()
    tm, pad = TM(w), Pad()
    mv = Mv(w, tm, pad)
    f = Field(w, mv)
    spots = json.loads(json.dumps(SPOTS))
    with tempfile.TemporaryDirectory(prefix="altar_andre_") as d:
        d = Path(d)
        (d / "routes").mkdir()
        (d / "spots.json").write_text(json.dumps(spots), encoding="utf-8")
        (d / "routes" / AA.ROUTE).write_text(json.dumps(stamp(route(), json.dumps(spots))), encoding="utf-8")
        m = AA.AltarToAndre(f, NM(), d, lock=Lock(), log=lambda *a: None, clock=lambda: w.t, sleep=lambda s: None,
                            awake=lambda c: True, buttons=BTN)
        fp0, goals0 = m.route.fingerprint, [leg.points[-1] for leg in m.route.legs]
        moved = route()                                    # now the files say something else (and aren't validated)
        moved["legs"][0]["points"][1] = [0.0, 0.0, 0.0]
        (d / "routes" / AA.ROUTE).write_text(json.dumps(moved), encoding="utf-8")
        spots[AA.END_SPOT]["stand"] = [0.0, 0.0, 0.0]
        (d / "spots.json").write_text(json.dumps(spots), encoding="utf-8")
        v = m.check()
        r = m.run()
    assert v.ok and v.facts["route_sha256"] == fp0 and not r.startswith("refused"), (v.stop, r)
    assert f.walks[:2] == goals0 and m.end.stand == END, f.walks


def test_missing_optional_spot_data_does_not_block_arrival():
    m, w, f, mv, pad = build()                             # real spots: heading present, no object
    assert m.end.object is None
    r = m.run()
    assert r.startswith("arrived_area") and "object" in r and mv.presses == []


def test_right_bonfire_wrong_place_refused():
    w = World(pos=(START[0] + 30.0, START[1], START[2]))      # last_bonfire is the altar, but standing 30 m off
    m, w, f, mv, pad = build(w=w)
    r = m.run()
    assert "시작 자리 밖" in r and "마지막 화톳불" not in r
    no_input(f, mv, pad)


def test_no_map_telemetry_refused():
    m, w, f, mv, pad = build(has_map=False)
    r = m.run()
    assert "현재 맵 확인 불가" in r
    no_input(f, mv, pad)


def test_no_navmesh_refused():
    m, w, f, mv, pad = build(nm=None)
    r = m.run()
    assert "NavMesh 없음" in r
    no_input(f, mv, pad)


def test_unreadable_menu_and_sitting_refused():
    w = World()
    w.menu, w.sit = None, True
    m, w, f, mv, pad = build(w=w)
    r = m.run()
    assert "메뉴 상태 못 읽음" in r and "앉아 있음" in r
    no_input(f, mv, pad)


def test_unknown_sitting_refused():
    w = World()
    w.sit = None                                           # sitting() would say False here and let it start
    m, w, f, mv, pad = build(w=w)
    r = m.run()
    assert r.startswith("refused") and "앉음 상태 못 읽음" in r
    no_input(f, mv, pad)


def test_missing_sitting_reader_refused():
    m, w, f, mv, pad = build(has_sit_state=False)          # only the old sitting() — not used
    r = m.run()
    assert r.startswith("refused") and "앉음 읽기 없음" in r
    no_input(f, mv, pad)


def test_not_sitting_starts():
    m, w, f, mv, pad = build()                             # sitting_state False: no sitting refusal
    r = m.run()
    assert "앉" not in r.split("—")[0] and not r.startswith("refused"), r


def test_unknown_sitting_after_a_is_not_rest():
    w = World()
    w.sit_unknown_on_press = True                          # last_bonfire even changes — still not a rest
    with interacting():
        m, w, f, mv, pad = build(w=w, end_object=True)
        r = m.run()
    assert r.startswith("rest_unconfirmed") and "앉음 상태 못 읽음" in r
    assert mv.presses == ["A"] and "B" not in mv.presses   # no more A, no B on a state we can't see
    released(f, pad)


def test_smash_denial_hands_off_not_stuck():
    for res in ("denied", "stuck", "arrived"):             # whatever walk returned, the denial wins — no re-walk, no distance check
        m, w, f, mv, pad = build(deny_on_walk=(1, res))
        r = m.run()
        assert r.startswith("handoff") and "거부됨 (smash)" in r, (res, r)
        assert len(f.walks) == 1 and mv.presses == [] and f.smash_seen == [False], (res, f.walks)
        assert f.smash_ok is True and f.denial["op"] == "smash"   # opt-in undone, the denial kept as evidence
        released(f, pad)


def test_smash_off_for_every_walk_of_the_mission():
    m, w, f, mv, pad = build(step=12.0)                    # several walk / walk_to calls
    m.run()
    assert len(f.smash_seen) > 2 and not any(f.smash_seen) and f.smash_ok is True


def test_leftover_denial_refused():
    m, w, f, mv, pad = build()
    f.denial = {"kind": "denied", "op": "smash", "reason": "earlier", "detail": {}}
    r = m.run()
    assert r.startswith("refused") and "앞선 거부" in r
    no_input(f, mv, pad)


def test_lock_not_held_wrong_lock_or_other_mission_refused():
    m, w, f, mv, pad = build(lock=Lock(held=False))
    assert "BotLock" in m.run()
    no_input(f, mv, pad)
    m, w, f, mv, pad = build(lock=Lock(path=AA.botlock.LOCK_PATH.parent / "pad.lock"))
    assert "봇 잠금이 아님" in m.run()
    no_input(f, mv, pad)
    AA.ACTIVE.append("other")
    try:
        m, w, f, mv, pad = build()
        assert "다른 미션 진행 중" in m.run()
        no_input(f, mv, pad)
        assert AA.ACTIVE == ["other"]                      # a refusal leaves the other owner alone
    finally:
        AA.ACTIVE.clear()


def test_dead_at_start_refused():
    m, w, f, mv, pad = build(w=World(hp=0))
    assert "HP 0" in m.run()
    no_input(f, mv, pad)


# ── bounded traversal ─────────────────────────────

def test_death_returns_died_and_releases():
    m, w, f, mv, pad = build(die_on_walk=1)
    assert m.run() == "died"
    assert len(f.walks) == 1 and mv.presses == []
    released(f, pad)


def test_no_estus_hands_off():
    m, w, f, mv, pad = build(result="no_estus")
    r = m.run()
    assert r.startswith("handoff") and "걷기 결과 no_estus" in r
    assert len(f.walks) == 1 and mv.presses == []
    released(f, pad)


def test_deadline_hands_off_and_is_passed_into_walks():
    m, w, f, mv, pad = build(step=1.2, walk_s=AA.MISSION_MAX_S + 1.0)
    r = m.run()
    assert r.startswith("handoff") and "시간 넘음" in r
    assert len(f.walks) == 1 and mv.presses == []
    assert f.dones and all(callable(d) for d in f.dones) and f.dones[0](None)   # past the deadline → done() true
    released(f, pad)


def test_stalled_hands_off_without_retry():
    m, w, f, mv, pad = build(step=0.0)
    r = m.run()
    assert r.startswith("handoff") and "진행 없음" in r and "원인 미확정" not in r
    assert len(f.walks) == 1 and mv.presses == []
    released(f, pad)


def test_recovery_budget_exhausted():
    m, w, f, mv, pad = build(step=1.2)                     # gets closer each time, never arrives (leg a is ~70 m)
    r = m.run()
    assert r.startswith("handoff") and "복구" in r
    assert len(f.walks) == 1 + AA.RECOVERY_BUDGET and mv.presses == []
    assert w.t == 0.0 and all(callable(d) for d in f.dones)
    released(f, pad)


def test_no_progress_with_foe_near_is_not_classified():
    w = World()
    w.foes = [NS(x=START[0] + 3.0, y=START[1], z=START[2], hp=300, npc_param=999999, ptr=7, anim=3000)]
    m, w, f, mv, pad = build(step=0.0, w=w)
    r = m.run()
    assert r.startswith("handoff") and "원인 미확정" in r and "999999" in r and "지원 안 되는" not in r
    assert len(f.walks) == 1 and mv.presses == []
    ev = [e for e in m.events_seen if e.get("what") == "handoff"][-1]
    assert ev["foes"][0]["npc"] == 999999 and ev["foes"][0]["ptr"] == 7 and ev["walk"] == "stuck"
    released(f, pad)


# ── bonfire: arrival ≠ interaction ≠ confirmed rest ─────────────────────────────

def test_interaction_blocked_by_default():
    w = World()
    w.sit_on_press = 1
    m, w, f, mv, pad = build(w=w)                          # real defaults: INTERACT_ENABLED False, no object
    r = m.run()
    assert r.startswith("arrived_area") and "상호작용 막힘" in r and "object" in r
    assert mv.presses == [] and w.last == AA.START_BONFIRE
    released(f, pad)


def test_traversal_validated_rest_unvalidated_starts_and_stops_at_area():
    m, w, f, mv, pad = build()                             # fixture: traversal validated, rest unvalidated
    r = m.run()
    assert r.startswith("arrived_area") and mv.presses == []
    start = [e for e in m.events_seen if e.get("what") == "start"][0]
    assert start["ok"] and "'rest': 'unvalidated'" in start["facts"]["validation"]


def test_arrived_but_never_sat():
    with interacting():
        m, w, f, mv, pad = build(end_object=True)          # sit_on_press None: A does nothing visible
        r = m.run()
    assert r.startswith("rest_unconfirmed") and "앉음 안 보임" in r
    assert mv.presses == ["A"] * AA.INTERACT_MAX           # no B when never seated
    released(f, pad)


def test_sat_but_last_bonfire_unchanged():
    w = World()
    w.sit_on_press, w.last_after_sit = 2, AA.START_BONFIRE
    with interacting():
        m, w, f, mv, pad = build(w=w, end_object=True)
        r = m.run()
    assert r.startswith("rest_unconfirmed") and "앉음 보임" in r
    assert mv.presses.count("A") == 2 and "B" in mv.presses and not w.sit


def test_unexpected_menu_before_a():
    w = World()
    with interacting():
        m, w, f, mv, pad = build(w=w, end_object=True)
        orig = f._move

        def move_then_menu(goal):
            r = orig(goal)
            if tuple(goal) == END:
                w.menu = True                              # a menu opens on arrival, not seated
            return r

        f._move = move_then_menu
        r = m.run()
    assert r.startswith("handoff") and "예상 밖 메뉴" in r and mv.presses == []


def test_foe_at_bonfire_no_press():
    w = World()
    w.foes = [NS(x=END[0] + 2.0, y=END[1], z=END[2], hp=300, npc_param=255000)]
    with interacting():
        m, w, f, mv, pad = build(w=w, end_object=True)
        r = m.run()
    assert r.startswith("handoff") and "화톳불 앞 적" in r and mv.presses == []


def test_confirmed_rest():
    w = World()
    w.sit_on_press = 2                                     # 1st A lights, 2nd A sits (light_burg_bonfire pattern)
    with interacting():
        m, w, f, mv, pad = build(w=w, end_object=True)
        r = m.run()
    assert r == "rested"
    assert mv.presses == ["A", "A", "B"] and not w.sit and w.last == AA.END_BONFIRE
    released(f, pad)


def test_rested_but_still_seated():
    w = World()
    w.sit_on_press, w.b_stands = 1, False
    with interacting():
        m, w, f, mv, pad = build(w=w, end_object=True)
        r = m.run()
    assert r.startswith("rested_seated") and mv.presses.count("B") == AA.STAND_TRIES


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
