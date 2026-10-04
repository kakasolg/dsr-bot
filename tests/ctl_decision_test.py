"""P1-C: decision records (nav.goto, Field._walk retreat, Reflex.tick, duel rules) — recording must not change any decision.
python tests/ctl_decision_test.py

Checks:
  · duel: every golden situation (tests/duel_golden.json.gz) gives the same decisions with ctl ON; dec.rule records exist,
    rules outside FOLD_RULES (attacks, backstab, estus, kicks …) are always single (n = 1)
  · Field._walk_mode: same four checks, same order, same short-circuit (no _chaser call once threat_now is true), same
    return off and on; the record names the check that fired
  · nav.goto via nav.follow on a fake pad: same reports to the device and same result off and on; start / mode-change /
    end records with one gid per goto, a mode record only when the mode changes, end = the returned value ('retreat' too)
  · Reflex.tick on a scripted foe: same return values and same moves off and on; a dec.reflex record when (act, target)
    changes, a new burst after a quiet tick is recorded again
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import gzip
import itertools
import json
import sys
import tempfile
import types
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import ctl
import nav
import pad_fakes
from telemetry import Chr, Snapshot

import duel_golden_test as G
from souls import duel as D
from souls import field as Fld
from souls.reflex import Reflex


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def on(path: Path) -> None:
    ctl.start(path, run="t", argv=["x"], cmd="test")


def test_duel_golden_with_ctl_on(tmp: Path) -> None:
    ctl.QUEUE_MAX = 2_000_000                         # keep every record for the checks below (test only)
    path = tmp / "duel.ctl.jsonl"
    on(path)
    got = {json.dumps(sc, sort_keys=True): G.run(sc)
           for sc in itertools.chain(G.situations(), G.situations_terrain(), G.situations_axe())}
    summ = ctl.stop()
    ctl.QUEUE_MAX = 20000
    want = json.loads(gzip.decompress(G.GOLDEN.read_bytes()).decode("utf-8"))
    bad = [k for k in want if got.get(k) != want[k]]
    check(f"duel: 기록 켠 채 golden {len(want)}개 상황 판단이 전부 같음 (다른 것 {len(bad)})", not bad)
    r = [x for x in rows(path) if x["k"] == "dec.rule"]
    names = {f.__name__.removeprefix("rule_").removeprefix("prep_") for f in D.RULES}
    check("dec.rule: 기록이 있고 규칙 이름은 RULES 안의 것만", r and {x["rule"] for x in r} <= names)
    single = [x for x in r if x["rule"] not in D.FOLD_RULES]
    check("공격·뒤잡기·에스트 등 접지 않는 규칙은 늘 n = 1",
          single and all(x["n"] == 1 for x in single) and {"attack", "backstab"} & {x["rule"] for x in single})
    check("접는 규칙(block 등)은 n ≥ 1, 하나라도 2 이상 (같은 규칙 연속이 접힘)",
          all(x["n"] >= 1 for x in r if x["rule"] in D.FOLD_RULES) and any(x["n"] > 1 for x in r))
    check("dec.rule 필드: rule·ptr·out·snap_t·snap_age_ms·n", all({"rule", "ptr", "out", "snap_t", "snap_age_ms", "n"} <= set(x) for x in r))
    check("버린 기록 없음", summ["dropped"] == 0)


class WalkSelf:
    """Just what Field._walk_mode reads, with every call logged in order."""

    def __init__(self, threat, chaser, escaping, gen):
        self.calls = []
        me = self
        self.reflex = types.SimpleNamespace(threat_now=lambda sn: (me.calls.append("threat_now"), threat)[1])
        self._chaser_v = chaser
        self.esc = types.SimpleNamespace(escaping=escaping, gen=gen)

    def _chaser(self, sn, ignore):
        self.calls.append("_chaser")
        return self._chaser_v


def test_walk_mode(tmp: Path) -> None:
    foe = types.SimpleNamespace(ptr=0xAB, npc_param=250023)
    st = types.SimpleNamespace(ignore=set())
    sn = types.SimpleNamespace(t=12.5)
    cases = [  # (threat, chaser, escaping, gen) → (return, calls, reason)
        ((True, foe, True, 1), ("retreat", ["threat_now"], "threat")),
        ((False, foe, True, 1), ("retreat", ["threat_now", "_chaser"], "chaser")),
        ((False, None, True, 0), ("retreat", ["threat_now", "_chaser"], "escaping")),
        ((False, None, False, 1), ("retreat", ["threat_now", "_chaser"], "gen")),
        ((False, None, False, 0), ("walk", ["threat_now", "_chaser"], None)),
    ]
    for mode_on in (False, True):
        path = tmp / f"walk_{mode_on}.ctl.jsonl"
        if mode_on:
            on(path)
        outs = []
        for args, (want_r, want_calls, _) in cases:
            me = WalkSelf(*args)
            r = Fld.Field._walk_mode(me, sn, st, 0, "walk")
            outs.append((r, me.calls))
            check(f"_walk_mode {'켜짐' if mode_on else '꺼짐'} {args[:1]}…: 반환 {want_r}, 호출 순서 {want_calls}",
                  r == want_r and me.calls == want_calls)
        if mode_on:
            ctl.stop()
            rec = [x for x in rows(path) if x["k"] == "dec.walk_retreat"]
            check("dec.walk_retreat: 물러남 넷 → 기록 넷, 이유 threat·chaser·escaping·gen",
                  [x["reason"] for x in rec] == ["threat", "chaser", "escaping", "gen"])
            check("chaser 이유엔 ptr·npc, 나머지엔 None", rec[1]["ptr"] == 0xAB and rec[1]["npc"] == 250023
                  and rec[0]["ptr"] is None and rec[0]["snap_t"] == 12.5)


class WalkTm:
    """The player reaches the point it was sent to after a few ticks (like tests/mover_epoch_test.py)."""

    def __init__(self, path):
        self.path, self.i, self.ticks = path, 0, 0

    def snapshot(self, within: float = 40.0):
        self.ticks += 1
        if self.ticks % 6 == 0 and self.i < len(self.path):
            self.i += 1
        x, y, z = ([(0.0, 0.0, -3.0)] + list(self.path))[min(self.i, len(self.path))]
        p = Chr(1, 0, 1, 500, 500, x, y, z, gx=x, gy=y, gz=z, heading=0.0)
        return Snapshot(t=float(self.ticks), player=p, chars=[], cam_yaw=0.0)


def goto_run(tmp: Path, rec_on: bool):
    vg = pad_fakes.install(tmp)
    path = tmp / "goto.ctl.jsonl"
    if rec_on:
        on(path)
    pad = control.Pad()
    pts = [(0.0, 0.0, 0.0), (0.0, 0.0, 3.0)]
    tick = itertools.count()
    # walk for 2 ticks, then guard: one mode change per point (plus the first mode)
    tm1, tm2 = WalkTm(pts), WalkTm([(0.0, 0.0, 5.0)])
    r1 = nav.follow(tm1, pad, pts, mode_fn=lambda s: "walk" if next(tick) % 6 < 2 else "guard")
    r2 = nav.goto(tm2, pad, (0.0, 0.0, 5.0), mode_fn=lambda s: "retreat")
    pad.close()
    if rec_on:
        ctl.stop()
    return [list(d.sent) for d in vg.devices], (r1, r2), (rows(path) if rec_on else []), tm1.ticks + tm2.ticks


def test_goto(tmp: Path) -> None:
    (tmp / "g0").mkdir()
    (tmp / "g1").mkdir()
    sent0, res0, _, _ = goto_run(tmp / "g0", False)
    sent1, res1, r, ticks = goto_run(tmp / "g1", True)
    check("goto: 켜기/끄기 결과 같음 (arrived, retreat)", res0 == res1 == ("arrived", "retreat"))
    check("goto: 켜기/끄기 때 장치가 받은 보고·순서 같음", sent0 == sent1)
    g = [x for x in r if x["k"] == "dec.goto"]
    starts = [x for x in g if x["ev"] == "start"]
    ends = [x for x in g if x["ev"] == "end"]
    check("goto 세 번 → start 셋·end 셋, gid로 짝지어짐",
          len(starts) == len(ends) == 3 and [x["gid"] for x in starts] == [x["gid"] for x in ends])
    check("end = 돌려준 값: arrived, arrived, retreat", [x["ret"] for x in ends] == ["arrived", "arrived", "retreat"])
    for s in starts:
        modes = [x for x in g if x["ev"] == "mode" and x["gid"] == s["gid"]]
        check(f"gid {s['gid']}: mode 기록은 바뀔 때만 (이어진 둘이 같은 mode 아님), prev = 앞 mode",
              modes and all(a["mode"] != b["mode"] and b["prev"] == a["mode"] for a, b in zip(modes, modes[1:]))
              and modes[0]["prev"] is None)
    n_mode = len([x for x in g if x["ev"] == "mode"])
    check(f"mode 기록 {n_mode}개 < goto 틱 {ticks}개 (틱마다 쓰지 않음)", n_mode < ticks / 2)
    check("start: 목표·허용 거리", starts[0]["tgt"] == [0.0, 0.0, 0.0] and starts[0]["tol"] == 1.0)


class RMv:
    def __init__(self):
        self.t = []
        me = self
        self.pad = types.SimpleNamespace(guard=lambda v: me.t.append(("guard", v)), move=lambda x, y: me.t.append(("move", x, y)))

    def face(self, s, c, deg=20.0):
        self.t.append(("face", c.ptr))
        return True


def reflex_run(tmp: Path, rec_on: bool):
    path = tmp / "reflex.ctl.jsonl"
    if rec_on:
        on(path)
    mv = RMv()
    rf = Reflex(mv)
    player = Chr(1, 0, 1, 500, 500, 0.0, 0.0, 0.0, sp=90, max_sp=100, gx=0.0, gy=0.0, gz=0.0, heading=0.0)
    low = Chr(1, 0, 1, 500, 500, 0.0, 0.0, 0.0, sp=10, max_sp=100, gx=0.0, gy=0.0, gz=0.0, heading=0.0)

    def snap(anim, p=player, t=0.0):
        foe = Chr(0x77, 250023, 6, 100, 100, 0.0, 0.0, 1.5, anim=anim, dist=1.5)
        return Snapshot(t=t, player=p, chars=[foe])
    outs = [rf.tick(snap(3003, t=1.0)), rf.tick(snap(3003, t=2.0)), rf.tick(snap(-1, t=3.0)),
            rf.tick(snap(3004, t=4.0)), rf.tick(snap(3005, low, t=5.0))]
    if rec_on:
        ctl.stop()
    return outs, mv.t, (rows(path) if rec_on else [])


def test_reflex(tmp: Path) -> None:
    out0, mv0, _ = reflex_run(tmp, False)
    out1, mv1, r = reflex_run(tmp, True)
    check("reflex: 켜기/끄기 반환 같음 (막음, 막음, 없음, 막음, 마주봄)", out0 == out1 == [True, True, False, True, True])
    check("reflex: 켜기/끄기 패드·얼굴 돌리기 호출 같음", mv0 == mv1)
    d = [x for x in r if x["k"] == "dec.reflex"]
    check("dec.reflex: guard(첫 공격) → [같은 것 반복 안 씀] → guard(조용한 틱 뒤 새로) → face(스태미나 낮음)",
          [x["act"] for x in d] == ["guard", "guard", "face"] and all(x["ptr"] == 0x77 for x in d))
    check("dec.reflex 필드: eanim·npc·age·snap_t", d[0]["eanim"] == 3003 and d[0]["npc"] == 250023
          and isinstance(d[0]["age"], float) and d[0]["snap_t"] == 1.0)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="ctldec_"))
    test_walk_mode(tmp)
    test_reflex(tmp)
    test_goto(tmp)
    test_duel_golden_with_ctl_on(tmp)
    check("끝: ctl 꺼짐", not ctl.on())
    print("ctl_decision_test: 전부 통과")


if __name__ == "__main__":
    main()
