"""P-73: a roll goes where it was aimed, and its floor is checked for the whole roll. No game.

  python tests/roll_test.py

20261012_033444 68.0 s: low_hp with 254001 + 254002 on us on the ramp → "빈틈 쪽 (-30°)" → the roll went −126° (the way the
character faced, off the ramp) → 22.4 m fall. The events file shows the camera turning toward the attacker during the roll
(align: cam −70° at 67.8 s, −10° at 68.39 s): Moves.roll_toward worked the camera-relative stick out once and held it while
CamFollow kept turning. Checks:
  · on the real ramp NavMesh (m10_02_00_00) at the decision spot: −30° had floor (old and new check agree), −126° had none
    — the floor check was not what failed; nav.can_move also follows the ramp down where the old 2-point check read a drop
  · roll_toward: camera held (cam_busy) from before the stick is worked out until the roll is under way, the stick from a
    fresh snapshot (not the caller's), a hit stagger waited out first, the stick let go once the roll anim starts,
    and the direction actually taken reported
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import math
import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import motion
import nav
from souls import moves as M


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def way(deg):
    a = math.radians(deg)
    return math.sin(a), math.cos(a)


def main() -> None:
    nm = motion.load_navmeshes()["m10_02_00_00"]
    at = NS(gx=-19.83, gy=-39.42, gz=15.68)                # the last snapshot before the decision (67.44 s)
    check("decision spot: −30° (meant) has floor for the whole roll — old check and can_move agree",
          nav.ground_ahead(nm, at, *way(-30), reach=2.5) and nav.can_move(nm, at, *way(-30), nav.ROLL_CHECK_M))
    check("decision spot: −126° (taken) has no floor — a 10 m drop", not nav.can_move(nm, at, *way(-126), nav.ROLL_CHECK_M))
    off = NS(gx=-20.4, gy=-39.56, gz=15.87)                # where the roll started, just off the mesh
    check("roll start (off the mesh): a gap 2 m out is not walked over", not nav.can_move(nm, off, *way(-30), nav.ROLL_CHECK_M))
    top = NS(gx=-19.73, gy=-39.61, gz=16.39)
    check("down the ramp 4 m: the old fixed-drop check calls it a drop, can_move follows the slope",
          not nav.ground_ahead(nm, top, *way(-30), reach=4.0) and nav.can_move(nm, top, *way(-30), 4.0))
    check("no terrain → True; zero direction → True", nav.can_move(None, at, 1, 0, 3) and nav.can_move(nm, at, 0, 0, 3))

    # roll_toward with a fake pad and a world that moves as the inputs say
    log, state = [], {"t": 0.0}
    cam = {"yaw": 0.0}
    me = {"x": 0.0, "z": 0.0, "anim": 2004}

    class Pad:
        def move(self, x, y):
            log.append(("move", round(x, 2), round(y, 2), mv.cam_busy))
            if (x, y) != (0.0, 0.0):
                state["stick"] = (x, y)

        def dodge(self):
            log.append(("dodge", mv.cam_busy))
            state["rolled_at"] = state["t"]

        def release_due(self):
            pass

    def snap(within=10.0):
        t = state["t"]
        if me["anim"] == 2004 and t > 0.3:
            me["anim"] = -1                                  # the stagger ends
        if "rolled_at" in state and t - state["rolled_at"] > 0.15 and me["anim"] != 710:
            me["anim"] = 710                                 # the roll starts: it goes where the stick points, in world terms
            sx, sy = state["stick"]
            yaw = cam["yaw"] + __import__("nav").YAW_OFFSET
            # inverse of control.world_to_stick for FLIP_X = False: world = rotate(stick) by the camera yaw
            wx = sx * math.cos(yaw) + sy * math.sin(yaw)
            wz = -sx * math.sin(yaw) + sy * math.cos(yaw)
            me["x"], me["z"] = me["x"] + 2.5 * wx, me["z"] + 2.5 * wz
        return NS(player=NS(x=me["x"], y=0.0, z=me["z"], anim=me["anim"], heading=0.0), cam_yaw=cam["yaw"], chars=[])

    class Clock:
        def time(self):
            return state["t"]

        def sleep(self, s):
            state["t"] += max(0.01, s)
            if not mv.cam_busy:
                cam["yaw"] += 0.5 * s                        # the camera thread keeps turning unless the camera is held

    real_time = M.time
    M.time = Clock()
    try:
        mv = M.Moves.__new__(M.Moves)
        mv.tm, mv.pad, mv.cam_busy, mv.snap = NS(), Pad(), False, snap
        stale = NS(player=NS(x=0.0, y=0.0, z=0.0, anim=2004, heading=0.0), cam_yaw=-1.2, chars=[])   # the caller's old view
        # the stick must map to world −30° at the camera's yaw when it is worked out
        if not hasattr(nav, "FLIP_X") or nav.FLIP_X:
            print("skip: stick inverse assumes FLIP_X False")
        aim = way(-30)
        r = mv.roll_toward(stale, 3.0 * aim[0], 3.0 * aim[1])
    finally:
        M.time = real_time
    moves = [e for e in log if e[0] == "move"]
    check("camera held for every stick input and the dodge", all(e[-1] for e in log))
    check("camera released afterwards", mv.cam_busy is False)
    check("stagger waited out before the stick (first stick after t 0.3)", moves and state.get("rolled_at", 0) > 0.3)
    check("stick let go (0, 0) once the roll anim started, before the 1.2 s hold", ("move", 0.0, 0.0, True) in log)
    check(f"rolled where it was aimed: meant {r['want']}°, took {r['got']}° (off {r['off']}°)",
          r["off"] is not None and r["off"] <= 5)
    print("roll_test: all ok")


if __name__ == "__main__":
    main()
