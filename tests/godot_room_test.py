"""Godot practice room, stage 0 (MoKa M1109-47/50): the bot's own stick math (control.world_to_stick, nav constants)
walks from the altar bonfire to the saved lever spot (data/spots.json altar-lever), the A prompt shows only there,
A pulls the lever and the gate opens. Runs the room headless; skipped when Godot isn't installed.

This checks the room and the bot's stick math against the room — not DSR. The room's values are tagged
[game]/[meas]/[guess] in sim/godot/main.gd.   python tests/godot_room_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

import json
import math
import time

import control
import nav
from sim import godot_link as GL

ROOT = _pl.Path(__file__).resolve().parent.parent


def check(msg: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        raise SystemExit(1)


def go(tm, pad, x, z, scale=0.55, tol=0.15, tmax=12.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < tmax:
        s = tm.snapshot()
        p = s.player
        if math.hypot(p.x - x, p.z - z) < tol:
            break
        st = control.world_to_stick(x - p.x, z - p.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
        pad.move(st[0] * scale, st[1] * scale)
        time.sleep(1 / 60)
    pad.move(0.0, 0.0)
    time.sleep(0.4)
    return tm.state()


def main() -> None:
    if not GL.GODOT.exists():
        print(f"skip: Godot not found at {GL.GODOT}")
        return
    spot = json.loads((ROOT / "data/spots.json").read_text(encoding="utf-8"))["altar-lever"]
    tm = GL.SimTelemetry()
    pad = GL.SimPad()
    proc = GL.start_room(headless=True)
    try:
        st = tm.state(wait=20.0)
        check("room is up and sends state", st is not None)
        check("starts at the bonfire stand, no prompt", math.hypot(st["x"] - 23.8, st["z"] + 23.0) < 0.3 and not st["prompt"])
        a = spot["approach"]["stand"]
        st = go(tm, pad, a[0], a[2])
        print(f"  approach: {st['x']:.2f} {st['z']:.2f} h {st['heading']:.2f}  {st['prompt_why']}")
        check("approach point (2.7 m from the action point) → no prompt", not st["prompt"])
        s = spot["stand"]
        st = go(tm, pad, s[0], s[2], tol=0.12)
        print(f"  stand:    {st['x']:.2f} {st['z']:.2f} h {st['heading']:.2f}  {st['prompt_why']}")
        check("saved lever stand, walked in from the approach → A 'Pull lever'", st["prompt"] and st["prompt_text"] == "Pull lever")
        pad.interact()
        time.sleep(0.3)
        st = tm.state()
        check("A → lever pulled, pull anim 8000", st["lever"] and st["anim"] == 8000)
        time.sleep(3.5)
        st = tm.state()
        check(f"gate opens ({st['gate_open']:.0%})", st["gate_open"] >= 0.99)
        print("godot_room_test: 전부 통과")
    finally:
        pad.neutral()
        proc.terminate()
        tm.close()


if __name__ == "__main__":
    main()
