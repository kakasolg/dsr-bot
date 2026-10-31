"""One record of each kind from one attack cycle, raw lines (chars lists cut to 3 with _truncated). python inv_examples.py <ctl> <out> <cycle_id>"""
import json, sys
src, out, cid = sys.argv[1], sys.argv[2], int(sys.argv[3])
lines = open(src, encoding="utf-8").read().splitlines()
R = [json.loads(l) for l in lines]
cs = next(x for x in R if x["k"] == "span.cycle" and x["cycle_id"] == cid and x["ev"] == "start")
ce = next(x for x in R if x["k"] == "span.cycle" and x["cycle_id"] == cid and x["ev"] == "end")
fid = cs["parent"]
lo, hi = cs["seq"], ce["seq"]
inside = lambda x: lo <= x["seq"] <= hi
act = next(x for x in R if x["k"] == "span.action" and x["ev"] == "start" and x["parent"] == cid)
picks = [
    ("span.fight start", lambda x: x["k"] == "span.fight" and x["fight_id"] == fid and x["ev"] == "start"),
    ("span.fight end", lambda x: x["k"] == "span.fight" and x["fight_id"] == fid and x["ev"] == "end"),
    ("span.cycle start", lambda x: x is cs),
    ("span.cycle end", lambda x: x is ce),
    ("span.rule", lambda x: x["k"] == "span.rule" and x["parent"] == cid),
    ("span.action start", lambda x: x is act),
    ("span.action end", lambda x: x["k"] == "span.action" and x["action_id"] == act["action_id"] and x["ev"] == "end"),
    ("span.obs", lambda x: x["k"] == "span.obs" and x["obs_id"] == ce.get("obs_id")),
    ("pad (with action_id)", lambda x: x["k"] == "pad" and x.get("action_id") == act["action_id"]),
    ("pad.override", lambda x: x["k"] == "pad.override" and inside(x)),
    ("scene", lambda x: x["k"] == "scene" and inside(x)),
]
with open(out, "w", encoding="utf-8", newline="\n") as f:
    for name, pred in picks:
        i = next((i for i, x in enumerate(R) if pred(x)), None)
        if i is None:
            print(f"{name}: none in cycle {cid}")
            continue
        x = R[i]
        snap = x.get("snap")
        if isinstance(snap, dict) and isinstance(snap.get("chars"), list) and len(snap["chars"]) > 3:
            n = len(snap["chars"]); snap["chars"] = snap["chars"][:3]; x["_truncated"] = n
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
        else:
            f.write(lines[i] + "\n")
        print(f"{name}: line {i + 1}" + (f" (chars cut, was {x['_truncated']})" if "_truncated" in x else " (raw)"))
