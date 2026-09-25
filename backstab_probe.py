"""등 뒤 공격(진짜 백스탭)이 되는 거리·각도를 찾는다 — 등뒤돌기(157°)로도 0 피해였다 (2026-09-25, duel.py 등뒤돌기).
가만히 선 채 안 움직이는 방패병(254013/254014, anim -1) 옆에서: 그놈 기준 각도(180=정후방)·거리 조합마다
그 자리로 걸어가 → 그놈을 보고 → 약공 1회 → 내 애니·피해·그놈 HP 변화를 본다. 표적이 죽으면 다음 표적으로.

  BOT_GAME=dsr python backstab_probe.py
"""
from __future__ import annotations

import math
import sys
import time

sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env
import nav
from souls import moves as M

GRID = [(d, a) for d in (0.8, 1.0, 1.3, 1.6) for a in (150, 160, 170, 180)]


def goto_point(tm, pad, gx, gz, timeout=4.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        pad.release_due()
        s = tm.snapshot(within=10.0)
        if s is None or s.cam_yaw is None:
            time.sleep(0.05)
            continue
        d = math.hypot(gx - s.player.x, gz - s.player.z)
        if d < 0.35:
            pad.move(0.0, 0.0)
            return True
        pad.move(*control.world_to_stick(gx - s.player.x, gz - s.player.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X))
        time.sleep(0.04)
    pad.move(0.0, 0.0)
    return False


def watch_anim(tm, pad, secs: float) -> list:
    t0, out, last = time.time(), [], None
    while time.time() - t0 < secs:
        pad.release_due()
        s = tm.snapshot(within=6.0)
        a = s.player.anim if s else None
        if a != last:
            out.append((round(time.time() - t0, 2), a))
            last = a
        time.sleep(1 / 60)
    return out


def main() -> None:
    tm = env.make_telemetry({})
    control.focus_game()
    pad = control.Pad()
    mv = M.Moves(tm, pad)
    s = tm.snapshot(within=15.0)
    targets = [c.ptr for c in s.hostile(15.0) if c.hp > 0 and c.anim in (-1, None)]
    print(f"표적 {len(targets)}: {targets}", flush=True)
    ti = 0
    for d, ang in GRID:
        if ti >= len(targets):
            print("표적 다 씀 — 멈춤", flush=True)
            break
        ptr = targets[ti]
        s = tm.snapshot(within=15.0)
        c = next((x for x in s.hostile(20.0) if x.ptr == ptr), None)
        if c is None or c.hp <= 0:
            print(f"  표적 {ptr:x} 없어짐/죽음 — 다음 표적", flush=True)
            ti += 1
            continue
        off = math.radians(180 - ang)
        bx, bz = math.sin(c.heading), math.cos(c.heading)
        rx = bx * math.cos(off) + bz * math.sin(off)
        rz = bz * math.cos(off) - bx * math.sin(off)
        gx, gz = c.x + rx * d, c.z + rz * d
        ok = goto_point(tm, pad, gx, gz)
        s = tm.snapshot(within=15.0)
        c = next((x for x in s.hostile(20.0) if x.ptr == ptr), None) if s else None
        if c is None:
            print(f"  d={d} ang={ang}: 자리 못 감({ok}) — 표적 사라짐", flush=True)
            continue
        real_d = math.hypot(c.x - s.player.x, c.z - s.player.z)
        for _ in range(3):
            if mv.face(s, c, deg=15.0):
                break
            s = tm.snapshot(within=15.0)
            c = next((x for x in s.hostile(20.0) if x.ptr == ptr), None)
        hp0 = c.hp
        pad.tap(control.B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06)
        anims = watch_anim(tm, pad, 2.2)
        s = tm.snapshot(within=15.0)
        c2 = next((x for x in s.hostile(20.0) if x.ptr == ptr), None) if s else None
        hp1 = c2.hp if c2 is not None else 0
        print(f"  d={d} ang={ang} 자리도착={ok} 실측거리={real_d:.2f} → HP {hp0}→{hp1} 내 애니 {anims[:6]}", flush=True)
        if c2 is None or hp1 <= 0:
            ti += 1
        time.sleep(0.6)
    pad.neutral()


if __name__ == "__main__":
    main()
