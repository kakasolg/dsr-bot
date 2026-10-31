"""I1-current vs I2-memory with fixed C3 RandomForest settings. Imports the committed I1-current script unchanged.

  PYTHONDONTWRITEBYTECODE=1 python i1_i2_compare.py --config i2_config.json --rf-dir <experiments/g2_i1current_rf_2026_10_31> \
      --c34-dir <experiments/g2_c3_c4_classweight_diag_2026_10_31> --extract <g2_scene_extract.jsonl> --manifest <manifest_scenes.jsonl> \
      --baseline-results <baseline results.json> --out <dir>
"""
import argparse, collections, hashlib, importlib.util, json, math
from pathlib import Path

import numpy as np


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


ap = argparse.ArgumentParser()
for k in ("--config", "--rf-dir", "--c34-dir", "--extract", "--manifest", "--baseline-results", "--out"): ap.add_argument(k, required=True)
a = ap.parse_args()
out = Path(a.out); rf = Path(a.rf_dir); c34 = Path(a.c34_dir)
cfg = json.load(open(a.config, encoding="utf-8"))
assert sha(rf / "config.json") == cfg["refs"]["rf_config_sha256"] and sha(rf / "rf_i1current.py") == cfg["refs"]["rf_script_sha256"]
assert sha(a.baseline_results) == cfg["refs"]["baseline_results_sha256"]
spec = importlib.util.spec_from_file_location("rfi", rf / "rf_i1current.py"); R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
rfcfg = json.load(open(rf / "config.json", encoding="utf-8"))
X = R.load(argparse.Namespace(extract=a.extract, manifest=a.manifest), rfcfg)   # also checks extract/manifest hashes
bl = json.load(open(a.baseline_results, encoding="utf-8"))["variants"]["A_base"]["eval"]
bl_sets = {e: v["lookup"]["primary_classes"] for e, v in bl.items()}

NAN = float("nan")


def rel(v):
    """since (s) from a captured wall-time timer; NaN when never set (0.0 / None / absent)."""
    if isinstance(v, dict) and "_t" in v: return -v["_t"]
    return NAN


def dget(d, key):
    if not isinstance(d, dict) or "_dict" not in d: return None
    for k, v in d["_dict"]:
        if k == key: return v
    return None


def memory(x) -> dict:
    f, rx, cr = x["fight"], x["reflex"], x["care"]
    tp = x["tick"]["ptr"]
    t = next(c for c in x["snap"]["chars"] if c["ptr"] == tp)
    has = lambda k: k in f
    num = lambda v: NAN if v is None else float(v)
    shots = [s for s in f.get("shots", []) if isinstance(s, dict) and "_t" in s]
    sw = f.get("swung", {}).get("_dict", [])
    st = rx.get("start", {}).get("_dict", []) if isinstance(rx.get("start"), dict) else []
    still = f.get("still")
    y0 = dget(f.get("_foe_y0"), tp)
    m = {"mem_fight_age_s": rel(f.get("t0")), "mem_since_last_dmg_s": rel(f.get("last_dmg_t")),
         "mem_best_h_m": num(f.get("best_h")), "mem_since_best_s": rel(f.get("best_t")),
         "mem_hp_start": num(f.get("hp_start")), "mem_hp_min": num(f.get("hp_min")),
         "mem_hp_lost_in_fight": (f["hp_start"] - f["hp_min"]) if (f.get("hp_start") is not None and f.get("hp_min") is not None) else NAN,
         "mem_since_kick_s": rel(f.get("kick_t")), "mem_since_backstep_s": rel(f.get("backstep_t")), "mem_since_care_s": rel(f.get("care_t")),
         "mem_since_move_s": rel(f.get("move_t")), "mem_since_sep_s": rel(f.get("sep_t")), "mem_sep_n": num(f.get("sep_n")),
         "mem_since_switch_s": rel(f.get("switch_t")), "mem_since_wait_start_s": rel(f.get("wait_t0")),
         "mem_wait_hmin_m": num(f.get("wait_hmin")) if isinstance(f.get("wait_t0"), dict) else NAN,
         "mem_wait_hp0": num(f.get("wait_hp0")),
         "mem_edge_until_rel_s": f["edge_until"]["_t"] if isinstance(f.get("edge_until"), dict) else NAN,
         "mem_since_lock_s": rel(f.get("lock_t")), "mem_lock_n": num(f.get("lock_n")) if has("lock_n") else NAN,
         "mem_circle_n": num(f.get("circle_n")), "mem_shot_hp": num(f.get("shot_hp")),
         "mem_n_shots": float(len(f.get("shots", []))), "mem_since_last_shot_s": min(-s["_t"] for s in shots) if shots else NAN,
         "mem_since_still_s": rel(still[3]) if isinstance(still, list) and len(still) > 3 else NAN,
         "mem_target_woke": float(tp in f.get("woke", {}).get("_set", [])), "mem_n_woke": float(len(f.get("woke", {}).get("_set", []))),
         "mem_target_calm_known": float(dget(f.get("calm"), tp) is not None),
         "mem_since_target_swung_s": rel(dget(f.get("swung"), tp)),
         "mem_n_swung_1_5s": float(sum(1 for _, v in sw if isinstance(v, dict) and "_t" in v and -v["_t"] < 1.5)),
         "mem_since_swing_end_s": rel(f.get("_swing_end_t")), "mem_since_swing_aged_s": rel(f.get("_swing_aged")),
         "mem_since_stag_s": rel(f.get("_stag_t")),
         "mem_stag_is_target": (float(f["_stag_ptr"] == tp) if f.get("_stag_ptr") is not None else 0.0) if has("_stag_ptr") else NAN,
         "mem_target_drop_from_y0_m": (t["y"] - y0) if isinstance(y0, (int, float)) else NAN,
         "mem_limit_s": num(f.get("limit")), "mem_low_hp": num(f.get("low_hp")),
         "mem_wait_far": num(f.get("wait_far")), "mem_crowd_ok": num(f.get("crowd_ok")), "mem_wall_ok": num(f.get("wall_ok")),
         "mem_pulled": num(f.get("pulled")), "mem_arena_present": float(f.get("arena") is not None), "mem_orig_switched": float(f.get("orig_ptr") is not None),
         "mem_reflex_age_s": num(rx.get("age")), "mem_reflex_target_since_start_s": rel(next((v for k, v in st if k == tp), None)),
         "mem_reflex_n_start_1_3s": float(sum(1 for _, v in st if isinstance(v, dict) and "_t" in v and -v["_t"] < 1.3)),
         "mem_reflex_prefer_is_target": float(rx.get("prefer") == tp),
         "mem_care_wants": num(cr.get("wants")),
         "mem_aprev_anim": "__absent__" if not has("_aprev") else ("idle" if f["_aprev"] in (None, -1) else str(f["_aprev"]))}
    return m


MEM_NUM = [r[0] for r in cfg["inputs"]["memory_numeric"]]
MEM_CAT = [r[0] for r in cfg["inputs"]["memory_categorical"]]


class Enc:
    """Same rules as R.Encoder (min count 5, __rare__/__unknown__, NaN + __missing) for any column lists."""
    def __init__(self, num, nan_ok, cat): self.num, self.nan_ok, self.cat = num, nan_ok, cat
    def fit(self, F):
        self.vocab = {k: sorted(v for v, n in collections.Counter(f[k] for f in F).items() if n >= R.MIN_CAT) for k in self.cat}
        self.seen = {k: set(f[k] for f in F) for k in self.cat}
        self.cols = list(self.num) + [f"{k}__missing" for k in self.nan_ok]
        for k in self.cat: self.cols += [f"{k}={v}" for v in self.vocab[k]] + [f"{k}=__rare__", f"{k}=__unknown__"]
        return self
    def transform(self, F):
        idx = {c: i for i, c in enumerate(self.cols)}; M = np.zeros((len(F), len(self.cols))); unk = collections.Counter()
        for r, f in enumerate(F):
            for k in self.num: v = f[k]; M[r, idx[k]] = np.nan if v is None else v
            for k in self.nan_ok:
                v = f[k]; M[r, idx[f"{k}__missing"]] = 1.0 if (v is None or (isinstance(v, float) and math.isnan(v))) else 0.0
            for k in self.cat:
                v = f[k]
                if v in self.vocab[k]: M[r, idx[f"{k}={v}"]] = 1.0
                elif v in self.seen[k]: M[r, idx[f"{k}=__rare__"]] = 1.0
                else: M[r, idx[f"{k}=__unknown__"]] = 1.0; unk[k] += 1
        return M, dict(unk)


for x in X:
    x["_f1"] = R.features(x); x["_f2"] = {**x["_f1"], **memory(x)}
by = collections.defaultdict(list)
for x in X: by[x["split"]].append(x)
tr = by["train"]; ytr = [x["rule"] for x in tr]; tc = set(ytr)
evals = {e: by[e] for e in cfg["splits"]["eval"]}
for k, v in cfg["splits"]["extra_eval"].items(): evals[k] = [x for x in by[v["from"]] if x["run"] not in v["drop_runs"]]

# I1 with the original encoder, plus the generic encoder check (must give the same matrix)
e1 = R.Encoder().fit([x["_f1"] for x in tr]); X1tr, _ = e1.transform([x["_f1"] for x in tr])
g1 = Enc(R.NUM, R.NAN_OK, R.CAT).fit([x["_f1"] for x in tr]); G1tr, _ = g1.transform([x["_f1"] for x in tr])
enc_check = bool(g1.cols == e1.cols and np.array_equal(np.nan_to_num(G1tr, nan=-9e9), np.nan_to_num(X1tr, nan=-9e9)))
e2 = Enc(R.NUM + MEM_NUM, R.NAN_OK + MEM_NUM, R.CAT + MEM_CAT).fit([x["_f2"] for x in tr]); X2tr, _ = e2.transform([x["_f2"] for x in tr])
assert e2.cols[:len(R.NUM)] == R.NUM
params = cfg["model"]["params"]
m1 = R.make_model(rfcfg, params).fit(X1tr, ytr)
m2 = R.make_model(rfcfg, params).fit(X2tr, ytr)

old3 = {(p["run"], p["scene_seq"]): p["y_pred_c3"] for p in map(json.loads, open(c34 / "paired_predictions.jsonl", encoding="utf-8"))}
res = {"config_sha256": sha(a.config), "encoder_generic_equals_original_I1": enc_check,
       "columns": {"I1": len(e1.cols), "I2_memory": len(e2.cols), "I2_added": [c for c in e2.cols if c not in e1.cols]},
       "train": {"I1": R.metrics(tr, ytr, list(m1.predict(X1tr)), {}, tc), "I2_memory": R.metrics(tr, ytr, list(m2.predict(X2tr)), {}, tc)},
       "i1_repro": {}, "eval": {}}
rare = sorted(c for c, n in collections.Counter(ytr).items() if n <= 5)
res["rare_train_le5"] = rare
FOCUS = ["after_swing", "stagger_punish", "reflex", "stamina", "attack", "estus"]
preds = []
for en, rows in evals.items():
    A1, u1 = e1.transform([x["_f1"] for x in rows]); A2, u2 = e2.transform([x["_f2"] for x in rows])
    y = [x["rule"] for x in rows]; p1 = list(m1.predict(A1)); p2 = list(m2.predict(A2))
    mis = [(x["run"], x["scene_seq"]) for x, q in zip(rows, p1) if old3.get((x["run"], x["scene_seq"])) != q]
    res["i1_repro"][en] = {"n": len(rows), "mismatch_vs_preserved_c3": len(mis), "examples": mis[:5]}
    r1 = R.metrics(rows, y, p1, {"baseline_set": bl_sets.get(en)}, tc); r2 = R.metrics(rows, y, p2, {"baseline_set": bl_sets.get(en)}, tc)
    pc = collections.Counter(); runp = collections.defaultdict(collections.Counter)
    for x, t, q1, q2 in zip(rows, y, p1, p2):
        k = "both_correct" if q1 == t and q2 == t else "i1_only" if q1 == t else "i2_only" if q2 == t else "both_wrong"
        pc[k] += 1; pc["changed"] += (q1 != q2)
        rr = runp[x["run"]]; rr["n"] += 1; rr["changed"] += (q1 != q2); rr["i1_ok"] += (q1 == t); rr["i2_ok"] += (q2 == t)
        if en in cfg["splits"]["eval"]:
            preds.append(dict(run=x["run"], scene_seq=x["scene_seq"], split=x["split"], y_true=t, y_pred_i1=q1, y_pred_i2_memory=q2))
    focus = {}
    for c in FOCUS + rare:
        d1, d2 = r1["per_class"].get(c, {}), r2["per_class"].get(c, {})
        focus[c] = {"true_n": (d1 or d2).get("n", 0), "runs": (d1 or d2).get("runs", 0), "rare": c in rare,
                    "I1": {k: d1.get(k) for k in ("pred_n", "P", "R", "F1")}, "I2_memory": {k: d2.get(k) for k in ("pred_n", "P", "R", "F1")}}
    res["eval"][en] = {"n": len(rows), "runs": len({x["run"] for x in rows}), "unknown_categories": {"I1": u1, "I2_memory": u2},
                       "I1": r1, "I2_memory": r2, "paired": dict(pc), "per_run_paired": {k: dict(v) for k, v in sorted(runp.items())}, "focus": focus,
                       "labels": {"baseline_set": r1["baseline_set_classes"], "all_true": r1["all_true_classes"],
                                  "pred_only_I1": sorted(c for c, d in r1["per_class"].items() if d["n"] == 0),
                                  "pred_only_I2_memory": sorted(c for c, d in r2["per_class"].items() if d["n"] == 0)}}
res["feature_importance_I2_impurity_top30"] = dict(sorted(zip(e2.cols, [round(float(v), 4) for v in m2.feature_importances_]), key=lambda kv: -kv[1])[:30])
res["i2_memory_vocab"] = {k: e2.vocab[k] for k in MEM_CAT}
json.dump(res, open(out / "results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
with open(out / "predictions.jsonl", "w", encoding="utf-8") as fo:
    for p in preds: fo.write(json.dumps(p, ensure_ascii=False) + "\n")
print("enc_check", enc_check, "repro", {k: v["mismatch_vs_preserved_c3"] for k, v in res["i1_repro"].items()}, "cols", res["columns"]["I1"], res["columns"]["I2_memory"])
