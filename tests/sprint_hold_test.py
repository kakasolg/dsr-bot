"""P-70: the sprint B is never let go within SPRINT_MIN_HOLD_S of pressing it — a shorter hold is a tap (roll while walking,
jump while running, backstep standing). Real control.Pad on a fake vgamepad (pad_fakes), no game.
python tests/sprint_hold_test.py

Checks:
  · sprint(True) → sprint(False) after 0.1 s: B stays down, then release_due lets it go at SPRINT_MIN_HOLD_S
  · sprint(False) → sprint(True) inside that window: B never goes up (one continuous hold)
  · neutral() right after the press: stick 0, B still down until SPRINT_MIN_HOLD_S
  · after SPRINT_MIN_HOLD_S: sprint(False) / neutral() release at once (old behaviour)
  · nav.follow sprinting through braked points (sprint → walk every 0.1 s): no B hold shorter than SPRINT_MIN_HOLD_S
  · tap(B) (dodge) is still a short tap
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
import tempfile
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import nav
import pad_fakes
from telemetry import Chr, Snapshot

BB = "XUSB_GAMEPAD_B"
MIN = control.SPRINT_MIN_HOLD_S


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def b_down(rec) -> bool:
    return BB in rec.last().get("buttons", set())


def holds(rec, n0: int) -> list[float]:
    """Lengths of every B hold in the reports since n0 (by report time stamps)."""
    out, since = [], None
    for x, t in zip(rec.sent[n0:], rec.times[n0:]):
        down = BB in x.get("buttons", set())
        if down and since is None:
            since = t
        elif not down and since is not None:
            out.append(t - since)
            since = None
    return out


class WalkTm:
    def __init__(self, path):
        self.path, self.i, self.ticks = path, 0, 0

    def snapshot(self, within: float = 40.0):
        self.ticks += 1
        if self.ticks % 3 == 0 and self.i < len(self.path):
            self.i += 1
        x, y, z = ([(0.0, 0.0, -3.0)] + list(self.path))[min(self.i, len(self.path))]
        p = Chr(1, 0, 1, 500, 500, x, y, z, gx=x, gy=y, gz=z, heading=0.0)
        return Snapshot(t=0.0, player=p, chars=[], cam_yaw=0.0)


def main() -> None:
    vg = pad_fakes.install(Path(tempfile.mkdtemp(prefix="sprint_")))
    pad = control.Pad()
    rec = vg.devices[-1]

    pad.sprint(True)
    time.sleep(0.1)
    pad.sprint(False)
    check("0.1 s 뒤 sprint(False): B 아직 눌림", b_down(rec))
    time.sleep(MIN - 0.1 + 0.05)
    pad.release_due()
    check(f"{MIN} s 지나 release_due: B 뗌", not b_down(rec))

    pad.sprint(True)
    time.sleep(0.1)
    pad.sprint(False)
    time.sleep(0.1)
    pad.sprint(True)
    n0 = len(rec.sent)
    time.sleep(MIN)
    pad.release_due()
    check("창 안에서 다시 sprint(True): B 한 번도 안 떨어짐", all(BB in x.get("buttons", set()) for x in rec.sent[n0:]) and b_down(rec))
    pad.sprint(False)
    check("오래 누른 뒤 sprint(False): 바로 뗌", not b_down(rec))

    pad.sprint(True)
    pad.move(0.5, 0.5)
    time.sleep(0.05)
    pad.neutral()
    st = rec.last()
    check("누르자마자 neutral: 스틱 0, B는 유지", st["lx"] == 0 and st["ly"] == 0 and b_down(rec))
    time.sleep(MIN)
    pad.release_due()
    check("neutral 뒤 시간이 지나면 B 뗌", rec.is_neutral())

    pad.sprint(True)
    time.sleep(MIN + 0.05)
    pad.neutral()
    check("오래 누른 뒤 neutral: 바로 전부 뗌", rec.is_neutral())

    pad.tap(control.B.XUSB_GAMEPAD_B, 0.06)
    check("tap(B): 눌림", b_down(rec))
    time.sleep(0.08)
    pad.release_due()
    check("tap(B): 0.06 s 뒤 뗌 (구르기는 그대로 짧게)", not b_down(rec))

    # nav.follow with a braked point every other step: sprint ↔ walk flips each ~0.1 s
    path = [(0.0, 0.0, float(i)) for i in range(8)]
    n0 = len(rec.sent)
    flips = {"n": 0}

    def mode(s):
        flips["n"] += 1
        return "sprint" if (flips["n"] // 2) % 2 == 0 else "walk"
    r = nav.follow(WalkTm(path), pad, path, mode_fn=mode)
    time.sleep(MIN)
    pad.release_due()
    hs = [round(h, 3) for h in holds(rec, n0)]
    check("follow: 도착", r == "arrived")
    check(f"follow 달리기↔걷기 반복: 짧은 B 없음 (B 누른 시간 {hs})", hs and min(hs) >= MIN - 0.03)
    pad.close()
    print("sprint_hold_test: 전부 통과")


if __name__ == "__main__":
    main()
