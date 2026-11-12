"""Parish → Firelink elevator in the room (MoKa M1111-35): a body standing on the car at the top rides it down to the measured
bottom height and stays on it; a body beside the car (on the floor strip at the door) is not taken. Headless room on
sim/godot/assets/firelink_loop_scene.json (python sim/burg_scene.py --loop); skipped without Godot or the scene.
The room's own rules only — not DSR.   python tests/godot_elevator_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent.parent / "sim")]

import json
import os
import subprocess
import time

import pytest

os.environ.setdefault("BOT_GAME", "sim")
import godot_link as GL

SCENE = GL.PROJECT / "assets" / "firelink_loop_scene.json"


def _ride(start: list[float], wait_s: float) -> list[tuple]:
    sc = json.loads(SCENE.read_text(encoding="utf-8"))
    sc.update({"name": "elevator_test", "start": start, "start_heading": 1.5708})
    (GL.PROJECT / "assets" / "_walk_from_scene.json").write_text(json.dumps(sc), encoding="utf-8")
    tm = GL.room_telemetry()
    pad = GL.room_pad()
    room = subprocess.Popen([str(GL.GODOT), "--headless", "--path", str(GL.PROJECT), "res://ramp.tscn", "--", "--scene=_walk_from"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = []
    try:
        t0 = time.time()
        while tm.snapshot() is None and time.time() - t0 < 90:
            time.sleep(0.3)
        t1 = time.time()
        while time.time() - t1 < wait_s:
            s = tm.snapshot()
            out.append((round(time.time() - t1, 1), s.player.x, s.player.y, s.player.z, (tm.last or {}).get("elevator")))
            time.sleep(0.25)
    finally:
        pad.neutral()
        pad.close()
        room.kill()
        time.sleep(1)
    return out


def test_elevator():
    if not GL.GODOT.exists() or not SCENE.exists():
        pytest.skip("no Godot or no firelink_loop scene (python sim/burg_scene.py --loop)")
    E = json.loads(SCENE.read_text(encoding="utf-8"))["elevators"][0]
    tr = _ride([E["at"][0] + 0.5, E["y_top"] + 0.03, E["at"][1]], 30.0)
    last = tr[-1]
    print("on the car:", tr[::20], "last", last)
    assert last[4] == "bottom", last
    assert abs(last[2] - E["y_bot"]) < 0.3, last              # rode it all the way down
    assert abs(last[1] - (E["at"][0] + 0.5)) < 0.3, last      # still on the car, not slid off
    tr = _ride([E["at"][0] + E["half"] + 0.6, 28.47, E["at"][1]], 6.0)
    print("beside the car:", tr[-1])
    assert tr[-1][4] == "top" and abs(tr[-1][2] - 28.47) < 0.3, tr[-1]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-s"]))
