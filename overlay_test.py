"""overlay offline test — what the overlay shows, from radar_server /state. No game, no window.

  python overlay_test.py
"""
from __future__ import annotations

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


def foe(ptr, x, z, hp=100, anim=3000, team=6, name="망자"):
    return {"ptr": ptr, "name": name, "npc": 250000, "team": team, "hp": hp, "max_hp": 100, "x": x, "y": 0.0, "z": z,
            "dist": (x * x + z * z) ** 0.5, "anim": anim}


state = {"age": 0.1, "says": [{"line": "교전: 망자"}, {"line": "후퇴 모드: guard"}],
         "props": [[0.0, 0.0, 3.0, False, "o1130_12"], [50.0, 0.0, 0.0, False, "far"]],
         "snap": {"player": {"x": 0.0, "y": 0.0, "z": 0.0, "hp": 200, "max_hp": 800, "sp": 50, "max_sp": 100},
                  "cam_yaw": 0.0, "flask_hp": 2, "target": 5, "path_tag": "경사로", "path": [[0, 0, 0], [0, 0, 5]],
                  "smash": "o1130_12",
                  "chars": [foe(5, 0.0, 4.0, name="방패병"), foe(6, 4.0, 0.0), foe(7, -3.0, 0.0, hp=0), foe(8, 1.0, 1.0, team=26)]}}

print("글 (lines)")
L = [t for t, _ in O.lines(state)]
check("서버 없음", "연결 없음" in O.lines(None)[0][0])
check("봇 데이터 없음", "봇 데이터 없음" in O.lines({"snap": None})[0][0])
check("HP 25% → 경고색", L[0].startswith("HP 200/800 (25%)") and O.lines(state)[0][1] == O.WARN)
check("목표·경로·부숨", any(t.startswith("목표: 방패병") for t in L) and any("경로: 경사로" in t for t in L) and any("부숨: o1130_12" in t for t in L))
check("8 m 안 적 수 (죽은 적·우호 제외)", any(t.startswith("8 m 안 적 2 (움직임 2)") for t in L))
check("판단 최신이 먼저", L[-2] == "› 후퇴 모드: guard" and L[-1] == "› 교전: 망자")
check("끊김 표시", O.lines({**state, "age": 5.0})[0][0].startswith("끊김"))

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
turned = O.radar_points({**state, "snap": {**state["snap"], "cam_yaw": 3.14159265}}, size=200, range_m=10.0)
t2 = next(p for p in turned if p[0] == "target")
check("카메라가 반대로 보면 목표는 아래쪽", t2[2] > c)
check("데이터 없으면 빈 목록", O.radar_points(None) == [])

print("전부 통과" if not fails else f"실패 {fails}")
sys.exit(1 if fails else 0)
