"""In-game overlay — a transparent, click-through window over the game showing what the bot sees and decides.

  python radar_server.py                   (1) collects the bot's state (same as the radar page)
  python overlay.py                        (2) draws it over the game window
  python run.py burg-bonfire --radar       (3) the bot sends
  python overlay.py --demo                 fake world, no game or bot (starts its own demo server)

The game must run in **windowed or borderless windowed** mode — an exclusive-fullscreen game hides other windows.

Never takes focus (control.game_in_front() only sends pad input while the game is the foreground window, so an overlay
that grabbed focus would stop the bot): the window is WS_EX_NOACTIVATE | WS_EX_TRANSPARENT (clicks go through) |
WS_EX_LAYERED | WS_EX_TOOLWINDOW (no taskbar entry), always on top, and never calls focus. Reads /state from
radar_server.py over localhost; if the server is gone it just shows "no radar server". Standard library only (tkinter).
On other OSes it opens as a normal window (development).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HOSTILE = {6, 7, 24, 25, 27}
KEY = "#010203"                 # transparent colour key (drawn pixels of exactly this colour are see-through)
FG, MUTED, WARN, GOOD = "#f2f2f2", "#b8bcc6", "#ff6a6a", "#6ee29a"
C_PLAYER, C_FOE, C_TARGET, C_PATH, C_SPOT, C_PROP, C_SMASH = "#6c9cf0", "#ff6a6a", "#f0c33c", "#b69cff", "#6ee29a", "#c79c78", "#ff8a4c"
C_ZONE = "#9fd8c8"
C_ITEM = {"soul": "#7fd3ff", "humanity": "#f4f4f4", "titanite": "#aaa8ff"}
ITEM_LETTER = {"soul": "S", "humanity": "H", "titanite": "T"}
POLL_S = 0.1
RADAR_PX, RADAR_M = 500, 15.0   # mini radar size (px) and range (m) — 200 → 500 ([MoKa] 2026-10-01: "2배", then "500px도 괜찮음")
SAYS = 3


# ── What to show (pure — tested in overlay_test.py) ─────────────────────────
def lines(state: dict | None, now: float | None = None) -> list[tuple[str, str]]:
    """[(text, colour)] for the text panel."""
    if not state:
        return [("no radar server — python radar_server.py", WARN)]
    snap = state.get("snap")
    age = state.get("age")
    head = []                                       # game state / Steam — only when not the normal "in game, offline"
    game = (state.get("game") or {}).get("game")
    if (state.get("steam") or {}).get("offline") is False:
        head.append(("Steam ONLINE", WARN))
    if game in ("off", "title", "dead"):
        head.append(({"off": "game off", "title": "title / loading", "dead": "dead"}[game], MUTED if game == "title" else WARN))
    if not snap:
        return head + [("no bot data — run.py … --radar, or python radar.py watch", WARN)]
    out = head
    if age is not None and age > 2:
        out.append((f"stale {age:.0f} s", WARN))
    p = snap["player"]
    if state.get("zone"):
        out.append((f"zone: {state['zone']}", C_ZONE))
    hp, mhp = p.get("hp") or 0, p.get("max_hp") or 0
    frac = hp / mhp if mhp else 0
    out.append((f"HP {hp}/{mhp} ({frac:.0%})  SP {p.get('sp')}/{p.get('max_sp')}  Estus {snap.get('flask_hp', '?')}",
                WARN if frac < 0.35 else FG))
    chars = snap.get("chars") or []
    tgt = next((c for c in chars if c.get("ptr") == snap.get("target")), None) if snap.get("target") is not None else None
    if tgt:
        out.append((f"target: {(state.get('labels') or {}).get(str(tgt.get('ptr'))) or tgt.get('name') or tgt.get('npc')}  {tgt.get('dist', 0):.1f} m  HP {tgt.get('hp')}  anim {tgt.get('anim')}", C_TARGET))
    if snap.get("path_tag"):
        out.append((f"path: {snap['path_tag']} ({len(snap.get('path') or [])} pts)", C_PATH))
    if snap.get("spot_tag"):
        out.append((f"hold: {snap['spot_tag']}", C_SPOT))
    if snap.get("smash"):
        out.append((f"smash: {snap['smash']}", C_SMASH))
    items = [o for o in (state.get("items") or []) if o[3] in C_ITEM]
    if items:
        d, o = min((math.hypot(o[0] - p["x"], o[2] - p["z"]), o) for o in items)
        out.append((f"item: {o[4]}  {d:.1f} m" + (f"  (+{len(items) - 1} more)" if len(items) > 1 else ""), C_ITEM[o[3]]))
    near = [c for c in chars if c.get("team") in HOSTILE and (c.get("hp") or 0) > 0 and (c.get("dist") or 99) < 8]
    if near:
        awake = sum(1 for c in near if c.get("anim") not in (-1, None))
        out.append((f"foes within 8 m: {len(near)} ({awake} moving)", WARN if awake >= 2 else MUTED))
    for i, s in enumerate((state.get("says") or [])[-SAYS:][::-1]):
        out.append(("› " + s.get("line", "").strip()[:80], FG if i == 0 else MUTED))    # newest first
    return out


def radar_labels(state: dict | None, size: int = RADAR_PX, range_m: float = RADAR_M) -> list[tuple[float, float, str]]:
    """Foe names on the mini radar ("ramp#2 shield", "hollow-12" — places.Labels via radar_server): [(x, y, text)] for live foes in range."""
    labels = (state or {}).get("labels") or {}
    snap = (state or {}).get("snap") or {}
    live = [c for c in snap.get("chars") or [] if c.get("team") in HOSTILE and (c.get("hp") or 0) > 0]
    out = []
    p = snap.get("player") or {}
    base = snap.get("cam_yaw") or 0.0
    c0, k = size / 2, (size / 2 - 6) / range_m
    for c in live:
        dx, dz = c["x"] - p.get("x", 0), c["z"] - p.get("z", 0)
        d = math.hypot(dx, dz)
        name = labels.get(str(c.get("ptr")))
        if d > range_m or not name:
            continue
        a = math.atan2(dx, dz) - base
        out.append((c0 + math.sin(a) * d * k, c0 - math.cos(a) * d * k, name))
    return out


def radar_points(state: dict | None, size: int = RADAR_PX, range_m: float = RADAR_M, marks: bool = True,
                 items: bool | None = None) -> list[tuple]:
    """Mini radar marks, camera-up like the radar page: [(kind, x, y)] in pixels, centre = player.
    kind: player | foe | foe_dead | target | prop | smash | item_soul | item_humanity | item_titanite | path (x, y lists)."""
    snap = (state or {}).get("snap")
    if not snap:
        return []
    p = snap["player"]
    base = snap.get("cam_yaw") or 0.0
    c0, k = size / 2, (size / 2 - 6) / range_m

    def xy(x, z):
        dx, dz = x - p["x"], z - p["z"]
        d = math.hypot(dx, dz)
        if d > range_m:
            return None
        a = math.atan2(dx, dz) - base
        return c0 + math.sin(a) * d * k, c0 - math.cos(a) * d * k

    out = []
    if snap.get("path"):
        pts = [xy(q[0], q[2]) for q in snap["path"]]
        pts = [q for q in pts if q]
        if len(pts) >= 2:
            out.append(("path", [q[0] for q in pts], [q[1] for q in pts]))
    for o in (state.get("props") or []):
        q = xy(o[0], o[2])
        if q and (marks or o[4] == snap.get("smash")):
            out.append(("smash" if o[4] == snap.get("smash") else "prop", *q))
    for o in (state.get("items") or []) if (marks if items is None else items) else []:
        if o[3] in C_ITEM:
            q = xy(o[0], o[2])
            if q:
                out.append(("item_" + o[3], *q))
    for c in snap.get("chars") or []:
        if c.get("team") not in HOSTILE:
            continue
        q = xy(c["x"], c["z"])
        if q:
            kind = "target" if c.get("ptr") == snap.get("target") else ("foe" if (c.get("hp") or 0) > 0 else "foe_dead")
            out.append((kind, *q))
    out.append(("player", c0, c0))
    return out


# ── Window ──────────────────────────────────────────────────────────────────
def _win32_passthrough(tk_root) -> None:
    """Click-through, never activated, not in the taskbar. Windows only; no-op elsewhere."""
    if sys.platform != "win32":
        return
    import ctypes
    GWL_EXSTYLE = -20
    WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_TOPMOST = 0x80000, 0x20, 0x80, 0x8000000, 0x8
    u = ctypes.windll.user32
    hwnd = u.GetParent(tk_root.winfo_id()) or tk_root.winfo_id()
    style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
    u.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST)


def _game_rect():
    """(x, y, w, h) of the game window, or None."""
    if sys.platform != "win32":
        return None
    import ctypes
    import ctypes.wintypes
    u = ctypes.windll.user32
    h = u.FindWindowW(None, "DARK SOULS™: REMASTERED")
    if not h:
        return None
    r = ctypes.wintypes.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


class Overlay:
    def __init__(self, url: str, marks: bool = False, items: bool = False):
        import tkinter as tk
        self.url, self.state, self.tk, self.marks, self.items = url, None, tk, marks, marks or items
        self.root = tk.Tk()
        self.root.title("dsr-bot overlay")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=KEY)
        if sys.platform == "win32":
            self.root.attributes("-transparentcolor", KEY)
        self.canvas = tk.Canvas(self.root, bg=KEY, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.root.geometry("900x520+40+40")
        self.root.update_idletasks()
        _win32_passthrough(self.root)
        threading.Thread(target=self._poll, daemon=True).start()
        self._rect = None
        self.root.after(100, self._tick)

    def _poll(self) -> None:
        while True:
            try:
                with urllib.request.urlopen(self.url, timeout=1.0) as r:
                    self.state = json.loads(r.read())
            except Exception:
                self.state = None
            time.sleep(POLL_S)

    def _text(self, x, y, s, col, size=13, bold=False):
        font = ("Malgun Gothic", size, "bold" if bold else "normal")
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (1, 1)):          # dark outline — readable on any background
            self.canvas.create_text(x + dx, y + dy, text=s, fill="#000000", anchor="nw", font=font)
        self.canvas.create_text(x, y, text=s, fill=col, anchor="nw", font=font)

    def _tick(self) -> None:
        rect = _game_rect()
        if rect and rect != self._rect:                                  # follow the game window
            self._rect = rect
            self.root.geometry(f"{rect[2]}x{rect[3]}+{rect[0]}+{rect[1]}")
        cv = self.canvas
        cv.delete("all")
        w = cv.winfo_width()
        y = 38
        for i, (s, col) in enumerate(lines(self.state)):
            self._text(16, y, s, col, 14 if i == 0 else 12, bold=(i == 0))
            y += 22 if i == 0 else 19
        ox, oy, R = w - RADAR_PX - 16, 38, RADAR_PX
        cv.create_oval(ox, oy, ox + R, oy + R, outline="#000000", width=3)
        cv.create_oval(ox, oy, ox + R, oy + R, outline=MUTED, width=1)
        for kind, a, b in radar_points(self.state, marks=self.marks, items=self.items):
            if kind == "path":
                pts = [v for xy in zip(a, b) for v in (ox + xy[0], oy + xy[1])]
                cv.create_line(*pts, fill=C_PATH, width=2, dash=(4, 3))
                continue
            x, y2 = ox + a, oy + b
            if kind == "player":
                cv.create_oval(x - 5, y2 - 5, x + 5, y2 + 5, fill=C_PLAYER, outline="#000000")
            elif kind.startswith("item_"):
                # bigger, with a letter — 5 px dots couldn't be told apart over the game (ROADMAP P-9)
                r = 9
                cv.create_polygon(x, y2 - r, x + r, y2, x, y2 + r, x - r, y2, fill=C_ITEM[kind[5:]], outline="#000000", width=2)
                cv.create_text(x, y2, text=ITEM_LETTER[kind[5:]], fill="#000000", font=("Segoe UI", 8, "bold"))
            elif kind in ("prop", "smash"):
                cv.create_rectangle(x - 3, y2 - 3, x + 3, y2 + 3, fill=C_PROP, outline="#000000")
                if kind == "smash":
                    cv.create_oval(x - 8, y2 - 8, x + 8, y2 + 8, outline=C_SMASH, width=2)
            else:
                col = {"foe": C_FOE, "target": C_FOE, "foe_dead": MUTED}[kind]
                cv.create_oval(x - 4, y2 - 4, x + 4, y2 + 4, fill=col, outline="#000000")
                if kind == "target":
                    cv.create_oval(x - 8, y2 - 8, x + 8, y2 + 8, outline=C_TARGET, width=2)
        for a, b, name in radar_labels(self.state):
            self._text(ox + a + 7, oy + b - 14, name, FG, 10)
        self.root.after(int(POLL_S * 1000), self._tick)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://127.0.0.1:47801/state")
    ap.add_argument("--demo", action="store_true", help="start a demo radar server too (no game)")
    ap.add_argument("--marks", action="store_true", help="also draw breakable props and items on the mini radar (off: too small to tell apart in game)")
    ap.add_argument("--items", action="store_true", help="draw souls/humanity/titanite on the mini radar, without the props")
    a = ap.parse_args()
    if a.demo:
        import subprocess
        subprocess.Popen([sys.executable, "radar_server.py", "--demo"])
        time.sleep(1.0)
    print("overlay: the game must be windowed or borderless windowed. Stop: Ctrl+C here")
    Overlay(a.url, marks=a.marks, items=a.items).run()


if __name__ == "__main__":
    main()
