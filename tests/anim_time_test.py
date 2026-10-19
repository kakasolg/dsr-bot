"""DSRTelemetry.anim_time against a fake memory (docs/rea.md 3차): newest anim = smallest time among blended entries."""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules)
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
import dsr_telemetry as D  # noqa: E402


class FakeTm:
    anim_time = D.DSRTelemetry.anim_time

    def __init__(self, mem):
        self.mem = mem

    def q(self, a):
        return self.mem.get(("q", a))

    def i32(self, a):
        return self.mem.get(("i", a))

    def f32(self, a):
        return self.mem.get(("f", a))


def tm_with(entries):
    """entries: [(time, weight) | None] → ChrIns 0x1000 → ChrCtrl 0x2000 → queue 0x3000 → array 0x4000 → controls 0x5000 + 0x100·i"""
    m = {("q", 0x1000 + 0x68): 0x2000, ("q", 0x2000 + 0x18): 0x3000, ("i", 0x3000): len(entries), ("q", 0x3008): 0x4000}
    for i, e in enumerate(entries):
        if e is None:
            continue
        c = 0x5000 + 0x100 * i
        m[("q", 0x4000 + i * 0x78 + 0x8)] = c
        m[("f", c + 0x10)], m[("f", c + 0x14)] = e
    return FakeTm(m)


def test_newest_blended_entry():
    assert tm_with([(2.88, 0.96), (0.017, 0.04), (2.0, 0.0)]).anim_time(0x1000) == 0.017   # new anim fading in
    assert tm_with([(0.9, 1.0), (2.0, 0.0), None]).anim_time(0x1000) == 0.9                # weight 0 entries ignored
    assert tm_with([]).anim_time(0x1000) is None
    assert FakeTm({}).anim_time(0x1000) is None


if __name__ == "__main__":
    test_newest_blended_entry()
    print("ok test_newest_blended_entry")
