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

DEADBAND = 25.0      # don't turn within this — keeps the screen from constantly shaking during a fight
AUTO_R = 12.0        # radius for awake enemies to look at when there's no cam_target
TICK = 0.12


class CamFollow:
    def __init__(self, mv, esc=None, log=print):
        self.mv, self.esc, self.log = mv, esc, log
        self._stop = False
        self.pulses = 0
        self.th = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "CamFollow":
        self.th.start()
        return self

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
                if err is None or abs(err) <= DEADBAND:
                    continue
                self.mv.look_pulse(err, 0.06 if abs(err) < 60 else 0.1)
                self.pulses += 1
                if not had_sign and self.mv.LOOK_SIGN is not None:
                    had_sign = True
                    self.log(f"   카메라: 오른스틱 +x → cam_yaw {'+' if self.mv.LOOK_SIGN > 0 else '−'} (첫 펄스로 배움)")
            except Exception as ex:                        # don't stop the run because of the camera
                self.log(f"   카메라 따라가기 오류: {type(ex).__name__}: {ex}")
                time.sleep(1.0)
