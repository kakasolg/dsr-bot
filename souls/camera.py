"""카메라 따라가기 — 봇이 상대하는 적 쪽으로 카메라를 계속 돌린다.

사용자 2026-09-26: "봇이 적극적으로 카메라 방향을 돌려서 적을 바라보게 해줘야 할 것 같아. 봇은 실제로는 카메라를 보지 않기
때문에 … 나는 볼 때 카메라 방향이 달라서 뭘 하고 있는지 모를 때도 많아." — 봇 판단은 텔레메트리만 보니 카메라가 어디를 향하든
상관없지만, 화면을 보는 사람(과 R3 자동 락온)에겐 중요하다.

  cam = CamFollow(mv, esc, log).start()   # run.py
  mv.cam_target = ptr                      # 4층(field.fight·lure)이 넣는다. None 이면 가장 가까운 깨어 있는 적

손대지 않는 때:
  · 락온 중 — 오른스틱이 락온 대상을 바꾼다
  · mv.cam_busy — 1층이 카메라를 직접 쓰는 중(나이프 락온)
  · 긴급 탈출 중 — 패드가 얼어 있다
걷기·공격 방향은 틱마다 그때의 cam_yaw 로 스틱을 다시 계산하므로(control.world_to_stick) 카메라가 돌아도 몸 방향은 그대로다.
"""
from __future__ import annotations

import threading
import time

DEADBAND = 25.0      # 이 안이면 안 돌린다 — 싸우는 중 화면이 계속 흔들리지 않게
AUTO_R = 12.0        # cam_target 이 없을 때 볼 깨어 있는 적의 반경
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
        """cam_target 이 살아 있으면 그놈, 아니면 AUTO_R 안에서 움직이는(애니 -1 아님) 가장 가까운 적."""
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
            except Exception as ex:                        # 카메라 때문에 판을 멈추지 않는다
                self.log(f"   카메라 따라가기 오류: {type(ex).__name__}: {ex}")
                time.sleep(1.0)
