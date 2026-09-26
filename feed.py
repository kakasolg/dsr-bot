"""
0층 — 스냅샷 피드. 게임 메모리를 **스레드 하나**가 계속 읽어 최신 프레임을 두고, 모든 층은 그 프레임을 본다.

왜: 층마다 따로 tm.snapshot() 을 불렀다 (duel 4곳, field 17곳, moves 6곳, watch 스레드는 0.05 s 마다 또).
한 틱에 pymem 읽기가 여러 번 겹치고, 반사가 본 적 위치와 duel 이 본 위치가 다른 시점이었다.
피드는 "같은 순간의 사진 한 장"을 모두에게 준다. 읽기 비용은 프레임당 한 번.

  feed = Feed(DSRTelemetry()).start()
  s = feed.snapshot(within=5.0)      # 최신 프레임(≤ MAX_AGE 전)을 within 으로 걸러 돌려준다
  feed.right_weapon() 등 나머지는 그대로 아래 텔레메트리로 위임

규칙:
  · 프레임이 MAX_AGE 보다 낡았으면 다음 프레임을 기다린다 (최대 WAIT). "지금 읽기" 의미를 지킨다 — 퀵 종료 전후 위치 비교 등.
  · 반경이 RADIUS 를 넘는 요청(find_at 200 m)과 스레드가 죽은 경우는 직접 읽는다 (폴백, 동작은 예전과 같다).
  · 프레임의 Chr 객체는 공유한다 — 층 코드는 Chr 를 고치지 않는다 (grep 으로 확인, 2026-09-24).
  · 로딩 중엔 아래가 None 을 준다 → latest 를 지우고 None. 호출자는 예전처럼 None 을 처리한다.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from telemetry import Snapshot

RADIUS = 40.0        # 피드가 읽는 반경 — 호출자 대부분이 5~40 m
MAX_AGE = 0.05       # 이보다 낡은 프레임은 안 준다
WAIT = 0.25          # 새 프레임을 기다리는 최대 시간 (로딩 중이면 그냥 None)
MIN_PERIOD = 1 / 60  # 읽기 상한 60 Hz — 더 빨리 돌 이유가 없고 GIL 을 양보한다


class Feed:
    def __init__(self, tm, radius: float = RADIUS):
        self.tm, self.radius = tm, radius
        self.latest: Optional[Snapshot] = None
        self._cv = threading.Condition()
        self._stop = False
        self._th = threading.Thread(target=self._run, daemon=True, name="feed")
        self.frames = 0
        self.read_ms = 0.0                      # 지수 이동 평균
        self.served = {"fresh": 0, "waited": 0, "direct": 0, "none": 0}
        self.listeners: list = []               # 프레임마다 불림 (피드 스레드) — blackbox.py. 가볍게, 예외는 삼킨다

    def start(self, first: float = 2.0) -> "Feed":
        self._th.start()
        with self._cv:
            self._cv.wait_for(lambda: self.frames > 0, timeout=first)   # 첫 프레임까지 (로딩 중이면 그냥 넘어간다)
        return self

    def stop(self) -> None:
        self._stop = True

    def alive(self) -> bool:
        return self._th.is_alive() and not self._stop

    def _run(self) -> None:
        while not self._stop:
            t0 = time.time()
            try:
                s = self.tm.snapshot(within=self.radius)
            except Exception:
                s = None
            dt = time.time() - t0
            self.read_ms = dt * 1000 if not self.frames else self.read_ms * 0.95 + dt * 1000 * 0.05
            with self._cv:
                self.latest = s
                self.frames += 1
                self._cv.notify_all()
            for fn in list(self.listeners):
                try:
                    fn(s)
                except Exception:
                    pass
            rest = MIN_PERIOD - dt
            if rest > 0:
                time.sleep(rest)

    def snapshot(self, within: float = 60.0) -> Optional[Snapshot]:
        if within > self.radius or not self.alive():
            self.served["direct"] += 1
            return self.tm.snapshot(within=within)
        now = time.time()
        with self._cv:
            s = self.latest
            if s is not None and now - s.t <= MAX_AGE:
                self.served["fresh"] += 1
                return self._view(s, within)
            seen = self.frames
            self._cv.wait_for(lambda: self.frames != seen, timeout=WAIT)
            s = self.latest
        if s is None:
            self.served["none"] += 1
            return None
        self.served["waited"] += 1
        return self._view(s, within)

    @staticmethod
    def _view(s: Snapshot, within: float) -> Snapshot:
        return Snapshot(t=s.t, player=s.player, chars=[c for c in s.chars if c.dist <= within],
                        cam_yaw=s.cam_yaw, cam_pitch=s.cam_pitch, arm_style=s.arm_style,
                        flask_hp=s.flask_hp, max_flask_hp=s.max_flask_hp)

    def stats(self) -> dict:
        return {"frames": self.frames, "read_ms": round(self.read_ms, 1), **self.served}

    def __getattr__(self, name):          # 나머지(right_weapon, pos_warp, goods_count…)는 아래 텔레메트리
        return getattr(self.tm, name)
