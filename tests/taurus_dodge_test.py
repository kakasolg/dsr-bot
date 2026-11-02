"""taurus.Taurus._back_up — on the way back to the ladder it rolls just before a swing lands, not when it starts. No game.

20261101_002546: rolled at the start of 3012 (1.4 s early) and was hit after the roll; a 3005 that started during the roll
cool-down was never dodged (−233), then a 3004 leap from 9 m killed it. Blackbox 60 Hz: start → hit per anim is steady
(taurus.HIT_AT), and the game's own anim clock (DSRTelemetry.anim_time) tells where in the swing it is.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("BOT_GAME", "dsr")

from souls import taurus as T  # noqa: E402

DT = 0.05                                       # anim time per snapshot read


def run(script, anim_time=True):
    """script: list of (boss anim, boss distance) per read; the boss anim clock runs DT per read and restarts on a new anim.
    The player stands 3.2 m from the ladder foot, so the loop ends by BACK_S (fake clock)."""
    clock = {"t": 1000.0}
    st = {"i": 0, "anim": None, "at": 0.0, "rolls": [], "x": 46.0}

    def now():
        return clock["t"]

    def snap(r=40.0):
        clock["t"] += DT
        i = min(st["i"], len(script) - 1)
        st["i"] += 1
        a, h = script[i]
        st["at"] = st["at"] + DT if a == st["anim"] else 0.0
        st["anim"] = a
        boss = NS(npc_param=T.TAURUS, hp=500, ptr=7, anim=a, x=st["x"] - h, y=15.82, z=-117.1, heading=0.0)
        return NS(player=NS(x=st["x"], y=15.82, z=-117.1, hp=600, max_hp=742, heading=0.0, anim=-1), chars=[boss],
                  cam_yaw=0.0)

    tm = NS(anim_time=lambda p: st["at"]) if anim_time else NS()
    tb = T.Taurus.__new__(T.Taurus)
    tb.log, tb.events = (lambda *a, **k: None), (lambda *a, **k: None)
    tb.nm, tb.tm = None, tm
    tb.pad = NS(sprint=lambda on: None, move=lambda x, y: None, release_due=lambda: None, neutral=lambda: None)
    tb.mv = NS(snap=snap, stick_to=lambda s, x, z, sc=1.0: (sc, 0.0),
               roll_toward=lambda s, x, z, hold=False: st["rolls"].append((st["anim"], round(st["at"], 2))))
    tb.f = NS(alive=lambda: True)
    tb.ms = NS(_before=lambda *a, **k: "ok")
    tb._over = lambda s: None
    real_time = T.time.time
    T.time.time, T.time.sleep = now, (lambda s: clock.__setitem__("t", clock["t"] + s))
    try:
        tb._back_up(1)
    finally:
        T.time.time, T.time.sleep = real_time, __import__("time").sleep
    return st["rolls"]


def test_known_swing_rolls_just_before_it_lands_not_at_the_start():
    rolls = run([(-1, 3.0)] * 3 + [(3005, 2.0)] * 40 + [(-1, 3.0)] * 400)
    assert len(rolls) == 1 and rolls[0][0] == 3005, rolls
    assert T.HIT_AT[3005] - T.ROLL_LEAD - 0.01 <= rolls[0][1] < T.HIT_AT[3005], rolls


def test_swing_that_started_during_a_roll_is_still_dodged():
    # 002546 74.58: 3005 began while the bot was busy; first read already 0.6 s in — still one roll before it lands
    script = [(3005, 2.0)] * 40 + [(-1, 3.0)] * 400
    rolls = run(script)
    assert len(rolls) == 1 and rolls[0][1] >= T.HIT_AT[3005] - T.ROLL_LEAD - 0.01, rolls


def test_leap_from_far_is_dodged_but_far_ordinary_swing_is_not():
    assert len(run([(-1, 9.0)] * 2 + [(3004, 9.0)] * 45 + [(-1, 9.0)] * 400)) == 1
    assert run([(-1, 9.0)] * 2 + [(3005, 9.0)] * 45 + [(-1, 9.0)] * 400) == []


def test_unknown_swing_rolls_at_once_as_before():
    rolls = run([(-1, 2.0)] * 2 + [(3012, 1.4)] * 30 + [(-1, 3.0)] * 400)
    assert rolls and rolls[0] == (3012, 0.0), rolls


def test_no_anim_clock_falls_back_to_time_since_seen():
    rolls = run([(-1, 3.0)] * 3 + [(3002, 2.0)] * 40 + [(-1, 3.0)] * 400, anim_time=False)
    assert len(rolls) == 1 and rolls[0][0] == 3002, rolls


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
    print("ok")
