"""Menus by keyboard ([MoKa] 2026-10-13 "메뉴 명령은 키보드가 정확해" · "앞으로 메뉴는 키보드로 해") — docs/keyboard-menus.md.

  python keys.py continue          title ("PRESS ANY BUTTON" or the menu) → into the world
  python keys.py title             in the world → save and back to the title
  python keys.py quit              title → close the game
  python keys.py cycle [n]         n × (continue → title), timed
  python keys.py fallwatch [min]   watch; at the first sign of a fall → keys to the title at once (timed)

Keys go as scancodes (KEYEVENTF_SCANCODE; arrows also EXTENDEDKEY) to the focused game. Each step waits on the game's own
state (player readable = in the world, menu_open) instead of fixed sleeps, and re-sends a key the game ate (10-13: the
first key after focusing was sometimes dropped).
"""
from __future__ import annotations

import ctypes
import os
import sys
import time

os.environ.setdefault("BOT_GAME", "dsr")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env

SCAN = {"esc": (0x1B, 0x01), "e": (0x45, 0x12), "q": (0x51, 0x10), "enter": (0x0D, 0x1C),
        "left": (0x25, 0x4B), "up": (0x26, 0x48), "right": (0x27, 0x4D), "down": (0x28, 0x50)}
EXTENDED = {"left", "up", "right", "down"}
HOLD_S = 0.06
GAP_S = 0.25            # between keys inside one menu — 10-13: 0.12 s dropped keys (menu closed), 0.25 s: ESC → title in 2.9 s


def press(key: str, hold: float = HOLD_S) -> None:
    vk, sc = SCAN[key]
    fl = 0x0008 | (0x0001 if key in EXTENDED else 0)
    u = ctypes.windll.user32
    u.keybd_event(vk, sc, fl, 0)
    time.sleep(hold)
    u.keybd_event(vk, sc, fl | 0x0002, 0)


def seq(keys, gap: float = GAP_S) -> None:
    for k in keys:
        press(k)
        time.sleep(gap)


def in_world(tm) -> bool:
    try:
        s = tm.snapshot(within=3.0)
        return s is not None and s.player is not None and s.player.hp is not None and s.player.max_hp
    except Exception:
        return False


def menu_open(tm):
    try:
        return tm.menu_open()
    except Exception:
        return None


def wait(cond, timeout: float, step: float = 0.1) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(step)
    return False


def to_title(tm, log=print) -> bool:
    """In the world → ESC · ← (System) · E · ↑ (Quit Game) · E · ← (OK; default CANCEL) · E → title. → reached the title."""
    control.focus_game()
    for attempt in range(3):
        press("esc")
        if not wait(lambda: menu_open(tm) is True, 1.5):
            log(f"  ESC 뒤 메뉴 안 열림 ({attempt + 1}/3)")
            continue
        time.sleep(GAP_S)
        seq(["left", "e", "up", "e", "left", "e"])
        if wait(lambda: not in_world(tm), 8.0):
            return True
        log(f"  타이틀로 안 나감 ({attempt + 1}/3) — 메뉴 닫고 다시")
        seq(["q", "q", "q"])
    return False


SETTLE_S = 1.5          # after Continue: the world reads before the fade-in ends; an ESC then was eaten (10-13 cycle: 1st try failed 3/3)


def continue_(tm, log=print, timeout: float = 40.0) -> bool:
    """Title → into the world: E until the player is readable (covers PRESS ANY BUTTON · offline notice · Continue)."""
    control.focus_game()
    t0 = time.time()
    while time.time() - t0 < timeout:
        if in_world(tm):
            return True
        press("e")
        if wait(lambda: in_world(tm), 1.2):
            time.sleep(SETTLE_S)
            return True
    return False


def quit_game(log=print) -> None:
    """Title menu → Quit Game (↓ ×5 from Continue) → E. Only from the title menu."""
    control.focus_game()
    seq(["down"] * 5 + ["e"], gap=0.3)


FALL_GAP_S = 0.15        # 10-13: 0.15 s (with the same pause after ESC) left the world 2.30 s after ESC, 2/2 · 0.2 s 2.60 s · 0.25 s 2.89 s
FALL_ANIMS = (1500, 1550, 121500)   # = souls/watch.FALL_ANIMS + 1500 (falling)
FALL_DY = 1.0                      # or the height dropped this much within FALL_WINDOW_S
FALL_WINDOW_S = 0.3


def fall_watch(tm, minutes: float = 10.0, log=print, gap: float = None) -> None:
    """[MoKa] 2026-10-13 "낙사 할때, 타이틀 화면 가는것 시도 할꺼야": at the first sign of a fall, ESC + the quit-to-title keys at once.
    Logs fall start (anim / height), keys done, left the world, and where we stand after coming back in (Continue by hand or
    `keys.py continue`). Watches only — sends keys only when it fires, once."""
    import collections
    ys = collections.deque()
    t_end = time.time() + minutes * 60
    log(f"낙하 감시 시작 ({minutes:.0f}분) — 낙하 애니 {FALL_ANIMS} 또는 {FALL_WINDOW_S} s에 {FALL_DY} m 넘게 내려가면 타이틀로")
    while time.time() < t_end:
        try:
            s = tm.snapshot(within=3.0)
        except Exception:
            s = None
        if s is None or s.player is None or s.player.hp is None:
            time.sleep(0.03)
            continue
        p, now = s.player, time.time()
        ys.append((now, p.y))
        while ys and now - ys[0][0] > FALL_WINDOW_S:
            ys.popleft()
        drop = max(y for _, y in ys) - p.y
        if (p.anim in FALL_ANIMS) or drop > FALL_DY:
            pos0 = (round(p.x, 2), round(p.y, 2), round(p.z, 2))
            why = f"애니 {p.anim}" if p.anim in FALL_ANIMS else f"{drop:.1f} m / {FALL_WINDOW_S} s"
            control.focus_game()
            t0 = time.time()
            press("esc")
            wait(lambda: menu_open(tm) is True, 0.6, step=0.02)
            g = FALL_GAP_S if gap is None else gap
            time.sleep(g)
            seq(["left", "e", "up", "e", "left", "e"], gap=g)
            t_keys = time.time() - t0
            hp_at, y_at, out = None, None, None
            while time.time() - t0 < 8.0:
                try:
                    s2 = tm.snapshot(within=3.0)
                except Exception:
                    s2 = None
                if s2 is None or s2.player is None or s2.player.hp is None:
                    out = time.time() - t0
                    break
                hp_at, y_at = s2.player.hp, round(s2.player.y, 2)
                time.sleep(0.02)
            log(f"낙하 감지 ({why}) @ {pos0}, HP {p.hp} → 키 끝 {t_keys:.2f} s → "
                + (f"게임 밖 {out:.2f} s (마지막으로 읽힌 HP {hp_at}, y {y_at})" if out else "게임 밖으로 안 나감 (8 s)"))
            return
        time.sleep(0.03)
    log("낙하 없음 — 감시 끝")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "cycle"
    tm = env.make_telemetry({})
    if cmd == "continue":
        print("in" if continue_(tm) else "failed")
    elif cmd == "title":
        print("title" if to_title(tm) else "failed")
    elif cmd == "quit":
        quit_game()
    elif cmd == "fallwatch":
        fall_watch(tm, float(sys.argv[2]) if len(sys.argv) > 2 else 10.0)
    elif cmd == "cycle":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        for k in range(n):
            t0 = time.time()
            ok_in = continue_(tm)
            t1 = time.time()
            ok_out = to_title(tm) if ok_in else False
            t2 = time.time()
            print(f"{k + 1}: 이어하기 {'됨' if ok_in else '실패'} {t1 - t0:.1f} s · 타이틀로 {'됨' if ok_out else '실패'} {t2 - t1:.1f} s")
            if not (ok_in and ok_out):
                break
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
