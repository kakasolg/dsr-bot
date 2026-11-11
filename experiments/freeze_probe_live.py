"""P-91/P-92 game check harness, variant J only (docs/formal/pad_freeze/GAME_CHECK_PLAN.md). Not run in game yet — needs MoKa's OK.

  python experiments/freeze_probe_live.py quit  [--note "…"]                 Escape.fire(kind="shake") — menu quit-out + Continue
  python experiments/freeze_probe_live.py nudge [--stick 0 0.5] [--note "…"]  Escape._nudge(stick) — NUDGE_S as in the bot

Variant J: the harness wraps only the Pad it creates. Right after that Pad's freeze() succeeds in the harness thread, a
'probe' thread makes a fixed list of non-holder calls (keep_guard, guard, sprint, tap, hold, release_due, neutral, kick);
freeze() returns to the owner (fire / _nudge) only after the probe thread has ended, so every probe call lands before the
holder's first neutral and menu input. unfreeze() runs only once the probe thread is confirmed dead.

  · probe call raised / returned an unsafe result, join timed out, Ctrl+C during the join → abort: no owner body, no
    normal unfreeze; release_all → close. A probe exception is recorded with its traceback and fails the whole check.
  · telemetry is passed through a read-only guard: quit_to_title (the byte fallback, a game-memory write) or any other
    non-read attribute is recorded and aborts the check instead of running.
  · the Escape watch thread is never started; one Pad, no bot loop.

Records: data/runs/<time>_freeze_probe_<mode>.probe.jsonl (harness: probe calls and returns, freeze / unfreeze order) and
.ctl.jsonl (control.Pad's pad / esc records: what reached the device). --help and argument errors import nothing that
touches the pad or the game (tests/freeze_probe_live_test.py checks that).
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOIN_TIMEOUT_S = 2.0
JOIN_SLICE_S = 0.05            # join in slices so Ctrl+C reaches the main thread while it waits


class Abort(Exception):
    """Stops the check. kind: probe_error · probe_unsafe · join_timeout · probe_alive_at_unfreeze · fallback_blocked · blocked_attr"""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind


def default_calls(pad, B) -> list[tuple]:
    """(name, call, expected return) — the non-holder calls the minimal patch blocks (PATCH_PLAN §1)."""
    A, Y = B.XUSB_GAMEPAD_A, B.XUSB_GAMEPAD_Y
    return [("keep_guard", lambda: pad.keep_guard(time.time() + 5.0), False),
            ("guard(True)", lambda: pad.guard(True), None),
            ("sprint(True)", lambda: pad.sprint(True), None),
            ("tap(A)", lambda: pad.tap(A, 0.05), None),
            ("hold(Y, True)", lambda: pad.hold(Y, True), None),
            ("release_due", pad.release_due, None),
            ("neutral", pad.neutral, None),
            ("kick", lambda: pad.kick(0.0, 1.0), None)]


class Harness:
    """Wraps one Pad instance's freeze / unfreeze (instance attributes; the class and other Pads are untouched)."""

    def __init__(self, pad, calls: list[tuple], join_timeout: float = JOIN_TIMEOUT_S, sink=None):
        self.pad, self.calls, self.join_timeout, self.sink = pad, calls, join_timeout, sink
        self.owner = threading.get_ident()
        self.stop = threading.Event()
        self.th: threading.Thread | None = None
        self.errors: list[str] = []
        self.blocked: list[str] = []
        self.refused = False
        self.events: list[dict] = []
        self._seq = itertools.count()
        self._mk = threading.Lock()
        self._armed = True
        self._real_freeze, self._real_unfreeze = pad.freeze, pad.unfreeze
        pad.freeze, pad.unfreeze = self._freeze, self._unfreeze

    def mark(self, ev: str, **kw) -> dict:
        with self._mk:
            rec = {"seq": next(self._seq), "pc": time.perf_counter_ns(), "th": threading.current_thread().name, "ev": ev, **kw}
            self.events.append(rec)
            if self.sink is not None:
                self.sink.write(json.dumps(rec, ensure_ascii=False, default=repr) + "\n")
                self.sink.flush()
        return rec

    def _freeze(self, take: bool = True) -> bool:
        ok = self._real_freeze(take)
        if threading.get_ident() != self.owner or not self._armed:
            self.mark("freeze_other", ok=ok, take=take)
            return ok
        self._armed = False
        if not ok:
            self.refused = True
            self.mark("freeze_refused", take=take)
            return False
        self.mark("freeze_ok", take=take, ep=self.pad.epoch)
        self.th = threading.Thread(target=self._probe, name="probe", daemon=True)
        try:                                       # Ctrl+C can land in start() as well as in the join
            self.th.start()
            self._join("freeze")
        except KeyboardInterrupt:
            self.stop.set()
            self.mark("interrupt", where="freeze")
            self.th.join(JOIN_SLICE_S * 4)
            raise
        self.mark("owner_resume")
        return True

    def _join(self, where: str) -> None:
        deadline = time.monotonic() + self.join_timeout
        while self.th.is_alive() and time.monotonic() < deadline:
            self.th.join(JOIN_SLICE_S)
        if self.th.is_alive():
            self.stop.set()
            self.mark("join_timeout", where=where, timeout_s=self.join_timeout)
            raise Abort("join_timeout", where)
        self.mark("probe_joined", where=where)
        if self.errors:
            raise Abort("probe_error" if any(e.startswith("raised") for e in self.errors) else "probe_unsafe", "; ".join(self.errors))

    def _unfreeze(self) -> None:
        if threading.get_ident() == self.owner and self.th is not None:
            alive = self.th.is_alive()
            self.mark("unfreeze_check", probe_alive=alive)
            if alive:
                raise Abort("probe_alive_at_unfreeze")
        self._real_unfreeze()
        self.mark("unfreeze_done", ep=self.pad.epoch)

    def _probe(self) -> None:
        try:
            for name, call, want in self.calls:
                if self.stop.is_set():
                    self.mark("probe_stopped", before=name)
                    break
                ep0 = self.pad.epoch
                self.mark("call", name=name, ep=ep0)
                try:
                    r = call()
                except BaseException as e:
                    self.errors.append(f"raised {name}: {e!r}")
                    self.mark("call_error", name=name, error=repr(e), tb=traceback.format_exc())
                    break
                ep1 = self.pad.epoch
                ok = r is want and ep1 == ep0
                self.mark("ret", name=name, ret=r, ep0=ep0, ep1=ep1, ok=ok)
                if not ok:
                    self.errors.append(f"unsafe {name}: returned {r!r} (want {want!r}), epoch {ep0}→{ep1}")
        finally:
            self.mark("probe_exit")


class _ReadOnlyPm:
    def __init__(self, pm, h: Harness):
        self._pm, self._h = pm, h

    def __getattr__(self, name):
        if name.startswith("read_"):
            return getattr(self._pm, name)
        self._h.blocked.append(f"pm.{name}")
        self._h.mark("blocked_attr", name=f"pm.{name}")
        raise Abort("blocked_attr", f"pm.{name}")


class GuardedTm:
    """Telemetry for fire(): only what quitout.quit_out / close_menu read. quit_to_title (byte quit = memory write) → Abort."""
    READ = frozenset({"snapshot", "menu_open", "base"})

    def __init__(self, tm, h: Harness):
        self._tm, self._h = tm, h

    def __getattr__(self, name):
        if name == "pm":
            return _ReadOnlyPm(self._tm.pm, self._h)
        if name in self.READ:
            return getattr(self._tm, name)
        self._h.blocked.append(name)
        kind = "fallback_blocked" if name == "quit_to_title" else "blocked_attr"
        self._h.mark(kind, name=name)
        raise Abort(kind, name)


def execute(h: Harness, body) -> dict:
    """Run body (fire / _nudge), then — only on the normal path — one guard request after unfreeze. Always release_all at the end."""
    pad = h.pad
    outcome, err = "normal", None
    try:
        r = body()
        h.mark("body_returned", ret=r)
        if h.refused:
            outcome = "refused"
        else:
            t = h.mark("recover_req")
            pad.guard(True)
            h.mark("recover_ret", held=pad.guard_held(), req_seq=t["seq"])
            pad.guard(False)
            pad.neutral()
    except Abort as e:
        outcome, err = e.kind, str(e)
    except KeyboardInterrupt:
        outcome = "interrupted"
    except Exception as e:
        outcome, err = "error", "".join(traceback.format_exception(e))
    finally:
        h.stop.set()
        alive = h.th is not None and h.th.is_alive()
        h.mark("cleanup", outcome=outcome, probe_alive=alive)
        pad.release_all()
        h.mark("released")
    ok = outcome == "normal" and not h.errors and not h.blocked
    return {"ok": ok, "outcome": outcome, "error": err, "probe_errors": list(h.errors), "blocked": list(h.blocked),
            "probe_started": h.th is not None, "probe_alive": h.th is not None and h.th.is_alive()}


def parse(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="freeze_probe_live.py", description="P-91/P-92 game check, variant J (see module docstring)")
    ap.add_argument("mode", choices=["quit", "nudge"])
    ap.add_argument("--variant", choices=["J"], default="J", help="only J exists (probe calls before the owner body)")
    ap.add_argument("--stick", nargs=2, type=float, default=[0.0, 0.5], metavar=("X", "Y"), help="nudge stick, each in [-1, 1]")
    ap.add_argument("--note", default="", help="free text into the records")
    a = ap.parse_args(argv)
    if any(abs(v) > 1.0 for v in a.stick):
        ap.error("--stick values must be within [-1, 1]")
    return a


def live(a: argparse.Namespace) -> int:
    """Game and device from here on — never reached by --help or an argument error."""
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("BOT_GAME", "dsr")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    import control
    import ctl
    import env
    import quitout
    from botlock import BotLock
    from souls import watch

    lock = BotLock()
    if not lock.acquire():
        print("a bot is running (data/bot.lock)")
        return 2
    stem = f"{time.strftime('%Y%m%d_%H%M%S')}_freeze_probe_{a.mode}"
    out = ROOT / "data" / "runs"
    out.mkdir(parents=True, exist_ok=True)
    pad = sink = None
    try:
        tm = env.make_telemetry({})
        if not quitout._in_world(tm):
            print("not in the world — start in game, standing still")
            return 2
        ctl.start(str(out / f"{stem}.ctl.jsonl"), run=stem, argv=sys.argv, cmd="freeze_probe")
        ctl.emit("life", ev="start", cmd="freeze_probe", args=vars(a))
        sink = (out / f"{stem}.probe.jsonl").open("w", encoding="utf-8")
        control.focus_game()
        pad = control.Pad()
        h = Harness(pad, default_calls(pad, control.B), sink=sink)
        h.mark("start", mode=a.mode, variant=a.variant, stick=a.stick, note=a.note)
        esc = watch.Escape(pad, nms=[], log=print)          # watch thread not started
        if a.mode == "quit":
            body = lambda: esc.fire("freeze probe J", "shake", tm=GuardedTm(tm, h))
        else:
            body = lambda: esc._nudge((a.stick[0], a.stick[1]))
        s = execute(h, body)
        h.mark("summary", **s)
        print(json.dumps(s, ensure_ascii=False, indent=1))
        print(f"→ {out / stem}.probe.jsonl · .ctl.jsonl")
        return 0 if s["ok"] else 1
    finally:
        if pad is not None:
            pad.close()
        if sink is not None:
            sink.close()
        ctl.stop()
        lock.release()


def main(argv=None) -> int:
    return live(parse(argv))


if __name__ == "__main__":
    raise SystemExit(main())
