"""ctl links (ctlspan.py, run.py --ctl-spans) — the span records must not change any decision or pad report. No game.
python tests/ctl_spans_test.py

Checks:
  · duel golden: every situation gives the same trace with spans on, with the sink raising on every put, with a full
    queue, and with ctlspan's own id counter broken — and nothing is left open on the thread afterwards
  · duel golden, spans on: one start and one end per cycle and fight, every cycle's parent is its fight, every span.rule's
    parent is an open cycle and its rule is the cycle's picked one; rules that returned None get no span.rule
  · real Moves on the fake pad (kick ×2, backstep inside a cycle; CamFollow-like and GuardKeep-like threads writing the
    pad meanwhile): action start / end pairs with parent and end reason, Hit copied; main-thread pad records carry the
    cycle id (and the action id inside an action); other threads' records carry no main id
  · control.Pad on the fake device: the same scripted calls give the same device reports with spans on and off;
    keep_guard holding LB through guard(False) / neutral() writes one pad.override each
Prints the linkage ratios (MoKa 10-30 request, verification 2).
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import gzip
import itertools
import json
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import ctl
import ctlspan
import pad_fakes
from field_fakes import World

import duel_golden_test as G
from souls import moves as M


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def golden() -> dict:
    return {json.dumps(sc, sort_keys=True): G.run(sc)
            for sc in itertools.chain(G.situations(), G.situations_terrain(), G.situations_axe())}


def left_open() -> bool:
    return bool(getattr(ctlspan._tl, "stack", None)) or getattr(ctlspan._tl, "cycle", None) is not None


class _Boom:
    alive = True

    def put(self, k, f):
        raise RuntimeError("sink broken (test)")


def test_golden(tmp: Path) -> None:
    want = json.loads(gzip.decompress(G.GOLDEN.read_bytes()).decode("utf-8"))
    same = lambda got: not [k for k in want if got.get(k) != want[k]]

    ctl.QUEUE_MAX = 3_000_000
    path = tmp / "golden.ctl.jsonl"
    ctl.start(path, run="t", argv=["x"], cmd="test")
    ctlspan.ON = True
    got = golden()
    ctlspan.ON = False
    ctl.flush(300.0)                                              # let the writer catch up (stop() alone waits 2 s)
    summ = ctl.stop()
    ctl.QUEUE_MAX = 20000
    check(f"golden: 기록 잃음·버림 0 (쓴 줄 {summ['written']})", summ["lost"] == 0 and summ["dropped"] == 0)
    check(f"golden: spans 켬 — {len(want)}개 상황 판단 trace 전부 같음", same(got))
    check("golden: 끝난 뒤 이 스레드에 열린 fight·cycle 없음", not left_open())
    r = rows(path)
    fights = [x for x in r if x["k"] == "span.fight"]
    cyc = [x for x in r if x["k"] == "span.cycle"]
    rules = [x for x in r if x["k"] == "span.rule"]
    fs = {x["fight_id"] for x in fights if x["ev"] == "start"}
    fe = {x["fight_id"] for x in fights if x["ev"] == "end"}
    cs = {x["cycle_id"]: x for x in cyc if x["ev"] == "start"}
    ce = {x["cycle_id"]: x for x in cyc if x["ev"] == "end"}
    check(f"golden: fight 시작·끝 짝 ({len(fs)}개)", fs == fe and len(fs) == sum(1 for x in fights if x["ev"] == "start"))
    check(f"golden: cycle 시작·끝 짝 ({len(cs)}개), parent = fight", cs.keys() == ce.keys()
          and all(x["parent"] in fs for x in cs.values()) and all(ce[k]["parent"] == cs[k]["parent"] for k in cs))
    by_rule = {x["rule_id"]: x for x in rules}
    ok_parent = sum(1 for x in rules if x["parent"] in cs)
    check(f"golden: span.rule {len(rules)}개 모두 parent가 cycle, 그 cycle의 picked·rule_id와 같음",
          ok_parent == len(rules) and all(ce[x["parent"]]["picked"] == x["rule"] and ce[x["parent"]]["rule_id"] == x["rule_id"]
                                          for x in rules))
    kinds = {}
    for x in ce.values():
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
    picked = [x for x in ce.values() if x["picked"] is not None]
    check("golden: picked가 있는 cycle마다 span.rule 하나 (None 돌려준 규칙은 기록 없음)",
          all(x["rule_id"] in by_rule for x in picked) and len(picked) == len(rules))
    check("golden: span.rule 순서 enter ≤ ret", all(x["enter_pc"] <= x["ret_pc"] for x in rules))
    nonepad = sum(len(x["none_pad"]) for x in ce.values())
    print(f"     cycle 끝 종류 {kinds}; None 돌려준 규칙 호출 {sum(x['none_n'] for x in ce.values())}회 "
          f"(그중 패드 출력 {nonepad} — 가짜 Moves라 패드 기록 없음)")
    print(f"     span.rule parent 있음 {ok_parent}/{len(rules)}")

    for label, setup in (("sink가 put마다 예외", lambda: setattr(ctl, "_sink", _Boom())),
                         ("큐 가득 참 (put마다 Full)", None),
                         ("ctlspan id 카운터 고장", None)):
        if label.startswith("큐"):
            ctl.start(tmp / "full.ctl.jsonl", run="t", argv=["x"], cmd="test")

            def full(rec):
                raise queue.Full
            ctl._sink.q.put_nowait = full                             # every put finds the queue full (test only)
        elif label.startswith("ctlspan"):
            ctl.start(tmp / "ids.ctl.jsonl", run="t", argv=["x"], cmd="test")
            ctlspan._ids = iter(())                                   # next() raises inside ctlspan
        else:
            setup()
        ctlspan.ON = True
        got = golden()
        ctlspan.ON = False
        dropped = None
        if isinstance(ctl._sink, _Boom):
            ctl._sink = ctl._Off()
        else:
            dropped = ctl._sink.dropped
            ctl.stop()
        if label.startswith("큐"):
            check(f"golden: 큐 가득 참 — 버린 기록 {dropped}개 (호출자 쪽에서)", dropped and dropped > 100000)
        ctl.QUEUE_MAX = 20000
        ctlspan._ids = itertools.count(1)
        ctlspan._tl.__dict__.clear()
        check(f"golden: {label} — 판단 trace 전부 같음", same(got))


class Tm:
    def __init__(self, w):
        self.w = w

    def snapshot(self, within=60.0):
        return self.w.snapshot(within)


def test_moves_on_pad(tmp: Path) -> None:
    pad_fakes.install(tmp)
    pad = control.Pad()
    w = World()
    foe = w.add(2, 0x1002, 254000, (0.0, -49.4, 1.0), hp=60)
    mv = M.Moves(Tm(w), pad)
    path = tmp / "moves.ctl.jsonl"
    ctl.QUEUE_MAX = 200000
    ctl.start(path, run="t", argv=["x"], cmd="test")
    ctlspan.ON = True
    stop = threading.Event()

    def cam():                                                    # CamFollow-like: right stick from its own thread
        while not stop.is_set():
            pad.look(0.2, 0.0)
            pad.look(0.0, 0.0)
            time.sleep(0.01)

    def keeper():                                                 # GuardKeep-like
        while not stop.is_set():
            pad.keep_guard(time.time() + 0.05)
            time.sleep(0.03)
            pad.unkeep()

    th = [threading.Thread(target=cam, name="cam-test"), threading.Thread(target=keeper, name="keep-test")]
    for t in th:
        t.start()
    fight = ctlspan.Fight(foe.ptr)
    fight.cycle_start()
    fight.rule_enter()
    w.hidden.add(foe.ptr)                                         # gone from the list on the first watch read
    h1 = mv.kick(w.snapshot(), foe)
    w.hidden.clear()
    fight.rule_return("kick_test", "continue")
    fight.cycle_end("rule_cont", "kick_test")
    fight.cycle_start()
    fight.rule_enter()
    foe.hp = 0
    mv.kick(w.snapshot(), foe)
    mv.backstep()
    pad.move(0.3, 0.3)                                            # outside any action, inside the cycle
    fight.rule_return("two_test", "continue")
    fight.cycle_end("rule_cont", "two_test")
    fight.end(None)
    pad.move(0.0, 0.0)                                            # after the fight: no ids
    stop.set()
    for t in th:
        t.join()
    ctlspan.ON = False
    ctl.flush(30.0)
    ctl.stop()
    ctl.QUEUE_MAX = 20000
    pad.close()
    r = rows(path)
    acts = [x for x in r if x["k"] == "span.action"]
    st = {x["action_id"]: x for x in acts if x["ev"] == "start"}
    en = {x["action_id"]: x for x in acts if x["ev"] == "end"}
    check(f"moves: span.action 시작·끝 짝 {len(st)}개 (kick, kick, backstep)", st.keys() == en.keys()
          and [x["action"] for x in st.values()] == ["kick", "kick", "backstep"])
    with_parent = sum(1 for x in st.values() if x["parent"] is not None and x["rule_id"] is not None)
    check("moves: 끝난 이유 gone · dead · returned", [en[k]["end"] for k in st] == ["gone", "dead", "returned"])
    check("moves: Hit 원본 복사 (kind·dmg·e_anims·my_anims·presses·others)",
          en[list(st)[0]]["hit"]["kind"] == h1.kind and isinstance(en[list(st)[0]]["hit"]["my_anims"], list)
          and {"dmg", "taken", "presses", "others", "e_anims"} <= set(en[list(st)[0]]["hit"]))
    sr = [x for x in r if x["k"] == "span.rule"]
    check("moves: span.rule first_action_pc·first_pad_pc가 enter와 ret 사이",
          all(x["enter_pc"] <= x["first_action_pc"] <= x["ret_pc"] and x["enter_pc"] <= x["first_pad_pc"] <= x["ret_pc"]
              for x in sr))
    main = [x for x in r if x["k"] in ("pad", "pad.drop") and x["th"] == "MainThread"]
    other = [x for x in r if x["k"] in ("pad", "pad.drop", "pad.override") and x["th"] != "MainThread"]
    cyc_ids = {x["cycle_id"] for x in r if x["k"] == "span.cycle"}
    in_fight = [x for x in main if x.get("cycle_id") is not None]
    in_act = [x for x in main if x.get("action_id") is not None]
    check("moves: 싸움 밖(마지막 move) 메인 패드 기록엔 id 없음", "cycle_id" not in main[-1])
    check("moves: 메인 패드 기록의 cycle_id는 모두 열린 cycle", all(x["cycle_id"] in cyc_ids for x in in_fight))
    check("moves: action 안 메인 패드 기록의 action_id는 그 action", all(x["action_id"] in st for x in in_act))
    wrong = [x for x in other if x.get("cycle_id") is not None or x.get("action_id") is not None]
    check(f"moves: 다른 스레드 패드 기록 {len(other)}개에 메인 id 0개", not wrong and len(other) > 0)
    print(f"     span.action parent 있음 {with_parent}/{len(st)}; 메인 스레드 pad 기록 중 id 붙음 {len(in_fight)}/{len(main)} "
          f"(싸움 밖 기록 포함, action_id {len(in_act)}); 다른 스레드에 잘못 붙은 id {len(wrong)}")


def _script(pad) -> None:
    pad.move(0.5, 0.2)
    pad.guard(True)
    pad.tap(control.B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.0)
    pad.release_due()
    pad.keep_guard(time.time() + 60)
    pad.guard(False)                                              # kept: LB stays
    pad.neutral()                                                 # kept: LB pressed again
    pad.force_guard = False
    pad.unkeep()
    pad.look(0.1, 0.0)
    pad.neutral()


def test_pad_same_reports(tmp: Path) -> None:
    vg = pad_fakes.install(tmp)
    off = control.Pad()
    _script(off)
    rep_off = [{k: v for k, v in x.items() if k != "th"} for x in vg.devices[-1].sent]
    off.close()
    path = tmp / "pad.ctl.jsonl"
    ctl.start(path, run="t", argv=["x"], cmd="test")
    ctlspan.ON = True
    on = control.Pad()
    f = ctlspan.Fight(None)
    f.cycle_start()
    _script(on)
    f.cycle_end("no_rule")
    f.end(None)
    ctlspan.ON = False
    ctl.stop()
    rep_on = [{k: v for k, v in x.items() if k != "th"} for x in vg.devices[-1].sent]
    on.close()
    check(f"pad: 같은 호출 → 장치 보고 같음 (spans 끔/켬, {len(rep_off)}개)", rep_off == rep_on and rep_off)
    ov = [x for x in rows(path) if x["k"] == "pad.override"]
    check("pad: keep_guard가 LB를 붙잡은 guard(False)·neutral() → pad.override 둘, cycle_id 붙음",
          [x["m"] for x in ov] == ["guard_off", "neutral"] and all(x.get("cycle_id") for x in ov))


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="ctlspans_"))
    test_pad_same_reports(tmp)
    test_moves_on_pad(tmp)
    test_golden(tmp)
    check("끝: ctl 꺼짐, spans 꺼짐", not ctl.on() and not ctlspan.ON)
    print("ctl_spans_test: 전부 통과")


if __name__ == "__main__":
    main()
