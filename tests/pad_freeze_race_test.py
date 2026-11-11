"""control.Pad freeze / unfreeze — race table, each row run with a forced order (Events, no timing luck).
Real control.Pad on a fake vgamepad.  python tests/pad_freeze_race_test.py

The holder (the thread that froze) is always the main thread here; "other" = a short-lived thread run to completion
(other(fn)), so a finished holder's thread id is never reused by a later 'other'.

  row  order                                                              expected
  F1   other holds stick + LB · main freeze                                device report all off (freeze resets it)
  F2   main frozen · other move / tap / hold / sprint / neutral / kick     no device report from other; main's input goes out
  F3   other mid-press (A down, sleeping) · main freeze · other releases   A not left on the device, before or after unfreeze
  F4   main frozen · other freeze(take=False)                              False, holder unchanged, main's input still out
  F5   other frozen · main freeze(take=True) · other unfreeze              main holds it now; other's unfreeze ignored
  F6   main frozen · other unfreeze                                        ignored, still frozen by main
  F7   main frozen → unfreeze                                              epoch moves; other's guard(True) reaches the device
  F8   main frozen · other release_all (exit path)                         device all off although main holds the freeze
  F9   main frozen · other sprint(True), aged past SPRINT_MIN_HOLD_S       main's closing neutral leaves B off and _b_since None
       · main neutral → unfreeze                                           (the holders' finally-neutral resyncs sprint state)
  F10  main frozen · other keep_guard(now + 5) (souls/guardkeep thread)    no LB on the device in main's neutral or menu reports;
  P-91 · main neutral() · main press(A)                                    keep_guard returns False (blocked)
  F11  main frozen · other sprint(True) · main neutral() at once           no B on the device in main's reports; _b_since None
  P-92 · main press(A)
  F12  main frozen · main tap(A) · other release_due() after the hold      other's release_due is blocked: the _due entry stays,
  (P-92 note)                                                              so main's own release_due lets A go
  (F10–F12 were the known rows K1–K3 until the P-91/P-92 minimal patch; more rows: tests/pad_freeze_accept_test.py)
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
import tempfile
import threading
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import pad_fakes
from control import B

A, LB_N, BB = "XUSB_GAMEPAD_A", "XUSB_GAMEPAD_LEFT_SHOULDER", "XUSB_GAMEPAD_B"
FAILED: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        FAILED.append(name)


def fresh():
    vg = pad_fakes.install(Path(tempfile.mkdtemp(prefix="frzrace_")))
    pad = control.Pad()
    return pad, vg.devices[-1]


def other(fn, name: str = "other"):
    """Run fn in a fresh thread to completion (a non-holder) → its return value."""
    out: dict = {}
    th = threading.Thread(target=lambda: out.setdefault("r", fn()), name=name)
    th.start()
    th.join(5)
    return out.get("r")


def from_thread(rec, n0: int, th: str) -> list[dict]:
    return [r for r in rec.sent[n0:] if r["th"] == th]


def main() -> None:
    # F1
    pad, rec = fresh()
    other(lambda: (pad.move(1.0, 0.0), pad.guard(True)))
    pad.freeze()
    check("F1 다른 스레드가 스틱·LB를 쥔 채 freeze → 장치 보고 전부 꺼짐", rec.is_neutral())
    pad.unfreeze()
    pad.close()

    # F2
    pad, rec = fresh()
    pad.freeze()
    n0 = len(rec.sent)
    other(lambda: (pad.move(1.0, 1.0), pad.tap(B.XUSB_GAMEPAD_A), pad.guard(True), pad.sprint(True),
                   pad.neutral(), pad.kick(0.0, 1.0), pad.look(1.0, 0.0)))
    check("F2 얼린 동안 다른 스레드 입력은 장치로 하나도 안 감", not from_thread(rec, n0, "other") and rec.is_neutral())
    pad.move(0.5, 0.0)
    check("F2 얼린 스레드(홀더) 입력은 장치로 감", abs(rec.last()["lx"] - 0.5) < 1e-9)
    pad.neutral()
    pad.unfreeze()
    pad.close()

    # F3
    pad, rec = fresh()
    down, frozen = threading.Event(), threading.Event()
    real_sleep = time.sleep

    def presser():
        orig = control.time.sleep
        control.time.sleep = lambda s: (down.set(), frozen.wait(5))   # inside press(): A is down, now hold until frozen
        try:
            pad.press(B.XUSB_GAMEPAD_A, 0.2)
        finally:
            control.time.sleep = orig
    th = threading.Thread(target=presser, name="other")
    th.start()
    down.wait(5)
    a_was_down = A in rec.last()["buttons"]
    pad.freeze()
    frozen.set()
    th.join(5)
    control.time.sleep = real_sleep
    check("F3 누르는 중(A 눌림) freeze → 장치에서 A 꺼짐", a_was_down and A not in rec.last()["buttons"])
    pad.unfreeze()
    check("F3 unfreeze 뒤에도 A 남지 않음", A not in rec.last()["buttons"])
    pad.close()

    # F4
    pad, rec = fresh()
    pad.freeze()
    me = threading.get_ident()
    got = other(lambda: pad.freeze(take=False))
    pad.move(0.3, 0.0)
    check("F4 홀더가 있을 때 freeze(take=False) → False, 홀더 그대로, 홀더 입력 계속 감",
          got is False and pad._frozen_by == me and abs(rec.last()["lx"] - 0.3) < 1e-9)
    pad.neutral()
    pad.unfreeze()
    pad.close()

    # F5
    pad, rec = fresh()
    held, stolen, done = threading.Event(), threading.Event(), threading.Event()
    res: dict = {}

    def first_holder():
        pad.freeze()                          # e.g. Escape._nudge
        held.set()
        stolen.wait(5)
        n = len(rec.sent)
        pad.move(1.0, 0.0)                    # its input after the steal
        res["dropped"] = len(rec.sent) == n
        pad.unfreeze()                        # must not lift the quit-out's freeze
        done.set()
    th = threading.Thread(target=first_holder, name="nudge")
    th.start()
    held.wait(5)
    pad.freeze()                              # e.g. Escape.fire (take=True)
    stolen.set()
    done.wait(5)
    th.join(5)
    check("F5 take=True로 가져가면 앞 홀더 입력은 버려지고, 앞 홀더의 unfreeze는 무시됨",
          res.get("dropped") is True and pad._frozen_by == threading.get_ident())
    pad.neutral()
    pad.unfreeze()
    pad.close()

    # F6
    pad, rec = fresh()
    pad.freeze()
    other(pad.unfreeze)
    check("F6 홀더 아닌 스레드의 unfreeze는 무시됨", pad._frozen_by == threading.get_ident())
    pad.unfreeze()
    pad.close()

    # F7
    pad, rec = fresh()
    pad.freeze()
    ep = pad.epoch
    pad.unfreeze()
    other(lambda: pad.guard(True))
    check("F7 unfreeze → epoch 바뀜, 다른 스레드 guard(True)가 장치에 들어감",
          pad.epoch != ep and LB_N in rec.last()["buttons"])
    pad.close()

    # F8
    pad, rec = fresh()
    pad.freeze()
    pad.move(1.0, 0.0)
    other(pad.release_all)
    check("F8 종료 경로 release_all은 홀더가 있어도 장치를 전부 끔", rec.is_neutral())
    pad.unfreeze()
    pad.close()

    # F9
    pad, rec = fresh()
    keep_min = control.SPRINT_MIN_HOLD_S
    control.SPRINT_MIN_HOLD_S = 0.05
    try:
        pad.freeze()
        other(lambda: pad.sprint(True))
        time.sleep(0.08)                      # older than SPRINT_MIN_HOLD_S
        pad.neutral()
        pad.unfreeze()
        check("F9 오래된 달리기는 홀더의 마지막 neutral이 B 끄고 _b_since 비움",
              BB not in rec.last()["buttons"] and pad._b_since is None)
    finally:
        control.SPRINT_MIN_HOLD_S = keep_min
    pad.close()

    # F10 (was K1, P-91)
    pad, rec = fresh()
    pad.freeze()
    got = other(lambda: pad.keep_guard(time.time() + 5.0), name="guardkeep")
    pad.neutral()                             # quitout.quit_out's first call
    lb_after_neutral = LB_N in rec.last()["buttons"]
    pad.press(B.XUSB_GAMEPAD_A, 0.0)          # a menu press (quitout._press)
    menu_reports = rec.sent[-2:]
    check("F10 (P-91) 얼린 동안 guardkeep의 keep_guard → 막힘(False), 홀더 neutral·메뉴 보고에 LB 없음",
          got is False and not lb_after_neutral and all(LB_N not in r["buttons"] for r in menu_reports))
    pad.neutral()
    pad.unfreeze()
    pad.close()

    # F11 (was K2, P-92)
    pad, rec = fresh()
    pad.freeze()
    other(lambda: pad.sprint(True), name="nav")
    pad.neutral()
    b_after_neutral = BB in rec.last()["buttons"]
    pad.press(B.XUSB_GAMEPAD_A, 0.0)
    check("F11 (P-92) 얼린 동안 다른 스레드 sprint(True) → 막힘, 홀더 neutral·메뉴 보고에 B 없음, _b_since None",
          not b_after_neutral and all(BB not in r["buttons"] for r in rec.sent[-2:]) and pad._b_since is None)
    pad.neutral()
    pad.unfreeze()
    pad.close()

    # F12 (was K3, P-92 note)
    pad, rec = fresh()
    pad.freeze()
    pad.tap(B.XUSB_GAMEPAD_A, 0.01)
    time.sleep(0.03)
    other(pad.release_due)
    kept = A in rec.last()["buttons"] and B.XUSB_GAMEPAD_A in pad._due
    pad.release_due()                         # the holder's own release
    check("F12 (P-92 참고) 홀더 tap 뒤 다른 스레드 release_due → 막혀 예약이 남고, 홀더 release_due가 A를 뗌",
          kept and A not in rec.last()["buttons"] and not pad._due)
    pad.neutral()
    pad.unfreeze()
    pad.close()

    if FAILED:
        print("\nFAILED:\n  " + "\n  ".join(FAILED))
        raise SystemExit(1)
    print("pad_freeze_race_test: 전부 통과")


if __name__ == "__main__":
    main()
