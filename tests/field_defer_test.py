"""Patch B 오프라인 테스트 — 미룬 제자리 고수 대상은 찾아가지 않고, 안전하게 'partial deferred_unreachable' 로 끝낸다.

  python field_defer_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World, make_field
from souls import field as F
from souls import missions as MS

SPAWN2 = (-23.4, -49.67, 16.15)
SPOT = (-30.35, -49.43, 27.91)
LA = {"spot": SPOT, "min": 13.0, "max": 15.0, "hold": True}
T2 = {"npc": 255010, "pos": list(SPAWN2), "label": 2, "lure": True, "lure_at": LA}
T1 = {"npc": 254000, "pos": [-29.79, -49.62, 24.88], "label": 1, "lure": False}

F.HOLD_WAIT = 0.01                     # 테스트는 빠르게 — 기다림 길이는 논리에 상관없다


def world_at_spot():
    w = World(player=SPOT)
    w.add(2, 0x1018, 255010, SPAWN2, hp=85, max_hp=85)
    return w


def test_unreachable_terminal() -> None:
    w = world_at_spot()
    f = make_field(w)
    f.lure_result = "too_close"
    r = f.clear([dict(T2)], nm=None, lure=True)
    assert r == "partial deferred_unreachable #2", r
    assert not any(x["ptr"] == 2 for x in f.fights), f.fights          # 찾아가 싸우지 않는다
    assert len(f.lures) == 2 * F.HOLD_TRIES, len(f.lures)               # 미룬 뒤 한 바퀴 더
    tail = f.mv.pad.calls[-3:]
    assert ("neutral",) in tail and ("guard", False) in tail, tail      # 입력 중립·방패 내림
    ev = [kw for k, kw in f.evs if k == "deferred_unreachable"]
    assert len(ev) == 1 and ev[0]["handle"] == 0x1018 and ev[0]["gen"] == 0 and ev[0]["hp"] == 85 and ev[0]["dist"] is not None, ev
    assert not any(g[1] == "#2 이동" for g in f.walks)
    print(f"ok  lure always too_close → '{r}', fight(#2) never called, neutral+guard off, event with handle/gen/hp/dist")


def test_deferred_then_others_then_terminal() -> None:
    w = world_at_spot()
    w.add(1, 0x1015, 254000, T1["pos"])
    f = make_field(w)
    f.lure_result = "interrupted"
    r = f.clear([dict(T2), dict(T1)], nm=None, lure=True)
    assert r == "partial deferred_unreachable #2", r
    assert [x["ptr"] for x in f.fights] == [1], f.fights                # #1 은 평소대로 싸움, #2 는 아님
    assert any("맨 뒤로" in l for l in f.logs)
    print("ok  deferral rotates #2 behind #1; #1 fought normally; #2 still never fought → partial")


def test_coming_target_is_engaged() -> None:
    w = world_at_spot()
    f = make_field(w)

    def lure(ptr, spawn, nm, tag, arena=None, lure_at=None):
        f.lures.append(dict(ptr=ptr))
        w.move(2, (SPOT[0] + 2.0, SPOT[1], SPOT[2]))                  # 깨서 평지로 옴
        w.chars[2].anim = 3005
        return "lured"
    f.lure = lure
    r = f.clear([dict(T2)], nm=None, lure=True)
    assert r == "cleared", r
    assert [x["ptr"] for x in f.fights] == [2] and f.fights[0]["wait_far"] is True, f.fights
    assert f.fights[0]["tag"].startswith("오는 놈"), f.fights
    print("ok  lured #2 that comes (anim≠-1, near) → fought via the existing coming branch → cleared")


def test_non_hold_unchanged() -> None:
    w = World(player=SPOT)
    w.add(1, 0x1015, 254000, T1["pos"])
    f = make_field(w)
    f.lure_result = "no_reaction"
    t = dict(T1, lure=True)
    r = f.clear([t], nm=None, lure=True)
    assert r == "cleared" and [x["ptr"] for x in f.fights] == [1], (r, f.fights)
    print("ok  non-hold target: failed lure → fight() as before")


def test_callers_stop() -> None:
    ms = MS.Missions.__new__(MS.Missions)
    calls = []
    ms.f = type("F", (), {"alive": lambda self: True, "wait_respawn": lambda self: None})()
    ms.log = lambda *a: None
    ms.start_fresh = lambda: True
    ms.clear_ramp = lambda lure=True: "partial deferred_unreachable #2"
    ms.to_merchant = lambda: calls.append("to_merchant") or "도착"
    for name in ("burg_bonfire", "burg_bonfire_round_trip"):
        r = getattr(MS.Missions, name)(ms)
        assert r == "경사로 partial deferred_unreachable #2" and not calls, (name, r, calls)
    print("ok  burg_bonfire / burg_bonfire_round_trip stop at the ramp (no route progression)")


def test_risk_report_flags_partial() -> None:
    import risk_report
    d = Path(tempfile.mkdtemp())
    p = d / "x_clear-ramp.jsonl"
    rows = [{"t": 1.0, "ev": "vital", "hp": 793, "max": 793, "near": 0},
            {"t": 2.0, "ev": "result", "cmd": "clear-ramp", "result": "partial deferred_unreachable #2"}]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    sc = risk_report.score(p)
    assert sc["verdict"] != "깨끗" and "partial" in sc["flags"], sc
    print(f"ok  risk_report: partial run → verdict '{sc['verdict']}', flags {sc['flags']}")


if __name__ == "__main__":
    test_unreachable_terminal()
    test_deferred_then_others_then_terminal()
    test_coming_target_is_engaged()
    test_non_hold_unchanged()
    test_callers_stop()
    test_risk_report_flags_partial()
    print("전부 통과")
