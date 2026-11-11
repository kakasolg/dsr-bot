"""Run settings object, step 1 (settings.py, ROADMAP settings-object). No game.

  python tests/settings_test.py

Checks: for every run.py flag combination the constants after Settings.from_args(a).apply() are the ones the old run.py
blocks produced (copied below as `old_blocks`) · restore() / applied() put the defaults back · a name the module lacks
is an error · to_dict() holds only what changed · runinfo.collect records the overrides and levelup / kindle constants ·
run.py writes no module constant itself any more. Step 2: duel.py's rules read F.flags (duel.Flags) — no bare global
reads left, Flags given / fallback / read-only, Fight / Field defaults, the wiring run.py → Field → duel(flags=).
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import itertools
import re
import sys
from pathlib import Path
from types import SimpleNamespace

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import kindle
import levelup
import runinfo
import settings
from souls import duel, field

ROOT = Path(__file__).resolve().parent.parent
WATCH = [(duel, "BACKSTAB"), (duel, "HEAVY"), (duel, "FOOTING"), (duel, "COMBO_ONLY"), (duel, "DRILL"),
         (field, "NOTICE_PULL"), (levelup, "WANT"), (kindle, "ON")]
FAILS = []


def check(what: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        FAILS.append(what)


def state() -> dict:
    return {f"{m.__name__}.{k}": getattr(m, k) for m, k in WATCH}


def old_blocks(a) -> None:
    """run.py before 11-10 (1b9c7ee), the blocks settings.py replaced."""
    if a.level_up:
        levelup.WANT = a.level_up.upper()
    if a.kindle:
        kindle.ON = True
    if a.basic:
        duel.BACKSTAB, duel.HEAVY = False, False
    if a.pull:
        field.NOTICE_PULL = True
    if a.footing:
        duel.FOOTING = True
    if a.combo_only or a.drill:
        duel.COMBO_ONLY = True
        duel.DRILL = a.drill


def args(**kw):
    base = dict(basic=False, pull=False, footing=False, combo_only=False, drill=None, level_up=None, kindle=False)
    return SimpleNamespace(**{**base, **kw})


def main() -> None:
    default = state()
    choices = [("basic", [False, True]), ("pull", [False, True]), ("footing", [False, True]),
               ("combo_only", [False, True]), ("drill", [None, "roll_r1"]), ("level_up", [None, "vit"]),
               ("kindle", [False, True])]
    same, n = 0, 0
    for combo in itertools.product(*[v for _k, v in choices]):
        a = args(**dict(zip([k for k, _v in choices], combo)))
        old_blocks(a)
        want = state()
        for m, k in WATCH:                                   # back to defaults by hand
            setattr(m, k, default[f"{m.__name__}.{k}"])
        s = settings.Settings.from_args(a).apply()
        got = state()
        s.restore()
        n += 1
        same += got == want
        if got != want:
            print("   differs:", combo, {k: (want[k], got[k]) for k in want if want[k] != got[k]})
    check(f"every flag combination gives the old blocks' constants ({same}/{n})", same == n)
    check("restore() puts every default back", state() == default)

    s = settings.Settings.from_args(args(basic=True, drill="jump_r2"))
    check("to_dict(): only what changed",
          s.to_dict() == {"souls.duel": {"BACKSTAB": False, "COMBO_ONLY": True, "DRILL": "jump_r2", "HEAVY": False}})
    with s.applied():
        inside = (duel.BACKSTAB, duel.DRILL)
    check("applied(): set inside, defaults after", inside == (False, "jump_r2") and state() == default)
    check("no flags → no overrides", settings.Settings.from_args(args()).to_dict() == {})
    try:
        settings.Settings({"souls.duel": {"BACKSTABB": False}}).apply()
        check("a misspelt name raises", False)
    except AttributeError:
        check("a misspelt name raises", state() == default)

    with settings.Settings.from_args(args(level_up="vit", kindle=True)).applied() as s:
        rec, _diff = runinfo.collect("t", ["run.py"], {"level_up": "vit"}, overrides=s.to_dict(), root=ROOT)
    check("runinfo: overrides recorded", rec.get("overrides") == {"kindle": {"ON": True}, "levelup": {"WANT": "VIT"}})
    check("runinfo: levelup / kindle constants recorded",
          rec["constants"]["levelup"]["WANT"] == "VIT" and rec["constants"]["kindle"]["ON"] is True)
    check("runinfo: no overrides argument → no field (older callers)",
          "overrides" not in runinfo.collect("t", ["run.py"], {}, root=ROOT)[0])

    src = (ROOT / "run.py").read_text(encoding="utf-8")
    writes = re.findall(r"^\s+(?:duel_\w*|field_\w*|levelup|kindle)\.[A-Z][A-Z0-9_]*\s*(?:,|=[^=])", src, re.M)
    check("run.py sets no fight / walk / levelup / kindle constant itself", not writes)

    # step 2: the fight rules read F.flags (duel.Flags), not the module globals
    import ast
    from souls import field as field_mod
    tree = ast.parse((ROOT / "souls" / "duel.py").read_text(encoding="utf-8"))
    bare = sorted({(fn.name, n.id) for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
                   for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id in duel.Flags.NAMES and isinstance(n.ctx, ast.Load)})
    check(f"duel.py: no function reads a flag as a module global ({bare})", not bare)
    fsrc = (ROOT / "souls" / "field.py").read_text(encoding="utf-8")
    check("field.py: no D.COMBO_ONLY / D.DRILL / … reads",
          not re.findall(r"\bD\.(?:" + "|".join(duel.Flags.NAMES) + r")\b", fsrc))
    f = duel.Flags(HEAVY=False, DRILL="roll_r1")
    check("Flags: given values win, the rest follow the module globals",
          f.HEAVY is False and f.DRILL == "roll_r1" and f.BACKSTAB is duel.BACKSTAB)
    old = duel.BACKSTAB
    duel.BACKSTAB = not old
    live = duel.Flags().BACKSTAB
    duel.BACKSTAB = old
    check("Flags(): an unset flag reads the global at that moment (tests that set duel.X keep working)", live is (not old))
    try:
        duel.Flags(HEAVYY=False)
        check("Flags: an unknown name raises", False)
    except AttributeError:
        check("Flags: an unknown name raises", True)
    try:
        f.HEAVY = True
        check("Flags: read-only", False)
    except AttributeError:
        check("Flags: read-only", f.HEAVY is False)
    check("a Fight made without __init__ (scene_replay) and Field default read the globals",
          duel.Fight.flags.values() == duel.Flags().values() and field_mod.Field.flags.values() == duel.Flags().values())
    import inspect
    check("duel() and Fight take flags; Field passes its own; run.py sets Field.flags from the Settings",
          "flags" in inspect.signature(duel.duel).parameters and "flags" in inspect.signature(duel.Fight.__init__).parameters
          and "flags=self.flags" in fsrc and "fld.flags = duel_flags.Flags(**run_settings.overrides" in src)
    s2 = settings.Settings.from_args(args(basic=True, drill="jump_r2"))
    fl = duel.Flags(**s2.overrides.get("souls.duel", {}))
    check("Flags from the Settings = what the flags mean (--basic --drill jump_r2)",
          (fl.BACKSTAB, fl.HEAVY, fl.COMBO_ONLY, fl.DRILL) == (False, False, True, "jump_r2") and state() == default)

    # step 3: run.py no longer applies the overrides to module globals; every reader of a FLAGS value has the run's object
    check("run.py builds the Settings without apply()",
          "Settings.from_args(a)" in src and "Settings.from_args(a).apply()" not in src and ".apply()" not in src)
    check("run.py hands the Settings to Moves and Field",
          "mv.settings = run_settings" in src and "fld.settings = run_settings" in src)
    st = settings.Settings.from_args(args(pull=True, level_up="end", kindle=True))
    check("Settings.get: the override, else the module's value now",
          st.get("souls.field", "NOTICE_PULL") is True and st.get("levelup", "WANT") == "END" and st.get("kindle", "ON") is True
          and st.get("souls.field", "GROUP_R") == field.GROUP_R and state() == default)
    for f_, names in (("souls/field.py", {"NOTICE_PULL"}), ("levelup.py", {"WANT"}), ("kindle.py", {"ON"})):
        t = ast.parse((ROOT / f_).read_text(encoding="utf-8"))
        loads = sorted({(fn.name, n.lineno) for fn in ast.walk(t) if isinstance(fn, ast.FunctionDef) for n in ast.walk(fn)
                        if isinstance(n, ast.Name) and n.id in names and isinstance(n.ctx, ast.Load)})
        allowed = {"levelup.py": {"maybe"}, "kindle.py": {"maybe"}}.get(f_, set())   # the `None → module value` fallback
        check(f"{f_}: no other function reads {sorted(names)} as a global ({loads})", {fn for fn, _ in loads} <= allowed)
    check("field.py reads NOTICE_PULL through self.settings (2 places)",
          fsrc.count('self.settings.get("souls.field", "NOTICE_PULL")') == 2)
    farm_src = (ROOT / "farm.py").read_text(encoding="utf-8")
    mv_src = (ROOT / "souls" / "moves.py").read_text(encoding="utf-8")
    mi_src = (ROOT / "souls" / "missions.py").read_text(encoding="utf-8")
    check("Moves.rest → farm.rest(settings=) → kindle.maybe(on=) / levelup.maybe(want=); missions passes want",
          'settings=getattr(self, "settings", None)' in mv_src and 'on=settings.get("kindle", "ON")' in farm_src
          and 'want=settings.get("levelup", "WANT")' in farm_src and 'want=st.get("levelup", "WANT")' in mi_src)

    class _Tm:
        def last_bonfire(self):
            return 0                                      # not the Burg bonfire
    check("kindle.maybe(on=False) stops before reading the game; on=None follows kindle.ON (off)",
          kindle.maybe(None, None, None, None, on=False) is None and kindle.maybe(None, None, None, None) is None)
    check("kindle.maybe(on=True) goes on to the bonfire check (not the Burg one → None)",
          kindle.maybe(_Tm(), None, None, None, on=True) is None)
    check("levelup.maybe(want='') / want=None with WANT None → no level-up", levelup.maybe(None, None, want="") is None
          and levelup.maybe(None, None) is None)

    rec3, _ = runinfo.collect("t", ["run.py"], {}, overrides=st.to_dict(), root=ROOT)
    check("runinfo: constants = module defaults overlaid with the overrides (globals untouched)",
          rec3["constants"]["souls.field"]["NOTICE_PULL"] is True and rec3["constants"]["levelup"]["WANT"] == "END"
          and rec3["constants"]["kindle"]["ON"] is True and field.NOTICE_PULL is False and state() == default)

    if FAILS:
        print(f"settings_test: {len(FAILS)} 실패")
        sys.exit(1)
    print("settings_test: 전부 통과")


if __name__ == "__main__":
    main()
