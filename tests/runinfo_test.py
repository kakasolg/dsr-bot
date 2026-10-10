"""Run settings record (runinfo.py, sample.py, ab.py — docs/design-run-settings.md). No game.

  python tests/runinfo_test.py

Checks: commit / branch / dirty / diff from a throwaway git repo · no git → None, nothing raises · constants after a flag
(--basic) · settings_sha1 follows code / arguments / constants, not the character or the end · short() ↔ head_line() ·
end() once · writes never raise · sample.py keeps the stamp and leaves the diff behind · ab.py lists only what differs.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import ab
import runinfo
import sample
from souls import duel as D


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def git(cwd: Path, *a) -> None:
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="runinfo_"))
    try:
        repo = tmp / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "work")
        git(repo, "config", "user.email", "t@example.com")
        git(repo, "config", "user.name", "t")
        (repo / "a.py").write_text("X = 1\n", encoding="utf-8")
        git(repo, "add", "a.py")
        git(repo, "commit", "-q", "-m", "one")
        c, diff = runinfo.code(repo)
        check("clean repo: commit 40 hex, branch, dirty False, no diff",
              len(c["commit"] or "") == 40 and c["branch"] == "work" and c["dirty"] is False and diff is None)
        (repo / "a.py").write_text("X = 2\n", encoding="utf-8")
        c, diff = runinfo.code(repo)
        check("edited file: dirty True, file listed, diff text and hash", c["dirty"] is True and c["dirty_files"] == ["a.py"]
              and "+X = 2" in (diff or "") and len(c["diff_sha1"] or "") == 40)
        nogit = tmp / "nogit"
        nogit.mkdir()
        c, diff = runinfo.code(nogit)
        check("no .git: commit None, dirty None (unknown, not False), no raise", c["commit"] is None and c["dirty"] is None)

        saved = D.BACKSTAB
        try:
            d1, _ = runinfo.collect("r1", ["run.py", "x"], {"basic": False})
            D.BACKSTAB = False                                 # what run.py --basic does before collect()
            d2, _ = runinfo.collect("r1", ["run.py", "x"], {"basic": False})
        finally:
            D.BACKSTAB = saved
        check("constants after a flag: duel.BACKSTAB recorded as set", d2["constants"]["souls.duel"]["BACKSTAB"] is False)
        check("constants from duel · field · missions · nav are there",
              all(m in d1["constants"] for m in ("souls.duel", "souls.field", "souls.missions", "nav")))
        check("settings_sha1 changes with a constant", d1["settings_sha1"] != d2["settings_sha1"])
        d3 = dict(d1, game={"hp": [1, 2]}, end={"result": "x"}, started="later")
        check("settings_sha1 ignores character, end and time", runinfo.settings_sha1(d3) == d1["settings_sha1"])

        runs = tmp / "runs"
        runs.mkdir()
        sp = runs / "20261009_120000_burg-upper.settings.json"
        d, _ = runinfo.collect("20261009_120000_burg-upper", ["run.py", "burg-upper", "--seg", "5-8", "--basic"],
                               {"seg": "5-8", "basic": True}, note="save X", root=repo)
        check("write with a diff: .diff beside it, diff_file named", runinfo.write(sp, d, "diff text")
              and (runs / "20261009_120000_burg-upper.diff").read_text(encoding="utf-8") == "diff text"
              and runinfo.read(sp)["code"]["diff_file"] == "20261009_120000_burg-upper.diff")
        line = runinfo.short(d)
        log = runs / "20261009_120000_burg-upper.log"
        log.write_text(f"[    0.0] {line}\n[    0.1] 무기: …\n", encoding="utf-8")
        h = runinfo.head_line(log)
        check("short() → head_line(): run, commit, dirty, arguments", h is not None and h["run"] == "20261009_120000_burg-upper"
              and h["dirty"] is True and h["args"] == "burg-upper --seg 5-8 --basic" and h["commit"] == (d["code"]["commit"] or "?")[:7])
        check("older log (no line): head_line None, describe says so", runinfo.head_line(Path(__file__)) is None
              and "older" in runinfo.describe(Path(__file__)))
        runinfo.update(sp, game={"hp": [742, 742], "estus": 5})
        runinfo.end(sp, result="cleared", secs=12.0)
        runinfo.end(sp, result="later call", secs=99.0)
        r = runinfo.read(sp)
        check("update + end: game kept, end written once", r["game"]["estus"] == 5 and r["end"]["result"] == "cleared")
        check("writing into a missing folder: False, no raise", runinfo.write(tmp / "missing" / "x.settings.json", dict(d)) is False)
        check("update / end on a missing file: no raise", runinfo.update(tmp / "nope.json", game={}) is None
              and runinfo.end(tmp / "nope.json", result="x") is None)

        (runs / "20261009_120000_burg-upper.track.jsonl").write_text('{"type": "run"}\n', encoding="utf-8")
        samples = tmp / "samples"
        out = sample.copy("20261009_120000_burg-upper", "zone5-8", runs=runs, samples=samples)
        names = sorted(p.name for p in out)
        check("sample.py: stamp kept, log → .txt, track and settings copied", names == [
            "20261009_120000_burg-upper_zone5-8.settings.json", "20261009_120000_burg-upper_zone5-8.track.jsonl",
            "20261009_120000_burg-upper_zone5-8.txt"])
        s2 = json.loads((samples / "20261009_120000_burg-upper_zone5-8.settings.json").read_text(encoding="utf-8"))
        check("sample.py: the diff stays in data/runs (not copied, name dropped, hash kept)",
              not list(samples.glob("*.diff")) and "diff_file" not in s2["code"] and s2["code"].get("diff_kept_local") is True)
        check("sample.py: the copied log still carries the settings line", runinfo.head_line(samples / "20261009_120000_burg-upper_zone5-8.txt") is not None)

        a1 = dict(d1, args={"basic": False, "seg": "4"}, game={"hp": [742, 742], "estus": 5})
        a2 = dict(d1, args={"basic": True, "seg": "4"}, game={"hp": [742, 742], "estus": 5})
        a3 = dict(d2, args={"basic": True, "seg": "4"}, game={"hp": [700, 742], "estus": 5})
        check("ab.py: the same settings → no differences", ab.differences([a1, dict(a1)]) == {})
        check("ab.py: only args.basic differs", list(ab.differences([a1, a2])) == ["args.basic"])
        diff3 = ab.differences([a1, a3])
        check("ab.py: a constant and the start HP show up too",
              "constants.souls.duel.BACKSTAB" in diff3 and "game.hp" in diff3 and "args.basic" in diff3)
        runinfo._ALL = None
        from datetime import datetime as _dt
        t0 = _dt.fromisoformat(runinfo.read(sp)["started"]).timestamp()
        check("covering(): the run going at a time is found (with its --basic flags), outside it is not",
              (runinfo.covering(t0 + 5.0, folders=(runs,)) or {}).get("run") == "20261009_120000_burg-upper"
              and runinfo.covering(t0 + 3600.0, folders=(runs,)) is None and runinfo.covering(None) is None)
        check("flags(): duel flags from the constants", set(runinfo.flags(d2)) == {"BACKSTAB", "HEAVY"} and runinfo.flags(d2)["BACKSTAB"] is False)
        runinfo._ALL = None
        print("runinfo_test: 전부 통과")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
