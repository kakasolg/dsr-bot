"""Try one attack combo with no foe around and print our anim sequence (60 Hz) — which inputs make one move.

  python experiments/combo_probe.py backstep [--r1 0.45]     stick neutral → B tap → R1 at t (after B)
  python experiments/combo_probe.py roll [--r1 0.55]         stick forward + B → R1 at t
  python experiments/combo_probe.py jump [--r1 0.1]          stick forward + R2 in one report (Pad.jump_attack); --r1 = stick leads R2 by t
  python experiments/combo_probe.py kick                     stick forward + R1 (control.Pad.kick)

[MoKa] 2026-11-03 (in a room): "하나 씩 여기서 해봐." — after P-121 ("구르기 하고 기다렸다 약공 … 사이가 떠 버려").
LAYERS.md "User demo recording": MoKa's backstep is 695 → 304500 (backstep attack, two-handed); the bot's B tap + R1 at 0.45 s
gave 690 → 304040 (a plain light). Keeps the current grip. First turns to a heading with floor ahead and behind (open_way).
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import argparse
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import math
from types import SimpleNamespace as NS

import control
import dsr_telemetry
import env
import nav
import navmesh
from control import B
from souls import missions
from souls import moves as M

ACTIVE_VALS = (5, 257)      # anim struct +0xA0 while the blade is out (swing_probe.py, Claymore 10-13)
FRONT_M, BACK_M = 3.0, 2.6   # floor needed ahead / behind — the bot's own checks (combo need_front 3.0, backstep 2.6)


def heading(nm, p):
    """(off from my facing °, dx, dz) of the open heading nearest my facing, or None."""
    best = None
    for k in range(24):
        a = math.radians(k * 15)
        dx, dz = math.sin(a), math.cos(a)
        if nav.can_move(nm, p, dx, dz, FRONT_M) and nav.can_move(nm, p, -dx, -dz, BACK_M):
            off = abs(math.degrees(M.rel_angle(p, NS(x=p.x + dx, z=p.z + dz)))) if getattr(p, "heading", None) is not None else 0.0
            if best is None or off < best[0]:
                best = (off, dx, dz)
    return best


def open_way(tm, pad):
    """[MoKa] 11-03: "지금 벽에 붙어 있는데 이걸 하면 어떻게 해, 공간을 확보 하고 해야지" — find a heading with FRONT_M of floor
    ahead and BACK_M behind on the Burg / Firelink NavMesh, turn the body to it (≤ 3 s). → the point to aim at, or None."""
    s = tm.snapshot(within=8.0)
    p = s.player
    nm = next((n for n in (navmesh.Navmesh(missions.MAP_B), navmesh.Navmesh(missions.MAP_A))
               if n.floor_at(p.gx, p.gz, p.gy) is not None), None)
    if nm is None:
        print("  no NavMesh floor under us — not moving", flush=True)
        return None
    mv = M.Moves(tm, pad)
    best = heading(nm, p)
    if best is None:
        spot = None
        for r in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0):           # nearest spot (walkable in a straight line) that has an open heading
            for k in range(16):
                a = math.radians(k * 22.5)
                dx, dz = math.sin(a), math.cos(a)
                q = NS(x=p.x + dx * r, z=p.z + dz * r, gx=p.gx + dx * r, gz=p.gz + dz * r, gy=p.gy)
                if nav.can_move(nm, p, dx, dz, r) and heading(nm, q) is not None:
                    spot = q
                    break
            if spot is not None:
                break
        if spot is None:
            print(f"  no spot within 4 m with {FRONT_M} m ahead and {BACK_M} m behind — not moving", flush=True)
            return None
        print(f"  walking {math.hypot(spot.x - p.x, spot.z - p.z):.1f} m to open floor", flush=True)
        t0 = time.time()
        while time.time() - t0 < 5.0:
            s = tm.snapshot(within=5.0)
            if s is None:
                continue
            if math.hypot(spot.x - s.player.x, spot.z - s.player.z) < 0.4:
                break
            pad.move(*mv.stick_to(s, spot.x, spot.z, 0.6))
            time.sleep(0.03)
        pad.neutral()
        time.sleep(0.4)
        p = tm.snapshot(within=5.0).player
        best = heading(nm, p)
        if best is None:
            print(f"  still no open heading after walking (now {p.x:.2f}, {p.z:.2f}) — not moving", flush=True)
            return None
    c = NS(x=p.x + best[1] * 5.0, z=p.z + best[2] * 5.0)
    t0 = time.time()
    while time.time() - t0 < 3.0:
        s = tm.snapshot(within=5.0)
        if s and mv.face(s, c, deg=8.0):
            pad.neutral()
            time.sleep(0.4)
            print(f"  faced open floor ({math.degrees(math.atan2(best[1], best[2])):+.0f}°)", flush=True)
            return mv, c
        time.sleep(0.03)
    pad.neutral()
    print("  could not turn to open floor in 3 s — not moving", flush=True)
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["backstep", "roll", "jump", "kick"])
    ap.add_argument("--r1", type=float, default=None, help="R1 this long after B (backstep 0.45, roll 0.55)")
    ap.add_argument("--secs", type=float, default=2.5)
    a = ap.parse_args()
    tm = env.make_telemetry({})
    pad = control.Pad()
    time.sleep(2.0)                                  # a new pad needs ~2 s before the game takes it
    control.focus_game()
    time.sleep(0.5)
    s = tm.snapshot(within=8.0)
    p0 = s.player if s else None
    print(f"{a.kind}: grip {tm.grip()}  HP {p0 and p0.hp}  SP {p0 and p0.sp}  at {p0 and (round(p0.x, 2), round(p0.z, 2))}", flush=True)
    pad.neutral()
    time.sleep(0.8)
    way = open_way(tm, pad)
    if way is None:
        return
    mv, aim = way
    s = tm.snapshot(within=5.0)
    p0 = s.player
    fwd = mv.stick_to(s, aim.x, aim.z)
    r1_at = None if a.kind == "jump" else (a.r1 if a.r1 is not None else {"backstep": 0.45, "roll": 0.55}.get(a.kind))
    t0 = time.time()
    if a.kind == "backstep":
        pad.release_stick()
        t0 = time.time()
        pad.tap(B.XUSB_GAMEPAD_B, 0.06)
    elif a.kind == "roll":
        pad.move(*fwd)
        time.sleep(0.3)
        t0 = time.time()
        pad.tap(B.XUSB_GAMEPAD_B, 0.06, stick_ok=True)
    elif a.kind == "jump" and a.r1 is None:
        t0 = time.time()
        pad.jump_attack(fwd)                  # stick and R2 in the same report, like the kick
    elif a.kind == "jump":
        pad.move(*fwd)                               # --r1 here = how long the stick leads R2 (COMBOS jump_r2: 0.1)
        time.sleep(a.r1)
        t0 = time.time()
        pad._r2(0.12)
    else:
        t0 = time.time()
        pad.kick(*fwd)
    # [MoKa] 11-04 "검이 길고 동작이 다르니 다시 측정": blade-out window (+0xA0) and how far we had moved along the aim by then
    ax, az = aim.x - p0.x, aim.z - p0.z
    an_ = math.hypot(ax, az) or 1.0
    ax, az = ax / an_, az / an_

    def blade():
        try:
            pp = tm.player_ptr()
            v = tm.i32(tm.q(tm.q(pp + dsr_telemetry.OFF_MAPDATA) + 0x48) + 0xA0)
            return None if v is None else v & 0xFFFF     # combos set the high bit (0x80000005 / 0x80000101) — plain light doesn't
        except Exception:
            return None
    wins, on, braw = [], None, []
    anims, last, r1_done, stick_off = [], None, r1_at is None, False
    while time.time() - t0 < a.secs:
        pad.release_due()
        t = time.time() - t0
        if not stick_off and t >= 0.25 and a.kind in ("roll", "jump", "kick"):
            pad.move(0.0, 0.0)
            stick_off = True
        if not r1_done and t >= r1_at:
            pad.tap(B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06, stick_ok=True)
            anims.append((round(t, 2), "R1"))
            r1_done = True
        s = tm.snapshot(within=5.0)
        an = s.player.anim if s else None
        b = blade()
        if not braw or braw[-1][1] != b:
            braw.append((round(t, 2), b))
        fw = ((s.player.x - p0.x) * ax + (s.player.z - p0.z) * az) if s else None
        if b in ACTIVE_VALS and on is None:
            on = (round(t, 2), fw)
        elif b not in ACTIVE_VALS and on is not None:
            if wins and on[0] - wins[-1][1] < 0.05:
                wins[-1] = (wins[-1][0], round(t, 2), wins[-1][2], fw)
            else:
                wins.append((on[0], round(t, 2), on[1], fw))
            on = None
        if an != last:
            anims.append((round(t, 2), an))
            last = an
        time.sleep(1 / 60)
    pad.neutral()
    s = tm.snapshot(within=5.0)
    p1 = s.player if s else None
    moved = ((p1.x - p0.x) ** 2 + (p1.z - p0.z) ** 2) ** 0.5 if p0 and p1 else None
    print(f"  → {anims}", flush=True)
    print(f"  moved {moved and round(moved, 2)} m, SP {p1 and p1.sp}", flush=True)
    for w0, w1, f0, f1 in wins:                      # forward displacement at blade on → off (m along the aim; − = backwards)
        print(f"  blade {w0:.2f}–{w1:.2f} s, forward {f0 if f0 is None else round(f0, 2)} → {f1 if f1 is None else round(f1, 2)} m", flush=True)
    if not wins:
        print("  blade: no +0xA0 window seen", flush=True)


if __name__ == "__main__":
    main()
