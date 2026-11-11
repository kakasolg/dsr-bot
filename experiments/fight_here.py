"""지금 자리에서 가장 가까운 적과 봇 싸움 규칙(Field.fight)으로 싸운다 — 수동 시험 중 적이 올 때 (11-08 P-135 나이프 자리).

  python experiments/fight_here.py [--r 15] [--n 1]
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]
import argparse, sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import control, env, navmesh, track
from botlock import BotLock
from run import Log
from souls import missions, moves as M, props, weapons
from souls.field import Field
from souls.watch import Escape


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--r", type=float, default=15.0)
    ap.add_argument("--n", type=int, default=1)
    a = ap.parse_args()
    log = Log("fight-here")
    lock = BotLock()
    if not lock.acquire():
        log("   ⚠ 이미 다른 본체가 실행 중 — 멈춤"); return
    tm = env.make_telemetry({})
    tr = track.Track(str(log.path).replace(".jsonl", ".track.jsonl")).attach(tm)
    log.on_line = tr.say
    control.focus_game()
    pad = control.Pad()
    nm = navmesh.Navmesh(missions.MAP_B)
    props.attach({missions.MAP_B: nm}, log)
    mv = M.Moves(tm, pad); tr.follow(mv)
    w = weapons.of(tm.right_weapon()); mv.weapon = w
    esc = Escape(pad, [nm], log=log, events=log.event).start()
    fld = Field(mv, w, esc, bonfires=[missions.FIRELINK["stand"], missions.BURG_BONFIRE], log=log, events=log.event)
    try:
        mv.guard(True)
        for k in range(a.n):
            s = mv.snap(40.0)
            foes = [c for c in s.hostile(a.r) if c.hp > 0]
            if not foes:
                log("   가까운 적 없음 — 끝"); break
            c = min(foes, key=lambda c: c.dist)
            log(f"   싸움 {k+1}: {c.npc_param} {c.dist:.1f} m 애니 {c.anim}")
            r = fld.fight(c.ptr, nm, f"fight-here {c.npc_param}")
            log(f"   → {r}")
        mv.guard(True)
    finally:
        pad.neutral()
        esc.stop() if hasattr(esc, "stop") else None
        lock.release()


if __name__ == "__main__":
    main()
