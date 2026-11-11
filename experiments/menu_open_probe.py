"""When does the menu count as open? (quit-out speed) — START, then time three signals, then B out. Never presses A.

  python experiments/menu_open_probe.py [times]

Per try, ms after START is pressed: flag = tm.menu_open() true, screen = quitout._screen() differs from before START,
text = the item tab's description matches data/ui/itemtab.npy (what quit_out waits for now, polled ~33 ms a grab).
If screen tracks text, quit_out's start step can wait on the screen value instead of grabbing the screen.
"""
from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("BOT_GAME", "dsr")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env
import quitout
from botlock import BotLock

B = quitout.B


def one(tm, pad) -> dict:
    while tm.menu_open():
        quitout.close_menu(tm, pad)
    time.sleep(0.5)
    s0 = quitout._screen(tm)
    t0 = time.perf_counter()
    pad.press(B.XUSB_GAMEPAD_START, quitout.HOLD)
    got: dict = {}
    vals = []
    while time.perf_counter() - t0 < 1.5 and len(got) < 3:
        ms = round((time.perf_counter() - t0) * 1000)
        if "flag" not in got and tm.menu_open():
            got["flag"] = ms
        sc = quitout._screen(tm)
        if sc != s0 and (not vals or vals[-1][1] != sc):
            vals.append((ms, sc))
        if "screen" not in got and sc != s0:
            got["screen"] = ms
        if "text" not in got and quitout._is_screen("itemtab") is True:
            got["text"] = ms
    got["screen_values"] = [(ms, hex(v) if v is not None else None) for ms, v in vals[:4]]
    quitout.close_menu(tm, pad)
    return got


def left_after(tm, pad, delay: float) -> str:
    """START → delay → LEFT → 0.5 s → which tab? 'sys' (LEFT taken) / 'item' (eaten) / '?' — then B out. Never A."""
    while tm.menu_open():
        quitout.close_menu(tm, pad)
    time.sleep(0.6)
    t0 = time.perf_counter()
    pad.press(B.XUSB_GAMEPAD_START, quitout.HOLD)
    while time.perf_counter() - t0 < delay:
        time.sleep(0.002)
    pad.press(B.XUSB_GAMEPAD_DPAD_LEFT, quitout.HOLD)
    time.sleep(0.5)
    r = "sys" if quitout._is_screen("systab") is True else "item" if quitout._is_screen("itemtab") is True else "?"
    quitout.close_menu(tm, pad)
    return r


def main_left(delays: list[float], n: int) -> None:
    """python experiments/menu_open_probe.py left [n] — shortest START→LEFT delay the menu takes."""
    lock = BotLock()
    for _ in range(10):
        if lock.acquire():
            break
        time.sleep(0.2)
    else:
        raise SystemExit("a bot is running (data/bot.lock)")
    pad = None
    try:
        tm = env.make_telemetry({})
        control.focus_game()
        pad = control.Pad()
        pad.neutral()
        for d in delays:
            res = [left_after(tm, pad, d) for _ in range(n)]
            print(f"START→LEFT {d * 1000:.0f} ms (press start to press start): {res.count('sys')}/{n} taken  {res}", flush=True)
    finally:
        if pad is not None:
            pad.neutral()
            pad.close()
        lock.release()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "left":    # left [n] [delay ms …]
        ds = [float(x) / 1000 for x in sys.argv[3:]] or [0.08, 0.11, 0.14, 0.17, 0.20]
        return main_left(ds, int(sys.argv[2]) if len(sys.argv) > 2 else 5)
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    lock = BotLock()
    for _ in range(10):
        if lock.acquire():
            break
        time.sleep(0.2)
    else:
        raise SystemExit("a bot is running (data/bot.lock)")
    pad = None
    try:
        tm = env.make_telemetry({})
        control.focus_game()
        pad = control.Pad()
        pad.neutral()
        rows = []
        for i in range(n):
            r = one(tm, pad)
            rows.append(r)
            print(f"{i + 1}: flag {r.get('flag')} ms · screen {r.get('screen')} ms · text {r.get('text')} ms · {r['screen_values']}")
            time.sleep(0.6)
        for k in ("flag", "screen", "text"):
            v = [r[k] for r in rows if r.get(k) is not None]
            if v:
                print(f"{k}: median {statistics.median(v):.0f} ms, range {min(v)}–{max(v)} ({len(v)}/{n})")
    finally:
        if pad is not None:
            pad.neutral()
            pad.close()
        lock.release()


if __name__ == "__main__":
    main()
