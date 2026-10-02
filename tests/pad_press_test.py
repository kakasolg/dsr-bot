"""P0-G: every report write goes through control.Pad — quitout._press uses Pad.press (blocking press → hold → release,
the release in finally). Real control.Pad on a fake vgamepad.  python tests/pad_press_test.py

Checks:
  · Pad.press: held for `hold`, then released; an exception (KeyboardInterrupt) during the hold still releases
  · quitout._press: one press + one release through Pad, then the gap; while another thread holds the freeze it sends nothing
  · source scan: no direct vgamepad writes (press_button, update via .pad.pad, _vpad, joystick/trigger setters) outside
    control.py in the bot's code (root, souls/, boss/, experiments/)
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import re
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import pad_fakes
import quitout
from control import B

ROOT = Path(__file__).resolve().parent.parent
A = "XUSB_GAMEPAD_A"
DIRECT = re.compile(r"\.pad\.pad\.|\._vpad\b|\bpress_button\(|\brelease_button\(|_joystick_float\(|_trigger_float\(")


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def main() -> None:
    vg = pad_fakes.install(Path(tempfile.mkdtemp(prefix="press_")))
    pad = control.Pad()
    rec = vg.devices[-1]

    # 1) Pad.press timing
    t0 = time.time()
    n0 = len(rec.sent)
    pad.press(B.XUSB_GAMEPAD_A, 0.1)
    dt = time.time() - t0
    new = rec.sent[n0:]
    check("Pad.press: 누름 → 뗌 두 보고", len(new) == 2 and A in new[0]["buttons"] and A not in new[1]["buttons"])
    check("Pad.press: hold 만큼 누른 채", dt >= 0.1)

    # 2) exception during the hold → released anyway
    real_time = control.time

    def boom(_s):
        raise KeyboardInterrupt
    control.time = types.SimpleNamespace(sleep=boom, time=real_time.time)
    try:
        pad.press(B.XUSB_GAMEPAD_A, 5.0)
        raised = False
    except KeyboardInterrupt:
        raised = True
    finally:
        control.time = real_time
    check("누른 채 KeyboardInterrupt: 예외는 나가고 버튼은 뗌", raised and A not in rec.last()["buttons"])

    # 3) quitout._press goes through Pad
    n0 = len(rec.sent)
    t0 = time.time()
    quitout._press(pad, B.XUSB_GAMEPAD_A, 0.0, quitout.MENU_GAP)
    dt = time.time() - t0
    new = rec.sent[n0:]
    check("quitout._press: 누름·뗌 두 보고", len(new) == 2 and A in new[0]["buttons"] and not new[1]["buttons"])
    check("quitout._press: HOLD + 최소 간격 지킴", dt >= quitout.HOLD + quitout.MENU_GAP - 0.005)
    held, release = threading.Event(), threading.Event()

    def holder():
        pad.freeze()
        held.set()
        release.wait(5)
        pad.unfreeze()
    th = threading.Thread(target=holder)
    th.start()
    held.wait(5)
    n0 = len(rec.sent)
    quitout._press(pad, B.XUSB_GAMEPAD_A, 0.0, 0.0)
    check("다른 스레드가 얼려 두면 quitout._press 는 아무것도 안 보냄", len(rec.sent) == n0)
    release.set()
    th.join(5)
    pad.close()

    # 4) no direct vgamepad writes outside control.Pad
    files = [p for p in ROOT.glob("*.py") if p.name != "control.py"]
    for d in ("souls", "boss", "experiments"):
        files += list((ROOT / d).rglob("*.py"))
    hits = []
    for f in files:
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            code = line.split("#", 1)[0]
            if DIRECT.search(code):
                hits.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()}")
    check(f"control.Pad 밖에서 vgamepad 를 직접 쓰는 곳 없음 ({len(files)} 파일)", not hits)
    if hits:
        print("\n".join(hits))
    print("pad_press_test: 전부 통과")


if __name__ == "__main__":
    main()
