"""Counter trace report — rule_after_swing's windows, evaluations and strikes from a run's .ctl.jsonl, each strike linked to
the pad records sent during it. No game, read-only (souls/counter_trace.py writes the records with run.py --ctl).

  python counter_report.py data/runs/<run>.ctl.jsonl [--hits data/runs/<run>.hits.jsonl] [--json OUT]

Decision key: (run_id, fight_start seq, dec). `dec` restarts at 1 in every fight (souls/counter_trace.py keeps it per fight),
so it is never used alone; the raw records are not renumbered. An intent is paired only with the outcome of the same key,
inside the same fight (fight_start … its fight_end / the next fight_start). No outcome, two outcomes, two intents with one key,
or an intent outside any fight → status unknown with the reason; nothing is paired with "the next nearby" record instead.

Pad link (by ctl seq, the one counter both sides share): the pad / pad.drop records between an "intent" and its "outcome",
main thread only (guardkeep / camera write from their own threads).
  issued        R1 (RB) rising edges ≥ presses intended
  partial       some, fewer than intended
  not_issued    none and nothing dropped
  dropped       pad.drop records in the range (the pad was frozen / closed: the report went to a null device)
  unknown       no / duplicate / out-of-fight outcome, an exception, or a ctl "gap" (queue full) overlapping the range —
                never counted as issued
partial reason (only what the records show): target_dead (the outcome says dead and the presses it counted = the R1 edges seen —
moves.light skips the next R1 once the target is dead) · sp_below_second (the intent's stamina < sp_min, light skips the
second R1) · input_missing (fewer R1 edges than the outcome counted) · dropped · unexplained
Hit link (optional --hits, the blackbox bundles): HP drops within POST_S after the intent's decision time. The bundle's
'blame' is the nearest foe — kept as 'attacker_unconfirmed', never as the attacker.
Research columns are copied from the record (null + reason) — nothing here fills them in.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RB = 0x0200
POST_S = 1.5             # 운영 설계값: 공격 결정 뒤 이만큼 안의 HP 감소를 그 결정 옆에 보여 줌 (원인 판정 아님)


def load(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def pad_link(recs: list[dict], s0: int, s1: int | None, presses: int) -> dict:
    if s1 is None:
        return {"status": "unknown", "why": "no outcome record"}
    gaps = [r for r in recs if r.get("k") == "gap" and not (r.get("seq_to", -1) < s0 or r.get("seq_from", 1 << 62) > s1)]
    rng = [r for r in recs if r.get("k") in ("pad", "pad.drop") and s0 < r.get("seq", -1) < s1 and r.get("th") == "MainThread"]
    prev = next((r for r in reversed([r for r in recs if r.get("k") == "pad" and r.get("seq", 1 << 62) < s0])), None)
    held = bool(prev and prev.get("btn", 0) & RB)
    edges, sites = 0, []
    for r in rng:
        if r["k"] == "pad":
            on = bool(r.get("btn", 0) & RB)
            if on and not held:
                edges += 1
                sites.append(r.get("caller"))
            held = on
    drops = sum(1 for r in rng if r["k"] == "pad.drop")
    if gaps:
        st = "unknown"
    elif drops and edges < presses:
        st = "dropped"
    elif edges >= presses:
        st = "issued"
    elif edges:
        st = "partial"
    else:
        st = "not_issued"
    return {"status": st, "rb_edges": edges, "intended": presses, "drops": drops, "gaps": len(gaps), "callers": sites,
            "pad_records": len(rng)}


def fight_spans(ct: list[dict]) -> list[dict]:
    """[{start, end}] by seq: a fight runs from its fight_start to its fight_end, else to the next fight_start, else open."""
    out = []
    for r in ct:
        if r["ev"] == "fight_start":
            if out and out[-1]["end"] is None:
                out[-1]["end"] = r["seq"] - 1
            out.append({"start": r["seq"], "end": None})
        elif r["ev"] == "fight_end" and out and out[-1]["end"] is None:
            out[-1]["end"] = r["seq"]
    return out


def fight_of(fights: list[dict], seq) -> dict | None:
    return next((f for f in fights if f["start"] < seq and (f["end"] is None or seq <= f["end"])), None)


def partial_reason(intent: dict, out: dict, pad: dict) -> str:
    counted = out.get("presses_counted")
    if pad.get("drops"):
        return "dropped"
    if counted is not None and pad["rb_edges"] < counted:
        return "input_missing"
    if out.get("dead") and counted is not None and counted == pad["rb_edges"] and counted < intent["presses"]:
        return "target_dead"
    me, conds = intent.get("me") or {}, intent.get("conds") or {}
    if me.get("sp") is not None and conds.get("sp_min") is not None and me["sp"] < conds["sp_min"] and pad["rb_edges"] == 1:
        return "sp_below_second"
    return "unexplained"


def hits_after(hits: list[dict], t0: float) -> list[dict]:
    out = []
    for b in hits:
        fr = b.get("frames", [])
        for a, f in zip(fr, fr[1:]):
            if f["hp"] < a["hp"] and t0 <= f["t"] <= t0 + POST_S:
                out.append({"dt": round(f["t"] - t0, 3), "dmg": a["hp"] - f["hp"],
                            "attacker_unconfirmed": [(x["npc"], x["anim"], x["d"]) for x in b.get("blame", [])]})
    seen, uniq = set(), []
    for h in out:
        k = (h["dt"], h["dmg"])
        if k not in seen:
            seen.add(k)
            uniq.append(h)
    return uniq


def report(recs: list[dict], hits: list[dict]) -> dict:
    ct = [r for r in recs if r.get("k") == "dec.counter"]
    out = {"schema": sorted({r.get("schema") for r in ct}), "commit": next((r.get("commit") for r in recs if r.get("k") == "hdr"), None),
           "events": {}, "strikes": [], "quality": {}}
    for r in ct:
        out["events"][r["ev"]] = out["events"].get(r["ev"], 0) + r.get("n", 1)
    run_id = next((r.get("run") for r in recs if r.get("k") == "hdr"), None)
    fights = fight_spans(ct)
    keyed: dict = {}
    for r in ct:
        if r["ev"] in ("intent", "outcome"):
            f = fight_of(fights, r["seq"])
            keyed.setdefault((r["ev"], None if f is None else f["start"], r.get("dec")), []).append(r)
    for r in ct:
        if r["ev"] != "intent":
            continue
        f = fight_of(fights, r["seq"])
        key = (run_id, None if f is None else f["start"], r.get("dec"))
        why = None
        if f is None:
            why = "intent outside any fight_start … fight_end"
        elif len(keyed.get(("intent", key[1], key[2]), [])) > 1:
            why = "two intents with one (fight, dec)"
        outs = [] if f is None else [o for o in keyed.get(("outcome", key[1], key[2]), []) if o["seq"] > r["seq"]]
        if why is None and not outs:
            why = "no outcome for this (fight, dec)"
        elif why is None and len(outs) > 1:
            why = "two outcomes for this (fight, dec)"
        o = outs[0] if why is None else None
        if o is not None and o.get("status") != "returned":
            pad = pad_link(recs, r["seq"], None, r["presses"])
            pad["why"] = f"outcome status {o.get('status')}: {o.get('error')}"
        elif o is not None:
            pad = pad_link(recs, r["seq"], o["seq"], r["presses"])
            if pad["status"] == "partial":
                pad["partial_reason"] = partial_reason(r, o, pad)
        else:
            pad = {"status": "unknown", "why": why}
        st = {"key": list(key), "dec": r["dec"], "seq": r["seq"], "outcome_seq": None if o is None else o["seq"],
              "decided_t": r.get("decided_t"), "kind": r["kind"], "presses": r["presses"],
              "target": r.get("target"), "foe": (r.get("foe") or {}).get("name"), "unknown_foe": (r.get("foe") or {}).get("unknown"),
              "limit": r.get("limit"), "observed_id_age": r.get("observed_id_age"), "owners": r.get("owners"),
              "conds": r.get("conds"), "near": r.get("near"),
              "outcome": None if o is None else {k: o.get(k) for k in ("status", "kind", "presses_counted", "dmg", "taken", "dead", "error")},
              "pad": pad,
              "research": {k: r.get(k) for k in ("anim_time", "anim_time_why", "hitbox", "hitbox_why", "tae", "tae_why", "id_restart")}}
        if hits and r.get("decided_t"):
            st["hp_drops_after"] = hits_after(hits, r["decided_t"])
        out["strikes"].append(st)
    end = next((r for r in recs if r.get("k") == "end"), None)
    out["quality"] = {"ctl_end": None if end is None else end.get("summary", {k: end.get(k) for k in ("written", "dropped", "lost")}),
                      "gaps": sum(r.get("count", 0) for r in recs if r.get("k") == "gap"),
                      "trace_errors": max([((r.get("trace") or {}).get("errors") or 0) for r in ct if r["ev"] == "fight_end"], default=None),
                      "intent_without_outcome": sum(1 for s in out["strikes"] if s["outcome"] is None)}
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return
    path = Path(args[0])
    hits = []
    if "--hits" in sys.argv:
        hits = load(Path(sys.argv[sys.argv.index("--hits") + 1]))
    rep = report(load(path), hits)
    print(f"{path.name}: schema {rep['schema']} · events {rep['events']}")
    for s in rep["strikes"]:
        t = s["target"] or {}
        print(f"  dec {s['dec']} seq {s['seq']}: {s['kind']} ×{s['presses']} → target {t.get('npc')}@{t.get('ptr')} anim {t.get('anim')} "
              f"h {t.get('h')} · foe {s['foe']} (unknown {s['unknown_foe']}) · limit {s['limit']} · observed_id_age {s['observed_id_age']}")
        print(f"     owners {s['owners']}")
        print(f"     pad {s['pad']} · outcome {s['outcome']}")
        for h in s.get("hp_drops_after", []):
            print(f"     HP −{h['dmg']} at +{h['dt']} s (attacker unconfirmed; blackbox nearest: {h['attacker_unconfirmed']})")
    print(f"  quality {rep['quality']}")
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
