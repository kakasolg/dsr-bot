"""
게임 어댑터 선택 — 루프(patrol/nav/learn)는 게임을 모르고, 여기서 고른 텔레메트리/패드만 쓴다.

  BOT_GAME=er   엘든링 (telemetry.Telemetry — CE 브릿지 symbols.json 필요)      [기본]
  BOT_GAME=dsr  다크소울 리마스터 (dsr_telemetry.DSRTelemetry — pymem 직결, 오프라인 필수)
                프로세스당 **피드 하나**(feed.Feed)로 감싼다 — 층마다 따로 읽지 않고 같은 프레임을 본다. BOT_FEED=0 이면 예전처럼 직접 읽기.

같은 Snapshot/Chr 모양을 돌려주므로 nav.goto 등은 그대로 동작한다. 게임마다 다른 것(리셋·휴식·소환)은 각 어댑터가 제공.
"""
from __future__ import annotations

import os

GAME = os.environ.get("BOT_GAME", "er").lower()
FEED = os.environ.get("BOT_FEED", "1") != "0"
_feed = None


def make_telemetry(names: dict | None = None):
    if GAME == "dsr":
        import dsr_telemetry
        if not FEED:
            return dsr_telemetry.DSRTelemetry(names)
        global _feed
        if _feed is None or not _feed.alive():
            import feed
            _feed = feed.Feed(dsr_telemetry.DSRTelemetry(names)).start()
        return _feed
    import telemetry
    return telemetry.Telemetry(names if names is not None else telemetry.load_names())


def load_names() -> dict:
    if GAME == "dsr":
        return {}
    import telemetry
    return telemetry.load_names()
