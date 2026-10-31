"""ctl-linkage integrity check on one run's raw files only (<run>.ctl.jsonl + its .settings.json next to it). Read only —
nothing is moved, rewritten or filled in from neighbouring records.

  python ctl_check.py data/runs/<run>.ctl.jsonl                  link invariants + span.obs restorability
  python ctl_check.py data/runs/<run>.ctl.jsonl --cycles 50,778  + those cycles in time order (observation → rule → action
                                                                   → pad → next observation), each line with its L<n>
  python ctl_check.py data/runs/<run>.ctl.jsonl --vs-scene       + each scene against the span.obs of the same cycle, read
                                                                   counts per cycle, span.obs line sizes
Every finding names the record line (L<n>, 1-based) it comes from. The header line names the run, the file hashes and this
checker's own hash, so a result can be tied to what produced it.

Four different things — never one standing in for another:
  writer complete    the end record's complete (ctl.Sink.stop): the writer reached the stop marker and nothing was dropped /
                     lost / failed — every record emitted before stop() is in the file. Says nothing about what was emitted.
  linkage validity   span invariants (pairs, parents, picked ↔ span.rule, pad ids by thread): ids and links are consistent.
  input status       per cycle, from its span.obs record (ctlspan.Fight.sensed):
             sense_only      span.obs present and matching, and the read counter saw no other snapshot() call on the duel
                             thread in that cycle (snap_reads_sense == 1, snap_reads_after == 0, no resnap). It does NOT mean
                             no other input: other threads keep changing shared state the rules read (Moves.swung from every
                             thread's reads, CamFollow, GuardKeep), scalar reads (grip, lock_target, handle, goods_count) are
                             not counted, and Fight / reflex / care / shadow memory is not stored. Only the snapshot body is
                             restorable.
             partial         span.obs present, but the cycle called snapshot() again (F.cancel, rules, nav.goto, _watch);
                             those later bodies are not stored
             reads_uncounted span.obs present, the read counter saw nothing (a fake / non-counting telemetry) — can't tell
             dropped         the cycle names an obs_id that is not in the file and a gap record overlaps the cycle
             missing         … and no gap explains it
             no_obs          sense_result / sense_cont (rules never ran), obs_err, or a file from before span.obs existed
  full decision replay   re-running the decision exactly as it was — snapshot + Fight memory + derived state + scalar reads +
                     other threads' shared state at that instant. No file has that today; sense_only is not it.
--vs-scene compares two records written from the SAME snapshot object (scene copies it in scenes.capture, span.obs in
ctlspan.sensed): agreement checks that the two storage paths are consistent, not that the reading was right — it is not an
independent sensor check.
"""
from __future__ import annotations

import collections
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def load(path: Path) -> list[dict]:
    R = []
    for i, l in enumerate(path.read_bytes().decode("utf-8").splitlines(), 1):
        try:
            d = json.loads(l)
        except Exception:
            d = {"k": "BROKEN"}
        d["_L"] = i
        R.append(d)
    return R


def spans(R: list[dict]) -> tuple[dict, dict, dict, dict]:
    F, C, A = {}, {}, {}
    for x in R:
        if x["k"] == "span.fight":
            F.setdefault(x["fight_id"], {})[x["ev"]] = x
        elif x["k"] == "span.cycle":
            C.setdefault(x["cycle_id"], {})[x["ev"]] = x
        elif x["k"] == "span.action":
            A.setdefault(x["action_id"], {})[x["ev"]] = x
    return F, C, A, {x["rule_id"]: x for x in R if x["k"] == "span.rule"}


def input_status(R: list[dict]) -> dict:
    """cycle_id → (status, detail). See the module docstring for the statuses."""
    _, C, _, _ = spans(R)
    obs = {}
    for x in R:
        if x["k"] == "span.obs":
            obs.setdefault(x["obs_id"], []).append(x)
    gaps = [(x.get("seq_from"), x.get("seq_to")) for x in R if x["k"] == "gap"]
    out = {}
    for cid, v in C.items():
        e = v.get("end")
        if e is None:
            out[cid] = ("no_obs", "cycle not closed")
            continue
        if "obs_id" not in e:
            out[cid] = ("no_obs", "no obs_id field (file from before obs records)")
            continue
        oid = e.get("obs_id")
        if oid is None:
            out[cid] = ("no_obs", e.get("obs_err") or e["kind"])
            continue
        got = obs.get(oid, [])
        if not got:
            a, b = v.get("start", e)["seq"], e["seq"]
            hit = any(lo is not None and hi is not None and lo <= b and hi >= a for lo, hi in gaps)
            out[cid] = ("dropped" if hit else "missing", f"obs_id {oid} not in file")
            continue
        if len(got) > 1:
            out[cid] = ("missing", f"obs_id {oid} on {len(got)} records")
            continue
        o = got[0]
        if o["cycle_id"] != cid or (o.get("snap") or {}).get("t") != e.get("snap_t"):
            out[cid] = ("missing", f"obs L{o.get('_L')} belongs to cycle {o['cycle_id']} / t {(o.get('snap') or {}).get('t')}")
            continue
        rs, ra = e.get("snap_reads_sense"), e.get("snap_reads_after")
        if not rs:
            out[cid] = ("reads_uncounted", f"obs L{o.get('_L')}")
        elif rs == 1 and ra == 0 and not e.get("resnap"):
            out[cid] = ("sense_only", f"obs L{o.get('_L')}")
        else:
            out[cid] = ("partial", f"obs L{o.get('_L')} · reads in sense {rs}, after {ra}, resnap {e.get('resnap')}")
    return out


def restore(R: list[dict], obs_id) -> dict | None:
    """The stored snapshot body of one obs, as written (no fill-in). None if that obs is not in the file."""
    for x in R:
        if x["k"] == "span.obs" and x["obs_id"] == obs_id:
            return {"src": x["src"], "fseq": x["fseq"], "now": x["now"], "target_ptr": x["target_ptr"], **x["snap"]}
    return None


def report(p: Path, want_cycles: list[int] | None = None) -> None:
    raw = p.read_bytes()
    R = load(p)
    me = Path(__file__).resolve()
    st = p.with_name(p.name.replace(".ctl.jsonl", ".settings.json"))
    head = subprocess.run(["git", "-C", str(me.parent), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    print(f"run {p.name.split('.')[0]} · ctl sha256 {hashlib.sha256(raw).hexdigest()[:16]} ({len(R)} lines) · "
          f"settings sha256 {hashlib.sha256(st.read_bytes()).hexdigest()[:16] if st.exists() else None} · "
          f"checker sha256 {hashlib.sha256(me.read_bytes()).hexdigest()[:16]} · repo HEAD {head}")
    K = collections.Counter(x["k"] for x in R)
    print("kinds:", dict(K))
    end = [x for x in R if x["k"] == "end"]
    print("end:", {k: v for k, v in end[-1].items() if k not in ("k", "th")} if end else "NONE")
    print("gap records:", [(x["_L"], x["count"]) for x in R if x["k"] == "gap"], "· broken lines:", K["BROKEN"],
          "· lines after end:", (len(R) - end[-1]["_L"]) if end else None)
    print("life:", [(x["_L"], x.get("ev"), x.get("result") or x.get("exc")) for x in R if x["k"] == "life"])

    F, C, A, SR = spans(R)

    def pair(name, D):
        full = [k for k, v in D.items() if "start" in v and "end" in v]
        no_end = [(k, v["start"]["_L"]) for k, v in D.items() if "end" not in v]
        no_start = [(k, v["end"]["_L"]) for k, v in D.items() if "start" not in v]
        print(f"{name}: {len(D)} · paired {len(full)} · start without end {no_end[:5]} · end without start {no_start[:5]}")
    pair("fight", F); pair("cycle", C); pair("action", A)
    print("fight results:", collections.Counter(v.get("end", {}).get("result") for v in F.values()))
    print("cycle parent not a fight:", [(k, v["start"]["_L"]) for k, v in C.items() if "start" in v and v["start"]["parent"] not in F][:5])
    print("cycle end kinds:", dict(collections.Counter(v["end"]["kind"] for v in C.values() if "end" in v)))
    print("cycle src:", dict(collections.Counter(v["end"].get("src") for v in C.values() if "end" in v)),
          "· resnap true:", sum(1 for v in C.values() if v.get("end", {}).get("resnap")))
    mism = []
    for rid, r in SR.items():
        ce = C.get(r["parent"], {}).get("end")
        if ce is None:
            mism.append((rid, r["_L"], "cycle not closed"))
        elif ce["picked"] != r["rule"] or ce["rule_id"] != rid:
            mism.append((rid, r["_L"], ce["picked"], r["rule"]))
    picked = [v["end"] for v in C.values() if "end" in v and v["end"]["picked"] is not None]
    print(f"span.rule {len(SR)} · cycles with picked {len(picked)} · rule↔picked mismatch {mism[:5]} · picked without span.rule "
          f"{[c['_L'] for c in picked if c['rule_id'] not in SR][:5]}")
    print("picked rules:", dict(collections.Counter(c["picked"] for c in picked)))
    np_ = collections.Counter(n for v in C.values() for n in v.get("end", {}).get("none_pad", []))
    print("none_pad (rule returned None after writing the pad):", dict(np_), "in",
          sum(1 for v in C.values() if v.get("end", {}).get("none_pad")), "cycles")
    print("span.rule pc order broken:", [r["_L"] for r in SR.values() if not (r["enter_pc"] <= r["ret_pc"] and all(
        r[k] is None or r["enter_pc"] <= r[k] <= r["ret_pc"] for k in ("first_action_pc", "first_pad_pc")))][:5])
    acts = [v for v in A.values() if "start" in v]
    print("actions:", dict(collections.Counter(v["start"]["action"] for v in acts)),
          "· parent kinds", dict(collections.Counter(v["start"]["parent_kind"] for v in acts)),
          "· rule_id set", sum(1 for v in acts if v["start"]["rule_id"] is not None), "/", len(acts),
          "· rule_id → emitted span.rule", sum(1 for v in acts if v["start"]["rule_id"] in SR))
    print("action parent dangling:", [v["start"]["_L"] for v in acts if (
        v["start"]["parent"] not in A if v["start"]["parent_kind"] == "action" else v["start"]["parent"] not in C)][:5])
    # end "dead" / "gone" (moves._watch): the TARGET's HP reached 0 / it left the list — not the player's death
    print("action end reasons (dead = target HP 0):", dict(collections.Counter((v["start"]["action"], v.get("end", {}).get("end")) for v in acts)))
    print("action with hit:", sum(1 for v in acts if "hit" in v.get("end", {})), "· with ret:", sum(1 for v in acts if "ret" in v.get("end", {})))
    pads = [x for x in R if x["k"] in ("pad", "pad.drop")]
    by_th = collections.defaultdict(list)
    for x in pads:
        by_th[x["th"]].append(x)
    cyc_rng = {k: (v["start"]["seq"], v.get("end", {}).get("seq", 1 << 62)) for k, v in C.items() if "start" in v}
    for th, xs in by_th.items():
        print(f"pad th={th}: {len(xs)} records (+dup {sum(x.get('dup', 0) for x in xs)}) · with cycle_id "
              f"{sum(1 for x in xs if x.get('cycle_id') is not None)} · with action_id {sum(1 for x in xs if x.get('action_id') is not None)}")
    main = by_th.get("MainThread", [])
    fights_rng = [(v["start"]["seq"], v.get("end", {}).get("seq", 1 << 62)) for v in F.values() if "start" in v]
    unl_in_cycle = [x["_L"] for x in main if x.get("cycle_id") is None and any(a <= x["seq"] <= b for a, b in cyc_rng.values())]
    unl_in_fight = [x for x in main if x.get("cycle_id") is None and any(a <= x["seq"] <= b for a, b in fights_rng)]
    print(f"main pad without ids inside an open cycle: {len(unl_in_cycle)} {unl_in_cycle[:5]} · inside a fight but between cycles: "
          f"{len(unl_in_fight) - len(unl_in_cycle)} (callers {dict(collections.Counter(x['caller'] for x in unl_in_fight if x['_L'] not in unl_in_cycle).most_common(5))})")
    print("main pad cycle_id outside that cycle's seq range:", [x["_L"] for x in main if x.get("cycle_id") is not None and not (
        cyc_rng.get(x["cycle_id"], (1, 0))[0] <= x["seq"] <= cyc_rng.get(x["cycle_id"], (1, 0))[1])][:5])
    other = [x for x in pads if x["th"] != "MainThread"] + [x for x in R if x["k"] == "pad.override" and x["th"] != "MainThread"]
    print("other threads with a main id:", [(x["_L"], x["th"]) for x in other if x.get("cycle_id") is not None or x.get("action_id") is not None][:5])
    ov = [x for x in R if x["k"] == "pad.override"]
    print("pad.override:", len(ov), dict(collections.Counter((x["m"], x["th"], x.get("cycle_id") is not None) for x in ov)))
    print("pad.drop:", K["pad.drop"])
    sc = [x for x in R if x["k"] == "scene"]
    in_c = collections.Counter(sum(1 for a, b in cyc_rng.values() if a <= x["seq"] <= b) for x in sc)
    print(f"scenes {len(sc)} · inside exactly one cycle {in_c[1]} · none {in_c[0]} · cycles with picked and a scene "
          f"{sum(1 for a, b in cyc_rng.values() if any(a <= x['seq'] <= b for x in sc))}/{len(picked)}")
    ins = input_status(R)
    print("input (obs) per cycle:", dict(collections.Counter(s for s, _ in ins.values())),
          "· examples", {s: next((f"{k}: {d}" for k, (s2, d) in ins.items() if s2 == s), None)
                         for s in sorted({s for s, _ in ins.values()})})
    print("writer complete (end record) ≠ input restorable — they are reported apart")
    if st.exists():
        e = json.loads(st.read_text(encoding="utf-8")).get("end")
        print("settings end:", None if e is None else {k: e.get(k) for k in ("result", "end_read", "last_valid_obs", "end_state_known")})
    for c in want_cycles or ():
        show(R, C, c)


def show(R: list[dict], C: dict, cid) -> None:
    key = next((k for k in C if str(k) == str(cid)), None)
    if key is None:
        print(f"\n── cycle {cid}: not in file")
        return
    v = C[key]
    a, b = v["start"]["seq"], v.get("end", {}).get("seq", 1 << 62)
    e = v.get("end", {})
    print(f"\n── cycle {key} (L{v['start']['_L']}–L{e.get('_L')}) picked={e.get('picked')} kind={e.get('kind')} "
          f"none_pad={e.get('none_pad')} obs_id={e.get('obs_id')} reads sense/after={e.get('snap_reads_sense')}/{e.get('snap_reads_after')}")
    t0 = v["start"]["pc"]
    last = None
    for x in R:
        if x["k"] in ("hdr", "sync") or not (a <= x.get("seq", -1) <= b) or x["th"] != "MainThread":
            continue
        ms = (x["pc"] - t0) / 1e6
        k = x["k"]
        if k == "pad":
            rep = (x["btn"], x["lx"], x["ly"], x["rx"])
            if rep == last:
                continue
            last = rep
            s = f"pad {x['m']} btn={x['btn']:#06x} L=({x['lx']},{x['ly']}) R=({x['rx']}) {x['caller']} act={x.get('action_id')}"
        elif k == "span.cycle":
            s = f"cycle {x['ev']}" + ("" if x["ev"] == "start" else f" snap_t={x['snap_t']} fseq={x['fseq']} src={x['src']} "
                                      f"sense_pc+{(x['sense_pc'] - t0) / 1e6 if x.get('sense_pc') else 0:.1f}ms my_anim={x['my_anim']} "
                                      f"none_n={x['none_n']} resnap={x['resnap']}")
        elif k == "span.rule":
            f = lambda q: "-" if x[q] is None else round((x[q] - t0) / 1e6, 1)
            s = f"rule {x['rule']} enter+{f('enter_pc')} first_pad+{f('first_pad_pc')} first_action+{f('first_action_pc')} ret+{f('ret_pc')} out={x['out']}"
        elif k == "span.action":
            s = f"action {x['ev']} {x.get('action', '')} id={x['action_id']} " + (
                json.dumps(x.get("params")) if x["ev"] == "start" else f"end={x['end']} hit={json.dumps(x.get('hit'))[:300]}")
        elif k == "span.obs":
            s = f"obs id={x['obs_id']} src={x['src']} chars={len(x['snap']['chars'])} target={x['target_ptr']} t={x['snap']['t']}"
        elif k == "scene":
            s = f"scene rule={x['rule']} out={x['out']} snap.t={x['snap']['t']} tick={x['tick']} chars={len(x['snap']['chars'])}"
        elif k == "dec.rule":
            s = f"dec.rule {x['rule']} n={x['n']} out={x['out']} (folded record: may describe earlier cycles)"
        else:
            s = f"{k} {x.get('ev', '')} {x.get('act', '')}"
        print(f"  L{x['_L']:<6} +{ms:8.1f} ms  {s}")
    later = sorted((w for w in C.values() if "start" in w and w["start"]["seq"] > b), key=lambda w: w["start"]["seq"])
    if later and "end" in later[0]:
        n = later[0]["end"]
        same = later[0]["start"]["parent"] == v["start"]["parent"]
        print(f"  next cycle {n['cycle_id']} L{n['_L']}{'' if same else ' (next fight)'}: snap_t={n['snap_t']} my_anim={n['my_anim']}"
              + (f" (sense +{(n['sense_pc'] - t0) / 1e6:.1f} ms)" if n.get("sense_pc") else f" kind {n['kind']}"))


def vs_scene(p: Path) -> None:
    """Each scene ↔ the span.obs of the cycle it lies in (same snapshot object, two storage paths — a consistency check of the
    records, not of the reading), read counts per cycle, span.obs line sizes."""
    import statistics as S
    raw = p.read_bytes()
    lines = raw.decode("utf-8").splitlines()
    R = load(p)
    _, C, _, _ = spans(R)
    st = input_status(R)
    ce = {k: v["end"] for k, v in C.items() if "end" in v}
    print("\n── vs-scene (consistency of two records of one read, not an independent sensor check)")
    print("input status by cycle kind:", dict(collections.Counter((ce[k]["kind"], s) for k, (s, _) in st.items() if k in ce)))
    print("(snapshot() calls in sense, after) for cycles with span.obs:",
          dict(collections.Counter((e.get("snap_reads_sense"), e.get("snap_reads_after")) for e in ce.values()
                                   if e.get("obs_id") is not None).most_common(12)))
    for lab in ("partial", "sense_only"):
        print(f"{lab} by picked rule:", dict(collections.Counter(ce[k]["picked"] for k, (s, _) in st.items() if s == lab)))
    obs = [x for x in R if x["k"] == "span.obs"]
    sz = [len(lines[x["_L"] - 1].encode()) for x in obs]
    nc = [len(x["snap"]["chars"]) for x in obs]
    if sz:
        print(f"span.obs lines {len(sz)} · bytes min {min(sz)} med {int(S.median(sz))} max {max(sz)} total {sum(sz)} of file "
              f"{len(raw)} · chars per obs min {min(nc)} med {S.median(nc)} max {max(nc)}")
    rng = {k: (v["start"]["seq"], v["end"]["seq"]) for k, v in C.items() if "start" in v and "end" in v}
    for x in R:
        if x["k"] != "scene":
            continue
        cid = next((k for k, (a, b) in rng.items() if a <= x["seq"] <= b), None)
        b = None if cid is None else restore(R, ce[cid].get("obs_id"))
        if b is None:
            print(f"scene L{x['_L']} cycle {cid}: no span.obs")
            continue
        sc = x["snap"]
        near = [c for c in b["chars"] if c["dist"] <= 25.0]           # scenes.CHAR_R
        print(f"scene L{x['_L']} ↔ span.obs (cycle {cid}): player same {b['player'] == sc['player']} · chars ≤25 m same "
              f"{near == sc['chars']} ({len(near)} vs {len(sc['chars'])}) · cam_yaw same {b['cam_yaw'] == sc['cam_yaw']} · "
              f"t same {x['t_wall'] + sc['t'] == b['t']} · span.obs chars beyond 25 m {len(b['chars']) - len(near)} · "
              f"target {b['target_ptr']} == scene tick ptr {x['tick']['ptr']}")
        if near != sc["chars"]:
            for a_, c_ in zip(near, sc["chars"]):
                if a_ != c_:
                    print("   first diff:", {k: (a_.get(k), c_.get(k)) for k in set(a_) | set(c_) if a_.get(k) != c_.get(k)})
                    break


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    cyc = None
    if "--cycles" in argv:
        cyc = [int(x) for x in argv[argv.index("--cycles") + 1].split(",")]
    report(Path(argv[1]), cyc)
    if "--vs-scene" in argv:
        vs_scene(Path(argv[1]))


if __name__ == "__main__":
    main(sys.argv)
