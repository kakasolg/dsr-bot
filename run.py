"""DSR 봇 실행 — 층 구조(souls/)의 진입점. 층 설명은 LAYERS.md.

  python run.py status                   HP·에스트·무기·마지막 화톳불·핏자국 (게임에 입력 안 함)
  python run.py burg-bonfire             불의 제전 → 경사로 하나씩 → 상인 → 성벽 마을 화톳불 찍기
  python run.py clear-ramp [--no-rest]   경사로 6마리만 (--no-rest: 쉬지 않고 지금 상태에서)
  python run.py merchant                 지금 자리에서 상인까지 (쉬지 않음)
  python run.py light-burg               지금 자리(성벽 마을)에서 화톳불 찍기만
  python run.py quit-test                1번을 잡고 퀵 종료 전후 경사로 적 생존 비교 (퀵 종료가 죽은 적을 살리나)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent


class Log:
    """화면 + data/runs/<시각>.log, 사건은 .jsonl 로."""

    def __init__(self, name: str):
        d = ROOT / "data" / "runs"
        d.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.txt = (d / f"{stamp}_{name}.log").open("a", encoding="utf-8")
        self.ev = (d / f"{stamp}_{name}.jsonl").open("a", encoding="utf-8")
        self.t0 = time.time()

    def __call__(self, msg: str) -> None:
        line = f"[{time.time() - self.t0:7.1f}] {msg}"
        print(line, flush=True)
        self.txt.write(line + "\n")
        self.txt.flush()

    def event(self, _ev: str, **kw) -> None:
        # 인자 이름이 kind 였더니 퀵 종료 결과의 kind 와 겹쳐 봇이 멈췄다 (2026-09-24)
        self.ev.write(json.dumps({"t": round(time.time() - self.t0, 2), "ev": _ev, **kw}, ensure_ascii=False, default=str) + "\n")
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
    ap.add_argument("cmd", choices=["status", "burg-bonfire", "clear-ramp", "merchant", "light-burg", "quit-test"])
    ap.add_argument("--no-rest", action="store_true")
    ap.add_argument("--no-lure", action="store_true", help="나이프로 한 놈씩 깨우지 않고 예전처럼 걸어가 붙는다 (비교용)")
    ap.add_argument("--style", choices=["guard", "backstep"], default="guard",
                    help="guard: 방패로 받고 휘청에 친다 (기본) | backstep: 양손, 백스텝으로 피하고 헛친 뒤 약공 (사용자 제안, 실험)")
    a = ap.parse_args()
    if a.cmd == "status":
        return status()

    import control
    import env
    import navmesh
    from souls import missions, moves, weapons
    from souls.field import Field
    from souls.watch import Blood, Escape

    log = Log(a.cmd)
    tm = env.make_telemetry({})
    control.focus_game()
    pad = control.Pad()
    nms = {missions.MAP_A: navmesh.Navmesh(missions.MAP_A), missions.MAP_B: navmesh.Navmesh(missions.MAP_B)}
    mv = moves.Moves(tm, pad)
    w = weapons.of(tm.right_weapon())
    log(f"무기: {w.name} (약공 {w.combo}연타, 닿는 거리 {w.reach} m, 강공 {'씀' if w.use_heavy else '안 씀'})")
    esc = Escape(pad, list(nms.values()), log=log, events=log.event).start()
    blood = Blood(log=log).start()
    fld = Field(mv, w, esc, bonfires=[missions.FIRELINK["stand"], missions.BURG_BONFIRE], log=log, events=log.event, style=a.style)
    log(f"스타일: {a.style}")
    log.event("style", style=a.style)
    try:   # 판마다 캐릭터 상태를 남긴다 — 레벨업·반지(강인도)·무기가 성적을 바꾸는데 기록이 없어 묶음 비교가 흐려졌다 (사용자 2026-09-25)
        st, eq = tm.char_stats(), tm.equipment()
        log(f"캐릭터: SL {st.get('SL')} VIT {st.get('VIT')} END {st.get('END')} STR {st.get('STR')} DEX {st.get('DEX')} | 반지 {eq.get('반지1')},{eq.get('반지2')} 왼손 {eq.get('왼손1')}")
        log.event("char", stats=st, equip=eq)
    except Exception as ex:
        log(f"캐릭터 상태 읽기 실패: {ex!r}")
    ms = missions.Missions(fld, nms, log=log)
    try:
        if a.cmd == "burg-bonfire":
            r = ms.burg_bonfire()
        elif a.cmd == "clear-ramp":
            if not a.no_rest:
                ms.start_fresh()
            r = ms.clear_ramp(lure=not a.no_lure)
        elif a.cmd == "merchant":
            r = ms.to_merchant()
        elif a.cmd == "light-burg":
            r = ms.light_burg_bonfire()
        else:
            r = quit_test(ms, mv, esc, log)
        log(f"══ 결과: {r}")
        log.event("result", cmd=a.cmd, result=r)
    except BaseException as ex:
        # 봇이 멈추면 캐릭터가 적 옆에 조작 없이 서서 죽는다 (2026-09-24 두 번) — 멈추기 전에 퀵 종료로 적을 떼어낸다
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
        while esc.escaping and time.time() - t_wait < 40.0:  # 퀵 종료 도중에 끝내면 메뉴·로딩에 멈춘다
            time.sleep(0.2)
        try:
            if not fld.alive():
                fld.wait_respawn(30.0)                     # 죽은 채 끝내면 핏자국이 안 남는다 (부활 뒤 소울 감소로 확인하므로)
                time.sleep(1.5)
        except Exception:
            pass
        esc.stop()
        blood.stop()
        pad.neutral()
        if hasattr(tm, "stats"):
            log(f"텔레메트리 피드: {tm.stats()}")   # frames = 아래 읽기 수, fresh/waited = 층이 받은 프레임, direct = 폴백


def quit_test(ms, mv, esc, log) -> str:
    """퀵 종료가 죽은 적을 살리나 — 쉬고, 1번만 잡고, 퀵 종료 전후 스폰 자리 생존을 비교. 끝나도 쉬지 않는다."""
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
