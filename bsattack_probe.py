"""백스텝 공격(695 → 304500) 을 내는 입력 찾기 — 사용자 시범: 695 뒤 0.96 s 에 304500, 봇의 B 톡 + 0.45 s R1 은 690 → 304040 (보통 약공).

  python bsattack_probe.py [--variants all]

적 없는 자리에서 조합마다 한 번씩: 양손 확인 → 스틱 중립 → B(hold) → t 뒤 R1 → 2.5 s 동안 내 애니 흐름을 60 Hz 로 읽는다.
락온이 필요한 조합(lock)은 5 m 안에 적이 있을 때만 (R3 로 걸고, 끝나면 푼다).
"""
from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env
from control import B

VARIANTS = [
    # 이름, B 누름(s), R1 시각(s), 스틱(x,y) B 와 함께, 락온
    ("tap_r1_045",   0.06, 0.45, None, False),      # 봇이 쓰던 것 (690 → 304040 예상)
    ("tap_r1_070",   0.06, 0.70, None, False),
    ("tap_r1_090",   0.06, 0.90, None, False),      # 사용자 간격
    ("tap_r1_110",   0.06, 1.10, None, False),
    ("hold25_r1_090", 0.25, 0.90, None, False),
    ("back_r1_090",  0.06, 0.90, (0.0, -0.6), False),   # 스틱 뒤로 + B
    ("tap_r1_045_lock", 0.06, 0.45, None, True),
    ("tap_r1_090_lock", 0.06, 0.90, None, True),
]


def watch(tm, secs: float) -> list:
    t0, out, last = time.time(), [], None
    while time.time() - t0 < secs:
        s = tm.snapshot(within=5.0)
        a = s.player.anim if s else None
        if a != last:
            out.append((round(time.time() - t0, 2), a))
            last = a
        time.sleep(1 / 60)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="all")
    a = ap.parse_args()
    tm = env.make_telemetry({})
    control.focus_game()
    pad = control.Pad()
    if tm.grip() == 1:
        pad.two_hand_right()
        time.sleep(0.5)
    print(f"grip {tm.grip()}  lock {tm.lock_target()}", flush=True)
    s = tm.snapshot(within=8.0)
    has_enemy = bool(s and s.hostile(8.0))
    for name, hold, t_r1, stick, lock in VARIANTS:
        if a.variants != "all" and name not in a.variants.split(","):
            continue
        if lock and not has_enemy:
            print(f"{name:16s} 건너뜀 (8 m 안 적 없음)", flush=True)
            continue
        pad.neutral()
        time.sleep(1.0)
        if lock:
            pad.lock_on()
            time.sleep(0.4)
            pad.release_due()
            if tm.lock_target() in (None, -1):
                print(f"{name:16s} 락온 안 걸림 — 건너뜀", flush=True)
                continue
        if stick:
            pad.move(*stick)
            time.sleep(0.05)
        else:
            pad.release_stick()
        t0 = time.time()
        pad.tap(B.XUSB_GAMEPAD_B, hold)
        anims, last, r1_done = [], None, False
        while time.time() - t0 < 2.5:
            pad.release_due()
            if not r1_done and time.time() - t0 >= t_r1:
                pad.tap(B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06, stick_ok=True)
                r1_done = True
            s = tm.snapshot(within=5.0)
            an = s.player.anim if s else None
            if an != last:
                anims.append((round(time.time() - t0, 2), an))
                last = an
            time.sleep(1 / 60)
        pad.move(0.0, 0.0)
        pad.release_due()
        if lock and tm.lock_target() not in (None, -1):
            pad.lock_on()
            time.sleep(0.3)
            pad.release_due()
        got = [an for _, an in anims]
        verdict = "★ 304500" if 304500 in got else ("695" if 695 in got else "")
        print(f"{name:16s} B {hold:.2f}s R1@{t_r1:.2f}s {'락온' if lock else ''} → {anims}  {verdict}", flush=True)
        time.sleep(1.5)
    pad.neutral()


if __name__ == "__main__":
    main()
