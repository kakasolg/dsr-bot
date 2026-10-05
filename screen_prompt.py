"""화면 아래 가운데 안내창('A: …')이 떴나 — 안개벽·문·아이템 앞에서 A를 누를지 정할 때 쓴다.

legacy/ladder_test.py에서 옮겨 왔다: 봇(souls/field.py)이 legacy·experiments에 기대지 않게 하고, 게임 없는 곳
(Linux CI)에서도 import는 되게 하려고 (vgamepad·창 API는 부를 때만 쓴다).
"""
from __future__ import annotations

PROMPT_ON = 820


def window_rect() -> tuple[int, int, int, int] | None:
    """게임 창의 클라이언트 영역 (화면 좌표)."""
    import ctypes
    import ctypes.wintypes
    u = ctypes.windll.user32
    h = u.FindWindowW(None, "DARK SOULS™: REMASTERED")
    if not h:
        return None
    r = ctypes.wintypes.RECT()
    u.GetClientRect(h, ctypes.byref(r))
    pt = ctypes.wintypes.POINT(0, 0)
    u.ClientToScreen(h, ctypes.byref(pt))
    return pt.x, pt.y, pt.x + r.right, pt.y + r.bottom


def prompt_px() -> int:
    """안내창은 거의 검은 틀이라 어두운 픽셀 비율로 본다 (×1000).
    실측: 안내 있음 900~920, 없음 590~710 (밝은 글자 수로 재면 배경 빛에 흔들려 못 썼다)."""
    import numpy as np
    from PIL import ImageGrab
    x0, y0, x1, y1 = window_rect()
    w, h = x1 - x0, y1 - y0
    im = ImageGrab.grab(bbox=(x0 + int(0.30 * w), y0 + int(0.80 * h), x0 + int(0.70 * w), y0 + int(0.86 * h))).convert("L")
    a = np.asarray(im)
    dark = int(1000 * float((a < 40).mean()))
    # 어두운 방(수용소 오스카 방)에선 안내가 없어도 어두움 902 — 안내창엔 흰 글자가 있다 (밝은 글자 픽셀이 있어야 인정)
    return dark if int((a > 200).sum()) >= 60 else min(dark, 700)
