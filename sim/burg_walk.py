"""Walk the character from the Undead Burg bonfire to the Taurus bridge in the practice room, no foes (MoKa M1111-27).

  python sim/burg_walk.py [--headless] [--mode walk|sprint] [--hold 20] [--ladders]

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
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sim"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _face(tm, pad, mv, fx: float, fz: float, limit: float = 1.5) -> float:
    """Turn the body toward world direction (fx, fz) with the stick (0.55, as souls/missions.py ladder facing) → degrees off."""
    from souls import moves as M
    t0, off = time.time(), 180.0
    while time.time() - t0 < limit:
        s = tm.snapshot()
        c = types.SimpleNamespace(x=s.player.x + fx, z=s.player.z + fz)
        off = abs(math.degrees(M.rel_angle(s.player, c)))
        if off <= 20.0:
            break
        pad.move(*mv.stick_to(s, c.x, c.z, 0.55))
        time.sleep(0.05)
    pad.move(0.0, 0.0)
    time.sleep(0.15)
    return off


def _hold_stick(tm, pad, y: float, until, limit: float) -> tuple[float, list]:
    """Stick (0, y) until until(snapshot) or limit s → (seconds, ladder anims seen in order)."""
    t0, seen = time.time(), []
    while time.time() - t0 < limit:
        pad.move(0.0, y)
        time.sleep(0.05)
        s = tm.snapshot()
        an = int(s.player.anim)
        if 7000 <= an < 7100 and (not seen or seen[-1] != an):
            seen.append(an)
        if until(s):
            break
    return time.time() - t0, seen


def ladder_round_trip(tm, pad, mv, nm, L: dict) -> dict:
    """Up then back down one ladder the way the bot does it (souls/missions.py _before 'ladder': stand at the bottom, face the
    ladder, A, stick up until the top; then at the top face the ladder, A, stick down) — room only (MoKa M1111-30)."""
    fx, fz = L["face"]
    ax, az = L["at"]
    bottom = (ax - fx * 0.1, L["y_bot"], az - fz * 0.1)
    s = tm.snapshot()
    path = nm.find_path((s.player.x, s.player.y, s.player.z), bottom)
    res = mv.walk_path(path, nm, mode="walk", tol=0.4, timeout_per=12.0) if path else "no path"
    pad.neutral()
    row = {"ladder": L["name"], "walk": res}
    off = _face(tm, pad, mv, fx, fz)
    pad.interact()
    up_s, up_seen = _hold_stick(tm, pad, 1.0, lambda q: q.player.y >= L["y_top"] - 0.1 and int(q.player.anim) < 7000, 15.0)
    pad.neutral()
    s = tm.snapshot()
    row.update({"face_off": round(off), "up_s": round(up_s, 1), "up_anims": up_seen, "top": [round(s.player.x, 2), round(s.player.y, 2), round(s.player.z, 2)]})
    print(f"사다리 {L['name']} 오르기: {up_s:4.1f} s · 애니 {up_seen} · 위 {tuple(row['top'])}", flush=True)
    time.sleep(1.0)
    off2 = _face(tm, pad, mv, -fx, -fz)
    pad.interact()
    dn_s, dn_seen = _hold_stick(tm, pad, -1.0, lambda q: q.player.y <= L["y_bot"] + 0.1 and int(q.player.anim) < 7000, 20.0)
    pad.neutral()
    s = tm.snapshot()
    row.update({"face_off2": round(off2), "down_s": round(dn_s, 1), "down_anims": dn_seen, "bottom": [round(s.player.x, 2), round(s.player.y, 2), round(s.player.z, 2)]})
    print(f"사다리 {L['name']} 내리기: {dn_s:4.1f} s · 애니 {dn_seen} · 아래 {tuple(row['bottom'])}", flush=True)
    time.sleep(0.5)
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--mode", default="walk", choices=("walk", "sprint"))
    ap.add_argument("--hold", type=float, default=3.0, help="seconds the window stays after the last leg")
    ap.add_argument("--ladders", action="store_true", help="also climb each ladder up and back down (M1111-30)")
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
    tm = GL.room_telemetry()                                # ports first: a clash (another room / test) fails before a room starts
    pad = GL.room_pad()
    room = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rows = []
    try:
        t0 = time.time()
        while tm.snapshot() is None and time.time() - t0 < 90:
            time.sleep(0.3)
        time.sleep(1.5)                                     # first frames after load are slow (godot_stamina_test)
        nm = navmesh.Navmesh("m10_01_00_00")
        mv = moves.Moves(tm, pad)
        pts = sc["route"]
        lads = {L["name"]: L for L in sc.get("ladders", [])}
        if a.ladders and "burg-bonfire" in lads:
            rows.append(ladder_round_trip(tm, pad, mv, nm, lads["burg-bonfire"]))
        for i, goal in enumerate(pts[1:], 1):
            if a.ladders and i == len(pts) - 1 and "taurus" in lads:
                rows.append(ladder_round_trip(tm, pad, mv, nm, lads["taurus"]))     # past the fog, before the bridge
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
