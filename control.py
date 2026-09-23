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
import threading
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
        # 반사 스레드(reflex.py)와 판단 루프가 같이 누른다 — 보고서(report)를 동시에 고치지 않게 잠근다
        self._lock = threading.RLock()
        self.force_guard = False  # 반사 스레드가 켜면 판단 루프가 가드를 내려도 무시한다 (적 공격 중)
        self.pad = vg.VX360Gamepad()
        self.neutral()
        time.sleep(2.0)  # 게임이 새 XInput 장치를 인식할 시간 (바로 누르면 첫 입력이 씹힘)

    def reconnect(self) -> None:
        """가상 패드를 뺐다 다시 꽂는다. 실측: 이전 프로세스의 패드가 막 빠진 직후 새 패드를 만들면
        게임이 입력을 안 받는 때가 있다 (화면에 '컨트롤러 연결 해제' 알림 둘, 버튼 표시가 키보드 E 로 바뀜)."""
        with self._lock:
            self._due.clear()
            self.pad = None
        import gc
        gc.collect()
        time.sleep(1.5)
        with self._lock:
            self.pad = vg.VX360Gamepad()
            self.pad.reset()
            self.pad.update()
        time.sleep(2.5)

    def neutral(self) -> None:
        with self._lock:
            self.pad.reset()
            if self.force_guard:
                self.pad.press_button(B.XUSB_GAMEPAD_LEFT_SHOULDER)
            self.pad.update()

    def move(self, x: float, y: float) -> None:
        """왼스틱. x: 오른쪽 +, y: 앞 + (각 -1..1)"""
        m = math.hypot(x, y)
        if m > 1.0:
            x, y = x / m, y / m
        with self._lock:
            self.pad.left_joystick_float(x_value_float=x, y_value_float=y)
            self.pad.update()

    def look(self, x: float, y: float) -> None:
        """오른스틱 (카메라)."""
        with self._lock:
            self.pad.right_joystick_float(x_value_float=x, y_value_float=y)
            self.pad.update()

    def tap(self, button, hold: float = 0.08) -> None:
        """버튼을 누르고 **뗄 시각만 예약**한다 — 자지 않는다.

        예전엔 누른 뒤 time.sleep(hold) 했다. 그 동안 감지 루프가 통째로 멈춰서, 공격 한 번에 한 틱을
        버렸다 (틱 65 ms, 공격 hold 60 ms — 사용자 지적: "순차적으로 하는 것 같다"). 뗄 시각은
        release_due() 가 매 틱 처리한다."""
        with self._lock:
            self.pad.press_button(button)
            self.pad.update()
            self._due[button] = time.time() + hold

    def release_due(self) -> None:
        """예약된 버튼 떼기 — 감지 루프가 매 틱 부른다."""
        if not self._due:
            return
        with self._lock:
            now = time.time()
            done = [b for b, t in self._due.items() if now >= t]
            for b in done:
                self.pad.release_button(b)
                del self._due[b]
            if done:
                self.pad.update()

    def guard_held(self) -> bool:
        return bool(self.pad.report.wButtons & B.XUSB_GAMEPAD_LEFT_SHOULDER) if self.pad else False

    def hold(self, button, on: bool) -> None:
        with self._lock:
            if not on and button == B.XUSB_GAMEPAD_LEFT_SHOULDER and self.force_guard:
                return
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

    # ── 퀵슬롯 (실측) ───────────────────────────────
    # 길게 누르면 **무조건 1번 칸(에스트병)으로 돌아간다** — 사용자가 알려준 게임의 편의 기능.
    # 덕분에 "지금 몇 번 칸인지" 를 추적할 필요가 없다. 매번 초기화하고 필요한 만큼만 내린다.
    def item_reset(self) -> None: self.tap(B.XUSB_GAMEPAD_DPAD_DOWN, 0.9)
    def item_next(self) -> None: self.tap(B.XUSB_GAMEPAD_DPAD_DOWN, 0.08)

    # 실측된 슬롯 순서 (화면 확인, 2026-09-22): 초기화=에스트병+2, 1칸=파이어밤, 2칸=투척 나이프, 3칸=한 바퀴
    SLOT_ESTUS, SLOT_BOMB, SLOT_KNIFE = 0, 1, 2
    def attack(self) -> None: self.tap(B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06)

    def heavy(self, hold: float = 0.12, stick: tuple[float, float] | None = None) -> None:
        """R2 강공 — 오른쪽 트리거라 tap(버튼 예약)을 못 쓴다. hold 동안 눌렀다 뗀다 (그동안 잔다).
        stick 을 주면 같은 입력에 왼스틱도 — 공격 시작 순간의 스틱 방향으로 몸이 틀어진다 (락온 없이 겨누기, kick 과 같은 방식)."""
        with self._lock:
            if stick is not None:
                self.pad.left_joystick_float(x_value_float=stick[0], y_value_float=stick[1])
            self.pad.right_trigger_float(value_float=1.0)
            self.pad.update()
        time.sleep(hold)
        with self._lock:
            self.pad.right_trigger_float(value_float=0.0)
            if stick is not None:
                self.pad.left_joystick_float(x_value_float=0.0, y_value_float=0.0)
            self.pad.update()

    def kick(self, sx: float, sy: float) -> None:
        """발차기 = 캐릭터 정면으로 스틱을 끝까지 + RB 를 **같은 보고(report)에** 넣는다.
        (sx, sy) 는 world_to_stick 으로 바꾼 '캐릭터 정면' 방향. 한손 무기일 때만 나간다.

        실측(강화 곤봉 한손, 2026-09-22): RB 만 → 애니 333000(→333040), 스틱 앞+RB → 333100 (화면에서 다리를 뻗고
        팔을 벌린 자세 확인). 같은 프레임·스틱 30 ms 먼저·중립에서 튕기기 세 방식 모두 333100.
        쓰임새(사용자): 방패 든 적의 가드를 깨서 틈을 만들거나, 그 틈에 빠져나갈 때."""
        with self._lock:
            self.pad.left_joystick_float(x_value_float=sx, y_value_float=sy)
            self.pad.press_button(B.XUSB_GAMEPAD_RIGHT_SHOULDER)
            self.pad.update()
            self._due[B.XUSB_GAMEPAD_RIGHT_SHOULDER] = time.time() + 0.06
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
