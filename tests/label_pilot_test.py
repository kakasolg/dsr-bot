"""Labeling pilot (LAYA.md 11): a label holds only what a person chose; 'after' (bot action, buttons pressed, outcome)
never reaches the model input or the label; the page before 'after' shows nothing past the decision and no bot log lines;
one scene per fight. No game, synthetic recordings.

  python tests/label_pilot_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import math
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import label_pilot as L
import laya_shadow as LS


def snap(rt, foe_anim=-1, hp=600, foe_hp=75, d=1.2):
    return {"rt": rt, "type": "snap", "t": rt,
            "player": {"ptr": 1, "npc": 0, "team": 1, "hp": hp, "max_hp": 793, "sp": 90, "max_sp": 100,
                       "x": -30.0, "y": -49.25, "z": 29.0, "heading": -math.pi, "anim": -1},
            "chars": [{"ptr": 7, "npc": 254000, "team": 6, "hp": foe_hp, "max_hp": 75, "x": -30.0, "y": -49.25, "z": 29.0 + d,
                       "heading": 0.0, "anim": foe_anim}]}


def human_msgs():
    msgs = []
    for i in range(0, 100):
        rt = round(i * 0.1, 2)
        msgs.append({**snap(rt, foe_anim=3003 if 4.0 <= rt < 5.5 else -1, hp=600 if rt < 5.2 else 480),
                     "target": 7, "path_tag": "#3 이동", "path": [[0, 0, 0], [1, 0, 1]]})     # bot intent on the snapshot
    msgs += [{"rt": 3.0, "type": "pad", "i": 0, "btn": 0}, {"rt": 3.5, "type": "pad", "i": 0, "btn": 0x0100},
             {"rt": 5.0, "type": "pad", "i": 0, "btn": 0x0100 | 0x0200}]          # LB before t_d, R1 after
    return sorted(msgs, key=lambda m: m["rt"])


def scene_and_clip(tmp: Path):
    msgs = human_msgs()
    c = {"source": "human_demo", "source_file": "data/observe/x.jsonl", "run_id": "human-x", "fight_id": "human-x#f000",
         "t_d": 4.5, "event": "swing", "zone": "ramp flat", "npc": 254000, "result": "killed", "y": -49.25}
    s = L.build_scene(c, msgs)
    L.CLIPS = tmp
    (tmp / f"{s['scene_id']}.jsonl").write_text("\n".join(json.dumps(m) for m in msgs) + "\n", encoding="utf-8")
    return s


def test_scene_separates_after() -> None:
    with tempfile.TemporaryDirectory() as d:
        s = scene_and_clip(Path(d))
        assert s["schema"] == L.SCENE_SCHEMA and s["source"] == "human_demo" and s["code_commit"] is None
        assert s["obs"]["target_state"] == "swinging" and s["obs"]["distance_m"] == 1.2
        assert s["after"]["human_pressed"] == [[0.5, "R1"]], s["after"]          # pressed after t_d → 'after' only
        assert s["context"]["actor_did"] == [[-1.0, "LB"]], s["context"]        # before t_d → context
        assert s["after"]["my_hp_change_1_5s"] == -120
        flat = json.dumps({"obs": s["obs"], "context": s["context"], "allowed": s["allowed"]})
        for k in ("human_pressed", "bot_action", "fight_result", "my_hp_change_1_5s"):
            assert k not in flat
        assert "weapon_reach_m" in s["missing"] and s["obs"]["weapon_reach_m"] is None
        assert "attack" in s["allowed"], s["allowed"]                          # weapon unknown → bounded by the weapon table
        assert set(s["allowed"]) <= set(LS.TACTICS)
        page = L.scene_for_page(s, "pre")
        assert "after" not in page and "test_candidate" not in page and "selection" not in page
        assert "after" in L.scene_for_page(s, "full")
        pre = L.clip_msgs(s, "pre")
        assert max(m["rt"] for m in pre) <= s["t_d"]
        assert not any(k in m for m in pre for k in L.INTENT_KEYS)                # no planned path / target from the bot
        assert [m for m in pre if m["type"] == "say"] == [{"rt": s["t_d"], "type": "say", "t": s["t_d"], "line": "F9 marker ▶ 결정 시점"}]
        full = L.clip_msgs(s, "full")
        assert max(m["rt"] for m in full) > s["t_d"]
    print("ok  scene: observed state and context before t_d, actions and outcome only in 'after'")


def test_label_is_only_what_a_person_chose() -> None:
    with tempfile.TemporaryDirectory() as d:
        s = scene_and_clip(Path(d))
    good = {"scene_id": s["scene_id"], "labeler_id": "MoKa", "duration_s": 31.4, "saw_after": False,
            "acceptable": ["guard"], "forbidden": ["attack"], "best": "guard", "unsure": False,
            "rationale": "휘두르는 중, 1.2 m", "evidence": ["target_state", "distance_m", "context.target_states"],
            "label_source": "rule", "after": s["after"], "human_pressed": [[0.5, "R1"]], "bot_action": {"attack": 1}}
    assert L.validate_label(good, s) == []
    row = L.make_label(good, s)
    assert row["label_source"] == "human_verified" and row["schema"] == L.LABEL_SCHEMA
    assert set(row) == {"scene_id", "schema", "label_source", "labeler_id", "labeled_at", "duration_s", "saw_after", "acceptable",
                        "forbidden", "best", "unsure", "unsure_reason", "rationale", "evidence", "definition_note"}
    bad = [({"acceptable": ["guard"], "forbidden": ["guard"]}, "both"), ({"best": "attack"}, "best"),
           ({"acceptable": [], "forbidden": []}, "at least one"), ({"unsure": True, "unsure_reason": "?"}, "unsure_reason"),
           ({"evidence": ["after.fight_result"]}, "evidence"), ({"acceptable": ["fly"]}, "unknown"), ({"labeler_id": ""}, "labeler")]
    for change, why in bad:
        errs = L.validate_label({**good, **change}, s)
        assert any(why in e for e in errs), (change, errs)
    unsure = {**good, "acceptable": [], "forbidden": [], "best": None, "unsure": True, "unsure_reason": "정보 부족"}
    assert L.validate_label(unsure, s) == [] and L.make_label(unsure, s)["unsure"]
    print("ok  label: person's choice only, always human_verified, bad input refused")


def test_one_scene_per_fight() -> None:
    cands = []
    for f in range(30):                                    # 30 ramp fights, 10 ticks each, plus 30 town fights
        for i in range(10):
            cands.append({"source": "bot", "run_id": f"r{f % 6}", "fight_id": f"r{f % 6}#f{f}", "t_d": f * 100 + i,
                          "event": ["swing", "opening", "close_idle", "far"][i % 4], "zone": "ramp", "npc": 254000, "result": "killed"})
    for f in range(30):
        cands.append({"source": "human_demo", "run_id": f"h{f % 8}", "fight_id": f"h{f % 8}#f{f}", "t_d": f * 7.0,
                      "event": "swing", "zone": "town path", "npc": 255000, "result": "survived"})
    got = L.select(cands, 20)
    per_fight = {}
    for c in got:
        per_fight.setdefault(c["fight_id"], []).append(c)
    assert all(len(v) == 1 for v in per_fight.values()), {k: len(v) for k, v in per_fight.items() if len(v) > 1}
    assert sum(c["zone"] == "ramp" for c in got) <= 8
    runs = {}
    for c in got:
        runs[c["run_id"]] = runs.get(c["run_id"], 0) + 1
    assert max(runs.values()) <= 4, runs
    assert L.select(cands, 20) == got                      # fixed seed
    print(f"ok  selection: {len(got)} scenes from {len(per_fight)} fights, ramp ≤ 8, ≤ 4 per run, reproducible")


if __name__ == "__main__":
    test_scene_separates_after()
    test_label_is_only_what_a_person_chose()
    test_one_scene_per_fight()
