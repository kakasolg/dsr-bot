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


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def rescue(tm) -> None:
    """잠금을 가져왔다 = 본체가 진짜 죽었다(OS 가 확인해 줌, 추측 아님) — 이 프로세스가 직접 패드를 잡아 퀵 종료한다."""
    import control
    log("   ⚠ 본체 잠금 확보(=본체 없음, OS 확인됨) — 패드 잡고 퀵 종료 시도")
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
    log("watchdog 시작 — 텔레메트리만 읽음, 본체가 잠금을 쥐고 있으면(=살아있으면) 아무것도 안 함")
    tm = env.make_telemetry({})
    lock = BotLock()
    try:
        while True:
            if lock.acquire():                 # 성공 = 아무도 안 쥐고 있었다 = 본체가 진짜 죽었다 (OS 보장, 추측 없음)
                try:
                    s = tm.snapshot(within=20.0)
                except Exception as ex:
                    s = None
                    log(f"   텔레메트리 읽기 실패: {ex!r}")
                if s is not None and s.player.hp is not None and s.player.hp > 0:
                    log(f"본체 없음 — HP {s.player.hp}, 위치 ({s.player.x:.1f}, {s.player.y:.1f}, {s.player.z:.1f})")
                    rescue(tm)
                elif s is not None and s.player.hp == 0:
                    log("본체 없음 — 이미 죽음(부활 대기), 입력 필요 없음")
                lock.release()                  # 나중에 본체가 다시 켜지면 도로 쥘 수 있게 — 개입 뒤엔 놓아준다
                time.sleep(3.0)                  # 방금 개입했으니 본체가 다시 뜰 시간을 좀 둔다(계속 뺏고 놓기 방지)
            time.sleep(POLL)
    except KeyboardInterrupt:
        log("watchdog 종료")
        lock.release()


if __name__ == "__main__":
    main()
