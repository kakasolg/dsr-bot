"""souls/altar offline: Hellkite 'landed' / 'away' from MoKa's demo positions, and the route file's legs."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from souls import altar as A  # noqa: E402


def snap(*chars):
    return NS(chars=list(chars))


def drk(x, y, z):
    return NS(npc_param=A.DRAKE, x=x, y=y, z=z, anim=-1)


def test_landed_and_away():
    assert A.landed(snap(drk(8.9, 9.5, -48.0)))              # demo 349.5 s
    assert not A.landed(snap(drk(11.8, 28.5, -42.9)))         # still coming down (348.5 s)
    assert not A.landed(snap(drk(0.7, 15.0, -57.5)))          # fly-by over the bridge (119 s)
    assert not A.landed(snap())
    assert A.away(snap(drk(20.6, 18.9, -29.0)))               # perch
    assert A.away(snap())
    assert not A.away(snap(drk(10.4, 9.3, -45.7)))            # still on the bridge (367.7 s)


def test_route_file():
    R = A.load_route(ROOT / "data")
    m = R["markers"]
    assert R["sprint_1_to_2"][0] == m["1_bridge_entry"] and R["sprint_1_to_2"][-1] == m["2_stairs_bottom"]
    assert R["sprint_3_to_4"][-1] == m["4_drake_leaves"]
    assert R["claymore"]["flag"] == A.CLAYMORE_FLAG


if __name__ == "__main__":
    test_landed_and_away()
    test_route_file()
    print("ok  altar")
