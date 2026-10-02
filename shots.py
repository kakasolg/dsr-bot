"""Periodic screenshots of the game window, for the labeling pilot's hints (LAYA.md 13). Read-only: never focuses, moves
or types into anything — run it as its own process next to the bot (unlike shot.py, which brings the game to the front).

  python shots.py                     2 per second → data/shots/<YYYYmmdd_HHMMSS>/<epoch ms>.jpg  (Ctrl+C to stop)
  python shots.py --hz 1 --width 640  fewer / smaller
  python shots.py --title "..." --for 5   another window, a few seconds (to try it without the game)

File names are wall-clock epoch milliseconds — the radar recording's snapshots carry the same clock in "t", so a scene
finds its shots by time. Captures the screen region of the window as shown (an overlay on top is captured too).
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GAME_TITLE = "DARK SOULS™: REMASTERED"


def window_box(title: str):
    u = ctypes.windll.user32
    h = u.FindWindowW(None, title)
    if not h or u.IsIconic(h):
        return None
    r = ctypes.wintypes.RECT()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(h, 9, ctypes.byref(r), ctypes.sizeof(r))   # 9 = EXTENDED_FRAME_BOUNDS
    if r.right <= r.left:
        u.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom) if r.right > r.left else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hz", type=float, default=2.0)
    ap.add_argument("--width", type=int, default=960, help="resize to this width (keeps aspect)")
    ap.add_argument("--quality", type=int, default=70)
    ap.add_argument("--title", default=GAME_TITLE)
    ap.add_argument("--out", default=None)
    ap.add_argument("--for", dest="duration", type=float, default=None, help="stop after this many seconds")
    a = ap.parse_args()
    if sys.platform != "win32":
        sys.exit("Windows only")
    from PIL import ImageGrab
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)   # BELOW_NORMAL
    out = Path(a.out) if a.out else ROOT / "data" / "shots" / time.strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    print(f"shots: {a.title!r} at {a.hz} Hz → {out}")
    t0, n, missed, cost = time.time(), 0, 0, []
    period = 1.0 / a.hz
    nxt = time.time()
    try:
        while a.duration is None or time.time() - t0 < a.duration:
            nxt += period
            box = window_box(a.title)
            if box is None:
                missed += 1
            else:
                c0 = time.perf_counter()
                t = time.time()
                img = ImageGrab.grab(bbox=box, all_screens=True)
                if a.width and img.width > a.width:
                    img = img.resize((a.width, round(img.height * a.width / img.width)))
                img.convert("RGB").save(out / f"{int(t * 1000)}.jpg", quality=a.quality)
                cost.append((time.perf_counter() - c0) * 1000)
                n += 1
            time.sleep(max(0.0, nxt - time.time()))
    except KeyboardInterrupt:
        pass
    cost.sort()
    p = (lambda q: cost[min(len(cost) - 1, int(q * len(cost)))]) if cost else (lambda q: 0)
    print(f"shots: {n} saved, {missed} without the window, capture p50 {p(.5):.0f} ms · p95 {p(.95):.0f} ms → {out}")


if __name__ == "__main__":
    main()
