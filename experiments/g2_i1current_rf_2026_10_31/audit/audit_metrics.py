"""Recount from existing files only (no training, no prediction). args: extract baseline_results rf_results rf_predictions out_json"""
import json, sys, collections
ext, bl, rf, pr, out = sys.argv[1:6]
X = [json.loads(l) for l in open(ext, encoding="utf-8")]
B = json.load(open(bl, encoding="utf-8"))["variants"]["A_base"]["eval"]
R = json.load(open(rf, encoding="utf-8"))["variants"]["base"]["eval"]
P = [json.loads(l) for l in open(pr, encoding="utf-8") if json.loads(l)["variant"] == "base"]
res = {}
for en in ["val", "test", "shift_zone", "shift_ref"]:
    rows = [x for x in X if x["split"] == en]
    sup = collections.Counter(x["rule"] for x in rows)
    runs = collections.defaultdict(set)
    for x in rows: runs[x["rule"]].add(x["run"])
    pp = [p for p in P if p["split"] == en]
    ytrue_ext = {(x["run"], x["scene_seq"]): x["rule"] for x in rows}
    ytrue_pred = {(p["run"], p["scene_seq"]): p["y_true"] for p in pp}
    bl_lk = B[en]["lookup"]; bl_mj = B[en]["majority"]
    bl_keys = sorted(bl_lk["per_class"]); bl_true = sorted(c for c, d in bl_lk["per_class"].items() if d["n"] >= 1)
    bl_predonly = sorted(c for c, d in bl_lk["per_class"].items() if d["n"] == 0)
    rf_keys = sorted(R[en]["per_class"]); rf_true = R[en]["all_true_classes"]
    rf_predonly = sorted(c for c, d in R[en]["per_class"].items() if d["n"] == 0)
    bl_n = {c: d["n"] for c, d in bl_lk["per_class"].items() if d["n"] >= 1}
    rf_n = {c: d["n"] for c, d in R[en]["per_class"].items() if d["n"] >= 1}
    bl_runs_n = {k: v["n"] for k, v in bl_lk["per_run"].items()}
    rf_runs_n = {k: v["n"] for k, v in R[en]["per_run"].items()}
    # recount macro F1 over the exact baseline primary set from the RF per-class F1 (recomputed from predictions)
    def f1s(pairs, labels):
        out = {}
        for c in labels:
            tp = sum(1 for a, b in pairs if a == c and b == c); fp = sum(1 for a, b in pairs if a != c and b == c); fn = sum(1 for a, b in pairs if a == c and b != c)
            p_ = tp / (tp + fp) if tp + fp else 0.0; r_ = tp / (tp + fn) if tp + fn else 0.0
            out[c] = round(2 * p_ * r_ / (p_ + r_), 3) if p_ + r_ else 0.0
        return out
    pairs = [(p["y_true"], p["y_pred"]) for p in pp]
    prim = bl_lk["primary_classes"]; f_prim = f1s(pairs, prim); f_all = f1s(pairs, sorted(sup))
    union = sorted(set(sup) | {p["y_pred"] for p in pp})
    res[en] = {
        "y_true_from_extract": {"n": len(rows), "n_classes": len(sup), "support": dict(sup.most_common()), "runs_per_class": {c: len(v) for c, v in runs.items()}},
        "baseline_lookup": {"per_class_keys_n": len(bl_keys), "true_classes": bl_true, "n_true_classes_field": bl_lk.get("n_true_classes"),
                            "pred_only_classes": bl_predonly, "macro_f1_all_true": bl_lk["macro_f1_all_true"], "primary_classes": prim,
                            "majority_n_true_classes_field": bl_mj.get("n_true_classes")},
        "rf": {"per_class_keys_n": len(rf_keys), "all_true_classes": rf_true, "pred_only_classes": rf_predonly,
               "macro_f1_all_true": R[en]["macro_f1_all_true"], "baseline_set_classes": R[en].get("baseline_set_classes"), "macro_f1_baseline_set": R[en].get("macro_f1_baseline_set")},
        "union_true_or_pred_rf": {"n": len(union), "classes": union},
        "checks": {
            "baseline_true_classes == extract": bl_true == sorted(sup),
            "rf_true_classes == extract": rf_true == sorted(sup),
            "baseline_support == extract": bl_n == dict(sup),
            "rf_support == extract": rf_n == dict(sup),
            "rf predictions (run,scene_seq,y_true) == extract": ytrue_pred == ytrue_ext,
            "baseline per_run n == rf per_run n": bl_runs_n == rf_runs_n,
            "rf baseline_set_classes == baseline primary_classes": sorted(R[en].get("baseline_set_classes") or []) == sorted(prim)},
        "recount_from_predictions": {"note": "NEW recount from predictions.jsonl (variant base), not a rerun",
            "macro_f1_baseline_primary_set": round(sum(f_prim.values()) / len(prim), 4) if prim else None, "labels_primary": prim,
            "macro_f1_true_classes": round(sum(f_all.values()) / len(sup), 4), "labels_true": sorted(sup), "per_class_f1_true": f_all}}
json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for en, r in res.items():
    print(en, "extract classes", r["y_true_from_extract"]["n_classes"], "bl true", len(r["baseline_lookup"]["true_classes"]), "bl field", r["baseline_lookup"]["n_true_classes_field"],
          "bl predonly", r["baseline_lookup"]["pred_only_classes"], "rf true", len(r["rf"]["all_true_classes"]), "rf predonly", r["rf"]["pred_only_classes"], "union", r["union_true_or_pred_rf"]["n"])
    print("   checks", r["checks"]); print("   recount", r["recount_from_predictions"]["macro_f1_baseline_primary_set"], r["recount_from_predictions"]["macro_f1_true_classes"], "| reported rf", r["rf"]["macro_f1_baseline_set"], r["rf"]["macro_f1_all_true"])
print("val reflex support", res["val"]["y_true_from_extract"]["support"].get("reflex"))
