"""Andre hostile / dead flags (MoKa M1111-83): andre_route.Route.andre_bad reads 1321 / 1322 — offline, fake telemetry."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import andre_route


class FakeTm:
    def __init__(self, on):
        self.on = set(on)

    def event_flag(self, f):
        return f in self.on


def bad(on):
    r = andre_route.Route.__new__(andre_route.Route)
    r.tm = FakeTm(on)
    return r.andre_bad()


def test_andre_flags():
    assert bad({1320}) is None                  # 11-12 state: normal
    assert bad({1321}) == "hostile"
    assert bad({1322}) == "dead"
    assert bad({1321, 1322}) == "dead"


if __name__ == "__main__":
    test_andre_flags()
    print("ok  andre flags")
