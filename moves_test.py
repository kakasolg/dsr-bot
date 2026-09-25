"""1층(moves) 오프라인 테스트 — 게임·패드 없이 가짜 패드로 입력 시퀀스와 타이밍을 검증한다 (2026-09-25 층 설계 4단계).

  python moves_test.py

검사:
  · combo("backstep_r1"): 스틱 놓기 → B → 0.45 s 뒤 R1, 스틱은 중립 (앞+B 는 구르기가 된다)
  · light(n=2): R1 → 0.45 s 뒤 R1, 첫 R1 은 스틱을 놓고 0.16 s 지난 뒤 (control.Pad.release_stick 규칙)
  · guard_ok=False 면 guard(True) 가 패드에 안 간다 (백스텝 스타일)
  · combo("roll_r1"): 스틱 앞 + B → 0.85 s 뒤 R1
"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
from control import B
from telemetry import Chr, Snapshot
from souls import moves as M


class FakePad:
    """control.Pad 와 같은 겉모습 — 입력을 (시각, 이름, 값) 으로 기록만 한다."""
    STICK_RELEASE_S = control.Pad.STICK_RELEASE_S

    def __init__(self):
        self.t0 = time.time()
        self.log: list = []
        self._stick_on = False
        self._stick_off_t = 0.0
        self._due: dict = {}

    def _rec(self, name, *v):
        self.log.append((round(time.time() - self.t0, 3), name, *v))

    def move(self, x, y):
        on = abs(x) > 1e-3 or abs(y) > 1e-3
        if self._stick_on and not on:
            self._stick_off_t = time.time()
        self._stick_on = on
        self._rec("stick", round(x, 2), round(y, 2))

    def release_stick(self):
        if self._stick_on:
            self.move(0.0, 0.0)
        left = self.STICK_RELEASE_S - (time.time() - self._stick_off_t)
        if left > 0:
            time.sleep(left)

    def tap(self, button, hold=0.08, stick_ok=False):
        if button == B.XUSB_GAMEPAD_RIGHT_SHOULDER and not stick_ok:
            self.release_stick()
        self._rec("tap", {B.XUSB_GAMEPAD_B: "B", B.XUSB_GAMEPAD_RIGHT_SHOULDER: "R1", B.XUSB_GAMEPAD_X: "X",
                          B.XUSB_GAMEPAD_A: "A", B.XUSB_GAMEPAD_RIGHT_THUMB: "R3"}.get(button, str(button)))
        self._due[button] = time.time() + hold

    def _r2(self, hold):
        self._rec("R2")

    def guard(self, on):
        self._rec("guard", on)

    def hold(self, button, on):
        self._rec("hold", str(button), on)

    def release_due(self):
        now = time.time()
        for b in [b for b, t in self._due.items() if now >= t]:
            del self._due[b]

    def neutral(self):
        self.move(0.0, 0.0)

    def lock_on(self): self.tap(B.XUSB_GAMEPAD_RIGHT_THUMB, 0.06)
    def use_item(self): self.tap(B.XUSB_GAMEPAD_X, 0.1)
    def item_next(self): self._rec("item_next")


class FakeTm:
    """스냅샷: 플레이어는 원점, heading 0 (정면 = -z 쪽… rel_angle 규약: fwd = heading+π), 적은 정면 1.2 m."""
    def __init__(self):
        self.anim = -1

    def snapshot(self, within=40.0):
        p = Chr(1, 0, 0, 700, 700, 0.0, 0.0, 0.0, sp=90, max_sp=90, anim=self.anim, heading=0.0)
        c = Chr(10, 254000, 6, 75, 75, 0.0, 0.0, -1.2, anim=-1, dist=1.2)
        return Snapshot(t=time.time(), player=p, chars=[c], cam_yaw=0.0)


def taps(pad, name):
    return [t for t, k, *v in pad.log if k == "tap" and v and v[0] == name]


def main() -> None:
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("  OK  " if cond else "  FAIL") + " " + msg)
        ok = ok and cond

    # 1) 백스텝 공격 조합
    pad, tm = FakePad(), FakeTm()
    mv = M.Moves(tm, pad)
    s = tm.snapshot(); c = s.chars[0]
    pad.move(0.0, 1.0)                                   # 직전에 앞으로 밀고 있었다
    t0 = time.time()
    h = mv.combo("backstep_r1", s, c, nm=None)
    b, r1 = taps(pad, "B"), taps(pad, "R1")
    check(h.skipped is None and len(b) == 1 and len(r1) == 1, f"backstep_r1 눌림 B{b} R1{r1} skipped={h.skipped}")
    if b and r1:
        check(0.38 <= r1[0] - b[0] <= 0.55, f"B → R1 간격 {r1[0]-b[0]:.2f} s (0.45 ± 0.07)")
        sticks_before_b = [v for t, k, *v in pad.log if k == "stick" and t <= b[0]]
        check(sticks_before_b and sticks_before_b[-1] == [0.0, 0.0], f"B 직전 스틱 중립 {sticks_before_b[-1] if sticks_before_b else None}")
        check(b[0] - (0.0) >= 0.14, f"스틱 놓고 {b[0]:.2f} s 뒤 B (≥ 0.16 s 규칙)")

    # 2) 약공 2연타 타이밍
    pad, tm = FakePad(), FakeTm(); mv = M.Moves(tm, pad); s = tm.snapshot(); c = s.chars[0]
    pad.move(0.3, 0.9)
    h = mv.light(s, c, n=2, sp_second=40)
    r1 = taps(pad, "R1")
    check(len(r1) == 2, f"light×2 R1 {r1}")
    if len(r1) == 2:
        check(0.38 <= r1[1] - r1[0] <= 0.55, f"R1 간격 {r1[1]-r1[0]:.2f} s (0.45)")
        check(r1[0] >= 0.14, f"첫 R1 은 스틱 놓고 {r1[0]:.2f} s 뒤")

    # 3) guard_ok=False 면 방패가 안 간다
    pad, tm = FakePad(), FakeTm(); mv = M.Moves(tm, pad); mv.guard_ok = False
    mv.guard(True)
    check(not [1 for t, k, *v in pad.log if k == "guard" and v[0] is True], "guard_ok=False → guard(True) 무시")
    mv.guard_ok = True; mv.guard(True)
    check(bool([1 for t, k, *v in pad.log if k == "guard" and v[0] is True]), "guard_ok=True → guard(True) 전달")

    # 4) 구르기 약공: 앞스틱 + B, 0.85 s 뒤 R1
    pad, tm = FakePad(), FakeTm(); mv = M.Moves(tm, pad); s = tm.snapshot(); c = s.chars[0]
    h = mv.combo("roll_r1", s, c, nm=None)
    b, r1 = taps(pad, "B"), taps(pad, "R1")
    sticks_before_b = [v for t, k, *v in pad.log if k == "stick" and t <= (b[0] if b else 9)]
    check(len(b) == 1 and len(r1) == 1 and sticks_before_b and sticks_before_b[-1] != [0.0, 0.0], f"roll_r1: 스틱 {sticks_before_b[-1] if sticks_before_b else None} B{b} R1{r1}")
    if b and r1:
        check(0.5 <= r1[0] - b[0] <= 0.65, f"B → R1 간격 {r1[0]-b[0]:.2f} s (0.55)")

    print("\n전체:", "OK" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
