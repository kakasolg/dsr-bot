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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
