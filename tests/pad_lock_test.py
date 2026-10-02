"""P0-A: one virtual pad per machine — control.Pad takes a machine-wide pad lock; watchdog.rescue skips while it is held.
Fake vgamepad (pad_fakes), no game, no ViGEm.  python tests/pad_lock_test.py

Checks:
  · a second Pad() (same process or another process) raises PadBusy and plugs nothing in
  · close(): neutral report, device removed, lock free again; input after close goes nowhere (no exception)
  · reconnect keeps the lock across the gap; reconnect on a closed Pad refuses
  · watchdog.rescue with the lock held: no Pad, no focus_game, no input, a skip line; with it free: the Pad is closed after
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import pad_fakes


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="padlock_"))
    vg = pad_fakes.install(tmp)

    # 1) second Pad in the same process
    p1 = control.Pad()
    check("첫 Pad: 장치 하나, 중립 보고", len(vg.devices) == 1 and vg.devices[0].is_neutral() and vg.devices[0].sent)
    check("잠금이 잡힘", control.pad_lock_held())
    try:
        control.Pad()
        second = "created"
    except control.PadBusy:
        second = "busy"
    check("두 번째 Pad → PadBusy, 장치 안 늘어남", second == "busy" and len(vg.devices) == 1)

    # 2) reconnect keeps the lock
    p1.move(0.5, 0.5)
    p1.reconnect()
    check("reconnect: 새 장치, 옛 장치는 빠짐", len(vg.devices) == 2 and vg.devices[0].removed)
    check("reconnect 뒤에도 잠금 유지", control.pad_lock_held())
    check("reconnect 뒤 새 장치 중립", vg.devices[1].is_neutral())

    # 3) close
    p1.move(0.7, 0.0)
    p1.close()
    d = vg.devices[1]
    check("close: 마지막 보고가 중립", d.sent[-1]["lx"] == 0 and not d.sent[-1]["buttons"])
    check("close: 장치 빠짐", d.removed)
    check("close: 잠금 풀림", not control.pad_lock_held())
    n_sent = len(d.sent)
    p1.move(1.0, 1.0)
    p1.tap(control.B.XUSB_GAMEPAD_A)
    p1.neutral()
    check("close 뒤 입력은 어디에도 안 감 (예외 없음)", len(d.sent) == n_sent)
    try:
        p1.reconnect()
        rc = "ok"
    except control.PadBusy:
        rc = "busy"
    check("닫힌 Pad 의 reconnect → PadBusy", rc == "busy")
    p1.close()                                            # idempotent
    p2 = control.Pad()
    check("잠금이 풀린 뒤엔 새 Pad 가능", len(vg.devices) == 3)
    p2.close()

    # 4) another process holds the lock → machine-wide
    holder = subprocess.Popen([sys.executable, "-c", (
        "import sys; sys.path.insert(0, r'%s'); from pathlib import Path; from botlock import BotLock; "
        "l = BotLock(Path(r'%s')); print('held' if l.acquire() else 'no', flush=True); sys.stdin.read()"
    ) % (str(Path(__file__).resolve().parent.parent), str(control.PAD_LOCK_PATH))],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        check("다른 프로세스가 잠금을 잡음", holder.stdout.readline().strip() == "held")
        n_dev = len(vg.devices)
        try:
            control.Pad()
            other = "created"
        except control.PadBusy:
            other = "busy"
        check("다른 프로세스가 쥐면 Pad → PadBusy, 장치 안 생김", other == "busy" and len(vg.devices) == n_dev)

        # 5) watchdog.rescue while the lock is held elsewhere
        import watchdog
        watchdog.LOG_FILE = tmp / "watchdog.log"
        from botlock import BotLock
        watchdog.BotLock = lambda: BotLock(tmp / "bot.lock")
        calls: list = []
        control.focus_game = lambda: calls.append("focus") or True
        watchdog._rescue = lambda tm, pad: calls.append("rescue")
        watchdog.rescue(None)
        logged = (tmp / "watchdog.log").read_text(encoding="utf-8")
        check("watchdog: 잠금 쥔 동안 Pad·focus·입력 없음", calls == [] and len(vg.devices) == n_dev)
        check("watchdog: skip 줄을 남김", "event=skip reason=pad_lock_held" in logged)
    finally:
        holder.stdin.close()
        holder.wait(timeout=10)

    # 6) lock free → rescue runs, and its Pad is closed even if the rescue raises
    def boom(tm, pad):
        calls.append(("rescue", pad))
        pad.move(0.6, 0.6)
        raise RuntimeError("rescue failed")
    watchdog._rescue = boom
    try:
        watchdog.rescue(None)
        raised = False
    except RuntimeError:
        raised = True
    d = vg.devices[-1]
    check("watchdog: 잠금 풀려 있으면 구조 실행", raised and calls and calls[0][0] == "rescue")
    check("watchdog: 구조가 예외로 끝나도 Pad 닫힘 (중립·장치 빠짐·잠금 풀림)",
          d.sent[-1]["lx"] == 0 and d.removed and not control.pad_lock_held())
    print("pad_lock_test: 전부 통과")


if __name__ == "__main__":
    main()
