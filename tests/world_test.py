"""WorldState, step 1 (souls/world.py, ROADMAP worldstate). No game.

  python tests/world_test.py

Checks: the event table (byte quit-out / warp / rest / respawn revive, menu quit-out doesn't, run start unknown — P-25's
10-10 game check) · killed(): dead / alive again / unknown · since() / revived_since() · an unknown kind raises · a
`world` log event per call · Field's listener: forget_foes on every revive, loot reset on rest / respawn / warp only ·
the call sites (rest_at, wait_respawn, missions warp, Escape warp and quit-out, run.py run start) go through it.
Step 2: Moves' death detector (two zero-HP snapshots, once per ptr until revived, cleared on a load) · kill dedupe ·
pass_ramp scans for survivors after a byte quit-out even when 'cleared' · passage_drill stops if its warp revived the ramp.
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
    check("rest_at · wait_respawn go through the WorldState",
          'Field._world_event(self, "rest", why="rest_at")' in fs and 'Field._world_event(self, "respawn", why="wait_respawn")' in fs
          and 'self.loot.reset("rest")' not in fs
          and 'self.loot.reset("respawn")' not in fs)
    check("missions warp → world 'warp' (no direct loot reset)", 'Field._world_event(self.f, "warp", why="passage_drill")' in src["souls/missions.py"]
          and 'loot.reset("warp")' not in src["souls/missions.py"])
    ws = src["souls/watch.py"]
    check("Escape: crowd warp and a completed quit-out report to the world",
          'self.world.event("warp", why="crowd3_warp"' in ws and 'self.world.event("quit_" + res["how"], why=kind)' in ws)
    check("run.py: run start event", 'fld.world.event("run_start", why=a.cmd)' in src["run.py"])

    # ── step 2: one death detector in Moves.snap; readers ──
    from souls import missions as MS
    from souls import moves as M
    snaps = []
    tm = NS(snapshot=lambda within=40.0: snaps.pop(0))
    mv = object.__new__(M.Moves)
    mv.tm = tm
    got = []
    mv.on_death = lambda c: got.append(c.ptr)
    ch = lambda ptr, hp: NS(ptr=ptr, hp=hp, anim=-1, npc_param=254000, x=0.0, y=0.0, z=0.0)
    for t, chars in ((1.0, [ch(1, 80), ch(2, 0)]), (1.1, [ch(1, 0), ch(2, 0)]), (1.1, [ch(1, 0)]),
                     (1.2, [ch(1, 0)]), (1.3, [ch(1, 0)]), (1.4, [ch(1, 50)]), (1.5, [ch(1, 0)]), (1.6, [ch(1, 0)])):
        snaps.append(NS(t=t, chars=chars))
        mv.snap()
    check("detector: alive then HP 0 in two snapshots with different times → once; a corpse never seen alive → never; "
          "alive again (revived, same ptr) → once more", got == [1, 1])
    w2 = W.WorldState()
    w2.kill(254000, (0, 0, 0), ptr=1)
    w2.kill(254000, (0, 0, 0), ptr=1)
    w2.event("rest")
    w2.kill(254000, (0, 0, 0), ptr=1)
    check("kill: the same ptr is noted once until a revive", len(w2.kills) == 2)
    me2 = NS(forget_foes=lambda: None, loot=None, mv=NS(_deaths={1: [True, 0, None, False]}))
    F.Field._on_world(me2, "warp", dict(W.EVENTS["warp"]))
    me3 = NS(forget_foes=lambda: None, loot=None, mv=NS(_deaths={1: [True, 0, None, False]}))
    F.Field._on_world(me3, "rest", dict(W.EVENTS["rest"]))
    check("a load (ptrs change) clears the detector; a rest doesn't", "_deaths" not in vars(me2.mv) and "_deaths" in vars(me3.mv))
    fs2 = (ROOT / "souls" / "field.py").read_text(encoding="utf-8")
    check("Field hands Moves its on_death → WorldState.kill; the per-fight _world_kill is gone",
          "mv.on_death = lambda c: self.world.kill(c.npc_param, (c.x, c.y, c.z), ptr=c.ptr)" in fs2 and "_world_kill" not in fs2)

    def ramp_fake(results, events, alive):
        m = object.__new__(MS.Missions)
        m.lines = []
        m.log = m.lines.append
        m.f = NS(world=W.WorldState())
        m.calls = 0

        def clear(lure=None):
            for k in events[min(m.calls, len(events) - 1)]:
                m.f.world.event(k)
            r = results[min(m.calls, len(results) - 1)]
            m.calls += 1
            return r
        m.clear_ramp = clear
        m.ramp_survivors = lambda: alive[min(m.calls - 1, len(alive) - 1)]
        return m
    LIVE = [NS(npc_param=254000)]
    m = ramp_fake(["cleared"], [["quit_byte"], []], [LIVE, []])
    check("pass_ramp: 'cleared' after a byte quit-out with ramp foes alive → clear again (P-25 gap)",
          m.pass_ramp() == (True, "cleared") and m.calls == 2 and any("quit_byte" in x for x in m.lines))
    m = ramp_fake(["cleared"], [["quit_menu"]], [LIVE])
    check("pass_ramp: 'cleared' after a menu quit-out → as before (no scan, no retry)", m.pass_ramp() == (True, "cleared") and m.calls == 1)
    m = ramp_fake(["cleared"], [["quit_byte"]], [LIVE])
    ok, r = m.pass_ramp()
    check("pass_ramp: survivors after every retry → stop", ok is False and "살아 있는 적 남음" in r and m.calls == 1 + MS.RAMP_RETRIES)
    m = ramp_fake(["cleared"], [["quit_byte"]], [[]])
    check("pass_ramp: byte quit-out but nobody alive → pass", m.pass_ramp() == (True, "cleared") and m.calls == 1)

    # passage_drill (P-55): after its warp, ramp foes alive → stop before walking up
    m = object.__new__(MS.Missions)
    m.lines = []
    m.log = m.lines.append
    m.nms = {MS.MAP_A: None}
    walks = []
    m.f = NS(world=W.WorldState(), walk_to=lambda *a, **k: walks.append(a[2]) or "arrived", walk=lambda *a, **k: "arrived")
    m.f._on_world = lambda k, i: None
    m.mv = NS(tm=NS(bonfire_warp=lambda bid, log=None: True))
    MS.time.sleep, sleep0 = (lambda x: None), MS.time.sleep
    route0, corner0 = MS._route, MS._with_entry_corner
    MS._route = lambda: ((0.0, 0.0, 0.0), [tuple(MS.PASSAGE_A0)] * 5, None)   # no game NavMesh here
    MS._with_entry_corner = lambda r: list(r)
    try:
        m.ramp_survivors = lambda: LIVE
        r = m.passage_drill(rounds=2)
        check("passage_drill: warp → ramp foes alive → stops before the top (P-55)", r == "드릴 1 경사로 되살아남 1" and not walks
              and any("P-55" in x for x in m.lines))
        m.ramp_survivors = lambda: []
        walks.clear()
        r = m.passage_drill(rounds=2)
        check("passage_drill: warp → nobody alive → walks as before", r == "done" and len(walks) == 2)
    finally:
        MS.time.sleep = sleep0
        MS._route, MS._with_entry_corner = route0, corner0

    if FAILS:
        print(f"world_test: {len(FAILS)} 실패")
        sys.exit(1)
    print("world_test: 전부 통과")


if __name__ == "__main__":
    main()
