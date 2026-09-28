"""Backstab drill — only this, outside any mission: get behind the nearest hollow (and optionally stab).

  BOT_GAME=dsr python backstab_drill.py            get behind the nearest live foe within 8 m, then stop and report
  BOT_GAME=dsr python backstab_drill.py --stab     same, then release everything and press R1
  BOT_GAME=dsr python backstab_drill.py --radar    also send to radar_server.py

Uses the same moves as the duel (souls/duel.py): lock-on, strafe round at body contact (backstab_stick), walk straight in once
behind. Prints distance / how far behind / foe anim every 0.2 s so the approach can be compared with the human demos.
Offline only (virtual pad).
"""
from __future__ import annotations

import argparse
import math
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env
from souls import duel as D
from souls import moves as M
from souls import weapons

FIND_R = 8.0
TIMEOUT_S = 6.0


def behind_deg(c, p) -> float:
    return abs(math.degrees(M.rel_angle(c, p))) if c.heading is not None else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stab", action="store_true", help="once behind, release everything and press R1")
    ap.add_argument("--radar", action="store_true")
    a = ap.parse_args()

    tm = env.make_telemetry({})
    control.focus_game()
    pad = control.Pad()
    mv = M.Moves(tm, pad)
    mv.weapon = weapons.of(tm.right_weapon())
    if a.radar:
        import radar
        radar.Radar().attach(tm).follow(mv)

    s = mv.snap(FIND_R)
    foes = [c for c in (s.hostile(FIND_R) if s else []) if c.hp > 0]
    if not foes:
        print(f"no live foe within {FIND_R} m")
        return
    c = min(foes, key=lambda x: M.horiz(s.player, x))
    ptr = c.ptr
    print(f"target npc {c.npc} ptr {ptr}: {M.horiz(s.player, c):.1f} m, behind {behind_deg(c, s.player):.0f}°, anim {c.anim}")

    def wait(t: float) -> None:
        t1 = time.time() + t
        while time.time() < t1:
            pad.release_due()
            time.sleep(0.01)

    result = "timeout"
    mv.cam_busy = True
    try:
        pad.guard(False)
        if mv.lock_state(ptr) != "target":
            mv.unlock()
            pad.lock_on()
            wait(0.25)
        print(f"lock-on: {mv.lock_state(ptr)}")
        t0, last_print = time.time(), 0.0
        while time.time() - t0 < TIMEOUT_S:
            s = mv.snap(8.0)
            c = mv.find(s, ptr) if s else None
            if c is None or c.hp <= 0:
                result = "lost"
                break
            h, deg = M.horiz(s.player, c), behind_deg(c, s.player)
            x, y, _ = D.backstab_stick(c, s.player)
            if time.time() - last_print >= 0.2:
                last_print = time.time()
                print(f"  {time.time() - t0:4.1f}s  d {h:.2f} m  behind {deg:3.0f}°  foe anim {c.anim}  stick ({x:+.2f},{y:+.2f})")
            if deg >= D.BACKSTAB_DEG and h <= D.BACKSTAB_MAX_R:
                result = "behind"
                break
            pad.move(x, y)
            wait(D.BACKSTAB_TICK)
        pad.move(0.0, 0.0)
        wait(D.BACKSTAB_RELEASE_S)
        s = mv.snap(8.0)
        c = mv.find(s, ptr) if s else c
        if c is not None:
            print(f"{result}: d {M.horiz(s.player, c):.2f} m, behind {behind_deg(c, s.player):.0f}°, foe anim {c.anim}")
        if result == "behind" and a.stab:
            hp0 = c.hp
            pad.attack()
            for _ in range(20):
                wait(0.05)
                s = mv.snap(8.0)
                c2 = mv.find(s, ptr) if s else None
                if c2 is None or c2.hp <= 0:
                    print("stab: killed")
                    break
                me = s.player.anim
            else:
                print(f"stab: foe HP {hp0} → {c2.hp}, my anim {me} (backstab anims are 2030xx/2031xx? compare with demos)")
    finally:
        pad.move(0.0, 0.0)
        wait(0.1)
        mv.unlock()
        wait(0.1)
        pad.neutral()


if __name__ == "__main__":
    main()
