"""Godot ramp room (MoKa M1109-65): the Firelink ramp with its six foes, for the bot (BOT_GAME=sim).

Offline part (no Godot): the scene file sim/godot/assets/ramp_scene.json (python sim/ramp_scene.py) has the six MSB
placements with their NpcParam / think ids and the measured values, #5's spot gets a pad, and RoomDev turns control.Pad's
button codes into the room's input keys. Room part (headless Godot, skipped when Godot or the scene file is missing):
a NavMesh path from the Firelink arrival stand up the ramp to #1 can be walked (the 3rd room run stuck at the ramp's
foot), #1 wakes inside its 9 m and hits the player, a guarded hit costs stamina instead of HP; with the player on #5's
ledge, #6 comes down its NavMesh route to within 4 m (MoKa M1109-66 — it stood on its ledge in the 5th room run).

This checks the room against its own rules — not DSR.   python tests/godot_ramp_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent.parent / "sim")]

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

import json
import math
import subprocess
import time

import control
import godot_link as GL

ROOT = _pl.Path(__file__).resolve().parent.parent
SCENE = ROOT / "sim" / "godot" / "assets" / "ramp_scene.json"
NPC = [254000, 255010, 254000, 254001, 254002, 254000]       # m10_02 MSB, data/enemy-map.json order
THINK = [254011, 255008, 254008, 254009, 254010, 254011]


def check(msg: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        raise SystemExit(1)


def offline() -> dict | None:
    dev = GL.RoomDev(port=1)                     # nothing listens on port 1; update() only sends
    dev._alive = False
    dev.press_button(0x0100)
    dev.press_button("XUSB_GAMEPAD_RIGHT_SHOULDER")
    sent = {}

    class _Sock:
        def sendto(self, b, a):
            sent.update(json.loads(b))
    dev.sock = _Sock()
    dev.update()
    check(f"RoomDev: LB and RB (int and name forms) reach the room as lb / rb ({sent.get('lb')}, {sent.get('rb')})",
          sent.get("lb") is True and sent.get("rb") is True and sent.get("a") is False)
    dev.release_button(0x0100)
    dev.update()
    check("RoomDev: release clears lb", sent.get("lb") is False)
    if not SCENE.exists():
        print("skip scene checks — no sim/godot/assets/ramp_scene.json (python sim/ramp_scene.py)")
        return None
    sc = json.loads(SCENE.read_text(encoding="utf-8"))
    foes = sc["foes"]
    check(f"six foes with the MSB NpcParam / think ids ({[f['npc'] for f in foes]})",
          [f["npc"] for f in foes] == NPC and [f["think"] for f in foes] == THINK)
    check("#5 (firebomb) stays and throws every 3.6 s, lands 2.5 s after [meas]",
          foes[4].get("stay") and foes[4]["throw"]["every"] == 3.6 and foes[4]["throw"]["land"] == 2.5)
    check("#5's spot has no NavMesh under it → the room puts a pad there", foes[4]["floor"] is False)
    check(f"every foe has attack windows from AtkParam ({[len(f['attacks']) for f in foes]})",
          all(len(f["attacks"]) >= 10 for f in foes))
    check(f"walls on open NavMesh edges ({len(sc['walls'])})", len(sc["walls"]) > 500)
    return sc


def room(sc: dict) -> None:
    import navmesh
    if not GL.GODOT.exists():
        print("skip room checks — no Godot at", GL.GODOT)
        return
    nm = navmesh.Navmesh("m10_02_00_00")
    rec = str(ROOT / "data" / "runs" / "godot_ramp_test_room.jsonl")
    # a room left by an earlier test (p.kill() stops the console wrapper, not its Godot child) keeps sending to the
    # same port and its packets mix with this room's — stop any Godot first (only the room uses it here)
    for exe in (GL.GODOT.name, GL.GODOT.name.replace("_console", "")):
        subprocess.run(["taskkill", "/F", "/IM", exe], capture_output=True)
    p = subprocess.Popen([str(GL.GODOT), "--headless", "--path", str(GL.PROJECT), "res://ramp.tscn"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tm = GL.RoomTelemetry(rec=rec)
    pad = GL.room_pad()
    try:
        t0 = time.time()
        while tm.snapshot() is None and time.time() - t0 < 60:
            time.sleep(0.3)
        s = tm.snapshot()
        check("room state arrives with six foes", s is not None and len(tm.state()["foes"]) == 6)
        goal = sc["foes"][0]["pos"]
        path = nm.find_path((s.player.x, s.player.y, s.player.z), tuple(goal))
        i, t0, woke_at = 0, time.time(), None
        while time.time() - t0 < 40 and i < len(path):
            s = tm.snapshot()
            pl, q = s.player, path[i]
            f1 = next(c for c in s.chars if c.ptr == 1001)
            if woke_at is None and next(f for f in tm.state()["foes"] if f["n"] == 1)["woke"]:
                woke_at = math.dist((pl.x, pl.y, pl.z), (f1.x, f1.y, f1.z))
            if math.dist((pl.x, pl.z), (f1.x, f1.z)) < 3.0:
                break
            dx, dz = q[0] - pl.x, q[2] - pl.z
            if math.hypot(dx, dz) < 0.6:
                i += 1
                continue
            pad.move(*control.world_to_stick(dx, dz, s.cam_yaw, 0.0, False))
            time.sleep(0.05)
        pad.move(0.0, 0.0)
        s = tm.snapshot()
        f1 = next(c for c in s.chars if c.ptr == 1001)
        d1 = math.dist((s.player.x, s.player.y, s.player.z), (f1.x, f1.y, f1.z))
        check(f"walked the NavMesh path up the ramp to #1 ({d1:.1f} m left, {time.time() - t0:.1f} s)", d1 < 4.0)
        check(f"#1 woke inside its 9 m battle start distance (at {woke_at})", woke_at is not None and woke_at <= 9.5)
        hp0, t1 = s.player.hp, time.time()
        while time.time() - t1 < 12 and tm.snapshot().player.hp >= hp0:
            time.sleep(0.05)
        hp1 = tm.snapshot().player.hp
        check(f"#1 hits the standing player within 12 s ({hp0} → {hp1})", hp1 < hp0)
        pad.guard(True)
        # since foes chase along the NavMesh (M1109-66) #3 reaches the player here too and its lunge comes from the side,
        # outside the shield — so the check is the packet where the guarded hit lands: stamina drops, HP doesn't
        sp0, t2 = tm.state()["sp"], time.time()
        took, hp2, hp3 = False, None, None
        while time.time() - t2 < 15:
            st = tm.state()
            if st["sp"] < sp0 - 20:
                took, hp3 = True, st["hp"]
                break
            sp0, hp2 = st["sp"], st["hp"]
            time.sleep(0.02)
        pad.guard(False)
        # a firebomb still takes 30 through the shield [meas] — more than that means a melee hit got through
        check(f"guarding: a hit from the front costs stamina ({took}), HP {hp2} → {hp3} in that packet (≤ 30)",
              took and hp3 >= hp2 - 30)
    finally:
        pad.move(0.0, 0.0)
        tm.close()
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
        _pl.Path(rec).unlink(missing_ok=True)


def room_six(sc: dict) -> None:
    import navmesh
    if not GL.GODOT.exists():
        return
    for exe in (GL.GODOT.name, GL.GODOT.name.replace("_console", "")):
        subprocess.run(["taskkill", "/F", "/IM", exe], capture_output=True)
    nm = navmesh.Navmesh("m10_02_00_00")
    rec = str(ROOT / "data" / "runs" / "godot_ramp_test_room6.jsonl")
    p = subprocess.Popen([str(GL.GODOT), "--headless", "--path", str(GL.PROJECT), "res://ramp.tscn"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tm = GL.RoomTelemetry(rec=rec)
    pad = GL.room_pad()
    try:
        t0 = time.time()
        while tm.snapshot() is None and time.time() - t0 < 60:
            time.sleep(0.3)
        s = tm.snapshot()
        ledge = (-19.1, -39.3, 15.2)                 # the bot's stand under #5's pad
        path = nm.find_path((s.player.x, s.player.y, s.player.z), ledge)
        pad.guard(True)
        i, t0, arrived, best = 0, time.time(), None, 99.0
        while time.time() - t0 < 45:
            s = tm.snapshot()
            pl = s.player
            f6 = next(f for f in tm.state()["foes"] if f["n"] == 6)
            d6 = math.dist((pl.x, pl.y, pl.z), (f6["x"], f6["y"], f6["z"]))
            if i >= len(path):
                pad.move(0.0, 0.0)
                arrived = arrived or time.time()
                best = min(best, d6)
                if d6 < 4.0 or time.time() - arrived > 10:
                    break
            else:
                q = path[i]
                dx, dz = q[0] - pl.x, q[2] - pl.z
                if math.hypot(dx, dz) < 0.6:
                    i += 1
                    continue
                pad.move(*control.world_to_stick(dx, dz, s.cam_yaw, 0.0, False))
            time.sleep(0.05)
        took = time.time() - arrived if arrived else None
        check(f"on #5's ledge, #6 comes down its NavMesh route to within 4 m ({best:.1f} m, "
              f"{took if took is None else round(took, 1)} s after the player got there)", best < 4.0)
    finally:
        pad.move(0.0, 0.0)
        tm.close()
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
        _pl.Path(rec).unlink(missing_ok=True)


def main() -> None:
    sc = offline()
    if sc is not None:
        room(sc)
        room_six(sc)


if __name__ == "__main__":
    main()
