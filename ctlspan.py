"""ctl links — span records that tie the existing ctl records together (run.py --ctl-spans, needs --ctl). Record only.

  span.fight   start / end         one duel() call                       parent: the span open on this thread (none today)
  span.cycle   start / end         one turn of duel()'s while loop       parent: fight
  span.rule    one record          the rule that returned non-None       parent: cycle (rules that returned None: counted
                                   (enter_pc, first_action_pc /          in the cycle end record only — MoKa 2026-10-30
                                   first_pad_pc, ret_pc)                 "cycle에만 붙이기")
  span.action  start / end         a blocking Moves call (moves._span)   parent: the enclosing action, else the cycle; rule_id
                                                                         = the rule being called when it started
  span.obs     one record          the snapshot _sense read (T.s), copied   parent: cycle (obs_id; the cycle end names it)
                                   when sensed() runs — before the rules
  pad records  + cycle_id / action_id of the thread that wrote them (control.Pad._record) — only the writing thread's own
               ids: CamFollow / GuardKeep / Escape threads never open a span, so their records carry none.

Ids are per thread (threading.local); nothing here is shared between threads except the id counter. Every value put in a
record is a primitive or a fresh copy. Nothing here raises into the caller and nothing is read back by the bot.

span.obs — what it holds and what it does not (MoKa 2026-10-30 "각 cycle이 참조한 입력 본문"):
  · held: every Snapshot field (t, pc, fseq, cam_yaw, cam_pitch, arm_style, flask_hp, max_flask_hp), every field of the
    player and of every Chr in s.chars (all _sense got: SEEK_R 100 m, same order), Tick.now and the target ptr (T.c.ptr —
    h / dy / a follow from it and the snapshot). Copied on the duel thread inside sensed() into new dicts of primitives; the
    record owns them, the writer thread serializes them later, nothing else holds them.
  · not held: Fight's own state (F.*: ptr history, timers, last_seen, woke, …), Moves.swung (filled by every thread's reads),
    reflex / care / shadow state, scalar reads (grip, lock_target, handle, goods_count), and every snapshot read after
    the sense read — F.cancel() inside _sense (Field's far / leash), rules, prep_face, actions' _watch, nav.goto.
    Those later reads are only counted: snap_reads_sense / snap_reads_after in the cycle end (snap_read(), called by
    dsr_telemetry and feed). A cycle with any later read is not "input restorable" from its obs alone.
  · sense_result / sense_cont cycles: _sense returned before sensed() — no obs.
  · a dropped obs (queue full) leaves the cycle's obs_id pointing at nothing; ctl_check.py reports it as missing / dropped.
"""
from __future__ import annotations

import itertools
import threading
import time

import ctl

ON = False                # run.py --ctl-spans
_ids = itertools.count(1)
_tl = threading.local()


def _stack() -> list:
    st = getattr(_tl, "stack", None)
    if st is None:
        st = _tl.stack = []
    return st


def on() -> bool:
    return ON and ctl.on()


def active() -> bool:
    """A cycle is open on this thread — action spans are only written inside the duel loop."""
    return ON and getattr(_tl, "cycle", None) is not None


def pad_tags(mark: bool = True) -> dict:
    """Ids for a pad record written by this thread. mark: it is a report write — note it as the pending rule's first pad
    write. {} outside a cycle."""
    if not ON:
        return {}
    try:
        cy = getattr(_tl, "cycle", None)
        if cy is None:
            return {}
        r = getattr(_tl, "rule", None)
        if r is not None and mark:
            if r["first_pad_pc"] is None:
                r["first_pad_pc"] = time.perf_counter_ns()
            r["pad"] = True
        acts = getattr(_tl, "actions", None)
        return {"cycle_id": cy["id"], "action_id": acts[-1] if acts else None}
    except Exception:
        return {}


# ── fight / cycle / rule (souls/duel.py) ──

class Fight:
    """One per duel() while --ctl-spans is on. Every method swallows its own errors."""

    def __init__(self, ptr):
        self.id = self.cycle = None
        try:
            st = _stack()
            self.id = next(_ids)
            parent = st[-1] if st else None
            st.append(self.id)
            ctl.emit("span.fight", ev="start", fight_id=self.id, parent=parent, ptr=ptr)
        except Exception:
            pass

    def cycle_start(self) -> None:
        try:
            if self.cycle is not None:                     # not closed (should not happen) — close it, don't nest
                self.cycle_end("abandoned")
            cid = next(_ids)
            self.cycle = {"id": cid, "none": 0, "none_pad": [], "reads": 0}
            _tl.cycle, _tl.rule, _tl.actions = self.cycle, None, []
            ctl.emit("span.cycle", ev="start", cycle_id=cid, parent=self.id)
        except Exception:
            pass

    def sensed(self, T, radius) -> None:
        """What the cycle's sense step read: T.s is the snapshot _sense used (prep_face may read another one later)."""
        try:
            s = getattr(T, "s", None)
            fseq = getattr(s, "fseq", None)
            self.cycle.update(sense_pc=time.perf_counter_ns(), radius=radius, snap_t=getattr(s, "t", None), fseq=fseq,
                              # feed.Feed sets fseq on every frame it serves; a direct telemetry read never does
                              src=None if s is None else ("feed" if fseq is not None else "direct"), snap=s,
                              reads_sense=self.cycle["reads"])
        except Exception:
            return
        try:
            oid = next(_ids)
            body = _snap_body(s)
            c = getattr(T, "c", None)
            ctl.emit("span.obs", obs_id=oid, cycle_id=self.cycle["id"], src=self.cycle["src"], fseq=self.cycle["fseq"],
                     radius=radius, now=getattr(T, "now", None), target_ptr=getattr(c, "ptr", None), snap=body)
            self.cycle["obs_id"] = oid
        except Exception as e:
            self.cycle["obs_err"] = type(e).__name__

    def rule_enter(self) -> None:
        try:
            _tl.rule = {"id": next(_ids), "enter_pc": time.perf_counter_ns(), "first_action_pc": None,
                        "first_pad_pc": None, "pad": False}
        except Exception:
            pass

    def rule_none(self, name: str) -> None:
        """The rule returned None — no span.rule; counted in the cycle end record (and named if it wrote the pad)."""
        try:
            r, _tl.rule = getattr(_tl, "rule", None), None
            self.cycle["none"] += 1
            if r is not None and r["pad"]:
                self.cycle["none_pad"].append(name)
        except Exception:
            pass

    def rule_return(self, name: str, out) -> None:
        try:
            r, _tl.rule = getattr(_tl, "rule", None), None
            if r is None:
                return
            res = getattr(out, "result", None)
            ctl.emit("span.rule", rule_id=r["id"], parent=self.cycle["id"], rule=name, enter_pc=r["enter_pc"],
                     first_action_pc=r["first_action_pc"], first_pad_pc=r["first_pad_pc"], ret_pc=time.perf_counter_ns(),
                     out=str(out) if res is None else "result:" + str(res))
            self.cycle["rule_id"] = r["id"]
        except Exception:
            pass

    def cycle_end(self, kind: str, picked: str | None = None, T=None) -> None:
        """kind: sense_result · sense_cont · rule_cont · rule_result · no_rule · exception · abandoned.
        resnap: a rule (prep_face) put a newer snapshot into T before the picked rule ran."""
        try:
            cy, self.cycle = self.cycle, None
            _tl.cycle, _tl.rule, _tl.actions = None, None, []
            if cy is None:
                return
            s = cy.get("snap")
            p = getattr(s, "player", None)
            ctl.emit("span.cycle", ev="end", cycle_id=cy["id"], parent=self.id, kind=kind, picked=picked,
                     rule_id=cy.get("rule_id"), none_n=cy["none"], none_pad=list(cy["none_pad"]),
                     sense_pc=cy.get("sense_pc"), src=cy.get("src"), radius=cy.get("radius"), snap_t=cy.get("snap_t"),
                     fseq=cy.get("fseq"), resnap=None if T is None or s is None else getattr(T, "s", None) is not s,
                     my_anim=getattr(p, "anim", None), obs_id=cy.get("obs_id"), obs_err=cy.get("obs_err"),
                     snap_reads_sense=cy.get("reads_sense"),
                     snap_reads_after=None if "reads_sense" not in cy else cy["reads"] - cy["reads_sense"])
        except Exception:
            pass

    def end(self, result=None) -> None:
        try:
            if self.cycle is not None:
                self.cycle_end("exception" if result is None else "abandoned")
            st = _stack()
            if self.id in st:
                del st[st.index(self.id):]
            ctl.emit("span.fight", ev="end", fight_id=self.id, result=None if result is None else getattr(result, "result", str(result)))
        except Exception:
            pass


def snap_read() -> None:
    """A snapshot read on this thread (dsr_telemetry.snapshot, feed.Feed.snapshot's cached frames). Counted only while a
    cycle is open on this thread — the camera / guard / feed threads never have one."""
    if ON:
        try:
            cy = getattr(_tl, "cycle", None)
            if cy is not None:
                cy["reads"] += 1
        except Exception:
            pass


_PRIM = (int, float, str, bool, type(None))
_SNAP_F = ("t", "pc", "fseq", "cam_yaw", "cam_pitch", "arm_style", "flask_hp", "max_flask_hp")


def _chr(c) -> dict | None:
    if c is None:
        return None
    return {k: (v if isinstance(v, _PRIM) else repr(v)) for k, v in vars(c).items()}


def _snap_body(s) -> dict | None:
    if s is None:
        return None
    out = {k: getattr(s, k, None) for k in _SNAP_F}
    out["player"] = _chr(s.player)
    out["chars"] = [_chr(c) for c in s.chars]
    return out


# ── actions (souls/moves.py) ──


def _params(args: dict) -> dict:
    out = {}
    for k, v in args.items():
        if k == "self":
            continue
        if isinstance(v, _PRIM):
            out[k] = v
        elif hasattr(v, "ptr") and hasattr(v, "npc_param"):
            out[k + "_ptr"] = v.ptr
    return out


def action_start(name: str, args: dict) -> int | None:
    try:
        aid = next(_ids)
        acts = _tl.actions
        r = getattr(_tl, "rule", None)
        if r is not None and r["first_action_pc"] is None:
            r["first_action_pc"] = time.perf_counter_ns()
        ctl.emit("span.action", ev="start", action_id=aid, parent=acts[-1] if acts else _tl.cycle["id"],
                 parent_kind="action" if acts else "cycle", rule_id=None if r is None else r["id"], action=name,
                 params=_params(args))
        acts.append(aid)
        _tl.watch_end = None
        return aid
    except Exception:
        return None


def watch_end(reason: str) -> None:
    """moves._watch: why its window ended — window (time up) · early (anim back to standing) · dead · gone (left the list)."""
    if active():
        _tl.watch_end = reason


def action_end(aid: int | None, ret=None, exc: BaseException | None = None) -> None:
    if aid is None:
        return
    try:
        acts = _tl.actions
        if aid in acts:
            del acts[acts.index(aid):]
        why = "exception" if exc is not None else (getattr(_tl, "watch_end", None) or "returned")
        _tl.watch_end = None
        rec = {"action_id": aid, "end": why}
        if exc is not None:
            rec["exc"] = type(exc).__name__
        if hasattr(ret, "e_anims") and hasattr(ret, "my_anims"):          # moves.Hit — raw fields, copied
            rec["hit"] = {"kind": ret.kind, "presses": ret.presses, "dmg": ret.dmg, "dead": ret.dead, "taken": ret.taken,
                          "e_anims": [list(x) for x in ret.e_anims], "my_anims": [list(x) for x in ret.my_anims],
                          "skipped": ret.skipped, "others": ret.others}
        elif isinstance(ret, dict):
            rec["ret"] = {k: (v if isinstance(v, _PRIM) else repr(v)) for k, v in ret.items()}
        elif isinstance(ret, _PRIM):
            rec["ret"] = ret
        ctl.emit("span.action", ev="end", **rec)
    except Exception:
        pass
