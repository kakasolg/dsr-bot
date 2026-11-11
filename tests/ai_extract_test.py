"""ai_extract offline test — goal ids from fake m*.json, picking goals from fake luabnds, call scanning. No game, no decompiler.

  python tests/ai_extract_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import ai_extract as X


def test_goal_ids_for():
    with tempfile.TemporaryDirectory() as t:
        p = Path(t)
        (p / "m10_01_00_00.json").write_text(json.dumps({"enemies": [
            {"model": "c2540", "think": {"BattleID": 254000, "LogicID": 10000}},
            {"model": "c2540", "think": {"BattleID": 254001, "LogicID": 10000}},
            {"model": "c2540", "think": None},
            {"model": "c2550", "think": {"BattleID": 255000, "LogicID": 10000}},
            {"model": "c2540", "think": {"BattleID": -1, "LogicID": 10000}}]}), encoding="utf-8")
        assert X.goal_ids_for("c2540", p) == {254000, 254001, 10000}


def test_calls():
    script = """function Zombie254000Battle_Activate(ai, goal)
  local r = ai:GetRandam_Int(1, 100)
  if r < 30 then goal:AddSubGoal(GOAL_COMMON_Attack, 10, 3000, TARGET_ENE_0) end
  Approach_Act(ai, goal, 2.5, 0, 0)
end
local function helper() return math.floor(1.5) end
function Zombie254000Battle_Update(ai, goal) return GOAL_RESULT_Continue end"""
    c = X.calls(script)
    assert c["defines"] == ["Zombie254000Battle_Activate", "Zombie254000Battle_Update", "helper"]
    assert c["calls_outside"] == ["AddSubGoal", "Approach_Act", "GetRandam_Int"]


def test_pick():
    g1 = SimpleNamespace(goal_id=254000, goal_name="Zombie254000Battle", script="")
    g2 = SimpleNamespace(goal_id=999, goal_name="Other", script="")
    helper = SimpleNamespace(script_name="Approach_Act", script="")
    bnds = {"m10_01_00_00.luabnd.dcx": SimpleNamespace(goals=[g1, g2], unknown_scripts=[]),
            "aiCommon.luabnd.dcx": SimpleNamespace(goals=[], unknown_scripts=[helper])}
    assert X.pick(bnds, {254000}, common=False) == [("m10_01_00_00.luabnd.dcx", g1, "goal")]
    assert X.pick(bnds, {254000}, common=True)[-1] == ("aiCommon.luabnd.dcx", helper, "common")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
