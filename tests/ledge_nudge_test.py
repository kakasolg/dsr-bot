"""P0-F: Escape._ledge's nudge is the only writer while it runs — freeze → stick → neutral → unfreeze (finally) — and the
decision loop's Mover presses its buttons again after it. Real control.Pad on a fake vgamepad.  python tests/ledge_nudge_test.py

Checks:
  · while a decision thread keeps writing stick + guard, a ledge nudge's reports are all from the nudging thread,
    end with neutral, and the decision thread's guard (nav.Mover) comes back after unfreeze (Pad.epoch)
  · the nudge's stick write raises → still neutral + unfrozen
  · a quit-out already holding the freeze: no nudge (freeze(take=False) → False), that freeze is left alone
  · unfreeze from a thread that doesn't hold the freeze does nothing
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
import tempfile
import threading
import time
import types
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import nav
import pad_fakes
from souls.watch import Escape
from telemetry import Chr, Snapshot

LB = "XUSB_GAMEPAD_LEFT_SHOULDER"


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def sliding(esc: Escape):
    """A player 1 m below the last safe spot, barely moving for 1 s, no floor underfoot → _ledge nudges."""
    now = time.time()
    esc.safe_pos = (0.0, 0.0, 0.0)
    esc._pos.extend([(now - 0.6, 0.3, 0.0), (now - 0.3, 0.3, 0.0)])
    p = Chr(1, 0, 1, 500, 500, 0.3, -1.0, 0.0)
    return Snapshot(t=now, player=p, chars=[], cam_yaw=0.0), p, now


def main() -> None:
    vg = pad_fakes.install(Path(tempfile.mkdtemp(prefix="ledge_")))
    pad = control.Pad()
    rec = vg.devices[-1]
    nm = types.SimpleNamespace(tris_at=lambda x, z: [])          # no floor anywhere
    logs: list = []
    esc = Escape(pad, [nm], log=logs.append)

    # 1) decision thread writing all the time
    stop = threading.Event()
    mover = nav.Mover(pad)

    def decide():
        while not stop.is_set():
            pad.move(0.2, 0.9)
            mover.set("guard")
            time.sleep(0.01)
    dt = threading.Thread(target=decide, name="decide")
    dt.start()
    time.sleep(0.05)
    s, p, now = sliding(esc)
    threading.current_thread().name = "escape"
    esc._ledge(s, p, now)
    time.sleep(0.1)
    stop.set()
    dt.join(5)
    sent = rec.sent
    mine = [i for i, r in enumerate(sent) if r["th"] == "escape"]
    check("턱 되돌림이 일어남", esc.nudges == 1 and len(mine) >= 3)
    first, last = mine[0], mine[-1]
    check("되돌리는 동안의 보고는 전부 되돌리는 스레드 것", all(sent[i]["th"] == "escape" for i in range(first, last + 1)))
    check("되돌림 보고: 리셋 → 되돌림 스틱 → 중립", sent[first]["lx"] == 0 and any(sent[i]["lx"] < -0.5 for i in mine)
          and sent[last]["lx"] == 0 and sent[last]["ly"] == 0 and not sent[last]["buttons"])
    after = [r for r in sent[last + 1:] if r["th"] == "decide"]
    check("unfreeze 뒤 판단 스레드 입력이 다시 들어감", bool(after))
    check("unfreeze 뒤 Mover 가 가드(LB)를 다시 듦 (epoch)", any(LB in r["buttons"] for r in after))

    # 2) the nudge's stick write raises → neutral + unfrozen anyway
    pad.move(0.5, 0.5)
    pad.guard(True)
    vg.devices[-1].dev.fail_next = "left_joystick_float"
    try:
        esc._nudge((0.0, 1.0))
        raised = False
    except RuntimeError:
        raised = True
    check("되돌림 중 예외: 예외는 그대로 나감", raised)
    check("되돌림 중 예외: 그래도 중립·얼림 풀림", rec.is_neutral() and pad._frozen_by is None)

    # 3) a quit-out holds the freeze → no nudge, its freeze untouched
    held, release = threading.Event(), threading.Event()

    def quit_out():
        pad.freeze()
        held.set()
        release.wait(5)
        pad.neutral()
        pad.unfreeze()
    qt = threading.Thread(target=quit_out, name="quitout")
    qt.start()
    held.wait(5)
    owner = pad._frozen_by
    n0 = len(rec.sent)
    ok = esc._nudge((0.0, 1.0))
    check("퀵 종료가 얼려 두면 되돌리지 않음", ok is False and len(rec.sent) == n0)
    check("퀵 종료의 얼림은 그대로", pad._frozen_by == owner)
    pad.unfreeze()                                           # not the holder
    check("얼림을 안 쥔 스레드의 unfreeze 는 무시", pad._frozen_by == owner)
    release.set()
    qt.join(5)
    check("쥔 스레드가 풀면 풀림", pad._frozen_by is None)
    pad.close()
    print("ledge_nudge_test: 전부 통과")


if __name__ == "__main__":
    main()
