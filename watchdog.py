"""BIOS 층 — run.py 와 별도 프로세스로 띄워 둔다. 평소엔 읽기만(텔레메트리, 가상 패드 없음).
run.py 가 심장박동(heartbeat.py, data/heartbeat.json)을 못 남기면(죽음·강제 종료·완전히 멈춤)
그때만 자기 패드를 만들어 퀵 종료로 캐릭터를 뺀다. 사용자 2026-09-25: "Bios, os, application 레이어처럼" —
본체를 강제로 꺼도(사용자가 겪은 사고: 적 옆에서 그냥 죽음) 이 프로세스는 따로 살아있어 구해 준다.

  BOT_GAME=dsr python watchdog.py [--timeout 2]      Ctrl+C 로 끝
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import env
import quitout

ROOT = Path(__file__).resolve().parent
HB_FILE = ROOT / "data" / "heartbeat.json"
LOG_FILE = ROOT / "data" / "watchdog.log"
POLL = 0.3


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def last_beat() -> float | None:
    try:
        return json.loads(HB_FILE.read_text(encoding="utf-8"))["t"]
    except (OSError, ValueError, KeyError):
        return None


def rescue(tm) -> None:
    """본체가 없으니 이 프로세스가 직접 패드를 잡아 퀵 종료한다."""
    import control
    log("   ⚠ 본체 반응 없음 — 패드 잡고 퀵 종료 시도")
    control.focus_game()
    pad = control.Pad()
    pad.reconnect()                # 죽은 본체의 패드가 막 빠진 직후라 게임이 새 패드를 못 받을 때가 있다 (실측 2026-09-25 — 첫 시도 실패)
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=2.0, help="이만큼 심장박동이 없으면 본체가 죽은 것으로 본다 (별도 스레드라 짧아도 오작동 안 함)")
    a = ap.parse_args()
    log(f"watchdog 시작 (timeout {a.timeout}s) — 텔레메트리만 읽음, 본체 살아있으면 아무것도 안 함")
    tm = env.make_telemetry({})
    handled = False
    try:
        while True:
            beat = last_beat()
            stale = beat is None or time.time() - beat > a.timeout
            if not stale:
                handled = False                # 본체가 다시 돌아왔다 — 다음에 또 끊기면 새로 개입한다
            elif not handled:
                try:
                    s = tm.snapshot(within=20.0)
                except Exception as ex:
                    s = None
                    log(f"   텔레메트리 읽기 실패: {ex!r}")
                if s is not None and s.player.hp is not None and s.player.hp > 0:
                    age = "없음" if beat is None else f"{time.time() - beat:.0f}s"
                    log(f"심장박동 끊김({age}) — HP {s.player.hp}, 위치 ({s.player.x:.1f}, {s.player.y:.1f}, {s.player.z:.1f})")
                    rescue(tm)
                    handled = True
                elif s is not None and s.player.hp == 0:
                    log("심장박동 끊김 — 이미 죽음(부활 대기), 입력 필요 없음")
                    handled = True
            time.sleep(POLL)
    except KeyboardInterrupt:
        log("watchdog 종료")


if __name__ == "__main__":
    main()
