"""Copy one bot run from data/runs/ into data/samples/ with its timestamp kept in the name (docs/design-run-settings.md 3.4).

  python sample.py                          the newest run
  python sample.py 20261006_200335_burg-upper [zone5-8]
  python sample.py data/runs/20261006_200335_burg-upper.log

Copies <run>.log → data/samples/<run>[_name].txt, <run>.track.jsonl and <run>.settings.json beside it. The uncommitted diff
(<run>.diff) stays in data/runs/ — the repo is public; the settings file keeps the changed file names and the diff's hash.
Older sample names (<what>-<date><letter>) are left as they are.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
RUNS, SAMPLES = ROOT / "data" / "runs", ROOT / "data" / "samples"
COPY = ((".log", ".txt"), (".track.jsonl", ".track.jsonl"), (".settings.json", ".settings.json"))


def newest(runs: Path = RUNS) -> str | None:
    logs = sorted(runs.glob("*.log"), key=lambda p: p.stat().st_mtime)
    return logs[-1].name.removesuffix(".log") if logs else None


def copy(run: str, name: str = "", runs: Path = RUNS, samples: Path = SAMPLES) -> list[Path]:
    """→ the files written. A settings file is copied without the diff's file name (the diff isn't copied)."""
    run = Path(run).name.split(".")[0]
    stem = f"{run}_{name}" if name else run
    samples.mkdir(parents=True, exist_ok=True)
    out = []
    for src_ext, dst_ext in COPY:
        src = runs / f"{run}{src_ext}"
        if not src.exists():
            continue
        dst = samples / f"{stem}{dst_ext}"
        if src_ext == ".settings.json":
            try:
                d = json.loads(src.read_text(encoding="utf-8"))
                if (d.get("code") or {}).pop("diff_file", None):
                    d["code"]["diff_kept_local"] = True
                dst.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            except Exception:
                shutil.copyfile(src, dst)
        else:
            shutil.copyfile(src, dst)
        out.append(dst)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run", nargs="?", help="run id (<stamp>_<cmd>) or a file of it; default: the newest run")
    ap.add_argument("name", nargs="?", default="", help="optional suffix, e.g. zone5-8")
    a = ap.parse_args()
    run = a.run or newest()
    if not run:
        print("no runs in data/runs/")
        return
    files = copy(run, a.name)
    if not files:
        print(f"{run}: nothing to copy (no .log / .track.jsonl / .settings.json in data/runs/)")
        return
    for f in files:
        print(f"  → {f.relative_to(ROOT)}")
    if not any(f.name.endswith(".settings.json") for f in files):
        print("  (no settings file — a run from before runinfo)")


if __name__ == "__main__":
    main()
