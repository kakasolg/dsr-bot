"""Labeling pilot (LAYA.md 11): a label holds only what a person chose; observed actions (the bot's log, a human's buttons
— a roll included) never become candidates or answers; 'after' never reaches the model input, the first-pass screen or
the label; a first-pass label is kept when the labeler changes their mind after seeing 'after'. No game, synthetic
recordings, temp label files (never data/labels).

  python tests/label_pilot_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import itertools
import json
import math
import random
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import label_pilot as L
import laya_shadow as LS

REAL = (L.LABEL_FILE, L.REVEALS, L.CLIPS)


def snap(rt, foe_anim=-1, hp=600, foe_hp=75, d=1.2, my_anim=-1):
    return {"rt": rt, "type": "snap", "t": rt,
            "player": {"ptr": 1, "npc": 0, "team": 1, "hp": hp, "max_hp": 793, "sp": 90, "max_sp": 100,
                       "x": -30.0, "y": -49.25, "z": 29.0, "heading": -math.pi, "anim": my_anim},
            "chars": [{"ptr": 7, "npc": 254000, "team": 6, "hp": foe_hp, "max_hp": 75, "x": -30.0, "y": -49.25, "z": 29.0 + d,
                       "heading": 0.0, "anim": foe_anim}]}


def human_msgs():
    """Foe swings 4.0–5.5 s; the human holds LB at 3.5 s, then taps B at 4.7 s and rolls (anim 710), R1 at 5.0 s."""
    msgs = []
    for i in range(0, 100):
        rt = round(i * 0.1, 2)
        msgs.append({**snap(rt, foe_anim=3003 if 4.0 <= rt < 5.5 else -1, hp=600 if rt < 5.2 else 480,
                            my_anim=710 if 4.8 <= rt < 5.4 else -1),
                     "target": 7, "path_tag": "#3 이동", "path": [[0, 0, 0], [1, 0, 1]]})     # bot intent on the snapshot
    msgs += [{"rt": 3.0, "type": "pad", "i": 0, "btn": 0}, {"rt": 3.5, "type": "pad", "i": 0, "btn": 0x0100},
             {"rt": 4.7, "type": "pad", "i": 0, "btn": 0x0100 | 0x2000}, {"rt": 4.82, "type": "pad", "i": 0, "btn": 0x0100},
             {"rt": 5.0, "type": "pad", "i": 0, "btn": 0x0100 | 0x0200}]
    return sorted(msgs, key=lambda m: m["rt"])


def human_scene(tmp: Path):
    msgs = human_msgs()
    c = {"source": "human_demo", "source_file": "data/observe/x.jsonl", "run_id": "human-x", "fight_id": "human-x#f000",
         "t_d": 4.5, "event": "before_big_hit", "zone": "ramp flat", "npc": 254000, "result": "killed", "y": -49.25}
    s = L.build_scene(c, msgs)
    (tmp / f"{s['scene_id']}.jsonl").write_text("\n".join(json.dumps(m) for m in msgs) + "\n", encoding="utf-8")
    return s


def temp_files(tmp: Path) -> None:
    L.LABEL_FILE, L.REVEALS, L.CLIPS = tmp / "labels.jsonl", tmp / "reveals.jsonl", tmp


def restore() -> None:
    L.LABEL_FILE, L.REVEALS, L.CLIPS = REAL


def payload(s, **kw):
    d = {"scene_id": s["scene_id"], "labeler_id": "tester", "duration_s": 30.0, "acceptable": ["guard"], "forbidden": ["attack"],
         "best": "guard", "confidence": "mid", "unsure": False, "no_good_action": False, "outside_set": [], "model_input_sufficient": True,
         "outside_input": [], "rationale": "휘두르는 중, 1.2 m", "evidence": ["target_state", "distance_m"]}
    d.update(kw)
    return d


def test_scene_separates_after() -> None:
    with tempfile.TemporaryDirectory() as d:
        temp_files(Path(d))
        try:
            s = human_scene(Path(d))
            assert s["schema"] == L.SCENE_SCHEMA and s["source"] == "human_demo" and s["code_commit"] is None
            assert s["obs"]["target_state"] == "swinging" and s["obs"]["distance_m"] == 1.2
            pressed = s["after"]["human_pressed"]
            assert [p["button"] for p in pressed] == ["B", "R1"], pressed                # after t_d → 'after' only
            assert [p["button"] for p in s["context"]["actor_did"]] == ["LB"]            # before t_d → context, raw
            assert s["after"]["my_hp_change_1_5s"] == -120
            flat = json.dumps({"obs": s["obs"], "context": s["context"], "allowed": s["allowed"]}, ensure_ascii=False)
            for k in ("human_pressed", "bot_logged", "fight_result", "my_hp_change_1_5s", "before_big_hit", "구르기"):
                assert k not in flat, k
            assert "weapon_reach_m" in s["missing"] and s["obs"]["weapon_reach_m"] is None
            assert "attack" in s["allowed"]                                              # unknown weapon → table bounds
            page = L.scene_for_page(s, "pre")
            for k in ("after", "event", "test_candidate", "selection", "mask_inputs"):
                assert k not in page, k
            assert "before_big_hit" not in json.dumps(page)                               # the event is worked out from the future
            full = L.scene_for_page(s, "full")
            assert full["event"] == "before_big_hit" and "after" in full
            pre = L.clip_msgs(s, "pre")
            assert max(m["rt"] for m in pre) <= s["t_d"]
            assert not any(k in m for m in pre for k in L.INTENT_KEYS)                    # no planned path / target from the bot
            assert [m for m in pre if m["type"] == "say"] == [{"rt": s["t_d"], "type": "say", "t": s["t_d"], "line": "F9 marker ▶ 결정 시점"}]
            assert max(m["rt"] for m in L.clip_msgs(s, "full")) > s["t_d"]
        finally:
            restore()
    print("ok  scene: state and context before t_d, actions/outcome/event only after the reveal, no bot plan on screen")


def test_human_roll_is_not_evade() -> None:
    """A human's B press (here a tap followed by anim 710 = a roll, as far as we can tell) stays an observed button.
    It is not a candidate, not an answer, and 'evade' (the bot's backstep style) is out for the reason that the bot's
    default style has no such move — not because the human rolled."""
    with tempfile.TemporaryDirectory() as d:
        temp_files(Path(d))
        try:
            s = human_scene(Path(d))
            b = s["after"]["human_pressed"][0]
            assert b["button"] == "B" and b["my_anim_after"] == 710 and "구르기" in b["guess"] and b["hold_s"] == 0.12, b
            assert "evade" not in s["allowed"]
            assert s["unavailable"]["evade"]["why"] == LS.NOT_IN_BOT
            assert "roll" not in LS.TACTICS and "구르기" not in LS.TACTICS
            assert set(s["allowed"]) | set(s["unavailable"]) == set(LS.TACTICS)
            # the labeler says: nothing in the bot's set fits, a roll would — stored as such, not as evade
            d1 = payload(s, acceptable=[], best=None, forbidden=["attack"], no_good_action=True, outside_set=["구르기"])
            ok, row = L.save_label(d1, s)
            assert ok, row
            assert row["no_good_action"] and row["outside_set"] == ["구르기"] and row["acceptable"] == [] and "evade" not in json.dumps(row)
            # a tactic name can't be smuggled in as 'a move the bot lacks', and the page's buttons are never copied
            assert L.validate_label(payload(s, outside_set=["evade"]), s)
            row2 = L.make_label(payload(s, human_pressed=s["after"]["human_pressed"], after=s["after"]), s)
            assert "evade" not in row2["acceptable"] and "human_pressed" not in row2 and "after" not in row2
        finally:
            restore()
    print("ok  human roll: kept as an observed B press (+anim, guess), never a candidate, never evade in a label")


def test_label_kinds_and_stage() -> None:
    with tempfile.TemporaryDirectory() as d:
        temp_files(Path(d))
        try:
            s = human_scene(Path(d))
            # three different 'no answer' kinds stay apart
            unsure = payload(s, acceptable=[], forbidden=[], best=None, unsure=True, unsure_reason="정보 부족")
            assert L.validate_label(unsure, s) == []
            assert any("different" in e for e in L.validate_label({**unsure, "no_good_action": True}, s))
            assert L.validate_label(payload(s, model_input_sufficient=False), s)          # must name what was needed
            needs = payload(s, model_input_sufficient=False, outside_input=["terrain", "my_anim"])
            assert L.validate_label(needs, s) == []
            for change, why in [({"acceptable": ["guard"], "forbidden": ["guard"]}, "both"), ({"best": "attack"}, "best"),
                                ({"acceptable": [], "forbidden": [], "best": None}, "best tactic"), ({"confidence": None}, "confidence"),
                                ({"unsure": True, "unsure_reason": "?"}, "unsure_reason"), ({"evidence": ["after.fight_result"]}, "evidence"),
                                ({"acceptable": ["fly"]}, "unknown"), ({"labeler_id": ""}, "labeler"),
                                ({"no_good_action": True}, "no acceptable"), ({"outside_input": ["mind_reading"]}, "outside_input")]:
                errs = L.validate_label(payload(s, **change), s)
                assert any(why in e for e in errs), (change, errs)
            # stage: no reveal before a first-pass label; after the reveal, saves are revisions and the primary stays
            ok, why = L.request_reveal(s["scene_id"], "tester")
            assert not ok and "1차" in why
            ok, first = L.save_label(payload(s), s)
            assert ok and first["stage"] == "pre_reveal" and first["label_source"] == "human_verified"
            ok, _ = L.request_reveal(s["scene_id"], "tester")
            assert ok and L.revealed(s["scene_id"], "tester")
            ok, second = L.save_label(payload(s, acceptable=["guard", "retreat"], forbidden=["attack"], best="retreat",
                                              model_input_sufficient=False, outside_input=["replay_motion"]), s)
            assert ok and second["stage"] == "post_reveal" and second["revision_of"] == first["labeled_at"]
            v = L.label_views(L.label_rows(s["scene_id"], "tester"))
            assert v["primary"]["acceptable"] == ["guard"] and v["final"]["acceptable"] == ["guard", "retreat"] and len(v["revisions"]) == 1
            assert not L.revealed(s["scene_id"], "someone_else")                         # per labeler
            lines = Path(d, "labels.jsonl").read_text(encoding="utf-8").splitlines()
            assert len(lines) == 2                                                         # appended, nothing overwritten
            L.LABEL_SOURCE = "ui_trial"                                                    # serve --labels-dir
            try:
                assert L.make_label(payload(s), s)["label_source"] == "ui_trial"
            finally:
                L.LABEL_SOURCE = "human_verified"
        finally:
            restore()
    assert not Path(str(REAL[0])).exists() or "tester" not in Path(str(REAL[0])).read_text(encoding="utf-8")
    print("ok  labels: unsure / nothing fits / model input not enough kept apart; first pass kept, later changes appended")


def test_why_not_covers_every_tactic() -> None:
    rng = random.Random(3)
    vals = {"distance_m": [None, 0.8, 1.5, 2.4, 6.0], "height_diff_m": [None, 0.0, 1.6], "weapon_reach_m": [None, 1.2, 1.6],
            "_sp_ok": [None, True, False], "other_swinging_near": [None, True, False], "target_one_hit": [False, True],
            "_reflex_on": [None, True], "_shield": [True, False], "_evade": [None, True, False], "estus_wanted": [None, True, False],
            "_arena": [None, True, False], "_may_retreat": [True, False], "_room": [None, True, False], "_backstab_on": [None, True, False],
            "_reach_max": [None, 2.3], "_reach_min": [None, 1.2]}
    for _ in range(3000):
        f = {k: rng.choice(v) for k, v in vals.items()}
        al, wn = LS.allowed(f), LS.why_not(f)
        assert set(al) | set(wn) == set(LS.TACTICS) and not set(al) & set(wn), (f, al, wn)
        assert all(w["why"] in (LS.NOT_IN_BOT, LS.RULE_BLOCKED, LS.UNOBSERVED) for w in wn.values())
    print("ok  every tactic is either a candidate or has one reason: not_in_bot / rule_blocked / unobserved")


def test_ramp_set_selection_and_shots() -> None:
    """Chosen-recording sets: every fight, ≤ 2 scenes with different events ≥ 3 s apart; shots after the decision are not
    on the first-pass page."""
    cands = [{"fight_id": f"r#f{f}", "t_d": f * 100 + i * 1.5, "event": ev}
             for f in range(6) for i, ev in enumerate(["swing", "swing", "opening", "far", "before_retreat"])]
    got = L.select_fights(cands, 2)
    per = {}
    for c in got:
        per.setdefault(c["fight_id"], []).append(c)
    assert set(per) == {f"r#f{f}" for f in range(6)}
    for cs in per.values():
        assert len(cs) <= 2 and len({c["event"] for c in cs}) == len(cs)
        assert len(cs) < 2 or abs(cs[0]["t_d"] - cs[1]["t_d"]) >= 3.0
        assert cs[0]["event"] == "before_retreat"                                   # rarer events first
    assert L.select_fights(cands, 2) == got
    sc = {"scene_id": "x", "shots": [{"dt": -1.0, "file": "a.jpg"}, {"dt": 0.0, "file": "b.jpg"}, {"dt": 1.5, "file": "c.jpg"}],
          "after": {}, "event": "swing"}
    assert [x["dt"] for x in L.scene_for_page(sc, "pre")["shots"]] == [-1.0, 0.0]
    assert [x["i"] for x in L.scene_for_page(sc, "full")["shots"]] == [0, 1, 2]
    print("ok  ramp set: every fight, ≤ 2 different scenes each; screenshots after the decision hidden before 'after'")


def test_one_scene_per_fight() -> None:
    cands = []
    for f in range(30):
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
    assert all(len(v) == 1 for v in per_fight.values())
    assert sum(c["zone"] == "ramp" for c in got) <= 8
    runs = {}
    for c in got:
        runs[c["run_id"]] = runs.get(c["run_id"], 0) + 1
    assert max(runs.values()) <= 4, runs
    assert L.select(cands, 20) == got
    print(f"ok  selection: {len(got)} scenes from {len(per_fight)} fights, ramp ≤ 8, ≤ 4 per run, reproducible")


if __name__ == "__main__":
    test_scene_separates_after()
    test_human_roll_is_not_evade()
    test_label_kinds_and_stage()
    test_why_not_covers_every_tactic()
    test_ramp_set_selection_and_shots()
    test_one_scene_per_fight()
