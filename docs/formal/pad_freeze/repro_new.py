"""Real control.Pad (fake vgamepad) — the TLC counterexamples that had no offline test yet, replayed in a forced order.

    python docs/formal/pad_freeze/repro_new.py

Not a test (not under tests/, not collected): it prints REPRODUCED / NOT REPRODUCED per scenario and exits 0 either way.
Bot code is not changed. Order: every non-holder call runs on a long-lived named thread (Actor: "guardkeep", "nav") and
the main thread (the holder) waits on an Event until that call has returned. Time: control.time is swapped for a
clock that only moves when the scenario says so (time.sleep stays real; Pad.press(…, 0.0) sleeps 0).
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl
_ROOT = _pl.Path(__file__).resolve().parents[3]
_sys.path[:0] = [str(_ROOT), str(_ROOT / "tests")]

import queue
import sys
import tempfile
import threading
import time as _time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import pad_fakes
from control import B

A, LB, BB = "XUSB_GAMEPAD_A", "XUSB_GAMEPAD_LEFT_SHOULDER", "XUSB_GAMEPAD_B"


class Clock:
    """control.time stand-in: time() is frozen at self.t; everything else is the real time module."""
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def time(self) -> float:
        return self.t

    def __getattr__(self, name):
        return getattr(_time, name)


class Actor:
    """One long-lived named thread (same ident for its whole life, like the real guardkeep / decision threads).
    do(fn) runs fn there and returns only after it finished (Event) → a forced order with no timing luck."""
    def __init__(self, name: str) -> None:
        self.q: queue.Queue = queue.Queue()
        self.th = threading.Thread(target=self._run, name=name, daemon=True)
        self.th.start()

    def _run(self) -> None:
        while True:
            fn, done, out = self.q.get()
            if fn is None:
                return
            try:
                out["r"] = fn()
            finally:
                done.set()

    def do(self, fn):
        done, out = threading.Event(), {}
        self.q.put((fn, done, out))
        if not done.wait(5):
            raise RuntimeError("actor call timed out")
        return out.get("r")

    def stop(self) -> None:
        self.q.put((None, None, None))
        self.th.join(5)


def fresh():
    clock = Clock()
    control.time = clock
    vg = pad_fakes.install(Path(tempfile.mkdtemp(prefix="frzrepro_")))
    pad = control.Pad()
    return pad, vg.devices[-1], clock


def on(rec, btn) -> bool:
    return btn in rec.last().get("buttons", set())


RESULTS: list[tuple[str, bool, str]] = []


def report(name: str, reproduced: bool, detail: str) -> None:
    RESULTS.append((name, reproduced, detail))
    print(f"{'REPRODUCED    ' if reproduced else 'NOT REPRODUCED'} {name}\n               {detail}")


def scenario_k1_pre() -> None:
    """K1 without any race: keep_guard BEFORE the freeze (guardkeep, threat window), then the quit-out."""
    pad, rec, clock = fresh()
    gk = Actor("guardkeep")
    gk.do(lambda: pad.keep_guard(clock.t + 1.0))       # THREAT_S-like window, still running when the freeze comes
    lb_before = on(rec, LB)
    pad.freeze()                                       # watch.py:291
    off_after_freeze = not on(rec, LB)
    pad.neutral()                                      # quitout.py:158
    lb_neutral = on(rec, LB)
    n0 = len(rec.sent)
    pad.press(B.XUSB_GAMEPAD_A, 0.0)                   # quitout._press
    menu = rec.sent[n0:]
    lb_menu = bool(menu) and all(LB in r["buttons"] for r in menu)
    report("K1-pre  freeze 전 keep_guard → 홀더 neutral이 LB를 실제 장치에 누르고 메뉴 입력 내내 유지",
           lb_before and off_after_freeze and lb_neutral and lb_menu,
           f"freeze 전 LB={lb_before}, freeze 직후 LB 꺼짐={off_after_freeze}, neutral 뒤 LB={lb_neutral}, "
           f"메뉴 보고 {len(menu)}개 모두 LB={lb_menu}; freeze 중 다른 스레드 호출 0회")
    pad.force_guard = False
    pad.neutral()
    pad.unfreeze()
    gk.stop()
    pad.close()


def scenario_lb_orphan() -> None:
    """K1 followed by guardkeep's unkeep while still frozen: LB on the device that nobody means — how long does it last?"""
    pad, rec, clock = fresh()
    gk = Actor("guardkeep")
    pad.freeze()
    gk.do(lambda: pad.keep_guard(clock.t + 1.0))       # → _NullPad, but _force_until / _kept set
    pad.neutral()                                      # K1: LB on the device
    clock.t += 2.0                                     # the threat window is over
    gk.do(pad.unkeep)                                  # not the holder: guard_held() reads _NullPad → False → no release
    orphan = on(rec, LB) and not (pad._guard_want or pad._kept or pad.force_guard)
    n0 = len(rec.sent)
    pad.press(B.XUSB_GAMEPAD_A, 0.0)
    lb_menu = all(LB in r["buttons"] for r in rec.sent[n0:])
    pad.neutral()                                      # watch.py:308 (force_guard is over now → plain reset)
    lb_after_final = on(rec, LB)
    pad.unfreeze()
    lb_after_unfreeze = on(rec, LB)
    report("LB-orphan-a  freeze 중 unkeep 뒤 LB 고아 (메뉴 창 안)",
           orphan and lb_menu,
           f"unkeep 뒤 아무도 원하지 않는 LB가 장치에={orphan}, 메뉴 보고 LB={lb_menu}, "
           f"마지막 neutral 뒤 LB={lb_after_final}, unfreeze 뒤 LB={lb_after_unfreeze}")
    report("LB-orphan-b  같은 순서에서 unfreeze 이후까지 LB 고아",
           lb_after_unfreeze,
           "홀더의 마지막 neutral(watch.py:308)이 force_guard 끝난 뒤라 LB를 리셋함" if not lb_after_unfreeze
           else "unfreeze 뒤에도 LB 남음")
    gk.stop()
    pad.close()


def scenario_lb_orphan_post() -> None:
    """TLC's order (current_quit_m3_noguard_S6_post): keep_guard after the menu presses, before the closing neutral;
    the window ends while still frozen; guardkeep's unkeep (not the holder) clears _kept without releasing; unfreeze."""
    pad, rec, clock = fresh()
    gk = Actor("guardkeep")
    pad.freeze()                                       # watch.py:291
    pad.neutral()                                      # quitout.py:158
    pad.press(B.XUSB_GAMEPAD_A, 0.0)                   # quitout._press
    gk.do(lambda: pad.keep_guard(clock.t + 1.0))       # → _NullPad; _force_until, _kept=True
    pad.neutral()                                      # watch.py:308 — force_guard → LB pressed on the device
    clock.t += 2.0
    gk.do(pad.unkeep)                                  # still frozen: guard_held() reads _NullPad → no release, _kept=False
    pad.unfreeze()                                     # watch.py:309
    lb_after = on(rec, LB)
    gk.do(pad.unkeep)                                  # guardkeep keeps polling: _kept is False now → nothing
    orphan = on(rec, LB) and not (pad._guard_want or pad._kept or pad.force_guard)
    report("LB-orphan-d  메뉴 뒤·마지막 neutral 앞 keep_guard → 얼린 채 만료·unkeep → unfreeze 뒤 LB 고아 (TLC 순서)",
           lb_after and orphan,
           f"unfreeze 직후 LB={lb_after}, unkeep 한 번 더 뒤 LB={on(rec, LB)}, gw={pad._guard_want}, kept={pad._kept}, "
           f"fg={pad.force_guard}")
    gk.stop()
    pad.close()


def scenario_lb_orphan_guard() -> None:
    """The freeze-time variant that does survive unfreeze: the decision loop's guard(True) while frozen clears _kept."""
    pad, rec, clock = fresh()
    gk, nav = Actor("guardkeep"), Actor("nav")
    pad.freeze()
    gk.do(lambda: pad.keep_guard(clock.t + 1.0))       # _kept=True, _force_until set (→ _NullPad)
    nav.do(lambda: pad.guard(True))                    # _kept=False, _guard_want=True (→ _NullPad)
    pad.neutral()                                      # closing neutral, still inside the threat window: _guard_want=False, LB pressed
    pad.unfreeze()
    clock.t += 2.0
    gk.do(pad.unkeep)                                  # _kept is False → returns at once, LB stays
    orphan = on(rec, LB) and not (pad._guard_want or pad._kept or pad.force_guard)
    report("LB-orphan-c  freeze 중 keep_guard + guard(True) → unfreeze 뒤 LB 고아",
           orphan,
           f"unfreeze·만료·unkeep 뒤 LB 장치={on(rec, LB)}, gw={pad._guard_want}, kept={pad._kept}, fg={pad.force_guard}")
    gk.stop(); nav.stop()
    pad.close()


def scenario_stale_sprint() -> None:
    """nav's sprint(True) between the holder's closing neutral and unfreeze leaves _b_since set, B off the device;
    after unfreeze nav.Mover asks once (epoch bump → resync) and sprint(True) presses nothing."""
    for age in (0.0, 1.0):                             # unfreeze while that hold is still 'young' / after it aged
        pad, rec, clock = fresh()
        nav = Actor("nav")
        pad.freeze()
        pad.neutral()                                  # watch.py:308
        nav.do(lambda: pad.sprint(True))               # → _NullPad, _b_since = now
        clock.t += age
        pad.unfreeze()                                 # watch.py:309
        nav.do(lambda: pad.sprint(True))               # Mover.set("sprint") after its resync
        b_off = not on(rec, BB)
        nav.do(lambda: pad.sprint(True))               # asking again doesn't help either
        b_off2 = not on(rec, BB)
        clock.t += 5.0
        nav.do(pad.release_due)
        b_off3 = not on(rec, BB)
        report(f"stale-sprint  마지막 neutral과 unfreeze 사이 sprint(True) → unfreeze 뒤 sprint(True)가 B를 못 누름"
               f" (unfreeze 때 경과 {age:.1f} s)",
               b_off and b_off2,
               f"unfreeze 뒤 sprint(True) 1회 B 꺼짐={b_off}, 2회={b_off2}, 5 s 뒤 release_due 후 B 꺼짐={b_off3}, "
               f"_b_since 남음={pad._b_since is not None}")
        nav.stop()
        pad.close()


def scenario_stale_sprint_mover() -> None:
    """Same window driven through the real nav.Mover (the decision loop's caller): mode 'sprint' kept, B never pressed."""
    try:
        import nav as nav_mod
    except Exception as ex:                            # nav imports env / telemetry — report instead of failing
        report("stale-sprint-mover  nav.Mover 경유", False, f"nav import 실패: {type(ex).__name__}: {ex}")
        return
    pad, rec, clock = fresh()
    navt = Actor("nav")
    mover = navt.do(lambda: nav_mod.Mover(pad))
    navt.do(lambda: mover.set("sprint"))
    b_before = on(rec, BB)
    pad.freeze()
    navt.do(lambda: mover.set("sprint"))               # epoch moved → resync → sprint(True) → _NullPad, _b_since set
    pad.neutral()                                      # closing neutral: _b_since young → B pressed + release scheduled
    b_neutral = on(rec, BB)
    pad.unfreeze()
    navt.do(lambda: mover.set("sprint"))               # epoch moved again → resync → sprint(True): pops _due[B], no press
    clock.t += 1.0
    for _ in range(3):
        navt.do(pad.release_due)
        navt.do(lambda: mover.set("sprint"))
    report("stale-sprint-mover-a  nav.Mover 경유, set('sprint')가 홀더 마지막 neutral 앞 (→ unfreeze 뒤 반복)",
           not on(rec, BB) and mover.mode == "sprint",
           f"freeze 전 B={b_before}, 마지막 neutral 뒤 B={b_neutral}, 끝에 B={on(rec, BB)}, Mover.mode={mover.mode}")
    navt.stop()
    pad.close()

    # b: Mover's tick falls between watch.py:308 (neutral) and :309 (unfreeze) — the neutral bumped the epoch, so
    # set("sprint") resyncs and calls sprint(True) while still frozen
    pad, rec, clock = fresh()
    navt = Actor("nav")
    mover = navt.do(lambda: nav_mod.Mover(pad))
    navt.do(lambda: mover.set("sprint"))
    pad.freeze()
    pad.neutral()                                      # watch.py:308
    navt.do(lambda: mover.set("sprint"))               # resync → sprint(True) → _NullPad, _b_since set
    pad.unfreeze()                                     # watch.py:309
    clock.t += 1.0
    for _ in range(3):
        navt.do(lambda: mover.set("sprint"))           # resync once → sprint(True): _b_since set → no press
        navt.do(pad.release_due)
    report("stale-sprint-mover-b  nav.Mover 경유, set('sprint')가 마지막 neutral과 unfreeze 사이 (→ unfreeze 뒤 반복)",
           not on(rec, BB) and mover.mode == "sprint",
           f"끝에 B={on(rec, BB)}, Mover.mode={mover.mode}, _b_since 남음={pad._b_since is not None}")
    navt.stop()
    pad.close()


def scenario_stale_reservation_y() -> None:
    """S5 outside any freeze (TLC current_*_hold_S5): a tap's release reservation lets go of a later hold of the same
    button. Y is both tapped (two_hand_toggle :551) and held (two_hand_right :630). API-level: today two_hand_right
    blocks the decision loop, the only release_due caller, so the order below needs another release_due caller."""
    pad, rec, clock = fresh()
    nav = Actor("nav")
    nav.do(lambda: pad.tap(B.XUSB_GAMEPAD_Y, 0.1))     # reservation at t+0.1
    nav.do(lambda: pad.hold(B.XUSB_GAMEPAD_Y, True))   # a new hold — _due untouched
    clock.t += 0.2
    nav.do(pad.release_due)                            # the old reservation fires
    y_off = "XUSB_GAMEPAD_Y" not in rec.last().get("buttons", set())
    report("S5-normal  tap(Y) 예약 → hold(Y, True) → release_due가 새 hold를 뗌 (freeze 무관, API 수준)",
           y_off, f"hold(Y, True) 중 release_due 뒤 Y 꺼짐={y_off}")
    nav.stop()
    pad.close()


def scenario_stale_reservation_frozen() -> None:
    """S5f (TLC current_quit_m3_hold_S5f): a tap dropped to _NullPad during a freeze still writes _due; after unfreeze
    that reservation lets go of a new hold of the same button."""
    pad, rec, clock = fresh()
    nav = Actor("nav")
    pad.freeze()                                       # e.g. Escape._nudge (main = holder)
    nav.do(lambda: pad.tap(B.XUSB_GAMEPAD_Y, 0.1))     # → _NullPad, but _due[Y] = t+0.1
    due_kept = B.XUSB_GAMEPAD_Y in pad._due
    pad.neutral()
    pad.unfreeze()
    nav.do(lambda: pad.hold(B.XUSB_GAMEPAD_Y, True))   # a new hold after unfreeze
    y_on = "XUSB_GAMEPAD_Y" in rec.last().get("buttons", set())
    clock.t += 0.2
    nav.do(pad.release_due)
    y_off = "XUSB_GAMEPAD_Y" not in rec.last().get("buttons", set())
    report("S5f  freeze 중 버려진 tap(Y)의 예약 → unfreeze 뒤 hold(Y, True)를 release_due가 뗌",
           due_kept and y_on and y_off,
           f"freeze 중 tap 뒤 _due에 Y 남음={due_kept}, unfreeze 뒤 hold로 Y 켜짐={y_on}, release_due 뒤 Y 꺼짐={y_off}")
    nav.stop()
    pad.close()


def main() -> None:
    real_time = control.time
    try:
        scenario_k1_pre()
        scenario_lb_orphan()
        scenario_lb_orphan_post()
        scenario_lb_orphan_guard()
        scenario_stale_sprint()
        scenario_stale_sprint_mover()
        scenario_stale_reservation_y()
        scenario_stale_reservation_frozen()
    finally:
        control.time = real_time
    print(f"\n{sum(r for _, r, _ in RESULTS)}/{len(RESULTS)} reproduced")


if __name__ == "__main__":
    main()
