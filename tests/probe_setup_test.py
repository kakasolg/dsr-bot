"""probe_setup: heading toward a point, and stopping the shared Feed thread (no game)."""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules)
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
import math

import env
import probe_setup as P


def test_heading_to_faces_the_point():
    h = P.heading_to(0.0, 0.0, 0.0, 1.0)                       # target at +z: yaw 0 → heading −π
    yaw = h + math.pi
    assert abs(math.sin(yaw) - 0.0) < 1e-9 and abs(math.cos(yaw) - 1.0) < 1e-9
    yaw = P.heading_to(1.0, 1.0, 2.0, 1.0) + math.pi           # target at +x
    assert abs(math.sin(yaw) - 1.0) < 1e-9


def test_stop_feed_stops_and_forgets_it():
    class F:
        stopped = False

        def stop(self):
            self.stopped = True
    f = F()
    env._feed = f
    P.stop_feed()
    assert f.stopped and env._feed is None
    P.stop_feed()                                             # nothing running: no error


if __name__ == "__main__":
    test_heading_to_faces_the_point()
    test_stop_feed_stops_and_forgets_it()
    print("ok probe_setup_test")
