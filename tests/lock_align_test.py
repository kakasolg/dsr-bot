"""락온 정렬 오프라인 테스트 — Moves.lock_target ([MoKa] 2026-10-01: "캐릭터 앞이 어느 정도 적을 향하고 있어야 함").

  R3 전에 몸이 LOCK_BODY_DEG·카메라가 LOCK_CAM_DEG 안이 될 때까지 돌림 · 높이 LOCK_DY 넘게 다른 적은 시도 안 함 · 정렬 값을 last_lock에

  python tests/lock_align_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys
from types import SimpleNamespace as N

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import moves as M


def make(dy=0.0, body_deg=60.0, cam_deg=50.0):
    mv = M.Moves.__new__(M.Moves)
    st = {"body": body_deg, "cam": cam_deg, "presses": [], "locked": False}
    foe = N(ptr=2, x=0.0, y=dy, z=5.0, hp=75)

    def snap(within=40.0):
        h = math.radians(st["body"]) - math.pi                 # facing = heading + π; rel_angle(p, c) ≈ −body for c straight ahead
        return N(player=N(x=0.0, y=0.0, z=0.0, heading=h), chars=[foe])
    mv.snap = snap
    mv.find = M.Moves.find
    mv.cam_err = lambda s, x, z: st["cam"]
    mv.aim = lambda ptr, deg=8.0, timeout=0.6: st.__setitem__("body", 3.0)
    mv.look_at = lambda ptr, tol=6.0, timeout=0.6: st.__setitem__("cam", 2.0)
    mv.lock_state = lambda ptr: "target" if st["locked"] else "none"

    def lock_on():
        st["presses"].append((st["body"], st["cam"]))
        st["locked"] = abs(st["cam"]) <= M.LOCK_CAM_DEG and abs(st["body"]) <= M.LOCK_BODY_DEG
    mv.pad = N(lock_on=lock_on, release_due=lambda: None)
    return mv, st


def test_aligns_before_r3() -> None:
    mv, st = make()
    assert mv.lock_target(2) is True
    assert st["presses"] and abs(st["presses"][0][0]) <= M.LOCK_BODY_DEG and abs(st["presses"][0][1]) <= M.LOCK_CAM_DEG, st
    assert mv.last_lock.get("cam") is not None and abs(mv.last_lock["cam"]) <= M.LOCK_CAM_DEG, mv.last_lock
    print(f"ok  body 60° / camera 50° off → turned first, R3 pressed at {st['presses'][0]} → locked; last_lock {mv.last_lock}")


def test_other_level_skipped() -> None:
    mv, st = make(dy=5.0)
    assert mv.lock_target(2) is False and not st["presses"], st
    assert mv.last_lock.get("why") == "other level", mv.last_lock
    print("ok  foe 5 m above → no R3 at all")


if __name__ == "__main__":
    test_aligns_before_r3()
    test_other_level_skipped()
    print("전부 통과")
