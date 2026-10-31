"""A = I1-current vs B = I1-current + target-stagger memory (6 columns), both RandomForest with max_features=None.

Two stages, kept apart on purpose:
  prepare  build the train/eval matrices and check them. No fit, no predict: RandomForestClassifier.fit / predict are patched
           to raise for the whole stage. Writes prep_report.json.
  train    (needs separate approval) --approved TRAINING-APPROVED. Fits A and B on train, predicts the 4 eval splits,
           writes results.json and predictions.jsonl. Refuses to run unless prep_report.json matches this config.

  PYTHONDONTWRITEBYTECODE=1 python stagmem_compare.py prepare --config config.json --rf-dir <experiments/g2_i1current_rf_2026_10_31> \
      --extract <g2_scene_extract.jsonl> --manifest <g2_scene_manifest_scenes.jsonl> --baseline-results <baseline results.json> \
      --cond-results <conditional_reflex/results.json> --out <dir>
  PYTHONDONTWRITEBYTECODE=1 python stagmem_compare.py train   ... same arguments ... --approved TRAINING-APPROVED
"""
import argparse, collections, hashlib, importlib.util, json, math, sys
from pathlib import Path

import numpy as np

NAN = float("nan")
STAGGER, ATTACK, HOST, THREAT_R = range(3500, 3600), range(3000, 3500), {6, 7, 24, 25, 27, 33}, 2.5
RID = "20261019_212954_parish-group1"
MEM = ["smem_active", "smem_is_target", "smem_target_since_s"]
MEM_COLS = [c for k in MEM for c in (k, f"{k}__missing")]
APPROVAL = "TRAINING-APPROVED"


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def stagmem(x):
    """(smem_active, smem_is_target, smem_target_since_s) from the Fight state captured before the rules; NaN = missing."""
    f, tp = x["fight"], x["tick"]["ptr"]
    if "_stag_ptr" not in f:
        return NAN, NAN, NAN                      # not recorded (pre-93dce7b code, or no prep_reflex yet in this fight)
    sp = f["_stag_ptr"]
    if sp is None:
        return 0.0, NAN, NAN                      # no active streak; a leftover _stag_t is NOT used
    if sp != tp:
        return 1.0, 0.0, NAN                      # streak belongs to another entity; its timer is NOT used
    st = f.get("_stag_t")
    since = -st["_t"] if isinstance(st, dict) and "_t" in st else NAN
    return 1.0, 1.0, since


def mem_block(rows):
    M = np.zeros((len(rows), len(MEM_COLS)))
    for r, x in enumerate(rows):
        for j, v in enumerate(stagmem(x)):
            miss = math.isnan(v)
            M[r, 2 * j] = np.nan if miss else v
            M[r, 2 * j + 1] = 1.0 if miss else 0.0
    return M


def cond(x):
    """Same definition as conditional_reflex_audit.py cond() @3a0064f."""
    a_ = x["tick"]["a"]; A = a_ is not None and a_ in STAGGER
    p = x["snap"]["player"]; tp = x["tick"]["ptr"]
    near = [c for c in x["snap"]["chars"] if c["ptr"] != tp and c["team"] in HOST and (c["hp"] or 0) > 0
            and c["anim"] is not None and c["anim"] in ATTACK and math.hypot(c["x"] - p["x"], c["z"] - p["z"]) < THREAT_R]
    return A, bool(near)


def same(a, b):
    return a.shape == b.shape and bool(np.array_equal(np.isnan(a), np.isnan(b))) and bool(np.array_equal(np.nan_to_num(a, nan=0.0), np.nan_to_num(b, nan=0.0)))


def setup(a):
    cfg = json.load(open(a.config, encoding="utf-8")); rf = Path(a.rf_dir); ref = cfg["refs"]
    for p, k in ((rf / "config.json", "rf_config_sha256"), (rf / "rf_i1current.py", "rf_script_sha256"), (a.baseline_results, "baseline_results_sha256"),
                 (a.extract, "extract_sha256"), (a.manifest, "manifest_sha256"), (a.cond_results, "cond_audit_results_sha256")):
        assert sha(p) == ref[k], f"hash mismatch {p}"
    spec = importlib.util.spec_from_file_location("rfi", rf / "rf_i1current.py"); R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
    rfcfg = json.load(open(rf / "config.json", encoding="utf-8"))
    X = R.load(argparse.Namespace(extract=a.extract, manifest=a.manifest), rfcfg)      # checks hashes again, drops pending
    assert not any(x["split"] in cfg["splits"]["exclude"] for x in X)
    for x in X: x["_f1"] = R.features(x)
    by = collections.defaultdict(list)
    for x in X: by[x["split"]].append(x)
    enc = R.Encoder().fit([x["_f1"] for x in by["train"]])                                # train only
    mats = {}
    for sp in ["train"] + cfg["splits"]["eval"]:
        A, unk = enc.transform([x["_f1"] for x in by[sp]])
        B = np.hstack([A, mem_block(by[sp])])
        mats[sp] = (A, B, unk)
    cols_A = list(enc.cols); cols_B = cols_A + MEM_COLS
    base = json.load(open(a.baseline_results, encoding="utf-8"))["variants"]["A_base"]["eval"]
    prim = {e: base[e]["lookup"]["primary_classes"] for e in cfg["splits"]["eval"]}
    return cfg, R, by, enc, mats, cols_A, cols_B, prim


def prepare(a, out):
    from sklearn.ensemble import RandomForestClassifier
    def refuse(*_a, **_k): raise RuntimeError("prepare stage: fit/predict are not allowed")
    RandomForestClassifier.fit = RandomForestClassifier.predict = RandomForestClassifier.predict_proba = refuse
    cfg, R, by, enc, mats, cols_A, cols_B, prim = setup(a)
    assert cfg["memory_features"]["encoded_columns"] == MEM_COLS and cfg["memory_features"]["n_added_columns"] == len(MEM_COLS)
    assert cfg["model"]["params"]["max_features"] is None
    tr = by["train"]; A, B, _ = mats["train"]
    rep = {"config_sha256": sha(a.config), "script_sha256": sha(__file__), "stage": "prepare (no fit / predict)",
           "n": {sp: len(by[sp]) for sp in by}, "pending_present": "pending" in by,
           "columns": {"A": len(cols_A), "B": len(cols_B), "added": MEM_COLS, "A_cols": cols_A},
           "checks": {}, "train": {}}
    ck = rep["checks"]
    ck["B_prefix_equals_A"] = {sp: same(mats[sp][1][:, :len(cols_A)], mats[sp][0]) for sp in mats}
    ck["shape"] = {sp: [list(mats[sp][0].shape), list(mats[sp][1].shape)] for sp in mats}
    ck["value_nan_iff_missing_flag"] = {sp: all(bool(np.array_equal(np.isnan(mats[sp][1][:, len(cols_A) + 2 * j]), mats[sp][1][:, len(cols_A) + 2 * j + 1] == 1.0))
                                                for j in range(len(MEM))) for sp in mats}
    ck["missing_flags_have_no_nan"] = {sp: not bool(np.isnan(mats[sp][1][:, len(cols_A) + 1::2]).any()) for sp in mats}
    # reproduce the conditional-audit cell counts on the eval splits (consistency with the preserved audit only)
    cres = json.load(open(a.cond_results, encoding="utf-8"))["condition_counts"]
    cells = {sp: dict(collections.Counter(f"{'stag' if A_ else 'nostag'}|{'other' if B_ else 'noother'}" for A_, B_ in map(cond, by[sp]))) for sp in cfg["splits"]["eval"]}
    ck["core_condition_counts_equal_preserved_audit"] = {sp: cells[sp] == cres[sp] for sp in cfg["splits"]["eval"]}
    # train-only description of the memory states (used to fix the definition; eval distributions are not reported)
    def state(x):
        f, tp = x["fight"], x["tick"]["ptr"]
        if "_stag_ptr" not in f: return "key_absent"
        return "none" if f["_stag_ptr"] is None else ("target" if f["_stag_ptr"] == tp else "other")
    st = collections.Counter(state(x) for x in tr)
    stale = sum(1 for x in tr if state(x) == "none" and isinstance(x["fight"].get("_stag_t"), dict))
    since = [v[2] for v in map(stagmem, tr) if not math.isnan(v[2])]
    cur_stag = collections.Counter((state(x), x["tick"]["a"] is not None and x["tick"]["a"] in STAGGER) for x in tr)
    rule_by_state = {s: dict(collections.Counter(x["rule"] for x in tr if state(x) == s).most_common()) for s in st}
    runs_with_key = sorted({x["run"] for x in tr if "_stag_ptr" in x["fight"]})
    rep["train"] = {"state_counts": dict(st), "none_with_leftover_stag_t_not_used": stale,
                    "state_x_current_target_staggered": {f"{k[0]}|{'stag' if k[1] else 'nostag'}": v for k, v in sorted(cur_stag.items())},
                    "smem_target_since_s": {"n": len(since), "min": round(min(since), 4), "median": round(float(np.median(since)), 4), "max": round(max(since), 4), "negative": sum(v < 0 for v in since)},
                    "rule_by_state": rule_by_state, "runs_with_key": runs_with_key, "n_runs_with_key": len(runs_with_key),
                    "missing_rate": {c: round(float(B[:, len(cols_A) + 2 * j + 1].mean()), 4) for j, c in enumerate(MEM)},
                    "nonmissing_values": {c: dict(collections.Counter(float(v) for v in B[:, len(cols_A) + 2 * j] if not np.isnan(v))) for j, c in enumerate(MEM[:2])}}
    ck["generic_since_matches_raw_on_train"] = all(abs(v - (-x["fight"]["_stag_t"]["_t"])) < 1e-12 for x, v in ((x, stagmem(x)[2]) for x in tr) if not math.isnan(v))
    ck["eval_unknown_categories_count_only"] = {sp: sum(mats[sp][2].values()) for sp in cfg["splits"]["eval"]}
    rep["primary_class_sets"] = prim
    rep["model_params"] = cfg["model"]["params"]
    BOOL = ["B_prefix_equals_A", "value_nan_iff_missing_flag", "missing_flags_have_no_nan", "core_condition_counts_equal_preserved_audit"]
    rep["all_checks_pass"] = all(all(ck[k].values()) for k in BOOL) and ck["generic_since_matches_raw_on_train"] \
        and rep["train"]["smem_target_since_s"]["negative"] == 0 and not rep["pending_present"]
    json.dump(rep, open(out / "prep_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"columns": rep["columns"]["A"], "B": rep["columns"]["B"], "all_checks_pass": rep["all_checks_pass"], "train_states": rep["train"]["state_counts"]}))


def train(a, out):
    from sklearn.ensemble import RandomForestClassifier
    prep = json.load(open(out / "prep_report.json", encoding="utf-8"))
    assert prep["config_sha256"] == sha(a.config) and prep["script_sha256"] == sha(__file__) and prep["all_checks_pass"], "prepare first, unchanged"
    cfg, R, by, enc, mats, cols_A, cols_B, prim = setup(a)
    tr = by["train"]; ytr = [x["rule"] for x in tr]; tc = set(ytr)
    mA = RandomForestClassifier(**cfg["model"]["params"]).fit(mats["train"][0], ytr)
    mB = RandomForestClassifier(**cfg["model"]["params"]).fit(mats["train"][1], ytr)
    DIAG = cfg["evaluation"]["diagnostic_classes"]; CORE = cfg["evaluation"]["core_condition"]["classes"]
    res = {"config_sha256": sha(a.config), "prep_report_sha256": sha(out / "prep_report.json"), "columns": prep["columns"],
           "train": {"A": R.metrics(tr, ytr, list(mA.predict(mats["train"][0])), {}, tc), "B": R.metrics(tr, ytr, list(mB.predict(mats["train"][1])), {}, tc)},
           "eval": {}, "core": {}}
    preds, allrows = [], []
    for sp in cfg["splits"]["eval"]:
        rows = by[sp]; y = [x["rule"] for x in rows]
        pa = list(mA.predict(mats[sp][0])); pb = list(mB.predict(mats[sp][1]))
        rA = R.metrics(rows, y, pa, {"primary": prim[sp]}, tc); rB = R.metrics(rows, y, pb, {"primary": prim[sp]}, tc)
        pc = collections.Counter(); runp = collections.defaultdict(collections.Counter)
        for x, t, p, q in zip(rows, y, pa, pb):
            k = "both_correct" if p == t and q == t else "A_only" if p == t else "B_only" if q == t else "both_wrong"
            pc[k] += 1; runp[x["run"]][k] += 1
            A_, B_ = cond(x)
            r = dict(run=x["run"], scene_seq=x["scene_seq"], split=sp, y_true=t, y_pred_A=p, y_pred_B=q, core=A_ and B_)
            preds.append(r); allrows.append(r)
        res["eval"][sp] = {"n": len(rows), "runs": len({x["run"] for x in rows}), "unknown_categories": mats[sp][2], "A": rA, "B": rB,
                           "labels": {"primary": rA["primary_classes"], "all_true": rA["all_true_classes"]},
                           "diagnostic": {c: {"A": rA["per_class"].get(c), "B": rB["per_class"].get(c)} for c in DIAG},
                           "paired": dict(pc), "per_run_paired": {k: dict(v) for k, v in sorted(runp.items())}}

    def cell(rs):
        n = len(rs); ca = sum(r["y_pred_A"] == r["y_true"] for r in rs); cb = sum(r["y_pred_B"] == r["y_true"] for r in rs)
        b = sum(r["y_pred_A"] == r["y_true"] and r["y_pred_B"] == r["y_true"] for r in rs)
        return {"n": n, "runs": len({r["run"] for r in rs}), "A_correct": ca, "A_recall": round(ca / n, 4) if n else None,
                "B_correct": cb, "B_recall": round(cb / n, 4) if n else None, "both_correct": b, "A_only": ca - b, "B_only": cb - b,
                "both_wrong": n - ca - cb + b,
                "transitions": dict(collections.Counter(f"{r['y_true']}|{r['y_pred_A']}|{r['y_pred_B']}" for r in rs).most_common())}
    scopes = {"all": lambda r: True, "excl_212954": lambda r: r["run"] != RID}
    for sn, sf in scopes.items():
        res["core"][sn] = {}
        for sp in cfg["splits"]["eval"] + ["ALL_eval_supplementary"]:
            rs = [r for r in allrows if r["core"] and sf(r) and (sp.startswith("ALL") or r["split"] == sp)]
            res["core"][sn][sp] = {c: cell([r for r in rs if r["y_true"] == c]) for c in CORE}
    json.dump(res, open(out / "results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(out / "predictions.jsonl", "w", encoding="utf-8") as fo:
        for r in preds: fo.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({sp: {"A": res["eval"][sp]["A"]["acc"], "B": res["eval"][sp]["B"]["acc"]} for sp in cfg["splits"]["eval"]}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["prepare", "train"])
    for k in ("--config", "--rf-dir", "--extract", "--manifest", "--baseline-results", "--cond-results", "--out"): ap.add_argument(k, required=True)
    ap.add_argument("--approved", default=None, help=f"train stage only: must be {APPROVAL}")
    a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    if a.stage == "prepare":
        prepare(a, out)
    else:
        if a.approved != APPROVAL:
            sys.exit(f"train stage needs --approved {APPROVAL} (separate approval)")
        train(a, out)


if __name__ == "__main__":
    main()
