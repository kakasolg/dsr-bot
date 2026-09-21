"""
입력 계층 — ViGEmBus 가상 Xbox 360 패드(vgamepad)로 엘든링을 조작한다.

엘든링 Xbox 배치: 왼스틱 이동(카메라 기준), 오른스틱 카메라, B 구르기/달리기(홀드), A 점프,
X 아이템 사용(성배병), Y 상호작용 / Y홀드+RB 오른손 무기 양손, RB 약공격, LB 가드(양손일 때만 — 왼손이 비면 한손 상태의 LB 는 주먹), R3 락온.

이동 방향은 **카메라 yaw 기준**이라, 월드 방향 → 스틱 벡터 변환에 telemetry 의 cam_yaw 를 쓴다.
축 부호·오프셋은 calibrate() 로 실측해서 결정한다 (게임마다 다르고 문서로 알 수 없음).
"""
from __future__ import annotations

import math
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import ctypes

import vgamepad as vg

B = vg.XUSB_BUTTON


def focus_game() -> bool:
    """엘든링 창을 포그라운드로. 가상 패드 입력은 게임이 앞에 있을 때만 먹는다."""
    u = ctypes.windll.user32
    lua = u.FindWindowW(None, "Lua Engine")   # 테이블 스크립트 에러가 띄우는 CE 창 — 포커스를 뺏으므로 숨김
    if lua:
        u.ShowWindow(lua, 0)
    import env
    h = u.FindWindowW(None, "DARK SOULS™: REMASTERED" if env.GAME == "dsr" else "ELDEN RING™")
    if not h:
        return False
    u.keybd_event(0x12, 0, 0, 0)   # ALT down/up: 다른 프로세스가 앞에 있을 때 SetForegroundWindow 거부를 푸는 고전 트릭
    u.keybd_event(0x12, 0, 2, 0)
    u.ShowWindow(h, 9)
    u.SetForegroundWindow(h)
    time.sleep(0.3)
    return u.GetForegroundWindow() == h


class Pad:
    def __init__(self):
        self.pad = vg.VX360Gamepad()
        self.neutral()
        time.sleep(2.0)  # 게임이 새 XInput 장치를 인식할 시간 (바로 누르면 첫 입력이 씹힘)

    def neutral(self) -> None:
        self.pad.reset()
        self.pad.update()

    def move(self, x: float, y: float) -> None:
        """왼스틱. x: 오른쪽 +, y: 앞 + (각 -1..1)"""
        m = math.hypot(x, y)
        if m > 1.0:
            x, y = x / m, y / m
        self.pad.left_joystick_float(x_value_float=x, y_value_float=y)
        self.pad.update()

    def look(self, x: float, y: float) -> None:
        """오른스틱 (카메라)."""
        self.pad.right_joystick_float(x_value_float=x, y_value_float=y)
        self.pad.update()

    def tap(self, button, hold: float = 0.08) -> None:
        self.pad.press_button(button)
        self.pad.update()
        time.sleep(hold)
        self.pad.release_button(button)
        self.pad.update()

    def hold(self, button, on: bool) -> None:
        (self.pad.press_button if on else self.pad.release_button)(button)
        self.pad.update()

    # 의미 있는 이름들
    def dodge(self) -> None: self.tap(B.XUSB_GAMEPAD_B, 0.06)
    def jump(self) -> None: self.tap(B.XUSB_GAMEPAD_A, 0.06)
    def use_item(self) -> None: self.tap(B.XUSB_GAMEPAD_X, 0.1)
    def interact(self) -> None: self.tap(B.XUSB_GAMEPAD_Y, 0.1)
    def attack(self) -> None: self.tap(B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06)
    def lock_on(self) -> None: self.tap(B.XUSB_GAMEPAD_RIGHT_THUMB, 0.06)
    def sprint(self, on: bool) -> None: self.hold(B.XUSB_GAMEPAD_B, on)
    def guard(self, on: bool) -> None: self.hold(B.XUSB_GAMEPAD_LEFT_SHOULDER, on)

    def two_hand_right(self) -> None:
        """Y 홀드 + RB = 오른손 무기 양손 잡기 토글 (ArmStyle 3 ↔ 1). 실측 0.4 s 뒤 상태가 바뀐다."""
        self.hold(B.XUSB_GAMEPAD_Y, True)
        time.sleep(0.15)
        self.tap(B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.08)
        time.sleep(0.15)
        self.hold(B.XUSB_GAMEPAD_Y, False)


def world_to_stick(dx: float, dz: float, cam_yaw: float, yaw_offset: float, flip_x: bool) -> tuple[float, float]:
    """월드 평면 방향(dx, dz) 을 카메라 yaw 기준 스틱(x, y) 로. 부호/오프셋은 calibrate 결과."""
    ang = math.atan2(dx, dz)            # 월드 방향각
    rel = ang - (cam_yaw + yaw_offset)   # 카메라 기준 상대각
    sx, sy = math.sin(rel), math.cos(rel)
    return (-sx if flip_x else sx), sy
