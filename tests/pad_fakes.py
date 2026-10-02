"""Fake vgamepad for the pad safety tests — the real control.Pad runs on top of it, so its locks, freeze, release_due and
neutral are what get tested; only the ViGEm device underneath is fake. Not a test itself (no _test suffix).

  import pad_fakes
  vg = pad_fakes.install(tmp_dir)       # control.vg → fake, pad lock file → tmp_dir, Pad waits → 0 s
  pad = control.Pad()
  rec = vg.devices[-1]                  # Rec: what that device sent (rec.sent[-1] = last report), rec.removed
"""
from __future__ import annotations

import threading
import weakref
from pathlib import Path

import control

# XInput bit values by vgamepad button name (control.B is vg.XUSB_BUTTON on Windows, plain names without vgamepad)
BITS = {"XUSB_GAMEPAD_DPAD_UP": 0x1, "XUSB_GAMEPAD_DPAD_DOWN": 0x2, "XUSB_GAMEPAD_DPAD_LEFT": 0x4,
        "XUSB_GAMEPAD_DPAD_RIGHT": 0x8, "XUSB_GAMEPAD_START": 0x10, "XUSB_GAMEPAD_BACK": 0x20,
        "XUSB_GAMEPAD_LEFT_THUMB": 0x40, "XUSB_GAMEPAD_RIGHT_THUMB": 0x80, "XUSB_GAMEPAD_LEFT_SHOULDER": 0x100,
        "XUSB_GAMEPAD_RIGHT_SHOULDER": 0x200, "XUSB_GAMEPAD_GUIDE": 0x400, "XUSB_GAMEPAD_A": 0x1000,
        "XUSB_GAMEPAD_B": 0x2000, "XUSB_GAMEPAD_X": 0x4000, "XUSB_GAMEPAD_Y": 0x8000}


def bit(b) -> int:
    return BITS[getattr(b, "name", b)]


class _Report:
    def __init__(self, dev: "FakeVX360"):
        self.dev = dev

    @property
    def wButtons(self) -> int:
        out = 0
        for b in self.dev.buttons:
            out |= bit(b)
        return out


class Rec:
    """What one fake device did — kept apart from the device, so holding it doesn't keep the device alive (removal = GC)."""

    def __init__(self, dev: "FakeVX360"):
        self.sent: list[dict] = []
        self.removed = False
        self._dev = weakref.ref(dev)

    @property
    def dev(self) -> "FakeVX360 | None":
        return self._dev()

    def last(self) -> dict:
        return self.sent[-1] if self.sent else {}

    def is_neutral(self) -> bool:
        s = self.last()
        return bool(s) and not s["buttons"] and all(abs(s[k]) < 1e-9 for k in ("lx", "ly", "rx", "ry", "lt", "rt"))


class FakeVX360:
    """Records every update() (the moment a report would go to the driver) and its removal (__del__ = vigem_target_remove)."""

    def __init__(self, vg: "FakeVg"):
        self.vg = vg
        self.buttons: set = set()
        self.lx = self.ly = self.rx = self.ry = self.lt = self.rt = 0.0
        self.report = _Report(self)
        self.rec = Rec(self)
        self.sent = self.rec.sent
        self.fail_next: str | None = None          # method name that raises once (exception-path tests)
        vg.devices.append(self.rec)

    def _maybe_fail(self, name: str) -> None:
        if self.fail_next == name:
            self.fail_next = None
            raise RuntimeError(f"fake {name} failure")

    def state(self) -> dict:
        return {"buttons": {getattr(b, "name", b) for b in self.buttons}, "lx": self.lx, "ly": self.ly,
                "rx": self.rx, "ry": self.ry, "lt": self.lt, "rt": self.rt}

    def reset(self) -> None:
        self.buttons.clear()
        self.lx = self.ly = self.rx = self.ry = self.lt = self.rt = 0.0

    def update(self) -> None:
        self._maybe_fail("update")
        with self.vg.lock:
            self.sent.append({"th": threading.current_thread().name, **self.state()})

    def press_button(self, button) -> None:
        self.buttons.add(button)

    def release_button(self, button) -> None:
        self.buttons.discard(button)

    def left_joystick_float(self, x_value_float: float, y_value_float: float) -> None:
        self._maybe_fail("left_joystick_float")
        self.lx, self.ly = x_value_float, y_value_float

    def right_joystick_float(self, x_value_float: float, y_value_float: float) -> None:
        self.rx, self.ry = x_value_float, y_value_float

    def right_trigger_float(self, value_float: float) -> None:
        self.rt = value_float

    def left_trigger_float(self, value_float: float) -> None:
        self.lt = value_float

    def __del__(self):
        self.rec.removed = True


class FakeVg:
    """Stands in for the vgamepad module: control.vg.VX360Gamepad()."""

    def __init__(self):
        self.devices: list[Rec] = []
        self.lock = threading.Lock()

    def VX360Gamepad(self) -> FakeVX360:
        return FakeVX360(self)


def install(tmp: Path) -> FakeVg:
    """Point control at a fake vgamepad and a private pad lock file; drop the device-settle waits."""
    vg = FakeVg()
    control.vg = vg
    control.PAD_LOCK_PATH = Path(tmp) / "pad.lock"
    control.Pad.CONNECT_WAIT_S = 0.0
    control.Pad.RECONNECT_GAP_S = 0.0
    control.Pad.RECONNECT_WAIT_S = 0.0
    return vg
