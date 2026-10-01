"""핏자국 회수 — 불 붙인 화톳불로 워프해 핏자국까지 걸어가(가는 길 싸움은 봇 그대로) 줍고 불의 제전으로 워프.

  python experiments/fetch_blood.py [--from 1012962] [--radar]

화톳불 워프는 게임 메모리 쓰기 — Steam 오프라인일 때만 (CLAUDE.md). 소울·인간성은 워프로 안 잃는다.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import argparse
import math
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env
import navmesh
import steam_state
import track
from botlock import BotLock
from run import Log
from souls import missions, moves as M, props, weapons
from souls.field import Field
from souls.watch import Blood, Escape


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", type=int, default=missions.BURG_BONFIRE_ID, help="워프해 갈 화톳불 ID")
    ap.add_argument("--radar", action="store_true")
    ap.add_argument("--careful", action="store_true", help="핏자국까지 Field.careful_walk_to로 (천천히, 하나씩 끌어와)")
    a = ap.parse_args()

    log = Log("fetch-blood")
    b = Blood.read()
    if not b:
        log("핏자국 기록 없음 — 끝")
        return
    if steam_state.check().get("offline") is not True:
        log("Steam 오프라인 확인 안 됨 — 워프 안 함")
        return
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
    nms = {missions.MAP_A: navmesh.Navmesh(missions.MAP_A), missions.MAP_B: navmesh.Navmesh(missions.MAP_B)}
    props.attach(nms, log)
    nb = nms[missions.MAP_B]
    mv = M.Moves(tm, pad)
    tr.follow(mv)
    if rd:
        rd.follow(mv)
    w = weapons.of(tm.right_weapon())
    mv.weapon = w
    esc = Escape(pad, list(nms.values()), log=log, events=log.event).start()
    fld = Field(mv, w, esc, bonfires=[missions.FIRELINK["stand"], missions.BURG_BONFIRE], log=log, events=log.event)
    res = "?"
    try:
        log(f"핏자국 {b['pos']} 소울 {b['souls']} 인간성 {b['humanity']} — 지금 소울 {tm.souls()}")
        if not tm.bonfire_warp(a.src, log=log):
            res = "워프 실패"
            return
        time.sleep(2.0)
        s = mv.snap(5.0)
        log(f"   도착 ({s.player.x:.1f}, {s.player.y:.1f}, {s.player.z:.1f}), 핏자국까지 "
            f"{math.dist((s.player.x, s.player.y, s.player.z), tuple(b['pos'])):.1f} m")
        r = fld.careful_walk_to(tuple(b["pos"]), nb, "핏자국") if a.careful else "skip"
        if r == "dead":
            res = "dead"
            return
        res = fld.pick_blood(nb, near=200.0) or "없음"
        for k in range(3):                                 # 09-30: 0.15 m 위에서 멈추자마자 누른 A 한 번이 안 먹음 — 서서 기다렸다 다시
            if res != "miss":
                break
            time.sleep(1.0)
            souls0 = tm.souls() or 0
            mv.press(M.B.XUSB_GAMEPAD_A)
            time.sleep(2.0)
            res = "got" if (tm.souls() or 0) > souls0 else "miss"
            log(f"   A 다시 {k + 1}: {res} (소울 {souls0} → {tm.souls()})")
        log(f"── 핏자국: {res}")
    finally:
        if res != "dead" and fld.alive():
            ok = tm.bonfire_warp(missions.FIRELINK_ID, log=log)
            log(f"── 불의 제전으로: {'됨' if ok else '실패'}")
        esc.stop()
        lock.release()
        pad.neutral()
        log(f"══ 결과: {res}  소울 {tm.souls()} 인간성 {tm.humanity()}")


if __name__ == "__main__":
    main()
