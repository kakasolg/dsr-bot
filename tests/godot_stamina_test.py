"""Practice room stamina (MoKa M1111-03/05/07): the room's player stamina follows the 11-11 DSR measurements at the
Titanite Demon — attack cost = the weapon's BehaviorParam StaminaCost (Claymore 1H R1 30), taken at the blade window,
not at the press; an attack still starts while stamina > 0 and drives it below 0; roll 30; regen 45 per s only when no
action runs; max stamina from `-- --max-sp=` (END 40 = 160, PDF 8-7). Runs the ramp room headless; skipped without Godot.

    python tests/godot_stamina_test.py

This checks the room against the measured values — not DSR itself."""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

import json
import subprocess
import time

import control
from sim import godot_link as GL
from godot_ramp_test import _stop, _stop_all

ROOT = _pl.Path(__file__).resolve().parent.parent
MAX_SP = 160.0           # END 40 [meas 11-11]


def check(msg: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        raise SystemExit(1)


def main() -> None:
    if not GL.GODOT.exists():
        print("skip — no Godot at", GL.GODOT)
        return
    act = json.loads((ROOT / "sim/godot/actions.json").read_text(encoding="utf-8"))["actions"]
    cost = float(act["light"]["hit"]["stamina"])
    blade = float(act["light"]["attack"][0][0])
    _stop_all()
    GL.ensure_imported()
    p = subprocess.Popen([str(GL.GODOT), "--headless", "--path", str(GL.PROJECT), "res://ramp.tscn", "--", f"--max-sp={MAX_SP:.0f}"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tm = GL.RoomTelemetry()
    pad = GL.room_pad()
    try:
        t0 = time.time()
        while tm.snapshot() is None and time.time() - t0 < 60:
            time.sleep(0.3)
        st = tm.state()
        check(f"room up, max stamina {st['max_sp']} from --max-sp (END 40 = 160)", st["max_sp"] == MAX_SP and st["sp"] == MAX_SP)
        # 자연 질감이 기본이 된 뒤(M1111-24) 방이 막 떠서 첫 프레임들이 느릴 때 R1이 씹힘 (RAMP_LOOK=dsr 에선 통과) — 잠깐 기다림
        time.sleep(1.5)

        # one swing: stamina stays until the blade window, then drops by the weapon's cost
        pad.press(control.B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.08)
        trace = []
        t0 = time.time()
        while time.time() - t0 < 1.4:
            s = tm.state()
            trace.append((s["action"], s["anim_time"], s["sp"]))
            time.sleep(0.01)
        before = [sp for a, at, sp in trace if a == "light" and at is not None and at < blade - 0.05]
        after = [sp for a, at, sp in trace if a == "light" and at is not None and at > blade + 0.05]
        check(f"light: stamina {MAX_SP:.0f} until the blade ({blade:.2f} s): {sorted(set(before))[:3]}", before and min(before) >= MAX_SP - 0.5)
        check(f"light: −{cost:.0f} (Claymore BehaviorParam) after the blade: {min(after):.1f}", after and abs(min(after) - (MAX_SP - cost)) < 1.0)

        # mash: swings until stamina ≤ 0, the last one drives it below 0 (160 → 130 … 10 → −20 = 6 swings)
        time.sleep(4.0)
        st = tm.state()
        check(f"regen back to full when idle ({st['sp']:.0f})", st["sp"] >= MAX_SP - 0.5)
        # each swing = one drop of the weapon's cost; stop pressing once stamina went below 0, before regen brings a new swing
        swings, low, prev = 0, MAX_SP, MAX_SP
        t0 = time.time()
        while time.time() - t0 < 9.0 and low > 0:
            pad.press(control.B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.05)
            t1 = time.time()
            while time.time() - t1 < 0.1:
                sp_now = tm.state()["sp"]
                if prev - sp_now > cost - 1.0:
                    swings += 1
                prev = sp_now
                low = min(low, sp_now)
                time.sleep(0.01)
        t1 = time.time()
        while time.time() - t1 < 1.5:                 # the last swing's blade may land after the loop
            sp_now = tm.state()["sp"]
            if prev - sp_now > cost - 1.0:
                swings += 1
            prev = sp_now
            low = min(low, sp_now)
            time.sleep(0.01)
        want = 0
        sp = MAX_SP
        while sp > 0:
            sp -= cost
            want += 1
        check(f"mash from full: {swings} swings before stamina ran out (want {want}), lowest {low:.0f} (want {MAX_SP - want * cost:.0f})",
              swings == want and abs(low - (MAX_SP - want * cost)) < 1.5)

        # regen 45 per s while idle
        pad.move(0.0, 0.0)
        time.sleep(1.0)
        a = tm.state()["sp"]
        time.sleep(1.0)
        b = tm.state()["sp"]
        check(f"regen {b - a:.1f} per s idle (DSR 45)", 40 <= b - a <= 50 or b >= MAX_SP - 0.5)

        # roll costs 30 at once
        time.sleep(4.0)
        s0 = tm.state()["sp"]
        pad.move(0.0, 0.7)
        pad.press(control.B.XUSB_GAMEPAD_B, 0.08)
        time.sleep(0.15)
        s1 = tm.state()["sp"]
        pad.move(0.0, 0.0)
        check(f"roll: {s0:.0f} → {s1:.0f} (DSR −30)", abs((s0 - s1) - 30.0) < 1.5)
        print("godot_stamina_test: 전부 통과")
    finally:
        pad.move(0.0, 0.0)
        pad.close()
        tm.close()
        _stop(p)


if __name__ == "__main__":
    main()
