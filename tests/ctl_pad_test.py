"""P1-B: pad / neutral / freeze records — real control.Pad on a fake vgamepad, no game, no device.
python tests/ctl_pad_test.py

Checks:
  · on/off equivalence: the same input script sends exactly the same reports, in the same order, with ctl off and on
  · every report write is accounted for: Σ(1 + dup) over pad / pad.drop records + the pending fold = update() calls
  · a changed report is never folded: consecutive pad records always differ; repeats only raise dup
  · pad record fields: method, caller outside control.py (quitout._press shows as quitout.py), report ints, epoch, up_us
  · while another thread holds the freeze: pad.drop records (frz = that thread), nothing reaches the device
  · neutral records: why (when given), call site, epoch, the report left on the device; release_all / close too
  · esc records for freeze / refused freeze / unfreeze / ignored unfreeze; pad_dev unplug / plug on reconnect
  · off: no record calls at all, and recording overhead per input stays small (temporary bound)
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import sys
import tempfile
import threading
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import ctl
import pad_fakes
import quitout

A, X, LB = "XUSB_GAMEPAD_A", "XUSB_GAMEPAD_X", "XUSB_GAMEPAD_LEFT_SHOULDER"
B = control.B


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def script(pad: control.Pad) -> dict:
    """A fixed input sequence touching every report-writing method. Returns what the test needs afterwards."""
    pad.move(0.5, 0.3)
    pad.move(0.5, 0.3)                       # identical report → folded
    pad.move(0.5, 0.3)
    pad.look(0.2, 0.0)
    pad.hold(B.XUSB_GAMEPAD_LEFT_SHOULDER, True)
    pad.tap(B.XUSB_GAMEPAD_A, 0.005, stick_ok=True)
    time.sleep(0.02)
    pad.release_due()
    pad.press(B.XUSB_GAMEPAD_X, 0.002)
    quitout._press(pad, B.XUSB_GAMEPAD_Y, gap=0.0, min_gap=0.0)
    pad._r2(0.002)
    pad.kick(0.0, 1.0)
    time.sleep(0.08)
    pad.release_due()
    pad.neutral()
    pad.neutral(why="arrived")
    pad.jump_attack((0.0, 1.0), hold=0.002)
    # another thread holds the freeze: three moves here go nowhere
    held, go = threading.Event(), threading.Event()
    refused = {}

    def freezer():
        pad.freeze()
        held.set()
        go.wait(5)
        pad.unfreeze()

    t = threading.Thread(target=freezer, name="frz")
    t.start()
    held.wait(5)
    for _ in range(3):
        pad.move(1.0, 0.0)
    refused["take_false"] = pad.freeze(take=False)   # someone else holds it → refused
    pad.unfreeze()                                   # not the holder → ignored
    go.set()
    t.join(5)
    pad.move(0.1, 0.1)
    pad.release_all()
    pad.reconnect()
    pad.move(-0.2, 0.4)
    pad.close()
    return refused


def run(tmp: Path, on: bool):
    vg = pad_fakes.install(tmp)
    path = tmp / ("on.ctl.jsonl" if on else "off.ctl.jsonl")
    if on:
        ctl.start(path, run="t", argv=["x"], cmd="test")
    pad = control.Pad()
    refused = script(pad)
    pending = pad._ctl_fold
    if on:
        ctl.stop()
    sent = [[{k: v for k, v in s.items()} for s in rec.sent] for rec in vg.devices]
    return sent, (rows(path) if on else []), pending, refused, pad


def test_equivalence_and_records(tmp: Path) -> None:
    check("시작: ctl 꺼짐", not ctl.on())
    sent_off, _, _, ref_off, _ = run(tmp / "off", on=False)
    check("꺼짐: ctl 파일 없음", not (tmp / "off" / "off.ctl.jsonl").exists())
    sent_on, r, pending, ref_on, pad = run(tmp / "on", on=True)
    check("켜기/끄기: 장치가 받은 보고·순서가 완전히 같음", sent_off == sent_on)
    check("켜기/끄기: freeze(take=False) 결과 같음 (둘 다 거절)", ref_off == ref_on == {"take_false": False})

    pads = [x for x in r if x["k"] == "pad"]
    drops = [x for x in r if x["k"] == "pad.drop"]
    n_sent = sum(len(s) for s in sent_on)
    n_drop = 3
    check("모든 보고 쓰기가 셈에 들어감: Σ(1+dup) + 남은 접힘 = update 수 + 버려진 수",
          sum(1 + x["dup"] for x in pads + drops) + pending == n_sent + n_drop)
    reps = [(x["btn"], x["lt"], x["rt"], x["lx"], x["ly"], x["rx"], x["ry"]) for x in pads]
    seq = sorted(pads + drops, key=lambda x: x["seq"])
    consecutive_same = any(a["k"] == b["k"] == "pad" and b["m"] != "reconnect" and
                           (a["btn"], a["lt"], a["rt"], a["lx"], a["ly"], a["rx"], a["ry"]) ==
                           (b["btn"], b["lt"], b["rt"], b["lx"], b["ly"], b["rx"], b["ry"]) for a, b in zip(seq, seq[1:]))
    check("바뀐 보고는 접히지 않음: 이어진 pad 기록끼리 값이 늘 다름 (새 장치의 첫 보고만 예외)",
          not consecutive_same and len(set(reps)) > 5)
    moves = [x for x in pads if x["m"] == "move"]
    check("같은 move 세 번 → 기록 하나 + 다음 기록의 dup 2",
          moves and moves[0]["lx"] == round(0.5 * 32767) and
          next(x for x in seq if x["seq"] > moves[0]["seq"])["dup"] == 2)
    check("pad 기록 필드: m·caller·보고 정수·ep·up_us·frz",
          all({"m", "caller", "btn", "lt", "rt", "lx", "ly", "rx", "ry", "ep", "up_us", "frz", "dup"} <= set(x) for x in pads)
          and all(isinstance(x["up_us"], int) and x["up_us"] >= 0 for x in pads))
    check("caller는 control.py 밖 (이 테스트 파일)", all(not x["caller"].startswith("control.py") for x in pads)
          and any(x["caller"].startswith("ctl_pad_test.py:script:") for x in pads))
    check("quitout._press 경로: caller = quitout.py:_press", any(x["caller"].startswith("quitout.py:_press:") for x in pads))
    check("트리거: r2 → rt 255, 놓으면 0", any(x["m"] == "r2" and x["rt"] == 255 for x in pads)
          and any(x["m"] == "r2_release" and x["rt"] == 0 for x in pads))
    frz_th = [x for x in r if x["k"] == "esc" and x["ev"] == "freeze" and x["ok"]]
    check("얼린 동안: pad.drop 기록 하나(move) + 접힌 2번, frz = 얼린 스레드",
          len(drops) == 1 and drops[0]["m"] == "move" and drops[0]["frz"] == frz_th[0]["holder"]
          and next(x for x in seq if x["seq"] > drops[0]["seq"])["dup"] == 2)
    check("얼린 동안 장치엔 move(1,0)가 안 감", all(not (s["lx"] == 1.0 and s["ly"] == 0.0) for dev in sent_on for s in dev))
    esc = [(x["ev"], x["ok"]) for x in r if x["k"] == "esc"]
    check("esc: freeze ok → freeze 거절 → unfreeze 무시 → unfreeze ok",
          esc == [("freeze", True), ("freeze", False), ("unfreeze", False), ("unfreeze", True)])
    neu = [x for x in r if x["k"] == "neutral"]
    whys = [x["why"] for x in neu]
    check("neutral 기록: 처음(Pad 생성) → None, why='arrived', release_all, close",
          whys[0] is None and "arrived" in whys and "release_all" in whys and whys[-1] == "close")
    arrived = next(x for x in neu if x["why"] == "arrived")
    check("neutral: site = 부른 곳, ep 증가, 남은 보고가 중립",
          arrived["site"].startswith("ctl_pad_test.py:script:") and arrived["ep"] > neu[0]["ep"]
          and arrived["report"]["btn"] == 0 and arrived["report"]["lx"] == 0)
    dev = [x["ev"] for x in r if x["k"] == "pad_dev"]
    check("reconnect: pad_dev unplug → plug, 새 장치 보고는 m=reconnect",
          dev == ["unplug", "plug"] and any(x["m"] == "reconnect" for x in pads))
    check("close 뒤 pad 상태: 닫힘", pad._closed)


def test_off_overhead(tmp: Path) -> None:
    """Off: _record never runs. On: per-input cost stays small (temporary bound, not a policy constant)."""
    pad_fakes.install(tmp / "oh")
    pad = control.Pad()
    calls = []
    orig = control.Pad._record
    control.Pad._record = lambda self, *a: calls.append(a)
    for _ in range(200):
        pad.move(0.3, 0.3)
    control.Pad._record = orig
    check("꺼짐: _record 한 번도 안 불림", calls == [])
    N = 3000

    def timed() -> float:
        t0 = time.perf_counter()
        for i in range(N):
            pad.move((i % 7) / 10, 0.2)
        return (time.perf_counter() - t0) / N
    off = timed()
    ctl.start(tmp / "oh.ctl.jsonl", run="t", argv=["x"], cmd="test")
    on = timed()
    ctl.stop()
    pad.close()
    extra_us = (on - off) * 1e6
    print(f"     입력 한 번: 꺼짐 {off * 1e6:.1f} µs, 켜짐 {on * 1e6:.1f} µs (+{extra_us:.1f} µs)")
    check("켜짐: 입력 한 번에 더해지는 시간 < 200 µs (임시 상한)", extra_us < 200)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="ctlpad_"))
    for d in ("off", "on"):
        (tmp / d).mkdir()
    test_equivalence_and_records(tmp)
    test_off_overhead(tmp)
    print("ctl_pad_test: 전부 통과")


if __name__ == "__main__":
    main()
