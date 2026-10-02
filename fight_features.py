"""What a fight tick looks like as numbers, and which of the bot's tactics its rules allow there — read-only.

  features(F, T)   the observed state of a duel tick (souls/duel.py Fight F, Tick T) as a flat dict
  allowed(f)       tactics the existing rule conditions permit in that state; why_not(f) says why each other one is out
  freeze(F, T)     a copy of what features() reads, taken before a rule runs (attack_audit.py)
  note_tactic(n)   Fight.note label → tactic (old fight logs, label_pilot.py)

Used by the labeling tool (label_pilot.py) and the attack audit (attack_audit.py). Nothing here touches the pad, Moves or
the rules. Moved out of laya_shadow.py when Laya was stopped (2026-10-02, ROADMAP 1-j) — the functions are unchanged.
Import is stdlib-only (souls.* are imported lazily).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ── tactics the bot already has (rule groups in souls/duel.py RULES) ──
TACTICS = {
    "attack": "Strike the target now with the weapon (light attack, kick on a raised shield, finishing blow, punish a stagger).",
    "guard": "Raise the shield and face the target; block its swing.",
    "evade": "Backstep out of the target's swing (two-handed style, no shield).",
    "approach": "Walk toward the target to get within weapon reach.",
    "hold_position": "Stay put, keep the target in front and let it come (or let stamina refill).",
    "heal": "Drink an Estus flask now, backing off a step first if the target is close.",
    "reposition": "Move to the prepared flat spot away from ledges before engaging.",
    "retreat": "Leave this fight: back off toward the bonfire, heal, and come back later.",
    "backstab": "Circle behind the target and backstab it.",
}
# rule name (RULES, without rule_/prep_) → tactic. None: not a tactic (turning to face, splitting a pair, evade-style wait) — not compared
RULE_TACTIC = {
    "separate": None, "finish_first": "attack", "face_first": None, "early_kick": "attack", "late_windup_block": "guard",
    "hit_first": "attack", "backstab_swing": "backstab", "reflex": "guard", "lure": "reposition", "edge": "reposition",
    "estus": "heal", "stagger_punish": "attack", "evade": None, "block": "guard", "downed": "guard",
    "wait_far": "hold_position", "approach": "approach", "finish": "attack", "stamina": "hold_position", "face": None,
    "backstab": "backstab", "attack": "attack",
}


def policy_tactic(rule: str, f: dict):
    """What the rule did, as a tactic — some rules do different things per style (golden check 2026-10-01: with the
    backstep style the reflex backsteps and moves.guard is ignored; rule_edge without an arena only guards in place)."""
    shield = f.get("_shield") is not False
    if rule == "reflex":
        return "guard" if shield else "evade"
    if rule in ("downed", "late_windup_block"):
        return "guard" if shield else "hold_position"
    if rule == "edge" and not f.get("_arena"):
        return "guard" if shield else "hold_position"
    return RULE_TACTIC.get(rule)


# fight endings that are a decision (Field backs off and heals) — the rest (killed, timeout, me_dead …) are outcomes
END_TACTIC = {"low_hp": "retreat", "losing": "retreat", "crowd": "retreat"}


def _r(v, n=2):
    return None if v is None else round(float(v), n)


def target_state(a, age, M) -> str:
    """Anim id → what can be seen of the target now. Ranges from souls/moves.py; no guess at what it will do next."""
    a = -1 if a is None else a
    if 9000 <= a < 9100:
        return "asleep"
    if a == M.GUARD_BROKEN:
        return "guard_broken"
    if a in M.STAGGER:
        return "staggered"
    if a in M.DOWNED:
        return "getting_up" if a == M.GETTING_UP else "downed"
    if a in M.ATTACK:
        return "swinging"
    return "idle" if a == -1 else "other"


def features(F, T) -> dict:
    """Observed numbers of this tick (Fight/Tick of souls/duel.py). Reads only — no Moves, no pad, no reflex calls."""
    from souls import duel as D, foes as foes_, moves as M
    s, p, c = T.s, T.p, T.c
    w, foe = F.weapon, F.foe or foes_.of(c.npc_param)
    others = [x for x in s.hostile(4.5) if x.ptr != F.ptr and x.hp > 0 and not (9000 <= (x.anim or 0) < 9100)
              and M.horiz(p, x) < 4.5]
    care = F.care
    max_hp, max_sp = p.max_hp or 0, getattr(p, "max_sp", 0) or 0
    return {
        "my_hp_pct": _r(p.hp / max_hp) if max_hp and p.hp is not None else None,
        "my_stamina_pct": _r(p.sp / max_sp) if max_sp and p.sp is not None else None,
        "stamina_for_attack": (p.sp or 0) >= w.sp_min,
        "target_kind": "ranged" if foe.ranged else foe.kind,
        "target_state": target_state(T.a, getattr(T, "age", None), M),
        "target_swing_age_s": _r(getattr(T, "age", None)) if T.a in M.ATTACK else None,
        "target_hp_pct": _r(c.hp / c.max_hp) if c.max_hp else None,
        "target_one_hit": c.hp <= D.FINISH_HP,
        "distance_m": _r(T.h, 1),
        "height_diff_m": _r(T.dy, 1),
        "weapon_reach_m": w.reach,
        "in_reach": T.h <= w.reach,
        "facing_error_deg": round(abs(math_degrees(M.rel_angle(p, c)))) if p.heading is not None else None,
        "target_facing_me_deg": round(abs(math_degrees(M.rel_angle(c, p)))) if c.heading is not None else None,   # 0 = faces me
        "others_within_4_5m": len(others),
        "other_swinging_near": D._other_swinging(s, F.ptr),
        "estus_wanted": bool(care.wants(s)) if care is not None else False,
        "estus_opening": D.opening(s, F.ptr),
        "taken_this_fight_pct": _r(max(0, (F.hp_start or 0) - (F.hp_min or 0)) / max_hp) if max_hp else None,
        "fighting_style": F.style.name,                     # the bot's own settings, not a guess about the foe
        "let_it_come": bool(F.wait_far),
        # mask inputs (not sent to Laya as state)
        "_sp_ok": (p.sp or 0) >= w.sp_min or (c.hp <= D.FINISH_HP and (p.sp or 0) >= D.FINISH_SP),
        "_shield": bool(F.style.shield),
        "_evade": bool(F.style.evade),
        "_reflex_on": F.reflex is not None,
        "_arena": F.arena is not None and F.nm is not None,
        "_may_retreat": (F.low_hp or 0) > 0,
        "_room": bool(getattr(T, "room", False)),
    }


def math_degrees(rad: float) -> float:
    return rad * 57.29577951308232


def allowed(f: dict) -> list:
    """Tactics the existing rules would permit in this state — conditions copied from the rules that do them
    (souls/duel.py). Laya is only ever asked to choose among these. Unknown (None) inputs from old logs count as permitted,
    except where noted."""
    h, dy, reach = f.get("distance_m"), f.get("height_diff_m"), f.get("weapon_reach_m")
    # weapon unknown (human demos): attack up to the longest reach we know, approach beyond the shortest (label_pilot sets these)
    reach_hi, reach_lo = reach or f.get("_reach_max"), reach or f.get("_reach_min")
    out = []
    near = h is not None and reach_hi is not None and h <= reach_hi + 0.3 and (dy is None or abs(dy) <= 1.0)
    # hit_first / stagger_punish: reach, height, SP, nobody else swinging. finish_first ignores the other swing (one-hit kill);
    # rule_attack has no swing check of its own — the reflex (always on in the bot) takes those ticks first
    calm = f.get("other_swinging_near") is not True or f.get("target_one_hit") or f.get("_reflex_on") is False
    if near and f.get("_sp_ok") is not False and calm:
        out.append("attack")
    if f.get("_shield") is not False:
        out.append("guard")                                    # block / reflex: shield styles only
    if f.get("_evade"):
        out.append("evade")                                    # reflex of the backstep style
    if h is not None and reach_lo is not None and h > reach_lo:
        out.append("approach")
    out.append("hold_position")                                # wait_far / stamina: always possible
    if f.get("estus_wanted"):
        out.append("heal")                                     # estus: Care.wants (Estus left, HP under FIGHT_HEAL)
    if f.get("_arena"):
        out.append("reposition")                               # lure / edge: need arena + NavMesh
    if f.get("_may_retreat") is not False:
        out.append("retreat")                                  # low_hp 0 = desperate (fight to the end): no retreat
    if f.get("_room"):
        out.append("backstab")                                 # T.room: BACKSTAB on (not --basic), room behind, one-on-one
    return out


NOT_IN_BOT, RULE_BLOCKED, UNOBSERVED = "not_in_bot", "rule_blocked", "unobserved"


def why_not(f: dict) -> dict:
    """For every tactic allowed() leaves out, why: not_in_bot (the bot has no such move in this style/setting),
    rule_blocked (the rules' own conditions say no in this state), unobserved (an input the condition needs is missing).
    Walks the same conditions as allowed() — keep the two together. Moves the bot doesn't have at all (rolling) are not
    tactics and never appear here."""
    al = set(allowed(f))
    h, dy, reach = f.get("distance_m"), f.get("height_diff_m"), f.get("weapon_reach_m")
    reach_hi, reach_lo = reach or f.get("_reach_max"), reach or f.get("_reach_min")
    out = {}
    if "attack" not in al:
        if h is None or reach_hi is None:
            out["attack"] = (UNOBSERVED, "거리 또는 무기 거리 모름")
        elif h > reach_hi + 0.3:
            out["attack"] = (RULE_BLOCKED, f"닿는 거리 밖 ({h} m > {reach_hi} + 0.3)")
        elif dy is not None and abs(dy) > 1.0:
            out["attack"] = (RULE_BLOCKED, f"높이 차 {dy} m (1 m 넘음)")
        elif f.get("_sp_ok") is False:
            out["attack"] = (RULE_BLOCKED, "SP가 무기 sp_min보다 적음")
        else:
            out["attack"] = (RULE_BLOCKED, "2.5 m 안 다른 적이 휘두르는 중")
    if "guard" not in al:
        out["guard"] = (NOT_IN_BOT, "이 스타일은 방패를 안 씀")
    if "evade" not in al:
        out["evade"] = (NOT_IN_BOT, "백스텝 회피는 backstep 스타일에만 있음") if f.get("_evade") is False else (UNOBSERVED, "스타일 모름")
    if "approach" not in al:
        out["approach"] = (UNOBSERVED, "거리 또는 무기 거리 모름") if h is None or reach_lo is None else (RULE_BLOCKED, "이미 닿는 거리 안")
    if "heal" not in al:
        out["heal"] = (UNOBSERVED, "에스트 수 모름") if f.get("estus_wanted") is None else (RULE_BLOCKED, "에스트 없음 또는 HP 60 % 이상")
    if "reposition" not in al:
        out["reposition"] = (UNOBSERVED, "끌어올 자리(arena) 기록 없음") if f.get("_arena") is None else (RULE_BLOCKED, "이 싸움엔 정해 둔 자리 없음")
    if "retreat" not in al:
        out["retreat"] = (RULE_BLOCKED, "끝까지 싸우기(desperate) — 후퇴 없음")
    if "backstab" not in al:
        if f.get("_backstab_on") is False:
            out["backstab"] = (NOT_IN_BOT, "이 실행에서 뒤잡기 꺼짐 (--basic)")
        elif f.get("_room") is None:
            out["backstab"] = (UNOBSERVED, "뒤 공간·1:1 여부 모름")
        else:
            out["backstab"] = (RULE_BLOCKED, "뒤잡기 조건 아님 (망자·3.5 m 안·혼자·뒤 공간)")
    return {k: {"why": w, "detail": d} for k, (w, d) in out.items()}


# ── one frozen input, one payload (attack_audit.py) ──
FEATURE_SCHEMA_VERSION = 1      # bump when features()/allowed()/why_not() or the frozen attributes change
F_ATTRS = ("weapon", "foe", "ptr", "care", "hp_start", "hp_min", "style", "wait_far", "reflex", "arena", "nm", "low_hp")
T_ATTRS = ("h", "dy", "a", "age", "room")       # + s, p, c (copied snapshot)
_IMMUTABLE = (int, float, str, bool, bytes, type(None))


class _Present:
    """Stands in for a live object that features() only tests for `is not None` (reflex thread, arena, NavMesh)."""
    __slots__ = ()

    def __repr__(self):
        return "<present>"


PRESENT = _Present()


class FrozenView:
    """Plain holder — attributes are set by freeze()."""


def is_immutable(v, _depth: int = 0) -> bool:
    if isinstance(v, _IMMUTABLE) or v is PRESENT:
        return True
    if isinstance(v, (tuple, frozenset)):
        return _depth < 4 and all(is_immutable(x, _depth + 1) for x in v)
    params = getattr(type(v), "__dataclass_params__", None)
    if params is not None and params.frozen:
        return _depth < 4 and all(is_immutable(getattr(v, k), _depth + 1) for k in v.__dataclass_fields__)
    return False


def _plain_copy(obj):
    """A new object of the same class holding only obj's immutable attributes (a Field.Care keeps `left`, not its Field)."""
    if obj is None:
        return None
    new = object.__new__(type(obj))
    for k, v in vars(obj).items():
        if is_immutable(v):
            setattr(new, k, v)
    return new


def copy_snapshot(s):
    """Snapshot with its own player/chars copies (Chr fields are numbers/strings) → (copy, {id(live chr): copy})."""
    import copy as copy_
    s2 = copy_.copy(s)
    s2.player = copy_.copy(s.player)
    s2.chars = [copy_.copy(c) for c in s.chars]
    ids = {id(s.player): s2.player}
    ids.update({id(c): c2 for c, c2 in zip(s.chars, s2.chars)})
    return s2, ids


def freeze(F, T, snap_copy=None) -> tuple[FrozenView, FrozenView]:
    """What features(F, T) reads, copied now — the rule about to run may change F/T or the objects behind them; features()
    on the result never reads the live objects again (tests/attack_audit_test.py checks both). snap_copy: copy_snapshot(T.s)
    already made for this tick (the snapshot is the same for every rule of a tick)."""
    import copy as copy_
    fv, tv = FrozenView(), FrozenView()
    for k in F_ATTRS:
        v = getattr(F, k, None)
        if k in ("reflex", "arena", "nm"):
            v = None if v is None else PRESENT
        elif k == "care":
            v = _plain_copy(v)
        elif not is_immutable(v):
            v = copy_.deepcopy(v)
        setattr(fv, k, v)
    s2, ids = snap_copy if snap_copy is not None else copy_snapshot(T.s)
    tv.s = s2
    tv.p = ids.get(id(T.p)) or copy_.copy(T.p)
    tv.c = ids.get(id(T.c)) or copy_.copy(T.c)
    for k in T_ATTRS:
        if k in T.__dict__:
            v = T.__dict__[k]
            setattr(tv, k, v if is_immutable(v) else copy_.deepcopy(v))
    return fv, tv


_SCHEMA_IDS = None


def schema_ids() -> dict:
    """Identifies the exact feature code: an analyzer drops rows whose ids differ from the run header's."""
    global _SCHEMA_IDS
    if _SCHEMA_IDS is None:
        import hashlib
        import inspect
        src = "".join(inspect.getsource(f) for f in (features, target_state, allowed, why_not, freeze, copy_snapshot, _plain_copy))
        sha = hashlib.sha256(src.encode("utf-8")).hexdigest()
        _SCHEMA_IDS = {"feature_schema_version": FEATURE_SCHEMA_VERSION, "features_src_sha": sha,
                       "code_path": f"fight_features.decision_payload@{sha[:12]}"}
    return dict(_SCHEMA_IDS)


def canonical_json(d: dict) -> str:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def decision_payload(fv, tv) -> dict:
    """features() once, on frozen inputs → the payload an audit row carries."""
    import hashlib
    f = features(fv, tv)
    fj = canonical_json(f)
    ids = schema_ids()
    return {"feat": f, "feat_json": fj, "feat_sha256": hashlib.sha256(fj.encode("utf-8")).hexdigest(),
            "feature_keys_sha": hashlib.sha256(",".join(sorted(f)).encode("utf-8")).hexdigest()[:16],
            "allowed": allowed(f), "why_not": why_not(f), **ids}


# Fight.note labels → tactic (souls/duel.py). None = not a tactic (turning, splitting, explaining why no backstab)
NOTE_TACTIC = [("막으며다가감", "guard"), ("막기", "guard"), ("반사", "guard"), ("늦은windup막기", "guard"), ("누움대기", "guard"),
               ("먼저치기", "attack"), ("마무리", "attack"), ("휘청반격", "attack"), ("휘청돌기", "attack"), ("빠른발차기", "attack"),
               ("백스텝공격", "attack"), ("뒤치기", "attack"), ("light", "attack"), ("heavy", "attack"), ("kick", "attack"),
               ("붙기:", "approach"), ("기다림", "hold_position"), ("안옴→", "hold_position"), ("SP회복", "hold_position"),
               ("끌어오기:", "reposition"), ("자리옮김:", "reposition"), ("가장자리방어", "guard"),   # edge without arena: shield up in place
               ("에스트", "heal"), ("백스텝", "heal"), ("뒤잡기:", "backstab"),
               ("뒤잡기안함", None), ("방향", None), ("돌기", None), ("떼어놓기:", None), ("피함대기", None)]


def note_tactic(name: str):
    for pre, t in NOTE_TACTIC:
        if name.startswith(pre):
            return t
    return None
