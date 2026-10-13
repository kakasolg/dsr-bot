"""P-70 (10-13 staggerfix1): Moves.lock_target centers the left stick before pressing R3 — face() had left it pushed and the
character walked 3.9 m off the stair side during two lock tries.  python tests/lock_stick_test.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from souls import moves as M


class Pad:
    def __init__(self):
        self.calls = []
        self.stick = (0.41, -0.37)                 # left pushed by face()

    def move(self, x, y):
        self.stick = (x, y)
        self.calls.append(("move", x, y))

    def lock_on(self):
        self.calls.append(("R3", self.stick))

    def release_due(self):
        pass


def test_stick_centered_before_r3():
    m = M.Moves.__new__(M.Moves)
    m.pad = Pad()
    states = iter(["none", "none", "none", "target"])
    m.lock_state = lambda ptr: next(states, "target")
    m._lock_align = lambda ptr, aim: {}
    assert m.lock_target(7, tries=2, aim=False)
    r3 = [c for c in m.pad.calls if c[0] == "R3"]
    assert r3 and all(c[1] == (0.0, 0.0) for c in r3), m.pad.calls


def test_already_locked_leaves_stick_alone():
    m = M.Moves.__new__(M.Moves)
    m.pad = Pad()
    m.lock_state = lambda ptr: "target"
    assert m.lock_target(7)
    assert m.pad.calls == []


if __name__ == "__main__":
    test_stick_centered_before_r3()
    test_already_locked_leaves_stick_alone()
    print("ok")
