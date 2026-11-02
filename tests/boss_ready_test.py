"""boss_ready — entry checks before Taurus and the post-Taurus path, as fakes (no game, no pad).  python tests/boss_ready_test.py

  · burg-altar: Taurus alive / kill confirmed (HP 0 in two snapshots, or the kill flag once one is known) / unknown (not seen,
    snapshot failed) — only a confirmed kill goes on; run.main('burg-altar') stopped → no zones, no fog, no pad input
  · taurus: crossbows alive / both dead / not observable · resin none / bag only / quick slot · chest flag set but 0 resin ·
    read failures stay 'unknown' (never 0 or killed) · Taurus.run stopped → no move, attack or item use
[MoKa] 2026-10-31: "전제 미충족 또는 확인 불가이면 중단·보고" (10-31 155929: burg-altar walked onto the bridge with Taurus alive).
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import boss_ready as B
from telemetry import Chr, Snapshot

fails = 0


def check(name, ok):
    global fails
    print(("ok  " if ok else "FAIL") + "  " + name)
    if not ok:
        fails += 1


ME = Chr(ptr=1, npc_param=0, team=1, hp=700, max_hp=700, x=52.07, y=17.21, z=-118.55)
CB1, CB2 = B.crossbow_spots()


def foe(ptr, npc, pos, hp):
    return Chr(ptr=ptr, npc_param=npc, team=6, hp=hp, max_hp=max(hp, 1), x=pos[0], y=pos[1], z=pos[2])


def snap(*chars):
    return Snapshot(t=time.time(), player=ME, chars=list(chars))


TAURUS_PERCH = (-6.7, 27.0, -110.4)


class Tm:
    """goods_count / quick_items / event_flag / snapshot — None = read failed. Records every call (reads only exist here)."""

    def __init__(self, goods=None, quick=(205, 311, -1, -1, -1), flags=None, ss=None):
        self.goods = {205: 5, B.RESIN: 3} if goods is None else goods
        self.quick, self.flags, self.ss = quick, flags or {}, list(ss or [])
        self.calls = []

    def goods_count(self, i):
        self.calls.append("goods_count")
        if self.goods == "fail":
            return None
        return self.goods.get(i, 0)

    def quick_items(self):
        self.calls.append("quick_items")
        return list(self.quick) if self.quick is not None else []

    def event_flag(self, fid):
        self.calls.append(("event_flag", fid))
        return self.flags.get(fid)

    def snapshot(self, within=0.0):
        return self.ss.pop(0) if len(self.ss) > 1 else (self.ss[0] if self.ss else None)


both_dead = [snap(foe(11, 255002, CB1, 0), foe(12, 255002, CB2, 0))] * 2

# ── burg-altar ──────────────────────────────────────────────────────────────
v = B.altar(Tm(), [snap(foe(9, 225000, TAURUS_PERCH, 1215))] * 2)
check("altar: Taurus alive on its perch → stop, points at burg-upper 1-8 → taurus",
      not v.ok and "살아 있음" in v.stop[0] and B.ORDER in v.stop[0])
v = B.altar(Tm(), [snap(foe(9, 225000, TAURUS_PERCH, 0))] * 2)
check("altar: same Taurus at HP 0 in both snapshots → kill confirmed, go", v.ok)
v = B.altar(Tm(), [snap(foe(9, 225000, TAURUS_PERCH, 0)), snap()])
check("altar: HP 0 once, then gone → not confirmed, stop", not v.ok)
v = B.altar(Tm(), [snap(), snap()])
check("altar: not in the snapshot → unknown, stop (not seen ≠ killed)", not v.ok and "확인 불가" in v.stop[0]
      and v.facts["타우로스 스냅숏"] == "unseen")
v = B.altar(Tm(), [None, snap()])
check("altar: a snapshot read failed → unknown, stop", not v.ok and v.facts["타우로스 스냅숏"] == "unknown")
check("altar: kill flag unknown → recorded as such, not read", "기록 번호 모름" in v.facts["타우로스 처치 기록"])
keep = B.TAURUS_KILLED_FLAG
try:
    B.TAURUS_KILLED_FLAG = 12345678
    check("altar: once a kill flag is known and set → go", B.altar(Tm(flags={12345678: True}), [snap(), snap()]).ok)
    check("altar: kill flag read fails → stop", not B.altar(Tm(flags={}), [snap(), snap()]).ok)
finally:
    B.TAURUS_KILLED_FLAG = keep

# ── taurus: crossbows ───────────────────────────────────────────────────────
v = B.taurus(Tm(), both_dead)
check("taurus: both crossbows dead, resin 3 in a quick slot, Estus 5 → ready", v.ok and v.facts["석궁병"] == "dead / dead")
v = B.taurus(Tm(), [snap(foe(11, 255002, CB1, 0), foe(12, 255002, CB2, 85))] * 2)
check("taurus: one crossbow alive → stop (zone 8 first)", not v.ok and any("살아 있음" in s for s in v.stop))
v = B.taurus(Tm(), [snap(), snap()])
check("taurus: crossbows not observed → unknown, stop (not seen ≠ killed)",
      not v.ok and v.facts["석궁병"] == "unseen / unseen" and any("확인 불가" in s for s in v.stop))
v = B.taurus(Tm(), [snap(foe(11, 255002, CB1, 0)), snap(foe(11, 255002, CB1, 0))])
check("taurus: one dead, the other not seen → stop", not v.ok and v.facts["석궁병"] == "dead / unseen")
far = (CB1[0] + 20.0, CB1[1], CB1[2])
v = B.taurus(Tm(), [snap(foe(11, 255002, far, 85))] * 2)
check("taurus: a crossbow far from the tower doesn't count for its spot", v.facts["석궁병"] == "unseen / unseen")

# ── taurus: resin ───────────────────────────────────────────────────────────
v = B.taurus(Tm(goods={205: 5}, quick=(205, -1, -1, -1, -1)), both_dead)
check("taurus: no resin, no chest record → stop, asks MoKa about the door/chest",
      not v.ok and v.facts["송진 개수"] == 0 and any("MoKa 확인" in s for s in v.stop))
v = B.taurus(Tm(goods={205: 5, B.RESIN: 2}, quick=(205, -1, -1, -1, -1)), both_dead)
check("taurus: resin in the bag only → stop (no auto equip)",
      not v.ok and v.facts["송진 퀵슬롯"] == "없음" and any("가방에만" in s for s in v.stop))
v = B.taurus(Tm(goods={205: 5}, quick=(205, 311, -1, -1, -1), flags={B.RESIN_CHEST_FLAG: True}), both_dead)
check("taurus: chest record set but resin 0 → stop 'used up', each fact recorded",
      not v.ok and v.facts["송진 상자 기록"] == "있음" and v.facts["송진 개수"] == 0 and v.facts["송진 퀵슬롯"] == "있음"
      and any("다 씀" in s for s in v.stop))
v = B.taurus(Tm(flags={B.RESIN_CHEST_FLAG: False}), both_dead)
check("taurus: chest flag read and recorded (없음) — resin held, still ready", v.ok and v.facts["송진 상자 기록"] == "없음")
check("taurus: door state can't be read → '확인 불가'", "확인 불가" in v.facts["송진 문"])

# ── taurus: read failures stay unknown ─────────────────────────────────────
v = B.taurus(Tm(goods="fail"), both_dead)
check("taurus: goods read failed → resin and Estus 'unknown', not 0",
      not v.ok and v.facts["송진 개수"] == "확인 불가" and v.facts["에스트"] == "확인 불가")
v = B.taurus(Tm(quick=None), both_dead)
check("taurus: quick slots unreadable → stop, not 'not in slot'", not v.ok and v.facts["송진 퀵슬롯"] == "확인 불가")
v = B.taurus(Tm(goods={B.RESIN: 3}), both_dead)
check("taurus: Estus 0 → stop", not v.ok and v.facts["에스트"] == 0)
check("Verdict.line: says stop and the reasons", B.taurus(Tm(goods={B.RESIN: 3}), both_dead).line().startswith("멈춤 — "))

# ── Taurus.run: stopped → no move, attack or item use ───────────────────────
from souls import taurus as T


class Pad:
    def __init__(self):
        self.calls = []

    def __getattr__(self, k):
        return lambda *a, **kw: self.calls.append(k)


def taurus_run(tm, before="dead"):
    pad, done = Pad(), []
    mv = NS(tm=tm, pad=pad, estus_left=lambda: 5, select_item=lambda i, *a: done.append("select_item") or True,
            estus_id=lambda: 205)
    f = NS(mv=mv, alive=lambda: True, esc=NS(quit_ok=True, nudge_ok=True, gen=0),
           heal=lambda *a, **k: done.append("heal"), ignore_npcs=set())
    ms = NS(_before=lambda *a, **k: done.append("_before") or before)
    evs = []
    r = T.Taurus(f, None, ms, log=lambda *a: None, events=lambda *a, **k: evs.append((a, k))).run()
    return r, pad.calls, done, evs


r, pc, done, evs = taurus_run(Tm(goods={205: 5}, quick=(205, -1, -1, -1, -1), ss=[snap(), snap()]))
check("Taurus.run unready → '멈춤: …', no pad input, no fog walk, no heal, no item select",
      r.startswith("멈춤") and pc == [] and done == [])
ready = [e for e in evs if e[1].get("what") == "ready"]
check("Taurus.run: 'ready' event with ok False, reasons and facts", ready and ready[0][1]["ok"] is False
      and ready[0][1]["stop"] and "송진 개수" in ready[0][1]["facts"])
r, pc, done, evs = taurus_run(Tm(ss=both_dead), before="dead")
check("Taurus.run ready → goes on to the fog wall (existing _before)", done[:1] == ["_before"] and r == "died")

# ── run.py burg-altar: stopped before zones / fog / pad ─────────────────────
import run_stop_test as RS
import run
from souls import afterdeath

tmp = Path(tempfile.mkdtemp(prefix="bossready_"))
RS.install(tmp)
seen = []
afterdeath.run_zones = lambda *a, **k: seen.append("run_zones") or "cleared"
RS.FakeMissions.to_altar_bridge = lambda self: seen.append("to_altar_bridge") or "ok"
RS.FakeMissions.upper_segment = lambda self, n: seen.append("upper_segment") or "cleared"
RS.FakeTm.snapshot = lambda self, within=0.0: snap(foe(9, 225000, TAURUS_PERCH, 1215))
RS.TRACE.clear()
sys.argv = ["run.py", "burg-altar"]
run.main()
CLEANUP = {"pad.create", "pad.unkeep"}            # run.main always creates the pad and lets go of a kept guard on the way out
pad_in = [x for x in RS.TRACE if isinstance(x, str) and x.startswith("pad.") and x not in CLEANUP]
check("run burg-altar, Taurus alive → no zones, no fog walk", seen == [])
check("run burg-altar, Taurus alive → no pad input besides neutral / cleanup", pad_in == [])
evs = [json.loads(l) for f in (tmp / "data" / "runs").glob("*_burg-altar.jsonl") for l in f.read_text(encoding="utf-8").splitlines()]
rd = [e for e in evs if e.get("ev") == "ready"]
check("run burg-altar: 'ready' event ok False with the reason", rd and rd[-1]["ok"] is False and "살아 있음" in rd[-1]["stop"][0])
logs = [l for f in (tmp / "data" / "runs").glob("*_burg-altar.log") for l in f.read_text(encoding="utf-8").splitlines()]
check("run burg-altar: result line says 멈춤", any("══ 결과: 멈춤" in l for l in logs))

RS.FakeTm.snapshot = lambda self, within=0.0: None
seen.clear()
run.main()
check("run burg-altar, snapshot unreadable → also stops before anything", seen == [])

# ── run.py burg-altar: confirmed kill → the normal path still runs (zones → fog → altar) ──────────────
from souls import altar as altar_mod
altar_mod.Altar = lambda *a, **k: NS(run=lambda: seen.append("altar.run") or "arrived")
from souls import watch as watch_mod


class FakeBlood:                                  # run_stop_test's stand-in has no .read (burg-altar passes Blood.read on)
    read = staticmethod(lambda: None)

    def __init__(self, *a, **k): pass
    def start(self): return NS(stop=lambda: None)


watch_mod.Blood = FakeBlood
RS.FakeTm.snapshot = lambda self, within=0.0: snap(foe(9, 225000, TAURUS_PERCH, 0))
seen.clear()
RS.TRACE.clear()
run.main()
check("run burg-altar, Taurus at HP 0 in both snapshots → zones, fog and altar all run (normal path not blocked)",
      seen == ["run_zones", "to_altar_bridge", "altar.run"])
evs = [json.loads(l) for f in (tmp / "data" / "runs").glob("*_burg-altar.jsonl") for l in f.read_text(encoding="utf-8").splitlines()]
check("run burg-altar, confirmed kill → 'ready' event ok True", [e for e in evs if e.get("ev") == "ready"][-1]["ok"] is True)

# ── MoKa's raw recording: dead foes stay in the snapshot at HP 0 (same session, 30 m) ─────────────────
# Source: data/observe/20261006_173431.jsonl (MoKa's observe_record.py recording, not in git, 31 630 280 bytes,
# sha256 64b3f9756bd0efff27428a90dc0d97bb4136b0a559f883d12b7d1d7bdb10f74c), k="w" world frames at line 24002 (ms 400005.2) and
# line 24010 (ms 400113.6), epoch 0, header radius_m 30. Fields taken per 255002 entity: id (h:10004062#0 · h:10004063#0), ptr,
# pos (rounded to 0.01), hp_raw. Each frame below is extracted on its own; at this rounding the values match, only the recorded
# player distance d differed (9.09 → 9.06 m, 13.33 → 13.31 m: MoKa moved, the corpses didn't). MoKa stood near the
# ladder foot (48.97, 15.87, −117.13). The two died at 383.2 / 377.3 s and stayed at hp_raw 0 until the recording ended (578.5 s).
# Only this distance, map and session were seen — no claim about other distances, reloads or rests.
REC = [
    {"line": 24002, "ms": 400005.2, "foes": [(465625760, (52.6, 23.84, -119.56), 0), (465632416, (59.51, 23.8, -115.22), 0)]},
    {"line": 24010, "ms": 400113.6, "foes": [(465625760, (52.6, 23.84, -119.56), 0), (465632416, (59.51, 23.8, -115.22), 0)]},
]
rec = [snap(*(foe(p, 255002, q, hp) for p, q, hp in fr["foes"])) for fr in REC]
check("recording: two distinct source frames (lines 24002 → 24010, 108.4 ms apart)",
      [fr["line"] for fr in REC] == [24002, 24010] and REC[0]["ms"] < REC[1]["ms"])
check("recording: a dead crossbow at HP 0 in two frames → 'dead' (not seen ≠ dead, but HP 0 kept = dead)",
      B.life(rec, B.CROSSBOW, CB1) == "dead")
check("recording: track-style filter (HP > 0 only) would show nothing — that absence proves nothing",
      [c for s in rec for c in s.hostile(12.0)] == [])
# 두 번째 시체는 스폰 자리에서 7.9 m (59.5, −115.2) — 스폰 6 m 규칙이면 "unseen"으로 멈췄다 → 탑 위 전체에서 센다
# ([MoKa] 10-31 "규칙 변경 진행")
check("recording: second corpse 7.9 m off its spawn still counts (tower-wide) → 'dead / dead' → taurus ready",
      B.crossbows(rec, [CB1, CB2]) == ["dead", "dead"] and B.taurus(Tm(), rec).ok)
fell = (CB1[0], CB1[1] - 8.0, CB1[2] + 2.0)
check("tower rule: a corpse that fell off the tower (8 m lower) doesn't count → stop",
      B.crossbows([snap(foe(11, 255002, CB1, 0), foe(12, 255002, fell, 0))] * 2, [CB1, CB2]) == ["dead", "unseen"])
check("tower rule: the same corpse in both snapshots counts once, not as two",
      B.crossbows([snap(foe(11, 255002, CB1, 0))] * 2, [CB1, CB2]) == ["dead", "unseen"])
check("tower rule: one alive anywhere on the tower top → 'alive' → stop",
      B.crossbows([snap(foe(11, 255002, (59.51, 23.8, -115.22), 0), foe(12, 255002, (60.0, 23.8, -124.0), 85))] * 2,
                  [CB1, CB2]) == ["alive", "alive"])
check("tower rule: HP 0 in one snapshot, gone in the next → not counted", B.crossbows(
    [snap(foe(11, 255002, CB1, 0), foe(12, 255002, CB2, 0)), snap(foe(11, 255002, CB1, 0))], [CB1, CB2]) == ["dead", "unseen"])

if fails:
    print(f"boss_ready_test: {fails} 실패")
    raise SystemExit(1)
print("boss_ready_test: 전부 통과")
