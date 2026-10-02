"""The attack audit (attack_audit.py) must not change a single fight decision, never block or break the fight loop, and
record only inputs frozen before the attack rule ran. No game, no model.

  python tests/attack_audit_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import ast
import gzip
import itertools
import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import attack_audit as AA
import duel_golden_test as G
import laya_shadow as LS
from field_fakes import World
from souls import duel as D, moves as M, style as ST, weapons

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "experiments"))
import attack_audit_check as CHK  # noqa: E402


class MemorySink:
    def __init__(self):
        self.recs = []

    def put(self, rec):
        self.recs.append(rec)
        return True

    def close(self, footer):
        self.recs.append(footer)
        return {"written": len(self.recs)}


class RaisingSink:
    def put(self, rec):
        raise OSError("disk gone")

    def close(self, footer):
        raise OSError("disk gone")


class Boom:
    """Stands in for F.mv while the tap runs — any use of Moves / the pad fails loudly."""
    def __getattr__(self, name):
        raise AssertionError(f"tap touched Moves.{name}")


class NoMovesTap(AA.DecisionTap):
    def _guard(self, F, fn, *a):
        saved, F.mv = F.mv, Boom()
        try:
            return fn(F, *a)
        finally:
            F.mv = saved

    def freeze(self, F, T):
        return self._guard(F, super().freeze, T)

    def decided(self, F, T, tok, rule, out):
        return self._guard(F, super().decided, T, tok, rule, out)

    def sensed(self, F, T):
        return self._guard(F, super().sensed, T)

    def end(self, F, res):
        return self._guard(F, super().end, res)


def sample(step: int = 4):
    sits = itertools.chain(G.situations(), G.situations_terrain(), G.situations_axe())
    return [sc for i, sc in enumerate(sits) if i % step == 0]


# ── behaviour ──
def test_golden_unchanged_with_tap() -> None:
    """Every golden situation (the full recorded set) gives the recorded trace with the audit on."""
    want = json.loads(gzip.decompress(G.GOLDEN.read_bytes()).decode("utf-8"))
    taps, n = [], 0
    for sc in itertools.chain(G.situations(), G.situations_terrain(), G.situations_axe()):
        tap = NoMovesTap(MemorySink(), "golden")
        got = G.run(sc, tap=tap)
        assert got == want[json.dumps(sc, sort_keys=True)], f"decision changed with the audit on: {sc}"
        taps.append(tap)
        n += 1
    errs = [t.last_error for t in taps if t.errors]
    assert not errs, errs[:3]
    rows = sum(t.counts["attack_rule_invocation_snapshot"] + t.counts["audit_ambiguous_multi_attack"] for t in taps)
    assert rows > 1000, rows
    print(f"ok  {n} golden situations with the audit on: every trace as recorded, tap errors 0, {rows} attack rows, Moves untouched")


def _stalled_writer(d):
    gate = threading.Event()

    class Slow:
        def write(self, s):
            gate.wait(10.0)

        def flush(self):
            pass

        def fileno(self):
            raise OSError

        def close(self):
            pass
    return AA.AuditWriter(Path(d) / "a.jsonl", {"rec": "run_header"}, queue_max=1, opener=lambda p: Slow()), gate


def test_failures_do_not_change_flow() -> None:
    """Sink raising, features() broken, freeze broken, writer stalled with a 1-slot queue: same traces, nothing raised,
    and the fight loop never waits on the writer."""
    sits = sample(16)
    base = [G.run(sc) for sc in sits]
    real_features, real_freeze = LS.features, LS.freeze
    with tempfile.TemporaryDirectory() as d:
        writer, gate = _stalled_writer(d)
        variants = {
            "sink raises": lambda: AA.DecisionTap(RaisingSink(), "x"),
            "stalled writer": lambda: AA.DecisionTap(writer, "x"),
        }
        worst = 0.0
        for name, make in variants.items():
            for sc, want in zip(sits, base):
                tap = make()
                t0 = time.perf_counter()
                got = G.run(sc, tap=tap)
                worst = max(worst, time.perf_counter() - t0)
                assert got == want, f"{name}: decision changed in {sc}"
        put_t = []
        for i in range(200):                                 # producer side against the stalled writer
            t0 = time.perf_counter()
            writer.put({"seq": i})
            put_t.append(time.perf_counter() - t0)
        assert max(put_t) < 0.005, f"put waited {max(put_t) * 1000:.1f} ms"
        assert writer.dropped > 0
        gate.set()
        writer.close({"rec": "run_footer"})
    for name, patch in (("features raises", lambda: setattr(LS, "features", lambda F, T: 1 / 0)),
                        ("freeze raises", lambda: setattr(LS, "freeze", lambda *a, **k: 1 / 0))):
        patch()
        try:
            for sc, want in zip(sits, base):
                tap = AA.DecisionTap(MemorySink(), "x")
                assert G.run(sc, tap=tap) == want, f"{name}: decision changed"
        finally:
            LS.features, LS.freeze = real_features, real_freeze
    print(f"ok  {len(sits)} situations × 4 failure variants: same decisions; put() against a stalled writer ≤ {max(put_t) * 1e6:.0f} µs")


# ── freeze contract ──
_LIVE_SKIP = {"mv", "log", "cancel", "res", "events", "may_approach", "shadow", "acts"}


def _graph_ids(root, depth=5, skip=()) -> dict:
    """id → object for every mutable object reachable from root (attributes, list/dict/tuple items)."""
    out, stack = {}, [(root, 0)]
    while stack:
        o, k = stack.pop()
        if o is None or LS.is_immutable(o) or id(o) in out or k > depth or callable(o) and not hasattr(o, "__dict__"):
            continue
        out[id(o)] = o
        if isinstance(o, dict):
            items = list(o.values())
        elif isinstance(o, (list, tuple, set, frozenset)):
            items = list(o)
        else:
            items = [v for a, v in getattr(o, "__dict__", {}).items() if a not in skip]
        stack.extend((v, k + 1) for v in items)
    return out


class ContractTap(AA.DecisionTap):
    """At every freeze: compute features() on the live objects too (completeness), check the frozen view shares no mutable
    object with the live F/T (isolation), then scramble the live objects and check features(view) did not move."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.checked, self.mismatch, self.shared, self.moved = 0, [], [], []

    def freeze(self, F, T):
        tok = super().freeze(F, T)
        if tok is None:
            return tok
        live = LS.features(F, T)
        fv, tv = tok["fv"], tok["tv"]
        before = LS.features(fv, tv)
        self.checked += 1
        if before != live:
            self.mismatch.append((live, before))
        view_ids = {**_graph_ids(fv), **_graph_ids(tv)}
        live_ids = {**_graph_ids(F, skip=_LIVE_SKIP), **_graph_ids(T)}
        both = set(view_ids) & set(live_ids)
        if both:
            self.shared.append(sorted(type(view_ids[i]).__name__ for i in both))
        undo = _scramble(F, T)
        try:
            after = LS.features(fv, tv)
            if after != before:
                self.moved.append({k: (before[k], after.get(k)) for k in before if before[k] != after.get(k)})
        finally:
            undo()
        return tok


def _scramble(F, T):
    """Change every live value features() could read, in place; returns undo()."""
    saved = []
    chrs = [T.s.player, *T.s.chars] + [x for x in (T.p, T.c) if x is not None]
    for c in {id(x): x for x in chrs}.values():
        saved.append((c, dict(c.__dict__)))
        c.hp, c.max_hp, c.x, c.z, c.y = (c.hp or 0) + 7, (c.max_hp or 0) + 11, c.x + 1.3, c.z - 0.7, c.y + 0.4
        c.sp, c.max_sp, c.anim, c.heading = (c.sp or 0) + 5, (c.max_sp or 0) + 9, 3001 if c.anim != 3001 else 3500, 1.0
        c.dist = (c.dist or 0) + 2.0
    care = getattr(F, "care", None)
    if care is not None:
        saved.append((care, dict(care.__dict__)))
        care.left = 0 if getattr(care, "left", 1) else 5
    fsaved = {k: getattr(F, k, None) for k in LS.F_ATTRS}
    tsaved = dict(T.__dict__)
    F.wait_far, F.hp_min, F.hp_start, F.low_hp, F.ptr = not F.wait_far, (F.hp_min or 0) - 50, (F.hp_start or 0) + 50, 0.9, -1
    F.weapon, F.style, F.foe = Boom(), Boom(), Boom()
    for k in ("h", "dy", "a", "age", "room"):
        T.__dict__[k] = Boom()

    def undo():
        for o, d in saved:
            o.__dict__.clear()
            o.__dict__.update(d)
        for k, v in fsaved.items():
            setattr(F, k, v)
        T.__dict__.clear()
        T.__dict__.update(tsaved)
    return undo


def test_freeze_contract() -> None:
    """features() on the frozen view = features() on the live objects at that moment, the view shares no mutable object
    with live F/T, and scrambling the live objects (values changed in place, attributes replaced by objects that raise)
    leaves features(view) unchanged."""
    taps = []
    for sc in sample(24):
        tap = ContractTap(MemorySink(), "c")
        G.run(sc, tap=tap)
        taps.append(tap)
    checked = sum(t.checked for t in taps)
    mism = [m for t in taps for m in t.mismatch]
    shared = [m for t in taps for m in t.shared]
    moved = [m for t in taps for m in t.moved]
    assert checked > 5000, checked
    assert not mism, mism[:2]
    assert not shared, shared[:3]
    assert not moved, moved[:3]
    assert not [t.last_error for t in taps if t.errors]
    print(f"ok  freeze contract on {checked} rule calls: view = live features, no shared mutable objects, scramble-proof")


def test_contract_catches_live_reads() -> None:
    """Negative control: a freeze that keeps the live snapshot (no copy) must be caught by the same checks."""
    real = LS.copy_snapshot
    LS.copy_snapshot = lambda s: (s, {id(s.player): s.player, **{id(c): c for c in s.chars}})
    try:
        taps = []
        for sc in sample(400):
            tap = ContractTap(MemorySink(), "neg")
            G.run(sc, tap=tap)
            taps.append(tap)
        assert any(t.shared for t in taps), "shared live snapshot not detected"
        assert any(t.moved for t in taps), "live re-read not detected by the scramble"
    finally:
        LS.copy_snapshot = real
    print("ok  a freeze that shares the live snapshot is caught (shared objects + scramble)")


# ── event kinds ──
def _fake_ft(anim=3001):
    w = World(player=(0.0, -49.4, 0.0), sp=90)
    w.add(2, 0x1002, 254000, (0.0, -49.4, 1.0), hp=75, anim=anim)
    w.add(3, 0x1003, 255000, (2.0, -49.4, 3.0), hp=75, anim=-1)
    s = w.snapshot(40.0)
    p, c = s.player, next(x for x in s.chars if x.ptr == 2)
    F = SimpleNamespace(weapon=weapons.BATTLE_AXE, foe=None, ptr=2, care=None, hp_start=p.hp, hp_min=p.hp, style=ST.GUARD,
                        wait_far=False, reflex=object(), arena=None, nm=None, low_hp=0.5, res=SimpleNamespace(hits=[]),
                        t0=100.0, orig_ptr=None, shadow=SimpleNamespace(gen=1))
    T = SimpleNamespace(s=s, p=p, c=c, h=M.horiz(p, c), dy=c.y - p.y, a=c.anim, age=0.3, room=False, now=0.0)
    return F, T


def _hit(kind="light", presses=1):
    return {"kind": kind, "presses": presses, "dmg": 30, "dead": False, "taken": 0, "others": 0}


def test_event_kinds() -> None:
    clock = {"ns": 0}
    sink = MemorySink()
    tap = AA.DecisionTap(sink, "k", clock=lambda: clock["ns"], wall=lambda: 1000.0 + clock["ns"] / 1e9)

    def invoke(rule, hits, freeze_ok=True):
        F, T = _fake_ft()
        tok = tap.freeze(F, T) if freeze_ok else None
        F.res.hits.extend(hits)
        clock["ns"] += 50_000_000
        return F, T, tap.decided(F, T, tok, rule, D.CONT)

    cases = [("attack", [_hit()], "attack_rule_invocation_snapshot", ["input_time_not_observed"]),
             ("stagger_punish", [_hit(presses=2)], "attack_rule_invocation_snapshot", ["input_time_not_observed", "chained_presses"]),
             ("attack", [_hit("heavy+light")], "audit_ambiguous_multi_attack", None),
             ("attack", [_hit(), _hit()], "audit_ambiguous_multi_attack", None),
             ("reflex", [_hit("backstep")], "audit_ambiguous_attack_outside_invocation", None)]
    for rule, hits, want, amb in cases:
        n0 = len(sink.recs)
        F, T, pay = invoke(rule, hits)
        r = sink.recs[n0]
        assert r["rec"] == want, (rule, hits, r["rec"])
        assert pay is not None and pay["event_id"] == r["event_id"] and pay["feat_sha256"] == r["feat_sha256"]
        if amb:
            assert r["ambiguity"] == amb, r["ambiguity"]
        assert r["first_attack_input_time_if_observed"] is None and r["input_time_ambiguous"] is True
        assert r["rule_enter_time"]["mono_ns"] < r["rule_exit_time"]["mono_ns"]
        for k in ("window", "samples", "post_samples"):
            assert k not in r                              # no outcome in the invocation row
        assert json.loads(r["feat_json"]) == pay["feat"]
        assert any(o["npc"] == 255000 for o in r["raw_context"]["others_within_8m"])
    n0 = len(sink.recs)
    invoke("backstab", [])
    invoke("block", [])                                    # not an attack rule, no hit: nothing
    invoke("attack", [_hit()], freeze_ok=False)
    kinds = [r["rec"] for r in sink.recs[n0:]]
    assert kinds == ["audit_no_attack", "audit_missing"], kinds
    assert sink.recs[n0]["possible_unrecorded_input"] is True
    # outcome: a later tick ≥ 1 s after the rule returned closes the window, same event_id, separate row
    F, T = _fake_ft(anim=3500)
    for dt in (0.3, 0.7, 1.1):
        clock["ns"] += int(dt * 1e9) - (0 if dt == 0.3 else int((dt - 0.4) * 1e9))
        tap.sensed(F, T)
    outs = [r for r in sink.recs if r["rec"] == "attack_outcome"]
    assert outs, [r["rec"] for r in sink.recs]
    snaps = {r["event_id"]: r for r in sink.recs if r["rec"] in CHK.DECISION_RECS}
    for o in outs:
        assert o["event_id"] in snaps and o["seq"] > snaps[o["event_id"]]["seq"]
        assert "feat_json" not in o and "feat" not in o and o["proxy"] == AA.PROXY
    tap.end(SimpleNamespace(t0=100.0), SimpleNamespace(result="killed", vs=254000))
    assert not tap._pending
    print(f"ok  event kinds: snapshot / multi / outside-invocation / no_attack / missing; outcomes separate and linked ({len(outs)})")


# ── writer ──
def test_writer_failures() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "ok.jsonl"
        w = AA.AuditWriter(p, {"rec": "run_header", "seq": 0})
        for i in range(1, 101):
            assert w.put({"rec": "x", "seq": i})
        s = w.close({"rec": "run_footer", "seq_last": 100})
        rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]
        assert [r["file_seq"] for r in rows] == list(range(102)) and rows[-1]["rec"] == "run_footer" and s["dropped"] == 0
        # stalled → drops counted, then an audit_missing line names them
        gate = threading.Event()
        real_open = open

        class Gated:
            def __init__(self, path):
                self.f = real_open(path, "a", encoding="utf-8")

            def write(self, s_):
                gate.wait(10.0)
                return self.f.write(s_)

            def flush(self):
                self.f.flush()

            def fileno(self):
                return self.f.fileno()

            def close(self):
                self.f.close()
        p2 = Path(d) / "drop.jsonl"
        gate.set()
        w = AA.AuditWriter(p2, {"rec": "run_header", "seq": 0}, queue_max=2, opener=Gated)
        gate.clear()
        for i in range(1, 41):
            w.put({"rec": "x", "seq": i})
        gate.set()
        s = w.close({"rec": "run_footer", "seq_last": 40})
        rows = [json.loads(l) for l in p2.read_text(encoding="utf-8").splitlines()]
        miss = [r for r in rows if r["rec"] == "audit_missing"]
        written = {r["seq"] for r in rows if r["rec"] == "x"}
        named = {q for r in miss for q in r["seqs"]}
        assert s["dropped"] > 0 and miss and written | named == set(range(1, 41)) and not written & named, (s, len(written), named)
        # write error → reopen fails → writer off, later records counted as lost, nothing raised
        class Bad:
            def write(self, s_):
                raise OSError("no space")

            def close(self):
                pass
        calls = {"n": 0}

        def bad_open(path):
            calls["n"] += 1
            if calls["n"] > 1:
                raise PermissionError("denied")
            return Bad()
        w = AA.AuditWriter(Path(d) / "bad.jsonl", {"rec": "run_header"}, opener=bad_open)
        for i in range(10):
            w.put({"rec": "x", "seq": i})
        time.sleep(0.1)
        s = w.close({"rec": "run_footer"})
        assert not w.alive and s["write_errors"] >= 1 and s["lost"] + s["dropped"] >= 1, s
        w = AA.AuditWriter(Path(d) / "x" / "missing_dir" / "a.jsonl", {"rec": "run_header"})   # can't even open
        assert w.put({"seq": 1}) is False and w.close({})["disabled_reason"] == "open_error"
    print(f"ok  writer: clean file, drops named in audit_missing, write/open errors turn it off and count — nothing raised")


# ── shared payload ──
def test_shared_payload_with_advisor() -> None:
    """Audit on + shadow on: the shadow's request for an attack carries the audit row's bytes (same sha, same feat); the
    audit keeps every attack even when the shadow's rate limit drops ticks."""
    sent, rows, rows_alone = [], [], []
    for i, sc in enumerate(sample(12)):
        tap = AA.DecisionTap(MemorySink(), f"s{i}")              # event ids unique across situations
        G.run(sc, advisor=LS.Advisor(sent.append, min_interval=0.0), tap=tap)
        rows += tap.sink.recs
        tap2 = AA.DecisionTap(MemorySink(), "s")
        G.run(sc, advisor=LS.Advisor(lambda r: None, min_interval=60.0), tap=tap2)
        rows_alone += tap2.sink.recs
    by_id = {r["event_id"]: r for r in rows if r.get("rec") in CHK.DECISION_RECS}
    linked = [q for q in sent if q.get("audit_event_id")]
    assert linked
    for q in linked:
        r = by_id[q["audit_event_id"]]
        assert q["feat_sha256"] == r["feat_sha256"] and q["feat"] == json.loads(r["feat_json"]) and q["allowed"] == r["allowed"]
    n = lambda rs: sum(1 for r in rs if r.get("rec") in CHK.DECISION_RECS)
    assert n(rows) == n(rows_alone), (n(rows), n(rows_alone))
    print(f"ok  {len(linked)} shadow requests share the audit payload byte for byte; rate limit doesn't thin the audit ({n(rows)} rows)")


# ── offline checker ──
def _audit_run(step=30):
    recs = [AA.run_header("r", "golden", {}, "axe", "guard")]
    tap = AA.DecisionTap(MemorySink(), "r")
    for sc in sample(step):
        G.run(sc, tap=tap)
    tap.close()
    for i, r in enumerate(tap.sink.recs, 1):
        r["file_seq"] = i
    recs[0]["file_seq"] = 0
    return recs + tap.sink.recs


def test_checker() -> None:
    recs = _audit_run()
    res = CHK.check(recs)
    assert res["explained"], res["problems"]
    assert res["invocations"] == sum(res["classes"].values()) > 0
    assert res["classes"].get("primary", 0) == 0                     # no pad correlation → nothing primary
    ev = [r for r in recs if r.get("rec") == "attack_rule_invocation_snapshot" and r["presses_reported"] == 1]
    onsets = [((r["rule_enter_time"]["wall"] + r["rule_exit_time"]["wall"]) / 2, "RB") for r in ev]   # one press inside each invocation
    res2 = CHK.check(recs, onsets)
    assert res2["classes"].get("primary", 0) > 0, res2["classes"]
    assert res2["classes"]["primary"] <= len(ev)
    gap = [r for r in recs if r.get("seq") != recs[5].get("seq")]                    # a record vanished without a trace
    assert not CHK.check(gap)["explained"]
    bad = json.loads(json.dumps(recs))
    next(r for r in bad if r.get("rec") in CHK.DECISION_RECS)["feature_schema_version"] = 999
    assert CHK.check(bad)["classes"].get("schema_mismatch") == 1
    print(f"ok  checker: {res['invocations']} invocations all classified, seqs explained; pad correlation → "
          f"{res2['classes'].get('primary')} primary; a silent gap and a schema change are caught")


def test_flag_default_off() -> None:
    tree = ast.parse((ROOT / "run.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "add_argument"
             and n.args and getattr(n.args[0], "value", None) == "--attack-audit"]
    assert len(calls) == 1
    kw = {k.arg: getattr(k.value, "value", None) for k in calls[0].keywords}
    assert kw.get("action") == "store_true" and "default" not in kw
    print("ok  --attack-audit is a store_true flag, off unless given")


def test_cost_observation() -> None:
    """Observation only (no limit asserted): freeze / payload / enqueue cost in this offline harness."""
    tap = AA.DecisionTap(MemorySink(), "p")
    for sc in sample(8):
        G.run(sc, tap=tap)
    ft = tap.footer()["prep_us"]
    print(f"obs freeze µs {ft['freeze']} · payload µs {ft['payload']} · enqueue µs {ft['enqueue']} (offline fakes, not a live measurement)")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
