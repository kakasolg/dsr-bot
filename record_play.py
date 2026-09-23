"""
사람이 하는 플레이를 기록한다 — 사용자: "내가 싸우는 거 저장해줘". 봇이 사용자의 막기·구르기 타이밍을 적 애니와 맞춰 보려고.

  python record_play.py [--minutes 120]      → data/trace/play_YYYYmmdd_HHMMSS.jsonl

줄 종류 (t = 시작 뒤 초):
  {"pad": [버튼비트, LT, RT, LX, LY, RX, RY], "i": 패드번호}      실제 컨트롤러 입력이 바뀔 때마다 (XInput, 120 Hz 로 봄)
  {"my": [x,y,z,heading,hp,sp,anim], "lock": 핸들, "item": 선택 소모품}  내 상태가 바뀔 때 (10 Hz 로 봄)
  {"a": {적: [anim, dist, hp]}}                                     30 m 안 적의 애니가 바뀔 때
  {"me": [...], "e": {적: [x,y,z,heading,hp,anim]}, "phase": "사람"}   1 s 마다 전체 (trace_view.py 와 같은 모양)
  {"ev": "hit", "dmg", "who", "shot"}                               내가 맞을 때 (60 넘으면 화면 저장)
적 이름은 enemy-map 번호(스폰 1.5 m 안에서 처음 본 놈)가 있으면 그 번호, 아니면 "npc@ptr".
**읽기만 한다** — 가상 패드를 만들지 않으니 사용자 컨트롤러와 겹치지 않는다.
"""
from __future__ import annotations

import ctypes
import json
import math
import sys
import time
from ctypes import wintypes
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import env

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data" / "trace"
MAP = json.loads((ROOT / "data" / "enemy-map.json").read_text(encoding="utf-8"))["enemies"]


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", wintypes.WORD), ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short), ("sThumbRY", ctypes.c_short)]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XINPUT_GAMEPAD)]


def _xinput():
    for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
        try:
            return getattr(ctypes.windll, name)
        except OSError:
            continue
    return None


def pad_state(xi, i: int):
    st = XINPUT_STATE()
    if xi is None or xi.XInputGetState(i, ctypes.byref(st)) != 0:
        return None
    g = st.Gamepad
    q = lambda v: int(round(v / 3276.7))          # 스틱은 -10..10 로 (잔떨림에 줄이 쏟아지지 않게)
    return [g.wButtons, g.bLeftTrigger // 26, g.bRightTrigger // 26, q(g.sThumbLX), q(g.sThumbLY), q(g.sThumbRX), q(g.sThumbRY)]


def main() -> None:
    args = sys.argv[1:]
    minutes = float(args[args.index("--minutes") + 1]) if "--minutes" in args else 120.0
    tm = env.make_telemetry({})
    xi = _xinput()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"play_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    f = path.open("a", encoding="utf-8")
    t0 = time.time()

    def w(row: dict) -> None:
        f.write(json.dumps({"t": round(time.time() - t0, 3), **row}, ensure_ascii=False) + "\n")

    names: dict[int, str] = {}

    def name(c) -> str:
        if c.ptr not in names:
            idx = next((i for i, e in enumerate(MAP, 1) if math.dist((c.x, c.y, c.z), e["pos"]) < 1.5 and e["npc"] == c.npc_param), None)
            names[c.ptr] = str(idx) if idx else f"{c.npc_param}@{c.ptr:x}"
        return names[c.ptr]

    print(f"기록 시작 → {path}  ({minutes:.0f} 분, Ctrl+C 로 끝)", flush=True)
    w({"ev": "start", "xinput": [i for i in range(4) if pad_state(xi, i) is not None]})
    last_pad: dict[int, list] = {}
    last_my, last_anim, last_full, last_snap, hp_last = None, {}, 0.0, 0.0, None
    loading = False
    n_rows = 0
    try:
        while time.time() - t0 < minutes * 60:
            now = time.time()
            for i in range(4):
                ps = pad_state(xi, i)
                if ps is not None and ps != last_pad.get(i):
                    last_pad[i] = ps
                    w({"pad": ps, "i": i})
                    n_rows += 1
            if now - last_snap >= 0.1:
                last_snap = now
                try:
                    s = tm.snapshot(within=30.0)
                except Exception:
                    s = None
                if s is None:
                    if not loading:
                        w({"ev": "loading"})
                        loading = True
                else:
                    loading = False
                    p = s.player
                    my = [round(p.x, 2), round(p.y, 2), round(p.z, 2), None if p.heading is None else round(p.heading, 2), p.hp, p.sp, p.anim]
                    lock = tm.lock_target()
                    if last_my is None or my[4:] != last_my[4:] or math.dist(my[:3], last_my[:3]) > 0.3 or \
                            (my[3] is not None and last_my[3] is not None and abs(my[3] - last_my[3]) > 0.15):
                        w({"my": my, "lock": lock, "item": tm.selected_item()})
                        n_rows += 1
                    if hp_last is not None and p.hp < hp_last:
                        who = [(name(c), round(c.dist, 1), c.anim) for c in s.hostile(6.0) if c.hp > 0]
                        shot = None
                        if hp_last - p.hp >= 60:
                            try:
                                import vision_probe as vp
                                from PIL import ImageGrab
                                rc = vp.window_rect()
                                if rc:
                                    shot = f"play_hit_{time.strftime('%H%M%S')}_{hp_last - p.hp}.jpg"
                                    ImageGrab.grab(bbox=rc, all_screens=True).resize((800, 450)).save(vp.IMG_DIR / shot, quality=80)
                            except Exception:
                                shot = None
                        w({"ev": "hit", "dmg": hp_last - p.hp, "who": who, "my_anim": p.anim, "shot": shot})
                    hp_last = p.hp
                    last_my = my
                    ch = {}
                    for c in s.hostile(30.0):
                        if last_anim.get(c.ptr) != (c.anim, c.hp):
                            last_anim[c.ptr] = (c.anim, c.hp)
                            ch[name(c)] = [c.anim, round(c.dist, 1), c.hp]
                    if ch:
                        w({"a": ch})
                        n_rows += 1
                    if now - last_full >= 1.0:
                        last_full = now
                        w({"phase": "사람", "me": my[:4] + [p.hp, p.sp, p.anim, None],
                           "e": {name(c): [round(c.x, 2), round(c.y, 2), round(c.z, 2), None if c.heading is None else round(c.heading, 2), c.hp, c.anim]
                                 for c in s.hostile(30.0)}})
                        f.flush()
            time.sleep(1 / 120)
    except KeyboardInterrupt:
        pass
    finally:
        w({"ev": "end"})
        f.close()
        print(f"기록 끝: {path} ({n_rows} 줄, {(time.time() - t0) / 60:.1f} 분)", flush=True)


if __name__ == "__main__":
    main()
