"""P1 control observability — one local event file per run, data/runs/<run>.ctl.jsonl. Off unless run.py --ctl.

  ctl.start(path, run=..., argv=..., cmd=...)    run.py --ctl: hdr + sync, writer thread, atexit stop
  ctl.emit("k", field=...)                       anywhere: never blocks, never raises; a no-op while off
  ctl.flush(timeout)                             exit paths (console handler) — wait until what's queued is written
  ctl.stop()                                     final sync + end record (atexit does it)

Every record: {"k", "seq", "pc", "th", ...}. pc = perf_counter_ns() (QPC) — the main clock. hdr / sync also carry
wall_ns (time.time_ns, ~15.6 ms on this Windows Python) only to line up loosely with wall-clock-only logs (Log lines,
radar rt, watchdog.log). seq is given when emit is called, so a record lost to a full queue leaves a hole that the
writer's "gap" record accounts for.

Rules (P1, MoKa 2026-10-02):
  · the caller only builds a dict and put_nowait()s it — no JSON, no I/O, no wait. Queue full → drop count + gap record.
  · a writer error: one reopen, then the writer disables itself; nothing reaches the caller (or the pad).
  · logging on/off must not change any pad report value or order — this module never touches the pad.
  · time points stay apart: a record's pc is when *we* did something. Game-side frame time / FPS / XInput read time are
    not measured here and must not be named as such.
"""
from __future__ import annotations

import itertools
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

SCHEMA = "ctl/1"
# ── 임시값 (P1, 근거 등급: 임시 제안값 — 정책 상수 아님) ────────────────
QUEUE_MAX = 20000        # records waiting for the writer (~200 s at 100 records/s)
FLUSH_S = 0.5            # writer flushes the file at least this often
SYNC_S = 5.0             # wall ↔ pc sync record period
EXIT_FLUSH_S = 1.0       # console-close handler waits at most this for the queue to drain

_seq = itertools.count()
_STOP = object()


class _Off:
    alive = False

    def put(self, k: str, f: dict) -> None:
        pass


_sink = _Off()
_atexit_hooked = False


def _clock(name: str) -> dict:
    i = time.get_clock_info(name)
    return {"impl": i.implementation, "res": i.resolution, "monotonic": i.monotonic, "adjustable": i.adjustable}


def _commit(root: Path) -> str | None:
    """HEAD commit read from .git (no subprocess). None if it can't be read."""
    try:
        g = root / ".git"
        head = (g / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head
        ref = head[5:]
        p = g / ref
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
        for line in (g / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0]
    except Exception:
        pass
    return None


def sync_fields() -> dict:
    """wall → pc → wall, back to back: the pc instant lies between wall0 and wall1."""
    w0 = time.time_ns()
    pc = time.perf_counter_ns()
    w1 = time.time_ns()
    return {"wall0": w0, "sync_pc": pc, "wall1": w1}


class Sink:
    def __init__(self, path: Path, opener=None):
        self.path = Path(path)
        self.opener = opener or (lambda p: open(p, "a", encoding="utf-8"))
        self.q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        self.alive = True
        self.written = self.dropped = self.write_errors = self.lost = 0
        self._reported = 0
        self._drop_lo = self._drop_hi = None
        self._drop_lock = threading.Lock()   # only on the overflow path
        self.last_error: str | None = None
        self._acc = itertools.count(1)              # records accepted into the queue (caller side) …
        self._last_acc = 0
        self._done = 0                               # … records the writer finished (written or lost) …
        self._flushed = 0                            # … and how many of those were on disk at the last flush
        self._want_flush = False                     # flush() asks the writer to flush now
        self._f = self.opener(self.path)
        self._th = threading.Thread(target=self._loop, daemon=True, name="ctl-writer")

    # ── caller side ──
    def put(self, k: str, f: dict) -> None:
        rec = {**f, "k": k, "seq": next(_seq), "pc": time.perf_counter_ns(), "th": threading.current_thread().name}
        try:
            self.q.put_nowait(rec)
            self._last_acc = next(self._acc)
        except queue.Full:
            with self._drop_lock:
                self.dropped += 1
                s = rec["seq"]
                self._drop_lo = s if self._drop_lo is None else min(self._drop_lo, s)
                self._drop_hi = s if self._drop_hi is None else max(self._drop_hi, s)

    # ── writer side ──
    def _write(self, rec: dict) -> None:
        self._f.write(json.dumps(rec, ensure_ascii=False, default=repr) + "\n")
        self.written += 1

    def _write_safe(self, rec: dict) -> None:
        if not self.alive:
            self.lost += 1
            return
        try:
            self._write(rec)
            return
        except Exception as e:
            self.write_errors += 1
            self.last_error = f"write: {e!r}"[:200]
        try:                                         # one reopen, then give up
            try:
                self._f.close()
            except Exception:
                pass
            self._f = self.opener(self.path)
            self._write({"k": "writer_error", "seq": next(_seq), "pc": time.perf_counter_ns(), "th": "ctl-writer",
                         "error": self.last_error, "reopened": True})
            self._write(rec)
        except Exception as e:
            self.write_errors += 1
            self.last_error = f"reopen: {e!r}"[:200]
            self.alive = False                       # self-disable: emit() becomes a no-op, nothing raised anywhere
            self.lost += 1

    def _gap(self) -> None:
        with self._drop_lock:
            n = self.dropped - self._reported
            lo, hi = self._drop_lo, self._drop_hi
            self._reported, self._drop_lo, self._drop_hi = self.dropped, None, None
        if n > 0:
            self._write_safe({"k": "gap", "seq": next(_seq), "pc": time.perf_counter_ns(), "th": "ctl-writer",
                              "reason": "queue_full", "count": n, "seq_from": lo, "seq_to": hi})

    def _sync(self) -> None:
        self._write_safe({"k": "sync", "seq": next(_seq), "pc": time.perf_counter_ns(), "th": "ctl-writer", **sync_fields()})

    def _loop(self) -> None:
        last_flush = last_sync = time.perf_counter()
        while True:
            try:
                rec = self.q.get(timeout=min(FLUSH_S, SYNC_S))   # wake for sync / flush even when idle
            except queue.Empty:
                rec = None
            if rec is _STOP:
                return
            self._gap()
            if rec is not None:
                self._write_safe(rec)
                self._done += 1
            now = time.perf_counter()
            if now - last_sync >= SYNC_S:
                last_sync = now
                self._sync()
            if now - last_flush >= FLUSH_S or self.q.empty() or self._want_flush:
                done = self._done
                if self.alive:
                    try:
                        self._f.flush()
                    except Exception as e:
                        self.write_errors += 1
                        self.last_error = f"flush: {e!r}"[:200]
                self._flushed, self._want_flush = done, False
                last_flush = now

    def start(self) -> "Sink":
        self._th.start()
        return self

    def flush(self, timeout: float) -> bool:
        """Wait until the queue is drained and written (exit paths). → True if it got there in time."""
        target = self._last_acc
        self._want_flush = True
        t1 = time.perf_counter() + timeout
        while time.perf_counter() < t1 and self._th.is_alive():
            if self._flushed >= target:
                return True
            time.sleep(0.005)
        return self._flushed >= target

    def stop(self, timeout: float = 2.0) -> dict:
        """Final sync + end record, close. Idempotent."""
        if self._th.is_alive():
            t1 = time.perf_counter() + timeout
            while time.perf_counter() < t1:
                try:
                    self.q.put(_STOP, timeout=0.1)
                    break
                except queue.Full:
                    continue
            self._th.join(max(0.0, t1 - time.perf_counter()))
        while True:                                  # whatever the writer never reached (it stopped) is counted as lost
            try:
                r = self.q.get_nowait()
            except queue.Empty:
                break
            if r is not _STOP:
                self.lost += 1
        self._gap()
        self._sync()
        summary = {"written": self.written, "dropped": self.dropped, "lost": self.lost,
                   "write_errors": self.write_errors, "last_error": self.last_error}
        self._write_safe({"k": "end", "seq": next(_seq), "pc": time.perf_counter_ns(), "th": threading.current_thread().name,
                          **summary})
        try:
            self._f.flush()
            self._f.close()
        except Exception:
            pass
        self.alive = False
        return summary


# ── module API ──

def emit(k: str, **fields) -> None:
    """Never blocks, never raises. No-op while ctl is off."""
    s = _sink
    if not s.alive:
        return
    try:
        s.put(k, fields)
    except Exception:
        pass


def on() -> bool:
    return _sink.alive


def start(path, run: str, argv: list, cmd: str | None = None, opener=None) -> Sink:
    """Open the event file and start the writer. The first records are hdr and sync. Call before the Pad is made, so
    atexit (last in, first out) closes the pad first and stops this after."""
    global _sink, _atexit_hooked
    stop()
    root = Path(__file__).resolve().parent
    s = Sink(Path(path), opener=opener)
    s.put("hdr", {"schema": SCHEMA, "run": run, "pid": os.getpid(), "cmd": cmd, "argv": list(argv),
                  "py": sys.version.split()[0], "commit": _commit(root), "wall_ns": time.time_ns(),
                  "clocks": {n: _clock(n) for n in ("perf_counter", "time", "monotonic")},
                  "note": "pc = perf_counter_ns (QPC) main clock; wall_ns only for loose alignment with wall-clock logs"})
    s.put("sync", sync_fields())
    _sink = s.start()
    if not _atexit_hooked:
        import atexit
        atexit.register(stop)
        _atexit_hooked = True
    return s


def flush(timeout: float = EXIT_FLUSH_S) -> bool:
    s = _sink
    if not s.alive or not isinstance(s, Sink):
        return True
    try:
        return s.flush(timeout)
    except Exception:
        return False


def stop() -> dict | None:
    global _sink
    s = _sink
    if not isinstance(s, Sink):
        return None
    _sink = _Off()
    try:
        return s.stop()
    except Exception:
        return None
