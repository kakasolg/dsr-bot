"""Counter trace (souls/counter_trace.py + rule_after_swing hooks + counter_report.py) — record only, no game.

  python tests/counter_trace_test.py

  · ctl on vs off: every golden situation (sampled) gives the same decision / pad-call trace; the trace's own hooks read no clock
  · P-89 scene (run 205644, 255041 3004 at 1.63 s): code as run (255041 unregistered) → window "a", limit 1.6, strike ×1 intent;
    current foes.py → no window, no intent
  · a window left by target A and used on target B shows A as its owner
  · the same-id restart limit and the null research fields are written, not filled in
  · a turn-only CONT is recorded as turn_only, not as an attack
  · emit raising: the rule picks the same thing, the error is counted
  · not_evaluated: an open window and an earlier rule → folded record naming that rule
  · counter_report pad link: issued / partial / dropped / unknown (gap, no outcome)
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import copy
import itertools
import json
import math
import time
from types import SimpleNamespace as NS

import ctl
import counter_report
import duel_golden_test as G
import scene_replay as R
from souls import counter_trace as CT
from souls import duel as D
from souls import foes

EXP = _pl.Path(__file__).resolve().parent / "expect"
T41, T42 = 472005904, 471999248


class Capture:
    """ctl on, records into a list with a seq like ctl's (no file, no clock)."""
    def __init__(self, raise_on=None):
        self.recs, self.seq, self.raise_on = [], itertools.count(), raise_on

    def __enter__(self):
        self.saved = (ctl.on, ctl.emit)
        ctl.on = lambda: True

        def emit(k, **f):
            if self.raise_on and k == self.raise_on:
                raise RuntimeError("sink down")
            self.recs.append({"k": k, "seq": next(self.seq), **f})
        ctl.emit = emit
        CT._state.clear()
        return self

    def __exit__(self, *a):
        for st in list(CT._state.values()):
            CT._flush(st)
        ctl.on, ctl.emit = self.saved

    def ct(self, ev=None):
        return [r for r in self.recs if r["k"] == "dec.counter" and (ev is None or r["ev"] == ev)]


def scene(n=3):
    return json.loads(next(EXP.glob(f"scene_p89_run{n}_*.json")).read_text(encoding="utf-8"))


def as_run(fn):
    """foes.py as it was for the 10-19 runs (2a97b61): 255041 unregistered."""
    e = foes.BY_NPC.pop(255041)
    try:
        return fn()
    finally:
        foes.BY_NPC[255041] = e


def test_on_off_same_trace_and_no_clock():
    sits = list(G.situations())[::40]
    calls = {"n": 0}
    real = time.time

    def counted():
        calls["n"] += 1
        return real()
    for sc in sits:
        off = G.run(sc)
        with Capture():
            on = G.run(sc)
        assert on == off, sc
    # clock reads with the trace vs with its hooks stubbed out (both ctl on): the same count
    hooks = {k: getattr(CT, k) for k in ("fight_start", "tick", "after_rules", "fight_end", "window", "expired", "blocked",
                                         "turn_only", "intent", "outcome")}
    counts = []
    for stub in (False, True):
        if stub:
            for k in hooks:
                setattr(CT, k, (lambda *a, **kw: None))
        time.time = counted
        calls["n"] = 0
        try:
            with Capture():
                for sc in sits[:200]:
                    G.run(sc)
        finally:
            time.time = real
            for k, v in hooks.items():
                setattr(CT, k, v)
        counts.append(calls["n"])
    assert counts[0] == counts[1], counts
    return len(sits), counts[0]


def test_recorded_scenes_on_off():
    """Every scene recorded in data/runs (not in git — skipped when absent): same rule and the same fake Moves / pad calls
    with the trace on and off. Offline command equality only — not game timing."""
    import glob
    files = sorted(glob.glob(str(_pl.Path(__file__).resolve().parent.parent / "data" / "runs" / "*.ctl.jsonl")))
    recs = [r for f in files for r in R.load([f])]
    if not recs:
        return 0
    seen = []
    base = R.Mv

    class Mv2(base):
        def __init__(self, s):
            super().__init__(s)
            seen.append(self.calls)

    def run():
        out = []
        for r in recs:
            seen.clear()
            out.append((R.replay(r), [list(c) for c in seen]))
        return out
    R.Mv = Mv2
    try:
        off = run()
        with Capture():
            on = run()
    finally:
        R.Mv = base
    assert on == off
    return len(recs)


def test_p89_scene_then_and_now():
    rec = scene(3)
    with Capture() as cap:
        got = as_run(lambda: R.replay(rec))
    assert got == "after_swing"
    win = cap.ct("window_open")
    assert len(win) == 1 and win[0]["basis"] == "a" and win[0]["limit"]["limit_s"] == D.SWING_S and win[0]["foe"]["unknown"]
    it = cap.ct("intent")
    assert len(it) == 1 and it[0]["presses"] == 1 and it[0]["target"]["ptr"] == T41 and it[0]["conds"]["single"] is True
    assert it[0]["owners"]["swing_end_from"] == T41 and it[0]["observed_id_age"] == win[0]["observed_id_age"]
    assert cap.ct("outcome")[0]["status"] == "returned"
    with Capture() as cap2:
        got2 = R.replay(rec)
    assert got2 == "late_windup_block" and cap2.ct("window_open") == [] and cap2.ct("intent") == []
    return win[0], it[0]


def test_owner_from_other_target():
    rec = copy.deepcopy(scene(3))
    p = rec["snap"]["player"]
    for c in rec["snap"]["chars"]:
        if c["ptr"] == T42:                                  # 255042 brought to 1.2 m straight ahead, idle
            c["x"], c["z"], c["anim"] = p["x"] - 1.2 * math.sin(p["heading"]), p["z"] - 1.2 * math.cos(p["heading"]), -1
        if c["ptr"] == T41:
            c["anim"] = -1
    rec["tick"] = {"ptr": T42, "h": 1.2, "dy": 0.0, "a": -1}
    rec["fight"]["ptr"], rec["fight"]["orig_ptr"] = T42, None   # the fight's target is now 255042
    rec["fight"]["_aprev"] = -1
    rec["fight"]["_swing_end_t"] = {"_t": -0.2}             # a window opened 0.2 s ago …
    rec["fight"]["_swing_end_from"] = T41                    # … on 255041, now the target is 255042
    with Capture() as cap:
        as_run(lambda: R.replay(rec))
    ev = cap.ct()
    it = cap.ct("intent")
    blk = cap.ct("eval")
    if it:
        assert it[0]["owners"]["swing_end_from"] == T41 and it[0]["target"]["ptr"] == T42
        return "intent", it[0]["owners"]
    assert blk and blk[0]["window_from"] == T41 and blk[0]["ptr"] == T42, ev
    return "eval", blk[0]


def test_restart_limit_and_research_nulls():
    with Capture() as cap:
        as_run(lambda: R.replay(scene(3)))
    for r in cap.ct("window_open") + cap.ct("intent"):
        assert r["anim_time"] is None and r["hitbox"] is None and r["tae"] is None
        assert "not detectable" in r["id_restart"] and r["anim_time_why"] and r["hitbox_why"] and r["tae_why"]


def test_turn_only_is_not_an_attack():
    rec = copy.deepcopy(scene(3))
    rec["snap"]["player"]["heading"] += math.pi              # body turned away from 255041
    with Capture() as cap:
        got = as_run(lambda: R.replay(rec))
    assert got == "after_swing"                              # the rule acted (CONT) …
    ev = cap.ct("eval")
    assert ev and ev[-1]["outcome"] == "turn_only" and ev[-1]["attack"] is False
    assert cap.ct("intent") == [] and cap.ct("outcome") == []   # … but no attack was intended


def test_emit_error_keeps_the_decision():
    e0 = CT.stats["errors"]
    with Capture(raise_on="dec.counter"):
        got = as_run(lambda: R.replay(scene(3)))
    assert got == "after_swing" and CT.stats["errors"] > e0


def test_not_evaluated_fold():
    class Fake:                                              # a Fight stand-in (the trace keeps per-fight state by weakref)
        pass
    F = Fake()
    F.__dict__.update(ptr=T41, _swing_end_t=100.0, _swing_end_from=T41, orig_ptr=None, shadow=None)
    T = NS(now=100.1, s=NS(t=100.1, fseq=None, pc=None), c=None)
    with Capture() as cap:
        CT.after_rules(F, T, "finish_first", D._RULE_NAMES)
        CT.after_rules(F, T, "finish_first", D._RULE_NAMES)
        CT.after_rules(F, T, "block", D._RULE_NAMES)        # after after_swing in RULES → after_swing did run, nothing to note
        T2 = NS(now=100.9, s=T.s, c=None)
        CT.after_rules(F, T2, "finish_first", D._RULE_NAMES)   # window over (0.9 > 0.6) → nothing
        CT.fight_end(F, NS(result="killed"))
    ne = cap.ct("not_evaluated")
    assert len(ne) == 1 and ne[0]["n"] == 2 and ne[0]["by"] == "finish_first" and ne[0]["window_from"] == T41
    return ne[0]


def test_report_pad_link():
    def recs(*pads, outcome=True, gap=False, drop=False):
        r = [{"k": "dec.counter", "ev": "fight_start", "seq": 5},
             {"k": "dec.counter", "ev": "intent", "seq": 10, "dec": 1, "kind": "strike", "presses": 2, "target": {}, "foe": {}}]
        r += [{"k": "pad", "seq": 10 + i + 1, "th": "MainThread", "btn": b, "caller": "moves.py:light:312"} for i, b in enumerate(pads)]
        if drop:
            r.append({"k": "pad.drop", "seq": 18, "th": "MainThread"})
        if gap:
            r.append({"k": "gap", "seq": 30, "seq_from": 15, "seq_to": 16, "count": 2})
        if outcome:
            r.append({"k": "dec.counter", "ev": "outcome", "seq": 20, "dec": 1, "status": "returned"})
        r.append({"k": "dec.counter", "ev": "fight_end", "seq": 25})
        return r
    st = lambda rr: counter_report.report(rr, [])["strikes"][0]["pad"]["status"]   # noqa: E731
    assert st(recs(0x300, 0x100, 0x300, 0x100)) == "issued"
    assert st(recs(0x300, 0x100)) == "partial"
    assert st(recs(0x100)) == "not_issued"
    assert st(recs(0x100, drop=True)) == "dropped"
    assert st(recs(0x300, 0x100, 0x300, gap=True)) == "unknown"
    assert st(recs(0x300, outcome=False)) == "unknown"
    rr = recs(0x300, 0x300, 0x300)
    rr[1]["th"] = "guardkeep"                               # another thread's record is not ours
    assert counter_report.report(rr, [])["strikes"][0]["pad"]["rb_edges"] == 1


def fight(base: int, dec: int = 1, presses: int = 2, outcome: dict | None = None, pads=(), extra=(), end=True,
          intent_extra: dict | None = None) -> list[dict]:
    """One fight's records at seq base…base+50: fight_start, intent (dec), pads, outcome (or None), fight_end."""
    r = [{"k": "dec.counter", "ev": "fight_start", "seq": base},
         {"k": "dec.counter", "ev": "intent", "seq": base + 10, "dec": dec, "kind": "strike", "presses": presses, "target": {},
          "foe": {}, **(intent_extra or {})}]
    r += [{"k": "pad", "seq": base + 11 + i, "th": "MainThread", "btn": b, "caller": "moves.py:light:312"} for i, b in enumerate(pads)]
    r += list(extra)
    if outcome is not None:
        r.append({"k": "dec.counter", "ev": "outcome", "seq": base + 30, "dec": dec, "status": "returned", **outcome})
    if end:
        r.append({"k": "dec.counter", "ev": "fight_end", "seq": base + 40})
    return r


def test_report_three_fights_dec_1():
    """dec is 1 in every fight (the 10-19 live run): each intent keeps its own fight's outcome and pads."""
    two = (0x300, 0x100, 0x300, 0x100)
    rr = (fight(100, pads=(0x300, 0x100), outcome={"presses_counted": 1, "dead": True}, presses=1)
          + fight(200, pads=(0x300, 0x100), outcome={"presses_counted": 1, "dead": True})
          + fight(300, pads=two, outcome={"presses_counted": 2, "dead": True}))
    sts = counter_report.report([{"k": "hdr", "run": "R"}] + rr, [])["strikes"]
    assert [s["key"] for s in sts] == [["R", 100, 1], ["R", 200, 1], ["R", 300, 1]]
    assert [s["outcome_seq"] for s in sts] == [130, 230, 330]
    assert [s["pad"]["status"] for s in sts] == ["issued", "partial", "issued"]
    assert [s["pad"]["rb_edges"] for s in sts] == [1, 1, 2]
    assert sts[1]["pad"]["partial_reason"] == "target_dead"           # 2 intended, 1 pressed, target died — not an input failure


def test_report_never_borrows_from_another_fight():
    ok = {"presses_counted": 2, "dead": False}
    # fight 1 has no outcome; fight 2 does (same dec) → fight 1 stays unknown, not paired with fight 2's
    sts = counter_report.report(fight(100, pads=(0x300, 0x100), outcome=None) + fight(200, pads=(0x300, 0x100, 0x300), outcome=ok), [])["strikes"]
    assert sts[0]["pad"]["status"] == "unknown" and "no outcome" in sts[0]["pad"]["why"] and sts[0]["outcome_seq"] is None
    assert sts[1]["outcome_seq"] == 230 and sts[1]["pad"]["status"] == "issued"
    # fight 1 with no fight_end and no outcome, fight 2 starts: the open fight ends at fight 2's start
    sts = counter_report.report(fight(100, pads=(0x300, 0x100), outcome=None, end=False) + fight(200, pads=(0x300, 0x100, 0x300), outcome=ok), [])["strikes"]
    assert sts[0]["pad"]["status"] == "unknown" and sts[1]["outcome_seq"] == 230
    # two outcomes for one (fight, dec)
    dup = fight(100, pads=(0x300, 0x100, 0x300), outcome=ok)
    dup.insert(-1, {"k": "dec.counter", "ev": "outcome", "seq": 135, "dec": 1, "status": "returned", **ok})
    s = counter_report.report(dup, [])["strikes"][0]
    assert s["pad"]["status"] == "unknown" and "two outcomes" in s["pad"]["why"]
    # two intents with one key
    dup2 = fight(100, pads=(0x300,), outcome=ok)
    dup2.insert(2, {"k": "dec.counter", "ev": "intent", "seq": 105, "dec": 1, "kind": "strike", "presses": 1, "target": {}, "foe": {}})
    assert all(s["pad"]["status"] == "unknown" for s in counter_report.report(dup2, [])["strikes"])
    # a ctl gap inside the range → unknown, the next fight untouched
    gap = [{"k": "gap", "seq": 400, "seq_from": 112, "seq_to": 113, "count": 2}]
    sts = counter_report.report(fight(100, pads=(0x300, 0x100, 0x300, 0x100), outcome=ok, extra=gap) + fight(200, pads=(0x300, 0x100, 0x300), outcome=ok), [])["strikes"]
    assert sts[0]["pad"]["status"] == "unknown" and sts[1]["pad"]["status"] == "issued"
    # an intent before any fight_start
    stray = [{"k": "dec.counter", "ev": "intent", "seq": 50, "dec": 1, "kind": "strike", "presses": 1, "target": {}, "foe": {}}]
    s = counter_report.report(stray + fight(100, pads=(0x300,), outcome=ok), [])["strikes"][0]
    assert s["pad"]["status"] == "unknown" and "outside any fight" in s["pad"]["why"]


def test_report_partial_reasons():
    r = lambda **kw: counter_report.report(fight(100, **kw), [])["strikes"][0]["pad"]   # noqa: E731
    assert r(pads=(0x300, 0x100), outcome={"presses_counted": 1, "dead": True})["partial_reason"] == "target_dead"
    assert r(pads=(0x300, 0x100), outcome={"presses_counted": 2, "dead": False})["partial_reason"] == "input_missing"
    assert r(pads=(0x300, 0x100), outcome={"presses_counted": 1, "dead": False},
             intent_extra={"me": {"sp": 40}, "conds": {"sp_min": 60}})["partial_reason"] == "sp_below_second"
    assert r(pads=(0x300, 0x100), outcome={"presses_counted": 1, "dead": False})["partial_reason"] == "unexplained"
    assert r(pads=(0x300, 0x100), outcome={"presses_counted": 1, "dead": False},
             extra=[{"k": "pad.drop", "seq": 120, "th": "MainThread"}])["status"] == "dropped"


def test_live_run_three_decisions():
    """The 10-19 live run (data/runs, not in git — skipped when absent): the hand-checked result."""
    p = _pl.Path(__file__).resolve().parent.parent / "data" / "runs" / "20261019_232719_parish-group1.ctl.jsonl"
    if not p.exists():
        return None
    sts = counter_report.report(counter_report.load(p), [])["strikes"]
    got = [(s["seq"], s["outcome_seq"], s["pad"]["status"], s["pad"]["rb_edges"], s["pad"].get("partial_reason")) for s in sts]
    assert got == [(3619, 3623, "issued", 1, None), (3742, 3745, "partial", 1, "target_dead"), (3918, 3923, "issued", 2, None)], got
    return got


def main():
    n, clocks = test_on_off_same_trace_and_no_clock()
    print(f"ok  ctl on/off: {n} golden situations, same trace; time.time calls with/without trace hooks equal ({clocks})")
    n = test_recorded_scenes_on_off()
    print(f"ok  recorded scenes on/off: {n} scenes, same rule and fake pad calls" if n else "skip recorded scenes (no data/runs)")
    test_p89_scene_then_and_now()
    print("ok  P-89 scene: as run → window a / limit 1.6 / strike ×1 intent; now → no window, no intent")
    print(f"ok  owner across targets: {test_owner_from_other_target()[0]}")
    test_restart_limit_and_research_nulls()
    print("ok  research fields null with reasons, same-id restart marked undetectable")
    test_turn_only_is_not_an_attack()
    print("ok  turn-only CONT recorded as turn_only, no intent")
    test_emit_error_keeps_the_decision()
    print("ok  emit error: same decision, error counted")
    test_not_evaluated_fold()
    print("ok  not_evaluated folded by the preempting rule")
    test_report_pad_link()
    print("ok  report pad link: issued / partial / not_issued / dropped / unknown")
    test_report_three_fights_dec_1()
    print("ok  report: dec 1 in three fights → each paired inside its own fight")
    test_report_never_borrows_from_another_fight()
    print("ok  report: missing / duplicate outcome, duplicate intent, gap, stray intent → unknown, never another fight's")
    test_report_partial_reasons()
    print("ok  report partial reasons: target_dead / input_missing / sp_below_second / unexplained / dropped")
    got = test_live_run_three_decisions()
    print(f"ok  live run 232719: {got}" if got else "skip live run (no data/runs)")


if __name__ == "__main__":
    main()
