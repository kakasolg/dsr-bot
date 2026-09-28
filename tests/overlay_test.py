"""overlay offline test — what the overlay shows, from radar_server /state. No game, no window.

  python overlay_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys

sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import overlay as O

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


def foe(ptr, x, z, hp=100, anim=3000, team=6, name="Hollow"):
    return {"ptr": ptr, "name": name, "npc": 250000, "team": team, "hp": hp, "max_hp": 100, "x": x, "y": 0.0, "z": z,
            "dist": (x * x + z * z) ** 0.5, "anim": anim}


state = {"age": 0.1, "items": [[0.0, 0.0, 2.0, "titanite", "Titanite Shard", []], [5.0, 0.0, 0.0, "soul", "Soul of a Lost Undead", []],
                               [1.0, 0.0, 0.0, "other", "Firebomb", []]], "says": [{"line": "fight: Hollow"}, {"line": "retreat mode: guard"}],
         "props": [[0.0, 0.0, 3.0, False, "o1130_12"], [50.0, 0.0, 0.0, False, "far"]],
         "snap": {"player": {"x": 0.0, "y": 0.0, "z": 0.0, "hp": 200, "max_hp": 800, "sp": 50, "max_sp": 100},
                  "cam_yaw": 0.0, "flask_hp": 2, "target": 5, "path_tag": "ramp", "path": [[0, 0, 0], [0, 0, 5]],
                  "smash": "o1130_12",
                  "chars": [foe(5, 0.0, 4.0, name="Shield"), foe(6, 4.0, 0.0), foe(7, -3.0, 0.0, hp=0), foe(8, 1.0, 1.0, team=26)]}}

print("글 (lines)")
L = [t for t, _ in O.lines(state)]
check("서버 없음", "no radar server" in O.lines(None)[0][0])
check("봇 데이터 없음", "no bot data" in O.lines({"snap": None})[0][0])
check("HP 25% → 경고색", L[0].startswith("HP 200/800 (25%)") and O.lines(state)[0][1] == O.WARN)
check("목표·경로·부숨", any(t.startswith("target: Shield") for t in L) and any("path: ramp" in t for t in L) and any("smash: o1130_12" in t for t in L))
check("8 m 안 적 수 (죽은 적·우호 제외)", any(t.startswith("foes within 8 m: 2 (2 moving)") for t in L))
check("판단 최신이 먼저", L[-2] == "› retreat mode: guard" and L[-1] == "› fight: Hollow")
check("끊김 표시", O.lines({**state, "age": 5.0})[0][0].startswith("stale"))

check("가장 가까운 아이템 (기타 제외)", any(t.startswith("item: Titanite Shard  2.0 m  (+1 more)") for t in L))

print("미니 레이더 (카메라 위)")
pts = O.radar_points(state, size=200, range_m=10.0)
kinds = [p[0] for p in pts]
c = 100
tgt = next(p for p in pts if p[0] == "target")
right = next(p for p in pts if p[0] == "foe")
check("가운데 플레이어", pts[-1] == ("player", c, c))
check("목표(앞 4 m)는 위쪽", abs(tgt[1] - c) < 0.01 and tgt[2] < c)
check("오른쪽 적은 오른쪽", right[1] > c and abs(right[2] - c) < 0.01)
check("죽은 적·우호·범위 밖 물건", "foe_dead" in kinds and kinds.count("foe") == 1 and "smash" in kinds and "prop" not in kinds)
check("경로 선", pts[0][0] == "path" and len(pts[0][1]) == 2)
check("아이템 표시 (기타는 안 그림)", "item_titanite" in kinds and "item_soul" in kinds and not any(k == "item_other" for k in kinds))
turned = O.radar_points({**state, "snap": {**state["snap"], "cam_yaw": 3.14159265}}, size=200, range_m=10.0)
t2 = next(p for p in turned if p[0] == "target")
check("카메라가 반대로 보면 목표는 아래쪽", t2[2] > c)
check("데이터 없으면 빈 목록", O.radar_points(None) == [])

print("전부 통과" if not fails else f"실패 {fails}")
sys.exit(1 if fails else 0)
