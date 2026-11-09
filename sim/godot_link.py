"""Link to the Godot practice room (sim/godot, MoKa M1109-47/50) — the bot side.

  SimTelemetry.snapshot()  → telemetry.Snapshot built from the room's state packets (UDP 47811)
  SimPad                   → the subset of control.Pad the movement code uses, sent as UDP input (47812),
                             so a headless room can be driven without ViGEm. With a window, the bot's real
                             control.Pad works too (the room reads any Xbox pad).
  start_room(headless)     → runs Godot on sim/godot and returns the process.

Godot: D:/dev/tools/godot (GODOT_PATH overrides). Values in the room are tagged [game] / [meas] / [guess] in main.gd.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional

from telemetry import Chr, Snapshot

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "godot"
GODOT = Path(os.environ.get("GODOT_PATH", "D:/dev/tools/godot/Godot_v4.7.2-stable_win64_console.exe"))
STATE_PORT, INPUT_PORT = 47811, 47812


def start_room(headless: bool = True) -> subprocess.Popen:
    # the _console exe is a wrapper that starts the real exe as a child — fine headless, but a window then belongs to
    # another process; use the plain exe for a window
    exe = GODOT if headless else GODOT.with_name(GODOT.name.replace("_console", ""))
    args = [str(exe), "--path", str(PROJECT)]
    if headless:
        args.insert(1, "--headless")
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class SimTelemetry:
    def __init__(self, port: int = STATE_PORT):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", port))
        self.sock.setblocking(False)
        self.last: Optional[dict] = None

    def _drain(self) -> None:
        while True:
            try:
                data, _ = self.sock.recvfrom(65536)
            except (BlockingIOError, OSError):
                return
            self.last = json.loads(data)

    def state(self, wait: float = 2.0) -> Optional[dict]:
        end = time.time() + wait
        self._drain()
        while self.last is None and time.time() < end:
            time.sleep(0.01)
            self._drain()
        return self.last

    def snapshot(self, within: float = 60.0) -> Optional[Snapshot]:
        d = self.state()
        if d is None:
            return None
        p = Chr(ptr=1, npc_param=0, team=1, hp=1, max_hp=1, x=d["x"], y=d["y"], z=d["z"], anim=d["anim"],
                heading=d["heading"])
        return Snapshot(t=d["t"], player=p, chars=[], cam_yaw=d["cam_yaw"])

    def close(self) -> None:
        self.sock.close()


class SimPad:
    def __init__(self, port: int = INPUT_PORT):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addr = ("127.0.0.1", port)
        self.st = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "a": False, "b": False, "rb": False, "x": False}

    def _send(self) -> None:
        self.sock.sendto(json.dumps(self.st).encode(), self.addr)

    def move(self, x: float, y: float) -> None:
        self.st.update(lx=float(x), ly=float(y))
        self._send()

    def look(self, rx: float) -> None:
        self.st["rx"] = float(rx)
        self._send()

    def neutral(self, why: str | None = None) -> None:
        self.st = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "a": False, "b": False, "rb": False, "x": False}
        self._send()

    def press(self, key: str, hold: float = 0.1) -> None:
        """Press a button ("a" "b" "rb" "x") for hold seconds. B shorter than 0.25 s = roll / backstep, longer = run."""
        self.st[key] = True
        self._send()
        time.sleep(hold)
        self.st[key] = False
        self._send()

    def interact(self) -> None:
        self.st["a"] = True
        self._send()
        time.sleep(0.1)
        self.st["a"] = False
        self._send()

    def keep(self) -> None:
        """Resend the current input (the room drops UDP input older than 0.5 s and falls back to pads/keyboard)."""
        self._send()
