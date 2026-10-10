"""BIOS 층 — run.py 와 별도 프로세스로 띄워 둔다. 평소엔 읽기만(텔레메트리, 가상 패드 없음).
사용자 2026-09-25: "3초 이상 멈춰 있으면" — 감시 기준은 **캐릭터가 실제로 멈춰 있나**(위치·애니가 STALL_S
동안 안 바뀜)다. 프로세스 생사 신호(잠금 파일 등)로 추측하지 않는다 — 그건 "본체가 켜져 있나" 만 알지
"본체가 실제로 캐릭터를 움직이고 있나" 는 모른다(2026-09-25 사고: 잠금이 있다/없다만 보다가 —
① 판 사이 정상 대기를 위급으로 오판해 다크사인을 반복 쐈고 그 사이 다음 판이 못 켜졌다,
② 반대로 끈 순간만 한 번 보고 안전하다 넘어갔는데 그 뒤 아무도 없이 계속 맞아 죽었다("멈추고 처 맞네"),
③ 사용자: "이러면 watchdog 아니잖아" — 게임 위험도를 판단하는 건 전투 AI지 감시가 아니다).
**멈춰 있다 = 위험**만 본다 — 판단은 그거 하나, 나머지(구조 방법)는 그대로.

  BOT_GAME=dsr python watchdog.py [--stall 3]      Ctrl+C 로 끝
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import ctl
import env
import quitout
from botlock import BotLock

ROOT = Path(__file__).resolve().parent
LOG_FILE = ROOT / "data" / "watchdog.log"
POLL = 0.3
POS_EPS = 0.15           # 이보다 덜 움직이면 "안 움직였다"(부동 소수 흔들림 무시)
COOLDOWN_S = 20.0        # 구조한 뒤 이만큼은 다시 안 잰다 — 구조 자체(메뉴 넘기는 동안)도 안 움직이니 자기 자신을 다시 잡지 않게
PERCEIVE_R = 12.0        # 재접속 뒤 안전 확인용(적 인식 범위 추정, 위키 기반 첫 값)
SAFE_WATCH_S = 15.0
STABLE_S = 3.0


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def nearby_awake(s, r: float) -> list:
    return [c for c in s.hostile(r) if c.hp > 0 and (c.anim or -1) != -1]


def retreat_step(tm, pad, s, threats: list) -> None:
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


def watch_safety(tm, pad) -> None:
    """재접속한 자리가 진짜 안전한지 실시간으로 본다(사용자: "실시간으로 안전 지역을 평가", "적의 인식 범위를 기준으로")."""
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


def rescue(tm) -> None:
    """다크사인을 먼저 시도한다 — 퀵 종료(자리 안 바뀜)와 달리 알려진 화톳불로 순간이동해 안전 지역이 확정된다."""
    import control
    lock = BotLock()
    held_by_other = not lock.acquire()          # 참고 로그용 — 막는 건 아래 패드 잠금
    if held_by_other:
        log("   (참고: 봇 잠금은 다른 프로세스가 쥐고 있음)")
    else:
        lock.release()
    ctl.emit("wd", ev="bot_lock", held=held_by_other)                    # P1-D: record only
    # ── 패드 하나 원칙 ([MoKa] 2026-10-02 P0-A) ─────────────────────────────
    #  봇이 살아서 패드 잠금을 쥐고 있으면 구조하지 않는다 — 가상 패드 둘이 동시에 넣는 것보다 구조를 포기하는 쪽이 안전.
    #  잠금 확인은 어떤 입력보다도 먼저 (focus_game 도 ALT 키·제목줄 클릭을 보낸다)
    if control.pad_lock_held():
        log("   event=skip reason=pad_lock_held — 다른 프로세스가 가상 패드를 쥐고 있음, 패드 안 만들고 입력 안 보냄")
        ctl.emit("wd", ev="skip", reason="pad_lock_held", at="probe")
        return
    try:
        pad = control.Pad()
    except control.PadBusy as ex:              # probe 와 생성 사이에 누가 잡음
        log(f"   event=skip reason=pad_lock_held — {ex}")
        ctl.emit("wd", ev="skip", reason="pad_lock_held", at="create")
        return
    ctl.emit("wd", ev="rescue_start")
    try:
        _rescue(tm, pad)
    finally:
        pad.close()                            # 잠금을 바로 놓는다 — 다음 본체가 패드를 만들 수 있게
        ctl.emit("wd", ev="pad_close")


def _rescue(tm, pad) -> None:
    import control
    from souls import missions, moves
    log("   ⚠ 3 초 넘게 안 움직임 — 패드 잡고 구조 시도")
    control.focus_game()
    pad.reconnect()                # 죽은 본체의 패드가 막 빠진 직후라 게임이 새 패드를 못 받을 때가 있다 (실측 2026-09-25)
    mv = moves.Moves(tm, pad)
    if mv.select_item(117, timeout=3.0):
        ok = mv.darksign(missions.FIRELINK["stand"])
        log(f"   다크사인 {ok} — 됐으면 화톳불(알려진 안전 지역)로 순간이동")
        ctl.emit("wd", ev="result", how="darksign", ok=bool(ok))
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
            ctl.emit("wd", ev="result", how="quitout", ok=False)
            return
    rt = quitout.reload(pad)
    log(f"   퀵 종료 {t:.1f}s, 재접속 {rt}")
    ctl.emit("wd", ev="result", how="quitout", ok=True, quit_s=round(t, 2), reload_s=rt)
    watch_safety(tm, pad)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stall", type=float, default=3.0, help="이만큼 위치·애니가 안 바뀌면 멈춘 것으로 본다")
    ap.add_argument("--ctl", action="store_true",
                    help="P1: 감시 판단 기록 → data/runs/<시각>_watchdog.ctl.jsonl (ctl.py) — 기본 꺼짐. 기록만, 판단·패드엔 반영 안 함")
    a = ap.parse_args()
    if a.ctl:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        (ROOT / "data" / "runs").mkdir(parents=True, exist_ok=True)
        ctl.start(ROOT / "data" / "runs" / f"{stamp}_watchdog.ctl.jsonl", run=f"{stamp}_watchdog", argv=sys.argv, cmd="watchdog")
        ctl.emit("wd", ev="start", stall_s=a.stall)
    log(f"watchdog 시작 — 캐릭터가 {a.stall:.0f} s 넘게 안 움직이면(위치·애니 정지) 개입")
    tm = env.make_telemetry({})
    last_state = None
    last_change_t = time.time()
    cooldown_until = 0.0
    try:
        while True:
            now = time.time()
            try:
                s = tm.snapshot(within=20.0)
            except Exception as ex:
                s = None
                log(f"   텔레메트리 읽기 실패: {ex!r}")
            if s is None or s.player.hp is None:
                time.sleep(POLL)
                continue
            p = s.player
            if p.hp <= 0:
                last_state, last_change_t = None, now   # 죽어 있는 동안(부활 대기)은 안 움직이는 게 정상 — 안 잰다
                time.sleep(POLL)
                continue
            state = (round(p.x, 2), round(p.y, 2), round(p.z, 2), p.anim)
            moved = (last_state is None or state[3] != last_state[3]
                     or abs(state[0] - last_state[0]) > POS_EPS or abs(state[1] - last_state[1]) > POS_EPS
                     or abs(state[2] - last_state[2]) > POS_EPS)
            if moved:
                last_state, last_change_t = state, now
            elif now - last_change_t > a.stall and now > cooldown_until:
                log(f"멈춰 있음({now - last_change_t:.1f}s) — HP {p.hp}, 위치 ({p.x:.1f}, {p.y:.1f}, {p.z:.1f}), 애니 {p.anim}")
                ctl.emit("wd", ev="stall", stall_s=round(now - last_change_t, 2), hp=p.hp,
                         pos=[round(p.x, 2), round(p.y, 2), round(p.z, 2)], anim=p.anim)
                rescue(tm)
                last_state, last_change_t, cooldown_until = None, time.time(), time.time() + COOLDOWN_S
            time.sleep(POLL)
    except KeyboardInterrupt:
        log("watchdog 종료")


if __name__ == "__main__":
    main()
