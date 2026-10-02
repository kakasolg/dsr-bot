"""Offline check of one attack-audit file (attack_audit.py). No game, no model.

OUTCOME PROXY, NOT A HUMAN-VERIFIED TACTICAL LABEL, NOT A SAFETY VALIDATION. Never merged with the P-34 radar-reconstructed
audit data.

  python experiments/attack_audit_check.py data/runs/<run>.attack_audit.jsonl [--radar data/radar/<rec>.jsonl]
         [--log data/runs/<run>.log] [--allow-chained] [--out result.json]

Every issued seq must be explained (written / dropped / lost), and every attack invocation gets exactly one class:
  schema_mismatch · ambiguous · dropped_outcome · missing_outcome · overlaps_loss · outcome_incomplete · input_unconfirmed · primary
primary = complete, schema/hash/source match, pad input correlated (radar), no ambiguity, no loss in its span.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

DECISION_RECS = ("attack_rule_invocation_snapshot", "audit_ambiguous_multi_attack", "audit_ambiguous_attack_outside_invocation")
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
    for r in recs:
        if r.get("rec") == "audit_missing" and r.get("reason") == "queue_full":
            dropped |= set(r.get("seqs") or [])
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
    ids = {k: (header or {}).get(k) for k in ("feature_schema_version", "features_src_sha", "code_path")}
    outcomes = {r["event_id"]: r for r in recs if r.get("rec") == "attack_outcome"}
    classes, rows = Counter(), []
    for ev in [r for r in recs if r.get("rec") in DECISION_RECS]:
        cor = correlate(ev, onsets)
        oc = outcomes.get(ev["event_id"])
        span_end = oc["seq"] if oc else last
        sha_ok = hashlib.sha256(ev.get("feat_json", "").encode("utf-8")).hexdigest() == ev.get("feat_sha256")
        amb = [a for a in ev.get("ambiguity", []) if a != "input_time_not_observed" and not (allow_chained and a == "chained_presses")]
        if any(ev.get(k) != v for k, v in ids.items()) or not sha_ok:
            c = "schema_mismatch"
        elif amb:
            c = "ambiguous"
        elif oc is None:
            c = "dropped_outcome" if any(ev["seq"] < q <= last for q in dropped | lost) else "missing_outcome"
        elif any(ev["seq"] < q < span_end for q in loss):
            c = "overlaps_loss"
        elif not (oc["window"]["complete"] or oc["window"]["duel_ended_in_window"]):
            c = "outcome_incomplete"
        elif cor["input_correlation"] != "confirmed":
            c = "input_unconfirmed"
        else:
            c = "primary"
        classes[c] += 1
        rows.append({"event_id": ev["event_id"], "rec": ev["rec"], "rule": ev.get("rule"), "class": c, "ambiguity": amb, **cor})
    n_ev = sum(classes.values())
    hits_in_audit = sum(len(r.get("hits") or []) for r in recs if r.get("rec") in DECISION_RECS)
    return {"disclaimer": "outcome proxy, not human-verified tactical label, not a safety validation",
            "problems": problems, "seq_accounting": dict(acct), "unexplained_seqs": unexplained[:50],
            "records": dict(Counter(r.get("rec") for r in recs)),
            "invocations": n_ev, "classes": dict(classes),
            "explained": not problems and not unexplained and n_ev == sum(classes.values()),
            "no_attack": sum(1 for r in recs if r.get("rec") == "audit_no_attack"),
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
