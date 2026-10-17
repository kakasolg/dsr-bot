"""options_pilot: the gate sends each option's input at τ, the check counts reps and decides (fake game, no pad, no game)."""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))
import math

import options_pilot as O


class FakeAct:
    """Moves the fake player: circles 1.5 m/s along the tangent, a roll 2.5 m in 0.5 s (no damage while rolling)."""

    def __init__(self, game):
        self.g, self.calls = game, []

    def start(self, opt, s, ptr):
        self.calls.append(("start", opt, self.g["t"]))
        self.g["mode"], self.g["since"] = opt, self.g["t"]
        return {"in": "none" if opt == "stand" else opt}

    def steer(self, opt, s, ptr):
        self.calls.append(("steer", opt))

    def stop(self):
        if self.g["mode"].startswith("circle"):
            self.g["mode"] = "stand"

    def tick(self):
        pass

    def rehome(self, s):
        self.g["p"] = [0.0, 0.0, 0.85]
        self.g["mode"] = "stand"
        return {"home": [0.0, 0.0, 0.85]}

    def close(self):
        pass


def fake(reps=80, step=0.005, scatter=None):
    """Hollow at the origin facing +z (heading π), 7000 (1.0 s) → 3000 (1.2 s). Hit at age 0.89 if the player is within 1.6 m
    and within ±40° of the foe's front, not rolling. scatter(k) → True flips that rep's outcome (to test "흩어짐")."""
    g = {"t": 0.0, "p": [0.0, 0.0, 0.85], "mode": "stand", "since": 0.0}
    act = FakeAct(g)
    gate = O.OptionGate(act, clock=lambda: g["t"])
    lines, hp, pt0 = [{"kind": "header", "probe": "options", "tau": O.TAU}], 10000, None
    for k in range(reps):
        t_start = k * 2.2 + 1.0
        used = False
        while g["t"] < t_start + 1.2 + 1.0 - 1e-9:
            t = g["t"]
            age = t - t_start
            in3000 = 0 <= age < 1.2
            m, dt = g["mode"], step
            px, _, pz = g["p"]
            if m.startswith("circle"):
                tx, tz = O._tangent(px, pz, 0.0, 0.0, m.endswith("_cw"))
                g["p"] = [px + tx * 1.5 * dt, 0.0, pz + tz * 1.5 * dt]
            elif m.startswith("roll") and t - g["since"] < 0.5:
                tx, tz = O._tangent(px, pz, 0.0, 0.0, True)
                g["p"] = [px + tx * 5.0 * dt, 0.0, pz + tz * 5.0 * dt]
            rolling = m.startswith("roll") and t - g["since"] < 0.5
            if in3000 and not used and age >= 0.89:
                used = True
                px, _, pz = g["p"]
                ang = abs(math.degrees(math.atan2(px, pz)))
                hit = math.hypot(px, pz) <= 1.6 and ang <= 40 and not rolling
                if scatter and scatter(k):
                    hit = not hit
                if hit:
                    hp -= 45
            foes = [{"ptr": 1, "npc": 254010, "anim": 3000 if in3000 else 7000, "d": round(math.hypot(g["p"][0], g["p"][2]), 2),
                     "x": 0.0, "z": 0.0, "h": math.pi}]
            line = {"t0": round(t - 0.001, 5), "t": round(t, 5), "pt0": round(pt0 if pt0 is not None else t - 0.001, 5),
                    "hp": hp, "foes": foes, "dbg": "0" * 32, "p": [round(v, 3) for v in g["p"]],
                    "pa": 710 if rolling else 0}
            pt0 = t - 0.001
            gate(t, foes, line, g)
            lines.append(line)
            g["t"] = round(t + step, 6)
    return lines, act


def test_inputs_go_out_at_tau_in_turn():
    lines, act = fake(reps=8)
    starts = [c for c in act.calls if c[0] == "start"]
    assert [c[1] for c in starts] == list(O.OPTIONS) * 2
    reps = [x for x in lines if "rep" in x]
    for c, r in zip(starts, reps):
        assert 0 <= c[2] - r["t"] - O.TAU < 0.006       # first read past τ
    assert any(c[0] == "steer" for c in act.calls)
    assert sum("home" in x for x in lines) >= 1


def test_check_separates_options():
    r = O.check(fake()[0])
    per = r["per_option"]
    assert r["reps"] == 80 and r["valid"] == 80, r["excluded"]
    assert per["stand"]["rate"] == 1.0 and r["stand_control"]["ok"]
    assert per["roll_cw"]["rate"] == 0.0 and per["roll_cw"]["roll_seen"] == 20
    assert per["circle_cw"]["turn_median"] > 0 > per["circle_ccw"]["turn_median"]     # + = clockwise
    assert all(per[o]["stable"] for o in per)
    assert r["verdict"] == "상태값으로 갈림 (이 조건만)"
    hit = next(x for x in r["rows"] if x["opt"] == "stand")
    assert abs(hit["angle_hit"]) < 1 and 0.88 < sum(hit["hit_age"]) / 2 < 0.9


def test_check_scattered_and_too_few():
    # the same input gives different outcomes in the two halves → 흩어짐
    r = O.check(fake(scatter=lambda k: k >= 40 and k % 4 == 0)[0])
    assert not r["per_option"]["stand"]["stable"] and r["verdict"] == "흩어짐"
    assert O.check(fake(reps=12)[0])["verdict"] == "표본 부족"


def test_late_input_excluded():
    lines, _ = fake(reps=8)
    for x in lines:
        if "pad_t" in x:
            x["pad_t"] += 0.1
    r = O.check(lines)
    assert r["valid"] == 0 and r["excluded"] == {"input_late": 8}


def test_fisher():
    assert O.fisher_p(20, 20, 0, 20) < 1e-9
    assert O.fisher_p(10, 20, 10, 20) == 1.0
    assert abs(O.fisher_p(3, 10, 7, 10) - 0.1789) < 1e-3


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
    print("ok")
