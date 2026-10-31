"""M = A + raw-key recording flags (_stag_ptr / _stag_t key present), compared with the STORED A and B predictions.

  prepare  matrices and checks only; RandomForestClassifier.fit / predict are patched to raise. Writes prep_report_M.json.
  train    needs --approved TRAINING-APPROVED-M. Fits M only (A, B are reused from /tmp/stagmem/run), writes results_M.json,
           predictions_M.jsonl into --out.

  PYTHONDONTWRITEBYTECODE=1 python stagmem_m.py prepare --config config.json --stagmem-dir /tmp/stagmem --audit-rows /tmp/spaudit_consts/rows.json \
      --rf-dir <experiments/g2_i1current_rf_2026_10_31> --extract <...extract.jsonl> --manifest <...manifest_scenes.jsonl> \
      --baseline-results <baseline results.json> --cond-results /tmp/stagmem/cond/results.json --out <dir>
"""
import argparse, collections, hashlib, importlib.util, json, sys
from pathlib import Path

import numpy as np

APPROVAL = "TRAINING-APPROVED-M"
M_COLS = ["rec_stag_ptr_key", "rec_stag_t_key"]
RID = "20261019_212954_parish-group1"


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def m_block(rows):
    return np.array([[float("_stag_ptr" in x["fight"]), float("_stag_t" in x["fight"])] for x in rows]).reshape(len(rows), 2)


def load(a):
    cfg = json.load(open(a.config, encoding="utf-8")); ref = cfg["refs"]; sd = Path(a.stagmem_dir)
    checks = {"stagmem_config": sha(sd / "prep/config.json") == ref["stagmem_config_sha256"],
              "stagmem_script": sha(sd / "prep/stagmem_compare.py") == ref["stagmem_script_sha256"],
              "stagmem_prep_report": sha(sd / "prep/prep_report.json") == ref["stagmem_prep_report_sha256"],
              "stagmem_results": sha(sd / "run/results.json") == ref["stagmem_results_sha256"],
              "stagmem_predictions": sha(sd / "run/predictions.jsonl") == ref["stagmem_predictions_sha256"],
              "audit_rows": sha(a.audit_rows) == ref["branch_audit_rows_sha256"]}
    assert all(checks.values()), checks
    spec = importlib.util.spec_from_file_location("smc", sd / "prep/stagmem_compare.py"); S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
    sa = argparse.Namespace(config=str(sd / "prep/config.json"), rf_dir=a.rf_dir, extract=a.extract, manifest=a.manifest,
                            baseline_results=a.baseline_results, cond_results=a.cond_results)
    scfg, R, by, enc, mats, cols_A, cols_B, prim = S.setup(sa)        # same loading, hash checks, encoder as the stored A/B
    assert scfg["model"]["params"] == cfg["model"]["params"]
    MM = {sp: np.hstack([mats[sp][0], m_block(by[sp])]) for sp in mats}
    stored = {(p["run"], p["scene_seq"]): p for p in map(json.loads, open(sd / "run/predictions.jsonl", encoding="utf-8"))}
    sres = json.load(open(sd / "run/results.json", encoding="utf-8"))
    audit = json.load(open(a.audit_rows, encoding="utf-8"))
    return cfg, S, R, by, mats, MM, cols_A, prim, stored, sres, audit, checks


def audited_sets(audit, stored):
    ev = [r for r in audit if r["split"] != "train"]
    key = lambda r: (r["run"], r["seq"])
    late = [r for r in ev if r["branch"] == "late_guard"]
    gain = [r for r in late if stored[key(r)]["y_pred_A"] != "stagger_punish" and stored[key(r)]["y_pred_B"] == "stagger_punish"]
    return {"late_guard_95": [key(r) for r in late], "gain_35": [key(r) for r in gain],
            "boundary_7": [key(r) for r in late if r["margin"] is not None and r["margin"] < 0.05],
            "core_24": [key(r) for r in late if r["core"]], "strike_1": [key(r) for r in ev if r["branch"] == "strike"]}


def same(a, b): return a.shape == b.shape and bool(np.array_equal(np.isnan(a), np.isnan(b))) and bool(np.array_equal(np.nan_to_num(a), np.nan_to_num(b)))


def prepare(a, out):
    from sklearn.ensemble import RandomForestClassifier
    def refuse(*_a, **_k): raise RuntimeError("prepare stage: fit/predict are not allowed")
    RandomForestClassifier.fit = RandomForestClassifier.predict = RandomForestClassifier.predict_proba = refuse
    cfg, S, R, by, mats, MM, cols_A, prim, stored, sres, audit, checks = load(a)
    ev = cfg["splits"]["eval"]
    ck = {"refs": checks}
    ck["M_prefix_equals_A"] = {sp: same(MM[sp][:, :len(cols_A)], mats[sp][0]) for sp in MM}
    ck["M_prefix_equals_stored_B_prefix"] = {sp: same(MM[sp][:, :len(cols_A)], mats[sp][1][:, :len(cols_A)]) for sp in MM}
    ck["M_cols_binary_no_nan"] = {sp: bool(np.isin(MM[sp][:, len(cols_A):], [0.0, 1.0]).all()) for sp in MM}
    ck["shape"] = {sp: list(MM[sp].shape) for sp in MM}
    tr = by["train"]
    combo = lambda rows: dict(collections.Counter(f"ptr{int('_stag_ptr' in x['fight'])}_t{int('_stag_t' in x['fight'])}" for x in rows))
    ck["train_key_combos"] = combo(tr)
    ck["keys_identical_on_train"] = all(("_stag_ptr" in x["fight"]) == ("_stag_t" in x["fight"]) for x in tr)
    # stored predictions: join + recompute stored metrics (no prediction made)
    keys = {sp: [(x["run"], x["scene_seq"]) for x in by[sp]] for sp in ev}
    ck["stored_join"] = {sp: all(k in stored and stored[k]["split"] == sp and stored[k]["y_true"] == x["rule"] for k, x in zip(keys[sp], by[sp])) for sp in ev}
    ck["stored_rows"] = len(stored)
    tc = set(x["rule"] for x in tr)
    ck["stored_metrics_recomputed_equal"] = {}
    for sp in ev:
        y = [x["rule"] for x in by[sp]]
        for m, col in (("A", "y_pred_A"), ("B", "y_pred_B")):
            r = R.metrics(by[sp], y, [stored[k][col] for k in keys[sp]], {"primary": prim[sp]}, tc)
            s = sres["eval"][sp][m]
            ck["stored_metrics_recomputed_equal"][f"{sp}_{m}"] = all(r[k] == s[k] for k in ("acc", "macro_f1_primary", "macro_f1_all_true", "per_run_unweighted_mean_acc"))
    sets = audited_sets(audit, stored)
    ck["audited_set_sizes"] = {k: len(v) for k, v in sets.items()}
    ck["audited_sets_in_eval"] = all(k in stored for v in sets.values() for k in v)
    rec = {sp: dict(collections.Counter(("recorded" if "_stag_ptr" in x["fight"] else "not_recorded") for x in by[sp])) for sp in ev}
    rec_runs = {sp: {g: len({x["run"] for x in by[sp] if (("_stag_ptr" in x["fight"]) == (g == "recorded"))}) for g in ("recorded", "not_recorded")} for sp in ev}
    expect_sizes = {"late_guard_95": 95, "gain_35": 35, "boundary_7": 7, "core_24": 24, "strike_1": 1}
    ok = (all(ck["M_prefix_equals_A"].values()) and all(ck["M_prefix_equals_stored_B_prefix"].values()) and all(ck["M_cols_binary_no_nan"].values())
          and not ck["keys_identical_on_train"] and all(ck["stored_join"].values()) and ck["stored_rows"] == 723
          and all(ck["stored_metrics_recomputed_equal"].values()) and ck["audited_set_sizes"] == expect_sizes and ck["audited_sets_in_eval"])
    rep = {"config_sha256": sha(a.config), "script_sha256": sha(__file__), "stage": "prepare (no fit / predict)",
           "columns": {"A": len(cols_A), "M": len(cols_A) + len(M_COLS), "added": M_COLS}, "checks": ck,
           "eval_recorded_counts_scenes": rec, "eval_recorded_counts_runs": rec_runs,
           "audited_sets": {k: [list(t) for t in v] for k, v in sets.items()}, "primary_class_sets": prim, "all_checks_pass": ok}
    json.dump(rep, open(out / "prep_report_M.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"all_checks_pass": ok, "columns": rep["columns"], "train_key_combos": ck["train_key_combos"], "sets": ck["audited_set_sizes"], "eval_recorded": rec}))


def pair(rs, c1, c2):
    k = collections.Counter("both" if r[c1] == r["y_true"] and r[c2] == r["y_true"] else "first_only" if r[c1] == r["y_true"]
                            else "second_only" if r[c2] == r["y_true"] else "both_wrong" for r in rs)
    return dict(k)


def train(a, out):
    from sklearn.ensemble import RandomForestClassifier
    prep = json.load(open(out / "prep_report_M.json", encoding="utf-8"))
    assert prep["config_sha256"] == sha(a.config) and prep["script_sha256"] == sha(__file__) and prep["all_checks_pass"], "prepare first, unchanged"
    cfg, S, R, by, mats, MM, cols_A, prim, stored, sres, audit, _ = load(a)
    ev = cfg["splits"]["eval"]; tr = by["train"]; ytr = [x["rule"] for x in tr]; tc = set(ytr)
    mM = RandomForestClassifier(**cfg["model"]["params"]).fit(MM["train"], ytr)
    res = {"config_sha256": sha(a.config), "prep_report_M_sha256": sha(out / "prep_report_M.json"),
           "train_M": R.metrics(tr, ytr, list(mM.predict(MM["train"])), {}, tc), "eval": {}, "recorded": {}, "audited": {}}
    allr = []
    for sp in ev:
        rows = by[sp]; y = [x["rule"] for x in rows]; pm = list(mM.predict(MM[sp]))
        rr = []
        for x, t, q in zip(rows, y, pm):
            s = stored[(x["run"], x["scene_seq"])]
            rr.append(dict(run=x["run"], scene_seq=x["scene_seq"], split=sp, y_true=t, y_pred_A=s["y_pred_A"], y_pred_M=q, y_pred_B=s["y_pred_B"],
                           ptr_key="_stag_ptr" in x["fight"], t_key="_stag_t" in x["fight"]))
        allr += rr
        met = {m: R.metrics(rows, y, [r[f"y_pred_{m}"] for r in rr], {"primary": prim[sp]}, tc) for m in ("A", "M", "B")}
        runs = sorted({r["run"] for r in rr})
        res["eval"][sp] = {"n": len(rows), "runs": len(runs), "metrics": met,
                           "labels": {"primary": met["A"]["primary_classes"], "all_true": met["A"]["all_true_classes"]},
                           "paired": {"A_M": pair(rr, "y_pred_A", "y_pred_M"), "M_B": pair(rr, "y_pred_M", "y_pred_B"), "A_B": pair(rr, "y_pred_A", "y_pred_B")},
                           "per_run_paired": {run: {"A_M": pair([r for r in rr if r["run"] == run], "y_pred_A", "y_pred_M"),
                                                    "M_B": pair([r for r in rr if r["run"] == run], "y_pred_M", "y_pred_B")} for run in runs}}
        res["recorded"][sp] = {}
        for g, f in (("recorded", lambda r: r["ptr_key"]), ("not_recorded", lambda r: not r["ptr_key"]),
                     ("ptr1_t1", lambda r: r["ptr_key"] and r["t_key"]), ("ptr1_t0", lambda r: r["ptr_key"] and not r["t_key"])):
            q = [r for r in rr if f(r)]
            res["recorded"][sp][g] = {"n": len(q), "runs": len({r["run"] for r in q}),
                                      **{f"{m}_correct": sum(r[f"y_pred_{m}"] == r["y_true"] for r in q) for m in ("A", "M", "B")}}
    idx = {(r["run"], r["scene_seq"]): r for r in allr}
    for name, keys in prep["audited_sets"].items():
        q = [idx[tuple(k)] for k in keys]
        d = {"n": len(q), "runs": len({r["run"] for r in q}), **{f"{m}_correct": sum(r[f"y_pred_{m}"] == r["y_true"] for r in q) for m in ("A", "M", "B")},
             "M_pred": dict(collections.Counter(r["y_pred_M"] for r in q))}
        if name == "gain_35":
            d["M_like_B_right"] = sum(r["y_pred_M"] == r["y_true"] for r in q); d["M_like_A_wrong"] = len(q) - d["M_like_B_right"]
        if name in ("core_24", "gain_35"):
            d["excl_212954"] = {"n": sum(r["run"] != RID for r in q), **{f"{m}_correct": sum(r[f"y_pred_{m}"] == r["y_true"] for r in q if r["run"] != RID) for m in ("A", "M", "B")}}
        if name == "boundary_7":
            d["scenes"] = [{k: r[k] for k in ("run", "scene_seq", "split", "y_pred_A", "y_pred_M", "y_pred_B")} for r in q]
        res["audited"][name] = d
    json.dump(res, open(out / "results_M.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(out / "predictions_M.jsonl", "w", encoding="utf-8") as fo:
        for r in allr: fo.write(json.dumps({k: r[k] for k in ("run", "scene_seq", "split", "y_true", "y_pred_A", "y_pred_M", "y_pred_B")}, ensure_ascii=False) + "\n")
    print(json.dumps({sp: {m: res["eval"][sp]["metrics"][m]["acc"] for m in ("A", "M", "B")} for sp in ev}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["prepare", "train"])
    for k in ("--config", "--stagmem-dir", "--audit-rows", "--rf-dir", "--extract", "--manifest", "--baseline-results", "--cond-results", "--out"):
        ap.add_argument(k, required=True)
    ap.add_argument("--approved", default=None)
    a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    if a.stage == "prepare": prepare(a, out)
    elif a.approved != APPROVAL: sys.exit(f"train stage needs --approved {APPROVAL} (separate approval)")
    else: train(a, out)


if __name__ == "__main__":
    main()
