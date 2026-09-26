"""Patch C 오프라인 테스트 — 제자리 고수 중 스태미나 안전: 조용하면 방패 내림, 스태미나 모자란 접촉은 제자리 방어만,
접촉 싸움은 안전 구역·처음 신원에 묶임, 끌어오기 막음 해제는 히스테리시스.

  python field_hold_test.py
"""
from __future__ import annotations

import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World, make_field
from souls import duel as D
from souls import field as F

SPAWN2 = (-23.4, -49.67, 16.15)
SPOT = (-30.35, -49.43, 27.91)
LA = {"spot": SPOT, "min": 13.0, "max": 15.0, "hold": True}
T2 = {"npc": 255010, "pos": list(SPAWN2), "label": 2, "lure": True, "lure_at": LA}

F.HOLD_WAIT = 0.05
F.DEFEND_SLICE = 0.05


def at(dx=0.0, dy=0.0, dz=0.0):
    return (SPOT[0] + dx, SPOT[1] + dy, SPOT[2] + dz)


def base(sp=106, player=SPOT):
    w = World(player=player, sp=sp)
    w.add(2, 0x1018, 255010, SPAWN2, hp=85, max_hp=85)
    return w


def moves(f):
    return [c for c in f.mv.pad.calls if c[0] == "move"]


def test_low_stamina_threat_restricted() -> None:
    """C1·C2·C3: 스태미나 20 에 2.5 m 가만히 선 놈 — fight() 없음, 다가가지 않음, 그놈이 있는 동안 끌어오기 없음."""
    w = base(sp=20)
    f = make_field(w)
    f.lure_result = "too_close"
    lure_t, state = [], {"defends": 0, "gone_t": None}

    def lure(ptr, spawn, nm, tag, arena=None, lure_at=None):
        lure_t.append(time.time())
        if len(lure_t) == 1:
            w.add(3, 0x1013, 254000, at(dx=2.5))       # 첫 끌어오기 뒤 붙은 놈 (애니 -1, 안 '오는 놈')
        return "too_close"
    f.lure = lure
    orig = F.Field._defend_in_place

    def defend(ptr, nm):
        state["defends"] += 1
        assert f.reflex.bs_attack is True             # 부르기 전 원래 값
        r = orig(f, ptr, nm)
        assert f.reflex.bs_attack is True             # 끝나면 되돌림
        if state["defends"] == 5:
            del w.chars[3]
            state["gone_t"] = time.time()
        return r
    f._defend_in_place = defend
    r = f.clear([dict(T2)], nm=None, lure=True)
    assert r == "partial deferred_unreachable #2", r
    assert f.fights == [], f.fights                                   # C1: 제한 없는 fight() 안 부름
    assert state["defends"] >= 5
    assert all(c[1] == 0 and c[2] == 0 for c in moves(f)), moves(f)   # C2: 스틱은 늘 중립
    assert not f.walks, f.walks
    assert all(b is False for b in f.reflex.bs_seen), f.reflex.bs_seen  # 방어 중 반사 반격 꺼짐
    later = [t for t in lure_t[1:] if t < state["gone_t"] + F.LURE_UNBLOCK_S - 0.02]
    assert not later, (later, state)                                  # C3: 그놈이 있는 동안·직후엔 새 끌어오기 없음
    print(f"ok  C1-C3 low-stamina contact: no fight(), {state['defends']} defend slices, sticks neutral, no lure until calm")


def test_low_stamina_low_hp_recovers() -> None:
    """C4: 제자리 방어 중 HP 25 % 아래면 기존 recover()."""
    w = base(sp=20)
    w.player.hp = 100
    w.add(3, 0x1013, 254000, at(dx=2.5))
    f = make_field(w)
    assert f._defend_in_place(3, None) == "recovered" and f.recovers and not f.fights
    print("ok  C4 low HP during defend → existing recover(), no fight")


def test_contact_out_of_zone() -> None:
    """C5: 구역 밖 접촉 — 싸움 없음, 다가가지 않음."""
    w = base(sp=80, player=at(dx=1.4))
    w.add(3, 0x1013, 254000, at(dx=3.9))              # 나에게서 2.5 m, 자리에서 3.9 m (> 2.5 m 구역)
    f = make_field(w)
    st, thr = f._hold_at(SPOT, None, "#2", w.snapshot(), ())
    assert st == "contact_out_of_zone" and thr.ptr == 3, st
    f.lure_result = "too_close"
    r = f.clear([dict(T2)], nm=None, lure=True)
    assert r.startswith("partial") and f.fights == [], (r, f.fights)
    assert all(c[1] == 0 and c[2] == 0 for c in moves(f))
    print("ok  C5 contact outside the safe zone → no duel, no approach")


def test_contact_in_zone_leash() -> None:
    """C6 + 둘째 놈: 구역 안 접촉은 신원에 묶인 싸움 — 구역 이탈·신원 변화·둘째 놈 접근이면 끊는다."""
    w = base(sp=80)
    w.add(3, 0x1013, 254000, at(dx=2.0))
    f = make_field(w)
    st, thr = f._hold_at(SPOT, None, "#2", w.snapshot(), ())
    assert st == "contact_in_zone", st
    leash = f._zone_leash(thr, SPOT, None)
    assert leash() is False
    w.move(3, at(dx=3.0)); assert leash() is True; w.move(3, at(dx=2.0))            # 그놈이 구역 밖
    w.player.x = SPOT[0] + 2.8; assert leash() is True; w.player.x = SPOT[0]       # 내가 구역 밖
    w.handles[3] = 0x9999; assert leash() is True; w.handles[3] = 0x1013           # 신원 바뀜
    f.esc.gen = 1; assert leash() is True; f.esc.gen = 0                             # 세대 바뀜
    w.add(4, 0x1014, 254001, at(dx=-2.0)); assert leash() is True; del w.chars[4]  # 둘째 놈이 3 m 안
    assert leash() is False
    # clear 수준: 싸움 중 둘째 놈이 붙으면 그 틱에 끊기고, 그 싸움 안에서 목표를 바꾸지 않는다
    calls = []

    def fight(ptr, nm, tag, arena=None, desperate=False, limit=45.0, wait_far=False, leash=None, may_approach=None):
        calls.append(dict(ptr=ptr, tag=tag, wait_far=wait_far, limit=limit, leash=leash))
        if len(calls) == 1:
            w.add(4, 0x1014, 254001, at(dx=-1.5))    # 둘째 놈이 붙음
            assert leash is not None and leash() is True
            return D.DuelResult("cancel")
        w.chars[ptr].hp = 0
        return D.DuelResult("killed")
    f2 = make_field(w)
    f2.fight = fight
    f2.lure_result = "too_close"
    f2.clear([dict(T2)], nm=None, lure=True)
    first = calls[0]
    assert first["ptr"] == 3 and first["tag"].startswith("hold 접촉") and first["wait_far"] is True \
        and first["limit"] == F.COMING_LIMIT, first
    print(f"ok  C6 in-zone contact → leashed fight(wait_far, COMING_LIMIT); leash cuts on zone exit/identity/gen/2nd hostile"
          f" (2nd hostile entered → cancel, no retarget inside that fight; later handoffs: {[c['ptr'] for c in calls[1:]]})")


def test_coming_inside_zone_uses_existing_branch() -> None:
    """C7: 구역 안에서 '오는 놈'은 기존 가지가 받는다 — 제자리 고수용 싸움은 없다."""
    w = base(sp=80)
    f = make_field(w)
    f.lure_result = "too_close"
    seen = {"n": 0}

    def lure(ptr, spawn, nm, tag, arena=None, lure_at=None):
        seen["n"] += 1
        if seen["n"] == 1:
            w.add(3, 0x1013, 254000, at(dx=2.0), anim=3000)
        return "too_close"
    f.lure = lure
    f.clear([dict(T2)], nm=None, lure=True)
    tags = [x["tag"] for x in f.fights]
    assert tags and tags[0].startswith("오는 놈") and not any(t.startswith("hold 접촉") for t in tags), tags
    assert f.fights[0]["leash"] is None and f.fights[0]["wait_far"] is True
    print("ok  C7 coming hostile inside zone → existing coming branch (no leash), no hold-specific duel")


def test_calm_recovers_stamina() -> None:
    """C8: 조용한 제자리 — 방패를 계속 내리고, 스태미나가 찬다."""
    w = base(sp=40)
    f = make_field(w)
    snap0 = w.snapshot

    def snapshot(within=60.0):
        g = f.mv.guards[-1] if f.mv.guards else False
        w.player.sp = min(w.player.max_sp, w.player.sp + (0.6 if g else 3.0))   # 방패를 들면 거의 안 찬다
        return snap0(within)
    w.snapshot = snapshot
    for _ in range(20):
        st, _ = f._hold_at(SPOT, None, "#2", None, ())
        assert st == "calm", st
    assert f.mv.guards and all(g is False for g in f.mv.guards), f.mv.guards
    assert w.player.sp >= 90, w.player.sp
    print(f"ok  C8 calm hold: guard off every tick, stamina 40 → {w.player.sp}")


def test_approach_guard_only_when_closing() -> None:
    """C9: 다가오는 놈 — 좁혀 올 때만 방패. 서 있으면 내림."""
    w = base(sp=80)
    w.add(3, 0x1013, 254000, at(dx=4.5))
    f = make_field(w)
    for k in range(8):
        w.move(3, at(dx=4.5 - 0.08 * k))              # 0.1 s 에 0.08 m → 0.5 s 에 0.4 m
        st, _ = f._hold_at(SPOT, None, "#2", w.snapshot(), ())
        assert st == "approach", st
        time.sleep(0.05)
    assert f.mv.guards[-1] is True, f.mv.guards
    f2 = make_field(w)
    for _ in range(8):
        f2._hold_at(SPOT, None, "#2", w.snapshot(), ())
        time.sleep(0.05)
    assert f2.mv.guards and all(g is False for g in f2.mv.guards), f2.mv.guards
    print("ok  C9 approach: guard only while the hostile is closing (≥0.3 m / 0.5 s), else guard down")


def test_returning_and_height() -> None:
    """C10·C11: 자리에서 2 m → 돌아감. 2.5 m 이지만 3 m 위 → 조용."""
    w = base(player=at(dx=2.0))
    f = make_field(w)
    st, _ = f._hold_at(SPOT, None, "#2", w.snapshot(), ())
    assert st == "returning" and f.walks and f.walks[0][0] == SPOT, (st, f.walks)
    w2 = base()
    w2.add(3, 0x1013, 254000, at(dx=2.5, dy=3.0))
    st, _ = make_field(w2)._hold_at(SPOT, None, "#2", w2.snapshot(), ())
    assert st == "calm", st
    print("ok  C10 off-spot → returning (walk_to spot); C11 hostile 3 m higher → calm")


def test_lure_block_hysteresis_unit() -> None:
    lb = F.LureBlock()
    assert lb.update(False, 0.0) is False
    lb.set()
    seq = [(False, 0.00, True), (False, 0.30, True), (True, 0.35, True), (False, 0.40, True),
           (False, 0.85, True), (True, 0.88, True), (False, 0.90, True), (False, 1.39, True), (False, 1.41, False)]
    for near, t, want in seq:
        assert lb.update(near, t) is want, (near, t, want)
    print("ok  LureBlock: clears only after ≥0.5 s of continuous calm; a brief re-entry restarts the timer")


def test_boundary_crossing_does_not_restart_lure() -> None:
    """히스테리시스 (clear 수준): 스태미나 모자란 접촉 뒤 그놈이 5 m 경계를 오가면 끌어오기를 다시 시작하지 않는다."""
    w = base(sp=20)
    f = make_field(w)
    lure_t, st = [], {"phase_t": None, "gone_t": None, "last_near_t": None, "crossings": 0}

    def lure(ptr, spawn, nm, tag, arena=None, lure_at=None):
        lure_t.append(time.time())
        if len(lure_t) == 1:
            w.add(3, 0x1013, 254000, at(dx=2.5))
        return "too_close"
    f.lure = lure
    orig = F.Field._defend_in_place

    def defend(ptr, nm):
        r = orig(f, ptr, nm)
        if st["phase_t"] is None:
            st["phase_t"] = time.time()
            w.player.sp = 106                           # 이제 스태미나는 충분 — 접촉이 아니라 경계를 오가는 놈만 남긴다
        return r
    f._defend_in_place = defend
    snap0 = w.snapshot

    def snapshot(within=60.0):
        if st["phase_t"] is not None and 3 in w.chars:
            el = time.time() - st["phase_t"]
            if el > 1.2:
                del w.chars[3]
                st["gone_t"] = time.time()
            else:
                inside = int(el / 0.2) % 2 == 0          # 0.2 s 마다 5 m 경계를 넘나듦 (4.8 m ↔ 5.4 m)
                w.move(3, at(dx=4.8 if inside else 5.4))
                if inside:
                    if st["last_near_t"] is not None and time.time() - st["last_near_t"] > 0.1:
                        st["crossings"] += 1
                    st["last_near_t"] = time.time()
        return snap0(within)
    w.snapshot = snapshot
    r = f.clear([dict(T2)], nm=None, lure=True)
    assert st["gone_t"] is not None and r.startswith("partial"), (r, st)
    assert st["crossings"] >= 2, st                    # 실제로 경계를 여러 번 넘나들었다
    after = [t for t in lure_t[1:] if t >= st["phase_t"]]
    during = [t for t in after if t < st["gone_t"]]
    assert not during, (during, st)                    # 넘나드는 동안엔 한 번도 다시 안 던짐
    early = [t for t in after if t < st["last_near_t"] + F.LURE_UNBLOCK_S - 0.02]
    assert not early and after, (early, after, st)     # 마지막으로 5 m 안이었던 때부터 0.5 s 계속 조용해야 다시 던짐
    assert f.fights == []
    gap = after[0] - st["last_near_t"]
    print(f"ok  hostile crossed the 5 m boundary {st['crossings']}+ times over 1.2 s → no lure restart; "
          f"resumed {gap:.2f} s after it was last within 5 m (≥ {F.LURE_UNBLOCK_S} s)")


if __name__ == "__main__":
    test_low_stamina_threat_restricted()
    test_low_stamina_low_hp_recovers()
    test_contact_out_of_zone()
    test_contact_in_zone_leash()
    test_coming_inside_zone_uses_existing_branch()
    test_calm_recovers_stamina()
    test_approach_guard_only_when_closing()
    test_returning_and_height()
    test_lure_block_hysteresis_unit()
    test_boundary_crossing_does_not_restart_lure()
    print("전부 통과")
