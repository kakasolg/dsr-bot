"""Air-swing timing of the equipped right-hand weapon — startup · active · recovery for souls/weapons.py.

  python experiments/swing_probe.py [trials] [guard] [heavy]   (BOT_GAME=dsr, stand somewhere with no enemy within 12 m)
  guard: hold LB (shield) through the swing — how moves.light attacks with a shield (anim 425000 for the knife, not 203000)
  heavy: R2 (pad.heavy, stick released) instead of R1 — longer window, chain test with a second R2

Per trial: wait for full stamina, R1 once into the air, then read my anim, stamina and anim-struct +0xA0 as fast as
pymem allows for 2.5 s. Then the chain test: R1, second R1 after a delay, does a second swing come out (second stamina drop)?

── 읽는 법 ──────────────────────────────
 · startup  = R1 → 스태미나가 떨어진 순간 (칼날이 나가는 순간, weapons.py 24행 방법)
 · active   = +0xA0 이 5/257 인 구간 길이 (없으면 None — 값만 찍어 두고 사람이 판단)
 · recovery = 공격 애니가 끝난 순간 − (startup + active). 애니가 idle 로 안 돌아오면 None
 · 2타 연결: 두 번째 R1 을 늦게 누를수록 안 이어지는 경계가 chain_at 의 실측값
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import os
import statistics
import sys
import time

os.environ.setdefault("BOT_GAME", "dsr")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import dsr_telemetry
from dsr_telemetry import OFF_SP

ACTIVE_VALS = (5, 257)
WINDOW = 2.5
CHAIN_DELAYS = [0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]
HEAVY_WINDOW = 3.5
HEAVY_CHAIN_DELAYS = [0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6]


class Probe:
    def __init__(self, guard: bool = False, heavy: bool = False):
        self.tm = dsr_telemetry.DSRTelemetry({})
        self.pad = control.Pad()
        self.guard = guard
        self.heavy = heavy

    def press(self):
        if self.heavy:
            self.pad.heavy()                    # blocks for the trigger hold (0.12 s) — startups are far longer
        else:
            self.pad.tap(control.B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06, stick_ok=True)

    def read(self):
        tm = self.tm
        p = tm.player_ptr()
        mapd = tm.q(p + dsr_telemetry.OFF_MAPDATA)
        animst = tm.q(mapd + 0x48)
        return tm.i32(animst + 0x80), tm.i32(animst + 0xA0), tm.i32(p + OFF_SP)

    def safe(self) -> bool:
        s = self.tm.snapshot(within=12.0)
        return s is not None and not s.hostile(12.0)

    def wait_full_sp(self, timeout=8.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            s = self.tm.snapshot(within=1.0)
            if s and s.player.sp >= s.player.max_sp:
                time.sleep(0.3)
                return
            time.sleep(0.1)

    def trial(self, second_at: float | None = None):
        """→ list of (t, anim, a0, sp) change points, t relative to the first R1 press."""
        self.pad.guard(self.guard)
        self.wait_full_sp()
        idle = self.read()
        rows = [(0.0,) + idle]
        t0 = time.perf_counter()
        self.press()
        sent2 = second_at is None
        last = idle
        while (t := time.perf_counter() - t0) < (HEAVY_WINDOW if self.heavy else WINDOW) + (second_at or 0):
            if not sent2 and t >= second_at:
                self.press()
                sent2 = True
            self.pad.release_due()
            cur = self.read()
            if cur != last:
                rows.append((round(t, 3),) + cur)
                last = cur
        return idle, rows


def summarize(idle, rows):
    """startup = first sp drop, active = first 5/257 span, end = anim back to idle anim."""
    anim0, _, sp0 = idle
    drops = []
    prev_sp = sp0
    for t, a, a0, sp in rows[1:]:
        if sp is not None and prev_sp is not None and sp < prev_sp - 5:
            drops.append(t)
        prev_sp = sp
    act = []
    on = None
    for t, a, a0, sp in rows[1:]:
        if a0 in ACTIVE_VALS and on is None:
            on = t
        elif a0 not in ACTIVE_VALS and on is not None:
            act.append((on, t)); on = None
    end = next((t for t, a, a0, sp in rows[1:] if a == anim0 and t > 0.2), None)
    return drops, act, end


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    pr = Probe(guard="guard" in sys.argv[2:], heavy="heavy" in sys.argv[2:])
    control.focus_game()
    s = pr.tm.snapshot(within=1.0)
    print(f"무기 {pr.tm.right_weapon()}  SP {s.player.sp}/{s.player.max_sp}  위치 ({s.player.x:.1f},{s.player.y:.1f},{s.player.z:.1f})")
    if not pr.safe():
        print("12 m 안에 적 — 중단"); return
    starts, actives, ends = [], [], []
    try:
        print(f"\n── 한 번 휘두르기 × {n}")
        for i in range(n):
            if not pr.safe():
                print("적 접근 — 중단"); break
            idle, rows = pr.trial()
            drops, act, end = summarize(idle, rows)
            print(f"  {i+1}: 스태미나 떨어짐 {drops}  +0xA0 활성 {act}  끝(idle 애니) {end}")
            print("     " + "  ".join(f"{t:.3f}:{a}/{a0}/{sp}" for t, a, a0, sp in rows))
            if drops: starts.append(drops[0])
            if act: actives.append(act[0][1] - act[0][0])
            if end: ends.append(end)
            time.sleep(0.5)
        print("\n── 2타 연결 (두 번째 R1 시각 → 두 번째 스태미나 떨어짐)")
        for d in (HEAVY_CHAIN_DELAYS if pr.heavy else CHAIN_DELAYS):
            if not pr.safe():
                print("적 접근 — 중단"); break
            idle, rows = pr.trial(second_at=d)
            drops, act, end = summarize(idle, rows)
            print(f"  R2 {d:.2f} s: 스태미나 떨어짐 {drops}  +0xA0 활성 {act}  끝 {end}  → {'이어짐' if len(drops) >= 2 else '한 번만'}")
            time.sleep(0.5)
    finally:
        pr.pad.guard(False)
        pr.pad.neutral()
    if starts:
        st = statistics.median(starts)
        ac = statistics.median(actives) if actives else None
        en = statistics.median(ends) if ends else None
        rec = None if (en is None or ac is None) else en - st - ac
        print(f"\n중앙값: startup {st:.2f}  active {ac}  끝 {en}  → recovery {rec}")


if __name__ == "__main__":
    main()
