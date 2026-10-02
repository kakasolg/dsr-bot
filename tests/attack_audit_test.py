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
    """Golden runs: every fight ends right after its attacks (the harness cancels after two ticks), so no outcome window is
    observed — with or without pad correlation nothing may be primary (P-35)."""
    recs = _audit_run()
    res = CHK.check(recs)
    assert res["explained"], res["problems"]
    assert res["invocations"] == sum(res["classes"].values()) > 0
    assert set(res["classes"]) == set(AA.CLASSES)
    ev = [r for r in recs if r.get("rec") in CHK.DECISION_RECS]
    onsets = [((r["rule_enter_time"]["wall"] + r["rule_exit_time"]["wall"]) / 2, "RB") for r in ev]
    res2 = CHK.check(recs, onsets)
    assert res2["classes"]["primary"] == 0, res2["classes"]
    assert res2["classes"]["outcome_unobserved_fight_end"] + res2["classes"]["outcome_overlap"] > 0
    assert res["classes"]["no_attack"] == res["records"].get("audit_no_attack", 0)
    gap = [r for r in recs if r.get("seq") != recs[5].get("seq")]                    # a record vanished without a trace
    assert not CHK.check(gap)["explained"]
    bad = json.loads(json.dumps(recs))
    next(r for r in bad if r.get("rec") in CHK.DECISION_RECS)["feature_schema_version"] = 999
    r3 = CHK.check(bad)
    assert r3["classes"]["missing"] >= 1 and r3["primary_exclusion_reasons"].get("schema_mismatch") == 1
    print(f"ok  checker: {res['invocations']} invocations → {res2['classes']}; a silent gap and a schema change are caught")


# ── P-35: conservative outcome windows ──
DEFAULT_OTHERS = ((3, 255000, (2.0, -49.4, 3.0), 75, -1),)     # an idle shield soldier 3.6 m away (alive → attack-capable candidate)


class _Case:
    """One fight (t0 100), fake clock: attack invocations and later ticks at chosen times after the rule returned.
    others: (ptr, npc, pos, hp, anim) of the non-targets in every tick. sees_projectiles: pretend a future device that also
    reads projectiles (header 'observes' and the bot side) — the only way a window can reach primary in a test (P-37)."""

    def __init__(self, sink=None, others=DEFAULT_OTHERS, sees_projectiles=False):
        self.clock = {"ns": 0}
        self.sink = sink or MemorySink()
        self.others = others
        self.observes = dict(AA.OBSERVES, projectiles=sees_projectiles)
        self.tap = AA.DecisionTap(self.sink, "case", clock=lambda: self.clock["ns"],
                                  wall=lambda: 1000.0 + self.clock["ns"] / 1e9)
        self.exit_ns = None
        self.target_npc = {}                                 # dt → npc for the target pointer from then on

    def attack(self, rule="attack", hits=None, ptr=2):
        F, T = _fake_ft()
        F.ptr = ptr
        tok = self.tap.freeze(F, T)
        F.res.hits.extend([_hit()] if hits is None else hits)
        self.clock["ns"] += 50_000_000
        self.tap.decided(F, T, tok, rule, D.CONT)
        self.exit_ns = self.clock["ns"]

    def tick(self, dt, target=True, ptr=2):
        """A tick dt s after the last attack returned (the clock never goes back)."""
        self.clock["ns"] = max(self.clock["ns"], self.exit_ns + int(dt * 1e9))
        w = World(player=(0.0, -49.4, 0.0), sp=90)
        if target:
            npc = next((n for t, n in sorted(self.target_npc.items(), reverse=True) if dt >= t), 254000)
            w.add(2, 0x1002, npc, (0.0, -49.4, 1.0), hp=40, anim=3500)
        for optr, onpc, pos, hp, anim in self.others:
            w.add(optr, 0x1000 + optr, onpc, pos, hp=hp, anim=anim)
        s = w.snapshot(40.0)
        F = SimpleNamespace(t0=100.0, ptr=ptr)
        saved, AA.OBSERVES = AA.OBSERVES, self.observes
        try:
            self.tap.sensed(F, SimpleNamespace(s=s))
        finally:
            AA.OBSERVES = saved

    def end(self, result="killed"):
        saved, AA.OBSERVES = AA.OBSERVES, self.observes
        try:
            self.tap.end(SimpleNamespace(t0=100.0), SimpleNamespace(result=result, vs=254000))
        finally:
            AA.OBSERVES = saved

    def records(self, sink_recs=None):
        recs = [dict(AA.run_header("case", "test", {}, "axe", "guard"), observes=self.observes)]
        saved, AA.OBSERVES = AA.OBSERVES, self.observes
        try:
            ft = self.tap.footer()
        finally:
            AA.OBSERVES = saved
        recs += (sink_recs if sink_recs is not None else self.sink.recs) + [ft]
        for i, r in enumerate(recs):
            r["file_seq"] = i
        return recs

    def check(self, pad=True):
        recs = self.records()
        ev = [r for r in recs if r.get("rec") in CHK.DECISION_RECS]
        onsets = [((r["rule_enter_time"]["wall"] + r["rule_exit_time"]["wall"]) / 2, "RB") for r in ev] if pad else None
        return CHK.check(recs, onsets), recs


def _full(c, upto=1.0, step=0.1, skip=(), lost_at=None, switch_at=None):
    t = step
    while t <= upto + 1e-9:
        if round(t, 2) not in skip:
            c.tick(round(t, 2), target=round(t, 2) != lost_at, ptr=3 if switch_at is not None and t >= switch_at else 2)
        t += step


def test_outcome_windows() -> None:
    """0/1/2 samples then fight end, a full window, a gap, target lost, a second attack inside the window, a backstab
    attempt inside it, a target switch, the run ending — each lands in exactly one class; fight_end is never complete."""
    cases = {}

    def run(name, build, pad=True, clean=False):
        c = _Case(others=(), sees_projectiles=True) if clean else _Case()
        build(c)
        res, recs = c.check(pad)
        first = res["rows"][0] if res["rows"][0]["rec"] in CHK.DECISION_RECS else next(r for r in res["rows"] if r["rec"] in CHK.DECISION_RECS)
        cases[name] = (first["class"], first["reasons"], res, c)
        return first["class"]

    assert run("0 samples + fight end", lambda c: (c.attack(), c.end())) == "outcome_unobserved_fight_end"
    assert run("1 sample + fight end", lambda c: (c.attack(), c.tick(0.1), c.end())) == "outcome_unobserved_fight_end"
    assert run("2 samples + fight end", lambda c: (c.attack(), c.tick(0.1), c.tick(0.2), c.end())) == "outcome_unobserved_fight_end"
    assert run("0.9 s covered + fight end", lambda c: (c.attack(), _full(c, 0.9), c.end())) == "outcome_unobserved_fight_end"
    # time-complete windows reach primary only with a clean context and a (hypothetical) projectile-reading device — P-37
    assert run("full window", lambda c: (c.attack(), _full(c)), clean=True) == "primary"
    assert run("full window, no pad", lambda c: (c.attack(), _full(c)), pad=False, clean=True) == "input_unconfirmed"
    assert run("full window then fight end", lambda c: (c.attack(), _full(c, 1.0), c.end()), clean=True) == "primary"
    assert run("full window, this device", lambda c: (c.attack(), _full(c))) == "outcome_attribution_unconfirmed"
    assert run("0.4 s gap", lambda c: (c.attack(), _full(c, skip=(0.3, 0.4, 0.5)))) == "outcome_incomplete"
    assert run("target lost", lambda c: (c.attack(), _full(c, lost_at=0.5))) == "outcome_incomplete"
    assert run("second attack at 0.3 s", lambda c: (c.attack(), c.tick(0.1), c.tick(0.2), c.attack(), _full(c)), clean=True) == "outcome_overlap"
    assert run("backstab try at 0.3 s", lambda c: (c.attack(), c.tick(0.1), c.attack(rule="backstab", hits=[]), _full(c))) == "outcome_overlap"
    assert run("target switch at 0.5 s", lambda c: (c.attack(), _full(c, switch_at=0.5))) == "outcome_overlap"
    assert run("run ends", lambda c: (c.attack(), c.tick(0.1), c.tick(0.2))) == "outcome_incomplete"
    assert run("chained presses, full window", lambda c: (c.attack(hits=[_hit(presses=2)]), _full(c))) == "ambiguous"
    assert "fight_end" in cases["0 samples + fight end"][1] and "no_samples" in cases["0 samples + fight end"][1]
    assert "run_end" in cases["run ends"][1]
    assert "overlap_target_switch" in cases["target switch at 0.5 s"][1]
    assert "overlap_next_attack_rule_invocation" in cases["backstab try at 0.3 s"][1]
    _, _, res, c = cases["second attack at 0.3 s"]
    assert res["classes"]["outcome_overlap"] == 1 and res["classes"]["primary"] == 1     # the second attack's own window is clean
    for name, (cls, reasons, res, c) in cases.items():
        assert res["explained"] and sum(res["classes"].values()) == res["invocations"], name
        ft = c.tap.footer()
        assert sum(ft["invocation_classes_bot_side"].values()) == res["invocations"], (name, ft["invocation_classes_bot_side"])
        out = [r for r in c.sink.recs if r["rec"] == "attack_outcome"]
        assert all(o["outcome_status"] != "complete" or o["window"]["coverage"]["covered"] for o in out), name
        bot = {r["event_id"]: AA.STATUS_CLASS[r["outcome_status"]] for r in out}
        for row in res["rows"]:                               # the bot's label never claims more than the checker
            if row["event_id"] in bot and row["class"] in ("primary", "input_unconfirmed"):
                assert bot[row["event_id"]] == "pending_input_check", (name, row)
    print(f"ok  {len(cases)} outcome-window cases: " + ", ".join(f"{k} → {v[0]}" for k, v in cases.items()))


def test_attribution() -> None:
    """P-37: a time-complete window is primary only if every sample shows the same target (handle + npc), every other
    character within 8 m is dead / asleep / not hostile, no ranged or unknown-type enemy is alive anywhere in the snapshot,
    nothing alive is outside the 8 m radius, and the device reads projectiles. Otherwise outcome_attribution_unconfirmed."""
    def far(ptr, npc, d, hp=75, anim=-1):
        return (ptr, npc, (0.0, -49.4, d), hp, anim)
    cases = {}

    def run(name, others=(), sees=True, build=None):
        c = _Case(others=others, sees_projectiles=sees)
        (build or (lambda c: (c.attack(), _full(c))))(c)
        res, recs = c.check()
        row = next(r for r in res["rows"] if r["rec"] in CHK.DECISION_RECS)
        bot = c.tap.inv_class[row["event_id"]]
        assert res["explained"] and sum(res["classes"].values()) == res["invocations"], name
        assert bot == (row["class"] if row["class"] != "primary" else "pending_input_check"), (name, bot, row)   # same verdict
        cases[name] = (row["class"], row["attribution_reasons"])
        return row["class"], row["attribution_reasons"]

    def changed(c):
        c.attack()
        c.target_npc[0.5] = 254002                                       # same pointer, another npc from 0.5 s
        _full(c)

    assert run("clean (hypothetical projectile device)") == ("primary", [])
    cls, why = run("complete, this device (projectiles not read)", sees=False)
    assert cls == "outcome_attribution_unconfirmed" and why == ["ranged_threat_unknown"], why
    cls, why = run("target npc changes mid-window", build=changed)
    assert cls == "outcome_attribution_unconfirmed" and "target_identity_changed" in why, why
    cls, why = run("live non-target within 8 m", others=DEFAULT_OTHERS)
    assert cls == "outcome_attribution_unconfirmed" and why == ["other_attack_capable_enemy_within_8m"], why
    assert run("dead + asleep non-targets within 8 m", others=((3, 254000, (2.0, -49.4, 3.0), 0, 2255),
                                                                (4, 254000, (-2.0, -49.4, 4.0), 75, 9001))) == ("primary", [])
    cls, why = run("observed crossbowman at 15 m", others=(far(5, 255002, 15.0),))
    assert cls == "outcome_attribution_unconfirmed" and {"ranged_threat_present", "enemy_outside_observation_radius"} <= set(why), why
    cls, why = run("unknown-type enemy at 12 m", others=(far(6, 999999, 12.0),))
    assert cls == "outcome_attribution_unconfirmed" and "ranged_threat_unknown" in why, why
    cls, why = run("sword hollow at 20 m", others=(far(7, 254000, 20.0),))
    assert cls == "outcome_attribution_unconfirmed" and why == ["enemy_outside_observation_radius"], why
    # the same clean window with its per-sample context stripped (old format) or broken never passes
    c = _Case(others=(), sees_projectiles=True)
    c.attack()
    _full(c)
    res, recs = c.check()
    assert res["classes"]["primary"] == 1
    for k, drop in (("old format (no target/others per sample)", ("target", "others_8m", "outside", "ranged")),
                    ("context error in one sample", ())):
        bad = json.loads(json.dumps(recs))
        for o in bad:
            if o.get("rec") == "attack_outcome":
                for i, smp in enumerate(o["window"]["samples"]):
                    for f in drop:
                        smp.pop(f, None)
                    if not drop and i == 3:
                        smp["ctx_error"] = "boom"
                o["attribution_reasons"] = []                   # the bot's own verdict is not trusted either
        ev = [r for r in bad if r.get("rec") in CHK.DECISION_RECS]
        r2 = CHK.check(bad, [((e["rule_enter_time"]["wall"] + e["rule_exit_time"]["wall"]) / 2, "RB") for e in ev])
        row = next(r for r in r2["rows"] if r["rec"] in CHK.DECISION_RECS)
        assert row["class"] == "outcome_attribution_unconfirmed", (k, row)
        cases[k] = (row["class"], row["attribution_reasons"])
    assert "target_identity_missing_per_sample" in cases["old format (no target/others per sample)"][1]
    assert "other_enemy_context_incomplete" in cases["context error in one sample"][1]
    print(f"ok  {len(cases)} attribution cases: " + "; ".join(f"{k} → {v[0]} {v[1]}" for k, v in cases.items()))


def test_o2_event9_not_primary() -> None:
    """The ramp re-validation run (schema 0.2): event :9 covered its 1.0 s window and its pad press was confirmed, but the
    samples have no per-sample target identity or 8 m context → outcome_attribution_unconfirmed, never primary (P-37)."""
    recs = CHK.load(ROOT / "data" / "samples" / "clear-ramp-audit-2026-10-02-o2.attack_audit.jsonl")
    ev = [r for r in recs if r.get("rec") in CHK.DECISION_RECS]
    onsets = [((r["rule_enter_time"]["wall"] + r["rule_exit_time"]["wall"]) / 2, "RB") for r in ev for _ in range(r["presses_reported"])]
    res = CHK.check(recs, onsets)
    assert res["explained"] and res["invocations"] == 6
    row = next(r for r in res["rows"] if r["event_id"].endswith(":9"))
    assert row["outcome_status"] == "complete" and row["input_correlation"] == "confirmed"
    assert row["class"] == "outcome_attribution_unconfirmed", row
    assert {"target_identity_missing_per_sample", "other_enemy_context_incomplete"} <= set(row["attribution_reasons"])
    assert res["classes"]["primary"] == 0 and res["classes"]["ambiguous"] == 4 and res["classes"]["outcome_unobserved_fight_end"] == 1
    assert res["primary_exclusion_reasons"]["fight_end"] == 5                 # each reason once per invocation (P-36)
    print(f"ok  o2 re-checked: {res['classes']}; :9 → {row['class']} {row['attribution_reasons']}")


def test_old_fight_end_not_complete() -> None:
    """The first ramp run (schema 0.1, before P-35): its 3 former primary rows must not be primary any more."""
    path = ROOT / "data" / "samples" / "clear-ramp-audit-2026-10-02-o1.attack_audit.jsonl"
    recs = CHK.load(path)
    ev = [r for r in recs if r.get("rec") in CHK.DECISION_RECS]
    onsets = [((r["rule_enter_time"]["wall"] + r["rule_exit_time"]["wall"]) / 2, "RB") for r in ev for _ in range(r["presses_reported"])]
    res = CHK.check(recs, onsets)
    assert res["explained"] and res["invocations"] == 7
    assert res["classes"]["primary"] == 0, res["classes"]
    assert res["classes"]["outcome_unobserved_fight_end"] == 3 and res["classes"]["ambiguous"] == 4, res["classes"]
    print(f"ok  first ramp audit re-checked: {res['classes']}")


def test_writer_failure_classes() -> None:
    """Records dropped by a full queue: the invocations they belong to are classed 'dropped' (row gone or its outcome gone),
    every seq is explained, and the footer still carries the counts."""
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
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "w.jsonl"
        gate.set()
        w = AA.AuditWriter(path, AA.run_header("case", "test", {}, "axe", "guard"), queue_max=1, opener=Gated)
        gate.clear()
        c = _Case(sink=w)
        for _ in range(6):
            c.attack()
            _full(c)
        gate.set()
        summary = c.tap.close()
        recs = CHK.load(path)
        res = CHK.check(recs)
        assert summary["writer"]["dropped"] > 0, summary
        assert res["explained"], (res["problems"], res["unexplained_seqs"])
        assert res["classes"]["dropped"] > 0, res["classes"]
        assert sum(res["classes"].values()) == res["invocations"] == 6, res["classes"]   # each invocation once
        assert next(r for r in recs if r["rec"] == "run_footer")["writer"]["dropped"] == summary["writer"]["dropped"]
    print(f"ok  writer drops: {summary['writer']['dropped']} records dropped → classes {res['classes']}, all seqs explained")


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
