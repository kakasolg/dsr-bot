"""duel_sim offline test — data wiring on the committed tae.json / combat.json, the lua tables, and the frame loop.

  python tests/duel_sim_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import random
from collections import Counter

import duel_sim as S

W = S.load_windows()


def test_windows_from_files():
    assert W[3000] == [(0.8667, 1.0333, 110, 0)]                      # tae window + combat.json power (judge 100)
    assert len(W[3010]) == 6 and {d for _s, _e, d, _i in W[3010]} == {98} and [i for *_, i in W[3010]] == [0, 1, 2, 2, 2, 2]
    assert set(W) == set(S.REACH)


def test_pick_act_bands():
    rng = random.Random(0)
    near = Counter(S.pick_act(1.0, rng) for _ in range(20000))
    assert set(near) == {1, 2, 3} and abs(near[2] / 20000 - 0.5) < 0.02 and abs(near[1] / 20000 - 0.2) < 0.02
    far = Counter(S.pick_act(9.0, rng) for _ in range(20000))
    assert abs(far[7] / 20000 - 0.4) < 0.02 and 5 not in far          # act 5 (firebomb) has weight 0


def test_act_chains():
    rng = random.Random(1)
    chains = Counter(tuple(S.act_chain(3, 2.0, rng)[1][1]) for _ in range(20000))
    assert abs(chains[(3003,)] / 20000 - 0.20) < 0.02 and abs(chains[(3003, 3004)] / 20000 - 0.35) < 0.02
    assert S.act_chain(1, 5.0, rng) == [("approach", 2.0, 4.0), ("attack", [3010]), 100]
    assert S.act_chain(7, 3.0, rng)[1] == ("attack", [3005])             # closer than 5.7: always the short lunge
    try:
        S.act_chain(5, 3.0, rng)
    except ValueError:
        pass
    else:
        raise AssertionError("act 5 is outside the slice")


def test_after_attack_odds():
    rng = random.Random(2)
    kinds = Counter((S.after_attack(rng) or [("none",)])[0][0] for _ in range(20000))
    assert abs(kinds["none"] / 20000 - 0.75) < 0.02 and abs(kinds["step"] / 20000 - 0.08) < 0.015


def test_episode_deterministic_and_hit_rules():
    a = S.episode(W, S.p_stand, seed=7, secs=10)
    assert a == S.episode(W, S.p_stand, seed=7, secs=10)
    # a 3010 against a still target in reach: 6 windows → 6 hits (window) or 3 AttackIndex values → 3 (index)
    for rule, n in (("window", 6), ("index", 3)):
        foe = S.Foe(windows=W, rng=random.Random(0), hit_rule=rule)
        S.start_anim(foe, 3010, lambda m: None)
        hits = []
        for _ in range(int(3.5 / S.DT)):
            if foe.anim is None:
                break
            _d, h = S.step(foe, 1.6, lambda m: None)
            hits += h
        assert len(hits) == n, (rule, hits)


def test_guard_and_back_off_policies():
    g = S.episode(W, S.p_guard_on_swing, seed=3, secs=20)
    assert g["taken"] == 0 and all(h["blocked"] for h in g["hits"])    # ASSUME: guard blocks all physical damage
    s = S.episode(W, S.p_stand, seed=3, secs=20)
    assert s["taken"] > 0 and s["hits"][0]["anim"] in S.REACH


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
