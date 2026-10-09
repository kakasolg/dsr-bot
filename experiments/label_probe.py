"""Label probe (docs/design-scene-expectations.md §2) — MoKa's human-verified scene labels (data/labels/*_labels.jsonl)
against what today's duel() picks when the scene's observation is rebuilt as a fake world. No game.

  python experiments/label_probe.py            agreement table + every disagreement
  python experiments/label_probe.py --json     one line per scene (for the design's expectation file draft)
  --basic                                      as run.py --basic (no backstab, no heavy) — the 10-01 … 10-06 runs

Rebuild (tests/duel_golden_test.run style, one decision): target npc · anim · distance · height · HP · our SP · our facing
error · its facing · one other foe beside us (swinging or not, from others_within_4_5m / other_swinging_near) · style ·
weapon (reach 1.6 → Battle Axe). Not rebuilt: NavMesh / arena / edge, Estus wanted, the swing's age, more than one other
foe, and the reflex (faked: off, and 'auto' = fires when the target swings within duel.NEAR — both shown). The scene's obs comes from radar replay, which
is not exactly what the bot saw (P-34: 85–94 % per feature) — a disagreement here is a candidate, not a verdict.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent.parent / "tests")]

import collections
import json
import math

import duel_golden_test as G
import laya_shadow as LS
from field_fakes import World
from souls import duel as D
from souls import moves as M
from souls import weapons

ROOT = _pl.Path(__file__).resolve().parent.parent
LABELS = ROOT / "data" / "labels"
SETS = ("pilot", "ramp", "boundary")


def rows(path):
    return [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()] if path.exists() else []


def usable() -> list[tuple[str, dict, dict]]:
    """(set, scene, last label) — human_verified, not unsure, some acceptable tactic, confidence not low."""
    out = []
    for name in SETS:
        scenes = {s["scene_id"]: s for s in rows(LABELS / f"{name}_scenes.jsonl")}
        last = {}
        for r in rows(LABELS / f"{name}_labels.jsonl"):
            last[r["scene_id"]] = r
        for sid, r in last.items():
            if (r.get("label_source") == "human_verified" and not r.get("unsure") and r.get("acceptable")
                    and r.get("confidence") != "low" and sid in scenes):
                out.append((name, scenes[sid], r))
    return out


class Grab:
    """Rides along as duel's advisor: the first rule that acted."""
    def __init__(self):
        self.rules = []

    def observe(self, F, T, name, out, payload=None):
        self.rules.append(name)

    def end(self, *a, **k):
        pass


STATE_ANIM = {"idle": -1, "swinging": 3003, "staggered": 3500, "downed": 9910, "getting_up": 9600, "other": 2000}


def anim_of(o: dict, sc: dict) -> int:
    """The scene's anim, or one standing for its state (boundary scenes keep only the state category)."""
    if o.get("target_anim") is not None:
        return o["target_anim"]
    return STATE_ANIM.get(o.get("target_state"), -1)


def decide(o: dict, reflex: bool, sc: dict | None = None):
    w = World(player=(0.0, -49.4, 0.0), sp=round(106 * (o.get("my_stamina_pct") or 1.0)))
    err = math.radians(o.get("facing_error_deg") or 0.0)
    w.player.heading = -math.pi + err
    h = o.get("distance_m") or 1.0
    npc = o.get("target_npc") or ((sc or {}).get("enemy") or {}).get("npc") or 254000
    c = w.add(2, 0x1002, npc, (0.0, -49.4 + (o.get("height_diff_m") or 0.0), h),
              hp=max(1, round(85 * (o.get("target_hp_pct") if o.get("target_hp_pct") is not None else 1.0))), max_hp=85,
              anim=anim_of(o, sc or {}))
    c.heading = math.pi if (o.get("target_facing_me_deg") or 0) > 90 else 0.0
    if (o.get("others_within_4_5m") or 0) > 0:
        w.add(3, 0x1003, 254000, (1.3, -49.4, 0.3), hp=75, anim=3003 if o.get("other_swinging_near") else 2000).heading = -math.pi / 2
    trace, grab = [], Grab()
    mv = G.Mv(w, trace)
    mv.tm.grip = lambda: None
    ticks = {"n": 0}

    def cancel():
        ticks["n"] += 1
        return ticks["n"] > 3                              # turning to face isn't a tactic — take the first one that is
    saved = {k: getattr(D, k) for k in ("_backstab", "_back_to_safe", "_separate", "_approach")}
    sleep = D.time.sleep
    D._backstab = D._back_to_safe = lambda *a, **k: "not_behind"
    D._separate, D._approach = (lambda *a, **k: "no_spot"), (lambda *a, **k: "stopped")
    D.time.sleep = lambda s: None
    try:
        D.duel(mv, weapons.BATTLE_AXE if (o.get("weapon_reach_m") or 0) >= 1.5 else weapons.BROADSWORD, 2, None,
               log=lambda line: None, cancel=cancel, reflex=G.Reflex(reflex, trace), style=o.get("fighting_style") or "guard",
               advisor=grab)
    except Exception as e:
        return f"error:{type(e).__name__}"
    finally:
        for k, v in saved.items():
            setattr(D, k, v)
        D.time.sleep = sleep
    f = {"_shield": (o.get("fighting_style") or "guard") == "guard", "_arena": None}
    tac = [LS.policy_tactic(r, f) for r in grab.rules]
    return next((t for t in tac if t), f"({grab.rules[0]})" if grab.rules else None)


def main() -> None:
    if "--basic" in _sys.argv:                             # run.py --basic: no backstab, no wall heavy / two-hand switch
        D.BACKSTAB, D.HEAVY = False, False
    out, tally = [], collections.Counter()
    for name, sc, lab in usable():
        o = sc["obs"]
        acc, forb = set(lab["acceptable"]), set(lab.get("forbidden") or [])
        swinging = (anim_of(o, sc) in M.ATTACK) and (o.get("distance_m") or 9) < D.NEAR   # the reflex shields against a swing this close
        pick = {False: decide(o, False, sc), True: decide(o, swinging, sc)}
        verdict = {rf: ("ok" if p in acc else "forbidden" if p in forb else "not_acceptable") for rf, p in pick.items()}
        aft = sc.get("after", {})
        bot = aft.get("bot_action_as_tactic") or {}                # pilot / ramp: what the bot logged around the moment
        bot_top = aft.get("bot_tactic") or (max(bot, key=bot.get) if bot else None)   # boundary: the bot's own rule that tick
        tally[name, verdict[False]] += 1
        tally["all", verdict[False]] += 1
        tally["all reflex auto", verdict[True]] += 1
        tally["all bot-logged", "ok" if bot_top in acc else "forbidden" if bot_top in forb else "not_acceptable" if bot_top else "none"] += 1
        out.append({"set": name, "scene_id": sc["scene_id"], "segment": sc.get("segment"), "npc": o.get("target_npc") or (sc.get("enemy") or {}).get("npc"),
                    "anim": anim_of(o, sc), "state": o.get("target_state"), "dist": o.get("distance_m"), "acceptable": sorted(acc), "forbidden": sorted(forb),
                    "best": lab.get("best"), "today": pick[False], "today_reflex": pick[True], "bot_logged": bot_top,
                    "verdict": verdict[False], "confidence": lab.get("confidence"), "rationale": lab.get("rationale")})
    if "--json" in _sys.argv:
        for r in out:
            print(json.dumps(r, ensure_ascii=False))
        return
    print(f"{len(out)} usable labels ({', '.join(f'{n} {sum(1 for r in out if r['set'] == n)}' for n in SETS)})")
    for key in ("pilot", "ramp", "boundary", "all", "all reflex auto", "all bot-logged"):
        row = {v: n for (k, v), n in tally.items() if k == key}
        tot = sum(row.values())
        print(f"  {key:15} " + " · ".join(f"{v} {n} ({n / tot:.0%})" for v, n in sorted(row.items(), key=lambda kv: -kv[1])))
    print("disagreements (today, reflex off):")
    for r in out:
        if r["verdict"] != "ok":
            print(f"  {r['set']:8} {r['scene_id']} {str(r['segment'])[:12]:12} {r['npc']} anim {r['anim']} {r['dist']} m | "
                  f"MoKa {r['acceptable']}{' forbid ' + str(r['forbidden']) if r['forbidden'] else ''} | today {r['today']} "
                  f"(reflex auto {r['today_reflex']}) | bot then {r['bot_logged']}")


if __name__ == "__main__":
    main()
