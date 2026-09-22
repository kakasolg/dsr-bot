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
import ctypes.wintypes

import vgamepad as vg

B = vg.XUSB_BUTTON


_game_hwnd = None


def game_in_front() -> bool:
    """게임 창이 포그라운드인가 (틱마다 불러도 싸다)."""
    u = ctypes.windll.user32
    import env
    global _game_hwnd
    if not _game_hwnd:
        _game_hwnd = u.FindWindowW(None, "DARK SOULS™: REMASTERED" if env.GAME == "dsr" else "ELDEN RING™")
    return bool(_game_hwnd) and u.GetForegroundWindow() == _game_hwnd


def focus_game() -> bool:
    """엘든링 창을 포그라운드로. 가상 패드 입력은 게임이 앞에 있을 때만 먹는다."""
    u = ctypes.windll.user32
    lua = u.FindWindowW(None, "Lua Engine")   # 테이블 스크립트 에러가 띄우는 CE 창 — 포커스를 뺏으므로 숨김
    if lua:
        u.ShowWindow(lua, 0)
    # Windows IME/이모지 패널(TextInputHost, "Windows Input Experience")이 앞에 붙으면 게임이 포그라운드를 못 받는다 — 숨긴다
    ime = u.FindWindowW(None, "Windows Input Experience")
    if ime and u.GetForegroundWindow() == ime:
        u.ShowWindow(ime, 0)
        u.keybd_event(0x1B, 0, 0, 0)
        u.keybd_event(0x1B, 0, 2, 0)
        time.sleep(0.2)
    import env
    h = u.FindWindowW(None, "DARK SOULS™: REMASTERED" if env.GAME == "dsr" else "ELDEN RING™")
    if not h:
        return False
    u.keybd_event(0x12, 0, 0, 0)   # ALT down/up: 다른 프로세스가 앞에 있을 때 SetForegroundWindow 거부를 푸는 고전 트릭
    u.keybd_event(0x12, 0, 2, 0)
    u.ShowWindow(h, 9)
    u.SetForegroundWindow(h)
    time.sleep(0.2)
    if u.GetForegroundWindow() != h:
        # 그래도 안 되면(숨은 IME 창이 포그라운드를 쥔 채 안 놓을 때) 포그라운드 스레드에 입력을 붙여서 넘긴다
        k = ctypes.windll.kernel32
        fg = u.GetForegroundWindow()
        fg_tid = u.GetWindowThreadProcessId(fg, None) if fg else 0
        my_tid = k.GetCurrentThreadId()
        if fg_tid and fg_tid != my_tid:
            u.AttachThreadInput(my_tid, fg_tid, True)
            u.BringWindowToTop(h)
            u.SetForegroundWindow(h)
            u.AttachThreadInput(my_tid, fg_tid, False)
        time.sleep(0.2)
    if u.GetForegroundWindow() != h:
        # 최후: 게임 창 제목줄을 실제로 클릭한다 (게임 입력엔 영향 없음)
        r = ctypes.wintypes.RECT()
        u.GetWindowRect(h, ctypes.byref(r))
        x, y = (r.left + r.right) // 2, r.top + 12
        old = ctypes.wintypes.POINT()
        u.GetCursorPos(ctypes.byref(old))
        u.SetCursorPos(x, y)
        u.mouse_event(2, 0, 0, 0, 0)
        u.mouse_event(4, 0, 0, 0, 0)
        u.SetCursorPos(old.x, old.y)
        time.sleep(0.2)
    return u.GetForegroundWindow() == h


class Pad:
    def __init__(self):
        self._due: dict = {}      # 버튼 → 뗄 시각 (tap 이 자지 않도록)
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
        """버튼을 누르고 **뗄 시각만 예약**한다 — 자지 않는다.

        예전엔 누른 뒤 time.sleep(hold) 했다. 그 동안 감지 루프가 통째로 멈춰서, 공격 한 번에 한 틱을
        버렸다 (틱 65 ms, 공격 hold 60 ms — 사용자 지적: "순차적으로 하는 것 같다"). 뗄 시각은
        release_due() 가 매 틱 처리한다."""
        self.pad.press_button(button)
        self.pad.update()
        self._due[button] = time.time() + hold

    def release_due(self) -> None:
        """예약된 버튼 떼기 — 감지 루프가 매 틱 부른다."""
        if not self._due:
            return
        now = time.time()
        done = [b for b, t in self._due.items() if now >= t]
        for b in done:
            self.pad.release_button(b)
            del self._due[b]
        if done:
            self.pad.update()

    def hold(self, button, on: bool) -> None:
        (self.pad.press_button if on else self.pad.release_button)(button)
        self.pad.update()

    # 의미 있는 이름들
    def dodge(self) -> None: self.tap(B.XUSB_GAMEPAD_B, 0.06)
    def jump(self) -> None: self.tap(B.XUSB_GAMEPAD_A, 0.06)
    def use_item(self) -> None: self.tap(B.XUSB_GAMEPAD_X, 0.1)
    def interact(self) -> None:
        # DSR 에서 Y 는 상호작용이 아니라 **양손 파지 토글**이다. 이걸 눌렀더니 오른손 무기를 양손으로 잡아
        # 왼손 방패가 빠졌고, 봇이 가드를 못 한 채 해골에게 맞아 죽었다 (실측). DS1 의 상호작용은 A.
        import env
        self.tap(B.XUSB_GAMEPAD_A if env.GAME == "dsr" else B.XUSB_GAMEPAD_Y, 0.1)

    def two_hand_toggle(self) -> None: self.tap(B.XUSB_GAMEPAD_Y, 0.1)
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
