"""weapon_probe.analyze on made-up samples (no game): start, hit, cancel times from the anim clock."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import weapon_probe as W

ATK = {253000, 253010}


def _samples(seq):
    # seq: (anim, anim_time, hp) at 1/60 s steps after a press at t = 0
    return [(0.1 + i / 60, a, t, h) for i, (a, t, h) in enumerate(seq)]


def test_single_hit_and_end():
    seq = [(-1, 0.5, 100)] * 3 + [(253000, k / 60, 100 if k < 40 else 60) for k in range(0, 90)] + [(0, 0.0, 60)] * 5
    r = W.analyze(_samples(seq), 0.0, ATK, 100, "single")
    assert r["anim"] == 253000
    assert abs(r["press_to_start"] - (0.1 + 3 / 60)) < 1e-3
    assert r["hit"] == round(40 / 60, 3) and r["damage"] == 40
    assert r["end"] == round(89 / 60, 3) and r["next_anim"] == 0


def test_chain_cancel_and_roll_note():
    seq = [(253000, k / 60, 100) for k in range(70)] + [(253010, k / 60, 100) for k in range(10)]
    r = W.analyze(_samples(seq), 0.0, ATK, 100, "chain")
    assert r["end"] == round(69 / 60, 3) and r["next_anim"] == 253010 and "note" not in r
    r2 = W.analyze(_samples(seq), 0.0, ATK, 100, "roll")
    assert r2["note"] == "next was an attack, not a roll"


def test_no_attack_and_summary():
    assert W.analyze(_samples([(-1, 0.1, 100)] * 5), 0.0, ATK, 100, "single")["error"] == "no attack anim"
    rows = [{"weapon": 301003, "mode": "single", "hit": 0.68, "press_to_start": 0.05, "end": 1.8},
            {"weapon": 301003, "mode": "roll", "end": 1.40}]
    table = {"weapons": {"Claymore": {"row": 301000, "light": {"startup": 0.667, "blade_end": 0.8, "cancel_roll": 1.4}}}}
    out = "\n".join(W.summary(rows, table))
    assert "Claymore (301003)" in out and "roll 1.400" in out and "TAE 1.400" in out


class _Mesh:
    def __init__(self, edge):
        self.edge = edge                      # floor only for x < edge

    def floor_at(self, x, z, near_y):
        return (near_y, 0) if x < self.edge else None


def test_safe_line_needs_floor_behind():
    assert W.safe_line(_Mesh(10.0), 0, 5, 0, 1, 0, 1.4, 7.4)
    assert not W.safe_line(_Mesh(4.0), 0, 5, 0, 1, 0, 1.4, 7.4)
