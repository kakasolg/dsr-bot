"""Reflex error audit for I1-current vs I2-memory (fixed C3). No training, no prediction: joins the stored predictions with
the stored scene inputs and counts.

  python audit_reflex.py --extract <g2_scene_extract.jsonl> --manifest <g2_scene_manifest_scenes.jsonl> \
      --exp-dir <experiments/g2_i1_vs_i2memory_c3_2026_10_31> --manifest-runs <g2_scene_manifest_runs.json> --out <audit dir>
"""
import argparse, collections, hashlib, json, statistics
from pathlib import Path

ATTACK = range(3000, 3500)          # souls/moves.py:24 ATTACK
ap = argparse.ArgumentParser()
for k in ("--extract", "--manifest", "--exp-dir", "--manifest-runs", "--out"): ap.add_argument(k, required=True)
a = ap.parse_args()
exp, out = Path(a.exp_dir), Path(a.out)
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
cfg = json.load(open(exp / "i2_config.json", encoding="utf-8"))
assert sha(a.extract) == cfg["refs"]["extract_sha256"] and sha(a.manifest) == cfg["refs"]["manifest_sha256"]
X = {(x["run"], x["scene_seq"]): x for x in map(json.loads, open(a.extract, encoding="utf-8"))}
man = {(d["run"], d["scene_seq"]): d["split"] for d in map(json.loads, open(a.manifest, encoding="utf-8"))}
P = [json.loads(l) for l in open(exp / "predictions.jsonl", encoding="utf-8")]
runs_meta = {r["run"]: r for r in json.load(open(a.manifest_runs, encoding="utf-8"))["runs"]}

# join checks
keys = [(p["run"], p["scene_seq"]) for p in P]
join = {"pred_rows": len(P), "unique": len(set(keys)), "duplicates": len(keys) - len(set(keys)),
        "unlinked": sum(1 for k in keys if k not in X),
        "split_mismatch": sum(1 for p in P if X[(p["run"], p["scene_seq"])]["split"] != p["split"] or man[(p["run"], p["scene_seq"])] != p["split"]),
        "y_true_mismatch": sum(1 for p in P if X[(p["run"], p["scene_seq"])]["rule"] != p["y_true"]),
        "pending_in_predictions": sum(1 for p in P if p["split"] == "pending")}


def rel(v):
    return -v["_t"] if isinstance(v, dict) and "_t" in v else None


def dget(d, key):
    if isinstance(d, dict) and "_dict" in d:
        for k, v in d["_dict"]:
            if k == key: return v
    return None


def fields(x):
    """Values as the I2-memory script computed them (i1_i2_compare.memory), None = missing; plus raw reflex parts."""
    tp = x["tick"]["ptr"]; f = x["fight"]; rx = x["reflex"]; p = x["snap"]["player"]
    t = next(c for c in x["snap"]["chars"] if c["ptr"] == tp)
    st = rx["start"].get("_dict", []) if isinstance(rx.get("start"), dict) else []
    a_now = x["tick"]["a"]
    rx_anim = dget(rx.get("anim"), tp)
    start_t = next((v for k, v in st if k == tp), None)
    return {"tgt_anim": a_now, "tgt_anim_is_attack": a_now is not None and a_now in ATTACK,
            "tgt_h": round(x["tick"]["h"], 2), "my_hp_ratio": round(p["hp"] / p["max_hp"], 3) if p["max_hp"] else None,
            "my_sp_ratio": round(p["sp"] / p["max_sp"], 3) if p["max_sp"] else None,
            "reflex_age_s": rx.get("age"),
            "reflex_anim_target": rx_anim, "reflex_anim_target_is_attack": rx_anim is not None and rx_anim in ATTACK,
            "reflex_start_has_target": start_t is not None,
            "reflex_target_since_start_s": rel(start_t),
            "reflex_prefer_is_target": rx.get("prefer") == tp,
            "aprev_anim": f.get("_aprev", "__absent__"),
            "since_swing_end_s": rel(f.get("_swing_end_t")), "swing_end_key": "_swing_end_t" in f,
            "since_swing_aged_s": rel(f.get("_swing_aged")), "since_stag_s": rel(f.get("_stag_t")),
            "stag_is_target": (f.get("_stag_ptr") == tp) if "_stag_ptr" in f else None,
            "since_target_swung_s": rel(dget(f.get("swung"), tp))}


# reflex.age semantics recount on train (same definition as the earlier report: tick.a in 3000-3499 and age None)
tr = [x for x in X.values() if x["split"] == "train"]
age_none = [x for x in tr if x["reflex"]["age"] is None]
sem = {"train_n": len(tr), "age_none": len(age_none),
       "age_none_and_tick_a_attack": sum(1 for x in age_none if x["tick"]["a"] is not None and x["tick"]["a"] in ATTACK),
       "age_set_and_tick_a_not_attack": sum(1 for x in tr if x["reflex"]["age"] is not None and not (x["tick"]["a"] is not None and x["tick"]["a"] in ATTACK))}
# exact rule of attack_age: None iff reflex._anim[target] not in ATTACK or target not in reflex._start
viol = 0
for x in tr:
    ff = fields(x)
    pred_none = not (ff["reflex_anim_target_is_attack"] and ff["reflex_start_has_target"])
    viol += (pred_none != (x["reflex"]["age"] is None))
sem["attack_age_rule_violations_train"] = viol
sem["age_none_by_reflex_anim_attack"] = dict(collections.Counter(
    ("reflex_anim_attack" if fields(x)["reflex_anim_target_is_attack"] else "reflex_anim_not_attack") + "/" +
    ("start_present" if fields(x)["reflex_start_has_target"] else "start_absent") for x in age_none))

res = {"join": join, "reflex_age_semantics": sem, "eval": {}}
scene_rows = []
GROUPS = ("both_correct", "i1_only", "i2_only", "both_wrong")
summ_keys = ["tgt_anim_is_attack", "reflex_anim_target_is_attack", "reflex_start_has_target", "reflex_prefer_is_target", "swing_end_key"]
num_keys = ["tgt_h", "my_hp_ratio", "my_sp_ratio", "reflex_age_s", "reflex_target_since_start_s", "since_swing_end_s", "since_stag_s", "since_target_swung_s"]


def describe(rows):
    d = {"n": len(rows), "runs": len({r["run"] for r in rows})}
    for k in summ_keys: d[k] = dict(collections.Counter(str(r["f"][k]) for r in rows))
    for k in num_keys:
        vals = [r["f"][k] for r in rows if r["f"][k] is not None]
        d[k] = {"present": len(vals), "missing": len(rows) - len(vals),
                "min": round(min(vals), 3) if vals else None, "median": round(statistics.median(vals), 3) if vals else None, "max": round(max(vals), 3) if vals else None}
    d["tgt_anim"] = dict(collections.Counter(str(r["f"]["tgt_anim"]) for r in rows).most_common(8))
    d["aprev_anim"] = dict(collections.Counter(str(r["f"]["aprev_anim"]) for r in rows).most_common(8))
    return d


for sp in ("val", "test", "shift_zone", "shift_ref"):
    rows = []
    for p in P:
        if p["split"] != sp or p["y_true"] != "reflex": continue
        x = X[(p["run"], p["scene_seq"])]
        g = "both_correct" if p["y_pred_i1"] == "reflex" and p["y_pred_i2_memory"] == "reflex" else "i1_only" if p["y_pred_i1"] == "reflex" else "i2_only" if p["y_pred_i2_memory"] == "reflex" else "both_wrong"
        r = {"run": p["run"], "scene_seq": p["scene_seq"], "split": sp, "y_true": "reflex", "y_pred_i1": p["y_pred_i1"], "y_pred_i2_memory": p["y_pred_i2_memory"], "group": g, "f": fields(x)}
        rows.append(r)
    e = {"n": len(rows), "runs": len({r["run"] for r in rows})}
    for g in GROUPS:
        rs = [r for r in rows if r["group"] == g]
        e[g] = {"n": len(rs), "runs": len({r["run"] for r in rs}), "i1_pred": dict(collections.Counter(r["y_pred_i1"] for r in rs)),
                "i2_pred": dict(collections.Counter(r["y_pred_i2_memory"] for r in rs)), "by_run": dict(collections.Counter(r["run"] for r in rs)), "values": describe(rs) if rs else None}
    res["eval"][sp] = e
    scene_rows += rows

# train reference for the same true rules (descriptive)
def train_ref(rule):
    rs = [{"run": x["run"], "f": fields(x)} for x in tr if x["rule"] == rule]
    return describe(rs)
res["train_reference"] = {r: train_ref(r) for r in ("reflex", "face_first", "stagger_punish")}

# 212954 focus
RID = "20261019_212954_parish-group1"
fr = [p for p in P if p["run"] == RID]
res["run_212954"] = {"run": RID, "meta": runs_meta.get(RID),
    "style": dict(collections.Counter(X[(p["run"], p["scene_seq"])]["style"] for p in fr)),
    "weapon": dict(collections.Counter(str(X[(p["run"], p["scene_seq"])]["weapon"]) for p in fr)),
    "n": len(fr), "y_true": dict(collections.Counter(p["y_true"] for p in fr)),
    "i1_pred": dict(collections.Counter(p["y_pred_i1"] for p in fr)), "i2_pred": dict(collections.Counter(p["y_pred_i2_memory"] for p in fr)),
    "transitions_true_i1_i2": dict(collections.Counter(f"{p['y_true']}|{p['y_pred_i1']}|{p['y_pred_i2_memory']}" for p in fr)),
    "values_by_true_rule": {rule: describe([{"run": p["run"], "f": fields(X[(p["run"], p["scene_seq"])])} for p in fr if p["y_true"] == rule])
                            for rule in sorted({p["y_true"] for p in fr})}}
for p in fr:
    if p["y_true"] == "face_first":
        scene_rows.append({"run": p["run"], "scene_seq": p["scene_seq"], "split": p["split"], "y_true": p["y_true"], "y_pred_i1": p["y_pred_i1"],
                           "y_pred_i2_memory": p["y_pred_i2_memory"], "group": "212954_face_first", "f": fields(X[(p["run"], p["scene_seq"])])})
# other eval runs with true reflex / face_first: where losses happen
loss = collections.Counter(); tot = collections.Counter()
for p in P:
    if p["y_true"] in ("reflex", "face_first"):
        tot[(p["y_true"], p["split"], p["run"])] += 1
        if p["y_pred_i1"] == p["y_true"] and p["y_pred_i2_memory"] != p["y_true"]: loss[(p["y_true"], p["split"], p["run"])] += 1
res["reflex_face_first_by_run"] = [{"rule": k[0], "split": k[1], "run": k[2], "true_n": n, "i1_right_i2_wrong": loss[k]} for k, n in sorted(tot.items())]
res["rf_max_features"] = {"setting": cfg["model"]["common"]["max_features"], "n_features": {"I1": 61, "I2_memory": 174},
                          "sqrt_candidates_per_split": {"I1": int(61 ** 0.5), "I2_memory": int(174 ** 0.5)},
                          "note": "sklearn 'sqrt' -> max(1, int(sqrt(n_features))) candidate features per split"}
json.dump(res, open(out / "reflex_error_audit.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
with open(out / "reflex_error_scenes.jsonl", "w", encoding="utf-8") as f:
    for r in scene_rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(json.dumps(join), json.dumps(sem))
