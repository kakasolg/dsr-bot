"""Attack outcome-proxy separation audit — pre-registered in data/laya/attack_proxy_audit_plan.md (commit d54337b).

OUTCOME PROXY, NOT A HUMAN-VERIFIED TACTICAL LABEL. NOT A SAFETY VALIDATION.
No hit ≠ the attack was justified or safe. Hit ≠ choosing to attack was wrong. Never human_verified, a train target or a
final test label. Inference only: no training, no checkpoint change, no calibration fitting, no game, no bot change.

  python experiments/attack_proxy_audit.py equiv     a1–a3: radar-reconstructed features() vs the features logged live
                                                     → data/laya/attack_proxy_audit_equiv.json (no model)

Reconstruction = laya_shadow.features(F, T) itself, on telemetry.Snapshot/Chr built from radar snapshots and stand-in F/T
whose values come only from the recording up to the decision time (the bot's own log lines are in the radar as 'say').
"""
from __future__ import annotations

import bisect
import json
import math
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import laya_shadow as LS                                    # noqa: E402
from souls import duel as D, foes as foes_, moves as M, style as ST, weapons as W   # noqa: E402
from telemetry import Chr, Snapshot                         # noqa: E402

DISCLAIMER = {"kind": "outcome proxy, not human-verified tactical label",
              "not": "not a safety validation",
              "use": "never human_verified, a train target or a final test label",
              "plan": "data/laya/attack_proxy_audit_plan.md (pre-registered, commit d54337b)"}
HEAD = re.compile(r'^\{"rt": ([0-9.]+), "type": "(\w+)"')
STATUS = re.compile(r"\[\s*([0-9.]+)s\] 거리 ")
END = re.compile(r"^(?:\[\s*[0-9.]+\])?\s*(.+?)(?: \(끝까지\))?: (killed|low_hp|losing|crowd|me_dead|stuck|timeout|lost|cancel|unsafe_approach|stalemate) — (\d+) s")
ESTUS = re.compile(r"에스트: \{.*'left': (\d+)")
SNAP_MAX_S = 0.25
FIX_KIND = {254001: "hollow"}                               # laya_finetune.FIX_KIND — same as the training input (plan 7)


# ── radar recording ──
class Recording:
    def __init__(self, path: Path):
        self.path = path
        self.snap_t, self.snaps, self.says, self.e0 = [], [], [], None
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                m = HEAD.match(line)
                if not m:
                    continue
                rt, typ = float(m.group(1)), m.group(2)
                if typ == "snap":
                    s = json.loads(line)
                    if (s.get("t") or 0) > 1e9 and (s.get("player") or {}).get("x") is not None:
                        self.snap_t.append(s["t"])
                        self.snaps.append(s)
                        if self.e0 is None:
                            self.e0 = s["t"] - rt
                elif typ == "say":
                    self.says.append((rt, json.loads(line).get("line", "")))
        self.say_t = [self.e0 + rt for rt, _ in self.says]

    def at(self, t: float):
        """Last snapshot at or before t (never after) and its age."""
        i = bisect.bisect_right(self.snap_t, t) - 1
        return (self.snaps[i], t - self.snap_t[i]) if i >= 0 else (None, None)

    def between(self, t0: float, t1: float) -> list:
        i, j = bisect.bisect_left(self.snap_t, t0), bisect.bisect_right(self.snap_t, t1)
        return self.snaps[i:j]

    def says_before(self, t: float, since: float = 0.0) -> list:
        j = bisect.bisect_right(self.say_t, t)
        i = bisect.bisect_left(self.say_t, since)
        return [(self.say_t[k], self.says[k][1]) for k in range(i, j)]


def chr_of(d: dict) -> Chr:
    return Chr(ptr=d["ptr"], npc_param=d.get("npc") or 0, team=d.get("team") or 0, hp=d.get("hp") or 0, max_hp=d.get("max_hp") or 0,
               x=d["x"], y=d["y"], z=d["z"], sp=d.get("sp") or 0, max_sp=d.get("max_sp") or 0, anim=d.get("anim"),
               dist=d.get("dist") or 0.0, name=d.get("name") or "", heading=d.get("heading"))


def snapshot_of(d: dict) -> Snapshot:
    return Snapshot(t=d["t"], player=chr_of(d["player"]), chars=[chr_of(c) for c in d.get("chars") or []])


# ── run settings from the run's own log lines (all at or before the decision) ──
def run_setup(rec: Recording, t: float) -> dict:
    """Latest '무기:' / '스타일:' / '기본 플레이' lines before t. Missing → None (the case is excluded, never assumed)."""
    out = {"weapon": None, "style": None, "basic": False}
    for _, line in rec.says_before(t):
        if "무기: " in line:
            name = line.split("무기: ", 1)[1].split(" (")[0].strip()
            out["weapon"] = next((w for w in vars(W).values() if isinstance(w, W.Weapon) and w.name == name), None)
            out["weapon_name"] = name
        elif "스타일: " in line:
            name = line.split("스타일: ", 1)[1].strip()
            out["style"] = next((s for s in vars(ST).values() if isinstance(s, ST.Style) and s.name == name), None)
        elif "기본 플레이" in line:
            out["basic"] = True
        elif "── " in line and "실행" in line:                 # a new run in the same recording resets nothing we read
            pass
    return out


def fight_context(rec: Recording, t: float) -> dict | None:
    """The fight running at t: its start (first status line '[ x.xs]' after t's previous fight end: t0 = line time − x) and its tag
    (from the fight's end line, which is after t — used only for the call-site settings below, never as an outcome)."""
    j = bisect.bisect_right(rec.say_t, t)
    # start: walk back over this fight's status lines
    t0 = None
    k = j - 1
    while k >= 0:
        line = rec.says[k][1]
        if END.search(line):
            break
        m = STATUS.search(line)
        if m:
            t0 = rec.say_t[k] - float(m.group(1))
        k -= 1
    # end line: first one after t
    tag = None
    for k2 in range(j, min(len(rec.says), j + 400)):
        m = END.search(rec.says[k2][1])
        if m:
            tag, desperate = m.group(1), "(끝까지)" in rec.says[k2][1]
            break
    if tag is None:
        return None
    if t0 is None:                                          # no status line yet in this fight (first second): end line − duration
        t0 = None
    return {"t0": t0, "tag": tag, "desperate": desperate}


def wait_far_at(rec: Recording, ctx: dict, t: float) -> bool:
    """Field call sites (souls/field.py, current code): wait_far=True for '오는 놈' (clear and careful walk), '따라온' and 'hold 접촉'.
    rule_wait_far turns it off with '안옴→붙기' (counted in the next 1 s status line — that line's time is used)."""
    tag = ctx["tag"]
    on = any(k in tag for k in ("오는 놈", "따라온", "hold 접촉"))
    if on and ctx["t0"] is not None:
        for _, line in rec.says_before(t, ctx["t0"]):
            if "안옴→붙기" in line:
                on = False
    return on


def arena_on(ctx: dict, run_kind: str) -> bool:
    """arena: only souls/missions.py clear-ramp passes one (RAMP_ARENA) to Field.clear → '#i …' and '오는 놈' fights there; the careful
    walk's '…: 오는 놈' passes none. '따라온' passes a zone (arena=zone) — counted as arena."""
    tag = ctx["tag"]
    if "따라온" in tag:
        return True
    if run_kind != "clear-ramp" or ": 오는 놈" in tag:
        return False
    return True


def estus_left(rec: Recording, t: float):
    """Last Estus 'left' logged before t; None if none seen (then estus_wanted is not computed)."""
    left = None
    for _, line in rec.says_before(t):
        m = ESTUS.search(line)
        if m:
            left = int(m.group(1))
        elif "불의 제전 휴식: 됨" in line or "화톳불 휴식: 됨" in line:
            left = None                                     # refilled to an unknown max
    return left


class _Care:
    def __init__(self, left):
        self.left = left

    def wants(self, s) -> bool:
        from souls.field import FIGHT_HEAL
        return self.left > 0 and s.player.hp < s.player.max_hp * FIGHT_HEAL


class _F:
    pass


class _T:
    pass


def swing_age(rec: Recording, ptr, t: float):
    """souls/reflex.attack_age from snapshots ≤ t: time since the target's current attack anim began (anim change into ATTACK)."""
    start, last = None, None
    for d in rec.between(t - 6.0, t):
        c = next((x for x in d.get("chars") or [] if x.get("ptr") == ptr), None)
        a = (c or {}).get("anim")
        a = -1 if a is None else a
        if a in M.ATTACK and a != last:
            start = d["t"]
        last = a
    return (t - start) if (last in M.ATTACK and start is not None) else None


def reconstruct(rec: Recording, t: float, ptr, run_kind: str) -> tuple[dict | None, dict]:
    """features(F, T) at decision time t from the recording only (≤ t). → (features | None, provenance/why)."""
    d, age = rec.at(t)
    if d is None or age > SNAP_MAX_S:
        return None, {"exclude": "no_snapshot_at_decision", "snap_age_s": age}
    s = snapshot_of(d)
    c = next((x for x in s.chars if x.ptr == ptr), None)
    if c is None:
        return None, {"exclude": "target_not_in_snapshot"}
    setup = run_setup(rec, t)
    if setup["weapon"] is None or setup["style"] is None:
        return None, {"exclude": "no_weapon_or_style_line", "weapon_name": setup.get("weapon_name")}
    ctx = fight_context(rec, t)
    if ctx is None or ctx["t0"] is None:
        return None, {"exclude": "fight_not_found"}
    hist = rec.between(ctx["t0"] - SNAP_MAX_S, t)
    hp0 = hist[0]["player"]["hp"] if hist else s.player.hp
    left = estus_left(rec, t)
    F = _F()
    F.weapon, F.foe, F.ptr, F.style = setup["weapon"], foes_.of(c.npc_param), ptr, setup["style"]
    F.care = _Care(left) if left is not None else None
    F.hp_start, F.hp_min = hp0, min([h["player"]["hp"] for h in hist if h["player"].get("hp") is not None] or [hp0])
    F.wait_far = wait_far_at(rec, ctx, t)
    F.reflex = object()                                     # Field always builds a Reflex (souls/field.py) → _reflex_on True
    F.arena = object() if arena_on(ctx, run_kind) else None
    F.nm = object()                                         # Field always passes its NavMesh
    F.low_hp = 0.0 if ctx["desperate"] else 0.5
    T = _T()
    T.s, T.p, T.c = s, s.player, c
    T.h, T.dy, T.a = M.horiz(s.player, c), c.y - s.player.y, (c.anim if c.anim is not None else -1)
    T.age = swing_age(rec, ptr, t)
    T.room = False if setup["basic"] or not D.BACKSTAB else None     # non-basic: needs the bot's NavMesh check — not in the radar
    f = LS.features(F, T)
    if T.room is None:
        f["_room"] = None
    if F.care is None:
        f["estus_wanted"] = None
    prov = {"snap_age_s": round(age, 3), "fight_t0": ctx["t0"], "fight_tag": ctx["tag"], "estus_left": left,
            "basic": setup["basic"], "weapon": setup.get("weapon_name"), "style": setup["style"].name}
    return f, prov


# ── equivalence check on a1–a3 (plan 6) ──
TOL = {"distance_m": 0.15, "height_diff_m": 0.15, "my_hp_pct": 0.03, "my_stamina_pct": 0.03, "target_hp_pct": 0.03,
       "taken_this_fight_pct": 0.03, "facing_error_deg": 10, "target_facing_me_deg": 10, "target_swing_age_s": 0.15}
A_RUNS = {"a1": "20261001_180055_clear-ramp", "a2": "20261001_180316_clear-ramp", "a3": "20261001_180542_clear-ramp"}
RAMP_RADAR = ROOT / "data" / "radar" / "20261001_172152.jsonl"


def _target_ptr(rec: Recording, t: float, npc):
    d, _ = rec.at(t)
    if d is None:
        return None
    tp = d.get("target")
    c = next((x for x in d.get("chars") or [] if x.get("ptr") == tp), None)
    if c is not None and c.get("npc") == npc:
        return tp
    p = d["player"]
    cands = [x for x in d.get("chars") or [] if x.get("npc") == npc and (x.get("hp") or 0) > 0]
    return min(cands, key=lambda x: math.hypot(x["x"] - p["x"], x["z"] - p["z"]))["ptr"] if cands else None


def _same(k, a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if k in TOL:
        return abs(float(a) - float(b)) <= TOL[k] + 1e-9
    return a == b


def equiv() -> dict:
    rec = Recording(RAMP_RADAR)
    rows = []
    for tag, run in A_RUNS.items():
        for line in open(ROOT / "data" / "samples" / f"clear-ramp-shadow-2026-10-01-{tag}.laya.jsonl", encoding="utf-8"):
            r = json.loads(line)
            if r.get("type") != "answer":
                continue
            t = r["t_state"]
            ptr = _target_ptr(rec, t, r.get("npc"))
            f, prov = reconstruct(rec, t, ptr, "clear-ramp") if ptr is not None else (None, {"exclude": "target_not_found"})
            rows.append({"run": tag, "seq": r["seq"], "t": t, "logged": r["feat"], "logged_allowed": r["allowed"],
                         "recon": f, "prov": prov, "fight_logged": float(r["fight"])})
    keys = sorted(rows[0]["logged"].keys())
    ok = [x for x in rows if x["recon"] is not None]
    fields = {}
    for k in keys:
        pairs = [(x["logged"].get(k), x["recon"].get(k)) for x in ok]
        same = [_same(k, a, b) for a, b in pairs]
        e = {"agree": round(sum(same) / len(pairs), 4) if pairs else None, "n": len(pairs),
             "criterion": f"|Δ| ≤ {TOL[k]}" if k in TOL else "exact"}
        if k in TOL:
            ds = sorted(abs(float(a) - float(b)) for a, b in pairs if a is not None and b is not None)
            if ds:
                e["abs_err"] = {"median": round(statistics.median(ds), 3), "p95": round(ds[int(0.95 * (len(ds) - 1))], 3), "max": round(ds[-1], 3)}
            e["none_mismatch"] = sum(1 for a, b in pairs if (a is None) != (b is None))
        else:
            e["mismatches"] = [{"logged": a, "recon": b, "n": sum(1 for p in pairs if p == (a, b))}
                               for a, b in sorted({p for p, s_ in zip(pairs, same) if not s_}, key=str)][:8]
        e["pass"] = e["agree"] is not None and e["agree"] >= 0.95
        fields[k] = e
    al = [(sorted(x["logged_allowed"]), sorted(LS.allowed(x["recon"]))) for x in ok]
    allowed_agree = sum(a == b for a, b in al) / len(al)
    t0_err = sorted(abs(x["prov"]["fight_t0"] - x["fight_logged"]) for x in ok)
    res = {"disclaimer": DISCLAIMER, "step": "equivalence (plan 6) — no model", "ticks": len(rows), "reconstructed": len(ok),
           "not_reconstructed": {k: sum(1 for x in rows if x["recon"] is None and x["prov"].get("exclude") == k)
                                 for k in sorted({x["prov"].get("exclude") for x in rows if x["recon"] is None})},
           "snap_age_s": {"median": round(statistics.median(x["prov"]["snap_age_s"] for x in ok), 3),
                          "max": round(max(x["prov"]["snap_age_s"] for x in ok), 3)},
           "fight_start_err_s": {"median": round(statistics.median(t0_err), 3), "max": round(t0_err[-1], 3)},
           "fields": fields,
           "allowed": {"agree": round(allowed_agree, 4), "pass": allowed_agree >= 0.95,
                       "mismatches": [{"logged": a, "recon": b} for a, b in al if a != b][:10]},
           "failed_fields": [k for k, e in fields.items() if not e["pass"]]}
    res["gate"] = "pass" if not res["failed_fields"] and res["allowed"]["pass"] and len(ok) == len(rows) else "fail"
    out = ROOT / "data" / "laya" / "attack_proxy_audit_equiv.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "data" / "laya" / "attack_proxy_audit_equiv_rows.jsonl").write_text(
        "\n".join(json.dumps({k: v for k, v in x.items()}, ensure_ascii=False) for x in rows) + "\n", encoding="utf-8")
    return res


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "equiv":
        r = equiv()
        print(json.dumps({k: v for k, v in r.items() if k != "fields"}, ensure_ascii=False, indent=1))
        for k, e in r["fields"].items():
            print(f"  {'OK ' if e['pass'] else 'FAIL'} {k:24} {e['agree']}  {e.get('abs_err') or e.get('mismatches')}")
    else:
        print(__doc__)
