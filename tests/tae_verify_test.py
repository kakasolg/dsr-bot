"""tae_verify offline test — small fake tae / combat tables and a fake probe recording.

  python tests/tae_verify_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import tae_verify as V

ANIMS = {
    "3000": {"tae": "c2540.tae", "events": [{"type": 1, "start": 0.8667, "end": 1.0333, "p": [0, 0, 100, 128]}],
             "other_types": {"0": 10, "128": 11}, "ref": None},
    "3009": {"tae": "c2540.tae", "events": [], "other_types": {}, "ref": 3000},       # borrows 3000
    "3500": {"tae": "c2540.tae", "events": [{"type": 5, "start": 0.0, "end": 0.2, "p": [0, 16, 0, 0]}],
             "other_types": {}, "ref": None},
}
TAE = {"models": {"c2540": {"model": "c2540", "animations": ANIMS}}}
COMBAT = {"foes": {"254010": {"model": "c2540"}, "999": {"model": "c9999"}}}


def test_resolve_and_windows():
    assert V.resolve(ANIMS, 3009) is ANIMS["3000"]
    assert [e["start"] for e in V.windows(ANIMS, 3009)] == [0.8667]
    assert V.windows(ANIMS, 3500) == [] and V.resolve(ANIMS, 1234) is None


def test_sheet():
    lines = V.sheet(TAE["models"]["c2540"], [3000, 3009, 1234])
    assert "프레임 26.0–31.0" in lines[1] and "p=[0, 0, 100, 128]" in lines[1]
    assert "빌림 → 3000" in lines[2] and lines[-1] == "1234: TAE에 없음"


def test_blame_check():
    rows = [{"blame": [{"npc": 254010, "anim": 3000}, {"npc": 254010, "anim": 3009}]},
            {"blame": [{"npc": 254010, "anim": 3500}, {"npc": 254010, "anim": 3040}, {"npc": 999, "anim": 1}]}]
    r = V.blame_check(TAE, COMBAT, rows)
    assert r["kinds"] == {"attack_anim": 2, "no_attack_event": 1, "anim_not_in_tae": 1, "no_model": 1}, r
    assert r["attack_share"] == 0.4 and r["samples"]["anim_not_in_tae"] == {"254010/c2540/3040": 1}
    assert V.blame_check(TAE, COMBAT, rows, "c2540")["rows"] == 4


def frame(t, hp, foes):
    return {"t": t, "hp": hp, "foes": [{"ptr": p, "npc": n, "anim": a, "d": d} for p, n, a, d in foes]}


def test_timing():
    fr = [frame(0.00, 500, [(1, 254010, 7000, 2.0)]),
          frame(0.10, 500, [(1, 254010, 3000, 2.0)]),         # 3000 starts at 0.10
          frame(1.00, 500, [(1, 254010, 3000, 1.5)]),
          frame(1.05, 420, [(1, 254010, 3000, 1.5)]),         # hit at age 0.95 — inside 0.8667–1.0333
          frame(1.60, 420, [(1, 254010, 3009, 1.5)]),         # borrowed 3000, starts 1.60
          frame(1.70, 380, [(1, 254010, 3009, 1.5)]),         # age 0.10 — outside
          frame(1.80, 300, [(1, 254010, 3500, 1.0)]),         # no attack window → no_attacker
          frame(1.90, 300, [(2, 254010, 3000, 9.0)])]
    r = V.timing(TAE, COMBAT, fr)
    assert r["hits"] == 3 and r["status"] == {"inside": 1, "outside": 1, "no_attacker": 1}, r
    a, b, c = r["rows"]
    assert a["age"] == 0.95 and a["anim"] == 3000 and a["windows"] == [(0.8667, 1.0333)] and a["dt"] == 0.05
    assert b["status"] == "outside" and b["age"] == 0.1
    assert c["foes"] == [(254010, 3500, 1.0)]


def test_timing_unknown_start():
    fr = [frame(0.0, 500, [(1, 254010, 3000, 2.0)]), frame(0.9, 400, [(1, 254010, 3000, 2.0)])]
    assert V.timing(TAE, COMBAT, fr)["rows"][0]["status"] == "unknown_start"      # anim already running at frame 0


def test_timing_anim_unknown_and_dt():
    """Probe 1 (10-16): both hollows in reach read anim −1 the whole time → anim_unknown, not no_attacker.
    A line's own `dt` (read interval) is the resolution, not the gap to the previous written line."""
    fr = [frame(0.0, 500, [(1, 254010, -1, 1.9)]), frame(3.1, 430, [(1, 254010, -1, 1.9)])]
    r = V.timing(TAE, COMBAT, fr)
    assert r["status"] == {"anim_unknown": 1} and r["rows"][0]["foes"] == [(254010, -1, 1.9)]
    fr = [frame(0.0, 500, [(1, 254010, 7000, 2.0)]), dict(frame(0.10, 500, [(1, 254010, 3000, 2.0)]), dt=0.004),
          dict(frame(1.05, 420, [(1, 254010, 3000, 1.5)]), dt=0.004)]
    row = V.timing(TAE, COMBAT, fr)["rows"][0]
    assert row["dt"] == 0.004 and row["status"] == "inside" and row["age"] == 0.95


def test_frame_key():
    a = V.frame_key(500, [{"ptr": 2, "anim": 3000, "d": 1.0}, {"ptr": 1, "anim": -1, "d": 4.0}])
    assert a == V.frame_key(500, [{"ptr": 1, "anim": -1, "d": 4.2}, {"ptr": 2, "anim": 3000, "d": 1.1}])   # distance alone: same
    assert a != V.frame_key(430, [{"ptr": 1, "anim": -1, "d": 4.0}, {"ptr": 2, "anim": 3000, "d": 1.0}])
    assert a != V.frame_key(500, [{"ptr": 1, "anim": -1, "d": 4.0}, {"ptr": 2, "anim": 3001, "d": 1.0}])


def test_dsas_compare_real_c2540():
    """Level 2 on the committed data: tae.json vs DSAnimStudio's reading of c2540 3000 / 3003 / 3010 ([win] 10-16).
    Passes now; the old fixed 4 × s32 read (p[3] from the next event) gives the 8 differences [win] found."""
    import copy, json
    tae = json.loads(V.TAE.read_text(encoding="utf-8"))["models"]["c2540"]
    dsas = json.loads((V.ROOT / "data" / "gamefiles" / "tae_check_c2540_dsas.json").read_text(encoding="utf-8"))
    r = V.dsas_compare(tae, dsas)
    assert r["pass"] and [x["anim"] for x in r["rows"]] == [3000, 3003, 3010], r["diffs"][:3]
    old = copy.deepcopy(tae)
    for a in ("3000", "3003", "3010"):
        for ev in old["animations"][a]["events"]:
            if ev["type"] == 1:
                ev["p"] = ev["p"] + [128]
    bad = V.dsas_compare(old, dsas)["diffs"]
    assert len(bad) == 8 and {d["what"] for d in bad} == {"params"}, bad


def test_dsas_compare_catches_time_and_count():
    dsas = {"anims": [{"anim": 3000, "events": [
        {"type": 1, "start": 0.8666667, "end": 1.04, "params": {"AttackType": "0", "AttackIndex": "0", "BehaviorJudgeID": "100"}},
        {"type": 0, "start": 0.0, "end": 1.0, "params": {}}]}, {"anim": 4000, "events": []}]}
    r = V.dsas_compare(TAE["models"]["c2540"], dsas)
    whats = [d["what"] for d in r["diffs"]]
    assert not r["pass"] and "end" in whats and "event count" in whats and "other types" in whats
    assert "missing in tae.json" in whats and "start" not in whats            # 0.8667 vs 0.8666667 is within tol


# ── probe 3 (c2540 3000, one isolated hollow) ──
def f3(t, hp, foes, gap=0.003, **kw):
    """A probe3 line: read ran t−0.001 … t, the previous read began `gap` before t."""
    return {"t0": t - 0.001, "t": t, "pt0": t - gap, "hp": hp, "dbg": "01" + "00" * 15,
            "foes": [{"ptr": p, "npc": n, "anim": a, "d": d} for p, n, a, d in foes], **kw}


def run3(t0, hit_age, anim=3000, end=1.2, hp=(500, 420), others=(), extra_hit=None):
    """One 3000 run starting at t0 (from 7000), one HP drop at hit_age, back to 7000 after `end` s."""
    me = lambda a: [(1, 254010, a, 1.5), *others]
    out = [f3(t0 - 0.5, hp[0], me(7000)), f3(t0, hp[0], me(anim)), f3(t0 + hit_age, hp[1], me(anim))]
    if extra_hit is not None:
        out.append(f3(t0 + extra_hit, hp[1] - 10, me(anim)))
    return out + [f3(t0 + end, out[-1]["hp"], me(7000))]


def test_timing3_match_mismatch_and_bounds():
    lines = [{"kind": "header", "probe": 3}] + run3(10, 0.95) + run3(20, 0.30) + run3(30, 1.06) + run3(40, 1.10)
    r = V.timing3(TAE, COMBAT, lines)
    assert r["samples"] == 4 and r["valid"] == 4 and r["match"] == 2 and r["mismatch"] == 2, r
    early, late = r["rows_mismatch"]
    assert early["age_since_seen"] == [0.297, 0.303] and early["offset"] == -0.5304   # before 0.8667 − 1 frame
    assert late["offset"] == 0.0304                                                   # after 1.0333 + 1 frame
    edge = [h for h in r["rows_match"] if h["t"] == 31.06][0]                         # within the 1-frame allowance
    assert edge["obs_width"] == 0.003 and r["verdict"] == "불일치" and r["runs"]["closed"] == 4


def test_timing3_exclusions():
    hollow2 = (2, 254010, 7000, 3.0)
    crossbow = (3, 255002, -1, 11.9)
    friend = (4, 100000, -1, 15.0)
    lines = (run3(10, 0.95, others=(hollow2,))                 # second hollow → not_isolated
             + run3(20, 0.95, others=(crossbow,))              # crossbow, even at anim −1 → not_isolated
             + run3(30, 0.95, others=(friend,))                # friendly NPC does not count → valid
             + run3(40, 0.95, anim=3001)                       # other animation: out of scope
             + run3(50, 0.90, extra_hit=0.95)                  # two drops in one run: restart not ruled out
             + run3(60, 0.95) + run3(70, 0.95))
    lines[-1:-1] = [f3(70.5, 420, [(1, 254010, 3000, 1.5)], gap=0.05)]
    r = V.timing3(TAE, COMBAT, lines)
    assert r["excluded"] == {"not_isolated": 2, "other_anim": 1, "multi_hit_in_run": 2}, r["excluded"]
    assert r["valid"] == 3 and r["verdict"] == "표본 부족"
    lines = [f3(0.0, 500, [(1, 254010, 3000, 1.5)]), f3(0.9, 400, [(1, 254010, 3000, 1.5)]), f3(1.2, 400, [(1, 254010, 7000, 1.5)])]
    assert V.timing3(TAE, COMBAT, lines)["excluded"] == {"start_unseen": 1}     # running when the record began
    lines = run3(10, 0.95)
    lines[1]["pt0"] = 10 - 0.2                                                   # start bounded only within 0.2 s
    lines[2]["pt0"] = lines[2]["t"] - 0.05
    assert V.timing3(TAE, COMBAT, lines)["rows_excluded"][0]["reasons"][:2] == ["start_gap", "restart_unchecked"]
    lines = run3(10, 0.95)[:3]                                                   # recording ends inside the run
    assert V.timing3(TAE, COMBAT, lines)["excluded"] == {"run_open": 1}
    lines = run3(10, 0.95)
    lines[2]["refill"] = 793
    assert "refill_in_run" in V.timing3(TAE, COMBAT, lines)["rows_excluded"][0]["reasons"]


def test_timing3_restart_possible():
    lines = run3(10, 0.9) + run3(20, 0.9) + run3(30, 0.9) + run3(40, 0.9, end=2.5)  # 2.5 s > 1.5 × median 1.2
    r = V.timing3(TAE, COMBAT, lines)
    assert r["valid"] == 3 and r["excluded"] == {"restart_possible": 1}


def test_precheck():
    good = [{"kind": "header"}] + [f3(i * 0.5, 700, [(1, 254010, 3000 if i % 2 else 7000, 1.5), (4, 100000, -1, 9.0)])
                                    for i in range(10)]
    pc = V.precheck(good, 5, 120)
    assert pc["ok"], pc
    bad = [f3(i * 0.5, 1, [(1, 254010, -1, 1.5), (2, 254010, -1, 2.0), (3, 255002, -1, 12.0)], dbg="01" + "00" * 11 + "01" + "00" * 3)
           for i in range(10)]
    pc = V.precheck(bad, 5, 120, max_lines=100)
    failed = {c["check"] for c in pc["checks"] if not c["ok"]}
    assert failed == {"hp", "target_one", "target_awake", "isolated", "dbg_flags", "volume"}, pc
    assert "AllNoMove" in [c for c in pc["checks"] if c["check"] == "dbg_flags"][0]["detail"]
    assert V.dbg_on("01" + "00" * 15) == ["PlayerNoDead"]


def test_anim_runs_restart_after_leaving():
    fr = [f3(0, 500, [(1, 254010, 3000, 1.0)]), f3(1, 500, []), f3(2, 500, [(1, 254010, 3000, 1.0)])]
    runs = V.anim_runs(fr)[1]
    assert [(r["start"], r["end"]) for r in runs] == [(None, None), (None, None)]   # gone then back: neither end is seen


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
