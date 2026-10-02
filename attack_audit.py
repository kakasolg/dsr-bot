"""Attack audit — an observation device on the existing bot's attack rules. Not Laya inference, not an action hook:
nothing here is read back by the fight, and it never touches Moves, the pad or the rules (LAYA.md, ROADMAP P-34).

OUTCOME PROXY, NOT A HUMAN-VERIFIED TACTICAL LABEL, NOT A SAFETY VALIDATION. Rows are never human_verified, a train
target or a final test label. Data from these files is not merged with the old radar-reconstructed audit (P-34, failed gate).

  run.py --attack-audit  →  data/runs/<run>.attack_audit.jsonl            (off by default)
  duel(..., tap=DecisionTap(AuditWriter(path, header), run_id))

What a row is: the inputs laya_shadow.features() reads, frozen right before an attack rule was *invoked*
('attack_rule_invocation_snapshot'). It is not an exact button-press snapshot: the input path is unchanged, so the pad
press inside the rule is not observed here — rule_enter/exit times bound it, and experiments/attack_audit_check.py can
correlate it with the radar's pad stream.

Event lifecycle (one seq per record, issued in the fight loop; event_id ties an outcome to its invocation):
  run_header → [attack_rule_invocation_snapshot | audit_ambiguous_multi_attack | audit_ambiguous_attack_outside_invocation]
             → attack_outcome (same event_id, after the 1.0 s post window or the fight's end)
  audit_no_attack (an attack rule ran, no new hit recorded) · fight_end · audit_missing / audit_writer_error (writer side)
  → run_footer (counts; also returned to run.py and written to the run log, so drops survive a dead writer)

Outcome status (P-35, outcome_status()): complete only when the bot's own tick samples cover the whole 1.0 s after the rule
returned (no stretch > MAX_SAMPLE_GAP_S) with nothing else in it. A fight ending inside the window → unobserved_fight_end;
another attack-rule invocation / target switch / new fight inside it → overlap; gaps, target out of view, run end →
incomplete. The radar never fills a window. Classes per invocation: CLASSES (settled by experiments/attack_audit_check.py).
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections import Counter
from pathlib import Path

import laya_shadow as LS

SCHEMA = "dsr-attack-audit/0.2"     # 0.2: conservative outcome status (P-35)
PROXY = "outcome proxy, not human-verified tactical label, not a safety validation"
DISCLAIMER = {"kind": "outcome proxy, not human-verified tactical label", "not": "not a safety validation",
              "use": "never human_verified, a train target or a final test label",
              "what": "observation of the existing bot's attack rules — no Laya inference, no action wiring",
              "not_merged_with": "P-34 radar-reconstructed audit (failed equivalence gate)"}
ATTACK_TACTICS = ("attack", "backstab")
POST_S = 1.0
MAX_SAMPLE_GAP_S = 0.25         # an outcome window counts as observed only if no stretch of it (from the rule's return) is longer than this
# one class per attack invocation (experiments/attack_audit_check.py; the bot side can't see the pad, so it never says primary)
CLASSES = ("primary", "ambiguous", "no_attack", "missing", "dropped", "input_unconfirmed",
           "outcome_unobserved_fight_end", "outcome_overlap", "outcome_incomplete")
OTHERS_R = 8.0
ATTACKER_R = 3.5
MAX_SAMPLES = 60
_STOP = object()


def _motions(kind) -> int:
    """'heavy+light' (souls/duel._shield_combo) = two moves in one Hit."""
    return str(kind).count("+") + 1 if kind else 0


def outcome_status(samples: list, ended, overlaps: list, post_s: float = POST_S, max_gap: float = MAX_SAMPLE_GAP_S):
    """→ (status, reasons, coverage) of one outcome window — the bot and the checker both use this.
    complete only if the samples cover [0, post_s] after the rule returned with no stretch longer than max_gap, nothing else
    happened in it (next attack, target switch, new fight) and the target stayed in view. A fight that ended inside the
    window is NOT complete (the bot stops reading the fight then — P-35); the radar does not fill it in."""
    dts = [x["dt_s"] for x in samples]
    gaps = [b - a for a, b in zip([0.0] + dts[:-1], dts)]
    cov = {"n": len(dts), "first_dt_s": dts[0] if dts else None, "last_dt_s": dts[-1] if dts else None,
           "max_gap_s": round(max(gaps), 3) if gaps else None}
    covered = bool(dts) and dts[-1] >= post_s and max(gaps) <= max_gap
    cov["covered"] = covered
    reasons = [f"overlap_{o['kind']}" for o in overlaps]
    if not covered:
        if ended == "run_end":
            reasons.append("run_end")
        elif ended is not None:
            reasons.append("fight_end")
        reasons.append("no_samples" if not dts else "window_not_covered")
    if any(not x.get("target_present", True) for x in samples):
        reasons.append("target_lost")
    if overlaps:
        status = "overlap"
    elif "fight_end" in reasons:
        status = "unobserved_fight_end"
    elif reasons:
        status = "incomplete"
    else:
        status = "complete"
    return status, reasons, cov


STATUS_CLASS = {"complete": "pending_input_check", "unobserved_fight_end": "outcome_unobserved_fight_end",
                "overlap": "outcome_overlap", "incomplete": "outcome_incomplete"}


def _horiz(a, b) -> float:
    return ((a.x - b.x) ** 2 + (a.z - b.z) ** 2) ** 0.5


class AuditWriter:
    """One background thread writes JSON lines. put() never blocks or raises: a full queue drops the record and counts it
    (an audit_missing line follows when the writer gets to it); a write error reopens the file once, then the writer
    stops and every later record is counted as lost. The counts also come back from close()."""

    def __init__(self, path, header: dict, queue_max: int = 256, flush_s: float = 1.0, opener=None):
        self.path = Path(path)
        self.q: queue.Queue = queue.Queue(maxsize=max(1, queue_max))
        self.opener = opener or (lambda p: open(p, "a", encoding="utf-8"))
        self.flush_s = flush_s
        self.file_seq = 0
        self.written = 0
        self.dropped, self.dropped_seqs, self._reported = 0, [], 0
        self.lost, self.lost_seqs = 0, []
        self.dropped_recs, self.lost_recs = [], []          # [seq, rec, event_id] — so a dropped outcome names its invocation
        self.write_errors, self.last_error = 0, None
        self.alive, self.disabled_reason = True, None
        self.max_depth = 0
        self._f = None
        try:
            self._f = self.opener(self.path)
            self._write(header)
        except Exception as e:
            self._fail("open_error", e)
        self._th = threading.Thread(target=self._loop, name="attack-audit", daemon=True)
        self._th.start()

    # producer side (fight loop) — no I/O, no waiting
    def put(self, rec: dict) -> bool:
        try:
            if not self.alive:
                self._count(rec, lost=True)
                return False
            self.q.put_nowait(rec)
            d = self.q.qsize()
            if d > self.max_depth:
                self.max_depth = d
            return True
        except queue.Full:
            self._count(rec, lost=False)
            return False
        except Exception:
            return False

    def _count(self, rec, lost: bool) -> None:
        seq = rec.get("seq") if isinstance(rec, dict) else None
        what = [seq, rec.get("rec"), rec.get("event_id")] if isinstance(rec, dict) else [None, None, None]
        if lost:
            self.lost += 1
            if len(self.lost_seqs) < 5000:
                self.lost_seqs.append(seq)
                self.lost_recs.append(what)
        else:
            self.dropped += 1
            if len(self.dropped_seqs) < 5000:
                self.dropped_seqs.append(seq)
                self.dropped_recs.append(what)

    # writer thread
    def _fail(self, why: str, e) -> None:
        self.write_errors += 1
        self.last_error = f"{why}: {e!r}"[:200]
        self.alive, self.disabled_reason = False, why
        try:
            if self._f is not None:
                self._f.close()
        except Exception:
            pass
        self._f = None

    def _write(self, rec: dict) -> None:
        rec = dict(rec, file_seq=self.file_seq)
        line = json.dumps(rec, ensure_ascii=False, default=repr) + "\n"
        self._f.write(line)
        self.file_seq += 1
        self.written += 1

    def _write_safe(self, rec: dict) -> None:
        try:
            self._write(rec)
            return
        except Exception as e:
            self.write_errors += 1
            self.last_error = f"write: {e!r}"[:200]
        try:                                                 # one reopen, then give up
            try:
                self._f.close()
            except Exception:
                pass
            self._f = self.opener(self.path)
            self._write({"schema": SCHEMA, "rec": "audit_writer_error", "error": self.last_error, "reopened": True,
                         "t_mono_ns": time.monotonic_ns()})
            self._write(rec)
        except Exception as e:
            self._count(rec, lost=True)
            self._fail("write_error", e)

    def _loop(self) -> None:
        last_flush = time.monotonic()
        while True:
            try:
                rec = self.q.get(timeout=self.flush_s)
            except queue.Empty:
                rec = None
            if rec is _STOP:
                return
            if rec is not None:
                if not self.alive:
                    self._count(rec, lost=True)
                    continue
                if self.dropped > self._reported:
                    n = self.dropped - self._reported
                    self._write_safe({"schema": SCHEMA, "rec": "audit_missing", "reason": "queue_full", "count": n,
                                      "seqs": self.dropped_seqs[self._reported:self._reported + n],
                                      "recs": self.dropped_recs[self._reported:self._reported + n], "t_mono_ns": time.monotonic_ns()})
                    self._reported += n
                self._write_safe(rec)
            if self.alive and self._f is not None and time.monotonic() - last_flush >= self.flush_s:
                try:
                    self._f.flush()
                except Exception as e:
                    self._fail("flush_error", e)
                last_flush = time.monotonic()

    def close(self, footer: dict, timeout: float = 5.0) -> dict:
        """Run end (outside the fight loop): stop the thread, write the footer, fsync. → summary (also when the file is gone)."""
        deadline = time.monotonic() + timeout
        while self._th.is_alive() and time.monotonic() < deadline:
            try:
                self.q.put(_STOP, timeout=0.2)
                break
            except queue.Full:
                continue
        self._th.join(max(0.0, deadline - time.monotonic()))
        while True:                                          # whatever the thread never reached is lost (counted)
            try:
                r = self.q.get_nowait()
            except queue.Empty:
                break
            if r is not _STOP:
                self._count(r, lost=True)
        summary = {"written": self.written, "dropped": self.dropped, "dropped_seqs": self.dropped_seqs,
                   "lost": self.lost, "lost_seqs": self.lost_seqs, "write_errors": self.write_errors,
                   "last_error": self.last_error, "disabled_reason": self.disabled_reason, "max_queue_depth": self.max_depth,
                   "thread_stopped": not self._th.is_alive()}
        if self.alive and self._f is not None and not self._th.is_alive():
            try:
                if self.dropped > self._reported:
                    self._write({"schema": SCHEMA, "rec": "audit_missing", "reason": "queue_full",
                                 "count": self.dropped - self._reported, "seqs": self.dropped_seqs[self._reported:],
                                 "recs": self.dropped_recs[self._reported:]})
                    self._reported = self.dropped
                self._write(dict(footer, writer={k: v for k, v in summary.items() if k not in ("dropped_seqs", "lost_seqs")},
                                 dropped_seqs=self.dropped_seqs, lost_seqs=self.lost_seqs,
                                 dropped_recs=self.dropped_recs, lost_recs=self.lost_recs))
                self._f.flush()
                os.fsync(self._f.fileno())
            except Exception as e:
                summary["footer_error"] = repr(e)[:200]
        try:
            if self._f is not None:
                self._f.close()
        except Exception:
            pass
        summary["written"] = self.written
        return summary


class DecisionTap:
    """Called by souls/duel.duel() (tap=...): freeze() before every rule call, decided() after the rule that acted,
    sensed() on each later tick (outcome window), end() when the fight ends. Every method swallows its own errors and
    returns quickly; nothing it returns changes the fight (decided() hands the same payload to the Laya shadow, if on)."""

    def __init__(self, sink, run_id: str, clock=time.monotonic_ns, wall=time.time):
        self.sink, self.run_id, self.clock, self.wall = sink, run_id, clock, wall
        self.seq = 0
        self.errors, self.last_error = 0, None
        self.counts: Counter = Counter()
        self._snap = (None, None)
        self._pending: list = []
        self.inv_class: dict = {}                            # event_id → class as far as the bot can tell
        self.reasons: Counter = Counter()                    # why invocations can't be primary (all that apply)
        self.prep_ns = {"freeze": [], "payload": [], "enqueue": []}

    # ── helpers ──
    def _err(self, e) -> None:
        self.errors += 1
        self.last_error = repr(e)[:200]

    def _keep(self, k: str, ns: int) -> None:
        a = self.prep_ns[k]
        if len(a) < 50000:
            a.append(ns)

    def _ev(self, rec: str, event_id: str | None = None, **kw) -> dict:
        self.seq += 1
        self.counts[rec] += 1
        return {"schema": SCHEMA, "rec": rec, "run_id": self.run_id, "seq": self.seq,
                "event_id": event_id or f"{self.run_id}:{self.seq}", "t_mono_ns": self.clock(), "t_wall": self.wall(), **kw}

    def _put(self, rec: dict) -> None:
        t0 = time.perf_counter_ns()
        try:
            self.sink.put(rec)
        except Exception as e:
            self._err(e)
        self._keep("enqueue", time.perf_counter_ns() - t0)

    # ── fight loop hooks ──
    def freeze(self, F, T):
        """Right before a rule is called. Copies only — no features(), no I/O."""
        try:
            t0 = time.perf_counter_ns()
            if self._snap[0] is not T.s:                    # one snapshot copy per tick, shared by its rule calls
                self._snap = (T.s, LS.copy_snapshot(T.s))
            fv, tv = LS.freeze(F, T, self._snap[1])
            tok = {"fv": fv, "tv": tv, "hits_before": len(F.res.hits), "enter_ns": self.clock(), "enter_wall": self.wall(),
                   "ptr": F.ptr, "orig_ptr": getattr(F, "orig_ptr", None), "fight_t0": getattr(F, "t0", None),
                   "gen": getattr(getattr(F, "shadow", None), "gen", None)}
            ns = time.perf_counter_ns() - t0
            tok["freeze_ns"] = ns
            self._keep("freeze", ns)
            return tok
        except Exception as e:
            self._err(e)
            return None

    def decided(self, F, T, tok, rule: str, out):
        """After the rule that acted returned. → the shared payload when it attacked (for the shadow), else None."""
        try:
            exit_ns, exit_wall = self.clock(), self.wall()
            tactic = LS.RULE_TACTIC.get(rule)
            if tok is None:
                hits = None
            else:
                hits = list(F.res.hits[tok["hits_before"]:])
            if hits is None:                                 # freeze failed: can't say what was seen
                if tactic in ATTACK_TACTICS:
                    ev = self._ev("audit_missing", reason="freeze_error", rule=rule, error=self.last_error)
                    self._classify(ev["event_id"], "missing", ["freeze_error"])
                    self._put(ev)
                return None
            times = {"rule_enter_time": {"mono_ns": tok["enter_ns"], "wall": tok["enter_wall"]},
                     "rule_exit_time": {"mono_ns": exit_ns, "wall": exit_wall}}
            if not hits:
                if tactic in ATTACK_TACTICS:
                    ev = self._ev("audit_no_attack", rule=rule, rule_tactic=tactic, hit_delta=0, **times,
                                       out=type(out).__name__ if out is not None else None,
                                       possible_unrecorded_input=rule in ("backstab", "backstab_swing"),
                                       note=("backstab presses R1 through pad.attack without a Hit record — an input may have happened"
                                             if rule in ("backstab", "backstab_swing") else "attack rule acted without a new hit"))
                    self._overlap(tok["fight_t0"], "next_attack_rule_invocation", ev["event_id"])
                    self._classify(ev["event_id"], "no_attack", ["no_attack"])
                    self._put(ev)
                return None
            t0 = time.perf_counter_ns()
            pay = LS.decision_payload(tok["fv"], tok["tv"])
            pay_ns = time.perf_counter_ns() - t0
            self._keep("payload", pay_ns)
            kinds = [h.get("kind") for h in hits]
            presses = sum(int(h.get("presses") or 0) for h in hits)
            motions = sum(_motions(k) for k in kinds)
            if rule == "reflex":
                rec_kind = "audit_ambiguous_attack_outside_invocation"   # the reflex thread attacked before this rule ran
            elif len(hits) > 1 or motions > 1:
                rec_kind = "audit_ambiguous_multi_attack"
            else:
                rec_kind = "attack_rule_invocation_snapshot"
            ambiguity = ["input_time_not_observed"]
            if presses > 1:
                ambiguity.append("chained_presses")
            if rec_kind != "attack_rule_invocation_snapshot":
                ambiguity.append(rec_kind.removeprefix("audit_ambiguous_"))
            fv, tv = tok["fv"], tok["tv"]
            gen = tok["gen"]
            s, p, c = tv.s, tv.p, tv.c

            def handle(x):
                return f"{x.ptr:#x}#{gen}"

            others = [{"handle": handle(x), "npc": x.npc_param, "team": x.team, "d": round(_horiz(p, x), 2),
                       "dy": round(x.y - p.y, 2), "anim": x.anim, "hp": x.hp, "asleep": 9000 <= (x.anim or 0) < 9100}
                      for x in s.chars if x.ptr != c.ptr and _horiz(p, x) < OTHERS_R]
            f = pay["feat"]
            rec = self._ev(
                rec_kind, rule=rule, rule_tactic=tactic, policy_tactic=LS.policy_tactic(rule, f), **times,
                first_attack_input_time_if_observed=None, input_time_source="not_observed_in_bot (input path unchanged)",
                input_time_ambiguous=True, ambiguity=ambiguity,
                hit_delta=len(hits), attack_count_if_observed=motions, presses_reported=presses,
                attack_count_source="souls.moves.Hit kind/presses (Moves' own count; pad not observed)",
                hits=[{k: h.get(k) for k in ("kind", "presses", "dmg", "dead", "taken", "others")} for h in hits],
                fight={"t0": tok["fight_t0"], "gen": gen},
                snapshot={"t": getattr(s, "t", None), "age_at_rule_enter_s": round(tok["enter_wall"] - s.t, 4)
                          if isinstance(getattr(s, "t", None), (int, float)) else None,
                          "source": "T.s — the snapshot the bot read this tick (copied before the rule)"},
                target={"handle": handle(c), "npc": c.npc_param, "distance_m": f.get("distance_m"),
                        "height_diff_m": f.get("height_diff_m"),
                        "switched_from": None if tok["orig_ptr"] is None else f"{tok['orig_ptr']:#x}#{gen}"},
                **{k: pay[k] for k in ("feature_schema_version", "features_src_sha", "code_path", "feature_keys_sha",
                                       "feat_json", "feat_sha256", "allowed", "why_not")},
                nulls=sorted(k for k, v in f.items() if v is None),
                provenance={"target_kind": "bot table souls/foes.py (the bot's belief, uncorrected)",
                            "estus_wanted": "bot Care.left", "_room": "bot NavMesh check (T.room)",
                            "fighting_style": "bot setting", "let_it_come": "bot F.wait_far"},
                obs_status={"target_in_snapshot": any(x is c for x in s.chars), "reflex_on": fv.reflex is not None},
                raw_context={"others_within_8m": others,
                             "player": {k: getattr(p, k, None) for k in ("x", "y", "z", "hp", "max_hp", "sp", "max_sp", "anim", "heading")},
                             "target_raw": {k: getattr(c, k, None) for k in ("x", "y", "z", "hp", "max_hp", "anim", "heading")}},
                prep_us={"freeze": round(tok["freeze_ns"] / 1000, 1), "payload": round(pay_ns / 1000, 1)})
            pay["event_id"] = rec["event_id"]
            self._overlap(tok["fight_t0"], "next_decision", rec["event_id"])
            self._put(rec)
            amb = [a for a in ambiguity if a != "input_time_not_observed"]
            if amb:
                self._classify(rec["event_id"], "ambiguous", amb)
            self._pending.append({"event_id": rec["event_id"], "ptr": c.ptr, "gen": gen, "fight_t0": tok["fight_t0"],
                                  "exit_ns": exit_ns, "hits": rec["hits"], "samples": [], "overlaps": []})
            return pay
        except Exception as e:
            self._err(e)
            try:
                if tok is not None and len(F.res.hits) > tok["hits_before"]:
                    ev = self._ev("audit_missing", reason="build_error", rule=rule, error=self.last_error)
                    self._classify(ev["event_id"], "missing", ["build_error"])
                    self._put(ev)
            except Exception:
                pass
            return None

    def sensed(self, F, T) -> None:
        """A later tick of the same fight: one post-window sample per pending outcome (reads T.s only)."""
        if not self._pending:
            return
        try:
            from souls import moves as M
            now = self.clock()
            s, p = T.s, T.s.player
            for pe in list(self._pending):
                if pe["fight_t0"] != getattr(F, "t0", None):    # a new fight without the old one's end (shouldn't happen)
                    pe["overlaps"].append({"kind": "new_fight", "event_id": None})
                    self._finish(pe, ended=None)
                    continue
                if F.ptr != pe["ptr"] and not any(o["kind"] == "target_switch" for o in pe["overlaps"]):
                    pe["overlaps"].append({"kind": "target_switch", "event_id": None})
                dt = (now - pe["exit_ns"]) / 1e9
                c = next((x for x in s.chars if x.ptr == pe["ptr"]), None)
                att = [{"handle": f"{x.ptr:#x}#{pe['gen']}", "npc": x.npc_param, "anim": x.anim, "d": round(_horiz(p, x), 2),
                        "is_target": x.ptr == pe["ptr"]}
                       for x in s.hostile(ATTACKER_R + 2.0) if (x.anim if x.anim is not None else -1) in M.ATTACK
                       and _horiz(p, x) < ATTACKER_R]
                if len(pe["samples"]) < MAX_SAMPLES:
                    pe["samples"].append({"dt_s": round(dt, 3), "snap_t": s.t, "hp": p.hp, "target_present": c is not None,
                                          "target_anim": c.anim if c else None, "target_hp": c.hp if c else None,
                                          "attackers_3_5m": att})
                if dt >= POST_S:
                    self._finish(pe, ended=None)
        except Exception as e:
            self._err(e)

    def _classify(self, event_id: str, cls: str, reasons: list) -> None:
        if event_id not in self.inv_class:                   # first class wins (ambiguous before any outcome class)
            self.inv_class[event_id] = cls
        self.reasons.update(reasons)

    def _overlap(self, fight_t0, kind: str, event_id: str) -> None:
        """Another attack-rule invocation in the same fight: every still-open outcome window is mixed with it."""
        for pe in self._pending:
            if pe["fight_t0"] == fight_t0:
                pe["overlaps"].append({"kind": kind, "event_id": event_id})

    def _finish(self, pe: dict, ended) -> None:
        self._pending.remove(pe)
        smp = pe["samples"]
        status, reasons, cov = outcome_status(smp, ended, pe["overlaps"])
        self._classify(pe["event_id"], STATUS_CLASS[status], reasons)
        self._put(self._ev("attack_outcome", event_id=pe["event_id"], proxy=PROXY, outcome_status=status, outcome_reasons=reasons,
                           hit=pe["hits"], overlaps=pe["overlaps"],
                           window={"post_s": POST_S, "max_gap_s": MAX_SAMPLE_GAP_S, "samples": smp, "coverage": cov,
                                   "complete": status == "complete", "duel_ended_in_window": ended not in (None, "run_end"),
                                   "fight_result": ended},
                           status={"target_lost": any(not x["target_present"] for x in smp),
                                   "multiple_attackers": any(any(not a["is_target"] for a in x["attackers_3_5m"]) for x in smp)}))

    def end(self, F, res) -> None:
        try:
            t0 = getattr(F, "t0", None)
            result = getattr(res, "result", None)
            for pe in [p for p in self._pending if p["fight_t0"] == t0]:
                self._finish(pe, ended=result)
            self._put(self._ev("fight_end", fight={"t0": t0}, result=result, npc=getattr(res, "vs", None)))
        except Exception as e:
            self._err(e)

    def footer(self) -> dict:
        def pct(a, q):
            return round(sorted(a)[int(q * (len(a) - 1))] / 1000, 1) if a else None
        for pe in list(self._pending):
            self._finish(pe, ended="run_end")
        return {"schema": SCHEMA, "rec": "run_footer", "run_id": self.run_id, "seq_last": self.seq, "counts": dict(self.counts),
                "tap_errors": self.errors, "tap_last_error": self.last_error, "t_mono_ns": self.clock(),
                "prep_us": {k: {"n": len(v), "p50": pct(v, 0.5), "p95": pct(v, 0.95), "max": pct(v, 1.0)} for k, v in self.prep_ns.items()},
                "invocation_classes_bot_side": dict(Counter(self.inv_class.values())),
                "primary_exclusion_reasons": dict(self.reasons),
                "note": ("prep times are observations of this run, not validated limits; pending_input_check / primary / "
                         "input_unconfirmed / dropped are settled offline by experiments/attack_audit_check.py")}

    def close(self) -> dict:
        """Run end: pending outcomes out, footer, writer stopped. → summary for the run log."""
        try:
            ft = self.footer()
            return {"tap": {k: ft[k] for k in ("seq_last", "counts", "tap_errors", "tap_last_error", "prep_us",
                                               "invocation_classes_bot_side", "primary_exclusion_reasons")},
                    "writer": self.sink.close(ft)}
        except Exception as e:
            return {"error": repr(e)[:200]}


def run_header(run_id: str, mission: str, args: dict, weapon: str | None, style: str | None) -> dict:
    """Written once at start (outside the fight loop): code identity, settings, schema ids, the disclaimer."""
    import subprocess
    root = Path(__file__).resolve().parent

    def git(*a):
        try:
            return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return None
    dirty = git("status", "--porcelain", "--untracked-files=no")
    return {"schema": SCHEMA, "rec": "run_header", "run_id": run_id, "seq": 0, "event_id": f"{run_id}:0",
            "t_mono_ns": time.monotonic_ns(), "t_wall": time.time(), "disclaimer": DISCLAIMER,
            "code": {"commit": git("rev-parse", "HEAD"), "dirty": bool(dirty) if dirty is not None else None,
                     "dirty_files": dirty.splitlines()[:50] if dirty else []},
            **LS.schema_ids(), "mission": mission, "args": args, "weapon": weapon, "style": style,
            "clock": {"mono": "time.monotonic_ns", "wall": "time.time", "snapshot": "Snapshot.t (time.time at the bot's read)"},
            "record_kind": "attack_rule_invocation_snapshot — inputs frozen before the attack rule was invoked; not the exact button press",
            "laya_inference": False, "bot_behavior_changed": False}
