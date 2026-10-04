"""P1-A: ctl event writer, lifecycle, hdr/sync — no game, no pad device (fake vgamepad where a Pad is needed).
python tests/ctl_writer_test.py

Checks:
  · off by default: emit is a no-op, no writer thread, no file
  · on: first records hdr (schema, clocks, wall_ns, commit) then sync (wall0 ≤ wall1, pc between); seq strictly increasing;
    periodic sync; end record with counts on stop
  · queue full while the writer is blocked: emit returns at once (caller never waits), drops are counted and one gap
    record (count, seq range) accounts for them — written seqs + gap ranges = every seq
  · writer failure: one reopen, then self-disable; emit keeps returning, nothing raised
  · lifecycle: atexit and console-close (via control's hooks) emit life records, after the pad is released
  · run.main: --ctl writes start + user_stop / exception_exit / normal_exit; without --ctl no ctl file appears
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import ctl

ROOT = Path(__file__).resolve().parent.parent


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def writer_threads() -> int:
    return sum(1 for t in threading.enumerate() if t.name == "ctl-writer" and t.is_alive())


def test_off() -> None:
    check("기본 꺼짐: on() False", not ctl.on())
    t0 = time.perf_counter()
    for _ in range(10000):
        ctl.emit("x", a=1)
    check("꺼짐: emit 1만 번이 거의 공짜 (< 50 ms)", time.perf_counter() - t0 < 0.05)
    check("꺼짐: writer 스레드 없음", writer_threads() == 0)


def test_on(tmp: Path) -> None:
    ctl.SYNC_S = 0.1
    p = tmp / "a.ctl.jsonl"
    ctl.start(p, run="t", argv=["x"], cmd="test")
    for i in range(50):
        ctl.emit("ev", i=i)
    time.sleep(0.35)
    summ = ctl.stop()
    r = rows(p)
    check("켜짐: 첫 줄 hdr", r[0]["k"] == "hdr" and r[0]["schema"] == ctl.SCHEMA and "perf_counter" in r[0]["clocks"]
          and isinstance(r[0]["wall_ns"], int))
    check("hdr: 시계 정보 (perf_counter = QPC 구현 이름 기록)", r[0]["clocks"]["perf_counter"]["impl"])
    s = r[1]
    check("둘째 줄 sync: wall0 ≤ wall1, sync_pc 정수", s["k"] == "sync" and s["wall0"] <= s["wall1"] and isinstance(s["sync_pc"], int))
    seqs = [x["seq"] for x in r]
    check("seq 엄격히 증가", all(a < b for a, b in zip(seqs, seqs[1:])))
    check("모든 줄에 k·seq·pc·th", all({"k", "seq", "pc", "th"} <= set(x) for x in r))
    evs = [x for x in r if x["k"] == "ev"]
    check("emit 50개 다 기록, 순서 그대로", [x["i"] for x in evs] == list(range(50)))
    check("pc 단조 증가 (emit 순)", all(a["pc"] <= b["pc"] for a, b in zip(evs, evs[1:])))
    check("주기 sync 여러 번", sum(1 for x in r if x["k"] == "sync") >= 3)
    check("끝 줄 end, 버린 것 0", r[-1]["k"] == "end" and r[-1]["dropped"] == 0 and summ["written"] >= 52)
    check("stop 뒤 꺼짐", not ctl.on() and writer_threads() == 0)
    ctl.SYNC_S = 5.0


class SlowFile:
    """Writes block until released — the writer thread stalls, the queue fills."""

    def __init__(self, path):
        self.f = open(path, "a", encoding="utf-8")
        self.gate = threading.Event()

    def write(self, s):
        self.gate.wait(10)
        return self.f.write(s)

    def flush(self):
        self.f.flush()

    def close(self):
        self.f.close()


def test_overflow(tmp: Path) -> None:
    ctl.QUEUE_MAX = 100
    p = tmp / "b.ctl.jsonl"
    holder: list = []
    ctl.start(p, run="t", argv=[], opener=lambda path: holder.append(SlowFile(path)) or holder[-1])
    time.sleep(0.05)                                   # writer is now stuck on hdr
    worst = 0.0
    for i in range(1000):
        t0 = time.perf_counter()
        ctl.emit("ev", i=i)
        worst = max(worst, time.perf_counter() - t0)
    check("큐 가득: emit 이 안 기다림 (최악 < 5 ms)", worst < 0.005)
    s = ctl._sink
    check("큐 가득: 버린 수를 셈", s.dropped > 800)
    holder[0].gate.set()
    ctl.stop()
    r = rows(p)
    gaps = [x for x in r if x["k"] == "gap"]
    check("gap 기록: 수·seq 범위", gaps and sum(g["count"] for g in gaps) == s.dropped
          and all(g["seq_from"] <= g["seq_to"] for g in gaps))
    ev = [x["seq"] for x in r if x["k"] == "ev"]
    lo, hi = min(ev + [g["seq_from"] for g in gaps]), max(ev + [g["seq_to"] for g in gaps])
    dropped_range = sum(g["seq_to"] - g["seq_from"] + 1 for g in gaps)
    check("기록된 ev + gap 범위 = ev 의 모든 seq (빠짐 없이 설명됨)", len(ev) + dropped_range == hi - lo + 1 == 1000)
    check("end 기록에 dropped", r[-1]["k"] == "end" and r[-1]["dropped"] == s.dropped)
    ctl.QUEUE_MAX = 20000


class BadFile:
    def write(self, s):
        raise OSError("disk full")

    def flush(self):
        pass

    def close(self):
        pass


def test_writer_failure(tmp: Path) -> None:
    opens: list = []
    ctl.start(tmp / "c.ctl.jsonl", run="t", argv=[], opener=lambda path: opens.append(1) or BadFile())
    for i in range(100):
        ctl.emit("ev", i=i)                            # must not raise
    time.sleep(0.3)
    s = ctl._sink
    check("writer 실패: 한 번 다시 연 뒤 스스로 꺼짐", len(opens) == 2 and not s.alive and s.write_errors >= 2)
    for i in range(100):
        ctl.emit("ev", i=i)
    check("꺼진 writer: emit 은 계속 그냥 돌아옴", True)
    summ = ctl.stop()
    check("stop 도 예외 없음", summ is not None and summ["write_errors"] >= 2)


CHILD = r'''
import sys, json, time
sys.path[:0] = [{root!r}, {tests!r}]
from pathlib import Path
import ctl, control, pad_fakes
pad_fakes.install(Path({tmp!r}))
ctl.start(Path({out!r}), run="child", argv=[])
pad = control.Pad()
pad.move(0.5, 0.5)
if {console!r}:
    control._on_console_event(2)
    print("handled", flush=True)
    import os; os._exit(0)          # like the default handler: no atexit after the console handler
'''


def test_lifecycle(tmp: Path) -> None:
    for console in (False, True):
        out = tmp / f"life_{console}.ctl.jsonl"
        src = CHILD.format(root=str(ROOT), tests=str(ROOT / "tests"), tmp=str(tmp), out=str(out), console=console)
        subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, timeout=60)
        r = rows(out)
        life = [x for x in r if x["k"] == "life"]
        if console:
            check("콘솔 닫기: life console 기록이 프로세스 끝 전에 디스크에 (flush)",
                  any(x["ev"] == "console" and x["console_ev"] == 2 and x["pads"] == 1 for x in life))
        else:
            check("정상 종료: life atexit 기록 + end", any(x["ev"] == "atexit" and x["pads"] == 1 for x in life)
                  and r[-1]["k"] == "end")


def test_run_main(tmp: Path) -> None:
    import run_stop_test as rst
    rst.install(tmp)
    for argv, exc, want in ((["run.py", "merchant", "--ctl"], KeyboardInterrupt(), "user_stop"),
                            (["run.py", "merchant", "--ctl"], RuntimeError("bug"), "exception_exit")):
        rst.TRACE.clear()
        rst.FakeMissions.exc = exc
        sys.argv = argv
        try:
            import run
            run.main()
        except BaseException:
            pass
        ctl.stop()                                     # in a real run atexit does this
        files = sorted((tmp / "data" / "runs").glob("*_merchant.ctl.jsonl"))
        r = rows(files[-1])
        evs = [x["ev"] for x in r if x["k"] == "life"]
        check(f"run.main --ctl: life start → {want}", evs[:1] == ["start"] and want in evs)
        files[-1].unlink()
    sys.argv = ["run.py", "merchant"]
    rst.FakeMissions.exc = KeyboardInterrupt()
    try:
        run.main()
    except BaseException:
        pass
    check("run.main --ctl 없음: ctl 파일 안 생김, 꺼진 채", not list((tmp / "data" / "runs").glob("*.ctl.jsonl")) and not ctl.on())


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="ctl_"))
    test_off()
    test_on(tmp)
    test_overflow(tmp)
    test_writer_failure(tmp)
    test_lifecycle(tmp)
    test_run_main(tmp)
    print("ctl_writer_test: 전부 통과")


if __name__ == "__main__":
    main()
