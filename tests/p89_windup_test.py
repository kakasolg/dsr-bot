"""P-89 (limited): 255041's 3004 is a windup (lands ~2.1 s) — the early counter at 1.6 s becomes a block. No game.

  python tests/p89_windup_test.py

Real scenes (tests/expect/scene_p89_*.json, from the 10-19 parish runs' .ctl.jsonl): the decision that preceded the −257 hits
(runs 2 · 3) and a control (run 1: 255041 really staggered, 3500). Then the same scene edited: past the landing, attack ended,
attack cancelled into a stagger, target switched to a foe without windup data — no shield held on, no other policy changed.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import copy
import json

import scene_replay as R
from souls import duel as D
from souls import foes

EXP = _pl.Path(__file__).resolve().parent / "expect"
T41, T42 = 472005904, 471999248                         # 255041 · 255042 in these runs


def scene(n: int) -> dict:
    return json.loads(next(EXP.glob(f"scene_p89_run{n}_*.json")).read_text(encoding="utf-8"))


def with_age(rec: dict, ptr: int, age: float) -> dict:
    r = copy.deepcopy(rec)
    r["reflex"]["start"]["_dict"] = [[p, ({"_t": -age} if p == ptr else v)] for p, v in r["reflex"]["start"]["_dict"]]
    r["reflex"]["age"] = age
    return r


def with_anim(rec: dict, ptr: int, anim: int) -> dict:
    r = copy.deepcopy(rec)
    for c in r["snap"]["chars"]:
        if c["ptr"] == ptr:
            c["anim"] = anim
    if r["tick"]["ptr"] == ptr:
        r["tick"]["a"] = anim
    return r


def test_entry_is_windup_only():
    f, u = foes.of(255041), foes.UNKNOWN
    assert f.windup == (3004,) and f.windup_act_s == 1.2 and f.windup_land_s == 2.1
    for k in ("kind", "kick_when_idle", "circle_behind", "ranged", "unblockable", "punish_hits", "kick_on_stagger", "early_kick",
              "singles", "combos", "avoid"):
        assert getattr(f, k) == getattr(u, k), k             # not SHIELD: nothing else differs from the default
    assert foes.of(255042) is foes.UNKNOWN                    # 255042 untouched (its bolts are a separate question)


def test_swing_over_for_255041_3004():
    f = foes.of(255041)
    assert not D.swing_over(f, 3004, 1.63) and not D.swing_over(f, 3004, 2.29)    # before landing + LAND_PAD: still swinging
    assert D.swing_over(f, 3004, 2.31)                                           # after: over, as before for other attacks
    assert D.swing_over(f, 3003, 1.63)                                           # other anims keep SWING_S
    assert D.swing_over(foes.UNKNOWN, 3004, 1.63)                                # foes without data: unchanged


def test_real_scenes_before_hit_now_block():
    for n in (2, 3):
        rec = scene(n)
        assert rec["rule"] == "after_swing" and rec["tick"]["a"] == 3004   # what the bot did then (pressed light, took −257)
        assert R.replay(rec) == "late_windup_block", n                     # now: shield up until it lands


def test_real_stagger_scene_still_counters():
    rec = scene(1)                                       # 255041 in 3500 (blocked 3001) — the counter stays
    assert rec["tick"]["a"] == 3500 and R.replay(rec) == "after_swing"


def test_no_shield_held_past_landing():
    rec = with_age(scene(3), T41, 2.4)                   # still 3004 on the read, but past 2.1 + LAND_PAD
    assert R.replay(rec) == "after_swing"


def test_attack_ended_or_cancelled_strikes():
    for a in (-1, 3500):                                 # 3004 → idle, 3004 → stagger (cancelled): the swing-end path
        rec = with_anim(scene(3), T41, a)
        rec["fight"]["_aprev"] = 3004
        assert R.replay(rec) == "after_swing", a


def test_target_switched_to_foe_without_windup():
    rec = scene(3)
    r = copy.deepcopy(rec)
    r["tick"] = {**r["tick"], "ptr": T42, "a": 3004}
    r = with_anim(with_age(r, T42, 1.63), T42, 3004)
    for c in r["snap"]["chars"]:
        if c["ptr"] == T41:
            c["anim"] = -1                               # the 255041 swing is out of the picture
    got = R.replay(r)
    assert got != "late_windup_block", got               # 255042 (UNKNOWN): no windup block


def main():
    test_entry_is_windup_only()
    test_swing_over_for_255041_3004()
    test_real_scenes_before_hit_now_block()
    test_real_stagger_scene_still_counters()
    test_no_shield_held_past_landing()
    test_attack_ended_or_cancelled_strikes()
    test_target_switched_to_foe_without_windup()
    print("ok  p89 windup (255041 3004)")


if __name__ == "__main__":
    main()
