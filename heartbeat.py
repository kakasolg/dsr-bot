"""심장박동 — 본체(run.py)가 살아있다는 신호를 파일에 남긴다. watchdog.py 가 이걸 본다.
사용자 2026-09-25: "Bios, os, application 레이어처럼" — 본체 프로세스가 죽어도(강제 종료 포함) 감시자가 따로 살아있게.

  from heartbeat import Heartbeat
  hb = Heartbeat().start()   # 별도 스레드로 1 s 마다 파일 갱신
  ...
  hb.stop()                  # (finally 에서, 안 불러도 프로세스가 죽으면 파일 갱신이 저절로 끊긴다)
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILE = ROOT / "data" / "heartbeat.json"
PERIOD = 0.2   # 별도 스레드라 본체 로직이 느려도 계속 갱신된다 — 끊기는 건 프로세스가 죽었을 때뿐(사용자 2026-09-25: "그 정도는 항상 체크해야지")


class Heartbeat:
    def __init__(self, tag: str = ""):
        self.tag = tag
        self._stop = threading.Event()
        self._th: threading.Thread | None = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                FILE.parent.mkdir(parents=True, exist_ok=True)
                FILE.write_text(json.dumps({"t": time.time(), "tag": self.tag}), encoding="utf-8")
            except OSError:
                pass
            self._stop.wait(PERIOD)

    def start(self) -> "Heartbeat":
        self._th = threading.Thread(target=self._run, daemon=True)
        self._th.start()
        return self

    def stop(self) -> None:
        self._stop.set()
