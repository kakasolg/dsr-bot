"""One pad button → wait → screenshot, for learning menus by hand (MoKa 2026-10-12: "A누를 때 마다 스크린샷 찍어서 확인 하면서
테스트 하면 어떨까?" — the Undead Merchant's shop, firebombs and throwing knives).

  python pad_step.py A                     press A (0.1 s), wait 0.8 s, screenshot
  python pad_step.py DOWN --n 3            press DOWN three times (0.25 s apart), then one screenshot
  python pad_step.py none                  screenshot only
  python pad_step.py A --tag talk          name part of the file

Buttons: A B X Y START BACK UP DOWN LEFT RIGHT LB RB. Screenshots: data/shop/<date>/<nn>_<button>[_tag].jpg (JPEG ~150 KB,
committed as the record [cloud] builds the shop routine from). Each line also prints souls and the counts of the goods
we're after (290 throwing knife · 292 firebomb?) so a purchase shows up as numbers too. Holds data/bot.lock; focuses the
game first; game memory is only read. BOT_GAME=dsr.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
WATCH_GOODS = {290: "투척 나이프?", 292: "화염병?"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("button")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--hold", type=float, default=0.1)
    ap.add_argument("--wait", type=float, default=0.8)
    ap.add_argument("--tag", default="")
    ap.add_argument("--dir", default="", help="subfolder of data/shop/ (default: today's date)")
    a = ap.parse_args()

    import control
    import env
    import shot
    from botlock import BotLock
    lock = BotLock()
    if not lock.acquire():
        raise SystemExit("봇이 돌고 있음 (data/bot.lock)")
    B = control.B
    names = {"A": B.XUSB_GAMEPAD_A, "B": B.XUSB_GAMEPAD_B, "X": B.XUSB_GAMEPAD_X, "Y": B.XUSB_GAMEPAD_Y,
             "START": B.XUSB_GAMEPAD_START, "BACK": B.XUSB_GAMEPAD_BACK, "UP": B.XUSB_GAMEPAD_DPAD_UP,
             "DOWN": B.XUSB_GAMEPAD_DPAD_DOWN, "LEFT": B.XUSB_GAMEPAD_DPAD_LEFT, "RIGHT": B.XUSB_GAMEPAD_DPAD_RIGHT,
             "LB": B.XUSB_GAMEPAD_LEFT_SHOULDER, "RB": B.XUSB_GAMEPAD_RIGHT_SHOULDER}
    btn = a.button.upper()
    if btn != "NONE" and btn not in names:
        raise SystemExit(f"모르는 버튼 {a.button} — {' '.join(names)} none")
    try:
        control.focus_game()
        tm = env.make_telemetry({})
        pad = control.Pad() if btn != "NONE" else None
        before = {g: tm.goods_count(g) for g in WATCH_GOODS}
        souls0 = tm.souls()
        if pad is not None:
            for i in range(a.n):
                pad.press(names[btn], a.hold)
                time.sleep(0.25 if i < a.n - 1 else 0.0)
        time.sleep(a.wait)
        out = ROOT / "data" / "shop" / (a.dir or time.strftime("%Y%m%d"))
        out.mkdir(parents=True, exist_ok=True)
        n = len(list(out.glob("*.jpg"))) + 1
        name = f"{n:02d}_{btn.lower()}{'x' + str(a.n) if a.n > 1 else ''}{'_' + a.tag if a.tag else ''}.jpg"
        png = out / (name[:-4] + ".png")
        shot.shot(png)
        from PIL import Image
        Image.open(png).convert("RGB").save(out / name, quality=70)
        png.unlink()
        after = {g: tm.goods_count(g) for g in WATCH_GOODS}
        souls1 = tm.souls()
        goods = " · ".join(f"{g} {WATCH_GOODS[g]} {before[g]}→{after[g]}" if before[g] != after[g] else f"{g} {after[g]}"
                           for g in WATCH_GOODS)
        print(f"{out / name}  메뉴 {tm.menu_open()} · 소울 {souls0}→{souls1} · {goods}")
        if pad is not None:
            pad.close()
    finally:
        lock.release()


if __name__ == "__main__":
    main()
