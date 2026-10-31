"""Conditional reflex audit: recounts stored I1 / I2-memory predictions by (target staggered) x (other foe attacking < 2.5 m).
Standard library only; no model, no training, no prediction.

  python conditional_reflex_audit.py --config config.json --extract <g2_scene_extract.jsonl> --manifest <g2_scene_manifest_scenes.jsonl> \
      --predictions <experiments/g2_i1_vs_i2memory_c3_2026_10_31/predictions.jsonl> --out <dir>
"""
import argparse, collections, csv, hashlib, json, math
from pathlib import Path

ap = argparse.ArgumentParser()
for k in ("--config", "--extract", "--manifest", "--predictions", "--out"): ap.add_argument(k, required=True)
a = ap.parse_args()
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
cfg = json.load(open(a.config, encoding="utf-8"))
for key, p in (("extract_sha256", a.extract), ("manifest_sha256", a.manifest), ("predictions_sha256", a.predictions)):
    assert sha(p) == cfg["refs"][key], f"hash mismatch {p}"
out = Path(a.out)
STAGGER, ATTACK, HOST, R = range(3500, 3600), range(3000, 3500), {6, 7, 24, 25, 27, 33}, 2.5
X = {(x["run"], x["scene_seq"]): x for x in map(json.loads, open(a.extract, encoding="utf-8"))}
M = {(d["run"], d["scene_seq"]): d["split"] for d in map(json.loads, open(a.manifest, encoding="utf-8"))}
P = [json.loads(l) for l in open(a.predictions, encoding="utf-8")]
keys = [(p["run"], p["scene_seq"]) for p in P]
check = {"rows": len(P), "duplicates": len(keys) - len(set(keys)), "unlinked": sum(k not in X for k in keys),
         "split_mismatch": sum(1 for p in P if X[(p["run"], p["scene_seq"])]["split"] != p["split"] or M[(p["run"], p["scene_seq"])] != p["split"]),
         "y_true_mismatch": sum(1 for p in P if X[(p["run"], p["scene_seq"])]["rule"] != p["y_true"]),
         "pending": sum(p["split"] == "pending" for p in P), "splits": dict(collections.Counter(p["split"] for p in P))}
assert all(v == 0 for k, v in check.items() if k in ("duplicates", "unlinked", "split_mismatch", "y_true_mismatch", "pending"))


def cond(x):
    a_ = x["tick"]["a"]; A = a_ is not None and a_ in STAGGER
    p = x["snap"]["player"]; tp = x["tick"]["ptr"]
    near = [c for c in x["snap"]["chars"] if c["ptr"] != tp and c["team"] in HOST and (c["hp"] or 0) > 0
            and c["anim"] is not None and c["anim"] in ATTACK and math.hypot(c["x"] - p["x"], c["z"] - p["z"]) < R]
    return A, bool(near), len(near)


CLS = cfg["true_classes"]; RID = "20261019_212954_parish-group1"
rows = []
for p in P:
    x = X[(p["run"], p["scene_seq"])]
    A, B, nB = cond(x)
    rows.append({**p, "A_staggered": A, "B_other_attack": B, "n_other_attack": nB, "cell": f"{'stag' if A else 'nostag'}|{'other' if B else 'noother'}"})
CELLS = ["stag|other", "stag|noother", "nostag|other", "nostag|noother"]
disp = lambda r: r if r in CLS else "other"


def cell_stats(rs):
    n = len(rs); c1 = sum(r["y_pred_i1"] == r["y_true"] for r in rs); c2 = sum(r["y_pred_i2_memory"] == r["y_true"] for r in rs)
    b = sum(r["y_pred_i1"] == r["y_true"] and r["y_pred_i2_memory"] == r["y_true"] for r in rs)
    return {"n": n, "runs": len({r["run"] for r in rs}), "i1_correct": c1, "i1_recall": round(c1 / n, 4) if n else None,
            "i2_correct": c2, "i2_recall": round(c2 / n, 4) if n else None, "both_correct": b, "i1_only": c1 - b, "i2_only": c2 - b,
            "both_wrong": n - c1 - c2 + b, "i2_minus_i1": c2 - c1}


scopes = {"all": lambda r: True, "excl_212954": lambda r: r["run"] != RID, "only_212954": lambda r: r["run"] == RID}
res = {"config_sha256": sha(a.config), "join_check": check, "tables": {}, "transitions": {}, "per_run_core": [], "condition_counts": {}}
csv_rows = []
for sn, sf in scopes.items():
    res["tables"][sn] = {}; res["transitions"][sn] = {}
    for sp in cfg["splits"] + ["ALL_eval_supplementary"]:
        spf = (lambda r: True) if sp.startswith("ALL") else (lambda r, sp=sp: r["split"] == sp)
        res["tables"][sn][sp] = {}; res["transitions"][sn][sp] = {}
        for cl in CELLS:
            res["tables"][sn][sp][cl] = {}
            cr = [r for r in rows if sf(r) and spf(r) and r["cell"] == cl]
            for tc in CLS:
                st = cell_stats([r for r in cr if r["y_true"] == tc]); res["tables"][sn][sp][cl][tc] = st
                csv_rows.append({"scope": sn, "split": sp, "cell": cl, "true_class": tc, **st})
            tt = [r for r in cr if r["y_true"] in CLS]
            res["transitions"][sn][sp][cl] = {
                "raw": dict(collections.Counter(f"{r['y_true']}|{r['y_pred_i1']}|{r['y_pred_i2_memory']}" for r in tt).most_common()),
                "display": dict(collections.Counter(f"{r['y_true']}|{disp(r['y_pred_i1'])}|{disp(r['y_pred_i2_memory'])}" for r in tt).most_common())}
for sp in cfg["splits"]:
    res["condition_counts"][sp] = dict(collections.Counter(r["cell"] for r in rows if r["split"] == sp))
# per run, core cell
run_rows = []
for run in sorted({r["run"] for r in rows}):
    rs = [r for r in rows if r["run"] == run and r["cell"] == "stag|other" and r["y_true"] in CLS]
    if not rs: continue
    d = {"run": run, "split": rs[0]["split"]}
    for tc in CLS:
        st = cell_stats([r for r in rs if r["y_true"] == tc])
        d[f"{tc}_n"], d[f"{tc}_i1"], d[f"{tc}_i2"] = st["n"], st["i1_correct"], st["i2_correct"]
    d["total_n"] = len(rs); d["i1_correct"] = sum(r["y_pred_i1"] == r["y_true"] for r in rs); d["i2_correct"] = sum(r["y_pred_i2_memory"] == r["y_true"] for r in rs)
    d["transitions"] = dict(collections.Counter(f"{r['y_true']}|{r['y_pred_i1']}|{r['y_pred_i2_memory']}" for r in rs).most_common())
    run_rows.append(d)
res["per_run_core"] = run_rows
# consistency: all = excl + only, per split/cell/class
cons = []
for sp in cfg["splits"]:
    for cl in CELLS:
        for tc in CLS:
            A_, E_, O_ = (res["tables"][s][sp][cl][tc] for s in ("all", "excl_212954", "only_212954"))
            for k in ("n", "i1_correct", "i2_correct", "both_correct", "i1_only", "i2_only", "both_wrong"):
                if A_[k] != E_[k] + O_[k]: cons.append((sp, cl, tc, k))
tot = sum(res["tables"]["all"][sp][cl][tc]["n"] for sp in cfg["splits"] for cl in CELLS for tc in CLS)
res["consistency"] = {"all_equals_excl_plus_only_violations": cons,
                      "sum_cells_true3": tot, "true3_scenes_in_eval": sum(1 for r in rows if r["y_true"] in CLS)}
json.dump(res, open(out / "results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
with open(out / "condition_table.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys())); w.writeheader(); w.writerows(csv_rows)
with open(out / "per_run_core.csv", "w", newline="", encoding="utf-8") as f:
    fn = ["run", "split", "total_n", "i1_correct", "i2_correct"] + [f"{t}_{s}" for t in CLS for s in ("n", "i1", "i2")] + ["transitions"]
    w = csv.DictWriter(f, fieldnames=fn); w.writeheader()
    for d in run_rows: w.writerow({**{k: d[k] for k in fn if k != "transitions"}, "transitions": json.dumps(d["transitions"], ensure_ascii=False)})
print(json.dumps(check), res["consistency"]["all_equals_excl_plus_only_violations"], tot, res["consistency"]["true3_scenes_in_eval"])
