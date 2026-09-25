"""BIOS 층이 쓸 펜싱(fencing) — 타임스탬프 파일 대신 OS 파일 잠금.
사용자 2026-09-25 리서치 요청 뒤: Patroni(PostgreSQL HA) 같은 실제 시스템은 하트비트 하나만 보고
"죽었다"고 넘기지 않는다 — 반드시 펜싱한다(새 액터가 넘겨받기 전에 예전 액터가 확실히 죽었음을 OS가
보장). heartbeat.json 읽기 실패 한 번을 "죽음"으로 오판해 watchdog 이 살아있는 본체와 동시에 패드를
잡아 메뉴가 걸린 채 멈춘 사고(사용자: "최악이네") 뒤 이걸로 바꿨다.

  from botlock import BotLock
  lock = BotLock()
  if not lock.acquire():
      ...(이미 다른 본체가 돌고 있다 — 겹쳐 켜는 사고도 같이 막는다)
  ...
  lock.release()   # (안 불러도 프로세스가 죽으면 OS 가 풀어준다 — 이게 핵심)

watchdog 쪽:
  if lock.acquire():      # 성공 = 아무도 안 쥐고 있다 = 본체가 진짜 죽었다. 추측이 아니라 확인.
      rescue(...)
      lock.release()       # 나중에 본체가 다시 켜지면 도로 쥘 수 있게
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCK_PATH = ROOT / "data" / "bot.lock"


class BotLock:
    def __init__(self):
        self._f = None

    def acquire(self) -> bool:
        """지금 아무도 안 쥐고 있으면 잠그고 True. 이미 누가 쥐고 있으면(그 프로세스가 살아있으면) False —
        추측이 아니라 OS 가 보장한다(그 프로세스가 죽으면, 강제 종료여도, 자동으로 풀린다)."""
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        f = LOCK_PATH.open("a+")
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._f = f
        return True

    def release(self) -> None:
        if self._f is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt
                self._f.seek(0)
                msvcrt.locking(self._f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self._f.close()
        self._f = None
