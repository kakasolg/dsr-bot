"""Setup and teardown for the one-hollow probes (tae_verify probe3 / probe4, options_pilot run) — MoKa 2026-10-19: one
command instead of seven hand steps (10-19 runs: two prechecks failed — A not there yet, start HP 9 — and P-88).

  prep(tm, save)   savepoint restore → PlayerNoDead on → NavMesh walk to 3.5 m of the sleeping hollow A → light attacks
                   facing AWAY from it until it wakes (facing it killed A twice: B-8, 10-19) → warp back to the start spot →
                   wait until A is within WAIT_D and acting → HP full. Returns {"home": (x, y, z, heading), "ok", "why"}.
  finish(tm)       menu quit-out + Continue with PlayerNoDead still on (A goes back to sleep at its spot), then the flag
                   back to what it was before prep (P-88: switching it off next to an awake A killed the player twice).

Game-memory writes (PlayerNoDead, warp, HP) — offline only, like the probes themselves. The reader threads that
`env.make_telemetry` / savepoint start (feed.Feed) are stopped afterwards: left running they cut the probe's read rate to
~40 % (10-19 try 4).
"""
from __future__ import annotations

import math
import time

NPC_A = 254010          # c2540 sword hollow A (options-pilot save: asleep at (−15.9, −13.4, −58.7))
MAP = "m10_01_00_00"    # Undead Burg NavMesh
WAKE_D = 3.5            # walk this close before the whiffs (B-11)
WAIT_D = 3.0            # A counts as arrived within this (m)
HP_FULL = 793


def stop_feed() -> None:
    """Stop the shared reader thread env.make_telemetry starts (savepoint, Moves callers) — it slows the probe's reads."""
    import env
    f = getattr(env, "_feed", None)
    if f is not None:
        f.stop()
        env._feed = None


def heading_to(px: float, pz: float, tx: float, tz: float) -> float:
    """+0x4 heading that faces (tx, tz): world yaw = heading + π, direction (sin yaw, cos yaw) in x-z (dsr_telemetry.face)."""
    return math.atan2(tx - px, tz - pz) - math.pi


def wake(tm, pad, npc: int = NPC_A, log=print) -> int | None:
    """Walk to WAKE_D of the sleeping foe and whiff facing away until it acts or moves. → its ptr, None if not found."""
    import navmesh
    from souls import moves as M
    s = tm.snapshot(40)
    a = next((c for c in s.hostile(40) if c.npc_param == npc), None) if s else None
    if a is None:
        log(f"  {npc} 없음 (40 m)")
        return None
    ptr = a.ptr
    d = math.hypot(s.player.x - a.x, s.player.z - a.z) or 1.0
    goal = (a.x + WAKE_D * (s.player.x - a.x) / d, a.y, a.z + WAKE_D * (s.player.z - a.z) / d)
    nm = navmesh.Navmesh(MAP)
    mv = M.Moves(tm, pad)                       # the plain reader, no Feed thread
    r = mv.walk_path(nm.find_path((s.player.x, s.player.y, s.player.z), goal), nm,
                     stop=lambda sn: (lambda cc: cc is not None and M.horiz(sn.player, cc) <= WAKE_D)(mv.find(sn, ptr)))
    pad.move(0.0, 0.0)
    a = tm.read_chr(ptr)
    x0, z0 = a.x, a.z
    for k in range(6):
        s = tm.snapshot(40)
        a = tm.read_chr(ptr)
        if a.anim not in (-1, None) or math.hypot(a.x - x0, a.z - z0) > 0.5:
            log(f"  깨움: 헛스윙 {k}번 (걷기 {r}, 애니 {a.anim}, HP {a.hp})")
            return ptr
        tm.face(pad, heading_to(s.player.x, s.player.z, a.x, a.z) + math.pi)
        pad.attack()
        time.sleep(1.6)
    log("  헛스윙 6번에도 안 깸")
    return ptr


def prep(tm, save: str, npc: int = NPC_A, wait_s: float = 60.0, log=print) -> dict:
    import control
    import savepoint
    savepoint.cmd_restore(save)                 # SystemExit when it can't — nothing was changed in the game then
    stop_feed()
    out = {"save": save, "nodead_before": tm.get_dbg(tm.DBG_PLAYER_NO_DEAD), "ok": False, "why": ""}
    tm.set_dbg(tm.DBG_PLAYER_NO_DEAD, True)
    pad = control.Pad()
    try:
        s = tm.snapshot(40)
        out["home"] = (s.player.x, s.player.y, s.player.z, s.player.heading or 0.0)
        ptr = wake(tm, pad, npc, log)
        stop_feed()
        if ptr is None:
            out["why"] = "no_target"
            return out
        time.sleep(1.0)
        tm.pos_warp(*out["home"])
        t0, a, dd = time.perf_counter(), None, None
        while time.perf_counter() - t0 < wait_s:
            s = tm.snapshot(40)
            a = tm.read_chr(ptr)
            if s and a and time.perf_counter() - t0 > 0.5:      # the warp lands a frame or more later
                dd = math.hypot(s.player.x - a.x, s.player.z - a.z)
                if dd <= WAIT_D and a.anim not in (-1, None):
                    break
            time.sleep(0.1)
        out["wait_s"] = round(time.perf_counter() - t0, 1)
        out["ok"] = dd is not None and dd <= WAIT_D
        out["why"] = "" if out["ok"] else f"A not within {WAIT_D} m after {wait_s:.0f} s ({dd})"
        tm.set_hp(HP_FULL)
        log(f"  준비: A {dd:.1f} m, {out['wait_s']} s 기다림, HP {HP_FULL}, 시작 자리 "
            + " ".join(f"{v:.3f}" for v in out["home"]) if dd is not None else "  준비: A 안 보임")
        return out
    finally:
        pad.release_all()


def finish(tm, nodead_before: int = 0, log=print) -> dict:
    """Menu quit-out + Continue with PlayerNoDead on, then the flag back. → where the player ended up."""
    import control
    import savepoint
    tm.set_dbg(tm.DBG_PLAYER_NO_DEAD, True)
    pad = control.Pad()
    try:
        ok = savepoint.to_title(tm, pad, log) and savepoint.back_in(pad, log) is not None
    finally:
        pad.release_all()
        stop_feed()
    tm.set_dbg(tm.DBG_PLAYER_NO_DEAD, bool(nodead_before))
    s = tm.snapshot(30)
    out = {"menu_reload": bool(ok), "nodead": tm.get_dbg(tm.DBG_PLAYER_NO_DEAD),
           "hp": s.player.hp if s else None, "awake_near": [(c.npc_param, c.anim) for c in (s.hostile(10) if s else [])
                                                           if c.anim not in (-1, None)]}
    log(f"  끝 처리: 메뉴 종료·이어하기 {'됨' if ok else '실패'}, PlayerNoDead {out['nodead']}, HP {out['hp']}, 10 m 안 깬 적 {out['awake_near']}")
    return out
