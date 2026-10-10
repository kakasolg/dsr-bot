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
  · 기다린 뒤에도 STALE_S 보다 낡은 프레임이면 None (피드 스레드가 멈춤) — 낡은 프레임을 새것처럼 주지 않는다.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import ctl
from telemetry import Snapshot

RADIUS = 40.0        # 피드가 읽는 반경 — 호출자 대부분이 5~40 m
MAX_AGE = 0.05       # 이보다 낡은 프레임은 안 준다
WAIT = 0.25          # 새 프레임을 기다리는 최대 시간 (로딩 중이면 그냥 None)
MIN_PERIOD = 1 / 60  # 읽기 상한 60 Hz — 더 빨리 돌 이유가 없고 GIL 을 양보한다
# 임시값 (P0-C, 근거 등급: 임시 제안값 — 정책 상수 아님): 기다린 뒤에도 이보다 낡은 프레임은 주지 않는다 (None).
# 예전엔 WAIT 가 지나도 새 프레임이 없으면 옛 latest 를 '방금 것'처럼 줬다 — 피드 스레드가 죽지 않고 멈추면 낡은 화면으로 판단
STALE_S = 0.25


class Feed:
    def __init__(self, tm, radius: float = RADIUS):
        self.tm, self.radius = tm, radius
        self.latest: Optional[Snapshot] = None
        self._cv = threading.Condition()
        self._stop = False
        self._th = threading.Thread(target=self._run, daemon=True, name="feed")
        self.frames = 0
        self.read_ms = 0.0                      # 지수 이동 평균
        self.served = {"fresh": 0, "waited": 0, "direct": 0, "none": 0, "stale": 0}
        self.listeners: list = []               # 프레임마다 불림 (피드 스레드) — blackbox.py. 가볍게, 예외는 삼킨다
        self._obs: tuple | None = None          # P1-D: (kind, pc) of the open missing / stale stretch — records only

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
            pc = time.perf_counter_ns()
            dt = time.time() - t0
            self.read_ms = dt * 1000 if not self.frames else self.read_ms * 0.95 + dt * 1000 * 0.05
            if s is not None:                   # P1-D: which frame this is and when our read ended (nothing steers by them)
                s.fseq, s.pc = self.frames + 1, pc
            with self._cv:
                self.latest = s
                self.frames += 1
                self._cv.notify_all()
            if ctl.frames_on():
                self._frame_rec(s, pc, dt)
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
                if self._obs is not None:
                    self._obs_rec(None)
                return self._view(s, within)
            seen = self.frames
            self._cv.wait_for(lambda: self.frames != seen, timeout=WAIT)
            s = self.latest
        if s is None:
            self.served["none"] += 1
            self._obs_rec("none")
            return None
        if time.time() - s.t > STALE_S:
            self.served["stale"] += 1
            self._obs_rec("stale")
            return None
        self.served["waited"] += 1
        self._obs_rec(None)
        return self._view(s, within)

    @staticmethod
    def _view(s: Snapshot, within: float) -> Snapshot:
        return Snapshot(t=s.t, player=s.player, chars=[c for c in s.chars if c.dist <= within],
                        cam_yaw=s.cam_yaw, cam_pitch=s.cam_pitch, arm_style=s.arm_style,
                        flask_hp=s.flask_hp, max_flask_hp=s.max_flask_hp, fseq=s.fseq, pc=s.pc)

    # ── P1-D records (run.py --ctl / --ctl-frames). Records only: snapshot() returns the same thing with or without them ──
    def _obs_rec(self, kind: str | None) -> None:
        """A missing / stale stretch opens (kind) or closes (None, with how long it lasted). Transitions only."""
        if not ctl.on():
            return
        try:
            cur = self._obs
            if kind is None:
                if cur is not None:
                    self._obs = None
                    ctl.emit("obs", ev="recovered", was=cur[0], dur_ms=round((time.perf_counter_ns() - cur[1]) / 1e6, 1),
                             served=dict(self.served))
            elif cur is None or cur[0] != kind:
                self._obs = (kind, time.perf_counter_ns() if cur is None else cur[1])
                ctl.emit("obs", ev=kind, served=dict(self.served))
        except Exception:
            pass

    def _frame_rec(self, s, pc: int, dt: float) -> None:
        try:
            p = s.player if s is not None else None
            ctl.frame(fseq=self.frames, snap_t=None if s is None else s.t, pc_read_end=pc, read_ms=round(dt * 1000, 2),
                      none=s is None, x=getattr(p, "x", None), y=getattr(p, "y", None), z=getattr(p, "z", None),
                      heading=getattr(p, "heading", None), anim=getattr(p, "anim", None), hp=getattr(p, "hp", None),
                      sp=getattr(p, "sp", None), cam_yaw=None if s is None else s.cam_yaw,
                      n_chars=None if s is None else len(s.chars))
        except Exception:
            pass

    def stats(self) -> dict:
        return {"frames": self.frames, "read_ms": round(self.read_ms, 1), **self.served}

    def __getattr__(self, name):          # 나머지(right_weapon, pos_warp, goods_count…)는 아래 텔레메트리
        return getattr(self.tm, name)
