"""게임 화면을 캡처한다 — 봇이 왜 막혔는지 메모리로는 알 수 없을 때 눈으로 본다.

  python shot.py [파일명]     게임 창을 앞으로 가져와 캡처 (기본: 스크래치 폴더)

좌표·높이 같은 숫자는 메모리가 정확하니 그쪽을 쓴다. 이건 "앞에 뭐가 있나" 같은 질적 판단 전용.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys
import time
from pathlib import Path

import control
from PIL import ImageGrab


def shot(path: str | Path) -> str:
    control.focus_game()
    time.sleep(0.4)
    u = ctypes.windll.user32
    import env
    h = u.FindWindowW(None, "DARK SOULS™: REMASTERED" if env.GAME == "dsr" else "ELDEN RING™")
    if not h:
        raise SystemExit("게임 창을 못 찾음")
    r = ctypes.wintypes.RECT()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(h, 9, ctypes.byref(r), ctypes.sizeof(r))  # 9 = EXTENDED_FRAME_BOUNDS
    box = (r.left, r.top, r.right, r.bottom)
    if r.right <= r.left:
        u.GetWindowRect(h, ctypes.byref(r))
        box = (r.left, r.top, r.right, r.bottom)
    img = ImageGrab.grab(bbox=box, all_screens=True)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return f"{path}  {img.size[0]}x{img.size[1]}"


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "shot.png"
    print(shot(out))
