"""BIOS 층 — run.py 와 별도 프로세스로 띄워 둔다. 평소엔 읽기만(텔레메트리, 가상 패드 없음).
run.py 가 쥐고 있던 OS 잠금(botlock.py)이 풀리면(죽음·강제 종료·완전히 멈춰도 OS 가 자동으로 풀어준다)
watchdog 이 그 잠금을 **직접 가져와 봐서** 성공할 때만(=진짜 아무도 안 쥐고 있을 때만) 자기 패드로 퀵 종료한다.
사용자 2026-09-25: "Bios, os, application 레이어처럼" → 리서치(Patroni 등 HA 시스템의 펜싱 원칙) 뒤
타임스탬프 파일 추측 방식에서 이걸로 바꿈 — 추측 한 번 실패해 본체가 살아있는데 개입해 메뉴가 걸린
사고("최악이네") 재발을 원천 차단한다(OS 가 보장하는 잠금이라 읽기 경쟁 자체가 없다).

  BOT_GAME=dsr python watchdog.py      Ctrl+C 로 끝
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import env
import quitout
from botlock import BotLock

ROOT = Path(__file__).resolve().parent
LOG_FILE = ROOT / "data" / "watchdog.log"
POLL = 0.5
PERCEIVE_R = 12.0        # 적의 인식 범위 추정(사용자 2026-09-25: "적의 인식 범위를 기준으로") — 위키 기반 첫 값, 실측 전
SAFE_WATCH_S = 15.0      # 퀵 종료 뒤 이만큼 실시간으로 다시 확인 — 재접속했는데도 인식 범위 안이면 더 물러난다
STABLE_S = 3.0           # 이만큼 연속으로 안전(인식 범위 밖)이면 됐다고 본다


def nearby_awake(s, r: float) -> list:
    """r 안에서 이미 깨어(idle 이 아닌) 있는 적 — 재접속했는데도 바로 이러면 인식 범위를 못 벗어난 것."""
    return [c for c in s.hostile(r) if c.hp > 0 and (c.anim or -1) != -1]


def retreat_step(tm, pad, s, threats: list) -> None:
    """가장 가까운 적에게서 먼 쪽으로 한 걸음 — 정확한 길찾기 없이 그냥 반대 방향(막다른 곳일 수 있음, 최선은 아니다)."""
    import math
    import control
    import nav
    if s.cam_yaw is None or not threats:
        return
    nearest = min(threats, key=lambda c: c.dist if c.dist is not None else 999)
    dx, dz = s.player.x - nearest.x, s.player.z - nearest.z
    n = math.hypot(dx, dz) or 1.0
    gx, gz = s.player.x + dx / n * 4.0, s.player.z + dz / n * 4.0
    stx, sty = control.world_to_stick(gx - s.player.x, gz - s.player.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
    pad.move(stx, sty)
    time.sleep(0.4)
    pad.move(0.0, 0.0)


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def rescue(tm) -> None:
    """잠금을 가져왔다 = 본체가 진짜 죽었다(OS 가 확인해 줌, 추측 아님) — 이 프로세스가 직접 패드를 잡아 구한다.
    다크사인을 먼저 시도한다 — 퀵 종료(자리 안 바뀜)와 달리 알려진 화톳불로 순간이동해 안전 지역이 확정된다
    (소울·인간성은 잃지만, 프로세스가 죽은 위급 상황엔 그게 더 맞다). 퀵 아이템 링에 없으면(select_item 실패) 못 쓰니
    그때만 퀵 종료로 물러난다 — 이건 자리가 안 바뀌니 재접속 뒤 실시간으로 안전한지 계속 본다(watch_safety)."""
    import control
    from souls import missions, moves
    log("   ⚠ 본체 잠금 확보(=본체 없음, OS 확인됨) — 패드 잡고 구조 시도")
    control.focus_game()
    pad = control.Pad()
    pad.reconnect()                # 죽은 본체의 패드가 막 빠진 직후라 게임이 새 패드를 못 받을 때가 있다 (실측 2026-09-25 — 첫 시도 실패)
    mv = moves.Moves(tm, pad)
    if mv.select_item(117, timeout=3.0):           # 다크사인이 퀵 링에 있나 — 없으면 15 s+ 돌려도 안 됨, 짧게만 본다
        ok = mv.darksign(missions.FIRELINK["stand"])
        log(f"   다크사인 {ok} — 됐으면 화톳불(알려진 안전 지역)로 순간이동")
        if ok:
            return
        log("   다크사인 실패 — 퀵 종료로 대신")
    else:
        log("   다크사인 퀵 링에 없음 — 퀵 종료로 대신")
    t = quitout.quit_out(tm, pad)
    if t is None:
        log("   퀵 종료 실패 — 한 번 더 시도")
        pad.reconnect()
        t = quitout.quit_out(tm, pad)
        if t is None:
            log("   퀵 종료 재시도도 실패 — 메뉴가 이미 열려 있거나 조작 불가 상태일 수 있음")
            return
    rt = quitout.reload(pad)
    log(f"   퀵 종료 {t:.1f}s, 재접속 {rt}")
    watch_safety(tm, pad)          # 퀵 종료는 자리를 안 바꾸니(다크사인과 달리) 여기서만 실시간으로 다시 확인한다


def watch_safety(tm, pad) -> None:
    """재접속한 자리가 진짜 안전한지 실시간으로 본다 — 자리는 안 바뀌니 적의 인식 범위 안이면 바로 또 위험하다
    (사용자 2026-09-25: "실시간으로 안전 지역을 평가하는 것이 필요해 보여", "적의 인식 범위를 기준으로")."""
    t0 = time.time()
    stable_from = None
    while time.time() - t0 < SAFE_WATCH_S:
        try:
            s = tm.snapshot(within=PERCEIVE_R + 5.0)
        except Exception:
            s = None
        if s is None or s.player.hp is None:
            time.sleep(POLL)
            continue
        if s.player.hp <= 0:
            log("   재접속 뒤 다시 사망 — 더 볼 것 없음")
            return
        threats = nearby_awake(s, PERCEIVE_R)
        if not threats:
            stable_from = stable_from or time.time()
            if time.time() - stable_from >= STABLE_S:
                log(f"   안전 확인됨 ({time.time() - t0:.1f}s 뒤, 인식 범위 {PERCEIVE_R} m 안 깨어있는 적 없음)")
                return
        else:
            stable_from = None
            log(f"   아직 인식 범위 안: {[(c.npc_param, round(c.dist, 1)) for c in threats]} — 물러남")
            retreat_step(tm, pad, s, threats)
        time.sleep(POLL)
    log(f"   {SAFE_WATCH_S:.0f}s 지켜봤는데 계속 인식 범위 안 — 포기(다음 순찰에서 다시 봄)")


DANGER_HP_FRAC = 0.5     # 잠금이 풀린 순간 HP 가 이 아래면 위급 — 정상 종료(판 끝, 판 사이 쉬는 시간)는 대개 HP 가 높다


def main() -> None:
    """잠금이 비어 있는 것 자체는 정상이다(판 사이엔 아무도 안 쥔다 — loop_runs.py 는 잠금을 안 쥐고,
    run.py 는 한 판 끝나면 놓는다). '아무도 안 쥠' 을 매번 위급으로 보면 판 사이마다 다크사인을 쏘고,
    그 사이 다음 판 run.py 가 잠금을 못 가져가 "이미 실행 중" 으로 계속 막힌다(실전 사고, 2026-09-25).
    **쥐어져 있다가 방금 풀린 전환 순간**에만, 그것도 HP 가 낮거나(DANGER_HP_FRAC) 근처에 깨어있는 적이
    있을 때만 진짜 위급으로 본다 — 판이 깨끗이 끝난 것과 구분한다."""
    log("watchdog 시작 — 텔레메트리만 읽음, 본체가 살아있으면(잠금을 쥐고 있으면) 아무것도 안 함")
    tm = env.make_telemetry({})
    lock = BotLock()
    was_held = False
    try:
        while True:
            got = lock.acquire()
            if got and was_held:               # 전환: 방금까지 누가 쥐고 있다가 지금 풀렸다
                try:
                    s = tm.snapshot(within=PERCEIVE_R + 5.0)
                except Exception as ex:
                    s = None
                    log(f"   텔레메트리 읽기 실패: {ex!r}")
                if s is not None and s.player.hp is not None and 0 < s.player.hp:
                    frac = s.player.hp / (s.player.max_hp or s.player.hp)
                    threats = nearby_awake(s, PERCEIVE_R)
                    if frac < DANGER_HP_FRAC or threats:
                        log(f"본체 방금 사라짐, 위급 — HP {s.player.hp}/{s.player.max_hp}({frac:.0%}), "
                            f"근처 적 {[(c.npc_param, round(c.dist,1)) for c in threats]}")
                        rescue(tm)
                    else:
                        log(f"본체 방금 사라짐, 정상 종료로 보임 — HP {s.player.hp}/{s.player.max_hp}({frac:.0%}), 아무것도 안 함")
                elif s is not None and s.player.hp == 0:
                    log("본체 방금 사라짐 — 이미 죽음(부활 대기), 입력 필요 없음")
            if got:
                lock.release()
            was_held = not got
            time.sleep(POLL)
    except KeyboardInterrupt:
        log("watchdog 종료")
        if lock is not None:
            lock.release()


if __name__ == "__main__":
    main()
