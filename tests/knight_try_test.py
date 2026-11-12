"""knight_try.decide (v3) against MoKa's one-hand demo (M1111-87, observe 20261112_062835) — pure, no game.

Scenes are the demo's knight anim · anim time · distance at the moment MoKa acted (or stood still). This checks that the
rules give MoKa's choice in those scenes; it says nothing about the bot's timing or walking in the game.
"""
import knight_try as kt


def test_stood_out_of_reach_during_3002_window():
    # ① 3002 at 2.27 s (late window), MoKa at 4.0 m → nothing to dodge
    assert kt.decide(3002, 2.3, 4.1) == ("wait", None)


def test_walks_away_when_close_before_3002_late_window():
    # ③ 3002 just started, 1.3 m → walk away (2.27 s window leaves time to walk ~3 m)
    assert kt.decide(3002, 0.1, 1.3)[0] in ("away", "roll")
    assert kt.decide(3002, 1.2, 1.3)[0] == "away"


def test_rolls_when_walking_cannot_make_it():
    assert kt.decide(3002, 2.0, 1.3)[0] == "roll"


def test_punish_after_3002_window_with_time_left():
    # ① RB at 3.05 s into 3002 (2.3 s left) from ~2.8 m
    assert kt.decide(3002, 3.05, 2.5)[0] == "hit"
    assert kt.decide(3002, 3.05, 3.5)[0] == "step_in"


def test_punish_3003_with_1_2s_left_when_close():
    # ② RB at 2.46 s into 3003 (3.67 s long) — walked in from ~2.6 m
    assert kt.decide(3003, 2.46, 2.6)[0] == "hit"


def test_too_little_left_no_punish():
    assert kt.decide(3003, 2.46, 4.5) == ("wait", None)


def test_no_punish_after_3000_chain():
    # ④ MoKa went in after 3000 and 3001 followed → −227
    assert kt.decide(3000, 2.2, 2.5) == ("wait", None)


def test_3001_start_close_means_get_out():
    assert kt.decide(3001, 0.39, 2.0)[0] in ("away", "roll")


def test_walk_in_anim_hit_when_close():
    # ⑤ knight 3210 coming in, RB at 3.1 m landed at 1.2 m
    assert kt.decide(3210, None, 2.8) == ("hit_walkin", None)
    assert kt.decide(3210, None, 4.0) is None


def test_3005_lunge_far_reach():
    assert kt.decide(3005, 0.5, 6.0)[0] in ("away", "roll")


def test_plaza_box():
    assert kt.in_plaza(*kt.LURE[::2])
    assert not kt.in_plaza(10.7, 119.0)   # church interior (knight's spawn)
