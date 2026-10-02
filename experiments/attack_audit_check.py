"""Offline check of one attack-audit file (attack_audit.py). No game, no model.

OUTCOME PROXY, NOT A HUMAN-VERIFIED TACTICAL LABEL, NOT A SAFETY VALIDATION. Never merged with the P-34 radar-reconstructed
audit data. The radar is used only for the pad-input correlation — it never fills an outcome window (P-35).

  python experiments/attack_audit_check.py data/runs/<run>.attack_audit.jsonl [--radar data/radar/<rec>.jsonl]
         [--log data/runs/<run>.log] [--allow-chained] [--out result.json]

Every issued seq must be explained (written / dropped / lost), and every attack invocation gets exactly one class
(attack_audit.CLASSES), first match in this order:
  dropped · missing · no_attack · ambiguous · outcome_overlap · outcome_unobserved_fight_end · outcome_incomplete ·
  input_unconfirmed · primary
The outcome status is recomputed here from the raw samples (attack_audit.outcome_status) and from the other invocations of
the same fight — the bot's own label is not trusted; the stricter of the two wins. Every reason that applies is also
listed (reasons), so the exclusion table counts all of them, not only the first.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import attack_audit as AA  # noqa: E402

DECISION_RECS = ("attack_rule_invocation_snapshot", "audit_ambiguous_multi_attack", "audit_ambiguous_attack_outside_invocation")
INVOCATION_RECS = DECISION_RECS + ("audit_no_attack",)
STRICT = ["complete", "incomplete", "unobserved_fight_end", "overlap"]          # stricter → later
HEAD = re.compile(r'^\{"rt": ([0-9.]+), "type": "(\w+)"')
RB, RT_MIN = 0x0200, 100


def load(path) -> list:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"rec": "_unreadable_line"})
    return out


def pad_onsets(radar_path) -> list:
    """(wall time, 'RB'|'RT') press onsets from the radar's pad stream (radar_pad.py polls XInput), any slot."""
    e0, onsets, prev = None, [], {}
    with Path(radar_path).open(encoding="utf-8", errors="replace") as f:
        for line in f:
            m = HEAD.match(line)
            if not m:
                continue
            rt, typ = float(m.group(1)), m.group(2)
            if typ == "snap" and e0 is None:
                t = json.loads(line).get("t") or 0
                if t > 1e9:
                    e0 = t - rt
            elif typ == "pad":
                d = json.loads(line)
                i, b, r2 = d.get("i"), d.get("btn") or 0, (d.get("rtr") or 0) > RT_MIN
                pb, pr = prev.get(i, (0, False))
                if b & RB and not pb & RB:
                    onsets.append((rt, "RB"))
                if r2 and not pr:
                    onsets.append((rt, "RT"))
                prev[i] = (b, r2)
    return [(rt + e0, k) for rt, k in onsets] if e0 is not None else []


def correlate(ev: dict, onsets: list | None) -> dict:
    if onsets is None:
        return {"input_correlation": "not_checked", "first_attack_input_time_if_observed": None, "input_time_source": None}
    t0, t1 = ev["rule_enter_time"]["wall"] - 0.02, ev["rule_exit_time"]["wall"]
    hit = [(t, k) for t, k in onsets if t0 <= t <= t1]
    n = ev.get("presses_reported") or 0
    status = "confirmed" if hit and len(hit) == n else ("not_found" if not hit else "count_mismatch")
    return {"input_correlation": status, "pad_onsets_in_invocation": len(hit),
            "first_attack_input_time_if_observed": hit[0][0] if hit else None,
            "first_input_after_rule_enter_s": round(hit[0][0] - ev["rule_enter_time"]["wall"], 4) if hit else None,
            "input_time_source": "radar pad stream (XInput poll, another process — wall clocks of one machine)"}


def check(recs: list, onsets: list | None = None, allow_chained: bool = False, log_attack_lines: int | None = None) -> dict:
    header = next((r for r in recs if r.get("rec") == "run_header"), None)
    footer = next((r for r in recs if r.get("rec") == "run_footer"), None)
    problems = []
    if header is None:
        problems.append("no run_header")
    if footer is None:
        problems.append("no run_footer (crash or writer stopped) — seq accounting incomplete")
    if header and "not a safety validation" not in json.dumps(header.get("disclaimer"), ensure_ascii=False):
        problems.append("header disclaimer missing")
    fseq = [r.get("file_seq") for r in recs if "file_seq" in r]
    if fseq != list(range(len(fseq))):
        problems.append("file_seq not 0..n-1 in order")
    # seq accounting: every issued seq is written, dropped or lost
    written = {r["seq"] for r in recs if isinstance(r.get("seq"), int) and r.get("rec") not in ("run_header", "run_footer")}
    dropped = set((footer or {}).get("dropped_seqs") or [])
    gone_recs = [tuple(x) for x in (footer or {}).get("dropped_recs") or []] + [tuple(x) for x in (footer or {}).get("lost_recs") or []]
    for r in recs:
        if r.get("rec") == "audit_missing" and r.get("reason") == "queue_full":
            dropped |= set(r.get("seqs") or [])
            gone_recs += [tuple(x) for x in r.get("recs") or []]
    gone_recs = list({x[0]: x for x in gone_recs}.values())     # footer and audit_missing name the same drops — once per seq
    lost = set((footer or {}).get("lost_seqs") or [])
    last = (footer or {}).get("seq_last") or max(written | dropped | lost | {0})
    acct = Counter()
    unexplained = []
    for q in range(1, last + 1):
        k = "written" if q in written else "dropped" if q in dropped else "lost" if q in lost else "unexplained"
        acct[k] += 1
        if k == "unexplained":
            unexplained.append(q)
    loss = sorted(dropped | lost | set(unexplained))
    gone_outcome = {e for _, rec, e in gone_recs if rec == "attack_outcome"}
    ids = {k: (header or {}).get(k) for k in ("feature_schema_version", "features_src_sha", "code_path")}
    outcomes = {r["event_id"]: r for r in recs if r.get("rec") == "attack_outcome"}
    invocations = [r for r in recs if r.get("rec") in INVOCATION_RECS]
    by_fight: dict = {}
    for r in invocations:
        by_fight.setdefault((r.get("fight") or {}).get("t0"), []).append(r)
    classes, rows, why_all = Counter(), [], Counter()

    def put(ev_id, rec, rule, cls, reasons, extra=None):
        classes[cls] += 1
        why_all.update(reasons)
        rows.append({"event_id": ev_id, "rec": rec, "rule": rule, "class": cls, "reasons": reasons, **(extra or {})})

    for _, rec, e in gone_recs:                              # the invocation row itself never reached the file
        if rec in INVOCATION_RECS:
            put(e, rec, None, "dropped", ["invocation_row_dropped"])
    for r in recs:
        if r.get("rec") == "audit_missing" and r.get("reason") in ("freeze_error", "build_error"):
            put(r["event_id"], r["rec"], r.get("rule"), "missing", [r["reason"]])
    for ev in invocations:
        if ev["rec"] == "audit_no_attack":
            put(ev["event_id"], ev["rec"], ev.get("rule"), "no_attack",
                ["no_attack"] + (["possible_unrecorded_input"] if ev.get("possible_unrecorded_input") else []))
            continue
        cor = correlate(ev, onsets)
        oc = outcomes.get(ev["event_id"])
        reasons = [a for a in ev.get("ambiguity", []) if a != "input_time_not_observed" and not (allow_chained and a == "chained_presses")]
        amb = list(reasons)
        sha_ok = hashlib.sha256(ev.get("feat_json", "").encode("utf-8")).hexdigest() == ev.get("feat_sha256")
        schema_bad = any(ev.get(k) != v for k, v in ids.items()) or not sha_ok
        if schema_bad:
            reasons.append("schema_mismatch")
        status = None
        if oc is not None:
            exit_w = ev["rule_exit_time"]["wall"]
            overlaps = list(oc.get("overlaps") or [])
            for other in by_fight.get((ev.get("fight") or {}).get("t0"), []):
                t = other["rule_enter_time"]["wall"]
                if other is not ev and exit_w <= t < exit_w + oc["window"].get("post_s", AA.POST_S) \
                        and not any(o.get("event_id") == other["event_id"] for o in overlaps):
                    overlaps.append({"kind": "next_decision" if other["rec"] != "audit_no_attack" else "next_attack_rule_invocation",
                                     "event_id": other["event_id"]})
            w = oc["window"]
            ended = w.get("fight_result") if w.get("fight_result") is not None else ("ended" if w.get("duel_ended_in_window") else None)
            st, oreasons, cov = AA.outcome_status(w.get("samples") or [], ended, overlaps)
            bot = oc.get("outcome_status") or "complete"
            status = max(st, bot if bot in STRICT else "incomplete", key=STRICT.index)
            reasons += [x for x in oreasons + list(oc.get("outcome_reasons") or []) if x not in reasons]
        else:
            reasons.append("outcome_dropped" if ev["event_id"] in gone_outcome else "outcome_missing")
        span_end = oc["seq"] if oc else last
        if any(ev["seq"] < q < span_end for q in loss):
            reasons.append("overlaps_loss")
        if cor["input_correlation"] != "confirmed":
            reasons.append(f"input_{cor['input_correlation']}")
        if ev["event_id"] in gone_outcome:
            cls = "dropped"
        elif schema_bad or oc is None or "overlaps_loss" in reasons:
            cls = "missing"
        elif amb:
            cls = "ambiguous"
        elif status == "overlap":
            cls = "outcome_overlap"
        elif status == "unobserved_fight_end":
            cls = "outcome_unobserved_fight_end"
        elif status == "incomplete":
            cls = "outcome_incomplete"
        elif cor["input_correlation"] != "confirmed":
            cls = "input_unconfirmed"
        else:
            cls = "primary"
        put(ev["event_id"], ev["rec"], ev.get("rule"), cls, reasons, {"outcome_status": status, **cor})
    hits_in_audit = sum(len(r.get("hits") or []) for r in recs if r.get("rec") in DECISION_RECS)
    n_inv = len(rows)
    return {"disclaimer": "outcome proxy, not human-verified tactical label, not a safety validation",
            "schema": (header or {}).get("schema"), "problems": problems, "seq_accounting": dict(acct),
            "unexplained_seqs": unexplained[:50], "records": dict(Counter(r.get("rec") for r in recs)),
            "invocations": n_inv, "classes": {c: classes.get(c, 0) for c in AA.CLASSES},
            "explained": not problems and not unexplained and set(classes) <= set(AA.CLASSES) and sum(classes.values()) == n_inv,
            "primary_exclusion_reasons": dict(why_all),
            "bot_side": {k: (footer or {}).get(k) for k in ("invocation_classes_bot_side", "primary_exclusion_reasons")},
            "hits_in_audit": hits_in_audit, "log_attack_lines": log_attack_lines,
            "prep_us": (footer or {}).get("prep_us"), "writer": (footer or {}).get("writer"),
            "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audit")
    ap.add_argument("--radar")
    ap.add_argument("--log")
    ap.add_argument("--allow-chained", action="store_true", help="light×2 같은 연속 누름을 모호함으로 보지 않음 (기본: 모호함)")
    ap.add_argument("--out")
    a = ap.parse_args()
    n_log = None
    if a.log:
        n_log = sum(1 for l in Path(a.log).read_text(encoding="utf-8", errors="replace").splitlines() if "내 피해" in l and "→" in l)
    res = check(load(a.audit), pad_onsets(a.radar) if a.radar else None, a.allow_chained, n_log)
    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
