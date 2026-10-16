"""Foe AI scripts from the game files — the Lua goals that pick a foe's next action (combat-table step 3).

  python ai_extract.py c2540                 goals of every c2540 foe in data/gamefiles/m*.json → data/gamefiles/ai/
  python ai_extract.py --goals 254000 10000  these goal ids
  python ai_extract.py c2540 --common        also every loose script in aiCommon (shared helper functions)

[win] only: decompiling runs soulstruct's DSLuaDecompiler.exe (Windows). Reads script/*.luabnd.dcx (DSR install folder,
DSR_GAME_DIR like navmesh.py). Which goals: NpcThinkParam BattleID / LogicID of the model's foes (msb_extract wrote them
under `think`; c2540 in m10_01: battle 254000 · 254001 · 254002, logic 10000).

Writes data/gamefiles/ai/<goal name>.lua (decompiled, UTF-8) and data/gamefiles/ai/index.json: per goal its id, type, the
luabnd it came from, whether decompiling worked, and the functions the script calls that it does not define (to
pull in next — usually helpers in aiCommon). Evidence grade "file". The decompiled text is the decompiler's reading of the
bytecode: names of locals are lost, control flow can look odd — read it as a draft, check odd spots against play.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import navmesh   # noqa: F401 — stubs the soulstruct modules whose data files the wheel lacks (see navmesh.py)
from navmesh import GAME_DIR

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "gamefiles" / "ai"
_CALL = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\s*\(")
_DEF = re.compile(r"\bfunction\s+([A-Za-z0-9_.:]+)\s*\(")
LUA_BUILTINS = {"math", "string", "table"}


def goal_ids_for(model: str, folder: Path = ROOT / "data" / "gamefiles") -> set[int]:
    """BattleID / LogicID of every foe of this model in msb_extract's m*.json."""
    ids = set()
    for f in sorted(folder.glob("m*.json")):
        for e in json.loads(f.read_text(encoding="utf-8")).get("enemies", []):
            if e.get("model") == model and e.get("think"):
                for k in ("BattleID", "LogicID"):
                    v = e["think"].get(k)
                    if v is not None and v >= 0:
                        ids.add(int(v))
    return ids


def calls(script: str) -> dict:
    """Functions a script defines and the capitalised calls it makes but does not define (the next scripts to pull)."""
    defined = {d.split(".")[-1].split(":")[-1] for d in _DEF.findall(script)}
    called = set(_CALL.findall(script)) - LUA_BUILTINS
    return {"defines": sorted(defined), "calls_outside": sorted(called - defined)}


def pick(luabnds: dict, goal_ids: set[int], common: bool) -> list[tuple[str, object, str]]:
    """[(luabnd name, script object, kind)] — goals with a wanted id; with `common`, aiCommon's loose scripts too."""
    out = []
    for name, bnd in luabnds.items():
        for g in bnd.goals:
            if g.goal_id in goal_ids:
                out.append((name, g, "goal"))
        if common and "aicommon" in name.lower():
            for s in getattr(bnd, "unknown_scripts", []) or []:
                out.append((name, s, "common"))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model", nargs="?", help="e.g. c2540")
    ap.add_argument("--goals", nargs="*", type=int, default=[])
    ap.add_argument("--common", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    goal_ids = set(a.goals) | (goal_ids_for(a.model) if a.model else set())
    if not goal_ids and not a.common:
        raise SystemExit("goal id 없음 — 모델 이름(c2540)이나 --goals 를 주세요")
    from soulstruct.base.ai.luabnd import LuaBND
    luabnds = {}
    for p in sorted((GAME_DIR / "script").glob("*.luabnd.dcx")):
        try:
            luabnds[p.name] = LuaBND.from_path(p)
        except Exception as ex:
            print(f"경고: {p.name} 못 읽음 ({type(ex).__name__}: {ex})")
    a.out.mkdir(parents=True, exist_ok=True)
    index = []
    for bnd_name, s, kind in pick(luabnds, goal_ids, a.common):
        name = getattr(s, "goal_name", "") or getattr(s, "script_name", "") or "unnamed"
        row = {"name": name, "kind": kind, "goal_id": getattr(s, "goal_id", None),
               "goal_type": str(getattr(s, "goal_type", "")), "luabnd": bnd_name}
        try:
            if not s.script:
                s.decompile()
            (a.out / f"{name}.lua").write_text(s.script, encoding="utf-8")
            row.update({"ok": True, "lines": s.script.count("\n") + 1, **calls(s.script)})
        except Exception as ex:
            row.update({"ok": False, "error": f"{type(ex).__name__}: {ex}"})
        index.append(row)
        print(f"{bnd_name} {kind} {row['goal_id']} {name}: " + (f"{row['lines']} 줄" if row["ok"] else row["error"]))
    found = {r["goal_id"] for r in index if r["kind"] == "goal"}
    (a.out / "index.json").write_text(json.dumps({"evidence": "file", "model": a.model, "goal_ids": sorted(goal_ids),
                                                  "missing": sorted(goal_ids - found), "scripts": index},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"스크립트 {len(index)} (실패 {sum(1 for r in index if not r['ok'])}), 못 찾은 goal {sorted(goal_ids - found)} → {a.out}")


if __name__ == "__main__":
    main()
