"""G4 collection commit record: code hashes, decision-function hashes and environment for one commit (read only).

python experiments/g4_2026_10_31/collection_hashes.py <out.json> [--commit C] [--game-exe <path>]

File hashes are of the git blob (`git show C:<path>`), not the working tree: core.autocrlf=true checks files out with
CRLF, so a working-tree sha256 differs from the blob for every file that has line ends. Function hashes are sha1 of
ast.get_source_segment on the blob source (the G2 definition: 742caf · 3e9d1b · ddf6e3 · ed2af2 · RULES bc4c02).
"""
import ast
import hashlib
import importlib.metadata as md
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FILES = ["scenes.py", "souls/duel.py", "souls/foes.py", "souls/weapons.py", "souls/moves.py", "souls/reflex.py",
         "control.py", "dsr_telemetry.py", "feed.py", "run.py", "ctl.py", "ctlspan.py", "runinfo.py", "savepoint.py",
         "ctl_check.py", "scene_replay.py"]
FUNCS = ["rule_stagger_punish", "_stagger_late", "_other_swinging", "prep_reflex"]
G2 = {"rule_stagger_punish": "742caf", "_stagger_late": "3e9d1b", "_other_swinging": "ddf6e3", "prep_reflex": "ed2af2",
      "RULES": "bc4c02", "scenes.py": "065f4717"}
PACKAGES = ["vgamepad", "pymem", "numpy", "pytest", "soulstruct", "pillow", "zstandard"]


def git(*a) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout


def blob(commit: str, path: str) -> bytes:
    return subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT, capture_output=True, check=True).stdout


def func_hashes(src: str) -> dict:
    out = {}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in FUNCS:
            out[node.name] = hashlib.sha1(ast.get_source_segment(src, node).encode()).hexdigest()
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "RULES" for t in node.targets):
            out["RULES"] = hashlib.sha1(ast.get_source_segment(src, node).encode()).hexdigest()
    return out


def main():
    args = sys.argv[1:]
    out = Path(args[0])
    commit = args[args.index("--commit") + 1] if "--commit" in args else "HEAD"
    exe = Path(args[args.index("--game-exe") + 1]) if "--game-exe" in args else None
    full = git("rev-parse", commit).strip()

    files = {p: hashlib.sha256(blob(full, p)).hexdigest() for p in FILES}
    fh = func_hashes(blob(full, "souls/duel.py").decode("utf-8"))
    missing = [n for n in FUNCS + ["RULES"] if n not in fh]
    if missing:
        raise SystemExit(f"not found in souls/duel.py: {missing}")
    same = {k: (fh.get(k) or files.get(k, "")).startswith(v) for k, v in G2.items()}

    dirty = [ln[3:].strip() for ln in git("status", "--porcelain", "--untracked-files=no").splitlines() if ln.strip()]
    head = git("rev-parse", "HEAD").strip()
    pk = {}
    for p in PACKAGES:
        try:
            pk[p] = md.version(p)
        except md.PackageNotFoundError:
            pk[p] = None
    game = None
    if exe is not None:
        game = {"path": str(exe), "size": exe.stat().st_size, "sha256": hashlib.sha256(exe.read_bytes()).hexdigest()}

    rec = {
        "schema": "g4-collection-hashes/0.1",
        "commit": full,
        "branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
        "worktree_at_commit": head == full,
        "worktree_dirty_tracked": dirty,
        "core_autocrlf": git("config", "--get", "core.autocrlf").strip() or None,
        "file_sha256_git_blob": files,
        "duel_sha1_source_segment": fh,
        "same_as_g2_prefix": same,
        "python": {"executable": sys.executable, "version": platform.python_version()},
        "packages": pk,
        "game_exe": game,
        "tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(full[:12], "same as G2:", same, "dirty:", dirty)


if __name__ == "__main__":
    main()
