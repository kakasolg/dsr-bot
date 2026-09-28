"""Controller state for the radar — reads XInput (read-only) so the page shows the sticks and buttons actually pressed.

The bot's virtual pad (vgamepad / ViGEmBus) is an ordinary Xbox pad to Windows, so the same read shows a human's input
and the bot's input. Only XInputGetState is called (no XInputSetState, no vibration, nothing sent) — like observe_record.py.
Changes are posted as {"type": "pad", "i": slot, "btn", "lt", "rtr", "lx", "ly", "rx", "ry"} (raw XInput values;
"rtr" = right trigger, since "rt" is the recording's time key). Not Windows → nothing, or a demo pattern with demo=True.
"""
from __future__ import annotations

import ctypes
import math
import sys
import threading
import time

POLL_HZ = 60.0
FIELDS = ("btn", "lt", "rtr", "lx", "ly", "rx", "ry")

# XInput button bits (same as observe_record.py's "btn")
BUTTONS = {"up": 0x1, "down": 0x2, "left": 0x4, "right": 0x8, "start": 0x10, "back": 0x20, "ls": 0x40, "rs": 0x80,
           "lb": 0x100, "rb": 0x200, "a": 0x1000, "b": 0x2000, "x": 0x4000, "y": 0x8000}


class _GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", ctypes.c_ushort), ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short), ("sThumbRY", ctypes.c_short)]


class _STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", _GAMEPAD)]


def _xinput():
    for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
        try:
            return getattr(ctypes.windll, name).XInputGetState
        except (AttributeError, OSError):
            continue
    return None


def read_all(get_state) -> dict[int, dict]:
    """{slot: pad fields} for connected controllers."""
    out = {}
    for i in range(4):
        st = _STATE()
        if get_state(i, ctypes.byref(st)) == 0:
            g = st.Gamepad
            out[i] = {"btn": g.wButtons, "lt": g.bLeftTrigger, "rtr": g.bRightTrigger,
                      "lx": g.sThumbLX, "ly": g.sThumbLY, "rx": g.sThumbRX, "ry": g.sThumbRY}
    return out


def demo_pad(t: float) -> dict:
    """A moving pattern for --demo: left stick circling, RB tapped every 2.5 s, LB held in bursts."""
    btn = (BUTTONS["rb"] if (t % 2.5) < 0.15 else 0) | (BUTTONS["lb"] if (t % 6) > 3 else 0)
    return {"btn": btn, "lt": 0, "rtr": 255 if (t % 7) < 0.3 else 0,
            "lx": int(24000 * math.sin(t)), "ly": int(24000 * math.cos(t)), "rx": int(12000 * math.sin(t / 3)), "ry": 0}


def start(post, demo: bool = False) -> bool:
    """Poll in a daemon thread, post(msg) on every change. → False if there's nothing to read."""
    get_state = _xinput() if sys.platform == "win32" else None
    if get_state is None and not demo:
        return False
    last: dict[int, dict] = {}
    t0 = time.time()

    def loop():
        while True:
            try:
                now = read_all(get_state) if get_state is not None else {0: demo_pad(time.time() - t0)}
            except Exception:
                now = {}
            for i, v in now.items():
                if last.get(i) != v:
                    last[i] = v
                    post({"type": "pad", "i": i, **v})
            for i in [i for i in last if i not in now]:        # disconnected (e.g. the bot's virtual pad after a run)
                del last[i]
                post({"type": "pad", "i": i, "gone": True})
            time.sleep(1.0 / POLL_HZ)

    threading.Thread(target=loop, daemon=True, name="radar-pad").start()
    return True
