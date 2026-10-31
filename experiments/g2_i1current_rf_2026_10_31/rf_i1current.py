"""I1-current RandomForest rule classifier for G2 scenes (follow-up to experiments/g2_scene_baselines_2026_10_31).

  python rf_i1current.py select --config config.json --extract <g2_scene_extract.jsonl> --manifest <g2_scene_manifest_scenes.jsonl> --out <dir>
      trains the 4 candidates on train, evaluates train / val only, writes candidates.json + selection.json
  python rf_i1current.py final  --config config.json --extract ... --manifest ... --baseline-results <baseline results.json> --out <dir>
      needs selection.json; trains the selected config on train (base) and on train minus the dirty_duel_py run
      (sensitivity), evaluates val / test / shift_zone / shift_ref / shift_ref_no_dirty_duel, writes results.json,
      predictions.jsonl, comparison.json

Only the Python standard library, numpy and scikit-learn. Paths come from the command line.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier

HOST = {6, 7, 24, 25, 27, 33}
NUM = ["my_hp", "my_max_hp", "my_hp_ratio", "my_sp", "my_max_sp", "my_sp_ratio",
       "tgt_hp", "tgt_max_hp", "tgt_hp_ratio", "tgt_sp", "tgt_max_sp", "tgt_sp_ratio",
       "tgt_h", "tgt_dy", "tgt_off_my_facing_deg", "tgt_off_my_facing_signed_deg", "me_off_tgt_facing_deg",
       "n_hostile_2_5m", "n_hostile_4m", "n_hostile_8m", "n_hostile_25m",
       "other_nearest_hd", "other_second_hd", "n_other_attacking_4m"]
NAN_OK = ["my_hp_ratio", "my_sp_ratio", "tgt_hp_ratio", "tgt_sp_ratio", "other_nearest_hd", "other_second_hd"]
CAT = ["my_anim", "tgt_anim", "tgt_anim_cat", "weapon_id"]
MIN_CAT = 5


def sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def rel_angle(a, b) -> float:
    """souls/moves.py rel_angle: how far b is off a's facing (rad, -pi..pi, + right); world yaw = heading + pi."""
    fwd = a["heading"] + math.pi
    return (math.atan2(b["x"] - a["x"], b["z"] - a["z"]) - fwd + math.pi) % (2 * math.pi) - math.pi


def anim_cat(a):
    if a is None or a == -1: return "idle"
    if 3000 <= a < 3500: return "attack"
    if 3500 <= a < 3600: return "stagger"
    if 2000 <= a < 2100: return "hit_stun"
    if 9900 <= a < 10000: return "downed"
    if a == 9600: return "guard_broken"
    if 9000 <= a < 9100: return "dormant"
    if a in (1500, 1550, 121500): return "falling"
    return "other"


def ratio(v, m):
    return v / m if (v is not None and m) else float("nan")


def features(x) -> dict:
    p = x["snap"]["player"]
    t = next(c for c in x["snap"]["chars"] if c["ptr"] == x["tick"]["ptr"])
    hd = lambda c: math.hypot(c["x"] - p["x"], c["z"] - p["z"])
    host = [c for c in x["snap"]["chars"] if c["team"] in HOST and (c["hp"] or 0) > 0]
    others = sorted(hd(c) for c in host if c["ptr"] != t["ptr"])
    ra = rel_angle(p, t)
    f = {"my_hp": p["hp"], "my_max_hp": p["max_hp"], "my_hp_ratio": ratio(p["hp"], p["max_hp"]),
         "my_sp": p["sp"], "my_max_sp": p["max_sp"], "my_sp_ratio": ratio(p["sp"], p["max_sp"]),
         "tgt_hp": t["hp"], "tgt_max_hp": t["max_hp"], "tgt_hp_ratio": ratio(t["hp"], t["max_hp"]),
         "tgt_sp": t["sp"], "tgt_max_sp": t["max_sp"], "tgt_sp_ratio": ratio(t["sp"], t["max_sp"]),
         "tgt_h": x["tick"]["h"], "tgt_dy": x["tick"]["dy"],
         "tgt_off_my_facing_deg": abs(math.degrees(ra)), "tgt_off_my_facing_signed_deg": math.degrees(ra),
         "me_off_tgt_facing_deg": abs(math.degrees(rel_angle(t, p))),
         "n_hostile_2_5m": sum(hd(c) < 2.5 for c in host), "n_hostile_4m": sum(hd(c) < 4.0 for c in host),
         "n_hostile_8m": sum(hd(c) < 8.0 for c in host), "n_hostile_25m": len(host),
         "other_nearest_hd": others[0] if others else float("nan"),
         "other_second_hd": others[1] if len(others) > 1 else float("nan"),
         "n_other_attacking_4m": sum(1 for c in host if c["ptr"] != t["ptr"] and hd(c) < 4.0 and c["anim"] is not None and 3000 <= c["anim"] < 3500),
         "my_anim": "idle" if p["anim"] in (None, -1) else str(p["anim"]),
         "tgt_anim": "idle" if x["tick"]["a"] in (None, -1) else str(x["tick"]["a"]),
         "tgt_anim_cat": anim_cat(x["tick"]["a"]),
         "weapon_id": str(x["weapon"]["id"])}
    return f


class Encoder:
    def fit(self, F):
        self.vocab = {}
        for k in CAT:
            cnt = collections.Counter(f[k] for f in F)
            self.vocab[k] = sorted(v for v, n in cnt.items() if n >= MIN_CAT)
        self.cols = list(NUM) + [f"{k}__missing" for k in NAN_OK]
        for k in CAT:
            self.cols += [f"{k}={v}" for v in self.vocab[k]] + [f"{k}=__rare__", f"{k}=__unknown__"]
        self.seen = {k: set(f[k] for f in F) for k in CAT}
        return self

    def transform(self, F):
        idx = {c: i for i, c in enumerate(self.cols)}
        M = np.zeros((len(F), len(self.cols)), dtype=float)
        unk = collections.Counter()
        for r, f in enumerate(F):
            for k in NUM:
                v = f[k]
                M[r, idx[k]] = np.nan if v is None else v
            for k in NAN_OK:
                v = f[k]
                M[r, idx[f"{k}__missing"]] = 1.0 if (v is None or (isinstance(v, float) and math.isnan(v))) else 0.0
            for k in CAT:
                v = f[k]
                if v in self.vocab[k]: M[r, idx[f"{k}={v}"]] = 1.0
                elif v in self.seen[k]: M[r, idx[f"{k}=__rare__"]] = 1.0
                else: M[r, idx[f"{k}=__unknown__"]] = 1.0; unk[k] += 1
        return M, dict(unk)

    def describe(self):
        return {"n_columns": len(self.cols), "vocab": self.vocab}


def metrics(rows, y, yp, class_sets: dict, train_classes: set):
    classes = sorted(set(y) | set(yp))
    runs_of = collections.defaultdict(set)
    for r, t in zip(rows, y): runs_of[t].add(r["run"])
    per = {}
    for c in classes:
        tp = sum(1 for a, b in zip(y, yp) if a == c and b == c); fp = sum(1 for a, b in zip(y, yp) if a != c and b == c)
        fn = sum(1 for a, b in zip(y, yp) if a == c and b != c)
        P = tp / (tp + fp) if tp + fp else 0.0; R = tp / (tp + fn) if tp + fn else 0.0; F = 2 * P * R / (P + R) if P + R else 0.0
        n = tp + fn
        per[c] = dict(n=n, runs=len(runs_of[c]), pred_n=tp + fp, P=round(P, 3), R=round(R, 3), F1=round(F, 3),
                      reference_only=bool(n < 10 or len(runs_of[c]) < 3), in_train=c in train_classes)
    allt = sorted(c for c in per if per[c]["n"] >= 1)
    mf = lambda cs: (round(sum(per[c]["F1"] for c in cs) / len(cs), 4) if cs else None)
    out = dict(n=len(rows), runs=len({r["run"] for r in rows}),
               acc=round(sum(a == b for a, b in zip(y, yp)) / len(rows), 4) if rows else None,
               macro_f1_all_true=mf(allt), all_true_classes=allt,
               train_absent_true_classes=sorted(c for c in allt if c not in train_classes))
    for name, cs in class_sets.items():
        cs = sorted(c for c in (cs or []))
        out[f"macro_f1_{name}"] = mf(cs); out[f"{name}_classes"] = cs
    byrun = collections.defaultdict(lambda: [0, 0])
    for r, a, b in zip(rows, y, yp): byrun[r["run"]][0] += 1; byrun[r["run"]][1] += (a == b)
    out["per_run"] = {k: dict(n=v[0], acc=round(v[1] / v[0], 4)) for k, v in sorted(byrun.items())}
    out["per_run_unweighted_mean_acc"] = round(sum(v["acc"] for v in out["per_run"].values()) / len(out["per_run"]), 4) if out["per_run"] else None
    out["per_class"] = per
    out["confusion"] = {f"{a}->{b}": n for (a, b), n in sorted(collections.Counter(zip(y, yp)).items(), key=lambda kv: (-kv[1], kv[0]))}
    return out


def tactic(rule, x, tmap):
    if rule == "edge":
        return "reposition" if x["fight"].get("arena") is not None else "guard"
    return tmap.get(rule, "unmapped")


def load(args, cfg):
    for key, path in (("extract_sha256", args.extract), ("manifest_sha256", args.manifest)):
        h = sha(path)
        if h != cfg["data"][key]:
            sys.exit(f"hash mismatch {path}: {h} != {cfg['data'][key]}")
    X = [json.loads(l) for l in open(args.extract, encoding="utf-8")]
    man = {(d["run"], d["scene_seq"]): d["split"] for d in map(json.loads, open(args.manifest, encoding="utf-8"))}
    assert {(x["run"], x["scene_seq"]) for x in X} == set(man) and all(man[(x["run"], x["scene_seq"])] == x["split"] for x in X)
    return [x for x in X if x["split"] not in cfg["splits"]["exclude"]]


def make_model(cfg, cand):
    return RandomForestClassifier(max_depth=cand["max_depth"], class_weight=cand["class_weight"], **cfg["model"]["common"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["select", "final"])
    ap.add_argument("--config", required=True); ap.add_argument("--extract", required=True); ap.add_argument("--manifest", required=True)
    ap.add_argument("--baseline-results"); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    cfg = json.load(open(a.config, encoding="utf-8")); cfg_sha = sha(a.config)
    X = load(a, cfg)
    for x in X: x["_f"] = features(x)
    by = collections.defaultdict(list)
    for x in X: by[x["split"]].append(x)

    if a.stage == "select":
        tr, va = by["train"], by["val"]
        enc = Encoder().fit([x["_f"] for x in tr]); Xtr, _ = enc.transform([x["_f"] for x in tr]); Xva, unk = enc.transform([x["_f"] for x in va])
        ytr, yva = [x["rule"] for x in tr], [x["rule"] for x in va]
        tc = set(ytr); res = {"config_sha256": cfg_sha, "encoder": enc.describe(), "val_unknown_categories": unk, "candidates": {}}
        for cand in cfg["model"]["candidates"]:
            m = make_model(cfg, cand).fit(Xtr, ytr)
            res["candidates"][cand["id"]] = {"params": cand, "train": metrics(tr, ytr, list(m.predict(Xtr)), {}, tc),
                                             "val": metrics(va, yva, list(m.predict(Xva)), {}, tc)}
        order = {c["id"]: i for i, c in enumerate(cfg["model"]["candidates"])}
        best = sorted(res["candidates"].items(), key=lambda kv: (-round(kv[1]["val"]["macro_f1_all_true"], 4), kv[1]["params"]["max_depth"], order[kv[0]]))[0][0]
        json.dump(res, open(out / "candidates.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        sel = {"config_sha256": cfg_sha, "candidates_sha256": sha(out / "candidates.json"), "selected": best,
               "params": res["candidates"][best]["params"], "common": cfg["model"]["common"],
               "val_macro_f1_all_true": {k: v["val"]["macro_f1_all_true"] for k, v in res["candidates"].items()},
               "rule": cfg["selection"]}
        json.dump(sel, open(out / "selection.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(json.dumps(sel["val_macro_f1_all_true"]), "->", best)
        return

    sel = json.load(open(out / "selection.json", encoding="utf-8"))
    assert sel["config_sha256"] == cfg_sha, "config changed after selection"
    base = json.load(open(a.baseline_results, encoding="utf-8"))
    assert sha(a.baseline_results) == cfg["data"]["baseline_results_sha256"]
    bl_sets = {e: base["variants"]["A_base"]["eval"][e]["lookup"]["primary_classes"] for e in base["variants"]["A_base"]["eval"]}
    cand = sel["params"]
    evals = {e: by[e] for e in cfg["splits"]["eval"]}
    for k, v in cfg["splits"]["extra_eval"].items():
        evals[k] = [x for x in by[v["from"]] if x["run"] not in v["drop_runs"]]
    variants = {"base": by["train"],
                "no_dirty_duel_train": [x for x in by["train"] if x["run"] not in cfg["splits"]["sensitivity"]["no_dirty_duel_train"]["drop_train_runs"]]}
    results = {"config_sha256": cfg_sha, "selection_sha256": sha(out / "selection.json"), "selected": sel["selected"], "variants": {}}
    preds = []
    for vn, tr in variants.items():
        enc = Encoder().fit([x["_f"] for x in tr]); Xtr, _ = enc.transform([x["_f"] for x in tr]); ytr = [x["rule"] for x in tr]
        m = make_model(cfg, cand).fit(Xtr, ytr); tc = set(ytr)
        vr = {"train_n": len(tr), "train_runs": len({x["run"] for x in tr}), "encoder": enc.describe(),
              "train_metrics": metrics(tr, ytr, list(m.predict(Xtr)), {}, tc),
              "feature_importance_impurity": dict(sorted(zip(enc.cols, [round(float(v), 4) for v in m.feature_importances_]), key=lambda kv: -kv[1])),
              "eval": {}}
        for en, rows in evals.items():
            Xe, unk = enc.transform([x["_f"] for x in rows]); y = [x["rule"] for x in rows]; yp = list(m.predict(Xe))
            r = metrics(rows, y, yp, {"baseline_set": bl_sets.get(en)}, tc)
            r["unknown_categories"] = unk
            tt = [tactic(t, x, cfg["tactic_map"]) for t, x in zip(y, rows)]; tp = [tactic(t, x, cfg["tactic_map"]) for t, x in zip(yp, rows)]
            r["tactic_aux"] = {k: v for k, v in metrics(rows, tt, tp, {}, {tactic(t, x, cfg["tactic_map"]) for t, x in zip(ytr, tr)}).items()
                               if k in ("acc", "macro_f1_all_true", "all_true_classes", "per_class", "confusion")}
            vr["eval"][en] = r
            if en in cfg["splits"]["eval"]:
                preds += [dict(run=x["run"], scene_seq=x["scene_seq"], split=x["split"], variant=vn, y_true=t, y_pred=p) for x, t, p in zip(rows, y, yp)]
        results["variants"][vn] = vr
    json.dump(results, open(out / "results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(out / "predictions.jsonl", "w", encoding="utf-8") as f:
        for p in preds: f.write(json.dumps(p, ensure_ascii=False) + "\n")
    # comparison with the preserved baseline A (read as is)
    cmp = {"baseline_results_sha256": sha(a.baseline_results), "focus_classes": ["reflex", "stagger_punish", "stamina", "attack"], "eval": {}}
    for en in cfg["splits"]["eval"]:
        b = base["variants"]["A_base"]["eval"][en]; r = results["variants"]["base"]["eval"][en]
        row = {"n": r["n"], "runs": r["runs"],
               "acc": {"majority": b["majority"]["acc"], "lookup": b["lookup"]["acc"], "rf": r["acc"]},
               "macro_f1_baseline_set": {"classes": bl_sets[en], "majority": b["majority"]["macro_f1_primary"], "lookup": b["lookup"]["macro_f1_primary"], "rf": r["macro_f1_baseline_set"]},
               "macro_f1_all_true": {"classes_n": len(r["all_true_classes"]), "majority": b["majority"]["macro_f1_all_true"], "lookup": b["lookup"]["macro_f1_all_true"], "rf": r["macro_f1_all_true"]},
               "focus": {}}
        for c in cmp["focus_classes"]:
            bc = b["lookup"]["per_class"].get(c, {}); rc = r["per_class"].get(c, {})
            row["focus"][c] = {"n": rc.get("n", bc.get("n", 0)), "runs": rc.get("runs"), "lookup_R": bc.get("R"), "lookup_F1": bc.get("F1"),
                               "rf_P": rc.get("P"), "rf_R": rc.get("R"), "rf_F1": rc.get("F1"), "rf_pred_n": rc.get("pred_n")}
        cmp["eval"][en] = row
    json.dump(cmp, open(out / "comparison.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("final done")


if __name__ == "__main__":
    main()
