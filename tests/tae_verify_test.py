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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
