"""B0 = B with every valid smem_target_since_s value replaced by 0.0 (NaN, __missing flags and all other columns unchanged).
A, M, B are reused from stored predictions; only B0 is trained (train stage, separate approval).

  prepare  matrices and checks; RandomForestClassifier.fit / predict are patched to raise. Writes prep_report_B0.json into --out.
  train    --approved TRAINING-APPROVED-B0 is checked BEFORE --out is created. Writes results_B0.json, predictions_B0.jsonl.

  PYTHONDONTWRITEBYTECODE=1 python stagmem_b0.py prepare --config config.json --stagmem-dir /tmp/stagmem --m-dir /tmp/stagmem_m \
      --audit-rows /tmp/spaudit_consts/rows.json --rf-dir <experiments/g2_i1current_rf_2026_10_31> --extract <...> --manifest <...> \
      --baseline-results <...> --cond-results /tmp/stagmem/cond/results.json --out <dir>
"""
import argparse, collections, hashlib, importlib.util, json, sys
from pathlib import Path

import numpy as np

APPROVAL = "TRAINING-APPROVED-B0"
RID = "20261019_212954_parish-group1"


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(a):
    cfg = json.load(open(a.config, encoding="utf-8")); ref = cfg["refs"]; sd, md = Path(a.stagmem_dir), Path(a.m_dir)
    checks = {k: sha(p) == ref[r] for k, p, r in (
        ("stagmem_config", sd / "prep/config.json", "stagmem_config_sha256"), ("stagmem_script", sd / "prep/stagmem_compare.py", "stagmem_script_sha256"),
        ("stagmem_prep_report", sd / "prep/prep_report.json", "stagmem_prep_report_sha256"), ("stagmem_results", sd / "run/results.json", "stagmem_results_sha256"),
        ("stagmem_predictions", sd / "run/predictions.jsonl", "stagmem_predictions_sha256"), ("m_config", md / "prep/config.json", "m_config_sha256"),
        ("m_results", md / "run/results_M.json", "m_results_sha256"), ("m_predictions", md / "run/predictions_M.jsonl", "m_predictions_sha256"),
        ("audit_rows", a.audit_rows, "branch_audit_rows_sha256"))}
    assert all(checks.values()), checks
    spec = importlib.util.spec_from_file_location("smc", sd / "prep/stagmem_compare.py"); S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
    sa = argparse.Namespace(config=str(sd / "prep/config.json"), rf_dir=a.rf_dir, extract=a.extract, manifest=a.manifest,
                            baseline_results=a.baseline_results, cond_results=a.cond_results)
    scfg, R, by, enc, mats, cols_A, cols_B, prim = S.setup(sa)
    assert scfg["model"]["params"] == cfg["model"]["params"]
    j = cols_B.index(cfg["b0_column"])
    B0 = {}
    for sp in mats:
        M = mats[sp][1].copy(); v = M[:, j]; M[~np.isnan(v), j] = cfg["b0_value"]; B0[sp] = M
    stored = {(p["run"], p["scene_seq"]): p for p in map(json.loads, open(md / "run/predictions_M.jsonl", encoding="utf-8"))}   # has A, M, B
    sab = {(p["run"], p["scene_seq"]): p for p in map(json.loads, open(sd / "run/predictions.jsonl", encoding="utf-8"))}
    audit = json.load(open(a.audit_rows, encoding="utf-8"))
    return cfg, R, by, mats, B0, cols_B, j, prim, stored, sab, audit, checks


def diag_sets(audit, stored):
    ev = [r for r in audit if r["split"] != "train"]; k = lambda r: (r["run"], r["seq"])
    late = [r for r in ev if r["branch"] == "late_guard"]
    gain = [r for r in late if stored[k(r)]["y_pred_A"] != "stagger_punish" and stored[k(r)]["y_pred_B"] == "stagger_punish"]
    a6 = [key for key, p in stored.items() if p["y_pred_A"] == p["y_true"] and p["y_pred_B"] != p["y_true"]]
    return {"late_guard_95": [k(r) for r in late], "gain_35": [k(r) for r in gain], "core_24": [k(r) for r in late if r["core"]],
            "boundary_7": [k(r) for r in late if r["margin"] is not None and r["margin"] < 0.05], "a_only_6": sorted(a6)}


def prepare(a, out):
    from sklearn.ensemble import RandomForestClassifier
    def refuse(*_a, **_k): raise RuntimeError("prepare stage: fit/predict are not allowed")
    RandomForestClassifier.fit = RandomForestClassifier.predict = RandomForestClassifier.predict_proba = refuse
    cfg, R, by, mats, B0, cols_B, j, prim, stored, sab, audit, checks = load(a)
    ev = cfg["splits"]["eval"]; ck = {"refs": checks, "b0_column_index": j, "n_columns": len(cols_B)}
    other = [i for i in range(len(cols_B)) if i != j]
    eq = lambda x, y: bool(np.array_equal(np.isnan(x), np.isnan(y))) and bool(np.array_equal(np.nan_to_num(x), np.nan_to_num(y)))
    ck["other_columns_equal_B"] = {sp: eq(B0[sp][:, other], mats[sp][1][:, other]) for sp in mats}
    ck["nan_positions_kept"] = {sp: bool(np.array_equal(np.isnan(B0[sp][:, j]), np.isnan(mats[sp][1][:, j]))) for sp in mats}
    ck["valid_count"] = {sp: [int((~np.isnan(mats[sp][1][:, j])).sum()), int((~np.isnan(B0[sp][:, j])).sum())] for sp in mats}
    ck["valid_all_zero"] = {sp: bool((B0[sp][~np.isnan(B0[sp][:, j]), j] == 0.0).all()) for sp in mats}
    ck["missing_flag_consistent"] = {sp: bool(np.array_equal(np.isnan(B0[sp][:, j]), B0[sp][:, cols_B.index(cfg["b0_column"] + "__missing")] == 1.0)) for sp in mats}
    ck["shape"] = {sp: list(B0[sp].shape) for sp in mats}
    ck["stored_rows"] = {"AMB": len(stored), "AB": len(sab)}
    ck["stored_join"] = {sp: all((x["run"], x["scene_seq"]) in stored and stored[(x["run"], x["scene_seq"])]["split"] == sp
                                 and stored[(x["run"], x["scene_seq"])]["y_true"] == x["rule"] for x in by[sp]) for sp in ev}
    ck["stored_A_B_agree_between_files"] = all(sab[k]["y_pred_A"] == p["y_pred_A"] and sab[k]["y_pred_B"] == p["y_pred_B"] for k, p in stored.items())
    sets = diag_sets(audit, stored)
    ck["diag_set_sizes"] = {k: len(v) for k, v in sets.items()}
    ok = (all(ck["other_columns_equal_B"].values()) and all(ck["nan_positions_kept"].values()) and all(v[0] == v[1] for v in ck["valid_count"].values())
          and all(ck["valid_all_zero"].values()) and all(ck["missing_flag_consistent"].values()) and ck["stored_rows"] == {"AMB": 723, "AB": 723}
          and all(ck["stored_join"].values()) and ck["stored_A_B_agree_between_files"]
          and ck["diag_set_sizes"] == {"late_guard_95": 95, "gain_35": 35, "core_24": 24, "boundary_7": 7, "a_only_6": 6})
    rep = {"config_sha256": sha(a.config), "script_sha256": sha(__file__), "stage": "prepare (no fit / predict)", "checks": ck,
           "diag_sets": {k: [list(t) for t in v] for k, v in sets.items()}, "primary_class_sets": prim, "all_checks_pass": ok}
    json.dump(rep, open(out / "prep_report_B0.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"all_checks_pass": ok, "valid_count": ck["valid_count"], "sets": ck["diag_set_sizes"]}))


def pair(rs, c1, c2):
    return dict(collections.Counter("both" if r[c1] == r["y_true"] and r[c2] == r["y_true"] else "first_only" if r[c1] == r["y_true"]
                                    else "second_only" if r[c2] == r["y_true"] else "both_wrong" for r in rs))


def train(a, out):
    from sklearn.ensemble import RandomForestClassifier
    prep = json.load(open(Path(a.prep_report), encoding="utf-8"))
    assert prep["config_sha256"] == sha(a.config) and prep["script_sha256"] == sha(__file__) and prep["all_checks_pass"], "prepare first, unchanged"
    cfg, R, by, mats, B0, cols_B, j, prim, stored, sab, audit, _ = load(a)
    out.mkdir(parents=True, exist_ok=False)
    ev = cfg["splits"]["eval"]; tr = by["train"]; ytr = [x["rule"] for x in tr]; tc = set(ytr)
    m = RandomForestClassifier(**cfg["model"]["params"]).fit(B0["train"], ytr)
    res = {"config_sha256": sha(a.config), "prep_report_B0_sha256": sha(a.prep_report), "train_B0": R.metrics(tr, ytr, list(m.predict(B0["train"])), {}, tc),
           "eval": {}, "diag": {}, "reflex_face_first": {}}
    allr = []
    for sp in ev:
        rows = by[sp]; y = [x["rule"] for x in rows]; p0 = list(m.predict(B0[sp]))
        rr = [dict(run=x["run"], scene_seq=x["scene_seq"], split=sp, y_true=t, y_pred_A=stored[(x["run"], x["scene_seq"])]["y_pred_A"],
                   y_pred_M=stored[(x["run"], x["scene_seq"])]["y_pred_M"], y_pred_B0=q, y_pred_B=stored[(x["run"], x["scene_seq"])]["y_pred_B"]) for x, t, q in zip(rows, y, p0)]
        allr += rr
        met = {c: R.metrics(rows, y, [r[f"y_pred_{c}"] for r in rr], {"primary": prim[sp]}, tc) for c in ("A", "M", "B0", "B")}
        runs = sorted({r["run"] for r in rr})
        res["eval"][sp] = {"n": len(rr), "runs": len(runs), "metrics": met, "labels": {"primary": met["A"]["primary_classes"], "all_true": met["A"]["all_true_classes"]},
                           "paired": {"B0_B": pair(rr, "y_pred_B0", "y_pred_B"), "A_B0": pair(rr, "y_pred_A", "y_pred_B0"), "M_B0": pair(rr, "y_pred_M", "y_pred_B0")},
                           "per_run_paired": {run: {"B0_B": pair([r for r in rr if r["run"] == run], "y_pred_B0", "y_pred_B"),
                                                    "A_B0": pair([r for r in rr if r["run"] == run], "y_pred_A", "y_pred_B0")} for run in runs}}
    idx = {(r["run"], r["scene_seq"]): r for r in allr}
    for name, keys in prep["diag_sets"].items():
        q = [idx[tuple(k)] for k in keys]
        d = {"n": len(q), "runs": len({r["run"] for r in q}), "post_hoc": name in ("gain_35", "a_only_6"),
             **{f"{c}_correct": sum(r[f"y_pred_{c}"] == r["y_true"] for r in q) for c in ("A", "M", "B0", "B")},
             "B0_pred": dict(collections.Counter(r["y_pred_B0"] for r in q))}
        if name == "gain_35":
            d["per_run"] = {run: {"kept": sum(r["y_pred_B0"] == r["y_true"] for r in q if r["run"] == run),
                                  "lost": sum(r["y_pred_B0"] != r["y_true"] for r in q if r["run"] == run)} for run in sorted({r["run"] for r in q})}
        if name in ("core_24", "gain_35"):
            d["excl_212954"] = {"n": sum(r["run"] != RID for r in q), **{f"{c}_correct": sum(r[f"y_pred_{c}"] == r["y_true"] for r in q if r["run"] != RID) for c in ("A", "M", "B0", "B")}}
        if name in ("boundary_7", "a_only_6"):
            d["scenes"] = [{k: r[k] for k in ("run", "scene_seq", "split", "y_true", "y_pred_A", "y_pred_M", "y_pred_B0", "y_pred_B")} for r in q]
        res["diag"][name] = d
    for c in ("reflex", "face_first"):
        q = [r for r in allr if r["y_true"] == c]
        res["reflex_face_first"][c] = {"n": len(q), **{f"{m_}_correct": sum(r[f"y_pred_{m_}"] == c for r in q) for m_ in ("A", "M", "B0", "B")},
                                       "lost_vs_A": [{k: r[k] for k in ("run", "scene_seq", "split", "y_pred_A", "y_pred_B0")} for r in q if r["y_pred_A"] == c and r["y_pred_B0"] != c],
                                       "lost_vs_B": [{k: r[k] for k in ("run", "scene_seq", "split", "y_pred_B", "y_pred_B0")} for r in q if r["y_pred_B"] == c and r["y_pred_B0"] != c]}
    json.dump(res, open(out / "results_B0.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(out / "predictions_B0.jsonl", "w", encoding="utf-8") as fo:
        for r in allr: fo.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({sp: {c: res["eval"][sp]["metrics"][c]["acc"] for c in ("A", "M", "B0", "B")} for sp in ev}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["prepare", "train"])
    for k in ("--config", "--stagmem-dir", "--m-dir", "--audit-rows", "--rf-dir", "--extract", "--manifest", "--baseline-results", "--cond-results", "--out"):
        ap.add_argument(k, required=True)
    ap.add_argument("--prep-report", help="train stage: prep_report_B0.json from the prepare stage")
    ap.add_argument("--approved", default=None)
    a = ap.parse_args(); out = Path(a.out)
    if a.stage == "prepare":
        out.mkdir(parents=True, exist_ok=True); prepare(a, out)
    else:
        if a.approved != APPROVAL:
            sys.exit(f"train stage needs --approved {APPROVAL} (separate approval); nothing was created")
        if not a.prep_report:
            sys.exit("train stage needs --prep-report")
        train(a, out)


if __name__ == "__main__":
    main()
