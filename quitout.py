"""퀵 종료(quit-out) — 메뉴로 게임을 저장·종료하고 타이틀에서 바로 이어하기.

  python quitout.py drill [횟수] [커서 간격 s] [화면 전환 후 대기 s]     종료→재접속을 반복하며 시간·성공률을 잰다

왜: 사용자 — 고수들은 적이 경계 상태가 되면 0.3 s 안에 메뉴에 들어가 게임을 나갔다 온다. 그러면 몹 위치·경계가
초기화된다 (죽은 몹은 휴식 전까지 그대로). 봇에겐 두 가지 쓸모: 판 사이 초기화, 그리고 **최후의 탈출**
(구석에 몰림·낙하 중). 개발사가 일부러 나가기 어렵게 만들어 놨다 (7번 입력, 확인창 기본값 취소).

실측 순서 (2026-09-22 화면 확인):
  START → (메뉴: 아이템 칸) LEFT → (시스템) A → (Options 칸) UP → (Quit Game, 맨 아래로 순환) A
  → 확인창 기본값 CANCEL → LEFT → A → 타이틀 ("Updating save data...")
  → "Game will start in offline mode." OK(A) → 타이틀 메뉴 기본값 Continue → A → 로드
눈 감고 누르지 않는다 — 끝났는지는 메모리로 본다: 종료되면 플레이어 포인터가 사라지고, 로드되면 돌아온다.
"""
from __future__ import annotations

import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env
import vgamepad as vg

B = vg.XUSB_BUTTON
QUIT_SEQ = [B.XUSB_GAMEPAD_START, B.XUSB_GAMEPAD_DPAD_LEFT, B.XUSB_GAMEPAD_A, B.XUSB_GAMEPAD_DPAD_UP,
            B.XUSB_GAMEPAD_A, B.XUSB_GAMEPAD_DPAD_LEFT, B.XUSB_GAMEPAD_A]
HOLD = 0.05
# 메뉴 입력 사이 최소 간격 — 사용자: "메뉴 버튼 작업 때 한 번에 연속으로 하면 입력 버퍼가 꼬인다. 0.1 초씩 간격 줘봐".
# gap 0.0 으로 부르던 곳(다크사인 X → 확인창 → A, 종료 메뉴 이동)은 뗀 뒤 곧바로 다음 버튼이 들어갔다
MENU_GAP = 0.1


def _in_world(tm) -> bool:
    try:
        s = tm.snapshot(within=1.0)
        return bool(s and s.player and s.player.hp and s.player.hp > 0)
    except Exception:
        return False


def _press(pad, b, gap: float) -> None:
    with pad._lock:
        pad.pad.press_button(b)
        pad.pad.update()
    time.sleep(HOLD)
    with pad._lock:
        pad.pad.release_button(b)
        pad.pad.update()
    time.sleep(max(MENU_GAP, gap - HOLD))


OFF_SCREEN = 0x1C69698   # 모듈 기준 u32 — 지금 떠 있는 메뉴 화면마다 다른 값 (닫힘/아이템/시스템/확인창). 커서 이동엔 안 바뀐다


def _screen(tm) -> int | None:
    try:
        return tm.pm.read_uint(tm.base + OFF_SCREEN)
    except Exception:
        return None


def _wait(cond, timeout: float) -> bool:
    t = time.time()
    while time.time() - t < timeout:
        if cond():
            return True
        time.sleep(0.005)
    return False


UI_DIR = __import__("pathlib").Path(__file__).resolve().parent / "data" / "ui"
# 창 기준 비율 좌표 (1922x1112 창에서 잡은 영역) — 화면 '정체'는 글자로만 확실히 안다.
# 화면 ID 값(OFF_SCREEN)은 메뉴 깊이에 따라 줄어드는 할당 주소라 세션마다 바뀐다 (0x240270 → 0x241470 실측)
UI_BOX = {
    "systab": (0.663, 0.180, 0.877, 0.212),
    "itemtab": (0.663, 0.180, 0.877, 0.212),       # 같은 자리, 아이템 탭일 때 ("Browse and use items") — LEFT 가 씹혔는지 판별        # 메뉴 탭 설명 "Configure options or quit the game" (아이템 탭이면 "Browse and use items")
    "quitsel": (0.142, 0.153, 0.409, 0.178),       # 시스템 창 설명 "Save the game and return to Title Menu" (커서가 Quit Game 일 때)
    "ok_sel": (0.30, 0.600, 0.49, 0.645),          # 확인창 OK 에 불이 들어왔나 (기본값은 CANCEL)
    "system": (0.075, 0.095, 0.215, 0.155),        # 좌상단 "System" 제목
    "confirm_quit": (0.34, 0.43, 0.66, 0.53),      # "Are you sure you want to save the game and return to Title Menu?"
    "darksign_q": (0.25, 0.815, 0.76, 0.855),      # "Lose all humanity and souls, and return to the last bonfire rested at?"
    "darksign_yes": (0.27, 0.855, 0.49, 0.900),    # YES 칸 (다크사인은 기본값이 YES — 종료 확인창과 반대)
}
UI_MATCH = 0.35      # 글자 픽셀 어긋남 비율이 이보다 크면 다른 화면
TEXT_LEVEL = 150     # 이보다 밝은 픽셀만 글자로 본다 — 반투명 창 뒤 배경, LB/RB↔HOME/END 아이콘 전환에 안 흔들리게
# (실측: 밝기 그대로 비교하면 같은 탭인데도 카메라가 바뀌면 20 차이가 나서 문턱 18 을 넘었다)
LAST_DIFF: dict[str, float] = {}


def _grab(box):
    import ctypes, ctypes.wintypes
    import numpy as np
    from PIL import ImageGrab
    u = ctypes.windll.user32
    h = u.FindWindowW(None, "DARK SOULS™: REMASTERED")
    r = ctypes.wintypes.RECT()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(h, 9, ctypes.byref(r), ctypes.sizeof(r))
    w, hh = r.right - r.left, r.bottom - r.top
    bb = (r.left + int(box[0] * w), r.top + int(box[1] * hh), r.left + int(box[2] * w), r.top + int(box[3] * hh))
    # 주 모니터 안이면 all_screens=False — 33 ms (all_screens 는 138 ms, 실측)
    prim = r.left >= 0 and r.top >= 0 and r.right <= u.GetSystemMetrics(0) and r.bottom <= u.GetSystemMetrics(1)
    g = np.asarray(ImageGrab.grab(bbox=bb, all_screens=not prim).convert("L").resize((240, 40)))
    return g > TEXT_LEVEL


def _is_screen(name: str) -> bool | None:
    """참조 이미지와 비교. 참조가 없으면 None (calibrate 를 먼저)."""
    import numpy as np
    f = UI_DIR / f"{name}.npy"
    if not f.exists():
        return None
    ref, cur = np.load(f), _grab(UI_BOX[name])
    # 글자 픽셀끼리의 어긋남 비율 (0 = 같다, 1 = 전혀 다르다). 예전엔 전체 픽셀 중 다른 비율이었는데,
    # 글자가 성긴 창(다크사인 확인창 글자 6 %)은 **빈 화면도 0.059 로 '같다'** 가 나왔다.
    d = float((ref != cur).sum()) / max(1.0, float(ref.sum() + cur.sum()))
    LAST_DIFF[name] = round(d, 3)
    return d < UI_MATCH


def _fail_shot(tag: str) -> None:
    try:
        import shot
        shot.shot(UI_DIR / f"fail_{tag}_{time.strftime('%H%M%S')}.png")
    except Exception:
        pass


def calibrate(tm, pad) -> None:
    """메뉴를 한 번 들어가서 참조 이미지를 찍고 **확정하지 않고** 빠져나온다."""
    import numpy as np
    UI_DIR.mkdir(parents=True, exist_ok=True)
    _press(pad, B.XUSB_GAMEPAD_START, 0.8)
    np.save(UI_DIR / "itemtab.npy", _grab(UI_BOX["itemtab"]))
    _press(pad, B.XUSB_GAMEPAD_DPAD_LEFT, 0.8)
    np.save(UI_DIR / "systab.npy", _grab(UI_BOX["systab"]))
    _press(pad, B.XUSB_GAMEPAD_A, 0.7)
    np.save(UI_DIR / "system.npy", _grab(UI_BOX["system"]))
    _press(pad, B.XUSB_GAMEPAD_DPAD_UP, 0.5)
    np.save(UI_DIR / "quitsel.npy", _grab(UI_BOX["quitsel"]))
    _press(pad, B.XUSB_GAMEPAD_A, 0.7)
    np.save(UI_DIR / "confirm_quit.npy", _grab(UI_BOX["confirm_quit"]))
    _press(pad, B.XUSB_GAMEPAD_DPAD_LEFT, 0.5)
    np.save(UI_DIR / "ok_sel.npy", _grab(UI_BOX["ok_sel"]))
    close_menu(tm, pad)            # B 로만 빠진다 — A 는 절대 누르지 않는다


def quit_out(tm, pad, gap: float = 0.08, settle: float = 0.1, timeout: float = 8.0, ready_wait: float = 0.3) -> float | None:
    """→ 첫 입력부터 월드에서 사라질 때까지 걸린 시간(s). 실패면 None.

    화면이 바뀌는 입력(START·A·A) 뒤에는 **메모리로 화면 전환을 확인**하고 settle 만큼 쉰 뒤 다음을 누른다.
    전환 애니메이션 중에 누르면 씹힌다 (실측: 간격 0.12 s 로 일괄 입력하면 3/10 성공).
    같은 화면 안의 커서 이동(LEFT·UP·LEFT)은 gap 간격."""
    pad.neutral()
    # 0) 먼저 "조작 가능" 상태(플래그 1)가 0.3 s 이어지는지 본다. 로드 직후 페이드인 동안엔 메뉴가 없는데도 플래그가 0 이라,
    #    START 가 씹혔는데 "열렸다"고 착각하고 나머지를 눌렀다 (실측: 실패 스크린샷에 메뉴가 없음).
    t_ready = time.time()
    stable_from = None
    while time.time() - t_ready < 5.0:
        if tm.menu_open() is False:
            stable_from = stable_from or time.time()
            if time.time() - stable_from >= ready_wait:   # 긴급(낙하 중)엔 짧게 — 월드 안인 게 확실하다
                break
        else:
            stable_from = None
        time.sleep(0.01)
    else:
        return None
    t0 = time.time()
    for _ in range(5):                                       # 1) START → 플래그가 1→0 으로 **바뀌는 것**을 확인
        _press(pad, B.XUSB_GAMEPAD_START, 0.0)
        if _wait(tm.menu_open, 0.25):
            break
    else:
        return None
    # 커서 이동 → 그 칸에 불이 들어왔는지(설명 글자) 확인, 안 됐으면 한 번 더 → A → 다음 화면이 맞는지 확인
    for move, sel, expect in ((B.XUSB_GAMEPAD_DPAD_LEFT, "systab", "system"),
                              (B.XUSB_GAMEPAD_DPAD_UP, "quitsel", "confirm_quit")):
        time.sleep(settle)
        # 한 번 누르고 설명 글자가 다 나타날 때까지 기다린다 (글자가 서서히 나타나서 0.35 s 로는 부족 — 다시 눌렀다가
        # 한 칸 더 넘어간 적 있음). 재시도는 **아직 원래 칸일 때만** (아이템 탭 설명이 그대로면 입력이 씹힌 것)
        for _ in range(2):
            _press(pad, move, 0.0)
            if _wait(lambda: _is_screen(sel) is not False, 0.8):
                break
            if sel != "systab" or _is_screen("itemtab") is not True:
                _fail_shot(sel)
                return None
        else:
            _fail_shot(sel)
            return None
        before = _screen(tm)
        _press(pad, B.XUSB_GAMEPAD_A, 0.0)
        if not _wait(lambda: _screen(tm) != before, 0.6):
            return None
        # **그 화면이 맞는지 글자로 확인** — 아니면 멈춘다. 실측: LEFT 가 씹혀 A 가 아이템 창을 열었고,
        # 이어진 입력이 다크사인 확인창("영혼과 인간성을 모두 잃고 화톳불로...")까지 갔다.
        if not _wait(lambda: _is_screen(expect) is not False, 0.5):
            return None
    time.sleep(settle)
    for _ in range(3):                                       # 확인창: 기본값 CANCEL → OK 로 옮겨졌나
        _press(pad, B.XUSB_GAMEPAD_DPAD_LEFT, 0.0)
        if _wait(lambda: _is_screen("ok_sel") is not False, 0.35):
            break
    else:
        return None
    _press(pad, B.XUSB_GAMEPAD_A, 0.0)
    while time.time() - t0 < timeout:
        if not _in_world(tm):
            return time.time() - t0
        time.sleep(0.02)
    return None


def close_menu(tm, pad) -> None:
    for _ in range(6):
        if not tm.menu_open():
            return
        _press(pad, B.XUSB_GAMEPAD_B, 0.25)


def reload(pad, timeout: float = 40.0) -> float | None:
    """타이틀에서 이어하기. 로드될 때까지 1.2 s 마다 A (오프라인 안내 OK → Continue). → 걸린 시간 또는 None."""
    t0 = time.time()
    last_a = 0.0
    while time.time() - t0 < timeout:
        try:
            tm = env.make_telemetry({})       # 타이틀을 거치면 포인터가 새로 잡힌다
            if _in_world(tm):
                return time.time() - t0
        except Exception:
            pass
        if time.time() - last_a > 1.2:
            _press(pad, B.XUSB_GAMEPAD_A, 0.1)
            last_a = time.time()
        time.sleep(0.2)
    return None


def drill(n: int = 5, gap: float = 0.08, settle: float = 0.1) -> None:
    import statistics
    control.focus_game()
    pad = control.Pad()
    tm = env.make_telemetry({})
    if not _in_world(tm):
        print("월드에 없음 — 게임 안에서 시작하세요"); return
    q_times, r_times, ok = [], [], 0
    for i in range(n):
        control.focus_game()
        tm = env.make_telemetry({})
        p0 = tm.snapshot(within=1.0).player
        q = quit_out(tm, pad, gap, settle)
        if q is None:
            print(f"  {i+1}: 종료 실패 — 메뉴 닫고 다음  화면 대조 {LAST_DIFF}")
            close_menu(tm, pad)
            time.sleep(1.0)
            continue
        r = reload(pad)
        if r is None:
            print(f"  {i+1}: 종료 {q:.2f}s, 재접속 실패"); break
        tm = env.make_telemetry({})
        p1 = tm.snapshot(within=1.0).player
        moved = ((p1.x - p0.x) ** 2 + (p1.z - p0.z) ** 2) ** 0.5
        ok += 1
        q_times.append(q); r_times.append(r)
        print(f"  {i+1}: 종료 {q:.2f}s  재접속 {r:.1f}s  위치 차 {moved:.2f} m  hp {p1.hp}  화면 대조 {LAST_DIFF}", flush=True)
        time.sleep(1.0)
    print(f"\n성공 {ok}/{n}  입력 간격 {gap}s")
    if q_times:
        print(f"종료: 중앙 {statistics.median(q_times):.2f}s (최소 {min(q_times):.2f})  재접속: 중앙 {statistics.median(r_times):.1f}s")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "calibrate":
        control.focus_game()
        calibrate(env.make_telemetry({}), control.Pad())
        print("참조 저장:", sorted(p.name for p in UI_DIR.glob("*.npy")))
    elif len(sys.argv) >= 2 and sys.argv[1] == "drill":
        drill(int(sys.argv[2]) if len(sys.argv) > 2 else 5, float(sys.argv[3]) if len(sys.argv) > 3 else 0.08,
              float(sys.argv[4]) if len(sys.argv) > 4 else 0.1)
    else:
        print(__doc__)
