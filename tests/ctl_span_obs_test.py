"""ctlspan span.obs records (the snapshot _sense read, copied when Fight.sensed runs) and what ctl_check.py makes of them.
Offline, real telemetry dataclasses, no game — nothing here measures game-side delay.

  · the stored body is a copy: changing the snapshot / its Chr objects / its list afterwards does not change the file
  · restore() gives back every stored field and the Chr list in order; src feed (fseq) vs direct
  · different observations → different obs_id; obs_id never equals another span id
  · the read counter: only this thread's reads inside an open cycle; sense_only / partial / reads_uncounted
  · a dropped obs (queue full) → "dropped", a removed one → "missing"; a broken snapshot → obs_err, nothing raised
  · writer complete (end record) True while some cycles are partial: reported apart
  · size and copy / json cost of one representative snapshot (this machine, offline — not a game load figure)
The golden-trace checks with obs on (sink raising, queue full, broken ids) are in ctl_spans_test.py.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parents[1]), str(_pl.Path(__file__).resolve().parent)]

import dataclasses
import json
import queue
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import ctl
import ctl_check
import ctlspan
from telemetry import Chr, Snapshot


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def chr_(ptr, x, hp=100, anim=-1, dist=1.0) -> Chr:
    return Chr(ptr=ptr, npc_param=255000 + ptr % 100, team=6, hp=hp, max_hp=102, x=x, y=26.6, z=100.0 + x, sp=0, max_sp=0,
               anim=anim, dist=dist, name="Soldier")


def snap(t, n=3, fseq=None) -> Snapshot:
    pl = Chr(ptr=1, npc_param=0, team=1, hp=793, max_hp=793, x=28.3, y=26.6, z=104.0, sp=100, max_sp=100, anim=-1,
             gx=1.0, gy=2.0, gz=3.0, heading=0.5, map_id=1)
    return Snapshot(t=t, player=pl, chars=[chr_(1000 + i, 30.0 + i, dist=1.0 + i) for i in range(n)], cam_yaw=0.25,
                    cam_pitch=None, fseq=fseq, pc=123 if fseq else None)


def tick(s) -> SimpleNamespace:
    return SimpleNamespace(s=s, p=s.player, c=s.chars[0], now=s.t + 0.001)


def cycle(sp, s, reads_sense=1, reads_after=0, picked="block"):
    sp.cycle_start()
    for _ in range(reads_sense):
        ctlspan.snap_read()
    T = tick(s)
    sp.sensed(T, 100.0)
    for _ in range(reads_after):
        ctlspan.snap_read()
    sp.rule_enter()
    sp.rule_return(picked, "continue")
    sp.cycle_end("rule_cont", picked, T)
    return T


def rows(path: Path) -> list[dict]:
    return ctl_check.load(path)


def run(path: Path, body, opener=None) -> list[dict]:
    ctl.start(path, run="t", argv=["x"], cmd="test", opener=opener)
    ctlspan.ON = True
    try:
        body()
    finally:
        ctlspan.ON = False
        ctl.flush(5.0)
        ctl.stop()
        ctlspan._tl.__dict__.clear()
    return rows(path)


def test_copy_restore_src(tmp: Path) -> None:
    s1, s2 = snap(1000.0), snap(1000.1, n=5, fseq=2923)
    want1 = {"player": dataclasses.asdict(s1.player), "chars": [dataclasses.asdict(c) for c in s1.chars]}
    keep = {}

    def body():
        sp = ctlspan.Fight(1000)
        cycle(sp, s1)
        s1.player.hp = 1                                         # after sensed(): the bot's objects change …
        s1.chars[0].x = -999.0
        s1.chars.append(chr_(9999, 0.0))
        s1.cam_yaw = 9.9
        cycle(sp, s2)
        sp.end(None)
        keep["ids"] = (sp.id,)
    r = run(tmp / "copy.ctl.jsonl", body)
    obs = [x for x in r if x["k"] == "span.obs"]
    ce = [x for x in r if x["k"] == "span.cycle" and x["ev"] == "end"]
    check("obs: one per sensed cycle, the cycle end names it", len(obs) == 2 and [c["obs_id"] for c in ce] == [o["obs_id"] for o in obs])
    b1 = ctl_check.restore(r, ce[0]["obs_id"])
    check("obs: changing the snapshot after sensed() leaves the stored body as it was (player HP, a Chr's x, list length, cam)",
          b1["player"]["hp"] == 793 and b1["chars"][0]["x"] == 30.0 and len(b1["chars"]) == 3 and b1["cam_yaw"] == 0.25)
    check("obs: restore gives every Chr field of the player and of each char, chars in the same order",
          b1["player"] == want1["player"] and b1["chars"] == want1["chars"])
    check("obs: every Snapshot field held (t pc fseq cam_yaw cam_pitch arm_style flask_hp max_flask_hp) + now + target ptr",
          set(ctlspan._SNAP_F) <= set(b1) and b1["t"] == 1000.0 and b1["now"] == 1000.001 and b1["target_ptr"] == 1000)
    b2 = ctl_check.restore(r, ce[1]["obs_id"])
    check("obs: src direct (no fseq) vs feed (fseq kept)", b1["src"] == "direct" and b1["fseq"] is None
          and b2["src"] == "feed" and b2["fseq"] == 2923 and ce[1]["src"] == "feed")
    check("obs: two observations → two obs_ids, each with its own t and char list",
          ce[0]["obs_id"] != ce[1]["obs_id"] and b2["t"] == 1000.1 and [c["ptr"] for c in b2["chars"]] == [1000, 1001, 1002, 1003, 1004])
    ids = {x.get(k) for x in r for k in ("cycle_id", "fight_id", "rule_id", "action_id") if x["k"].startswith("span.")}
    check("obs: obs_id never equals a fight / cycle / rule id", not ({o["obs_id"] for o in obs} & ids))


def test_reads_and_status(tmp: Path) -> None:
    def body():
        sp = ctlspan.Fight(1)
        cycle(sp, snap(1.0), reads_sense=1, reads_after=0)       # sense_only
        cycle(sp, snap(2.0), reads_sense=1, reads_after=2)       # rules read twice more → partial
        cycle(sp, snap(3.0), reads_sense=2, reads_after=0)       # F.cancel read inside _sense → partial
        cycle(sp, snap(4.0), reads_sense=0)                      # nothing counted → can't tell
        sp.cycle_start()                                         # a read on another thread doesn't count here
        ctlspan.snap_read()
        th = threading.Thread(target=lambda: [ctlspan.snap_read() for _ in range(5)])
        th.start(); th.join()
        T = tick(snap(5.0))
        sp.sensed(T, 100.0)
        sp.cycle_end("rule_cont", None, T)
        sp.cycle_start()
        sp.cycle_end("sense_cont")                               # _sense ended the cycle: no obs
        sp.end(None)
    r = run(tmp / "reads.ctl.jsonl", body)
    ce = [x for x in r if x["k"] == "span.cycle" and x["ev"] == "end"]
    st = ctl_check.input_status(r)
    got = [st[c["cycle_id"]][0] for c in ce]
    check(f"reads: statuses {got}", got == ["sense_only", "partial", "partial", "reads_uncounted", "sense_only", "no_obs"])
    check("reads: counts in the cycle end (sense / after)", [(c["snap_reads_sense"], c["snap_reads_after"]) for c in ce[:5]]
          == [(1, 0), (1, 2), (2, 0), (0, 0), (1, 0)])
    end = [x for x in r if x["k"] == "end"][-1]
    check("reads: writer complete True in the same file that has partial cycles — the checker keeps them apart",
          end["complete"] is True and "partial" in got)
    ctlspan.snap_read()
    check("reads: snap_read with no open cycle does nothing and raises nothing", True)


def test_missing_dropped_broken(tmp: Path) -> None:
    def body():
        sp = ctlspan.Fight(1)
        cycle(sp, snap(1.0))
        real = ctl._sink.q.put_nowait

        def full(rec):                                           # the queue is full only for this obs record (test only)
            if isinstance(rec, dict) and rec.get("k") == "span.obs":
                raise queue.Full
            return real(rec)
        ctl._sink.q.put_nowait = full
        cycle(sp, snap(2.0))
        ctl._sink.q.put_nowait = real
        time.sleep(0.6)                                          # the writer's next turn writes the gap record
        cycle(sp, snap(3.0))
        bad = SimpleNamespace(s=SimpleNamespace(t=4.0, fseq=None, player=None, chars=None), c=None, now=4.0)
        sp.cycle_start()
        sp.sensed(bad, 100.0)                                    # chars None → the copy fails inside ctlspan
        sp.cycle_end("rule_cont", None, bad)
        sp.end(None)
    r = run(tmp / "drop.ctl.jsonl", body)
    ce = [x for x in r if x["k"] == "span.cycle" and x["ev"] == "end"]
    st = ctl_check.input_status(r)
    got = [st[c["cycle_id"]][0] for c in ce]
    check(f"drop: queue-full obs → 'dropped' (gap record overlaps the cycle), others sense_only, broken → no_obs {got}",
          got == ["sense_only", "dropped", "sense_only", "no_obs"] and any(x["k"] == "gap" for x in r))
    check("drop: the broken snapshot left obs_err in the cycle end, nothing raised", ce[3]["obs_err"] == "TypeError")
    r2 = [x for x in r if not (x["k"] == "span.obs" and x["obs_id"] == ce[2]["obs_id"])]   # an obs gone with no gap to explain it
    check("drop: an obs removed from the file with no gap → 'missing', not sense_only",
          ctl_check.input_status(r2)[ce[2]["cycle_id"]][0] == "missing")
    old = [dict(x) for x in r if x["k"] != "span.obs"]
    for x in old:
        if x["k"] == "span.cycle":
            x.pop("obs_id", None)
    check("drop: a file from before obs (no obs_id field) → no_obs with that reason",
          all(s == "no_obs" for s, _ in ctl_check.input_status(old).values()))


def test_cost() -> None:
    s = snap(time.time(), n=15)
    n = 2000
    t0 = time.perf_counter_ns()
    for _ in range(n):
        b = ctlspan._snap_body(s)
    t1 = time.perf_counter_ns()
    rec = {"obs_id": 1, "cycle_id": 2, "src": "direct", "fseq": None, "radius": 100.0, "now": s.t, "target_ptr": 1000, "snap": b,
           "k": "span.obs", "seq": 1, "pc": 1, "th": "MainThread"}
    for _ in range(n):
        line = json.dumps(rec, ensure_ascii=False, default=repr)
    t2 = time.perf_counter_ns()
    print(f"     cost (this PC, offline, player + 15 chars): copy in sensed() {(t1 - t0) / n / 1000:.1f} µs on the caller thread · "
          f"json {(t2 - t1) / n / 1000:.1f} µs on the writer thread · {len(line.encode())} bytes per line")
    check("cost: measured (a figure for this snapshot only, not a game load)", len(line) > 0)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="ctlspanobs_"))
    test_copy_restore_src(tmp)
    test_reads_and_status(tmp)
    test_missing_dropped_broken(tmp)
    test_cost()
    check("end: ctl off, spans off", not ctl.on() and not ctlspan.ON)
    print("ctl_span_obs_test: 전부 통과")


if __name__ == "__main__":
    main()
