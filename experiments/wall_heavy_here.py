"""배틀 액스 벽 강공 시험 — 지금 서 있는 자리(벽 옆)에서 같은 층 적을 한 마리씩 끌어와 봇 싸움 규칙(duel) 그대로 싸운다.

  python experiments/wall_heavy_here.py [--n 3] [--r 25] [--radar]

시작 자리 = 벽 자리(home). 적마다: 나이프로 깨움 → home으로 돌아옴 → 기다렸다 싸움(wait_far) → home으로 → 회복.
끝나면 벽 강공(`벽 … — 강공(수직)`) 수와 강공 명중·헛침·강공 중 받은 피해를 싸움마다 요약한다 (ROADMAP 0-b 배틀 액스 강공).
화톳불에서 쉬지 않음 — 적 부활 없이 지금 살아 있는 적만. 로그: data/runs/<시각>_wall-heavy.*
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import argparse
import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env
import navmesh
import track
from botlock import BotLock
from run import Log
from souls import missions, moves as M, props, weapons
from souls.field import Field
from souls.watch import Escape


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3, help="싸울 적 수 상한")
    ap.add_argument("--r", type=float, default=25.0, help="이 거리 안 같은 층 적만")
    ap.add_argument("--dy", type=float, default=1.5, help="같은 층 높이 차")
    ap.add_argument("--radar", action="store_true")
    a = ap.parse_args()

    log = Log("wall-heavy")
    lock = BotLock()
    if not lock.acquire():
        log("   ⚠ 이미 다른 본체가 실행 중 — 멈춤")
        return
    tm = env.make_telemetry({})
    tr = track.Track(str(log.path).replace(".jsonl", ".track.jsonl")).attach(tm)
    log.on_line = tr.say
    rd = None
    if a.radar:
        import radar
        rd = radar.Radar().attach(tm)
        log.on_line = lambda m: (tr.say(m), rd.say(m))
    control.focus_game()
    pad = control.Pad()
    nm = navmesh.Navmesh(missions.MAP_B)
    props.attach({missions.MAP_B: nm}, log)
    mv = M.Moves(tm, pad)
    tr.follow(mv)
    if rd:
        rd.follow(mv)
    w = weapons.of(tm.right_weapon())
    mv.weapon = w
    esc = Escape(pad, [nm], log=log, events=log.event).start()
    fld = Field(mv, w, esc, bonfires=[missions.FIRELINK["stand"], missions.BURG_BONFIRE], log=log, events=log.event)
    rows = []
    try:
        s = mv.snap(40.0)
        p = s.player
        home = (p.x, p.y, p.z)
        log(f"무기 {w.name} (벽 강공 {'됨' if w.heavy_vertical else '안 됨'})  home ({p.x:.1f}, {p.y:.1f}, {p.z:.1f}) "
            f"벽까지 {nm.border_dist(*home):.2f} m  HP {p.hp}/{p.max_hp}  에스트 {mv.estus_left()}")
        done: set = set()
        for k in range(a.n):
            s = mv.snap(40.0)
            foes = [c for c in s.hostile(a.r) if abs(c.y - s.player.y) <= a.dy and c.ptr not in done]
            foes = [c for c in foes if nm.find_path((s.player.x, s.player.y, s.player.z), (c.x, c.y, c.z))]
            if not foes:
                log("   같은 층에 남은 적 없음 — 끝")
                break
            c = min(foes, key=lambda c: c.dist)
            done.add(c.ptr)
            tag = f"[{k + 1}] {c.npc_param}"
            log(f"── {tag}: {c.dist:.1f} m, 그놈 벽까지 {nm.border_dist(c.x, c.y, c.z):.2f} m")
            lr = fld.lure(c.ptr, (c.x, c.y, c.z), nm, tag, arena=home)
            log(f"   끌어오기: {lr}")
            if lr == "dead":
                break
            fld.walk_to(home, nm, f"{tag} 벽 자리로", mode="sprint")
            r = fld.fight(c.ptr, nm, tag, wait_far=True, limit=60.0)
            heavies = [h for h in r.hits if h["kind"].startswith("heavy")]
            row = {"tag": tag, "result": r.result, "secs": round(r.secs, 1), "dealt": r.dealt, "taken": r.taken,
                   "heavy": len(heavies), "heavy_hit": sum(1 for h in heavies if h["dmg"]),
                   "rules": r.rules, "hits": r.hits}
            rows.append(row)
            log.event("wall_heavy", **row)
            if r.result == "me_dead":
                break
            fld.walk_to(home, nm, f"{tag} 돌아감")
            fld.heal(0.7)
    finally:
        esc.stop()
        lock.release()
        pad.neutral()
        log("══ 요약")
        for r in rows:
            log(f"   {r['tag']}: {r['result']} {r['secs']} s, 강공 {r['heavy']}번 중 명중 {r['heavy_hit']}, "
                f"준 피해 {r['dealt']}, 받은 피해 {r['taken']}")
        n_wall = sum(1 for line in open(log.path.with_suffix(".log"), encoding="utf-8") if "강공(수직)" in line) \
            if log.path.with_suffix(".log").exists() else None
        log(f"   벽 강공 판정 {n_wall}번 (로그 줄)")


if __name__ == "__main__":
    main()
