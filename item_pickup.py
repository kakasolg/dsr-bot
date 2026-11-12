"""Walk to one item corpse and press A to pick it up; check the item's event flag and goods count before and after.

  python item_pickup.py <x> <y> <z> <flag> <goods_id> [tag]

MoKa 11-12 (M1111-92): "중갑 기사 있었던데 아이템 있지 그거 획득해" — Fire Keeper Soul behind the parish church knight:
  python item_pickup.py 10.9 30.06 124.15 51010050 396 fire-keeper-soul   (m10_01 宝死体05, ItemLot 1010050)
Same steps as experiments/item_pickup_2026_11_01/humanity_probe.py (walk → A → flag/count), on andre_route.Route (lock, pad,
NavMesh, Field). The pickup window gets one more A to close it. A flag already on = nothing to pick up; it stops there.
"""
from __future__ import annotations

import math
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

import andre_route
import control

STAND_M = 0.7          # stop this far from the corpse (humanity_probe: picked up at 0.48 m)


def main() -> None:
    x, y, z = (float(v) for v in sys.argv[1:4])
    flag, item = int(sys.argv[4]), int(sys.argv[5])
    tag = sys.argv[6] if len(sys.argv) > 6 else "item"
    r = andre_route.Route()
    try:
        tm = r.tm
        f0, c0 = tm.event_flag(flag), tm.goods_count(item)
        r.say(f"[{tag}] before: flag {flag} {f0} · goods {item} = {c0}")
        if f0:
            r.say("  already picked up — nothing to do")
            return
        s = r.mv.snap(30.0)
        p = s.player
        d = max(math.hypot(x - p.x, z - p.z), 0.1)
        goal = (x - (x - p.x) / d * STAND_M, y, z - (z - p.z) / d * STAND_M)
        w = r.walk([goal], f"{tag} 앞으로")
        s = r.mv.snap(30.0)
        dist = math.hypot(x - s.player.x, z - s.player.z)
        r.say(f"  walk: {w}, {dist:.2f} m from the corpse")
        for i in range(3):
            s = r.mv.snap(30.0)
            r.pad.move(*r.mv.stick_to(s, x, z, 0.35)); time.sleep(0.25); r.pad.move(0, 0)
            r.pad.tap(control.B.XUSB_GAMEPAD_A, 0.1)
            time.sleep(1.0)
            if tm.event_flag(flag):
                break
        f1, c1 = tm.event_flag(flag), tm.goods_count(item)
        r.say(f"[{tag}] after: flag {flag} {f1} · goods {item} = {c1} (Δ {(c1 or 0) - (c0 or 0)})")
        if f1:
            time.sleep(0.5)
            r.pad.tap(control.B.XUSB_GAMEPAD_A, 0.1)        # close the "item obtained" window
            time.sleep(0.5)
        print(f"RESULT {tag}: {'picked up' if f1 else 'not picked up'} · flag {f1} · goods {c0} → {c1}")
    finally:
        r.pad.neutral()
        try:
            r.esc.stop()
        except Exception:
            pass
        r.pad.close()
        r.lock.release()


if __name__ == "__main__":
    main()
