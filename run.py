"""DSR bot runner — entry point for the layer stack (souls/). Layers are described in LAYERS.md.

  python run.py status                   HP, Estus, weapon, last bonfire, bloodstain (sends no game input)
  python run.py burg-bonfire             Firelink Shrine → ramp one by one → merchant → light and rest at Undead Burg bonfire (changes respawn point)
  python run.py burg-loop                same route, but don't rest at the bonfire; walk back to Firelink Shrine (for repeated testing)
  python run.py clear-ramp [--no-rest]   only the 6 ramp enemies (--no-rest: no rest, from current state)
  python run.py hunt-one [--i 5]         from the Undead Burg bonfire, kill only BURG_TOWN #i and return (5 = crossbowman)
  python run.py clear-burg-town          from here (inside Undead Burg), kill 6 enemies in the user's kill order (BURG_TOWN)
  python run.py merchant                 from here to the merchant (no rest)
  python run.py light-burg               from here (Undead Burg), just light the bonfire
  python run.py quit-test                kill #1 and compare ramp enemy survival before/after quit-out (does quit-out revive dead enemies?)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent


class Log:
    """Screen + data/runs/<timestamp>.log; events go to .jsonl."""

    def __init__(self, name: str):
        d = ROOT / "data" / "runs"
        d.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.path = d / f"{stamp}_{name}.jsonl"
        self.txt = (d / f"{stamp}_{name}.log").open("a", encoding="utf-8")
        self.ev = self.path.open("a", encoding="utf-8")
        self._lock = threading.Lock()          # the black box writer thread writes to the same file
        self.t0 = time.time()

    def __call__(self, msg: str) -> None:
        line = f"[{time.time() - self.t0:7.1f}] {msg}"
        with self._lock:
            print(line, flush=True)
            self.txt.write(line + "\n")
            self.txt.flush()

    def event(self, _ev: str, **kw) -> None:
        # the arg used to be named kind; it collided with the quit-out result's kind and stopped the bot (2026-09-24)
        line = json.dumps({"t": round(time.time() - self.t0, 2), "ev": _ev, **kw}, ensure_ascii=False, default=str)
        with self._lock:
            self.ev.write(line + "\n")
            self.ev.flush()


def status() -> None:
    import env
    from souls import moves, weapons
    from souls.watch import Blood
    tm = env.make_telemetry({})
    s = tm.snapshot(within=5.0)
    mv = moves.Moves(tm, None)
    wid = tm.right_weapon()
    print(f"HP {s.player.hp}/{s.player.max_hp}  위치 ({s.player.x:.1f}, {s.player.y:.1f}, {s.player.z:.1f})  "
          f"에스트 {mv.estus_id()} × {mv.estus_left()}  소울 {tm.souls()}  인간성 {tm.humanity()}")
    print(f"무기 {wid} → {weapons.of(wid).name}  양손 {tm.arm_style() == 3}  마지막 화톳불 {tm.last_bonfire()}  핏자국 {Blood.read()}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "burg-bonfire", "burg-loop", "clear-ramp", "clear-burg-town", "hunt-one", "merchant", "light-burg", "quit-test"])
    ap.add_argument("--no-rest", action="store_true")
    ap.add_argument("--no-quit", action="store_true", help="퀵 종료(메뉴로 나갔다 오기) 안 씀 — 영상 촬영용")
    ap.add_argument("--i", type=int, default=5, help="hunt-one: BURG_TOWN 몇 번째 (5 = 석궁병 255002)")
    ap.add_argument("--no-lure", action="store_true", help="나이프로 한 놈씩 깨우지 않고 예전처럼 걸어가 붙는다 (비교용)")
    ap.add_argument("--style", choices=["guard", "backstep", "rush"], default="guard",
                    help="guard: 방패로 받고 휘청에 친다 (기본) | backstep: 양손, 백스텝으로 피하고 헛친 뒤 약공 | "
                         "rush: 양손, 막지도 피하지도 않고 계속 공격, 에스트로 버틴다 (사용자 제안, 실험)")
    a = ap.parse_args()
    if a.cmd == "status":
        return status()

    import control
    import env
    import navmesh
    from botlock import BotLock
    from souls import missions, moves, weapons
    from souls.field import Field
    from souls.watch import Blood, Escape

    log = Log(a.cmd)
    lock = BotLock()
    # watchdog.py also polls briefly, grabbing and releasing at once — overlapping that instant can fail once, so retry a few times
    # (measured 2026-09-25: with a single try and no retry, 6 of 10 runs overlapped and failed immediately)
    for _ in range(10):
        if lock.acquire():
            break
        time.sleep(0.2)
    else:
        log("   ⚠ 이미 다른 본체가 실행 중 — 겹쳐 켜면 패드가 부딪힌다, 멈춤")
        return
    tm = env.make_telemetry({})
    control.focus_game()
    pad = control.Pad()
    nms = {missions.MAP_A: navmesh.Navmesh(missions.MAP_A), missions.MAP_B: navmesh.Navmesh(missions.MAP_B)}
    mv = moves.Moves(tm, pad)
    w = weapons.of(tm.right_weapon())
    mv.weapon = w
    log(f"무기: {w.name} (약공 {w.combo}연타, 닿는 거리 {w.reach} m, 강공 {'씀' if w.use_heavy else '안 씀'})")
    esc = Escape(pad, list(nms.values()), log=log, events=log.event)
    esc.quit_ok = not a.no_quit
    if a.no_quit:
        import os
        os.environ["BOT_NO_WARP"] = "1"                   # also disable farm.rest's warp to the bonfire
    esc.start()
    blood = Blood(log=log).start()
    from blackbox import BlackBox
    bbox = BlackBox(tm, log.path, events=log.event, log=log).start()
    fld = Field(mv, w, esc, bonfires=[missions.FIRELINK["stand"], missions.BURG_BONFIRE], log=log, events=log.event, style=a.style)
    from souls.camera import CamFollow
    cam = CamFollow(mv, esc, log=log).start()          # so a viewer can see what the bot is doing (user 2026-09-26)
    log(f"스타일: {a.style}")
    log.event("style", style=a.style)
    try:   # log character state each run — level-ups, rings (poise) and weapon change results, and without records batch comparisons got muddy (user 2026-09-25)
        st, eq = tm.char_stats(), tm.equipment()
        log(f"캐릭터: SL {st.get('SL')} VIT {st.get('VIT')} END {st.get('END')} STR {st.get('STR')} DEX {st.get('DEX')} | 반지 {eq.get('반지1')},{eq.get('반지2')} 왼손 {eq.get('왼손1')}")
        log.event("char", stats=st, equip=eq)
    except Exception as ex:
        log(f"캐릭터 상태 읽기 실패: {ex!r}")
    ms = missions.Missions(fld, nms, log=log)
    try:
        if a.cmd == "burg-bonfire":
            r = ms.burg_bonfire()
        elif a.cmd == "burg-loop":
            r = ms.burg_bonfire_round_trip()
        elif a.cmd == "clear-ramp":
            if not a.no_rest:
                ms.start_fresh()
            r = ms.clear_ramp(lure=not a.no_lure)
        elif a.cmd == "clear-burg-town":
            r = ms.clear_burg_town()
        elif a.cmd == "hunt-one":
            r = ms.hunt_one(a.i)
        elif a.cmd == "merchant":
            r = ms.to_merchant()
        elif a.cmd == "light-burg":
            r = ms.light_burg_bonfire()
        else:
            r = quit_test(ms, mv, esc, log)
        log(f"══ 결과: {r}")
        log.event("result", cmd=a.cmd, result=r)
    except BaseException as ex:
        # if the bot stops, the character stands idle next to enemies and dies (twice on 2026-09-24) — quit out to shake enemies before stopping
        import traceback
        log(f"══ 오류로 멈춤: {ex!r}\n{traceback.format_exc()}")
        if not esc.escaping:
            try:
                esc.fire(f"봇 오류({type(ex).__name__}) — 적 떼어내고 멈춤", "shake")
            except Exception as ex2:
                log(f"   퀵 종료도 실패: {ex2!r}")
        raise
    finally:
        t_wait = time.time()
        while esc.escaping and time.time() - t_wait < 40.0:  # exiting mid quit-out leaves the game stuck in menu/loading
            time.sleep(0.2)
        try:
            if not fld.alive():
                fld.wait_respawn(30.0)                     # ending while dead leaves no bloodstain (it's confirmed by the soul drop after respawn)
                time.sleep(1.5)
        except Exception:
            pass
        cam.stop()
        esc.stop()
        blood.stop()
        bbox.stop()
        try:
            import risk_report
            log(risk_report.one_line(risk_report.score(log.path)))
        except Exception as ex:
            log(f"위험 요약 실패: {ex!r}")
        lock.release()
        pad.neutral()
        if hasattr(tm, "stats"):
            log(f"텔레메트리 피드: {tm.stats()}")   # frames = underlying read count, fresh/waited = frames received by layers, direct = fallback


def quit_test(ms, mv, esc, log) -> str:
    """Does quit-out revive dead enemies — rest, kill only #1, compare survival at spawn spots before/after quit-out. Doesn't rest at the end."""
    from souls import missions

    def alive_map() -> str:
        s = mv.snap(200.0)
        out = []
        for i, e in enumerate(missions.RAMP, 1):
            ok = any(c.hp > 0 and c.npc_param == e["npc"] and math.dist((c.x, c.y, c.z), tuple(e["pos"])) < 6 for c in s.chars)
            out.append(f"#{i}{'살' if ok else '×'}")
        return " ".join(out)
    ms.start_fresh()
    r = ms.f.clear(missions.RAMP[:1], ms.nms[missions.MAP_A])
    before = alive_map()
    esc.fire("퀵 종료 실측", "shake")
    after = alive_map()
    log(f"   1번 처치 {r}: 종료 전 [{before}] → 종료 후 [{after}]")
    return "죽은 적 그대로" if before == after else "달라짐 — 확인 필요"


if __name__ == "__main__":
    main()
