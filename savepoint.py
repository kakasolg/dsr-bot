"""Save point for repeated tries (MoKa 2026-10-11: "타이틀로 가서 세이브 하고, 다시 타이틀 나가서 복원 하면 됨").

  python savepoint.py save <why>          menu quit-out to the title → copy the save folder to backup-<time>-<why> → Continue
  python savepoint.py restore <backup>    menu quit-out to the title → back up the live save (…-before-restore) →
                                          put <backup>'s DRAKS0005.sl2 back → Continue → check we stand where it was saved
  python savepoint.py reload              menu quit-out to the title → Continue (no file change). Inside the Taurus fog a load
                                          puts the character in front of the fog wall; killed foes stay dead (menu, not byte)
  python savepoint.py list                backups, newest first

At the title the game has written the save ("Updating save data…"); we wait until DRAKS0005.sl2 stops changing before
reading or replacing it. Continue reads the file again, so no game restart is needed. One file holds every character —
the backup is the whole folder (memory: backup-save-before-new-character). Holds data/bot.lock while it runs (radar warp
and bots refuse meanwhile). BOT_GAME=dsr.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SAVE_ROOT = Path(os.environ.get("USERPROFILE", "~")).expanduser() / "Documents" / "NBGI" / "DARK SOULS REMASTERED"
SAVE_ID = "384481941"
SL2 = "DRAKS0005.sl2"
META = "savepoint.json"
STABLE_S = 2.0          # the file is done when size·mtime haven't changed this long
STABLE_MAX_S = 30.0
ARRIVE_M = 3.0          # after a restore, standing within this of the saved spot = the restore took


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def wait_stable(p: Path, log=print) -> bool:
    t0, last, since = time.time(), None, time.time()
    while time.time() - t0 < STABLE_MAX_S:
        st = p.stat()
        cur = (st.st_size, st.st_mtime_ns)
        if cur != last:
            last, since = cur, time.time()
        elif time.time() - since >= STABLE_S:
            return True
        time.sleep(0.2)
    log(f"  {p.name}: {STABLE_MAX_S:.0f} s 동안 계속 바뀜")
    return False


def where(tm) -> dict | None:
    s = tm.snapshot(within=1.0)
    if s is None or s.player is None:
        return None
    p = s.player
    out = {"pos": [round(p.x, 2), round(p.y, 2), round(p.z, 2)], "hp": p.hp, "max_hp": p.max_hp}
    try:
        from souls import moves
        out["estus"] = moves.Moves(tm, None).estus_left()
    except Exception:
        pass
    try:
        out["char"] = tm.char_name()
    except Exception:
        pass
    return out


def slot0_taken() -> bool:
    """Another pad on XInput slot 0 before we plug ours in (MoKa's Xbox controller). Only a hint: on 2026-10-11 START ×5
    was not taken while it was on, but MoKa says the cause was game focus (control.focus_game now runs first)."""
    try:
        import ctypes

        class _S(ctypes.Structure):
            _fields_ = [("pn", ctypes.c_uint32), ("b", ctypes.c_ushort), ("lt", ctypes.c_ubyte), ("rt", ctypes.c_ubyte),
                        ("lx", ctypes.c_short), ("ly", ctypes.c_short), ("rx", ctypes.c_short), ("ry", ctypes.c_short)]
        return ctypes.WinDLL("xinput1_4").XInputGetState(0, ctypes.byref(_S())) == 0
    except Exception:
        return False


def to_title(tm, pad, log=print) -> bool:
    """Menus by keyboard ([MoKa] 2026-10-13 "앞으로 메뉴는 키보드로 해", docs/keyboard-menus.md) — the pad quit-out failed 3× that day."""
    import keys
    t0 = time.time()
    if not keys.to_title(tm, log=log):
        log("  키보드 타이틀로 실패 — 그대로 둠")
        return False
    log(f"  타이틀로 (키보드, {time.time() - t0:.1f} s)")
    return True


def back_in(pad, log=print):
    import env
    import keys
    tm = env.make_telemetry({})
    t0 = time.time()
    if not keys.continue_(tm, log=log):
        log("  이어하기 실패 (키보드, 40 s)")
        return None
    log(f"  이어하기 (키보드, {time.time() - t0:.1f} s)")
    return tm


def backup(why: str, log=print) -> Path:
    live = SAVE_ROOT / SAVE_ID
    dst = SAVE_ROOT / f"backup-{time.strftime('%Y%m%d-%H%M%S')}-{why}"
    shutil.copytree(live, dst)
    a, b = sha(live / SL2), sha(dst / SL2)
    if a != b:
        raise SystemExit(f"  백업 해시 다름 {a[:8]} ≠ {b[:8]}")
    log(f"  백업 {dst.name} (sl2 {a[:8]})")
    return dst


def cmd_save(why: str) -> None:
    import control
    import env
    control.focus_game()                               # 2026-10-11: no focus → START ×5 not taken (MoKa)
    tm, pad = env.make_telemetry({}), control.Pad()
    pad.reconnect()                                    # 10-13: right after another pad was unplugged ('컨트롤러 연결 해제' ×2) the game ignored a fresh pad — quit-out failed 3×
    here = where(tm)
    log = print
    log(f"지금: {here}")
    if not to_title(tm, pad, log):
        sys.exit(1)
    wait_stable(SAVE_ROOT / SAVE_ID / SL2, log)
    dst = backup(why, log)
    (dst / META).write_text(json.dumps({"saved": time.strftime("%Y-%m-%d %H:%M:%S"), "why": why, **(here or {})},
                                       ensure_ascii=False, indent=1), encoding="utf-8")
    tm2 = back_in(pad, log)
    log(f"돌아옴: {where(tm2) if tm2 else None}")
    pad.close()


def cmd_restore(name: str) -> None:
    import control
    import env
    src = SAVE_ROOT / name
    if not (src / SL2).is_file():
        raise SystemExit(f"없음: {src / SL2}")
    meta = json.loads((src / META).read_text(encoding="utf-8")) if (src / META).is_file() else {}
    want = sha(src / SL2)
    control.focus_game()
    tm, pad = env.make_telemetry({}), control.Pad()
    pad.reconnect()                                    # 10-13: right after another pad was unplugged ('컨트롤러 연결 해제' ×2) the game ignored a fresh pad — quit-out failed 3×
    log = print
    log(f"복원할 것: {src.name} (sl2 {want[:8]}) {meta.get('pos')} · 지금 {where(tm)}")
    if not to_title(tm, pad, log):
        sys.exit(1)
    live = SAVE_ROOT / SAVE_ID / SL2
    wait_stable(live, log)
    backup(f"before-restore-{name.removeprefix('backup-')[:40]}", log)
    shutil.copy2(src / SL2, live)
    if sha(live) != want:
        raise SystemExit("  덮어쓴 sl2 해시가 다름 — 이어하기 안 함")
    log(f"  sl2 되돌림 ({want[:8]})")
    tm2 = back_in(pad, log)
    now = where(tm2) if tm2 else None
    log(f"돌아옴: {now}")
    if now and meta.get("pos"):
        d = math.dist(now["pos"], meta["pos"])
        log(f"  저장 자리와 {d:.1f} m — {'복원 됨' if d <= ARRIVE_M else '복원 안 된 듯 (자리 다름)'}")
    pad.close()


def cmd_reload() -> None:
    import control
    import env
    control.focus_game()
    tm, pad = env.make_telemetry({}), control.Pad()
    pad.reconnect()                                    # 10-13: right after another pad was unplugged ('컨트롤러 연결 해제' ×2) the game ignored a fresh pad — quit-out failed 3×
    print(f"지금: {where(tm)}")
    if not to_title(tm, pad):
        sys.exit(1)
    tm2 = back_in(pad)
    print(f"돌아옴: {where(tm2) if tm2 else None}")
    pad.close()


def cmd_list() -> None:
    for p in sorted(SAVE_ROOT.glob("backup-*"), key=lambda p: p.stat().st_mtime, reverse=True)[:15]:
        m = p / META
        extra = json.loads(m.read_text(encoding="utf-8")) if m.is_file() else {}
        print(f"{p.name}  {extra.get('pos', '')} {('HP ' + str(extra['hp'])) if 'hp' in extra else ''}")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("save", "restore", "reload", "list"):
        print(__doc__)
        sys.exit(2)
    if sys.argv[1] == "list":
        return cmd_list()
    if sys.argv[1] == "reload":
        sys.argv.append("-")
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    if slot0_taken():
        print("  참고: XInput 0번 슬롯에 다른 패드가 있음 (실제 컨트롤러?) — 입력이 안 먹히면 이것도 의심")
    from botlock import BotLock
    lock = BotLock()
    if not lock.acquire():
        raise SystemExit("봇이 돌고 있음 (data/bot.lock) — 끝난 뒤에")
    try:
        if sys.argv[1] == "reload":
            cmd_reload()
        else:
            (cmd_save if sys.argv[1] == "save" else cmd_restore)(sys.argv[2])
    finally:
        lock.release()


if __name__ == "__main__":
    main()
