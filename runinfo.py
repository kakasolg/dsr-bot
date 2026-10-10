"""Run settings record (docs/design-run-settings.md) — what code, arguments, constants, data and character a bot run started
with, so a run can be found and compared later without guessing the commit from the time of day.

  run.py writes data/runs/<stamp>_<cmd>.settings.json at the start (update() adds the fight constants after the flags are
  applied, and the character), end() adds the result. The first log line is short() — it travels with the log when the
  log is copied to data/samples/.
  python runinfo.py <run or settings file>     print one run's settings in short

Nothing here may stop or slow a bot run: every reader returns None for what it can't read, writes never raise.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCHEMA = "dsr-run/0.1"
ROOT = Path(__file__).resolve().parent              # the repo (git) — run.py's data folder may differ (tests)
# fight / walk modules whose UPPER_CASE constants are recorded — after run.py has applied its flags (--basic etc.)
SETTINGS_MODULES = ("souls.duel", "souls.field", "souls.missions", "souls.reflex", "souls.moves", "souls.camera",
                    "souls.watch", "souls.props", "nav")
DATA_FILES = ("data/burg-upper-map.json", "data/burg-town-map.json", "data/safe-zones.json", "data/spots.json",
              "data/enemy-map.json", "data/routes/*.json", "souls/foes.py", "souls/weapons.py")
GIT_TIMEOUT = 5.0


def _now() -> str:
    """Local time with its UTC offset (time.strftime('%z') gives a zone name on some Windows builds)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def _git(root: Path, *args) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=GIT_TIMEOUT,
                           encoding="utf-8", errors="replace")
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def head(root: Path = ROOT) -> tuple[str | None, str | None]:
    """(commit, branch) read from .git — no git program needed. (None, None) if it can't be read."""
    try:
        g = root / ".git"
        h = (g / "HEAD").read_text(encoding="utf-8").strip()
        if not h.startswith("ref: "):
            return h, None
        ref = h[5:]
        branch = ref.removeprefix("refs/heads/")
        p = g / ref
        if p.exists():
            return p.read_text(encoding="utf-8").strip(), branch
        for line in (g / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0], branch
        return None, branch
    except Exception:
        return None, None


def code(root: Path = ROOT) -> tuple[dict, str | None]:
    """→ ({commit, branch, dirty, dirty_files, diff_sha1}, diff text or None). dirty None = couldn't ask git."""
    commit, branch = head(root)
    out = {"commit": commit, "branch": branch, "dirty": None, "dirty_files": None, "diff_sha1": None}
    st = _git(root, "status", "--porcelain", "--untracked-files=no")
    if st is None:
        return out, None
    files = [ln[3:].strip() for ln in st.splitlines() if ln.strip()]
    out["dirty"], out["dirty_files"] = bool(files), files
    if not files:
        return out, None
    diff = _git(root, "diff", "HEAD")
    if diff is not None:
        out["diff_sha1"] = _sha1(diff.encode("utf-8"))
    return out, diff


def _plain(v):
    if isinstance(v, (bool, int, float, str)) or v is None:
        return v
    if isinstance(v, (tuple, list)):
        return [_plain(x) for x in v]
    return repr(v)


def constants(modules=SETTINGS_MODULES) -> dict:
    """{module: {NAME: value}} — the UPPER_CASE plain values of each module (imported here if run.py hasn't yet; one that
    fails to import is left out). Read after the flags are applied, so the values are the ones the run uses."""
    out = {}
    for m in modules:
        mod = sys.modules.get(m)
        if mod is None:
            try:
                mod = importlib.import_module(m)
            except Exception:
                continue
        out[m] = {k: _plain(v) for k, v in sorted(vars(mod).items())
                  if k.isupper() and not k.startswith("_") and isinstance(v, (bool, int, float, str, tuple))}
    return out


def data_hashes(root: Path = ROOT, patterns=DATA_FILES) -> dict:
    out = {}
    for pat in patterns:
        for p in sorted(root.glob(pat)):
            try:
                out[p.relative_to(root).as_posix()] = _sha1(p.read_bytes())
            except Exception:
                out[p.relative_to(root).as_posix()] = None
    return out


def game(tm=None, mv=None, weapon=None) -> dict:
    """The character at the start — each value None if it can't be read. Reads only (no pad)."""
    def get(f):
        try:
            return f()
        except Exception:
            return None
    s = get(lambda: tm.snapshot(within=5.0)) if tm is not None else None
    p = getattr(s, "player", None)
    return {"hp": [p.hp, p.max_hp] if p is not None else None,
            "pos": [round(p.x, 2), round(p.y, 2), round(p.z, 2)] if p is not None else None,
            "weapon": [get(lambda: tm.right_weapon()), getattr(weapon, "name", None)],
            "grip": get(lambda: tm.grip()),
            "estus": get(lambda: mv.estus_left()),
            "souls": get(lambda: tm.souls()),
            "humanity": get(lambda: tm.humanity()),
            "knives": get(lambda: tm.goods_count(290)),
            "quick_items": get(lambda: tm.quick_items()),
            "last_bonfire": get(lambda: tm.last_bonfire())}


def settings_sha1(d: dict) -> str:
    """Hash of what decides behaviour — code, arguments, constants, data (not the time, the character or the end)."""
    key = {k: d.get(k) for k in ("code", "args", "constants", "data")}
    if isinstance(key["code"], dict):              # diff_file is the run's own file name (write() adds it after the first
        key["code"] = {k: v for k, v in key["code"].items() if k != "diff_file"}   # line) — diff_sha1 already covers the diff
    return _sha1(json.dumps(key, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return _sha1(json.dumps(key, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def collect(run: str, argv: list, args: dict, note: str | None = None, root: Path = ROOT) -> tuple[dict, str | None]:
    """The start record (constants and character come later with update()). → (record, diff text)."""
    c, diff = code(root)
    d = {"schema": SCHEMA, "run": run, "started": _now(),
         "code": c, "argv": [str(x) for x in argv], "args": {k: _plain(v) for k, v in sorted(args.items())},
         "constants": constants(), "data": data_hashes(root), "game": None, "note": note or ""}
    d["settings_sha1"] = settings_sha1(d)
    return d, diff


def write(path, d: dict, diff: str | None = None) -> bool:
    """Write the record (and the uncommitted diff next to it, as <run>.diff — kept in data/runs, sample.py doesn't copy it)."""
    try:
        path = Path(path)
        if diff:
            dp = path.with_name(path.name.replace(".settings.json", ".diff"))
            dp.write_text(diff, encoding="utf-8")
            d["code"]["diff_file"] = dp.name
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
        return True
    except Exception:
        return False


def read(path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def update(path, **fields) -> dict | None:
    """Add / replace top-level fields (constants after flags, game, end) and refresh settings_sha1."""
    d = read(path)
    if d is None:
        return None
    d.update(fields)
    d["settings_sha1"] = settings_sha1(d)
    write(path, d)
    return d


def end(path, **kw) -> None:
    """The end block — called once from run.py's finally (result, secs, …). A second call doesn't overwrite the first."""
    d = read(path)
    if d is None or d.get("end"):
        return
    d["end"] = {"at": _now(), **{k: _plain(v) for k, v in kw.items()}}
    write(path, d)


def short(d: dict) -> str:
    """One line for the top of the log: run · code <commit>[+dirty(n)] · <arguments> · settings <sha>."""
    c = d.get("code") or {}
    commit = (c.get("commit") or "?")[:7]
    dirty = "" if c.get("dirty") is False else "+dirty?" if c.get("dirty") is None else f"+dirty({len(c.get('dirty_files') or [])})"
    args = " ".join(d.get("argv", [])[1:]) or "-"
    note = f" · note {d['note']}" if d.get("note") else ""
    return f"run {d.get('run')} · code {commit}{dirty} · {args} · settings {d.get('settings_sha1', '')[:8]}{note}"


HEAD_RE = re.compile(r"run (\S+) · code (\S+?)(\+dirty\S*)? · (.*?) · settings (\w+)")


def head_line(log_path) -> dict | None:
    """The short() line near the top of a run log (a data/runs/*.log or a copy in data/samples/) → {run, commit, dirty,
    args, settings}. None for older logs, which don't have one."""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for _ in range(5):
                m = HEAD_RE.search(f.readline())
                if m:
                    return {"run": m[1], "commit": m[2], "dirty": bool(m[3]), "args": m[4], "settings": m[5]}
    except Exception:
        pass
    return None


def describe(log_path) -> str:
    """'code 93aff16+dirty · burg-upper --seg 5-8 --basic' for a report header — or 'no settings line (older log)'."""
    h = head_line(log_path)
    if h is None:
        return "no settings line (older log)"
    return f"code {h['commit']}{'+dirty' if h['dirty'] else ''} · {h['args']}"


def find(ref: str, runs: Path = ROOT / "data" / "runs", samples: Path = ROOT / "data" / "samples") -> Path | None:
    """A settings file from a path, a run id (<stamp>_<cmd>) or a log path."""
    p = Path(ref)
    if p.name.endswith(".settings.json") and p.exists():
        return p
    stem = p.name.split(".")[0]
    for folder in (runs, samples):
        hits = sorted(folder.glob(f"{stem}*.settings.json"))
        if hits:
            return hits[0]
    return None


_ALL: list | None = None


def covering(t_epoch: float | None, folders=(ROOT / "data" / "runs", ROOT / "data" / "samples")) -> dict | None:
    """The settings record of the bot run that was going at wall time t_epoch (started ≤ t ≤ started + end.secs + 5 s), or
    None — label_pilot uses it for a scene's commit and flags instead of guessing the commit from the time (approx)."""
    global _ALL
    if t_epoch is None:
        return None
    if _ALL is None:
        _ALL = []
        for folder in folders:
            for f in sorted(Path(folder).glob("*.settings.json")):
                d = read(f)
                try:
                    t0 = datetime.fromisoformat(d["started"]).timestamp()
                except Exception:
                    continue
                secs = ((d.get("end") or {}).get("secs")) or 4 * 3600.0
                _ALL.append((t0, t0 + secs + 5.0, d))
    return next((d for t0, t1, d in _ALL if t0 <= t_epoch <= t1), None)


def flags(d: dict) -> dict:
    """The duel flags a run used (from its constants), e.g. {"BACKSTAB": False, "HEAVY": False} for --basic."""
    c = ((d or {}).get("constants") or {}).get("souls.duel") or {}
    return {k: c[k] for k in ("BACKSTAB", "HEAVY") if k in c}


if __name__ == "__main__":
    for ref in sys.argv[1:]:
        f = find(ref)
        d = read(f) if f else None
        print(short(d) if d else f"{ref}: no settings file")
