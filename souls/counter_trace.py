"""Counter trace — why rule_after_swing (duel.py) thought the foe's swing was over, whom it hit, and what reached the pad.
Record only: nothing here is read back by the fight, every hook swallows its own errors, and nothing runs while ctl is off
(run.py --ctl). Records go into the run's existing .ctl.jsonl as k="dec.counter" (no file or writer of its own), so they
share ctl's seq with the pad records: the pad lines whose seq falls between an "intent" and its "outcome" are the inputs
sent during that strike (counter_report.py resolves them offline).

  ev = fight_start · target · tick-less events below (one record each) · fight_end
       window_open   the end of a swing was detected: basis "a" (age past the limit, swing_over) or "b" (target anim left 3000–3499)
       eval          rule_after_swing ran inside a window: outcome strike | blocked (first failing condition) | turn_only
                     — repeated identical blocked evals are folded (n, first/last seq; first/last tick time)
       not_evaluated a window was open but an earlier rule acted, so rule_after_swing did not run (folded per preempting rule)
       intent        right before the strike call (kick_combo / light): kind, presses intended, target, frozen decision state
       outcome       right after the call returned (or raised): Hit fields — the pad link is done offline by seq
       window_expired  a window passed AFTER_SWING_S without a strike (once per window)
       window_consumed the rule cleared the window right before striking

What the state copies are: the values the rule itself read this tick (no extra rule / face / swing_over call, no extra clock
read — the tick's T.now is the decision time). A condition the rule's short-circuit never reached is "not_evaluated".
Ownership (`*_from`) is metadata the rule now stores next to `_aprev` / `_swing_end_t` / `_swing_aged`: which target ptr the
value came from. Scenes recorded before this have no owner → "unknown".

Limits (stated, not filled in): the bot snapshot has no animation play time, hitbox state or verified TAE link — those fields
are null with a reason. `observed_id_age` = wall time since the reflex first saw this attack id on this foe; the same id
restarting is not detectable from it.
"""
from __future__ import annotations

import weakref

import ctl

from . import moves as M

SCHEMA = "dsr-counter-trace/0.1"
NEAR_KEEP_R = 6.0        # chars kept in a record: within this (= duel.SINGLE_HIT_R, the widest radius rule_after_swing reads)
# 운영 설계값(정책 상수 아님): 한 싸움에서 같은 blocked/not_evaluated 묶음이 이만큼 쌓이면 레코드를 내보내고 새로 센다
FOLD_MAX = 200

NO_ANIM_TIME = "not in telemetry.Chr: the bot snapshot reads no animation play time"
NO_HITBOX = "not in telemetry.Chr: the bot snapshot reads no hitbox state (+0x2E0 is read only by tae_verify probes)"
NO_TAE = "not linked at decision time; raw id only — AnimationIDOffset not applied, TAE runtime-checked only for c2540 3000"
RESTART = "same attack id restarting is not detectable (reflex starts the clock only when the id changes)"

_state: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
stats = {"emitted": 0, "errors": 0}


def _st(F) -> dict:
    st = _state.get(F)
    if st is None:
        st = _state[F] = {"tick": 0, "ptr": None, "fold": None, "expired_for": None, "win": None, "dec": 0}
    return st


def _emit(ev: str, **f) -> None:
    try:
        ctl.emit("dec.counter", schema=SCHEMA, ev=ev, **f)
        stats["emitted"] += 1
    except Exception:
        stats["errors"] += 1


def _chr(c, p=None) -> dict | None:
    if c is None:
        return None
    d = {"ptr": c.ptr, "npc": c.npc_param, "anim": c.anim, "hp": c.hp, "x": round(c.x, 3), "y": round(c.y, 3), "z": round(c.z, 3)}
    if p is not None:
        d["h"] = round(M.horiz(p, c), 3)
    return d


def _snap(s) -> dict | None:
    if s is None:
        return None
    return {"t": getattr(s, "t", None), "fseq": getattr(s, "fseq", None), "pc": getattr(s, "pc", None)}


def _foe_cfg(foe) -> dict:
    if foe is None:
        return {"name": None}
    from . import foes as foes_
    land = getattr(foe, "windup_land_s", None)
    return {"name": foe.name, "unknown": foe is foes_.UNKNOWN, "windup": list(getattr(foe, "windup", ())),
            "windup_act_s": getattr(foe, "windup_act_s", None), "windup_land_s": land,
            "unblockable": list(getattr(foe, "unblockable", ())), "kick_when_idle": getattr(foe, "kick_when_idle", None),
            "punish_hits": getattr(foe, "punish_hits", None)}


def _limit(foe, a) -> dict:
    """The limit swing_over applies to (foe, a) — the same constants it reads, worked out here without calling it."""
    from . import duel as D
    if a is None or a not in M.ATTACK:
        return {"limit_s": None, "why": "not an attack id"}
    if a in getattr(foe, "unblockable", ()):
        return {"limit_s": None, "why": "unblockable: never over by age"}
    land = getattr(foe, "windup_land_s", None)
    if land and a in getattr(foe, "windup", ()):
        return {"limit_s": round(max(D.SWING_S, land + D.LAND_PAD), 3), "why": "windup: max(SWING_S, land + LAND_PAD)"}
    return {"limit_s": D.SWING_S, "why": "SWING_S"}


def _near(s, p, ptr, reflex, now) -> list:
    """Every hostile within NEAR_KEEP_R as the rule's snapshot had it, with the reflex's observed id age (a dict read)."""
    out = []
    try:
        starts = getattr(reflex, "_start", {}) or {}
        for c in s.hostile(NEAR_KEEP_R + 1.0):
            if c.ptr == ptr:
                continue
            d = _chr(c, p)
            st = starts.get(c.ptr)
            d["observed_id_age"] = None if st is None or (c.anim or -1) not in M.ATTACK else round(now - st, 3)
            out.append(d)
    except Exception:
        stats["errors"] += 1
    return out


def research() -> dict:
    return {"anim_time": None, "anim_time_why": NO_ANIM_TIME, "hitbox": None, "hitbox_why": NO_HITBOX,
            "tae": None, "tae_why": NO_TAE, "id_restart": RESTART}


# ── hooks called from duel.duel() — only when ctl.on() ──

def fight_start(F) -> None:
    try:
        st = _st(F)
        st["ptr"] = F.ptr
        _emit("fight_start", ptr=F.ptr, gen=getattr(getattr(F, "shadow", None), "gen", None))
    except Exception:
        stats["errors"] += 1


def tick(F, T) -> None:
    """Before RULES: count ticks, note a target change (the previous ptr and the stale swing state it leaves behind)."""
    try:
        st = _st(F)
        st["tick"] += 1
        if F.ptr != st["ptr"]:
            _flush(st)
            c = T.c
            _emit("target", tick=st["tick"], snap=_snap(T.s), prev_ptr=st["ptr"], ptr=F.ptr, npc=getattr(c, "npc_param", None),
                  orig_ptr=F.orig_ptr, owners=_owners(F))
            st["ptr"] = F.ptr
    except Exception:
        stats["errors"] += 1


def after_rules(F, T, name: str | None, order: list) -> None:
    """After RULES picked `name`: if a window was open and that rule comes before rule_after_swing, the rule never ran."""
    try:
        if name is None or "after_swing" not in order:
            return
        end_t = F.__dict__.get("_swing_end_t")
        if end_t is None or order.index(name) >= order.index("after_swing"):
            return
        from . import duel as D
        if T.now - end_t > D.AFTER_SWING_S:
            return
        _fold(_st(F), "not_evaluated", {"by": name, "ptr": F.ptr, "window_from": F.__dict__.get("_swing_end_from", "unknown")}, T)
    except Exception:
        stats["errors"] += 1


def fight_end(F, result) -> None:
    try:
        st = _st(F)
        _flush(st)
        _emit("fight_end", result=getattr(result, "result", None), ticks=st["tick"], decisions=st["dec"], trace=dict(stats))
        _state.pop(F, None)
    except Exception:
        stats["errors"] += 1


# ── hooks called from rule_after_swing ──

def _owners(F) -> dict:
    g = F.__dict__.get
    return {"aprev": g("_aprev"), "aprev_from": g("_aprev_from", "unknown"),
            "swing_end_t": g("_swing_end_t"), "swing_end_from": g("_swing_end_from", "unknown"),
            "swing_aged": g("_swing_aged"), "swing_aged_from": g("_swing_aged_from", "unknown")}


def window(F, T, basis: str, prev, prev_from, started) -> None:
    try:
        st = _st(F)
        _flush(st)
        st["win"] = T.now
        _emit("window_open", tick=st["tick"], snap=_snap(T.s), basis=basis, ptr=F.ptr, npc=getattr(T.c, "npc_param", None),
              anim=T.a, observed_id_age=None if T.age is None else round(T.age, 3), id_started=started,
              foe=_foe_cfg(F.foe), limit=_limit(F.foe, T.a), prev_anim=prev, prev_anim_from=prev_from,
              prev_from_other_target=(prev_from not in ("unknown", None) and prev_from != F.ptr), **research())
    except Exception:
        stats["errors"] += 1


def expired(F, T, end_t) -> None:
    try:
        st = _st(F)
        if st["expired_for"] == end_t:
            return
        st["expired_for"] = end_t
        _flush(st)
        _emit("window_expired", tick=st["tick"], snap=_snap(T.s), ptr=F.ptr, window_t=end_t,
              window_from=F.__dict__.get("_swing_end_from", "unknown"), after_s=round(T.now - end_t, 3))
    except Exception:
        stats["errors"] += 1


def blocked(F, T, why: str, conds: dict) -> None:
    try:
        _fold(_st(F), "eval", {"outcome": "blocked", "why": why, "ptr": F.ptr, "attack": False,
                               "window_from": F.__dict__.get("_swing_end_from", "unknown")}, T, extra=conds)
    except Exception:
        stats["errors"] += 1


def turn_only(F, T, conds: dict) -> None:
    try:
        st = _st(F)
        _flush(st)
        _emit("eval", tick=st["tick"], snap=_snap(T.s), outcome="turn_only", ptr=F.ptr, conds=conds, attack=False,
              window_from=F.__dict__.get("_swing_end_from", "unknown"))
    except Exception:
        stats["errors"] += 1


def intent(F, T, s, c, kind: str, n: int, conds: dict) -> int | None:
    """Right before the strike call: the frozen decision. → a decision number the outcome repeats (or None)."""
    try:
        st = _st(F)
        _flush(st)
        st["dec"] += 1
        p = s.player
        _emit("window_consumed", tick=st["tick"], ptr=F.ptr, window_t=st.get("win"))
        _emit("intent", tick=st["tick"], dec=st["dec"], snap=_snap(s), decided_t=T.now, rule="after_swing", kind=kind, presses=n,
              target=_chr(c, p), npc=getattr(c, "npc_param", None), foe=_foe_cfg(F.foe), limit=_limit(F.foe, T.a),
              observed_id_age=None if T.age is None else round(T.age, 3), me={"anim": p.anim, "sp": p.sp, "hp": p.hp},
              conds=conds, near=_near(s, p, F.ptr, F.reflex, T.now), owners=_owners(F), **research())
        return st["dec"]
    except Exception:
        stats["errors"] += 1
        return None


def outcome(F, dec, hit=None, error: str | None = None) -> None:
    """After the strike call. Hit fields only — whether the pad really pressed is read from the pad records by seq offline."""
    try:
        if error is not None:
            _emit("outcome", dec=dec, status="exception", error=error)
            return
        _emit("outcome", dec=dec, status="returned", kind=getattr(hit, "kind", None), presses_counted=getattr(hit, "presses", None),
              dmg=getattr(hit, "dmg", None), taken=getattr(hit, "taken", None), dead=getattr(hit, "dead", None),
              skipped=getattr(hit, "skipped", None), others=getattr(hit, "others", None))
    except Exception:
        stats["errors"] += 1


# ── folding ──

def _fold(st: dict, ev: str, key: dict, T, extra=None) -> None:
    """Same (ev, key) on consecutive records → one record with n, first/last tick time; `extra` (the conditions) kept for
    the first and the last of the run."""
    f = st["fold"]
    k = (ev, repr(sorted(key.items())))
    if f is not None and f["k"] == k and f["n"] < FOLD_MAX:
        f["n"] += 1
        f["last_t"], f["last_tick"], f["last_extra"] = T.now, st["tick"], extra
        return
    _flush(st)
    st["fold"] = {"k": k, "ev": ev, "key": key, "n": 1, "first_t": T.now, "last_t": T.now, "first_tick": st["tick"],
                  "last_tick": st["tick"], "snap": _snap(T.s), "first_extra": extra, "last_extra": extra}


def _flush(st: dict) -> None:
    f = st.get("fold")
    if f is None:
        return
    st["fold"] = None
    extra = {} if f["first_extra"] is None else {"conds_first": f["first_extra"], "conds_last": f["last_extra"]}
    _emit(f["ev"], n=f["n"], first_t=f["first_t"], last_t=f["last_t"], first_tick=f["first_tick"], last_tick=f["last_tick"],
          snap=f["snap"], **f["key"], **extra)
