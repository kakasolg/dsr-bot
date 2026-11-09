"""Godot practice room, stages 1·2 (MoKa M1109-53, Perplexity build order M1109-52): camera pulled in by a wall,
lock-on, DSR input buffer (a press inside the TAE input window runs at the cancel time; one before it is dropped),
swept weapon hit (one hit per swing), the dummy's telegraphed swing hits a standing player and is dodged by a roll's
i-frames. Headless; skipped without Godot. Checks the room against its own rules and the DSR TAE windows — not DSR play.

python tests/godot_combat_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

import json
import math
import time

from godot_room_test import check, go
from sim import godot_link as GL

ROOT = _pl.Path(__file__).resolve().parent.parent
LEVER, ROT = (18.029, -25.488), math.radians(120.0)
DUMMY = (26.5, -26.0)


def wait_for(tm, cond, tmax=6.0, step=0.005) -> dict | None:
    t0 = time.time()
    while time.time() - t0 < tmax:
        st = tm.state()
        if cond(st):
            return st
        time.sleep(step)
    return None


def face_dummy_from(tm, pad, dist: float) -> dict:
    """Stand dist m from the dummy on the bonfire side and lock on (lock-on turns the body to it)."""
    st = tm.state()
    a = math.atan2(st["x"] - DUMMY[0], st["z"] - DUMMY[1])
    go(tm, pad, DUMMY[0] + math.sin(a) * dist, DUMMY[1] + math.cos(a) * dist, tol=0.12)
    if not tm.state()["lock"]:
        pad.press("r3")
    pad.move(0.0, 0.0)
    time.sleep(0.6)
    return tm.state()


def main() -> None:
    if not GL.GODOT.exists():
        print(f"skip: Godot not found at {GL.GODOT}")
        return
    d = json.loads((ROOT / "sim/godot/actions.json").read_text(encoding="utf-8"))
    act = d["actions"]
    dmg = round(d["equip"]["right"]["base_physical"] * act["light"]["hit"]["physical_pct"] / 100)   # [game] before scaling
    tm, pad = GL.SimTelemetry(), GL.SimPad()
    proc = GL.start_room(headless=True)
    try:
        st = tm.state(wait=20.0)
        check("room is up", st is not None)
        check(f"open floor: camera at full distance ({st['cam_dist']:.2f} m of 4.0)", abs(st["cam_dist"] - 4.0) < 0.3)

        # 1. camera vs wall: 1 m in front of the long wall left of the lever niche, turn the camera all the way round
        f = (math.sin(ROT), math.cos(ROT))
        w = (f[1], -f[0])
        px, pz = LEVER[0] + w[0] * 4.6 + f[0] * 0.4, LEVER[1] + w[1] * 4.6 + f[1] * 0.4
        st = go(tm, pad, px, pz, tol=0.15)
        dists = []
        pad.look(1.0)
        t0 = time.time()
        while time.time() - t0 < 3.0:                      # 2.5 rad/s × 3 s > one full turn
            dists.append(tm.state()["cam_dist"])
            time.sleep(0.02)
        pad.look(0.0)
        check(f"camera pulled in by the wall: {min(dists):.2f} m at the closest, {max(dists):.2f} m facing away",
              min(dists) < 2.0 and max(dists) > 3.6)

        # 2. lock-on: camera turns to the dummy, the body keeps facing it while strafing
        st = face_dummy_from(tm, pad, 3.0)
        to_d = math.atan2(DUMMY[0] - st["x"], DUMMY[1] - st["z"])
        cam_err = abs(math.degrees((st["cam_yaw"] - to_d + math.pi) % (2 * math.pi) - math.pi))
        check(f"R3 within 15 m → locked on, camera {cam_err:.0f}° off the dummy", st["lock"] and cam_err < 15)
        pad.move(0.6, 0.0)                                  # strafe right
        time.sleep(0.8)
        pad.move(0.0, 0.0)
        time.sleep(0.2)
        st = tm.state()
        to_d = math.atan2(DUMMY[0] - st["x"], DUMMY[1] - st["z"])
        body_err = abs(math.degrees((st["heading"] + math.pi - to_d + math.pi) % (2 * math.pi) - math.pi))
        check(f"strafing while locked on: body still faces the dummy ({body_err:.0f}° off)", body_err < 20)

        # 3. buffer: R inside the roll's R-input window (DSR flag 1 from 0.2 s) runs at its R-cancel (flag 4, 1.1 s);
        #    R before the window (0.1 s) is dropped
        st = face_dummy_from(tm, pad, 6.0)                 # out of the dummy's reach
        roll = act["roll"]
        pad.move(0.0, -0.6)                                  # roll backward, away from it
        pad.press("b", 0.06)
        time.sleep(0.05)                                     # B acts on release: keep the stick through it
        pad.move(0.0, 0.0)
        st = wait_for(tm, lambda s: s["action"] == "roll" and s["anim_time"] >= 0.08)
        pad.press("rb", 0.04)                                # too early
        st = wait_for(tm, lambda s: s["action"] == "roll" and s["anim_time"] >= 0.32)
        pad.press("rb", 0.04)                                # inside the window
        st = wait_for(tm, lambda s: s["anim"] == act["light"]["anim"], tmax=3.0)
        log = st["log"] if st else []
        rs = [e for e in log if e["k"] == "r"][-2:]
        print("  inputs:", rs)
        check("R at 0.1 s into the roll (before DSR's input window at 0.2 s) → dropped",
              len(rs) == 2 and not rs[0]["accepted"])
        lag = rs[1]["exec"] - rs[1]["in"] if len(rs) == 2 and rs[1]["exec"] else None
        check(f"R at ~0.33 s → buffered, ran {lag:.2f} s later at the roll's R-cancel "
              f"(DSR {roll['cancel_r']:.3f} s − 0.33 ≈ {roll['cancel_r'] - 0.33:.2f})",
              lag is not None and rs[1]["buffered"] and abs(lag - (roll["cancel_r"] - 0.33)) < 0.08)
        time.sleep(2.8)

        # 4. swept hit: one light attack at 1.3 m → one hit, in the DSR attack window
        st = face_dummy_from(tm, pad, 1.4)
        hp0, hits0 = st["dummy"]["hp"], st["player_hits"]
        pad.press("rb", 0.05)
        st = wait_for(tm, lambda s: s["player_hits"] > hits0, tmax=2.0)
        check(f"light attack hit the dummy at anim_time {st['anim_time'] if st else None} "
              f"(DSR window {act['light']['attack'][0]})",
              st is not None and act["light"]["attack"][0][0] - 0.02 <= st["anim_time"] <= act["light"]["attack"][0][1] + 0.02)
        time.sleep(2.0)
        st = tm.state()
        check(f"one hit per swing: dummy HP {hp0} → {st['dummy']['hp']} ({dmg} a hit), hits +{st['player_hits'] - hits0}",
              st["player_hits"] - hits0 == 1 and hp0 - st["dummy"]["hp"] == dmg)

        # 5. the dummy's swing: standing still → hit + stagger; rolling into it with i-frames up → dodged
        st = face_dummy_from(tm, pad, 1.6)
        hp0 = st["hp"]
        st = wait_for(tm, lambda s: s["dummy"]["phase"] == "active", tmax=8.0)
        st = wait_for(tm, lambda s: s["dummy"]["phase"] == "recover", tmax=2.0)
        time.sleep(0.05)
        st = tm.state()
        check(f"standing in its swing → hit: HP {hp0} → {st['hp']}, stagger {st['stagger']}", st["hp"] == hp0 - 120)
        time.sleep(1.0)
        d0 = st["dodged"]
        st = wait_for(tm, lambda s: s["dummy"]["phase"] == "windup", tmax=8.0)
        t_w = time.time()
        while time.time() - t_w < 0.55:                     # windup 0.7 s → roll so its i-frames (0–0.367 s) cover the swing
            time.sleep(0.005)
        pad.move(0.0, 0.6)                                   # roll toward it (through its swing)
        pad.press("b", 0.04)
        time.sleep(0.05)
        pad.move(0.0, 0.0)
        st = wait_for(tm, lambda s: s["dummy"]["phase"] == "recover", tmax=2.0)
        time.sleep(0.05)
        st = tm.state()
        check(f"rolled through its swing inside the i-frames → dodged {st['dodged'] - d0}, HP stays {st['hp']}",
              st["dodged"] - d0 == 1 and st["hp"] == hp0 - 120)
        print("godot_combat_test: 전부 통과")
    finally:
        pad.neutral()
        pad.close()
        proc.terminate()
        tm.close()


if __name__ == "__main__":
    main()
