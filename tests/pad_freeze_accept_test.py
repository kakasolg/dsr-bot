"""control.Pad freeze — acceptance rows for the "minimal" contract (docs/formal/pad_freeze/PATCH_PLAN.md §1, §2).
Real control.Pad on a fake vgamepad.  python tests/pad_freeze_accept_test.py

Each row checks a SAFETY property (S… = the TLA+ property in docs/formal/pad_freeze/PadFreeze.tla; "model out" = not in
the model, code test only). Verdicts:
  SAFE                  the property holds
  VIOLATED (known …)    listed in KNOWN — exit code stays 0 but it is NOT counted as a pass
  FAIL                  an unlisted violation, or a KNOWN row that now holds (then take it out of KNOWN)

Order is forced: every non-holder call runs on a long-lived named thread (Actor) and the caller waits on an Event until
it returned. Time: control.time is swapped for Clock (time() only moves when a row says so; sleep is real unless a row
hooks it).
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

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

A, LB, BB, RB, Y = ("XUSB_GAMEPAD_A", "XUSB_GAMEPAD_LEFT_SHOULDER", "XUSB_GAMEPAD_B", "XUSB_GAMEPAD_RIGHT_SHOULDER",
                    "XUSB_GAMEPAD_Y")

# 평상시(freeze 무관) 결함 후보 — 이 패치 범위 밖 (docs/formal/pad_freeze/REPORT.md §3, §5)
KNOWN = {
    "S5-normal": "평상시 S5 후보: tap 예약이 같은 버튼의 새 hold를 뗌",
    "S6-normal": "평상시 S6 후보: keep_guard 중 guard(True)→guard(False) 뒤 LB 고아",
}
SAFE: list[str] = []
VIOL: list[str] = []
FAILED: list[str] = []


def safety(key: str, desc: str, holds: bool, detail: str = "") -> None:
    name = f"{key} {desc}"
    if holds and key in KNOWN:
        FAILED.append(f"{name} — 알려진 위반이 사라짐: KNOWN에서 빼고 기록 갱신")
        print(f"FAIL     {name} (KNOWN인데 성립) {detail}")
    elif holds:
        SAFE.append(name)
        print(f"SAFE     {name}")
    elif key in KNOWN:
        VIOL.append(name)
        print(f"VIOLATED (known: {KNOWN[key]}) {name} {detail}")
    else:
        FAILED.append(name)
        print(f"FAIL     {name} {detail}")


class Clock:
    """control.time stand-in: time() is frozen at self.t; sleep() is real unless hook is set (hook(seconds) runs instead)."""
    def __init__(self) -> None:
        self.t = 1_000_000.0
        self.hook = None

    def time(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        if self.hook is not None:
            self.hook(s)
        else:
            _time.sleep(s)

    def __getattr__(self, name):
        return getattr(_time, name)


class Actor:
    """One long-lived named thread; do(fn) runs fn there and returns after it finished."""
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
            except BaseException as ex:          # surface it in the caller
                out["ex"] = ex
            finally:
                done.set()

    def start(self, fn) -> tuple[threading.Event, dict]:
        done, out = threading.Event(), {}
        self.q.put((fn, done, out))
        return done, out

    def do(self, fn):
        done, out = self.start(fn)
        if not done.wait(5):
            raise RuntimeError(f"{self.th.name}: call timed out")
        if "ex" in out:
            raise out["ex"]
        return out.get("r")

    def stop(self) -> None:
        self.q.put((None, None, None))
        self.th.join(5)


class Env:
    def __init__(self) -> None:
        self.clock = Clock()
        control.time = self.clock
        self.vg = pad_fakes.install(Path(tempfile.mkdtemp(prefix="frzaccept_")))
        self.pad = control.Pad()
        self.rec = self.vg.devices[-1]
        self.actors: list[Actor] = []

    def actor(self, name: str) -> Actor:
        a = Actor(name)
        self.actors.append(a)
        return a

    def on(self, btn: str) -> bool:
        return btn in self.rec.last().get("buttons", set())

    def state(self) -> tuple:
        p = self.pad
        return (p._force_until, p._kept, p._guard_want, p._b_since, dict(p._due), p.epoch, p._stick_on, p._stick_off_t,
                len(self.rec.sent))

    def close(self) -> None:
        for a in self.actors:
            a.stop()
        self.pad.close()


def row_a1() -> None:
    e = Env(); pad = e.pad
    gk = e.actor("guardkeep")
    pad.freeze()
    ret = gk.do(lambda: pad.keep_guard(e.clock.t + 1.0))
    pad.neutral()                                         # quitout.py:158
    n0 = len(e.rec.sent)
    pad.press(B.XUSB_GAMEPAD_A, 0.0)                      # quitout._press
    menu = [e.rec.sent[-1]] + e.rec.sent[n0:]
    safety("A1", "S1 K1-in: freeze 중 keep_guard → 메뉴 보고에 LB 없음, keep_guard 반환 False",
           all(LB not in r["buttons"] for r in menu) and ret is False, f"ret={ret}, LB={[LB in r['buttons'] for r in menu]}")
    pad.force_guard = False; pad.neutral(); pad.unfreeze(); e.close()


def row_a2() -> None:
    e = Env(); pad = e.pad
    gk = e.actor("guardkeep")
    gk.do(lambda: pad.keep_guard(e.clock.t + 1.0))
    pad.freeze()
    cleared = not pad.force_guard and not pad._kept and not pad._guard_want
    pad.neutral()
    n0 = len(e.rec.sent)
    pad.press(B.XUSB_GAMEPAD_A, 0.0)
    menu = [e.rec.sent[-1]] + e.rec.sent[n0:]
    safety("A2", "S1 K1-pre: freeze 전 keep_guard → freeze가 의도를 비우고 메뉴 보고에 LB 없음",
           cleared and all(LB not in r["buttons"] for r in menu), f"cleared={cleared}")
    pad.force_guard = False; pad.neutral(); pad.unfreeze(); e.close()


def row_a3() -> None:
    e = Env(); pad = e.pad
    nav = e.actor("nav")
    pad.freeze()
    nav.do(lambda: pad.sprint(True))
    pad.neutral()
    n0 = len(e.rec.sent)
    pad.press(B.XUSB_GAMEPAD_A, 0.0)
    menu = [e.rec.sent[-1]] + e.rec.sent[n0:]
    safety("A3", "S1b K2: freeze 중 비홀더 sprint(True) → 메뉴 보고에 B 없음, _b_since None",
           all(BB not in r["buttons"] for r in menu) and pad._b_since is None, f"b_since={pad._b_since}")
    pad._b_since = None; pad._due.clear(); pad.neutral(); pad.unfreeze(); e.close()


def row_a4() -> None:
    e = Env(); pad = e.pad
    nav = e.actor("nav")
    pad.freeze()
    pad.tap(B.XUSB_GAMEPAD_A, 0.1)                        # API-level: a holder that taps (none today)
    e.clock.t += 1.0
    nav.do(pad.release_due)
    orphan = e.on(A) and B.XUSB_GAMEPAD_A not in pad._due
    pad.release_due()                                     # the holder's own release
    released = not e.on(A)
    pad.neutral(); pad.unfreeze()
    n0 = len(e.rec.sent)
    nav.do(pad.release_due)
    safety("A4", "S2 K3: 홀더 tap 뒤 비홀더 release_due → 예약 유지(A 고아 없음), 홀더 release_due로 꺼짐",
           not orphan and released and len(e.rec.sent) == n0, f"orphan={orphan}, released={released}")
    e.close()


def row_a5() -> None:
    e = Env(); pad = e.pad
    nav = e.actor("nav")
    pad.freeze()
    pad.neutral()                                         # watch.py:308
    nav.do(lambda: pad.sprint(True))
    pad.unfreeze()                                        # watch.py:309
    nav.do(lambda: pad.sprint(True))
    direct = e.on(BB)
    e.close()

    import nav as nav_mod
    e = Env(); pad = e.pad
    navt = e.actor("nav")
    mover = navt.do(lambda: nav_mod.Mover(pad))
    navt.do(lambda: mover.set("sprint"))
    pad.freeze()
    pad.neutral()
    navt.do(lambda: mover.set("sprint"))                  # resync → sprint(True) while still frozen
    pad.unfreeze()
    navt.do(lambda: mover.set("sprint"))                  # resync once more → one sprint(True)
    via_mover = e.on(BB)
    safety("A5", "S4 스테일 sprint: 마지막 neutral과 unfreeze 사이 sprint(True) → unfreeze 뒤 1번 요청으로 B (직접·Mover)",
           direct and via_mover, f"direct={direct}, mover={via_mover}")
    e.close()


def row_a6() -> None:
    e = Env(); pad = e.pad
    nudge = e.actor("nudge")
    got = nudge.do(lambda: pad.freeze(take=False))
    pad.freeze()                                          # the quit-out takes it
    me = threading.get_ident()
    before = e.state()
    nudge.do(lambda: pad.neutral())                       # watch.py:242 (finally)
    after_neutral = e.state()
    nudge.do(pad.unfreeze)                                # watch.py:243
    still = pad._frozen_by == me
    pad.press(B.XUSB_GAMEPAD_A, 0.0)
    out = any(A in r["buttons"] and r["th"] == "MainThread" for r in e.rec.sent[-2:])
    pad.neutral(); pad.unfreeze()
    safety("A6", "S3 인계: nudge→quit-out 가져가기, nudge의 neutral은 상태·epoch·장치 무변화, unfreeze 무시, 홀더 입력 나감",
           got is True and before == after_neutral and still and out and pad._frozen_by is None,
           f"take_false={got}, nudge neutral 무변화={before == after_neutral}, 홀더 유지={still}, 입력={out}")
    e.close()


def row_a7() -> None:
    import nav as nav_mod
    res = {}
    e = Env(); pad = e.pad; nav = e.actor("nav")
    pad.freeze(); nav.do(lambda: pad.guard(True)); pad.neutral(); pad.unfreeze()
    nav.do(lambda: pad.guard(True)); res["guard"] = e.on(LB); e.close()

    e = Env(); pad = e.pad; gk = e.actor("guardkeep")
    pad.freeze(); gk.do(lambda: pad.keep_guard(e.clock.t + 1.0)); pad.neutral(); pad.unfreeze()
    r = gk.do(lambda: pad.keep_guard(e.clock.t + 1.0)); res["keep_guard"] = e.on(LB) and r is True
    pad.force_guard = False; e.close()

    e = Env(); pad = e.pad; nav = e.actor("nav")
    pad.freeze(); nav.do(lambda: pad.sprint(True)); pad.neutral(); pad.unfreeze()
    nav.do(lambda: pad.sprint(True)); res["sprint"] = e.on(BB); e.close()

    e = Env(); pad = e.pad; navt = e.actor("nav")
    mover = navt.do(lambda: nav_mod.Mover(pad))
    pad.freeze(); navt.do(lambda: mover.set("guard")); pad.neutral(); pad.unfreeze()
    navt.do(lambda: mover.set("guard")); res["mover_guard"] = e.on(LB); e.close()
    safety("A7", "S4 회복: freeze 중 요청이 막혀도 unfreeze 뒤 guard/keep_guard/sprint/Mover 요청 1번으로 장치에 들어감",
           all(res.values()), str(res))


def row_a8() -> None:
    res = {}
    e = Env(); pad = e.pad; nav = e.actor("nav")
    pad.freeze(); pad.sprint(True); pad.neutral()         # holder's own young hold → B kept + release scheduled
    pad.unfreeze()
    nav.do(lambda: pad.sprint(True)); e.clock.t += 1.0; nav.do(pad.release_due)
    res["a_holder_neutral_B"] = e.on(BB); e.close()

    e = Env(); pad = e.pad; nav = e.actor("nav")
    nav.do(lambda: pad.sprint(True)); nav.do(lambda: pad.sprint(False)); nav.do(lambda: pad.sprint(True))
    e.clock.t += 1.0; nav.do(pad.release_due)
    res["b_sprint_off_on"] = e.on(BB); e.close()

    e = Env(); pad = e.pad; nav = e.actor("nav")
    pad.freeze(); nav.do(lambda: pad.tap(B.XUSB_GAMEPAD_Y, 0.1))
    res["d_no_frozen_reservation"] = B.XUSB_GAMEPAD_Y not in pad._due
    pad.neutral(); pad.unfreeze()
    nav.do(lambda: pad.hold(B.XUSB_GAMEPAD_Y, True)); e.clock.t += 0.2; nav.do(pad.release_due)
    res["d_hold_kept"] = e.on(Y); e.close()
    safety("A8", "S5f 오래된 예약: freeze 중 버려진 tap이 예약을 남기지 않음, 예약이 새 입력을 떼지 않음",
           all(res.values()), str(res))


def row_s5_normal() -> None:
    e = Env(); pad = e.pad; nav = e.actor("nav")
    nav.do(lambda: pad.tap(B.XUSB_GAMEPAD_Y, 0.1)); nav.do(lambda: pad.hold(B.XUSB_GAMEPAD_Y, True))
    e.clock.t += 0.2; nav.do(pad.release_due)
    safety("S5-normal", "평상시: tap(Y) 예약 → hold(Y, True) → release_due가 hold를 떼지 않음", e.on(Y))
    e.close()


def row_s6_normal() -> None:
    e = Env(); pad = e.pad; nav = e.actor("nav"); gk = e.actor("guardkeep")
    gk.do(lambda: pad.keep_guard(e.clock.t + 1.0))
    nav.do(lambda: pad.guard(True)); nav.do(lambda: pad.guard(False))
    e.clock.t += 2.0; gk.do(pad.unkeep)
    orphan = e.on(LB) and not (pad._guard_want or pad._kept or pad.force_guard)
    safety("S6-normal", "평상시: keep_guard 중 guard(True)→guard(False) → 만료·unkeep 뒤 LB 고아 없음", not orphan)
    e.close()


def row_a9() -> None:
    e = Env(); pad = e.pad
    pad.freeze()
    pad.move(0.5, 0.0); ok_move = abs(e.rec.last()["lx"] - 0.5) < 1e-9
    pad.tap(B.XUSB_GAMEPAD_A, 0.1, stick_ok=True); ok_tap = e.on(A) and B.XUSB_GAMEPAD_A in pad._due
    pad.guard(True); ok_guard = e.on(LB)
    pad.sprint(True); ok_sprint = e.on(BB)
    e.clock.t += 1.0; pad.release_due(); ok_rel = not e.on(A)
    pad.neutral(); pad.unfreeze()
    safety("A9", "홀더 정상 입력: move/tap/guard/sprint/release_due가 장치에 들어감",
           ok_move and ok_tap and ok_guard and ok_sprint and ok_rel)
    e.close()


def row_a10() -> None:
    e = Env(); pad = e.pad; other = e.actor("exit")
    pad.freeze(); pad.move(1.0, 0.0); pad.guard(True); pad.tap(B.XUSB_GAMEPAD_A, 0.1, stick_ok=True)
    other.do(pad.release_all)
    safety("A10", "release_all 예외: 비홀더 종료 경로가 홀더 freeze 중에도 장치를 전부 끄고 예약을 비움",
           e.rec.is_neutral() and not pad._due)
    pad.unfreeze(); e.close()


def row_a11() -> None:
    e = Env(); pad = e.pad; nav = e.actor("nav")
    calls = {
        "neutral": lambda: pad.neutral(), "keep_guard": lambda: pad.keep_guard(e.clock.t + 1.0),
        "unkeep": lambda: pad.unkeep(), "guard(True)": lambda: pad.guard(True), "guard(False)": lambda: pad.guard(False),
        "sprint(True)": lambda: pad.sprint(True), "sprint(False)": lambda: pad.sprint(False),
        "tap(A)": lambda: pad.tap(B.XUSB_GAMEPAD_A, 0.1), "tap(B)": lambda: pad.tap(B.XUSB_GAMEPAD_B, 0.1),
        "hold(Y)": lambda: pad.hold(B.XUSB_GAMEPAD_Y, True), "kick": lambda: pad.kick(0.0, 1.0),
        "release_due": lambda: pad.release_due(),
    }
    pad.freeze()
    pad.tap(B.XUSB_GAMEPAD_A, 0.1, stick_ok=True)         # something for release_due to find
    e.clock.t += 1.0
    changed = []
    for name, fn in calls.items():
        before = e.state()
        nav.do(fn)
        if e.state() != before:
            changed.append(name)
    safety("A11", "비홀더 무변화: freeze 중 차단 대상 호출마다 의도·예약·epoch·스틱 기록·장치 보고 수 그대로",
           not changed, f"바뀐 호출={changed}")
    pad.neutral(); pad.unfreeze(); e.close()


def row_a13() -> None:
    e = Env(); pad = e.pad; nav = e.actor("nav")
    nav.do(lambda: pad.move(1.0, 0.0))                    # stick on → R1 tap will release it and wait
    sleeping, frozen = threading.Event(), threading.Event()

    def hook(s):
        if threading.current_thread().name == "nav":
            sleeping.set()
            frozen.wait(5)
        else:
            _time.sleep(s)
    e.clock.hook = hook
    done, out = nav.start(lambda: pad.tap(B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06))
    waited = sleeping.wait(5)                             # nav is inside release_stick's sleep (lock not held)
    pad.freeze()
    n0 = len(e.rec.sent)
    b_since0 = pad._b_since
    frozen.set()
    done.wait(5)
    e.clock.hook = None
    nav_reports = [r for r in e.rec.sent[n0:] if r["th"] == "nav"]
    safety("A13", "tap 대기 중 freeze: release_stick sleep 동안 freeze 시작 → 그 tap의 버튼 출력·예약·의도 변화 없음",
           waited and not e.on(RB) and B.XUSB_GAMEPAD_RIGHT_SHOULDER not in pad._due and pad._b_since == b_since0
           and not nav_reports,
           f"sleep 진입={waited}, RB 장치={e.on(RB)}, 예약={B.XUSB_GAMEPAD_RIGHT_SHOULDER in pad._due}, "
           f"nav 보고={len(nav_reports)}")
    pad.neutral(); pad.unfreeze(); e.close()


def row_a14() -> None:
    e = Env(); pad = e.pad; nav = e.actor("nav")
    pad.freeze()
    before = e.state()
    nav.do(lambda: pad.kick(0.0, 1.0))
    after = e.state()
    safety("A14", "비홀더 kick: 출력·예약·의도·스틱 기록·epoch 변화 없음",
           before == after and not e.on(RB), f"same={before == after}")
    pad.neutral(); pad.unfreeze(); e.close()


def row_a15() -> None:
    res = {}
    for who in ("normal", "holder"):
        e = Env(); pad = e.pad
        if who == "holder":
            pad.freeze()
        pad.kick(0.0, 1.0)
        r = e.rec.last()
        res[f"{who}_report"] = RB in r["buttons"] and abs(r["ly"] - 1.0) < 1e-9
        res[f"{who}_due"] = B.XUSB_GAMEPAD_RIGHT_SHOULDER in pad._due
        e.clock.t += 0.1
        pad.release_due()
        res[f"{who}_released"] = not e.on(RB)
        if who == "holder":
            pad.neutral(); pad.unfreeze()
        e.close()
    safety("A15", "홀더 kick·평상시 kick: 같은 보고에 스틱+RB, RB 예약, release_due로 RB 꺼짐 (기존 동작)",
           all(res.values()), str({k: v for k, v in res.items() if not v}))


def main() -> None:
    real_time = control.time
    try:
        for row in (row_a1, row_a2, row_a3, row_a4, row_a5, row_a6, row_a7, row_a8, row_s5_normal, row_s6_normal,
                    row_a9, row_a10, row_a11, row_a13, row_a14, row_a15):
            row()
    finally:
        control.time = real_time
    print(f"\n안전 성질: SAFE {len(SAFE)} · VIOLATED known {len(VIOL)} · FAIL {len(FAILED)}"
          f"  (VIOLATED known은 통과로 세지 않음)")
    if FAILED:
        print("FAILED:\n  " + "\n  ".join(FAILED))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
