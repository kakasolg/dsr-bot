"""C3 vs C4 class_weight diagnostic (no tuning). Reuses the committed I1-current script's functions unchanged.

  python c3_c4_diag.py --diag-config diag_config.json --rf-dir <experiments/g2_i1current_rf_2026_10_31> \
      --extract <g2_scene_extract.jsonl> --manifest <g2_scene_manifest_scenes.jsonl> --baseline-results <baseline results.json> --out <dir>
"""
import argparse, collections, hashlib, importlib.util, json, sys
from pathlib import Path


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


ap = argparse.ArgumentParser()
for k in ("--diag-config", "--rf-dir", "--extract", "--manifest", "--baseline-results", "--out"): ap.add_argument(k, required=True)
a = ap.parse_args()
out = Path(a.out); rf = Path(a.rf_dir)
dc = json.load(open(a.diag_config, encoding="utf-8"))
for f, h in dc["refs"]["rf_sha256"].items():
    assert sha(rf / f) == h, f"hash mismatch {f}"
assert sha(a.extract) == dc["refs"]["extract_sha256"] and sha(a.manifest) == dc["refs"]["manifest_sha256"] and sha(a.baseline_results) == dc["refs"]["baseline_results_sha256"]
spec = importlib.util.spec_from_file_location("rfi", rf / "rf_i1current.py"); R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
cfg = json.load(open(rf / "config.json", encoding="utf-8"))
cand = json.load(open(rf / "candidates.json", encoding="utf-8"))
base_bl = json.load(open(a.baseline_results, encoding="utf-8"))["variants"]["A_base"]["eval"]
bl_sets = {e: v["lookup"]["primary_classes"] for e, v in base_bl.items()}

ns = argparse.Namespace(extract=a.extract, manifest=a.manifest)
X = R.load(ns, cfg)
for x in X: x["_f"] = R.features(x)
by = collections.defaultdict(list)
for x in X: by[x["split"]].append(x)
evals = {e: by[e] for e in dc["splits"]["eval"]}
for k, v in dc["splits"]["extra_eval"].items(): evals[k] = [x for x in by[v["from"]] if x["run"] not in v["drop_runs"]]
tr = by["train"]; ytr = [x["rule"] for x in tr]; tc = set(ytr)
enc = R.Encoder().fit([x["_f"] for x in tr]); Xtr, _ = enc.transform([x["_f"] for x in tr])
m3 = R.make_model(cfg, dc["conditions"]["C3"]).fit(Xtr, ytr)

def ev(rows, yp, en):
    y = [x["rule"] for x in rows]
    return R.metrics(rows, y, yp, {"baseline_set": bl_sets.get(en)}, tc)

res = {"diag_config_sha256": sha(a.diag_config), "repro": {}, "eval": {}}
# reproduction check against candidates.json C3 (stored precision)
c3_old = cand["candidates"]["C3"]
pred3 = {}
for sp in ("train", "val"):
    rows = by[sp]; Xs, _ = enc.transform([x["_f"] for x in rows]); yp = list(m3.predict(Xs)); pred3[sp] = yp
    new = ev(rows, yp, sp) if sp == "val" else R.metrics(rows, [x["rule"] for x in rows], yp, {}, tc)
    old = c3_old[sp]
    mism = []
    for k in ("acc", "macro_f1_all_true"):
        if round(new[k], 4) != round(old[k], 4): mism.append((k, old[k], new[k]))
    for c, d in old["per_class"].items():
        nd = new["per_class"].get(c)
        for k in ("n", "pred_n", "P", "R", "F1"):
            if nd is None or nd[k] != d[k]: mism.append((f"{c}.{k}", d[k], None if nd is None else nd[k]))
    if set(new["per_class"]) != set(old["per_class"]): mism.append(("class_keys", sorted(old["per_class"]), sorted(new["per_class"])))
    res["repro"][sp] = {"match": not mism, "mismatches": mism[:50], "old": {k: old[k] for k in ("acc", "macro_f1_all_true")}, "new": {k: new[k] for k in ("acc", "macro_f1_all_true")}}

# C4: existing predictions (variant base)
P4 = {(p["run"], p["scene_seq"]): p for p in map(json.loads, open(rf / "predictions.jsonl", encoding="utf-8")) if p["variant"] == "base"}
train_support = collections.Counter(ytr)
rare = sorted(c for c, n in train_support.items() if n <= 5)
res["rare_classes_train_le5"] = {c: train_support[c] for c in rare}
res["train_support"] = dict(train_support.most_common())
rows_out = []
for en, rows in evals.items():
    Xe, unk = enc.transform([x["_f"] for x in rows]); y3 = list(m3.predict(Xe))
    y4 = [P4[(x["run"], x["scene_seq"])]["y_pred"] for x in rows]
    yt = [x["rule"] for x in rows]
    assert all(P4[(x["run"], x["scene_seq"])]["y_true"] == t for x, t in zip(rows, yt))
    e3, e4 = ev(rows, y3, en), ev(rows, y4, en)
    pc = collections.Counter()
    run_ch = collections.defaultdict(lambda: collections.Counter())
    for x, t, p3, p4 in zip(rows, yt, y3, y4):
        k = "both_correct" if p3 == t and p4 == t else "c3_only" if p3 == t else "c4_only" if p4 == t else "both_wrong"
        pc[k] += 1; pc["changed"] += (p3 != p4)
        rc = run_ch[x["run"]]; rc["n"] += 1; rc["changed"] += (p3 != p4); rc["c3_ok"] += (p3 == t); rc["c4_ok"] += (p4 == t); rc[k] += 1
        if en in dc["splits"]["eval"]:
            rows_out.append(dict(run=x["run"], scene_seq=x["scene_seq"], split=x["split"], y_true=t, y_pred_c3=p3, y_pred_c4=p4, c4_source="rf predictions.jsonl variant=base"))
    focus = {}
    for c in dc["paired"]["focus_classes"] + [r for r in rare if r not in dc["paired"]["focus_classes"]]:
        d3, d4 = e3["per_class"].get(c, {}), e4["per_class"].get(c, {})
        idx = [i for i, t in enumerate(yt) if t == c]
        focus[c] = {"train_support": train_support.get(c, 0), "rare": c in rare, "true_n": len(idx), "runs": (d3 or d4).get("runs", 0),
                    "C3": {k: d3.get(k) for k in ("pred_n", "P", "R", "F1")}, "C4": {k: d4.get(k) for k in ("pred_n", "P", "R", "F1")},
                    "true_scenes_c3_only": sum(1 for i in idx if y3[i] == c and y4[i] != c), "true_scenes_c4_only": sum(1 for i in idx if y4[i] == c and y3[i] != c)}
    res["eval"][en] = {"n": len(rows), "runs": len({x["run"] for x in rows}), "unknown_categories": unk, "C3": e3, "C4": e4,
                       "paired": dict(pc), "per_run_paired": {k: {kk: v[kk] for kk in ("n", "changed", "c3_ok", "c4_ok", "both_correct", "c3_only", "c4_only", "both_wrong")} for k, v in sorted(run_ch.items())},
                       "focus": focus,
                       "labels": {"macro_f1_baseline_set": e3["baseline_set_classes"], "macro_f1_all_true": e3["all_true_classes"],
                                  "pred_only_C3": sorted(c for c, d in e3["per_class"].items() if d["n"] == 0),
                                  "pred_only_C4": sorted(c for c, d in e4["per_class"].items() if d["n"] == 0)}}
json.dump(res, open(out / "diag_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
with open(out / "paired_predictions.jsonl", "w", encoding="utf-8") as f:
    for r in rows_out: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("repro", {k: v["match"] for k, v in res["repro"].items()})
