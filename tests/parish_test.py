"""souls/parish offline: route legs and the group loop with a fake Field (no game)."""
import math
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from souls import parish as P  # noqa: E402


def test_legs():
    pts = P.load_route(ROOT / "data")
    out, back = P.legs(pts)
    assert out[0] == pts[0] and math.dist(out[-1], (36.9, 26.6, 107.4)) < 1.0      # ends at MoKa's F9 marker
    assert back[0] == pts[-1] and back[-1] == pts[0]
    assert all(math.dist(a, b) < 6.0 for a, b in zip(back, back[1:]))              # no long jump on the way back


class FakeField:
    def __init__(self, results, seen=(True, True, True)):
        self.results, self.seen, self.fought, self.walks = list(results), list(seen), [], []
        self.left = []
        self.mv = NS(snap=lambda r: NS(player=NS(hp=793, x=0, y=0, z=0), chars=self.left))

    def alive(self):
        return True

    def estus_left(self):
        return 5

    def find_at(self, npc, pos, r):
        return NS(ptr=len(self.fought) + 1) if self.seen[len(self.fought)] else None

    def walk_to(self, goal, nm, tag):
        self.walks.append(tag)
        return "arrived"

    def fight(self, ptr, nm, tag):
        self.fought.append(tag)
        return NS(result=self.results.pop(0), taken=10)

    def recover(self, why, nm):
        return True


def group(fake):
    g = P.Group1.__new__(P.Group1)
    g.f, g.nm, g.log, g.ev = fake, None, lambda *a: None, lambda *a, **k: None
    return g.group()


def test_group_all_killed():
    f = FakeField(["killed"] * 3)
    assert group(f) == "cleared" and f.fought == ["#1 255042", "#2 255041", "#3 255041"]


def test_group_stops_on_death():
    f = FakeField(["killed", "me_dead", "killed"])
    assert group(f) == "died" and len(f.fought) == 2


def test_group_cleared_when_one_died_in_another_fight():
    # run 205059: 255041 cut into #1's fight and died there; #2's search found the other 255041, #3's spot was empty
    f = FakeField(["killed", "killed"])
    f.find_at = lambda npc, pos, r, f=f: None if len(f.fought) == 2 else NS(ptr=1)
    assert group(f) == "cleared" and f.walks == ["#3 255041 이동"]


def test_group_partial_when_one_left_alive():
    f = FakeField(["killed", "lost", "killed"])
    f.left = [NS(npc_param=255041, hp=40, x=28.0, y=26.6, z=104.0)]
    assert group(f).startswith("partial")


def test_walkway_targets_and_leg():
    pts = P.load_route(ROOT / "data")
    leg = pts[P.WALKWAY_FROM_I:]
    assert math.dist(leg[-1], (37.6, 29.8, 60.2)) < 0.5                            # route end = where MoKa stopped after 255040
    assert all(math.dist(a, b) < 6.0 for a, b in zip(leg, leg[1:]))
    g = P.Group1.__new__(P.Group1)
    f = FakeField(["killed", "killed"])
    g.f, g.nm, g.log, g.ev = f, None, lambda *a: None, lambda *a, **k: None
    assert g.clear(P.WALKWAY, "통로 둘", "") == "cleared" and f.fought == ["#1 256000", "#2 255040"]


if __name__ == "__main__":
    test_legs()
    test_group_all_killed()
    test_group_stops_on_death()
    test_group_cleared_when_one_died_in_another_fight()
    test_group_partial_when_one_left_alive()
    test_walkway_targets_and_leg()
    print("ok  parish")
