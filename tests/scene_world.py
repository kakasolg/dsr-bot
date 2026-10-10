"""A fight scene as a few readable values → today's duel() decision (docs/design-scene-expectations.md 3.1). No game.

Used by tests/duel_expect_test.py (tests/expect/duel.jsonl) and by `python tests/scene_world.py labels`, which drafts
expectation lines from MoKa's labels (data/labels/). The fakes (Mv, Reflex) are duel_golden_test's.

situation keys (all optional except foe):
  foe 254010 · anim -1 · anim_seq [3003, -1] (one anim per tick — a swing that ends) · dist 1.2 m · dy 0.0 ·
  foe_hp 1.0 (share of 85) · my_sp 1.0 (share of 106) · facing_err 0° (our body off the foe) · foe_facing 0° (180 = back to us) ·
  others [{"npc": 254000, "anim": 3003, "x": 1.3, "z": 0.3}] (metres from us; foe stands at x 0, z dist) ·
  style "guard" · weapon "battle_axe"|"broadsword" · flags {"BACKSTAB": false, "HEAVY": false} (duel module flags, e.g. --basic) ·
  reflex "auto" (shields when a foe swings within duel.NEAR) | "off" | "on" · age 0.3 (seconds since the swing began, as the
  reflex reports it) · wait_far false · room true (floor behind the foe for a backstab) · ticks 4

decide(situation) → {"tactic": first tactic (laya_shadow.policy_tactic; turning to face isn't one), "rules": [rule per tick],
                     "trace": [Moves calls]}
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
import math

import duel_golden_test as G
import laya_shadow as LS
from field_fakes import World
from souls import duel as D
from souls import moves as M
from souls import weapons

WEAPONS = {"battle_axe": weapons.BATTLE_AXE, "broadsword": weapons.BROADSWORD}
FLAGS = ("BACKSTAB", "HEAVY")
MAX_HP, MAX_SP = 85, 106


class Reflex(G.Reflex):
    """golden's fake reflex, with the swing age a scene gives and 'auto' = shield only when a foe swings within duel.NEAR."""
    def __init__(self, mode: str, age: float, trace: list):
        super().__init__(mode == "on", trace)
        self.mode, self.age, self._start = mode, age, {2: 1.0}

    def attack_age(self, ptr):
        return self.age

    def tick(self, s):
        if self.mode != "auto":
            return super().tick(s)
        p = s.player
        fire = any((c.anim or -1) in M.ATTACK and M.horiz(p, c) < D.NEAR for c in s.chars if c.hp > 0)
        if fire:
            self.t.append(("reflex",))
        return fire


class Grab:
    """Rides along as duel's advisor: every rule that acted, in order."""
    def __init__(self):
        self.rules = []

    def observe(self, F, T, name, out, payload=None):
        self.rules.append(name)

    def end(self, *a, **k):
        pass


def decide(sc: dict) -> dict:
    w = World(player=(0.0, -49.4, 0.0), sp=round(MAX_SP * sc.get("my_sp", 1.0)), max_sp=MAX_SP)
    w.player.heading = -math.pi + math.radians(sc.get("facing_err", 0.0))
    seq = sc.get("anim_seq") or [sc.get("anim", -1)]
    c = w.add(2, 0x1002, sc["foe"], (0.0, -49.4 + sc.get("dy", 0.0), sc.get("dist", 1.2)),
              hp=max(1, round(MAX_HP * sc.get("foe_hp", 1.0))), max_hp=MAX_HP, anim=seq[0])
    c.heading = math.radians(sc.get("foe_facing", 0.0))            # 0: facing us (−z); π: its back to us
    for i, o in enumerate(sc.get("others", [])):
        x = w.add(3 + i, 0x1003 + i, o.get("npc", 254000), (o.get("x", 1.3), -49.4, o.get("z", 0.3)),
                  hp=o.get("hp", 75), anim=o.get("anim", -1))
        x.heading = -math.pi / 2
    trace, grab = [], Grab()
    mv = G.Mv(w, trace)
    mv.tm.grip = lambda: None
    tick = {"n": 0}
    ticks = sc.get("ticks", 4)

    def cancel():                                                  # also steps the scene: the foe's anim per tick
        n = tick["n"]
        tick["n"] += 1
        c.anim = seq[min(n, len(seq) - 1)]
        return n >= ticks
    saved = {k: getattr(D, k) for k in ("_backstab", "_back_to_safe", "_separate", "_approach", "_room_behind")}
    flags = {k: getattr(D, k) for k in FLAGS}
    sleep = D.time.sleep
    rec = lambda name, ret: (lambda *a, **k: (trace.append((name,)), ret)[1])
    D._backstab, D._back_to_safe = rec("backstab", "not_behind"), rec("back_to_safe", None)
    D._separate, D._approach = rec("separate", "no_spot"), rec("approach", "stopped")
    D._room_behind = lambda nm, p, c_, r=1.0: sc.get("room", True)
    D.time.sleep = lambda s: None
    for k, v in (sc.get("flags") or {}).items():
        setattr(D, k, v)
    try:
        r = D.duel(mv, WEAPONS[sc.get("weapon", "battle_axe")], 2, None, log=lambda line: None, cancel=cancel,
                   reflex=Reflex(sc.get("reflex", "auto"), sc.get("age", 0.3), trace), style=sc.get("style", "guard"),
                   wait_far=sc.get("wait_far", False), advisor=grab)
        result = r.result
    except Exception as e:                                         # a crash is an answer too — it fails the scene
        result = f"error:{type(e).__name__}: {e}"
    finally:
        for k, v in saved.items():
            setattr(D, k, v)
        for k, v in flags.items():
            setattr(D, k, v)
        D.time.sleep = sleep
    f = {"_shield": sc.get("style", "guard") == "guard", "_arena": None}
    tactic = next((t for t in (LS.policy_tactic(r_, f) for r_ in grab.rules) if t), None)
    return {"tactic": tactic, "rules": grab.rules, "trace": trace, "result": result}


def judge(sc: dict, expect: dict) -> tuple[bool, str, dict]:
    """→ (meets the expectation, why not, decision). expect: acceptable / forbidden (the first tactic), first_rule, has_rule
    (acts on some tick — e.g. after_swing on the tick the swing ends), not_rules (on no tick), trace_has (a Moves call)."""
    d = decide(sc)
    why = []
    acc, forb = expect.get("acceptable"), expect.get("forbidden") or []
    if acc is not None and d["tactic"] not in acc:
        why.append(f"tactic {d['tactic']} not in {acc}")
    if d["tactic"] in forb:
        why.append(f"tactic {d['tactic']} forbidden")
    if expect.get("first_rule") and (d["rules"][:1] or [None])[0] != expect["first_rule"]:
        why.append(f"first rule {(d['rules'][:1] or [None])[0]} ≠ {expect['first_rule']}")
    if expect.get("has_rule") and expect["has_rule"] not in d["rules"]:
        why.append(f"rule {expect['has_rule']} never acted ({d['rules']})")
    bad = [r for r in d["rules"] if r in (expect.get("not_rules") or [])]
    if bad:
        why.append(f"rule {bad[0]} must not act")
    if expect.get("trace_has") and not any(t and t[0] == expect["trace_has"] for t in d["trace"]):
        why.append(f"no {expect['trace_has']} in the trace")
    if str(d["result"]).startswith("error"):
        why.append(d["result"])
    return not why, "; ".join(why), d


# ── drafts from MoKa's labels (design 3.5) ───────────────────────────────────────────────────────────────────────────

STATE_ANIM = {"idle": -1, "swinging": 3003, "staggered": 3500, "downed": 9910, "getting_up": 9600, "other": 2000}
LABELS = _pl.Path(__file__).resolve().parent.parent / "data" / "labels"
# runs whose settings are known from the record (ROADMAP 1-i: the boundary set is a1–a3 = clear-ramp --basic --laya-shadow)
SET_FLAGS = {"boundary": {"BACKSTAB": False, "HEAVY": False}, "ramp": {"BACKSTAB": False, "HEAVY": False}}


def from_obs(obs: dict, scene: dict, flags: dict | None) -> dict:
    """A label scene's observation → situation (what can't be rebuilt — NavMesh, Estus, swing age, more than one other
    foe — is left at the defaults)."""
    anim = obs.get("target_anim")
    sc = {"foe": obs.get("target_npc") or (scene.get("enemy") or {}).get("npc") or 254000,
          "anim": anim if anim is not None else STATE_ANIM.get(obs.get("target_state"), -1),
          "dist": obs.get("distance_m") or 1.0, "dy": obs.get("height_diff_m") or 0.0,
          "foe_hp": obs.get("target_hp_pct") if obs.get("target_hp_pct") is not None else 1.0,
          "my_sp": obs.get("my_stamina_pct") if obs.get("my_stamina_pct") is not None else 1.0,
          "facing_err": obs.get("facing_error_deg") or 0.0,
          "foe_facing": 180.0 if (obs.get("target_facing_me_deg") or 0) > 90 else 0.0,
          "weapon": "battle_axe" if (obs.get("weapon_reach_m") or 0) >= 1.5 else "broadsword",
          "style": obs.get("fighting_style") or "guard", "reflex": "auto"}
    if obs.get("target_swing_age_s") is not None:
        sc["age"] = obs["target_swing_age_s"]
    if (obs.get("others_within_4_5m") or 0) > 0:
        sc["others"] = [{"npc": 254000, "anim": 3003 if obs.get("other_swinging_near") else 2000, "x": 1.3, "z": 0.3}]
    if flags:
        sc["flags"] = dict(flags)
    return sc


def label_drafts() -> list[dict]:
    """Expectation lines for blind labels (not review_bot — those kept the bot's pre-filled answer) whose rebuilt decision is
    the bot's own logged one that tick (so the rebuild can be trusted for that scene). status: pass if today's choice is
    allowed, known_fail:P-33 for stagger scenes it isn't (the open decision), else review."""
    rows = lambda f: [json.loads(x) for x in open(f, encoding="utf-8") if x.strip()] if f.exists() else []
    out = []
    for name, flags in SET_FLAGS.items():
        scenes = {s["scene_id"]: s for s in rows(LABELS / f"{name}_scenes.jsonl")}
        last = {}
        for r in rows(LABELS / f"{name}_labels.jsonl"):
            last[r["scene_id"]] = r
        for sid, lab in sorted(last.items()):
            sc0 = scenes.get(sid)
            if (sc0 is None or lab.get("label_source") != "human_verified" or lab.get("unsure") or not lab.get("acceptable")
                    or lab.get("confidence") == "low" or lab.get("mode") == "review_bot"):
                continue
            bot = (sc0.get("after") or {}).get("bot_tactic")
            sit = from_obs(sc0["obs"], sc0, flags)
            d = decide(sit)
            if bot is None or d["tactic"] != bot:
                continue                                           # rebuild ≠ what the bot did — needs an exact-input scene
            exp = {"acceptable": sorted(lab["acceptable"])}
            if lab.get("forbidden"):
                exp["forbidden"] = sorted(lab["forbidden"])
            ok = d["tactic"] in exp["acceptable"] and d["tactic"] not in exp.get("forbidden", [])
            status = "pass" if ok else "known_fail:P-33" if sit["anim"] in M.STAGGER else "review"
            out.append({"id": f"{name}-{sid}", "source": {"kind": "label", "ref": f"{name}:{sid}", "labeler": lab.get("labeler_id"),
                        "date": (lab.get("labeled_at") or "")[:10], "mode": lab.get("mode") or "blind", "confidence": lab.get("confidence")},
                        "situation": sit, "expect": exp, "status": status,
                        "why": (lab.get("rationale") or "") + (f" (today {d['tactic']})" if not ok else "")})
    return out


if __name__ == "__main__":
    if _sys.argv[1:2] == ["labels"]:
        for row in label_drafts():
            print(json.dumps(row, ensure_ascii=False))
    else:
        print(__doc__)
