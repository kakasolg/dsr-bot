"""Walk the character from the Undead Burg bonfire to the Taurus bridge in the practice room, no foes (MoKa M1111-27).

  python sim/burg_walk.py [--headless] [--mode walk|sprint] [--hold 20] [--ladders] [--scene burg|firelink_taurus|firelink_demon]

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


def _view_watch(tm, stop: list, out: dict) -> None:
    """Viewer camera state from the room's packets ("view", ramp.gd _update_view) every 0.1 s → section changes with time and
    place, how often it was off the planned route, the largest wall pull (MoKa M1111-34)."""
    import threading

    def run():
        t0, prev, n, off, pull = time.time(), None, 0, 0, 0.0
        while not stop[0]:
            d = getattr(tm, "last", None) or {}
            v = d.get("view") or {}
            if v:
                n += 1
                off += int(v.get("idx", 0)) < 0
                pull = max(pull, float(v.get("pull", 0.0)))
                cur = v["mode"] if v.get("mode") == "ladder" else v.get("prof")
                if cur != prev:
                    out["changes"].append([round(time.time() - t0, 1), cur, [round(d.get("x", 0), 1), round(d.get("y", 0), 1), round(d.get("z", 0), 1)]])
                    prev = cur
            out.update({"samples": n, "off_route": off, "max_pull": round(pull, 2)})
            time.sleep(0.1)
    threading.Thread(target=run, daemon=True).start()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--mode", default="walk", choices=("walk", "sprint"))
    ap.add_argument("--hold", type=float, default=3.0, help="seconds the window stays after the last leg")
    ap.add_argument("--ladders", action="store_true", help="also climb each ladder up and back down (M1111-30)")
    ap.add_argument("--scene", default="burg", choices=("burg", "firelink_taurus", "firelink_demon", "firelink_loop"),
                    help="firelink_taurus = from the Firelink Shrine bonfire (python sim/burg_scene.py --full, M1111-31)")
    ap.add_argument("--from", dest="from_leg", type=int, default=1,
                    help="start at leg N (the room starts at the end of leg N-1; scene copy _walk_from_scene.json)")
    ap.add_argument("--room-arg", action="append", default=[],
                    help="passed on to the room, e.g. --room-arg=--cam=play or --room-arg=--view-snaps=<dir>,4")
    a = ap.parse_args()
    os.environ["BOT_GAME"] = "sim"
    import godot_link as GL
    import navmesh
    from souls import moves

    sc = json.loads((GL.PROJECT / "assets" / f"{a.scene}_scene.json").read_text(encoding="utf-8"))
    room_scene = a.scene
    if a.from_leg > 1:                                       # a copy that starts further on: only the later legs
        legs0 = sc.get("legs") or [{"name": f"구간 {i}", "kind": "find", "map": "B", "pts": [q]}
                                   for i, q in enumerate(sc["route"][1:], 1)]
        sc["start"] = legs0[a.from_leg - 2]["pts"][-1]
        sc["legs"] = legs0[a.from_leg - 1:]
        room_scene = "_walk_from"
        (GL.PROJECT / "assets" / "_walk_from_scene.json").write_text(json.dumps(sc), encoding="utf-8")
    GL.ensure_imported()
    exe = GL.GODOT if a.headless else GL.GODOT.with_name(GL.GODOT.name.replace("_console", ""))
    args = [str(exe), "--path", str(GL.PROJECT), "res://ramp.tscn", "--", f"--scene={room_scene}"] + a.room_arg
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
        nms = {"A": GL.room_navmesh("m10_02_00_00"), "B": GL.room_navmesh("m10_01_00_00")}   # as souls/missions.py MAP_A / MAP_B
        #                                                    (game folder, else the repo's exported .npz — cloud)
        mv = moves.Moves(tm, pad)
        legs = sc.get("legs") or [{"name": f"구간 {i}", "kind": "find", "map": "B", "pts": [q]}
                                  for i, q in enumerate(sc["route"][1:], 1)]
        lads = [L for L in sc.get("ladders", [])] if a.ladders else []
        t_all = time.time()
        view = {"changes": []}
        vstop = [False]
        _view_watch(tm, vstop, view)
        for i, leg in enumerate(legs, 1):
            s = tm.snapshot()
            here = (s.player.x, s.player.y, s.player.z)
            for L in list(lads):                            # a ladder whose bottom is right here → up and back down first
                if math.dist((here[0], here[2]), tuple(L["at"])) < 6.0 and abs(here[1] - L["y_bot"]) < 2.5:
                    rows.append(ladder_round_trip(tm, pad, mv, nms["B"], L))
                    lads.remove(L)
            s = tm.snapshot()
            here = (s.player.x, s.player.y, s.player.z)
            nm = nms[leg["map"]]
            goal = tuple(leg["pts"][-1])
            if leg["kind"] == "board":                      # straight into an elevator car with the stick (M1111-35)
                t1 = time.time()
                E = min(sc.get("elevators", []), key=lambda e: math.dist(e["at"], (goal[0], goal[2])))
                inside = E["half"] - 0.4                    # [guess] margin so the body doesn't stop on the edge
                res = "timeout"
                for q in leg["pts"]:
                    t2 = time.time()
                    while time.time() - t2 < 8.0:
                        s = tm.snapshot()
                        on = (abs(s.player.x - E["at"][0]) <= inside and abs(s.player.z - E["at"][1]) <= inside
                              and abs(s.player.y - E["y_top"]) < 0.5)
                        if on:
                            res = "arrived"
                            break
                        if math.hypot(s.player.x - q[0], s.player.z - q[2]) < 0.5:
                            break
                        pad.move(*mv.stick_to(s, q[0], q[2], 0.6))
                        time.sleep(0.05)
                    if res == "arrived":
                        break
                pad.neutral()
                s = tm.snapshot()
                end = (s.player.x, s.player.y, s.player.z)
                gap = math.dist(end, goal)
                rows.append({"leg": i, "name": leg["name"], "map": leg["map"], "kind": "board", "goal": list(goal), "res": res,
                             "s": round(time.time() - t1, 1), "end": [round(v, 2) for v in end], "gap": round(gap, 2)})
                print(f"{i:2d} {leg['name']} (board): {res} · {time.time() - t1:5.1f} s · 끝 {tuple(round(v, 1) for v in end)} · "
                      f"목표까지 {gap:.1f} m", flush=True)
                if res != "arrived":
                    print("   바닥판에 못 올라섬 — 여기서 멈춤", flush=True)
                    break
                continue
            if leg["kind"] == "ride":                       # stand still on the car until it is down (M1111-35)
                t1 = time.time()
                pad.neutral()
                last, still, res = None, 0, "timeout"
                while time.time() - t1 < 60.0:
                    s = tm.snapshot()
                    y = s.player.y
                    still = still + 1 if last is not None and abs(y - last) < 0.01 else 0
                    last = y
                    if abs(y - goal[1]) < 0.3 and still >= 5:
                        res = "arrived"
                        break
                    time.sleep(0.1)
                s = tm.snapshot()
                end = (s.player.x, s.player.y, s.player.z)
                gap = math.dist(end, goal)
                rows.append({"leg": i, "name": leg["name"], "map": leg["map"], "kind": "ride", "goal": list(goal), "res": res,
                             "s": round(time.time() - t1, 1), "m": round(abs(here[1] - goal[1]), 1),
                             "end": [round(v, 2) for v in end], "gap": round(gap, 2)})
                print(f"{i:2d} {leg['name']} (ride): {res} · {time.time() - t1:5.1f} s · 높이 {here[1]:.1f} → {end[1]:.1f} · 목표까지 {gap:.1f} m",
                      flush=True)
                if gap > 3.0:
                    print("   목표 3 m 밖 — 여기서 멈춤", flush=True)
                    break
                continue
            if leg["kind"] == "follow":                     # the recorded points as they are, from the nearest one (_to_merchant)
                k = min(range(len(leg["pts"])), key=lambda j: math.dist(leg["pts"][j], here))
                path = [tuple(q) for q in leg["pts"][k:]]
            else:
                path = nm.find_path(here, goal)
            length = sum(math.dist(p, q) for p, q in zip([here] + list(path or []), path or [])) if path else 0.0
            t1 = time.time()
            res = mv.walk_path(path, nm, mode=a.mode, tol=0.8, timeout_per=12.0) if path else "no path"
            pad.neutral()
            s = tm.snapshot()
            end = (s.player.x, s.player.y, s.player.z)
            gap = math.dist(end, goal)
            rows.append({"leg": i, "name": leg["name"], "map": leg["map"], "kind": leg["kind"], "goal": list(goal), "res": res,
                         "s": round(time.time() - t1, 1), "m": round(length, 1), "end": [round(v, 2) for v in end],
                         "gap": round(gap, 2)})
            print(f"{i:2d} {leg['name']} ({leg['map']}·{leg['kind']}): {res} · {time.time() - t1:5.1f} s · 경로 {length:5.1f} m · 끝 "
                  f"{tuple(round(v, 1) for v in end)} · 목표까지 {gap:.1f} m", flush=True)
            if gap > 3.0:
                print("   목표 3 m 밖 — 여기서 멈춤", flush=True)
                break
        print(f"전체 {time.time() - t_all:.0f} s", flush=True)
        vstop[0] = True
        ch = view["changes"]
        gaps = [b[0] - a[0] for a, b in zip(ch, ch[1:])]
        print(f"보는 카메라: 구간 바뀜 {max(0, len(ch) - 1)}번 · 가장 짧은 유지 {min(gaps) if gaps else 0:.1f} s · 경로 밖 "
              f"{view.get('off_route', 0)}/{view.get('samples', 0)} 표본 · 벽에 당겨진 최대 {view.get('max_pull', 0)} m", flush=True)
        for c in ch:
            print(f"   {c[0]:6.1f} s {c[1]:9s} {tuple(c[2])}", flush=True)
        rows.append({"view": view})
        time.sleep(a.hold)
    finally:
        pad.neutral()
        pad.close()
        room.kill()
    out = ROOT / "data" / "runs" / f"{time.strftime('%Y%m%d_%H%M%S')}_room-{a.scene.replace('_', '-')}-walk.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
