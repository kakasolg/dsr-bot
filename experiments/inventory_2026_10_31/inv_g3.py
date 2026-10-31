"""Per-run G3 summary JSON from a ctl.jsonl via ctl_check (read only). python inv_g3.py <repo> <outdir> <run>..."""
import collections, json, statistics, sys
from pathlib import Path
repo, out = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(repo))
import ctl_check as K
for run in sys.argv[3:]:
    p = repo / "data/runs" / f"{run}.ctl.jsonl"
    R = K.load(p)
    F, C, A, RU = K.spans(R)
    ends = [v["end"] for v in C.values() if "end" in v]
    st = K.input_status(R)
    obs = [x for x in R if x["k"] == "span.obs"]
    nc = [len((x.get("snap") or {}).get("chars") or []) for x in obs]
    end = next((x for x in R if x["k"] == "end"), None)
    kinds = collections.Counter(x["k"] for x in R)
    d = {
        "run": run, "source": f"data/runs/{run}.ctl.jsonl", "lines": len(R), "bytes": p.stat().st_size,
        "broken_lines": kinds.get("BROKEN", 0),
        "counts": {"fight": len(F), "fight_paired": sum(1 for v in F.values() if "start" in v and "end" in v),
                   "cycle": len(C), "cycle_paired": sum(1 for v in C.values() if "start" in v and "end" in v),
                   "rule": len(RU), "action": len(A), "action_paired": sum(1 for v in A.values() if "start" in v and "end" in v),
                   "span.obs": len(obs), "scene": kinds.get("scene", 0), "pad": kinds.get("pad", 0),
                   "pad.override": kinds.get("pad.override", 0), "dec.rule": kinds.get("dec.rule", 0)},
        "record_kinds": dict(kinds),
        "cycle_kind": dict(collections.Counter(e.get("kind") for e in ends)),
        "picked": dict(collections.Counter(e.get("picked") for e in ends if e.get("picked") is not None)),
        "fight_result": dict(collections.Counter(v["end"].get("result") for v in F.values() if "end" in v)),
        "action_name": dict(collections.Counter(v["start"].get("action") for v in A.values() if "start" in v)),
        "action_end": dict(collections.Counter(v["end"].get("end") for v in A.values() if "end" in v)),
        "obs_status": dict(collections.Counter(s for s, _ in st.values())),
        "obs_chars_per_record": ({"min": min(nc), "median": statistics.median(nc), "max": max(nc)} if nc else None),
        "ctl_end": ({k: end.get(k) for k in ("written", "dropped", "lost", "write_errors", "writer_joined", "complete")} if end else None),
        "note": "counts from ctl_check.load/spans/input_status (checker = ctl_check.py at this commit); obs_status covers every cycle id",
    }
    (out / f"g3_{run}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(run, d["counts"], d["obs_status"])
