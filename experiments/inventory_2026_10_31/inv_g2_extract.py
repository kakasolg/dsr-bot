"""G2 scene extract for the manifest's 55 runs / 1475 scenes (read only).

Step 1 checks every (run, scene_seq): the ctl.jsonl line with that seq is k="scene" and its rule equals the
rule in g2_scene_links.jsonl. Any mismatch or missing line -> write the check file and stop (no extract).
Step 2 writes one line per scene with the captured values as they are (no computing, no normalising):
  g2_scene_extract.jsonl(.gz if over 20 MB), g2_scene_fight_keys.json, g2_scene_extract_check.json.

python experiments/inventory_2026_10_31/inv_g2_extract.py <manifest.tsv>
"""
import collections
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "data" / "runs"
OUT = ROOT / "data" / "inventory" / "2026-10-31"
LIMIT = 20 * 1024 * 1024
MISSING = object()


def manifest(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        if line.strip() and not line.startswith("#"):
            run, split, n, flags, seqs = line.rstrip("\n").split("\t")
            rows.append({"run": run, "split": split, "n": int(n), "flags": flags,
                         "seqs": [int(s) for s in seqs.split(",")]})
    return rows


def links():
    out = {}
    for line in open(OUT / "g2_scene_links.jsonl", encoding="utf-8"):
        d = json.loads(line)
        out[(d["run"], d["scene_seq"])] = d["rule"]
    return out


def scenes_of(run, want):
    found = {}
    for line in open(RUNS / f"{run}.ctl.jsonl", encoding="utf-8"):
        m = re.search(r'"seq": (\d+)', line)
        if m and int(m.group(1)) in want:
            d = json.loads(line)
            if d.get("seq") in want:
                found[d["seq"]] = d
    return found


def get(d, path):
    for p in path.split("."):
        if not isinstance(d, dict) or p not in d:
            return MISSING
        d = d[p]
    return d


def settings(run):
    p = RUNS / f"{run}.settings.json"
    if not p.exists():
        return None, "file missing"
    try:
        return json.load(open(p, encoding="utf-8")), None
    except Exception as e:
        return None, f"read failed: {e}"


def diff_touches(run, s):
    """Uncommitted diff: does it change souls/duel.py / scenes.py? From <run>.diff, else settings dirty_files."""
    p = RUNS / f"{run}.diff"
    if p.exists():
        files = set(re.findall(r"^diff --git a/(\S+) b/", p.read_text(encoding="utf-8", errors="replace"), re.M))
        src = "diff file"
    else:
        files = set((s or {}).get("code", {}).get("dirty_files") or [])
        src = "settings dirty_files (no .diff file)"
    return {"source": src,
            "duel.py": "yes" if any(f.endswith("duel.py") for f in files) else "no",
            "scenes.py": "yes" if any(f.endswith("scenes.py") for f in files) else "no"}


FIELDS = ["schema", "rule", "out", "meta.commit", "meta.dirty", "meta.diff_sha1", "meta.cmd", "meta.seg",
          "weapon.id", "weapon.name", "style", "flags", "nm", "ground", "snap.t", "snap.cam_yaw", "snap.player",
          "snap.chars", "tick.ptr", "tick.h", "tick.dy", "tick.a", "res.dealt", "res.hits", "res.npc",
          "res.wall_back", "reflex.age", "reflex.start", "reflex.prefer", "reflex.anim", "care.wants", "fight"]


def main():
    rows = manifest(sys.argv[1])
    lk = links()
    check = {"manifest": {"runs": len(rows), "scenes": sum(len(r["seqs"]) for r in rows),
                          "n_matches_list": all(r["n"] == len(r["seqs"]) for r in rows)},
             "target_check": {"not_scene": [], "missing": [], "rule_mismatch": [], "not_in_links": [],
                              "read_failed": []}}
    tc = check["target_check"]
    recs = {}
    for r in rows:
        want = set(r["seqs"])
        try:
            found = scenes_of(r["run"], want)
        except Exception as e:
            tc["read_failed"].append({"run": r["run"], "why": str(e)})
            continue
        for q in r["seqs"]:
            d = found.get(q)
            if d is None:
                tc["missing"].append([r["run"], q])
            elif d.get("k") != "scene":
                tc["not_scene"].append([r["run"], q, d.get("k")])
            elif (r["run"], q) not in lk:
                tc["not_in_links"].append([r["run"], q])
            elif d.get("rule") != lk[(r["run"], q)]:
                tc["rule_mismatch"].append([r["run"], q, d.get("rule"), lk[(r["run"], q)]])
            else:
                recs[(r["run"], q)] = d
    bad = sum(len(v) for v in tc.values())
    tc["ok"] = len(recs)
    tc["result"] = "all match" if bad == 0 else f"{bad} problems - extract stopped"
    if bad:
        json.dump(check, open(OUT / "g2_scene_extract_check.json", "w", encoding="utf-8"), ensure_ascii=False,
                  indent=1)
        print(tc["result"])
        return

    lines, miss = [], collections.Counter()
    by_split, style_by_run, arena = collections.Counter(), collections.defaultdict(collections.Counter), 0
    keys_run = collections.defaultdict(collections.Counter)
    keys_commit = collections.defaultdict(collections.Counter)
    sizes = collections.defaultdict(list)
    meta_err, dirty = {}, {}
    for r in rows:
        s, err = settings(r["run"])
        if err:
            meta_err[r["run"]] = err
        code, args = (s or {}).get("code", {}), (s or {}).get("args", {})
        meta = {"commit": code.get("commit"), "dirty": code.get("dirty"), "diff_sha1": code.get("diff_sha1"),
                "cmd": args.get("cmd"), "seg": args.get("seg")}
        if "dirty" in r["flags"] or code.get("dirty"):
            dirty[r["run"]] = diff_touches(r["run"], s)
        for q in r["seqs"]:
            d = recs[(r["run"], q)]
            snap = d.get("snap") or {}
            e = {"run": r["run"], "scene_seq": q, "split": r["split"], "schema": d.get("schema"),
                 "rule": d.get("rule"), "out": d.get("out"), "meta": meta,
                 "weapon": d.get("weapon"), "style": d.get("style"), "flags": d.get("flags"), "nm": d.get("nm"),
                 "ground": d.get("ground"),
                 "snap": {k: snap[k] for k in ("t", "cam_yaw", "player", "chars") if k in snap},
                 "tick": d.get("tick"), "res": d.get("res"), "reflex": d.get("reflex"),
                 "care": {"wants": d["care"]["wants"]} if isinstance(d.get("care"), dict) and "wants" in d["care"]
                 else None,
                 "fight": d.get("fight")}
            for f in FIELDS:
                v = get(e, f)
                if v is MISSING or v is None:
                    miss[f] += 1
            by_split[r["split"]] += 1
            style_by_run[r["run"]][str(d.get("style"))] += 1
            fg = d.get("fight")
            if isinstance(fg, dict):
                if fg.get("arena") is not None:
                    arena += 1
                keys_run[r["run"]].update(fg.keys())
                keys_commit[str(meta["commit"])].update(fg.keys())
                sizes["fight_bytes"].append(len(json.dumps(fg, ensure_ascii=False)))
            team = (snap.get("player") or {}).get("team")
            chars = snap.get("chars") or []
            hostile = [c for c in chars if (c.get("hp") or 0) > 0 and c.get("team") != team]
            sizes["chars"].append(len(chars))
            sizes["hostile"].append(len(hostile))
            sizes["other"].append(len(chars) - len(hostile))
            line = json.dumps(e, ensure_ascii=False)
            sizes["line_bytes"].append(len(line.encode("utf-8")) + 1)
            lines.append(line)

    total = sum(sizes["line_bytes"])
    data = ("\n".join(lines) + "\n").encode("utf-8")
    if total > LIMIT:
        name = "g2_scene_extract.jsonl.gz"
        with gzip.open(OUT / name, "wb", compresslevel=9) as f:
            f.write(data)
    else:
        name = "g2_scene_extract.jsonl"
        (OUT / name).write_bytes(data)

    def stat(v):
        return {"n": len(v), "mean": round(sum(v) / len(v), 2) if v else None, "min": min(v, default=None),
                "max": max(v, default=None)}

    check.update({
        "extracted": {"total": len(lines), "by_split": dict(by_split)},
        "output": {"file": name, "uncompressed_bytes": total, "written_bytes": (OUT / name).stat().st_size,
                   "gzip": total > LIMIT},
        "missing_by_field": {f: miss.get(f, 0) for f in FIELDS},
        "settings_read": meta_err or "all 55 read",
        "style_by_run": {k: dict(v) for k, v in style_by_run.items()},
        "fight_arena_not_null": arena,
        "dirty_diff_touches": dirty,
        "sizes": {k: stat(v) for k, v in sizes.items()},
        "notes": ["hostile = hp > 0 and team != player team, within the captured chars (<= 25 m)",
                  "values are copied from the scene record as captured; meta from data/runs/<run>.settings.json"],
    })
    json.dump(check, open(OUT / "g2_scene_extract_check.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"by_run": {k: dict(v) for k, v in keys_run.items()},
               "by_commit": {k: dict(v) for k, v in keys_commit.items()}},
              open(OUT / "g2_scene_fight_keys.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(tc["result"], len(lines), name, total)


if __name__ == "__main__":
    main()
