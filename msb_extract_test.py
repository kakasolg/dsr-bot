"""msb_extract offline test — a fake MSB and fake params built in memory, no game files.

  python msb_extract_test.py
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import msb_extract as X
from soulstruct.darksouls1r.maps import MSB
from soulstruct.darksouls1r.maps.models import MSBCharacterModel, MSBObjectModel
from soulstruct.darksouls1r.maps.parts import MSBCharacter, MSBObject
from soulstruct.darksouls1r.maps.regions import MSBRegion
from soulstruct.utilities.maths import EulerDeg, Vector3


def V(*a):
    return Vector3(a)


def fake_msb():
    msb = MSB()
    hollow, human = MSBCharacterModel(name="c2250"), MSBCharacterModel(name="c0000")
    box, door = MSBObjectModel(name="o1200"), MSBObjectModel(name="o9999")
    msb.character_models.extend([hollow, human])
    msb.object_models.extend([box, door])
    a, b = MSBRegion(name="patrol_a", translate=V(1, 2, 3)), MSBRegion(name="patrol_b", translate=V(4, 2, 6))
    msb.region_points.extend([a, b])
    msb.characters.append(MSBCharacter(name="c2250_0000", model=hollow, translate=V(10, 0, 5), rotate=EulerDeg((0, 90, 0)),
                                       ai_id=225000, character_id=225000, patrol_regions=[a, None, b] + [None] * 5))
    msb.characters.append(MSBCharacter(name="c0000_0001", model=human, translate=V(0, 0, 0), ai_id=-1))
    msb.objects.append(MSBObject(name="o1200_0000", model=box, translate=V(4, 0, 4)))
    msb.objects.append(MSBObject(name="o9999_0000", model=door, translate=V(8, 0, 8)))
    return msb


def fake_params():
    objs = {1200: SimpleNamespace(ObjectHP=1, PreventAllDamage=False, IsLadder=False)}
    think = {225000: SimpleNamespace(SightDistance=20, HearingDistance=10, MaxRetreatDistance=15)}
    return objs, think


fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


print("MSB만")
d = X.extract("m_test", with_params=False, msb=fake_msb())
e0, e1 = d["enemies"]
check("적 수 (c0000 은 human 으로 분리)", d["counts"]["enemies"] == 1 and e1["kind"] == "human")
check("적 위치·방향", e0["pos"] == [10.0, 0.0, 5.0] and e0["rot_y"] == 90.0)
check("순찰 경로 (빈 칸 건너뜀)", [p["name"] for p in e0["patrol"]] == ["patrol_a", "patrol_b"])
check("params 없으면 breakable/think 는 None", d["objects"][0]["breakable"] is None and e0["think"] is None)
check("증거 등급 file", d["evidence"] == "file")

print("params 포함")
X.load_params = lambda game_dir: fake_params()
d = X.extract("m_test", msb=fake_msb())
box, door = d["objects"]
check("박스: 행 있음, 부서짐", box["param_row_found"] is True and box["breakable"] is True)
check("문: 행 없음 → 부서지지 않음", door["param_row_found"] is False and door["breakable"] is False)
check("적 think 붙음", d["enemies"][0]["think"] == {"SightDistance": 20, "HearingDistance": 10, "MaxRetreatDistance": 15})
check("ai_id -1 이면 think None", d["enemies"][1]["think"] is None)
check("breakable 판정", X.is_breakable({"ObjectHP": 0}) is False and X.is_breakable({"ObjectHP": 5, "PreventAllDamage": True}) is False)

print("전부 통과" if not fails else f"실패 {fails}")
sys.exit(1 if fails else 0)
