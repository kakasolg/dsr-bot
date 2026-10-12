"""duel._keep_lock + heavies only locked on ([MoKa] 2026-10-12: "강공 할때는 락온이 필수야" · "2번으로 해" = stay locked on through a
clear 1:1 fight). Fakes from duel_golden_test (R3 locks whatever the camera follows), no game.  python tests/lock_keep_test.py

Checks:
  · 1:1 within LOCK_KEEP_R, body on it → R3 → locked; a second R3 within LOCK_RETRY_S never comes
  · body 60° off → no R3 (R3 grabs whatever is nearest the camera centre); camera 12° → R3, 25° → none
  · a backstab try leaves a lock-on that was already on the target
  · a second awake foe within ALONE_R → released; locked on another foe → released
  · every tick lets tapped buttons go (release_due) — R3 left down made the next R3 the same press (unlock bug 10-12)
  · heavies: wall heavy (_slam), sleeper heavy, the weapon's default heavy only while locked on the target
  · duel() end leaves no lock-on behind
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import duel_golden_test as G
from field_fakes import World
from souls import duel as D
from souls import moves as M
from souls import weapons


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def rig(other=None, facing_err=0.0, dist=1.2):
    w = World(player=(0.0, -49.4, 0.0), sp=106, max_sp=106)
    w.player.heading = -math.pi + math.radians(facing_err)
    c = w.add(2, 0x1002, 254010, (0.0, -49.4, dist), hp=75, max_hp=75)
    c.heading = 0.0
    if other is not None:
        o = w.add(3, 0x1003, 254011, other, hp=75)
        o.heading = -math.pi / 2
    trace = []
    mv = G.Mv(w, trace)
    presses, released = [], []
    r3 = mv._r3
    mv._r3 = lambda: (presses.append(mv.locked), r3())[1]
    mv.pad.release_due = lambda: released.append(1)
    mv.cam_target = 2
    F = NS(mv=mv, ptr=2, lock_t=0.0, lock_n=0, note=lambda *a: None, weapon=weapons.BATTLE_AXE, nm=None, foe=None)
    return w, mv, F, presses, released


def tick(w, F, now):
    s = w.snapshot()
    c = next(x for x in s.chars if x.ptr == 2)
    T = NS(s=s, p=s.player, c=c, h=M.horiz(s.player, c), dy=c.y - s.player.y, now=now)
    D._keep_lock(F, T)
    return T


def main() -> None:
    w, mv, F, presses, released = rig()
    tick(w, F, 100.0)
    check("1:1, 1.2 m, 몸이 그놈 쪽 → R3 → 락온", mv.lock_state(2) == "target" and len(presses) == 1)
    check("틱마다 눌린 버튼을 뗌 (release_due)", released)
    mv.locked = None
    tick(w, F, 100.5)
    check(f"LOCK_RETRY_S ({D.LOCK_RETRY_S} s) 안에는 다시 안 누름", len(presses) == 1)
    tick(w, F, 101.2)
    check("그 뒤엔 다시 누름", len(presses) == 2 and mv.lock_state(2) == "target")

    w, mv, F, presses, _ = rig(facing_err=60.0)
    tick(w, F, 100.0)
    check("몸이 60° 어긋남 → R3 안 누름 (카메라 중앙 놈을 잡음)", not presses)

    w, mv, F, presses, _ = rig()
    mv.cam_err = lambda s, x, z: 12.0
    tick(w, F, 100.0)
    check(f"카메라 12° (≤ LOCK_KEEP_CAM_DEG {D.LOCK_KEEP_CAM_DEG:.0f}°) → 누름 — 1:1이라 옆 놈을 잡을 일 없음", len(presses) == 1)
    w, mv, F, presses, _ = rig()
    mv.cam_err = lambda s, x, z: 25.0
    tick(w, F, 100.0)
    check("카메라 25° → 안 누름", not presses)

    # a backstab try leaves _keep_lock's lock-on alone (074829 zone 1-3: it released it, the next hit went out unlocked)
    w, mv, F, presses, _ = rig()
    mv.locked = 2
    mv.pad.attack = lambda: None
    s = w.snapshot()
    c = next(x for x in s.chars if x.ptr == 2)
    sleep = D.time.sleep
    D.time.sleep = lambda t: None
    try:
        D._backstab(mv, s, c, cancel=lambda: True)
    finally:
        D.time.sleep = sleep
    check("뒤잡기 시도 뒤: 이미 걸려 있던 락온은 그대로", mv.lock_state(2) == "target")

    w, mv, F, presses, _ = rig(dist=D.LOCK_KEEP_R + 1.0)
    tick(w, F, 100.0)
    check(f"{D.LOCK_KEEP_R + 1:.0f} m — 아직 락온 안 함", not presses)

    w, mv, F, presses, _ = rig(other=(4.0, -49.4, 0.5))
    mv.locked = 2
    tick(w, F, 100.0)
    check("6 m 안 깨어 있는 둘째 → 락온 풂", mv.lock_state(2) == "none" and len(presses) == 1)
    tick(w, F, 102.0)
    check("둘째가 있는 동안 다시 안 잡음", mv.lock_state(2) == "none" and len(presses) == 1)

    w, mv, F, presses, _ = rig()
    mv.locked = 3
    tick(w, F, 100.0)
    check("다른 놈에 걸림 → 풂", mv.lock_state(2) == "none")
    tick(w, F, 101.5)
    check("다음엔 목표에 다시 걸음", mv.lock_state(2) == "target")

    # heavies need lock-on
    w, mv, F, presses, _ = rig()
    mv.tm.grip = lambda: 3                                   # two hands — _heavy_ok
    F.nm = NS(wall_dist=lambda x, y, z: 0.5)
    s = w.snapshot()
    c = next(x for x in s.chars if x.ptr == 2)
    mv.locked = 2
    check("벽 강공: 락온이면 됨", D._slam(F, s, c) is not None)
    mv.locked = None
    check("벽 강공: 락온 아니면 안 함", D._slam(F, s, c) is None)
    F.calm, F.woke = {2: (c.x, c.z, 0.0)}, set()
    T = NS(s=s, p=s.player, c=c, a=-1, now=10.0)
    mv.locked = 2
    check("잠든 적 강공: 락온이면 됨", D._sleeper_heavy(F, T))
    mv.locked = None
    check("잠든 적 강공: 락온 아니면 안 함", not D._sleeper_heavy(F, T))

    # a whole duel: 1:1 → locked during, nothing left locked after
    w, mv, F, presses, _ = rig()
    n = {"t": 0}

    def cancel():
        n["t"] += 1
        return n["t"] > 4
    saved = {k: getattr(D, k) for k in ("_backstab", "_approach")}
    sleep = D.time.sleep
    D._backstab, D._approach = (lambda *a, **k: "not_behind"), (lambda *a, **k: "stopped")
    D.time.sleep = lambda s: None
    try:
        r = D.duel(mv, weapons.BATTLE_AXE, 2, None, log=lambda line: None, cancel=cancel, reflex=G.Reflex(False, []))
    finally:
        for k, v in saved.items():
            setattr(D, k, v)
        D.time.sleep = sleep
    check(f"duel: 싸움 중 락온 ({presses}), 끝나면 풀림 ({r.result})", None in presses and mv.locked is None)
    print("lock_keep_test: all ok")


if __name__ == "__main__":
    main()
