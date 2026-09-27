"""props / field._smash offline test — breakable props on the way, from data/gamefiles. No game.

  python props_test.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World, make_field
from souls import field as F
from souls import props

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


def prop(name, pos, breakable=True, min_attack=0):
    return {"name": name, "model": name.split("_")[0], "pos": list(pos), "breakable": breakable, "min_attack": min_attack}


print("blocking (가짜 목록)")
me, goal = (0.0, 0.0, 0.0), (5.0, 0.0, 0.0)
P = [prop("o1_on_lane", (1.5, 0.0, 0.3)), prop("o2_behind", (-1.5, 0.0, 0.0)), prop("o3_far", (4.0, 0.0, 0.0)),
     prop("o4_below", (1.0, -2.0, 0.0)), prop("o5_closer", (0.8, 0.0, -0.5))]
got = [o["name"] for o in props.blocking(None, me, goal, props=P)]
check("길 위·가까운 것만, 가까운 순", got == ["o5_closer", "o1_on_lane"])
check("지도 없으면 빈 목록", props.blocking("m_none", me, goal) == [])

print("load (커밋된 Undead Burg 추출)")
burg = props.load("m10_01_00_00")
check("부서짐·약공 가능만", burg and all(o["breakable"] is True and (o["min_attack"] or 0) < props.STRONG_MIN_ATTACK for o in burg))
# P-6 scene: stuck at (-34.3,-13.5,-72.0) short of path point (-36.0,-13.5,-70.1)
names = [o["name"] for o in props.blocking("m10_01_00_00", (-34.3, -13.5, -72.0), (-36.0, -13.5, -70.1))]
check(f"P-6 장면: 막은 상자 찾음 {names}", "o1132_06" in names or "o1130_12" in names)

print("field._smash")
w = World(player=(0.0, 0.0, 0.0))
f = make_field(w)
calls = []
f.mv.pad.attack = lambda: calls.append("attack")
F.SMASH_SWING_S = 0.0
f._smash(prop("o1132_06", (1.0, 0.0, 0.0)), "성벽 마을")
check("약공 2번", calls == ["attack", "attack"])
check("smash 이벤트·로그", f.evs and f.evs[-1][0] == "smash" and f.evs[-1][1]["prop"] == "o1132_06" and "부숨 시도" in f.logs[-1])

print("nav.goto on_stuck (막힘 2 s 만에 알림)")
import time
import nav
from field_fakes import FakePad

w2 = World(player=(0.0, 0.0, 0.0))
w2.player.gx, w2.player.gy, w2.player.gz = 0.0, 0.0, 0.0


class Tm:
    def snapshot(self, within=60.0):
        return w2.snapshot(within)


class Pad(FakePad):
    def __getattr__(self, n):
        return lambda *a, **k: None


hits = []
t0 = time.time()
r = nav.goto(Tm(), Pad(), (5.0, 0.0, 0.0), tolerance=0.5, timeout=4.5, log=lambda *a: None,
             on_stuck=lambda p, t: hits.append(time.time() - t0) or len(hits) < 2)
check(f"안 움직이면 STUCK_WINDOW 뒤 호출, True 면 다시 재고 계속 ({[round(h, 1) for h in hits]})",
      len(hits) == 2 and 1.8 < hits[0] < 2.6 and 3.8 < hits[1] < 4.6 and r == "timeout")

print("field._smash_blocking")
f3 = make_field(World(player=(-34.3, -13.5, -72.0)))
f3.mv.pad.attack = lambda: None
nm = type("Nm", (), {"map_id": "m10_01_00_00"})()
smashed = {}
first = f3._smash_blocking(nm, (-34.3, -13.5, -72.0), (-36.0, -13.5, -70.1), smashed, "t")
for _ in range(5):
    f3._smash_blocking(nm, (-34.3, -13.5, -72.0), (-36.0, -13.5, -70.1), smashed, "t")
check("P-6 장면 상자 부숨 → True, 레이더용 기록", first and f3.mv.show_smash and f3.mv.show_smash[0] in ("o1130_12", "o1132_06"))
check(f"같은 물건은 걷기 한 번에 {F.SMASH_TRIES}회까지 {smashed}", all(v <= F.SMASH_TRIES for v in smashed.values())
      and not f3._smash_blocking(nm, (-34.3, -13.5, -72.0), (-36.0, -13.5, -70.1), smashed, "t"))
check("지도 없는 nm → False", not f3._smash_blocking(type("N", (), {})(), (0, 0, 0), (1, 0, 0), {}, "t"))

print("전부 통과" if not fails else f"실패 {fails}")
sys.exit(1 if fails else 0)
