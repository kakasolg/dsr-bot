"""P0-E: process exit paths release the pad — atexit (normal end, uncaught exception) and the Windows console control
handler (Ctrl+Break / console close: neutral → unplug; Ctrl+C: neutral only). Child processes on a fake vgamepad.
python tests/pad_exit_test.py

Checks:
  · child ends normally / with an uncaught exception, stick and LB still held → at exit: neutral, device removed, lock free
  · console handler called in-process: Ctrl+C → neutral only (even while another thread holds the freeze), the Pad stays
    usable; Ctrl+Break/close → neutral, removed, lock free
  · Windows: a real CTRL_BREAK_EVENT sent to a child → our handler ran before the process ended
Not checked (can't be, no code runs): TerminateProcess / hard kill — ViGEm's behaviour there stays UNKNOWN.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import pad_fakes

ROOT = Path(__file__).resolve().parent.parent
LB = "XUSB_GAMEPAD_LEFT_SHOULDER"

CHILD = r'''
import sys, json, time
sys.path[:0] = [{root!r}, {tests!r}]
from pathlib import Path
import control, pad_fakes
vg = pad_fakes.install(Path({tmp!r}))
OUT = Path({out!r})

def report():
    rec = vg.devices[-1]
    OUT.write_text(json.dumps({{"neutral": rec.is_neutral(), "removed": rec.removed,
                                "lock_free": not control.pad_lock_held(), "sent": len(rec.sent)}}), encoding="utf-8")

mode = {mode!r}
if mode in ("exit", "raise"):
    import atexit
    atexit.register(report)            # registered first → runs after control's (atexit is last-in first-out)
else:
    import ctypes, ctypes.wintypes
    H = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.DWORD)
    keep = H(lambda ev: (report(), False)[1])   # registered first → called after control's
    ctypes.windll.kernel32.SetConsoleCtrlHandler(keep, True)
pad = control.Pad()
pad.move(0.7, 0.7)
pad.guard(True)
if mode == "raise":
    raise RuntimeError("boom")
if mode == "break":
    print("ready", flush=True)
    time.sleep(30)
'''


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def child(mode: str) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix=f"padexit_{mode}_"))
    out = tmp / "out.json"
    src = CHILD.format(root=str(ROOT), tests=str(ROOT / "tests"), tmp=str(tmp), out=str(out), mode=mode)
    if mode == "break":
        p = subprocess.Popen([sys.executable, "-c", src], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        line = p.stdout.readline().strip()
        if line != "ready":
            raise SystemExit(f"child not ready: {line!r} {p.stderr.read()}")
        os.kill(p.pid, signal.CTRL_BREAK_EVENT)
        p.wait(timeout=20)
    else:
        subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, timeout=60)
    return json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}


def main() -> None:
    r = child("exit")
    check("정상 종료: 중립·장치 빠짐·잠금 풀림", r.get("neutral") and r.get("removed") and r.get("lock_free"))
    r = child("raise")
    check("잡히지 않은 예외로 종료: 중립·장치 빠짐·잠금 풀림", r.get("neutral") and r.get("removed") and r.get("lock_free"))

    vg = pad_fakes.install(Path(tempfile.mkdtemp(prefix="padexit_inproc_")))
    pad = control.Pad()
    rec = vg.devices[-1]
    pad.move(0.5, 0.5)
    pad.guard(True)
    frozen, release = threading.Event(), threading.Event()

    def holder():
        pad.freeze()
        pad.move(0.9, 0.0)               # the freezing thread's own input
        frozen.set()
        release.wait(5)
        pad.unfreeze()
    th = threading.Thread(target=holder, name="escape")
    th.start()
    frozen.wait(5)
    control._on_console_event(control.CTRL_C_EVENT)
    check("Ctrl+C 처리기: 다른 스레드가 얼려 둬도 중립", rec.is_neutral())
    check("Ctrl+C 처리기: 장치·잠금은 그대로 (KeyboardInterrupt 가 이어서 정리)", not rec.removed and control.pad_lock_held())
    release.set()
    th.join(5)
    pad.move(0.3, 0.3)
    check("Ctrl+C 뒤에도 Pad 는 쓸 수 있음", abs(rec.last()["lx"] - 0.3) < 1e-9)
    pad.guard(True)
    control._on_console_event(2)          # CTRL_CLOSE_EVENT
    check("콘솔 닫기 처리기: 중립·장치 빠짐·잠금 풀림", rec.is_neutral() and rec.removed and not control.pad_lock_held())

    if sys.platform == "win32":
        r = child("break")
        check("실제 Ctrl+Break: 처리기가 돌아 중립·장치 빠짐·잠금 풀림",
              r.get("neutral") and r.get("removed") and r.get("lock_free"))
    else:
        print("skip 실제 Ctrl+Break (윈도우 아님)")
    print("pad_exit_test: 전부 통과 (TerminateProcess/강제 종료는 검사 불가 — UNKNOWN)")


if __name__ == "__main__":
    main()
