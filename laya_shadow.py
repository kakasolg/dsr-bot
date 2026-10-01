"""Laya shadow mode — every fight tick where a rule acted, record what the rules did and which tactic Laya would have
picked. Record only: nothing here touches the pad, Moves or the rules (LAYA.md).

  bot side   adv = Advisor(WorkerChannel([py, "laya_worker.py", "--out", path]).offer)   # run.py --laya-shadow
             duel(..., advisor=adv)  →  adv.observe(F, T, rule) / adv.end(F, result)    # reads only, swallows errors
  worker     laya_worker.py (its own venv with torch + laya) reads one JSON request per line, answers into the .laya.jsonl
  offline    laya_eval.py builds the same requests from the golden situations / old logs and scores them

Import is stdlib-only, so the worker venv needs no bot modules beyond this file (souls.* are imported lazily on the bot side).
"""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ── what Laya may answer: tactics the bot already has (rule groups in souls/duel.py RULES) ──
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
INSTRUCTIONS = ("A Dark Souls bot is in a melee fight with its target. The state lists only what it can read from the game "
                "right now. Which tactic fits this state best?")
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
MIN_CONF = 0.5                 # below this the answer counts as 'abstain' (판단 보류)
MIN_INTERVAL = 0.2             # at most one tick request per this many seconds (fight ticks are ~0.04–0.05 s)


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


def state_for(f: dict) -> dict:
    """The state Laya reads: the observed fields only (no mask inputs, nothing unknown)."""
    return {k: v for k, v in f.items() if not k.startswith("_") and v is not None}


def questions_for(allowed_: list) -> dict:
    return {"tactic": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": {k: TACTICS[k] for k in allowed_}}}


def read_answer(out, allowed_: list, min_conf: float = MIN_CONF) -> dict:
    """Laya output → {choice, conf, probs, status}. status: ok | abstain (conf < min_conf) | invalid (not one of the
    permitted tactics, or malformed). Nothing outside `allowed_` is ever returned as a choice."""
    try:
        a = out["answers"]["tactic"]
        choice, conf = a.get("choice"), float(a.get("confidence"))
        probs = {str(k): round(float(v), 4) for k, v in (a.get("probabilities") or {}).items()}
    except Exception as e:
        return {"choice": None, "conf": None, "probs": None, "status": "invalid", "why": f"malformed: {e!r}"[:160]}
    if choice not in allowed_ or not (0.0 <= conf <= 1.0):
        return {"choice": None, "conf": conf, "probs": probs, "status": "invalid", "why": f"not permitted: {choice!r}"}
    # laya 0.3.23: `confidence` is its calibrated sureness (median 0.05 on our states), `answer_confidence` the chosen
    # option's probability (e.g. 0.40 among 4) — both kept; the gate stays on `confidence` (LAYA.md 9)
    top = a.get("answer_confidence", probs.get(choice))
    return {"choice": choice, "conf": round(conf, 4), "top_p": None if top is None else round(float(top), 4), "probs": probs,
            "status": "ok" if conf >= min_conf else "abstain"}


def answer(req: dict, backend, min_conf: float = MIN_CONF) -> dict:
    """One request → one result row (worker and laya_eval share this). Never raises."""
    t_recv = time.time()
    row = {k: v for k, v in req.items()}
    row["type"] = "answer"
    try:
        t0 = time.perf_counter()
        st, qs = state_for(req["feat"]), questions_for(req["allowed"])
        t1 = time.perf_counter()
        out = backend.predict(st, qs)
        t2 = time.perf_counter()
        row.update(read_answer(out, req["allowed"], min_conf))
        usage = (out.get("usage") or {}) if isinstance(out, dict) else {}
        row["tokens"] = usage.get("state_tokens") or usage.get("input_tokens")
        row["truncated"] = usage.get("truncated")
        row["prep_ms"], row["infer_ms"] = round((t1 - t0) * 1000, 3), round((t2 - t1) * 1000, 2)
    except Exception as e:
        row.update(choice=None, conf=None, probs=None, status="error", why=repr(e)[:200])
    t_done = time.time()
    row["worker_os"] = sys.platform
    if req.get("t_offer"):
        # bot clock → worker clock: exact on one OS; Windows bot → WSL worker are two clocks (~10–30 ms apart, measured
        # 2026-10-01), so these two are then only approximate (clock_cross) — infer_ms is always one clock
        row["queue_ms"] = round((t_recv - req["t_offer"]) * 1000, 2)
        row["total_ms"] = round((t_done - req["t_offer"]) * 1000, 2)
        row["clock_cross"] = req.get("bot_os", sys.platform) != sys.platform
    return row


# ── bot side ──

class Advisor:
    """Turns fight ticks into requests and hands them to `send` (must not block — WorkerChannel.offer).
    Every method swallows its own errors: a broken advisor can't change or stop a fight."""

    def __init__(self, send, min_interval: float = MIN_INTERVAL, source: str = "shadow", group: str = ""):
        self.send, self.min_interval, self.source, self.group = send, min_interval, source, group
        self.last_t = 0.0
        self.seq = 0
        self.errors = 0
        self.last_error = None
        self._last = {}                                      # fight id → (features, allowed, time) of its last tick

    def _req(self, F, f: dict, al: list, rule, policy, kind: str, t_state: float, prep_ms: float) -> dict:
        self.seq += 1
        return {"source": self.source, "group": self.group, "seq": self.seq, "kind": kind,
                "fight": f"{F.t0:.3f}", "npc": getattr(F.res, "npc", None), "rule": rule, "policy": policy,
                "allowed": al, "feat": f, "t_state": round(t_state, 3), "t_offer": time.time(), "prep_bot_ms": round(prep_ms, 3),
                "bot_os": sys.platform}

    def observe(self, F, T, rule: str, out=None) -> None:
        """A rule acted this tick (duel loop, after the rule ran). `out` is what the rule returned — a fight ending
        such as low_hp from wait_far goes to end()."""
        try:
            if getattr(out, "result", None) in END_TACTIC:
                return self.end(F, out, T, rule)
            now = time.time()
            if RULE_TACTIC.get(rule) is not None and now - self.last_t >= self.min_interval:
                t0 = time.perf_counter()
                f = features(F, T)
                al = allowed(f)
                policy = policy_tactic(rule, f)
                prep = (time.perf_counter() - t0) * 1000
                self._last[F.t0] = (f, al, now)
                self.last_t = now
                self.send(self._req(F, f, al, rule, policy, "tick", T.now, prep))
        except Exception as e:
            self.errors, self.last_error = self.errors + 1, repr(e)[:200]
        finally:
            if hasattr(out, "result"):                       # the fight is over (killed, …)
                self._last.pop(getattr(F, "t0", None), None)

    def end(self, F, res, T=None, rule: str | None = None) -> None:
        """A fight ended. low_hp / losing / crowd are the rules' decision to retreat — recorded with this tick's state
        (T) or, when _sense ended it before any rule ran, the fight's last recorded tick (`stale_s` says how old)."""
        try:
            policy = END_TACTIC.get(getattr(res, "result", None))
            if policy is None:
                self._last.pop(F.t0, None)
                return
            t0 = time.perf_counter()
            if T is not None:
                f, stale = features(F, T), 0.0
                al = allowed(f)
            else:
                last = self._last.get(F.t0)
                if last is None:
                    return
                f, al, stale = last[0], last[1], time.time() - last[2]
            prep = (time.perf_counter() - t0) * 1000
            req = self._req(F, f, al, rule or res.result, policy, "end", T.now if T is not None else time.time(), prep)
            req["stale_s"] = round(stale, 3)
            self._last.pop(F.t0, None)
            self.send(req)
        except Exception as e:
            self.errors, self.last_error = self.errors + 1, repr(e)[:200]


class WorkerChannel:
    """Requests → a worker process's stdin, from a thread. offer() never blocks: it keeps only the newest
    `maxsize` requests and counts what it dropped. If the worker is slow, missing or dead, requests are dropped — nothing
    comes back to the bot (the worker writes its answers to a file only)."""

    def __init__(self, cmd: list, err_path=None, maxsize: int = 1, log=print):
        self.log = log
        self.q: queue.Queue = queue.Queue(maxsize=maxsize)
        self.offered = self.dropped = self.sent = 0
        self.dead = None
        flags = 0
        if sys.platform == "win32":                         # below the game and the bot for CPU time, no console window
            flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW
        try:
            self.err = open(err_path, "a", encoding="utf-8") if err_path else subprocess.DEVNULL
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.err,
                                         cwd=str(ROOT), creationflags=flags)
        except Exception as e:
            self.proc, self.dead = None, f"start failed: {e!r}"
            log(f"laya shadow: 워커를 못 켬 ({e!r}) — 기록 없이 계속")
            return
        self.th = threading.Thread(target=self._pump, daemon=True, name="laya-shadow")
        self.th.start()

    def offer(self, req: dict) -> None:
        self.offered += 1
        if self.dead:
            self.dropped += 1
            return
        try:
            self.q.put_nowait(req)
        except queue.Full:
            try:
                self.q.get_nowait()                         # keep the newest
                self.dropped += 1
            except queue.Empty:
                pass
            try:
                self.q.put_nowait(req)
            except queue.Full:
                self.dropped += 1

    def _pump(self) -> None:
        while True:
            req = self.q.get()
            if req is None:
                break
            try:
                self.proc.stdin.write((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
                self.proc.stdin.flush()
                self.sent += 1
            except Exception as e:                          # worker exited (load failed, crashed) — stop sending
                self.dead = f"pipe: {e!r}"[:160]
                break

    def close(self, wait: float = 5.0) -> str:
        if self.proc is not None:
            while True:                                      # unsent requests are dropped; the sentinel must get in
                try:
                    self.q.get_nowait()
                    self.dropped += 1
                except queue.Empty:
                    break
            try:
                self.q.put(None, timeout=1.0)
            except Exception:
                pass
            if getattr(self, "th", None) is not None:
                self.th.join(timeout=1.0)
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=wait)
            except Exception:
                self.proc.kill()
        return f"요청 {self.offered} · 보냄 {self.sent} · 버림 {self.dropped}" + (f" · 워커 끊김 ({self.dead})" if self.dead else "")


WSL_PYTHON = "$HOME/laya-venv/bin/python"     # the WSL Ubuntu venv with torch + laya (LAYA.md 6)


def wsl_path(p) -> str:
    """D:\\dev\\x → /mnt/d/dev/x (WSL's default automount)."""
    s = str(p).replace("\\", "/")
    if not (len(s) > 2 and s[1] == ":" and s[2] == "/"):
        s = str(Path(p).resolve()).replace("\\", "/")
    return f"/mnt/{s[0].lower()}{s[2:]}" if len(s) > 1 and s[1] == ":" else s


def worker_cmd(out_path, where: str = "wsl", device=None, backend=None) -> list:
    """Command that starts laya_worker.py. where: 'wsl' (WSL Ubuntu venv, WSL_PYTHON) or a python executable path."""
    extra = (["--device", device] if device else []) + (["--backend", backend] if backend else [])
    if where == "wsl":
        py = WSL_PYTHON
        return ["wsl", "-e", "sh", "-c", f'exec "{py}" "$@"', "sh", wsl_path(ROOT / "laya_worker.py"),
                "--out", wsl_path(out_path), *extra]
    return [where, str(ROOT / "laya_worker.py"), "--out", str(out_path), *extra]


# ── backends (worker / laya_eval) ──

PINNED_REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"   # laya.revisions.PINNED_REVISIONS["convaiinnovations/laya"] (0.3.23)


class LayaBackend:
    """The real model. Imports torch/laya here (worker venv only). HF_HUB_OFFLINE should be set by the caller so a
    missing checkpoint fails instead of downloading."""

    def __init__(self, model: str = "convaiinnovations/laya", subfolder=None, revision=PINNED_REVISION, device=None):
        import laya
        import torch
        t0 = time.perf_counter()
        self.agent = laya.load(model, device=device, subfolder=subfolder, revision=revision)
        self.info = {"backend": "laya", "laya": getattr(laya, "__version__", "?"), "torch": torch.__version__,
                     "model": model, "subfolder": subfolder, "revision": getattr(self.agent, "revision", None) or revision,
                     "device": str(getattr(self.agent, "device", device)),
                     "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                     "load_ms": round((time.perf_counter() - t0) * 1000)}
        try:
            self.info["params_m"] = round(sum(p.numel() for p in self.agent.model.parameters()) / 1e6, 1)
        except Exception:
            pass

    def predict(self, state, questions):
        return self.agent.predict(state, questions)


class FakeBackend:
    """For tests and dry runs. spec: fake:<tactic> (pick it if offered, else the first) · fake:slow:<s> · fake:raise ·
    fake:garbage · fake:outside (answers a tactic that wasn't offered)."""

    def __init__(self, spec: str):
        self.spec = spec.split(":", 1)[1] if ":" in spec else "hold_position"
        self.info = {"backend": f"fake:{self.spec}"}

    def predict(self, state, questions):
        crit = list(questions["tactic"]["criteria"])
        kind, _, arg = self.spec.partition(":")
        if kind == "raise":
            raise RuntimeError("fake backend failure")
        if kind == "garbage":
            return {"answers": "???"}
        if kind == "slow":
            time.sleep(float(arg or 1.0))
        if kind == "outside":
            return {"answers": {"tactic": {"choice": "jump_off_cliff", "confidence": 0.99}}}
        pick = kind if kind in crit else crit[0]
        return {"answers": {"tactic": {"choice": pick, "confidence": 0.9, "probabilities": {pick: 0.9}}},
                "usage": {"input_tokens": 0}}


def make_backend(spec: str, **kw):
    return FakeBackend(spec) if spec.startswith("fake") else LayaBackend(**kw)
