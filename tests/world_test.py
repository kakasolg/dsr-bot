"""WorldState, step 1 (souls/world.py, ROADMAP worldstate). No game.

  python tests/world_test.py

Checks: the event table (byte quit-out / warp / rest / respawn revive, menu quit-out doesn't, run start unknown — P-25's
10-10 game check) · killed(): dead / alive again / unknown · since() / revived_since() · an unknown kind raises · a
`world` log event per call · Field's listener: forget_foes on every revive, loot reset on rest / respawn / warp only ·
the call sites (rest_at, wait_respawn, fight's kill, missions warp, Escape warp and quit-out, run.py run start) go
through it.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
from pathlib import Path
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from souls import field as F
from souls import world as W

ROOT = Path(__file__).resolve().parent.parent
FAILS = []


def check(what: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        FAILS.append(what)


def main() -> None:
    e = W.EVENTS
    check("revive: byte quit-out, warp, rest, respawn yes · menu quit-out no · run start unknown (P-25, 10-10)",
          e["quit_byte"]["revive"] is True and e["warp"]["revive"] is True and e["rest"]["revive"] is True
          and e["respawn"]["revive"] is True and e["quit_menu"]["revive"] is False and e["run_start"]["revive"] is None)

    logged = []
    w = W.WorldState(events=lambda ev, **k: logged.append((ev, k["kind"])))
    w.event("run_start")
    w.kill(254000, (0.0, 0.0, 0.0))
    check("killed: just killed → True; another type or far away → False",
          w.killed(254000, (2.0, 0.0, 2.0)) is True and w.killed(255010, (0.0, 0.0, 0.0)) is False
          and w.killed(254000, (30.0, 0.0, 0.0)) is False)
    n0 = w.n
    w.event("quit_menu", why="shake")
    check("menu quit-out: still dead; revived_since False", w.killed(254000, (0.0, 0.0, 0.0)) is True
          and not w.revived_since(n0) and w.since(n0) == ["quit_menu"])
    w.event("quit_byte", why="fall")
    check("byte quit-out: alive again; revived_since True", w.killed(254000, (0.0, 0.0, 0.0)) is False
          and w.revived_since(n0) and w.since(n0) == ["quit_menu", "quit_byte"])
    w.kill(254000, (0.0, 0.0, 0.0))
    w.event("run_start")
    check("killed before a run start → unknown (None)", w.killed(254000, (0.0, 0.0, 0.0)) is None)
    w.kill(254000, (0.0, 0.0, 0.0))
    w.event("run_start")
    w.event("rest")
    check("unknown then a rest → alive again (False)", w.killed(254000, (0.0, 0.0, 0.0)) is False)
    check("a world log event per call", logged[:3] == [("world", "run_start"), ("world", "quit_menu"), ("world", "quit_byte")]
          and len(logged) == w.n)
    try:
        w.event("teleport")
        check("unknown kind raises", False)
    except ValueError:
        check("unknown kind raises", True)

    # Field's listener
    calls = []
    me = NS(forget_foes=lambda: calls.append("forget"), loot=NS(reset=lambda why: calls.append(("loot", why))))
    for kind in W.EVENTS:
        calls.clear()
        F.Field._on_world(me, kind, dict(W.EVENTS[kind]))
        want = (["forget"] if W.EVENTS[kind]["revive"] else []) + ([("loot", kind)] if kind in ("rest", "respawn", "warp") else [])
        check(f"Field._on_world({kind}) → {want}", calls == want)
    calls.clear()
    me.world = None
    me._on_world = lambda k, i: F.Field._on_world(me, k, i)
    F.Field._world_event(me, "rest")
    check("a Field built without __init__ still does the old rest side effects", calls == ["forget", ("loot", "rest")])

    src = {p: (ROOT / p).read_text(encoding="utf-8") for p in ("souls/field.py", "souls/missions.py", "souls/watch.py", "run.py")}
    fs = src["souls/field.py"]
    check("rest_at · wait_respawn · fight kill go through the WorldState",
          'Field._world_event(self, "rest", why="rest_at")' in fs and 'Field._world_event(self, "respawn", why="wait_respawn")' in fs
          and "self._world_kill(ptr, r.npc)" in fs and 'self.loot.reset("rest")' not in fs
          and 'self.loot.reset("respawn")' not in fs)
    check("missions warp → world 'warp' (no direct loot reset)", 'Field._world_event(self.f, "warp", why="passage_drill")' in src["souls/missions.py"]
          and 'loot.reset("warp")' not in src["souls/missions.py"])
    ws = src["souls/watch.py"]
    check("Escape: crowd warp and a completed quit-out report to the world",
          'self.world.event("warp", why="crowd3_warp"' in ws and 'self.world.event("quit_" + res["how"], why=kind)' in ws)
    check("run.py: run start event", 'fld.world.event("run_start", why=a.cmd)' in src["run.py"])

    if FAILS:
        print(f"world_test: {len(FAILS)} 실패")
        sys.exit(1)
    print("world_test: 전부 통과")


if __name__ == "__main__":
    main()
