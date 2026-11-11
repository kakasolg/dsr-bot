"""Walk the character from the Undead Burg bonfire to the Taurus bridge in the practice room, no foes (MoKa M1111-27).

  python sim/burg_walk.py [--headless] [--mode walk|sprint] [--hold 20]

Starts the room on burg_scene.json (`python sim/burg_scene.py` first), then walks each leg of the scene's route with the
bot's own Moves.walk_path on the m10_01 NavMesh (the room's pad and telemetry, as `BOT_GAME=sim`). Prints per leg: result,
seconds, metres, where it ended. Room only — it never touches the game.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sim"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--mode", default="walk", choices=("walk", "sprint"))
    ap.add_argument("--hold", type=float, default=3.0, help="seconds the window stays after the last leg")
    a = ap.parse_args()
    os.environ["BOT_GAME"] = "sim"
    import godot_link as GL
    import navmesh
    from souls import moves

    sc = json.loads((GL.PROJECT / "assets" / "burg_scene.json").read_text(encoding="utf-8"))
    GL.ensure_imported()
    exe = GL.GODOT if a.headless else GL.GODOT.with_name(GL.GODOT.name.replace("_console", ""))
    args = [str(exe), "--path", str(GL.PROJECT), "res://ramp.tscn", "--", "--scene=burg"]
    if a.headless:
        args.insert(1, "--headless")
    room = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tm = GL.room_telemetry()
    pad = GL.room_pad()
    rows = []
    try:
        t0 = time.time()
        while tm.snapshot() is None and time.time() - t0 < 90:
            time.sleep(0.3)
        time.sleep(1.5)                                     # first frames after load are slow (godot_stamina_test)
        nm = navmesh.Navmesh("m10_01_00_00")
        mv = moves.Moves(tm, pad)
        pts = sc["route"]
        for i, goal in enumerate(pts[1:], 1):
            s = tm.snapshot()
            here = (s.player.x, s.player.y, s.player.z)
            path = nm.find_path(here, tuple(goal))
            length = sum(math.dist(p, q) for p, q in zip(path, path[1:])) if path else 0.0
            t1 = time.time()
            res = mv.walk_path(path, nm, mode=a.mode, tol=0.8, timeout_per=12.0) if path else "no path"
            pad.neutral()
            s = tm.snapshot()
            end = (s.player.x, s.player.y, s.player.z)
            gap = math.dist(end, goal)
            rows.append({"leg": i, "goal": goal, "res": res, "s": round(time.time() - t1, 1), "m": round(length, 1),
                         "end": [round(v, 2) for v in end], "gap": round(gap, 2)})
            print(f"구간 {i:2d} → {tuple(goal)}: {res} · {time.time() - t1:5.1f} s · 경로 {length:5.1f} m · 끝 "
                  f"{tuple(round(v, 1) for v in end)} · 목표까지 {gap:.1f} m", flush=True)
            if gap > 3.0:
                print("   목표 3 m 밖 — 여기서 멈춤", flush=True)
                break
        time.sleep(a.hold)
    finally:
        pad.neutral()
        pad.close()
        room.kill()
    out = ROOT / "data" / "runs" / f"{time.strftime('%Y%m%d_%H%M%S')}_room-burg-walk.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
