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
import re
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from telemetry import Chr, Snapshot

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "godot"
GODOT = Path(os.environ.get("GODOT_PATH", "D:/dev/tools/godot/Godot_v4.7.2-stable_win64_console.exe"))
STATE_PORT, INPUT_PORT = 47811, 47812


def ensure_imported() -> bool:
    """Godot's import cache (`.godot/imported`, not in git) — a fresh clone has none and the room then fails on its first
    asset load (cloud 11-10: no player body, no input, state packets still sent). Runs `--import` once when a file named
    by an `assets/**/*.import` is missing. True when an import ran."""
    missing = False
    for imp in PROJECT.rglob("*.import"):
        if ".godot" in imp.parts:
            continue
        m = re.search(r'^path="res://(.+?)"', imp.read_text(encoding="utf-8"), re.M)
        if m and not (PROJECT / m.group(1)).exists():
            missing = True
            break
    if missing:
        subprocess.run([str(GODOT), "--headless", "--path", str(PROJECT), "--import"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
    return missing


def start_room(headless: bool = True) -> subprocess.Popen:
    ensure_imported()
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
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        self.sock.bind(("127.0.0.1", port))
        self.sock.settimeout(0.2)
        self.last: Optional[dict] = None
        # read every packet as it comes: when nobody reads, a full socket buffer drops the *new* packets and a later
        # read returns old state (seen 11-09: the room looked 0.4× real time)
        self._alive = True
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        while self._alive:
            try:
                data, _ = self.sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            self.last = json.loads(data)

    def state(self, wait: float = 2.0) -> Optional[dict]:
        end = time.time() + wait
        while self.last is None and time.time() < end:
            time.sleep(0.01)
        return self.last

    def snapshot(self, within: float = 60.0) -> Optional[Snapshot]:
        d = self.state()
        if d is None:
            return None
        p = Chr(ptr=1, npc_param=0, team=1, hp=1, max_hp=1, x=d["x"], y=d["y"], z=d["z"], anim=d["anim"],
                heading=d["heading"])
        chars = []
        dm = d.get("dummy")
        if dm:                       # the training dummy as a hostile (team 6) character, like a DSR foe in the list
            dist = ((dm["x"] - d["x"]) ** 2 + (dm["z"] - d["z"]) ** 2) ** 0.5
            chars.append(Chr(ptr=2, npc_param=0, team=6, hp=dm["hp"], max_hp=600, x=dm["x"], y=dm["y"], z=dm["z"],
                             dist=dist, heading=dm["heading"], name="dummy"))
        return Snapshot(t=d["t"], player=p, chars=chars, cam_yaw=d["cam_yaw"])

    def close(self) -> None:
        self._alive = False
        self.sock.close()


class SimPad:
    def __init__(self, port: int = INPUT_PORT):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addr = ("127.0.0.1", port)
        self.st = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "a": False, "b": False, "rb": False, "x": False, "r3": False, "slow": False, "ov": False}
        # the room drops UDP input older than 0.5 s (then a real pad / the keyboard takes over) — resend every 0.1 s
        # so a held stick stays held like on a pad
        self._alive = True
        threading.Thread(target=self._beat, daemon=True).start()

    def _beat(self) -> None:
        while self._alive:
            time.sleep(0.1)
            try:
                self._send()
            except OSError:
                return

    def close(self) -> None:
        self._alive = False

    def _send(self) -> None:
        self.sock.sendto(json.dumps(self.st).encode(), self.addr)

    def move(self, x: float, y: float) -> None:
        self.st.update(lx=float(x), ly=float(y))
        self._send()

    def look(self, rx: float) -> None:
        self.st["rx"] = float(rx)
        self._send()

    def neutral(self, why: str | None = None) -> None:
        self.st = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "a": False, "b": False, "rb": False, "x": False, "r3": False, "slow": False, "ov": False}
        self._send()

    def press(self, key: str, hold: float = 0.1) -> None:
        """Press a button ("a" "b" "rb" "x" "r3" lock-on, "slow" ×0.25, "ov" overlay) for hold seconds. B shorter than 0.25 s = roll / backstep, longer = run."""
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


# ── The ramp room as the bot's game (BOT_GAME=sim, MoKa M1109-65) ─────────────────────────────────────────────────
# run.py builds its telemetry with env.make_telemetry() and its pad with control.Pad(); with BOT_GAME=sim those become
# RoomTelemetry (one per process, like feed.Feed) and RoomPad (control.Pad's own code — timing, guard keep, sprint
# hold, freeze — with the ViGEm device swapped for UDP to the room). Character values are the 11-09 character's
# (settings of run 20261109_171230: Claymore 301000 one-handed, Estus 203 ×10, quick slots [203, -1, -1, -1, -1]).
ESTUS_ID, WEAPON_ID = 203, 301000


class RoomTelemetry(SimTelemetry):
    LISTEN_S = 1 / 30           # listeners (track, blackbox, radar) at most this often, like feed.Feed's frames

    REC_S = 0.1                 # room state recorded this often (data/runs/<time>_room.jsonl) — foe_view.py --room

    def __init__(self, port: int = STATE_PORT, rec: str | None = None):
        self.listeners: list = []
        self._last_listen = 0.0
        self._last_rec = 0.0
        self.rec_path = rec or os.environ.get("BOT_ROOM_REC") or str(
            ROOT.parent / "data" / "runs" / time.strftime("%Y%m%d_%H%M%S_room.jsonl"))
        self._rec = open(self.rec_path, "a", encoding="utf-8")
        super().__init__(port)

    def _read(self) -> None:
        while self._alive:
            try:
                data, _ = self.sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            self.last = json.loads(data)
            now = time.time()
            if now - self._last_rec >= self.REC_S:
                self._last_rec = now
                try:
                    self._rec.write(json.dumps({"wall": round(now, 3), **self.last}) + "\n")
                    self._rec.flush()
                except ValueError:          # closed
                    pass
            if self.listeners and now - self._last_listen >= self.LISTEN_S:
                self._last_listen = now
                s = self.snapshot()
                for fn in list(self.listeners):
                    try:
                        fn(s)
                    except Exception:
                        pass

    def alive(self) -> bool:
        return self._alive

    def close(self) -> None:
        super().close()
        self._rec.close()

    def snapshot(self, within: float = 60.0) -> Optional[Snapshot]:
        d = self.state()
        if d is None or "foes" not in d:
            return None
        p = Chr(ptr=1, npc_param=0, team=1, hp=int(d["hp"]), max_hp=int(d["max_hp"]), sp=int(d["sp"]),
                max_sp=int(d["max_sp"]), x=d["x"], y=d["y"], z=d["z"], anim=int(d["anim"]), gx=d["x"], gy=d["y"],
                gz=d["z"], heading=d["heading"], map_id=0)
        chars = []
        for f in d["foes"]:
            dist = ((f["x"] - d["x"]) ** 2 + (f["y"] - d["y"]) ** 2 + (f["z"] - d["z"]) ** 2) ** 0.5
            if dist <= within:
                chars.append(Chr(ptr=f["ptr"], npc_param=f["npc"], team=6, hp=int(f["hp"]), max_hp=int(f["max_hp"]),
                                 x=f["x"], y=f["y"], z=f["z"], anim=int(f["anim"]), dist=dist, heading=f["heading"],
                                 name=f"#{f['n']}", map_id=0))
        chars.sort(key=lambda c: c.dist)
        return Snapshot(t=d["t"], player=p, chars=chars, cam_yaw=d["cam_yaw"], flask_hp=d.get("estus"))

    # what the bot asks DSR besides the snapshot
    def handle(self, ptr) -> Optional[int]:
        return ptr if ptr else None

    def lock_target(self) -> Optional[int]:
        d = self.state()
        return (d.get("lock_ptr") or -1) if d else None

    def goods_count(self, item: int) -> int:
        d = self.state() or {}
        return int(d.get("estus", 0)) if item == ESTUS_ID else 0

    def selected_item(self) -> int:
        return ESTUS_ID

    def quick_items(self) -> list[int]:
        return [ESTUS_ID, -1, -1, -1, -1]

    def grip(self) -> int:
        return 1

    def right_weapon(self) -> int:
        return WEAPON_ID

    def weapon_durability(self, weapon_id: int | None = None) -> None:
        return None

    def char_stats(self) -> dict:
        return {"SL": None, "VIT": 22}

    def equipment(self) -> dict:
        return {}

    def souls(self) -> int:
        return 0

    def humanity(self) -> int:
        return 0

    def last_bonfire(self) -> int:
        return 1022960

    def event_flag(self, fid: int) -> None:
        return None

    def menu_open(self) -> bool:
        return False

    def quit_to_title(self, timeout: float = 10.0) -> bool:
        return False              # no quit-out in the room (run with --no-quit)

    def stats(self) -> dict:
        return {"room": True}


_room_tm: Optional[RoomTelemetry] = None


def room_telemetry() -> RoomTelemetry:
    global _room_tm
    if _room_tm is None:
        _room_tm = RoomTelemetry()
    return _room_tm


class RoomDev:
    """The part of vgamepad.VX360Gamepad control.Pad uses, sent to the room as UDP input on update() and every 0.1 s
    (the room drops input older than 0.5 s)."""
    BITS = {0x1000: "a", 0x2000: "b", 0x4000: "x", 0x8000: "y", 0x0100: "lb", 0x0200: "rb", 0x0080: "r3",
            0x0002: "dd"}

    NAMES = {"XUSB_GAMEPAD_A": 0x1000, "XUSB_GAMEPAD_B": 0x2000, "XUSB_GAMEPAD_X": 0x4000, "XUSB_GAMEPAD_Y": 0x8000,
             "XUSB_GAMEPAD_LEFT_SHOULDER": 0x0100, "XUSB_GAMEPAD_RIGHT_SHOULDER": 0x0200,
             "XUSB_GAMEPAD_RIGHT_THUMB": 0x0080, "XUSB_GAMEPAD_DPAD_DOWN": 0x0002}

    class _Report:
        wButtons = 0

    def __init__(self, port: int = INPUT_PORT):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addr = ("127.0.0.1", port)
        self.report = RoomDev._Report()
        self.st = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "rt": 0.0}
        self._alive = True
        self._shut = False                       # close(): nothing is sent any more
        threading.Thread(target=self._beat, daemon=True).start()

    def _beat(self) -> None:
        while self._alive:
            time.sleep(0.1)
            try:
                self.update()
            except OSError:
                return

    def reset(self) -> None:
        self.report.wButtons = 0
        self.st = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "rt": 0.0}

    def _bit(self, button) -> int:
        # vgamepad's XUSB_BUTTON, or control._Buttons' names where vgamepad isn't installed
        return self.NAMES.get(button, 0) if isinstance(button, str) else int(button)

    def press_button(self, button) -> None:
        self.report.wButtons |= self._bit(button)

    def release_button(self, button) -> None:
        self.report.wButtons &= ~self._bit(button)

    def left_joystick_float(self, x_value_float: float, y_value_float: float) -> None:
        self.st["lx"], self.st["ly"] = float(x_value_float), float(y_value_float)

    def right_joystick_float(self, x_value_float: float, y_value_float: float) -> None:
        self.st["rx"] = float(x_value_float)

    def right_trigger_float(self, value_float: float) -> None:
        self.st["rt"] = float(value_float)

    def close(self) -> None:
        """Stop the 0.1 s beat. A pad left beating keeps sending its last (neutral) state to the room's input port, so a
        later pad's stick alternates with zeros and the player moves at a fraction of its speed (P-154)."""
        self.reset()
        self.update()
        self._alive = False
        self._shut = True

    def update(self) -> None:
        if self._shut:
            return
        msg = dict(self.st)
        for bit, k in self.BITS.items():
            msg[k] = bool(self.report.wButtons & bit)
        self.sock.sendto(json.dumps(msg).encode(), self.addr)

    def __bool__(self) -> bool:
        return True

    def close(self) -> None:
        self._alive = False


def room_pad():
    """control.Pad with RoomDev in place of the ViGEm device — no pad lock, no device wait."""
    import control

    class RoomPad(control.Pad):
        def __init__(self):
            self._due = {}
            self._b_since = None
            self.epoch = 0
            self._stick_on = False
            self._stick_off_t = 0.0
            self._lock = threading.RLock()
            self._force_until = 0.0
            self._kept = False
            self._guard_want = False
            self._closed = False
            self._pad_lock = None
            self.pad = RoomDev()
            self.neutral()

        def reconnect(self) -> None:
            pass

        def close(self) -> None:
            self.neutral()
            self._closed = True
            self.pad.close()

    return RoomPad()
