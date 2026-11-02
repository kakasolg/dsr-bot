"""G4 scene inventory for a fixed run list (read only on data/runs).

python experiments/g4_2026_10_31/g4_extract.py <runs.tsv> <outdir> [--prefix g4_] [--runs-dir data/runs]
                                               [--allow-dirty .claude/launch.json,...]

runs.tsv: one line per run, "<run><TAB><split>" ('#' lines skipped). The split is copied, never decided here.

Built from experiments/inventory_2026_10_31/inv_g2_scenes.py and inv_g2_extract.py (those files are not changed; their
sha256 go into the check file). Same definitions, with paths and prefix as arguments, and:
  1. <prefix>source_sha256.tsv  - sha256 and size of each run's ctl.jsonl, settings.json and .diff (missing = "-")
  2. <prefix>scene_links.jsonl  - one line per scene, as inv_g2_scenes.py
  3. <prefix>scene_manifest.tsv - every scene of every listed run: run, split, n, flags, scene_seq list
       flags = "dirty" when settings dirty_files go beyond --allow-dirty, plus "opt:<arg>" for each true boolean
       argument other than radar / ctl_scenes (G2 manifest convention); "-" when none
  4. target check, then <prefix>scene_extract.jsonl(.gz), <prefix>scene_fight_keys.json, <prefix>scene_extract_check.json
     as inv_g2_extract.py; an unreadable ctl.jsonl or any check problem writes the check file and stops (exit 1) before
     the extract. A run that was read and has no scene is kept in the check file (runs_zero_scenes), not an error
"""
import collections
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [ROOT / "experiments/inventory_2026_10_31/inv_g2_scenes.py",
           ROOT / "experiments/inventory_2026_10_31/inv_g2_extract.py"]
LIMIT = 20 * 1024 * 1024
MISSING = object()
QUIET_ARGS = {"radar", "ctl_scenes"}

FIELDS = ["schema", "rule", "out", "meta.commit", "meta.dirty", "meta.diff_sha1", "meta.cmd", "meta.seg",
          "weapon.id", "weapon.name", "style", "flags", "nm", "ground", "snap.t", "snap.cam_yaw", "snap.player",
          "snap.chars", "tick.ptr", "tick.h", "tick.dy", "tick.a", "res.dealt", "res.hits", "res.npc",
          "res.wall_back", "reflex.age", "reflex.start", "reflex.prefer", "reflex.anim", "care.wants", "fight"]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_runs(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        if line.strip() and not line.startswith("#"):
            run, split = line.rstrip("\n").split("\t")[:2]
            rows.append({"run": run, "split": split})
    return rows


def settings(runs_dir, run):
    p = runs_dir / f"{run}.settings.json"
    if not p.exists():
        return None, "file missing"
    try:
        return json.load(open(p, encoding="utf-8")), None
    except Exception as e:
        return None, f"read failed: {e}"


def get(d, path):
    for p in path.split("."):
        if not isinstance(d, dict) or p not in d:
            return MISSING
        d = d[p]
    return d


def tval(v):
    return v.get("_t") if isinstance(v, dict) else v


def caller_fn(c):
    return ":".join(c.split(":")[:2]) if c else None


def write_sources(runs_dir, rows, path):
    with open(path, "w", encoding="utf-8", newline="\n") as fo:
        fo.write("run\tfile\tsize\tsha256\n")
        for r in rows:
            for ext in (".ctl.jsonl", ".settings.json", ".diff"):
                p = runs_dir / f"{r['run']}{ext}"
                fo.write(f"{r['run']}\t{ext}\t{p.stat().st_size if p.exists() else '-'}\t"
                         f"{sha256(p) if p.exists() else '-'}\n")


def links(runs_dir, rows, path):
    """inv_g2_scenes.py, per run in the list."""
    stats = collections.Counter()
    by_run = {}
    with open(path, "w", encoding="utf-8", newline="\n") as fo:
        for run in [r["run"] for r in rows]:
            p = runs_dir / f"{run}.ctl.jsonl"
            try:
                R = [json.loads(l) for l in p.read_bytes().decode("utf-8").splitlines() if l.strip()]
            except Exception as e:
                fo.write(json.dumps({"run": run, "read_error": repr(e)[:200]}) + "\n"); stats["read_error"] += 1
                by_run[run] = None
                continue
            main = [x for x in R if x.get("th") == "MainThread"]
            decs = [x for x in main if x["k"] == "dec.rule"]
            marks = [x for x in main if x["k"] in ("dec.rule", "scene")]
            pads = [x for x in main if x["k"] == "pad"]
            scenes = [x for x in R if x["k"] == "scene"]
            by_run[run] = [s["seq"] for s in scenes]
            keys = []
            for s in scenes:
                f = s.get("fight") or {}
                t0 = tval(f.get("t0"))
                keys.append(f"{f.get('orig_ptr') or f.get('ptr')}@{(s['t_wall'] + t0):.2f}" if t0 is not None else None)
            for i, s in enumerate(scenes):
                snap = s.get("snap") or {}
                pl = snap.get("player") or {}
                hostile = [c for c in snap.get("chars") or [] if (c.get("hp") or 0) > 0 and c.get("team") != pl.get("team")]
                hits = (s.get("res") or {}).get("hits") or []
                before = [d for d in decs if d["seq"] < s["seq"]]
                prev = before[-1] if before else None
                st = (s["t_wall"], s["t_wall"] + (snap.get("t") or 0.0))
                mine = next((d for d in reversed(before) if d.get("rule") == s.get("rule") and d.get("snap_t") is not None
                             and min(abs(d["snap_t"] - v) for v in st) < 1e-4), None)
                how = "snap_t" if mine is not None else None
                if mine is None and prev is not None and prev.get("rule") == s.get("rule") \
                        and not any(prev["seq"] < m["seq"] < s["seq"] for m in marks):
                    mine, how = prev, "adjacent_same_rule"
                nomatch = None if mine is not None else (
                    "no dec.rule before the scene" if prev is None else
                    "same rule only earlier, not adjacent and snap_t differs" if any(d.get("rule") == s.get("rule") for d in before) else
                    "no dec.rule with this rule before the scene")
                nxt = next((j for j in range(i + 1, len(scenes)) if keys[j] == keys[i] and keys[i] is not None), None)
                if nxt is not None:
                    nh = (scenes[nxt].get("res") or {}).get("hits") or []
                    grown, why = nh[len(hits):], None
                else:
                    grown, why = None, ("no_next_scene" if i == len(scenes) - 1 else "fight_end")
                win = None
                if mine is not None:
                    lo = max((m["seq"] for m in marks if m["seq"] < mine["seq"]), default=-1)
                    w = [x for x in pads if lo < x["seq"] < mine["seq"]]
                    bits = 0
                    for x in w:
                        bits |= x.get("btn") or 0
                    win = {"from_seq": lo, "to_seq": mine["seq"], "n": len(w),
                           "callers": sorted({caller_fn(x.get("caller")) for x in w if x.get("caller")}),
                           "btn_or": bits, "first_pc": w[0]["pc"] if w else None, "last_pc": w[-1]["pc"] if w else None}
                    stats["window_empty" if not w else "window_nonempty"] += 1
                    stats["match_" + how] += 1
                else:
                    stats["no_scene_dec_rule: " + nomatch] += 1
                tick = s.get("tick") or {}
                row = {"run": run, "scene_seq": s["seq"], "scene_pc": s.get("pc"), "schema": s.get("schema"),
                       "snap_t": s["t_wall"] + (snap.get("t") or 0.0), "fight": keys[i], "rule": s.get("rule"), "out": s.get("out"),
                       "target_npc": (s.get("res") or {}).get("npc"), "target_h": tick.get("h"),
                       "hostile_25m": sum(1 for c in hostile if (c.get("dist") or 1e9) <= 25.0),
                       "hostile_4m": sum(1 for c in hostile if (c.get("dist") or 1e9) <= 4.0),
                       "hits_len": len(hits),
                       "prev_dec_rule": ({"seq": prev["seq"], "rule": prev.get("rule"), "same_as_scene": prev.get("rule") == s.get("rule")}
                                         if prev else None),
                       "scene_dec_rule_seq": mine["seq"] if mine else None, "scene_dec_rule_match": how,
                       "scene_dec_rule_null_reason": nomatch,
                       "next_scene_new_hits": grown, "next_scene_null_reason": why, "pad_window": win}
                fo.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                stats["scenes"] += 1
            stats["runs"] += 1
    return by_run, dict(stats)


def flags_of(s, allow):
    if s is None:
        return "no-settings"
    out = []
    files = (s.get("code") or {}).get("dirty_files")
    if files is None or any(f not in allow for f in files):
        out.append("dirty")
    out += [f"opt:{k}" for k, v in sorted((s.get("args") or {}).items()) if v is True and k not in QUIET_ARGS]
    return ",".join(out) or "-"


def write_manifest(runs_dir, rows, by_run, allow, path):
    out = []
    with open(path, "w", encoding="utf-8", newline="\n") as fo:
        fo.write("# g4 scene manifest 0.1 — run<TAB>split<TAB>n<TAB>flags<TAB>scene_seq (comma list)\n")
        for r in rows:
            seqs = by_run.get(r["run"])
            if not seqs:
                continue
            s, _ = settings(runs_dir, r["run"])
            m = {"run": r["run"], "split": r["split"], "n": len(seqs), "flags": flags_of(s, allow), "seqs": seqs}
            fo.write(f"{m['run']}\t{m['split']}\t{m['n']}\t{m['flags']}\t{','.join(map(str, m['seqs']))}\n")
            out.append(m)
    return out


def scenes_of(runs_dir, run, want):
    found = {}
    for line in open(runs_dir / f"{run}.ctl.jsonl", encoding="utf-8"):
        m = re.search(r'"seq": (\d+)', line)
        if m and int(m.group(1)) in want:
            d = json.loads(line)
            if d.get("seq") in want:
                found[d["seq"]] = d
    return found


def diff_touches(runs_dir, run, s):
    """Uncommitted diff: does it change souls/duel.py / scenes.py? From <run>.diff, else settings dirty_files."""
    p = runs_dir / f"{run}.diff"
    if p.exists():
        files = set(re.findall(r"^diff --git a/(\S+) b/", p.read_text(encoding="utf-8", errors="replace"), re.M))
        src = "diff file"
    else:
        files = set((s or {}).get("code", {}).get("dirty_files") or [])
        src = "settings dirty_files (no .diff file)"
    return {"source": src,
            "duel.py": "yes" if any(f.endswith("duel.py") for f in files) else "no",
            "scenes.py": "yes" if any(f.endswith("scenes.py") for f in files) else "no"}


def extract(runs_dir, out, prefix, rows, links_path, check):
    """inv_g2_extract.py main(), with the manifest rows and links file given."""
    lk = {}
    for line in open(links_path, encoding="utf-8"):
        d = json.loads(line)
        if "scene_seq" in d:
            lk[(d["run"], d["scene_seq"])] = d["rule"]
    check.update({"manifest": {"runs": len(rows), "scenes": sum(len(r["seqs"]) for r in rows),
                               "n_matches_list": all(r["n"] == len(r["seqs"]) for r in rows)},
                  "target_check": {"not_scene": [], "missing": [], "rule_mismatch": [], "not_in_links": [],
                                   "read_failed": []}})
    tc = check["target_check"]
    recs = {}
    for r in rows:
        want = set(r["seqs"])
        try:
            found = scenes_of(runs_dir, r["run"], want)
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
        return None

    lines, miss = [], collections.Counter()
    by_split, style_by_run, arena = collections.Counter(), collections.defaultdict(collections.Counter), 0
    keys_run = collections.defaultdict(collections.Counter)
    keys_commit = collections.defaultdict(collections.Counter)
    sizes = collections.defaultdict(list)
    meta_err, dirty = {}, {}
    for r in rows:
        s, err = settings(runs_dir, r["run"])
        if err:
            meta_err[r["run"]] = err
        code, args = (s or {}).get("code", {}), (s or {}).get("args", {})
        meta = {"commit": code.get("commit"), "dirty": code.get("dirty"), "diff_sha1": code.get("diff_sha1"),
                "cmd": args.get("cmd"), "seg": args.get("seg")}
        if "dirty" in r["flags"] or code.get("dirty"):
            dirty[r["run"]] = diff_touches(runs_dir, r["run"], s)
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
    name = f"{prefix}scene_extract.jsonl" + (".gz" if total > LIMIT else "")
    if total > LIMIT:
        with gzip.open(out / name, "wb", compresslevel=9) as f:
            f.write(data)
    else:
        (out / name).write_bytes(data)

    def stat(v):
        return {"n": len(v), "mean": round(sum(v) / len(v), 2) if v else None, "min": min(v, default=None),
                "max": max(v, default=None)}

    check.update({
        "extracted": {"total": len(lines), "by_split": dict(by_split)},
        "output": {"file": name, "uncompressed_bytes": total, "written_bytes": (out / name).stat().st_size,
                   "gzip": total > LIMIT, "sha256": sha256(out / name)},
        "missing_by_field": {f: miss.get(f, 0) for f in FIELDS},
        "settings_read": meta_err or f"all {len(rows)} read",
        "style_by_run": {k: dict(v) for k, v in style_by_run.items()},
        "fight_arena_not_null": arena,
        "dirty_diff_touches": dirty,
        "sizes": {k: stat(v) for k, v in sizes.items()},
        "notes": ["hostile = hp > 0 and team != player team, within the captured chars (<= 25 m)",
                  "values are copied from the scene record as captured; meta from <runs-dir>/<run>.settings.json"],
    })
    json.dump({"by_run": {k: dict(v) for k, v in keys_run.items()},
               "by_commit": {k: dict(v) for k, v in keys_commit.items()}},
              open(out / f"{prefix}scene_fight_keys.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return name


def main():
    a = sys.argv[1:]
    runs_tsv, out = Path(a[0]), Path(a[1])
    prefix = a[a.index("--prefix") + 1] if "--prefix" in a else "g4_"
    runs_dir = Path(a[a.index("--runs-dir") + 1]) if "--runs-dir" in a else ROOT / "data" / "runs"
    allow = set(a[a.index("--allow-dirty") + 1].split(",")) if "--allow-dirty" in a else set()
    out.mkdir(parents=True, exist_ok=True)
    rows = read_runs(runs_tsv)

    write_sources(runs_dir, rows, out / f"{prefix}source_sha256.tsv")
    by_run, link_stats = links(runs_dir, rows, out / f"{prefix}scene_links.jsonl")
    man = write_manifest(runs_dir, rows, by_run, allow, out / f"{prefix}scene_manifest.tsv")
    check = {"tool_sha256": sha256(Path(__file__)),
             "built_from_sha256": {p.relative_to(ROOT).as_posix(): sha256(p) for p in SOURCES},
             "runs_tsv_sha256": sha256(runs_tsv), "allow_dirty": sorted(allow),
             "runs_listed": len(rows), "runs_unreadable": [r["run"] for r in rows if by_run.get(r["run"]) is None],
             "runs_zero_scenes": [r["run"] for r in rows if by_run.get(r["run"]) == []],
             "links": link_stats,
             "manifest_sha256": sha256(out / f"{prefix}scene_manifest.tsv"),
             "source_sha256_tsv_sha256": sha256(out / f"{prefix}source_sha256.tsv")}
    if check["runs_unreadable"]:
        check["result"] = f"{len(check['runs_unreadable'])} runs unreadable - extract stopped"
        json.dump(check, open(out / f"{prefix}scene_extract_check.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(check["result"])
        sys.exit(1)
    name = extract(runs_dir, out, prefix, man, out / f"{prefix}scene_links.jsonl", check)
    json.dump(check, open(out / f"{prefix}scene_extract_check.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(check["target_check"]["result"], check.get("extracted", {}).get("total"), name)
    if name is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
