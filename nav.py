"""
네비게이션 프리미티브 — 글로벌 좌표의 목표 지점까지 걸어간다.

  goto(tm, pad, (x, z)) : 카메라 yaw 기준으로 스틱을 계속 조향하며 목표까지 이동.
                          2초 동안 0.3m 도 못 가면 "막힘" → 점프 + 옆걸음으로 빠져나가기 시도.
  실측 (2026-09-21): 스틱 앞 = cam_yaw 방향, 오른쪽 = +90°. 걷기 ~2.5 m/s, B 홀드 달리기 ~3.7 m/s.

── 알려진 한계 ──────────────────────────────
 · 장애물 회피 없음 (직선 조향). 웨이포인트를 촘촘히 두는 것으로 대신한다.
 · 높이(y) 는 무시한다. 낙하 위험 구간은 웨이포인트로 우회.
"""
from __future__ import annotations

import math
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import telemetry

YAW_OFFSET = 0.0
FLIP_X = False
SPRINT_BEYOND = 8.0     # 이보다 멀면 달리기
STUCK_WINDOW = 2.0      # 초
STUCK_MIN_PROGRESS = 0.3  # m


JUMP_PERIOD = 1.2       # guardjump 모드: 이 주기로 점프
JUMP_GUARD_OFF = 0.35   # 점프 직전·직후 LB 를 놓는 시간


class Mover:
    """이동 모드 상태기. 매 틱 set(mode) 로 원하는 모드를 주면 필요한 버튼 상태를 유지한다.
      walk       아무 것도 안 누름 (스태미나 회복)
      sprint     B 홀드
      guardjump  LB 홀드 + JUMP_PERIOD 마다 (LB 해제 → A 점프 → LB) — 빠르고, 점프 무적 + 가드로 보호
    """

    def __init__(self, pad: control.Pad):
        self.pad = pad
        self.mode = "walk"
        self.next_jump = 0.0
        self.guard_on = False
        self.jump_at = None

    def set(self, mode: str) -> None:
        now = time.time()
        if mode != self.mode:
            self.pad.sprint(mode == "sprint")
            if mode != "guardjump" and self.guard_on:
                self.pad.guard(False)
                self.guard_on = False
            if mode == "guardjump":
                self.next_jump = now + JUMP_PERIOD * 0.5
            self.mode = mode
        if mode == "guardjump":
            if self.jump_at is not None:
                if now - self.jump_at > JUMP_GUARD_OFF and not self.guard_on:
                    self.pad.guard(True)
                    self.guard_on = True
                    self.jump_at = None
            elif now >= self.next_jump:
                if self.guard_on:
                    self.pad.guard(False)
                    self.guard_on = False
                self.pad.jump()
                self.jump_at = now
                self.next_jump = now + JUMP_PERIOD
            elif not self.guard_on:
                self.pad.guard(True)
                self.guard_on = True

    def stop(self) -> None:
        self.pad.neutral()
        self.mode, self.guard_on, self.jump_at = "walk", False, None


def goto(tm: telemetry.Telemetry, pad: control.Pad, target: tuple[float, float], tolerance: float = 1.5,
         timeout: float = 60.0, on_tick=None, log=print, sprint_always: bool = False, mode_fn=None,
         mover: "Mover | None" = None) -> str:
    """반환: 'arrived' | 'timeout' | 'dead' | 'lost'.
    mode_fn(snapshot) -> 'walk'|'sprint'|'guardjump' 를 주면 매 틱 이동 모드를 정한다 (없으면 거리 기반 sprint)."""
    tx, tz = target
    t_start = time.time()
    last_progress_t, last_progress_d = t_start, None
    escapes = 0
    no_cam_since = None
    mover = mover or Mover(pad)
    try:
        while True:
            now = time.time()
            if now - t_start > timeout:
                return "timeout"
            s = tm.snapshot(within=30.0)
            if s is None or s.player.gx is None or s.cam_yaw is None:
                pad.neutral()
                time.sleep(0.1)
                if now - t_start > 15 and s is None:
                    return "lost"
                if s is not None and s.cam_yaw is None:   # camadr 가 죽으면 조향 불가 — 서서 timeout 을 기다리지 않는다
                    no_cam_since = no_cam_since or now
                    if now - no_cam_since > 5:
                        log("  카메라 yaw 없음 5 s — lost")
                        return "lost"
                continue
            no_cam_since = None
            p = s.player
            if p.hp <= 0:
                pad.neutral()
                return "dead"
            dx, dz = tx - p.gx, tz - p.gz
            dist = math.hypot(dx, dz)
            if on_tick:
                on_tick(s, dist)
            if dist <= tolerance:
                pad.neutral()
                return "arrived"

            # 막힘 감지
            if last_progress_d is None or last_progress_d - dist >= STUCK_MIN_PROGRESS:
                last_progress_d, last_progress_t = dist, now
            elif now - last_progress_t > STUCK_WINDOW:
                escapes += 1
                log(f"  stuck at {dist:.1f} m — escape #{escapes}")
                mover.set("walk")
                pad.jump()
                side = 1.0 if escapes % 2 else -1.0
                sx, sy = control.world_to_stick(dx, dz, s.cam_yaw, YAW_OFFSET, FLIP_X)
                pad.move(sx + side * 0.8, sy * 0.3)
                time.sleep(0.7)
                last_progress_d, last_progress_t = dist, time.time()
                if escapes >= 6:
                    pad.neutral()
                    return "timeout"
                continue

            sx, sy = control.world_to_stick(dx, dz, s.cam_yaw, YAW_OFFSET, FLIP_X)
            pad.move(sx, sy)
            if mode_fn:
                mover.set(mode_fn(s))
            else:
                mover.set("sprint" if (sprint_always or dist > SPRINT_BEYOND) else "walk")
            time.sleep(0.05)
    finally:
        mover.stop()


if __name__ == "__main__":
    # 테스트: 카메라 방향으로 8 m 앞 지점까지 갔다가 출발점으로 복귀
    tm = telemetry.Telemetry()
    pad = control.Pad()
    s = tm.snapshot()
    p = s.player
    start = (p.gx, p.gz)
    ahead = (p.gx + 8 * math.sin(s.cam_yaw), p.gz + 8 * math.cos(s.cam_yaw))
    print(f"start={start[0]:.1f},{start[1]:.1f} → ahead={ahead[0]:.1f},{ahead[1]:.1f}")
    r = goto(tm, pad, ahead, on_tick=lambda s, d: None)
    print("leg 1:", r, "pos=", round(tm.snapshot().player.gx, 1), round(tm.snapshot().player.gz, 1))
    time.sleep(0.5)
    r = goto(tm, pad, start)
    print("leg 2:", r, "pos=", round(tm.snapshot().player.gx, 1), round(tm.snapshot().player.gz, 1))
