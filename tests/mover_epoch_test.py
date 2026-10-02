"""P0-D: nav.Mover follows the real report — Pad.epoch changes on neutral/freeze/unfreeze/reconnect/close, and Mover then
forgets what it thinks it holds so the next set() presses it again. Real control.Pad on a fake vgamepad.
python tests/mover_epoch_test.py

Checks:
  · guard / sprint: neutral() wipes LB / B → the next set() presses it again (before: Mover kept guard_on=True, LB stayed off)
  · freeze from another thread: what the Mover pressed meanwhile went nowhere → after unfreeze set() presses it for real
  · reconnect: the new device gets the mode's buttons on the next set()
  · Mover.stop(): its own neutral — no extra presses afterwards
  · nav.follow over two points in guard mode: goto's arrival neutral drops LB, the second point holds it again
  · a pad without epoch (walksim.SimPad shape) never resyncs
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
import tempfile
import threading
import types
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import nav
import pad_fakes
from telemetry import Chr, Snapshot

LB, BB = "XUSB_GAMEPAD_LEFT_SHOULDER", "XUSB_GAMEPAD_B"


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def btns(rec) -> set:
    return rec.last().get("buttons", set())


class WalkTm:
    """Player stands at the path point it was last sent toward after a few ticks (arrival), so follow() runs point by point."""

    def __init__(self, path):
        self.path, self.i, self.ticks = path, 0, 0

    def snapshot(self, within: float = 40.0):
        self.ticks += 1
        if self.ticks % 4 == 0 and self.i < len(self.path):
            self.i += 1
        x, y, z = ([(0.0, 0.0, -3.0)] + list(self.path))[min(self.i, len(self.path))]   # start, then each point in turn
        p = Chr(1, 0, 1, 500, 500, x, y, z, gx=x, gy=y, gz=z, heading=0.0)
        return Snapshot(t=0.0, player=p, chars=[], cam_yaw=0.0)


def main() -> None:
    vg = pad_fakes.install(Path(tempfile.mkdtemp(prefix="epoch_")))
    pad = control.Pad()
    rec = vg.devices[-1]
    mv = nav.Mover(pad)

    mv.set("guard")
    check("guard: LB 눌림", LB in btns(rec))
    pad.neutral()
    check("neutral: LB 떨어짐", LB not in btns(rec))
    mv.set("guard")
    check("neutral 뒤 set('guard'): LB 다시 눌림", LB in btns(rec) and mv.guard_on)

    mv.set("sprint")
    check("sprint: B 눌림, LB 뗌", BB in btns(rec) and LB not in btns(rec))
    pad.neutral()
    mv.set("sprint")
    check("neutral 뒤 set('sprint'): B 다시 눌림", BB in btns(rec))

    # freeze held by another thread: our presses go to _NullPad
    pad.neutral()
    frozen, release = threading.Event(), threading.Event()

    def holder():
        pad.freeze()
        frozen.set()
        release.wait(5)
        pad.neutral()
        pad.unfreeze()
    th = threading.Thread(target=holder, name="escape")
    th.start()
    frozen.wait(5)
    n0 = len(rec.sent)
    mv.set("guard")
    check("얼린 동안 set('guard'): 실제 보고엔 안 감", len(rec.sent) == n0 and LB not in btns(rec))
    release.set()
    th.join(5)
    mv.set("guard")
    check("unfreeze 뒤 set('guard'): LB 실제로 눌림", LB in btns(rec))

    # reconnect
    pad.reconnect()
    rec2 = vg.devices[-1]
    check("reconnect: 새 장치는 중립", rec2 is not rec and rec2.is_neutral())
    mv.set("guard")
    check("reconnect 뒤 set('guard'): 새 장치에 LB", LB in btns(rec2))

    # stop() is the Mover's own neutral — no resync presses afterwards
    mv.stop()
    n0 = len(rec2.sent)
    mv.set("walk")
    check("stop 뒤 set('walk'): 아무것도 안 누름", len(rec2.sent) == n0 and rec2.is_neutral())

    # nav.follow, guard mode, two points: arrival neutral between them
    path = [(0.0, 0.0, 0.0), (0.0, 0.0, 3.0)]
    seen_lb: list = []
    r = nav.follow(WalkTm(path), pad, path, mode_fn=lambda s: "guard",
                   on_tick=lambda s, d: seen_lb.append((round(s.player.gz, 1), LB in btns(rec2))))
    second = [lb for z, lb in seen_lb if z == 0.0][1:]          # ticks spent walking to the second point
    check("follow: 둘 다 도착", r == "arrived")
    check("follow: 두 번째 점으로 가는 동안 LB 다시 듦 (도착 neutral 뒤)", second and second[-1])
    check("follow 끝: 중립", rec2.is_neutral())

    # pads without epoch: never resync (walksim.SimPad)
    calls: list = []
    sim = types.SimpleNamespace(sprint=lambda on: calls.append(("sprint", on)), guard=lambda on: calls.append(("guard", on)),
                                neutral=lambda: calls.append(("neutral",)), jump=lambda: None)
    m2 = nav.Mover(sim)
    m2.set("guard")
    m2.set("guard")
    check("epoch 없는 패드: 예전 그대로 (guard 한 번만)", calls.count(("guard", True)) == 1)
    pad.close()
    print("mover_epoch_test: 전부 통과")


if __name__ == "__main__":
    main()
