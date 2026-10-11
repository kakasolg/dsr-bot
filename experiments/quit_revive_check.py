"""Do killed foes come back after a quit-out? (P-25) — one quit-out + Continue, foes and the save file before / after.

  BOT_GAME=dsr python experiments/quit_revive_check.py byte     ChrClassWarp+0x19 = 1 (straight to title, Escape.fire's way)
  BOT_GAME=dsr python experiments/quit_revive_check.py menu     menu → Quit Game (quitout.quit_out), the 09-24 way

Kill a foe or two by hand first, stand still, then run it. Writes the bot lock and the virtual pad like run.py (one pad per
machine). Result: foes within 60 m per npc (alive / dead) before and after, the save file's modified time and hash before,
right after the exit and after Continue → printed and saved to data/runs/<time>_quit_check_<how>.json.
Offline only (CLAUDE.md: memory writes) — the byte way writes one game byte.
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("BOT_GAME", "dsr")                   # this check is DSR-only (P-25); without it env looks for eldenring.exe
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env
import quitout
from botlock import BotLock

ROOT = Path(__file__).resolve().parent.parent
R = 60.0


def save_file() -> Path | None:
    base = Path.home() / "Documents" / "NBGI" / "DARK SOULS REMASTERED"
    files = [p for p in base.glob("*/DRAKS0005.sl2") if not p.parent.name.startswith("backup")]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def save_state() -> dict:
    p = save_file()
    if p is None:
        return {"file": None}
    b = p.read_bytes()
    return {"file": str(p), "mtime": time.strftime("%H:%M:%S", time.localtime(p.stat().st_mtime)),
            "mtime_s": p.stat().st_mtime, "sha1": hashlib.sha1(b).hexdigest()[:12]}


def foes(tm) -> list[dict]:
    s = tm.snapshot(within=R)                         # within = radius (m)
    if s is None:
        return []
    p = s.player
    out = []
    for c in s.chars:
        if c.team == 1:
            continue
        d = ((c.x - p.x) ** 2 + (c.z - p.z) ** 2) ** 0.5
        if d <= R:
            out.append({"ptr": c.ptr, "npc": c.npc_param, "hp": c.hp, "max_hp": c.max_hp,
                        "pos": [round(c.x, 1), round(c.y, 1), round(c.z, 1)], "dist": round(d, 1)})
    return out


def tally(fs: list[dict]) -> dict:
    c = collections.defaultdict(lambda: [0, 0])
    for f in fs:
        c[f["npc"]][0 if f["hp"] and f["hp"] > 0 else 1] += 1
    return {str(k): {"alive": v[0], "dead": v[1]} for k, v in sorted(c.items())}


def main() -> None:
    how = sys.argv[1] if len(sys.argv) > 1 else "byte"
    if how not in ("byte", "menu"):
        raise SystemExit("usage: quit_revive_check.py byte|menu")
    lock = BotLock()
    for _ in range(10):
        if lock.acquire():
            break
        time.sleep(0.2)
    else:
        raise SystemExit("a bot is running (data/bot.lock)")
    pad = None
    try:
        tm = env.make_telemetry({})
        before = foes(tm)
        sv0 = save_state()
        print(f"before: {tally(before)}  save {sv0.get('mtime')} {sv0.get('sha1')}")
        control.focus_game()
        pad = control.Pad()
        pad.neutral()
        t0 = time.time()
        if how == "byte":
            q = time.time() - t0 if tm.quit_to_title(timeout=3.0) else None
        else:
            q = quitout.quit_out(tm, pad, gap=quitout.MENU_GAP, settle=0.1, ready_wait=0.05)
        if q is None:
            quitout.close_menu(tm, pad)
            raise SystemExit(f"quit-out ({how}) failed — still in the world")
        steps = dict(quitout.LAST_STEPS)                  # menu: ms per step (ready, start, systab, system, quitsel, confirm_quit, ok_sel, gone)
        if steps:
            print(f"steps (ms): {steps}")
        time.sleep(3.0)                                   # a menu save would land by now
        sv1 = save_state()
        print(f"exited ({how}) in {q:.2f} s — save {sv1.get('mtime')} {sv1.get('sha1')}"
              f" ({'CHANGED' if sv1.get('sha1') != sv0.get('sha1') else 'same'})")
        r = quitout.reload(pad)
        time.sleep(4.0)                                   # let the foes load in
        tm2 = env.make_telemetry({})
        after = foes(tm2)
        sv2 = save_state()
        tb, ta = tally(before), tally(after)
        revived = {k: ta[k]["alive"] - tb.get(k, {"alive": 0})["alive"] for k in ta
                   if ta[k]["alive"] > tb.get(k, {"alive": 0})["alive"]}
        print(f"after Continue ({'%.1f s' % r if r else 'reload failed'}): {ta}  save {sv2.get('mtime')} {sv2.get('sha1')}")
        print(f"more alive than before (revived?): {revived or 'none'}")
        out = {"how": how, "quit_s": round(q, 2), "steps_ms": steps, "reload_s": None if r is None else round(r, 1),
               "save": {"before": sv0, "after_exit": sv1, "after_continue": sv2},
               "before": before, "after": after, "tally_before": tb, "tally_after": ta, "revived": revived}
        dst = ROOT / "data" / "runs" / f"{time.strftime('%Y%m%d_%H%M%S')}_quit_check_{how}.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"→ {dst}")
    finally:
        if pad is not None:
            pad.neutral()
            pad.close()
        lock.release()


if __name__ == "__main__":
    main()
