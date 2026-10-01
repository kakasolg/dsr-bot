"""Camera follow — keeps turning the camera toward the enemy the bot is fighting.

User 2026-09-26: "The bot should actively turn the camera to face the enemy. Since the bot doesn't actually look at the
camera … when I watch, the camera points elsewhere and I often can't tell what it's doing." — bot decisions use telemetry only,
so camera direction doesn't matter to them, but it matters to the human watching the screen (and to R3 auto lock-on).

  cam = CamFollow(mv, esc, log).start()   # run.py
  mv.cam_target = ptr                      # set by layer 4 (field.fight·lure). If None, the nearest awake enemy

Hands off when:
  · locked on — the right stick switches the lock-on target
  · mv.cam_busy — layer 1 is using the camera directly (knife lock-on)
  · emergency escape — the pad is frozen
Walk/attack directions recompute the stick every tick from the current cam_yaw (control.world_to_stick), so body direction stays the same even as the camera turns.
"""
from __future__ import annotations

import threading
import time

DEADBAND = 10.0      # don't turn within this (was 25 — the screen shook less, but the camera sat 20°+ off the foe during fights)
AUTO_R = 12.0        # radius for awake enemies to look at when there's no cam_target
TICK = 0.05          # was 0.12
# ── 카메라·캐릭터·적 정렬 ([MoKa] 2026-10-01) ─────────────────────────────
#  "액션할 때 카메라 시점과 캐릭터와 적의 정렬이 잘되면 생각하는 플레이가 잘 나오는데, 아니면 안 될 확률이 높아 — 봇만이 아니라 이 게임을 하는
#   모든 플레이어가 겪는 현상. 카메라 따라오는 것도 더 빠르고, 신경 써서 잡는 것도 확인하는 게 좋겠다" → 더 빨리·더 가까이 따라가고,
#   싸움 중 카메라가 목표에서 얼마나 벗어나 있었는지 재서(stats) 실행 끝에 남긴다


class CamFollow:
    def __init__(self, mv, esc=None, log=print):
        self.mv, self.esc, self.log = mv, esc, log
        self._stop = False
        self.pulses = 0
        self.errs: list[float] = []          # |camera − target| (°) each tick a target was set — stats() at the end
        self.th = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "CamFollow":
        self.th.start()
        return self

    def stats(self) -> str:
        """Camera off the fight target: median / 90th percentile / share within DEADBAND (°)."""
        e = sorted(self.errs)
        if not e:
            return "카메라 정렬: 기록 없음"
        q = lambda f: e[min(len(e) - 1, int(f * len(e)))]
        return (f"카메라 정렬: 싸움 중 목표에서 중앙 {q(0.5):.0f}° · 90 % {q(0.9):.0f}° · {DEADBAND:.0f}° 안 "
                f"{sum(1 for x in e if x <= DEADBAND) / len(e):.0%} ({len(e)}번)")

    def stop(self) -> None:
        self._stop = True
        self.th.join(timeout=1.0)
        self.mv.pad.look(0.0, 0.0)

    def target(self, s):
        """The cam_target if alive, otherwise the nearest moving (anim not -1) enemy within AUTO_R."""
        t = self.mv.find(s, self.mv.cam_target) if self.mv.cam_target is not None else None
        if t is not None and t.hp > 0:
            return t
        awake = [c for c in s.hostile(AUTO_R) if c.anim not in (-1, None)]
        return min(awake, key=lambda c: c.dist, default=None)

    def _run(self) -> None:
        had_sign = self.mv.LOOK_SIGN is not None
        while not self._stop:
            time.sleep(TICK)
            try:
                if self.mv.cam_busy or (self.esc is not None and self.esc.escaping):
                    continue
                if self.mv.tm.lock_target() not in (None, -1):
                    continue
                s = self.mv.snap(AUTO_R + 30.0)
                c = self.target(s) if s is not None else None
                if c is None:
                    continue
                err = self.mv.cam_err(s, c.x, c.z)
                if err is not None and self.mv.cam_target is not None:
                    self.errs.append(abs(err))
                if err is None or abs(err) <= DEADBAND:
                    continue
                self.mv.look_pulse(err, 0.04 if abs(err) < 25 else 0.08 if abs(err) < 60 else 0.12)
                self.pulses += 1
                if not had_sign and self.mv.LOOK_SIGN is not None:
                    had_sign = True
                    self.log(f"   카메라: 오른스틱 +x → cam_yaw {'+' if self.mv.LOOK_SIGN > 0 else '−'} (첫 펄스로 배움)")
            except Exception as ex:                        # don't stop the run because of the camera
                self.log(f"   카메라 따라가기 오류: {type(ex).__name__}: {ex}")
                time.sleep(1.0)
