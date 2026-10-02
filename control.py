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
import weakref
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import ctypes
import ctypes.wintypes

# vgamepad (ViGEmBus) is Windows-only. Offline tests only need the button constants,
# so fall back to a stand-in; creating a real pad still requires vgamepad.
try:
    import vgamepad as vg
    B = vg.XUSB_BUTTON
except ImportError:
    vg = None

    class _Buttons:
        def __getattr__(self, name):
            return name

    B = _Buttons()


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


class _NullPad:
    """얼린 동안 다른 스레드가 보는 패드 — 무엇을 눌러도 게임에 안 간다."""
    class _Report:
        wButtons = 0
    report = _Report()

    def __getattr__(self, name):
        return lambda *a, **k: None


_NULL_PAD = _NullPad()

# machine-wide: one virtual pad at a time. Two pads (watchdog's rescue pad next to a live bot's) mix inputs in the game.
# Every script gets it through Pad(); the OS drops it when the holder dies (botlock.BotLock, its own file)
PAD_LOCK_PATH = Path(__file__).resolve().parent / "data" / "pad.lock"


class PadBusy(RuntimeError):
    """Another Pad holds the pad lock (or this one is closed) — no virtual pad is created (fail closed)."""


def pad_lock_held() -> bool:
    """Does some Pad hold the pad lock right now? Probe only: takes and drops it at once, creates no device."""
    from botlock import BotLock
    probe = BotLock(PAD_LOCK_PATH)
    if not probe.acquire():
        return True
    probe.release()
    return False


# ── process exit (P0-E) ─────────────────────────────
# Every exit that still runs code: neutral → unplug. atexit = normal end and uncaught exceptions; the console handler =
# Ctrl+Break, closing the console window, logoff/shutdown (the default handler then ends the process without atexit).
# Ctrl+C there only neutralizes — Python then raises KeyboardInterrupt and run.py's user stop takes over.
# TerminateProcess / a hard kill runs nothing here: what ViGEm does with the device then is UNKNOWN (not tested in game).
_LIVE: "weakref.WeakSet[Pad]" = weakref.WeakSet()
_HOOKED = False
_CTRL_HANDLER = None          # the ctypes callback must stay referenced while registered
CTRL_C_EVENT = 0


def _release_all(close: bool) -> None:
    for p in list(_LIVE):
        try:
            p.close() if close else p.release_all()
        except Exception:
            pass


def _on_console_event(ev: int) -> bool:
    _release_all(close=ev != CTRL_C_EVENT)
    return False              # not handled — the next handler (Python's Ctrl+C / the default exit) still runs


def _hook_exit() -> None:
    global _HOOKED, _CTRL_HANDLER
    if _HOOKED:
        return
    _HOOKED = True
    import atexit
    atexit.register(_release_all, True)
    if sys.platform == "win32":
        handler_type = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.DWORD)
        _CTRL_HANDLER = handler_type(lambda ev: _on_console_event(int(ev)))
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_CTRL_HANDLER, True)


class Pad:
    # 긴급 탈출(메뉴 → Quit Game) 동안 판단 루프가 스틱·버튼을 계속 넣으면 메뉴 입력과 섞인다 → 탈출 스레드만 패드를 쓴다
    _frozen_by: int | None = None
    _vpad = None

    CONNECT_WAIT_S = 2.0      # game picks up a new XInput device (pressing at once lost the first input)
    RECONNECT_GAP_S = 1.5     # reconnect(): unplugged → plugged (measured, see reconnect)
    RECONNECT_WAIT_S = 2.5

    @property
    def pad(self):
        if self._frozen_by is not None and threading.get_ident() != self._frozen_by:
            return _NULL_PAD
        # no device (mid-reconnect, or closed): drop the input instead of AttributeError — an exception here would reach
        # run.py's error path, which quits out
        return self._vpad if self._vpad is not None else _NULL_PAD

    @pad.setter
    def pad(self, v) -> None:
        self._vpad = v

    def freeze(self, take: bool = True) -> bool:
        """이 스레드만 패드를 쓴다 — 다른 스레드의 입력은 버려진다. 눌려 있던 것은 전부 뗀다.
        take=False: another thread already holds the freeze → leave it alone and return False (Escape._ledge yields to
        a running quit-out; the quit-out itself takes it, take=True)."""
        with self._lock:
            me = threading.get_ident()
            if not take and self._frozen_by not in (None, me):
                return False
            self._frozen_by = me
            self.epoch += 1
            self._due.clear()
            if self._vpad is not None:
                self._vpad.reset()
                self._vpad.update()
        return True

    def unfreeze(self) -> None:
        """Only the thread holding the freeze lifts it — a nudge that was overtaken by a quit-out must not unfreeze it."""
        with self._lock:
            if self._frozen_by != threading.get_ident():
                return
            self._frozen_by = None
            self.epoch += 1               # what others 'pressed' while frozen went to _NullPad — make them press it again

    # 스틱을 놓은 걸 게임이 알아채는 데 60fps ~0.16 s (30fps 0.33 s, 사용자 실측). 그 전에 R1 이면 발차기, R2 면 점프 공격
    # (조작표: 앞 + R1 = 발차기, 앞 + R2 = 점프 공격). 공격 버튼은 이 층에서 늘 스틱을 놓고 기다린 뒤 누른다 —
    # 부르는 쪽이 15군데라 거기서 지키게 했더니 빠진 곳에서 발차기·점프 공격이 나갔다 (2026-09-24)
    STICK_RELEASE_S = 0.16

    def __init__(self):
        self._due: dict = {}      # 버튼 → 뗄 시각 (tap 이 자지 않도록)
        # +1 whenever the report is wiped behind the callers' backs (neutral·freeze·unfreeze·reconnect·close) — nav.Mover sees
        # it change and forgets what it thinks it holds, so the next set() presses it again (P0-D)
        self.epoch = 0
        self._stick_on = False    # 왼스틱이 지금 중립이 아닌가
        self._stick_off_t = 0.0   # 왼스틱을 마지막으로 놓은 시각
        # 반사 스레드(reflex.py)와 판단 루프가 같이 누른다 — 보고서(report)를 동시에 고치지 않게 잠근다
        self._lock = threading.RLock()
        self.force_guard = False  # 반사 스레드가 켜면 판단 루프가 가드를 내려도 무시한다 (적 공격 중)
        self._closed = False
        self._pad_lock = None
        if vg is None:
            raise RuntimeError("vgamepad is not installed (Windows only) — cannot create the virtual pad")
        from botlock import BotLock
        lock = BotLock(PAD_LOCK_PATH)
        if not lock.acquire():                 # before the device exists — a refused Pad never plugs anything in
            raise PadBusy(f"pad lock held by another process or Pad ({PAD_LOCK_PATH}) — not creating a second virtual pad")
        self._pad_lock = lock
        try:
            self.pad = vg.VX360Gamepad()
            self.neutral()
        except BaseException:
            self.close()
            raise
        _LIVE.add(self)
        _hook_exit()
        time.sleep(self.CONNECT_WAIT_S)

    def release_all(self) -> None:
        """Exit paths only: every input off now, even while another thread holds the freeze — it is a user / OS stop."""
        got = self._lock.acquire(timeout=1.0)
        try:
            self.epoch += 1
            self._due.clear()
            self._note_stick(0.0, 0.0)
            v = self._vpad
            if v is not None:
                v.reset()
                v.update()
        finally:
            if got:
                self._lock.release()

    def close(self) -> None:
        """Neutral → unplug the device → drop the pad lock. Idempotent; later input goes nowhere (_NullPad)."""
        got = self._lock.acquire(timeout=1.0)   # an exit path must not hang on a stuck holder
        try:
            if self._closed:
                return
            self._closed = True
            self.epoch += 1
            v, self._vpad = self._vpad, None
            self._due.clear()
            if v is not None:
                try:
                    v.reset()
                    v.update()
                except Exception:
                    pass
            del v                                # last reference → vgamepad __del__ → vigem_target_remove
        finally:
            if got:
                self._lock.release()
        import gc
        gc.collect()                             # also when something holds it in a cycle (reconnect does the same)
        if self._pad_lock is not None:
            self._pad_lock.release()
            self._pad_lock = None

    def reconnect(self) -> None:
        """가상 패드를 뺐다 다시 꽂는다. 실측: 이전 프로세스의 패드가 막 빠진 직후 새 패드를 만들면
        게임이 입력을 안 받는 때가 있다 (화면에 '컨트롤러 연결 해제' 알림 둘, 버튼 표시가 키보드 E 로 바뀜).
        The pad lock stays held across the gap — nobody else can plug a pad in meanwhile."""
        if self._closed or self._pad_lock is None:
            raise PadBusy("reconnect on a closed Pad — it no longer holds the pad lock")
        with self._lock:
            self._due.clear()
            self.epoch += 1
            self.pad = None
        import gc
        gc.collect()
        time.sleep(self.RECONNECT_GAP_S)
        with self._lock:
            self.pad = vg.VX360Gamepad()
            self._vpad.reset()
            self._vpad.update()
        time.sleep(self.RECONNECT_WAIT_S)

    def _note_stick(self, x: float, y: float) -> None:
        on = abs(x) > 1e-3 or abs(y) > 1e-3
        if self._stick_on and not on:
            self._stick_off_t = time.time()
        self._stick_on = on

    def release_stick(self) -> None:
        """공격 버튼 전에: 스틱을 놓고 게임이 알아챌 때까지(STICK_RELEASE_S) 기다린다. 이미 놓은 지 오래면 바로 돌아온다."""
        if self._stick_on:
            self.move(0.0, 0.0)
        left = self.STICK_RELEASE_S - (time.time() - self._stick_off_t)
        if left > 0:
            time.sleep(left)

    def neutral(self) -> None:
        with self._lock:
            self.epoch += 1
            self._note_stick(0.0, 0.0)
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
            self._note_stick(x, y)
            self.pad.left_joystick_float(x_value_float=x, y_value_float=y)
            self.pad.update()

    def look(self, x: float, y: float) -> None:
        """오른스틱 (카메라)."""
        with self._lock:
            self.pad.right_joystick_float(x_value_float=x, y_value_float=y)
            self.pad.update()

    def tap(self, button, hold: float = 0.08, stick_ok: bool = False) -> None:
        """버튼을 누르고 **뗄 시각만 예약**한다 — 자지 않는다.

        예전엔 누른 뒤 time.sleep(hold) 했다. 그 동안 감지 루프가 통째로 멈춰서, 공격 한 번에 한 틱을
        버렸다 (틱 65 ms, 공격 hold 60 ms — 사용자 지적: "순차적으로 하는 것 같다"). 뗄 시각은
        release_due() 가 매 틱 처리한다.
        R1 은 스틱을 놓고 누른다 (release_stick). stick_ok=True 는 스틱과 같이 누르는 게 목적일 때만 (낙하 공격 등)."""
        if button == B.XUSB_GAMEPAD_RIGHT_SHOULDER and not stick_ok:
            self.release_stick()
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
        stick 을 주면 그쪽으로 **먼저 몸을 돌리고 스틱을 놓은 뒤** R2 — 예전엔 같은 입력에 넣었는데, 앞 + R2 는
        점프 공격이다 (조작표; 사용자: "브로드소드 점프 공격 모션이 안 좋아"). 점프 공격이 목적이면 jump_attack."""
        if stick is not None:
            self.move(stick[0] * 0.4, stick[1] * 0.4)
            time.sleep(0.08)
        self.release_stick()
        self._r2(hold)

    def jump_attack(self, stick: tuple[float, float], hold: float = 0.12) -> None:
        """앞 + R2 = 점프 공격 (뛰어들며 내려친다). 일부러 쓸 때만."""
        with self._lock:
            self._note_stick(*stick)
            self.pad.left_joystick_float(x_value_float=stick[0], y_value_float=stick[1])
            self.pad.update()
        self._r2(hold)
        self.move(0.0, 0.0)

    def _r2(self, hold: float) -> None:
        with self._lock:
            self.pad.right_trigger_float(value_float=1.0)
            self.pad.update()
        time.sleep(hold)
        with self._lock:
            self.pad.right_trigger_float(value_float=0.0)
            self.pad.update()

    def kick(self, sx: float, sy: float) -> None:
        """발차기 = 캐릭터 정면으로 스틱을 끝까지 + RB 를 **같은 보고(report)에** 넣는다.
        (sx, sy) 는 world_to_stick 으로 바꾼 '캐릭터 정면' 방향. 한손 무기일 때만 나간다.

        실측(강화 곤봉 한손, 2026-09-22): RB 만 → 애니 333000(→333040), 스틱 앞+RB → 333100 (화면에서 다리를 뻗고
        팔을 벌린 자세 확인). 같은 프레임·스틱 30 ms 먼저·중립에서 튕기기 세 방식 모두 333100.
        쓰임새(사용자): 방패 든 적의 가드를 깨서 틈을 만들거나, 그 틈에 빠져나갈 때."""
        with self._lock:
            self._note_stick(sx, sy)
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


# ── 임시값 (P0-C, 근거 등급: 임시 제안값) ─────────────────────────────
#  관측이 끊긴 동안 입력을 남기지 않는 안전 경로에서만 쓴다 — 전술 상수(nav·duel·reflex)가 아니다.
#  0.25 s 는 feed.WAIT 를 빌린 값이고 실측 근거는 없다. 실제 게임 검증 전에는 정책 상수로 올리지 않는다
NO_OBS_NEUTRAL_S = 0.25


class NoObs:
    """No snapshot this tick → stick to 0 at once; still none after NO_OBS_NEUTRAL_S → everything released (once per gap).
    seen() when a snapshot comes back. on_full: what 'everything released' is (default pad.neutral; Field passes mover.stop)."""

    def __init__(self, pad, on_full=None):
        self.pad, self.on_full = pad, on_full
        self.since: float | None = None
        self.full = False

    def missing(self) -> None:
        now = time.time()
        if self.since is None:
            self.since, self.full = now, False
        self.pad.move(0.0, 0.0)
        if not self.full and now - self.since >= NO_OBS_NEUTRAL_S:
            self.full = True
            full = self.on_full or getattr(self.pad, "neutral", None)
            if full is not None:
                full()

    def seen(self) -> None:
        self.since = None


def world_to_stick(dx: float, dz: float, cam_yaw: float, yaw_offset: float, flip_x: bool) -> tuple[float, float]:
    """월드 평면 방향(dx, dz) 을 카메라 yaw 기준 스틱(x, y) 로. 부호/오프셋은 calibrate 결과."""
    ang = math.atan2(dx, dz)            # 월드 방향각
    rel = ang - (cam_yaw + yaw_offset)   # 카메라 기준 상대각
    sx, sy = math.sin(rel), math.cos(rel)
    return (-sx if flip_x else sx), sy
