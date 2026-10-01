"""Labeling pilot — 30–50 fight decision scenes, reviewed on the existing radar replay (LAYA.md 11). No training, nothing
reaches the bot.

  python label_pilot.py build [--n 40]    pick scenes from bot radar recordings + human demos → data/labels/pilot_scenes.jsonl,
                                          clips → data/labels/clips/<scene>.jsonl (local, rebuilt from the sources)
  python label_pilot.py serve             http://127.0.0.1:47811 — radar replay (radar.html) + label panel (label.html)
  python label_pilot.py report            labeling time, 'unsure' rate, missing observations, definition notes

Labels: data/labels/pilot_labels.jsonl, one line per save (the last line per scene and labeler counts). Only what a person
chose on the label page is written there, as label_source "human_verified"; the bot's action, the rules' output and the
buttons a human pressed stay in the scene's "after" block (reference only, never model input, never copied into a label).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import laya_shadow as LS

ROOT = Path(__file__).resolve().parent
LABELS = ROOT / "data" / "labels"
SCENES = LABELS / "pilot_scenes.jsonl"
LABEL_FILE = LABELS / "pilot_labels.jsonl"
CLIPS = LABELS / "clips"
SCENE_SCHEMA, LABEL_SCHEMA = "dsr-scene/0.1", "dsr-label/0.1"
PRE_S, POST_S, CONTEXT_S = 6.0, 4.0, 3.0
HTTP_PORT = 47811
SEED = 20261001

HUMAN_FILES = ["20260926_081905", "20260926_083705", "20260926_084654", "20260926_101202", "20260926_101538", "20260926_101913",
               "20260926_130030", "20260926_131752", "20260926_132053", "20260926_133016", "20260926_133546", "20260926_133827",
               "20260926_134451", "20260926_135222", "20260926_140708", "20260927_183723", "20260927_184707", "20260927_185353",
               "20260927_224452", "20260928_221908", "20260929_061447"]   # data/observe files with only the human pad (slot 0)
NOT_FOE = {100000}                          # HP 999, team 26 in every recording — an NPC, not a foe (assumed)
TEST_ZONES = {"town #4 street (packs)", "crossbow spot (#5)"}
TEST_NPCS = {255002}
TACTIC_KO = {"attack": "공격", "guard": "막기(방패)", "evade": "회피(백스텝)", "approach": "접근", "hold_position": "거리 유지·기다림",
             "heal": "회복(에스트)", "reposition": "자리 옮김", "retreat": "후퇴", "backstab": "뒤잡기"}
INTENT_KEYS = {"target", "path_tag", "path", "spot_tag", "spot", "smash"}   # radar.intent_dict — the bot's plan, hidden before 'after'
BTN = {0x0100: "LB", 0x0200: "R1", 0x2000: "B", 0x4000: "X", 0x1000: "A", 0x8000: "Y"}

STATUS = re.compile(r"^\s*\[\s*([\d.]+)s\] 거리 ([\d.]+) 높이 ([+-]?[\d.]+) 그놈 애니 (-?\d+|None) HP (-?\d+) \| "
                    r"나 HP (-?\d+) SP (-?\d+) 애니 (-?\d+|None) 각 ([+-]?\d+)° \| (.*)$")
END = re.compile(r"^\s*(.*?): (killed|low_hp|losing|crowd|me_dead|stuck|stalemate|timeout|cancel|lost|unsafe_approach)"
                 r"(?: \(실제 상대 \d+\))? — (\d+) s, 준 피해 (\d+), 받은 피해 (\d+)")
BBOX = re.compile(r"블랙박스 #\d+: ([\d.]+) s 동안 (-\d+) → HP (\d+)/(\d+)")
WEAPON = re.compile(r"무기: (.+?) \(.*닿는 거리 ([\d.]+) m")
ESTUS = re.compile(r"에스트: \{.*'left': (\d+)")
HEAD = re.compile(r'^\{"rt": ([0-9.]+), "type": "(\w+)"')


# ── small helpers ──

def _anim_cat(a) -> str:
    from souls import moves as M
    return LS.target_state(a, None, M)


def _horiz(a: dict, b: dict) -> float:
    return math.hypot(b["x"] - a["x"], b["z"] - a["z"])


def _rel_deg(a: dict, b: dict):
    """Degrees b is off a's facing (souls/moves.rel_angle: world yaw = heading + π)."""
    if a.get("heading") is None:
        return None
    fwd = a["heading"] + math.pi
    d = (math.atan2(b["x"] - a["x"], b["z"] - a["z"]) - fwd + math.pi) % (2 * math.pi) - math.pi
    return round(abs(math.degrees(d)))


def _awake_foes(snap: dict) -> list:
    out = []
    for c in snap.get("chars") or []:
        # npc < 200000: NPCs in our recordings (120100 at the ramp top in a human demo) — foes are 2xxxxx/3xxxxx (assumed)
        if (c.get("x") is None or (c.get("hp") or 0) <= 0 or c.get("npc") in NOT_FOE or (c.get("npc") or 0) < 200000
                or c.get("team") in (1,)):
            continue
        a = c.get("anim")
        if a is not None and 9000 <= a < 9100:
            continue
        out.append(c)
    return out


def _kind(npc) -> str:
    import places
    return places._kind(npc, True)


def _zone(p: dict):
    import places
    z = places.zone(p["x"], p["y"], p["z"], en=True)
    if z is None and p["y"] > 100:
        return "asylum"                                    # Northern Undead Asylum (y ≈ 180–210), no zones drawn there
    return z


def _commit_before(epoch: float):
    try:
        out = subprocess.run(["git", "rev-list", "-1", f"--before={int(epoch)}", "HEAD"], cwd=ROOT, capture_output=True,
                             text=True, timeout=10).stdout.strip()
        return out[:10] or None
    except Exception:
        return None


def _file_epoch(stem: str) -> float:
    return time.mktime(time.strptime(stem[:15], "%Y%m%d_%H%M%S"))


# ── candidates from bot radar recordings ──

def _scan_bot(path: Path) -> dict:
    """One streaming pass: log lines (all) and a 2 Hz sample of snapshots (positions for zones)."""
    says, snaps, last_b = [], [], -1
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            m = HEAD.match(line)
            if not m:
                continue
            rt, typ = float(m.group(1)), m.group(2)
            if typ == "say":
                says.append((rt, json.loads(line).get("line", "")))
            elif typ == "snap" and int(rt * 2) != last_b:
                last_b = int(rt * 2)
                s = json.loads(line)
                if (s.get("player") or {}).get("x") is not None:
                    snaps.append((rt, s))
    return {"says": says, "snaps": snaps}


def _nearest(snaps: list, t: float):
    lo, hi = 0, len(snaps) - 1
    if hi < 0:
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if snaps[mid][0] < t:
            lo = mid + 1
        else:
            hi = mid
    best = min((i for i in (lo - 1, lo) if 0 <= i < len(snaps)), key=lambda i: abs(snaps[i][0] - t))
    return snaps[best][1] if abs(snaps[best][0] - t) < 1.5 else None


def bot_candidates(path: Path) -> list:
    sc = _scan_bot(path)
    says, snaps = sc["says"], sc["snaps"]
    run = path.stem
    fights, cur, prev_t = [], None, 1e9
    reach, style, basic, estus = None, None, False, None
    big = []
    for rt, line in says:
        if (m := WEAPON.search(line)):
            reach = float(m.group(2))
        if "스타일:" in line:
            style = line.split("스타일:")[1].strip().split()[0]
        if "기본 플레이: 방패 + 약공만" in line:
            basic = True
        if (m := ESTUS.search(line)):
            estus = int(m.group(1))
        if (m := BBOX.search(line)):
            big.append((rt, int(m.group(2))))
        if (m := STATUS.match(line)):
            t_f = float(m.group(1))
            if cur is None or t_f < prev_t:
                cur = {"lines": [], "start": rt - t_f, "end": None, "result": None, "tag": None}
                fights.append(cur)
            prev_t = t_f
            cur["lines"].append({"rt": rt, "h": float(m.group(2)), "dy": float(m.group(3)), "anim": None if m.group(4) == "None" else int(m.group(4)),
                                 "ehp": int(m.group(5)), "hp": int(m.group(6)), "sp": int(m.group(7)), "acts": m.group(10),
                                 "reach": reach, "style": style, "basic": basic, "estus": estus})
        elif (m := END.match(line)) and cur is not None and cur["end"] is None:
            cur.update(end=rt, result=m.group(2), tag=m.group(1).strip(), dealt=int(m.group(4)), taken=int(m.group(5)))
            nums = re.findall(r"\b(\d{6})\b", m.group(1))
            cur["npc"] = int(nums[-1]) if nums else None
    out = []
    for fi, fg in enumerate(fights):
        fid = f"{run}#f{fi:03d}"
        ls = fg["lines"]
        for prev, nxt in zip(ls, ls[1:]):
            t_d = prev["rt"]                                   # state at the previous line, the next line = what came after
            snap = _nearest(snaps, t_d)
            if snap is None:
                continue
            cat = _anim_cat(prev["anim"])
            end_in = (fg["end"] - t_d) if fg["end"] else None
            hit = any(t_d < bt <= t_d + 2.5 and dmg <= -100 for bt, dmg in big)
            if end_in is not None and end_in <= 4 and fg["result"] == "me_dead":
                ev = "before_death"
            elif end_in is not None and end_in <= 3 and fg["result"] in LS.END_TACTIC:
                ev = "before_retreat"
            elif hit:
                ev = "before_big_hit"
            elif cat in ("staggered", "guard_broken", "downed", "getting_up"):
                ev = "opening"
            elif cat == "swinging" and prev["h"] < 4:
                ev = "swing"
            elif prev["h"] <= 2.5:
                ev = "close_idle"
            else:
                ev = "far"
            out.append({"source": "bot", "source_file": str(path.relative_to(ROOT)).replace("\\", "/"), "run_id": run,
                        "fight_id": fid, "t_d": round(t_d, 2), "event": ev, "zone": _zone(snap["player"]),
                        "npc": fg.get("npc"), "result": fg["result"] or "unknown", "y": snap["player"]["y"],
                        "_line": prev, "_next": nxt, "_fight": fg})
    return out


# ── candidates from human demos (observe_record) ──

def _load_human(stem: str) -> list:
    import radar_record
    return radar_record.load(ROOT / "data" / "observe" / f"{stem}.jsonl")


def human_candidates(stem: str, msgs: list | None = None) -> list:
    msgs = msgs if msgs is not None else _load_human(stem)
    snaps = [(m["rt"], m) for m in msgs if m.get("type") == "snap" and (m.get("player") or {}).get("x") is not None]
    out, fight, last_close, prev_cat, prev_hp, fi = [], None, -1e9, None, None, -1
    for rt, s in snaps:
        p = s["player"]
        foes = [c for c in _awake_foes(s) if _horiz(p, c) < 4.5 and abs(c["y"] - p["y"]) < 1.5]
        hp = p.get("hp")
        if foes:
            tgt = min(foes, key=lambda c: _horiz(p, c))
            if rt - last_close > 3.0:
                fi += 1
                fight = {"id": f"human-{stem}#f{fi:03d}", "start": rt, "npc": tgt.get("npc"), "ptrs": set(), "result": "survived"}
                ev = "close_idle" if _horiz(p, tgt) <= 2.5 else "far"
                out.append({"t_d": rt, "event": ev, "fight": fight})
            last_close = rt
            fight["ptrs"].add(tgt.get("ptr"))
            cat = _anim_cat(tgt.get("anim"))
            if cat != prev_cat and cat == "swinging":
                out.append({"t_d": rt, "event": "swing", "fight": fight})
            elif cat != prev_cat and cat in ("staggered", "guard_broken", "downed"):
                out.append({"t_d": rt, "event": "opening", "fight": fight})
            if prev_hp is not None and hp is not None and hp < prev_hp - 100:
                out.append({"t_d": rt - 0.5, "event": "before_big_hit", "fight": fight})
            prev_cat = cat
        if fight is not None and fight["result"] == "survived" and any(
                c.get("ptr") in fight["ptrs"] and c.get("hp") is not None and c["hp"] <= 0 for c in s.get("chars") or []):
            fight["result"] = "killed"                         # _awake_foes drops dead ones — look at every char
        if hp is not None and hp <= 0 and fight is not None:
            fight["result"] = "me_dead"
        prev_hp = hp
    for c in out:
        s = _nearest(snaps, c["t_d"])
        f = c.pop("fight")
        c.update(source="human_demo", source_file=f"data/observe/{stem}.jsonl", run_id=f"human-{stem}", fight_id=f["id"],
                 t_d=round(c["t_d"], 2), zone=_zone(s["player"]) if s else None, npc=f["npc"], result=f["result"],
                 y=s["player"]["y"] if s else 0.0)
    return [c for c in out if c["zone"] is not None or c["y"] > 100]


# ── selection ──

QUOTA = {"swing": 9, "opening": 6, "close_idle": 6, "far": 4, "before_big_hit": 6, "before_retreat": 5, "before_death": 3}


def select(cands: list, n: int = 40, seed: int = SEED) -> list:
    """Stratified greedy: one scene per fight (two only from a long fight, different events, ≥ 5 s apart), ≤ 4 per run,
    ≤ 8 on the ramp, events by QUOTA, then spread over zones, foe kinds, outcomes and sources."""
    rng = random.Random(seed)
    pool = cands[:]
    rng.shuffle(pool)
    picked, per_fight, per_run = [], collections.defaultdict(list), collections.Counter()
    cnt = {k: collections.Counter() for k in ("event", "zone", "kind", "result", "source")}
    want_src = {"bot": round(n * 0.65), "human_demo": n - round(n * 0.65)}

    def ok(c) -> bool:
        f = per_fight[c["fight_id"]]
        if len(f) >= 2 or (f and (f[0]["event"] == c["event"] or abs(f[0]["t_d"] - c["t_d"]) < 5.0)):
            return False
        if f and len(picked) < n * 0.9:
            return False                                       # a second scene from a fight only to fill the last slots
        if per_run[c["run_id"]] >= 4 or (c["zone"] in ("ramp", "ramp flat", "ramp top") and
                                          sum(cnt["zone"][z] for z in ("ramp", "ramp flat", "ramp top")) >= 8):
            return False
        return cnt["event"][c["event"]] < QUOTA.get(c["event"], 3) + 2 and cnt["source"][c["source"]] < want_src[c["source"]] + 2

    def gain(c) -> float:
        g = 3.0 * max(0, QUOTA.get(c["event"], 3) - cnt["event"][c["event"]])
        g += 2.0 * max(0, want_src[c["source"]] - cnt["source"][c["source"]]) / max(1, want_src[c["source"]])
        g += 1.5 / (1 + cnt["zone"][c["zone"]]) + 1.5 / (1 + cnt["kind"][_kind(c["npc"])]) + 1.0 / (1 + cnt["result"][c["result"]])
        return g + rng.random() * 0.1

    while len(picked) < n:
        best = max((c for c in pool if ok(c)), key=gain, default=None)
        if best is None:
            break
        pool.remove(best)
        picked.append(best)
        per_fight[best["fight_id"]].append(best)
        per_run[best["run_id"]] += 1
        for k, v in (("event", best["event"]), ("zone", best["zone"]), ("kind", _kind(best["npc"])), ("result", best["result"]),
                     ("source", best["source"])):
            cnt[k][v] += 1
    return picked


# ── scene building ──

def _clip_bot(path: Path, windows: dict) -> dict:
    """scene_id → messages within [t0, t1] (one streaming pass over the recording)."""
    out = {k: [] for k in windows}
    spans = sorted((t0, t1, k) for k, (t0, t1) in windows.items())
    lo, hi = min(s[0] for s in spans), max(s[1] for s in spans)
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            m = HEAD.match(line)
            if not m:
                continue
            rt = float(m.group(1))
            if rt < lo or rt > hi or m.group(2) not in ("snap", "say", "pad", "status"):
                continue
            msg = None
            for t0, t1, k in spans:
                if t0 <= rt <= t1:
                    msg = msg or json.loads(line)
                    out[k].append(msg)
    return out


def _target(snap: dict, line: dict | None, npc=None):
    p = snap["player"]
    foes = [c for c in _awake_foes(snap) if abs(c["y"] - p["y"]) < 3.0]
    if line is not None:
        m = [c for c in foes if abs(_horiz(p, c) - line["h"]) < 0.6 and c.get("hp") == line["ehp"]]
        if m:
            return m[0]
    if npc is not None:
        m = [c for c in foes if c.get("npc") == npc and _horiz(p, c) < 12]
        if m:
            return min(m, key=lambda c: _horiz(p, c))
    near = [c for c in foes if _horiz(p, c) < 12]
    return min(near, key=lambda c: _horiz(p, c)) if near else None


def _obs(snap: dict, tgt: dict, reach, style, basic, estus_left, swing_age) -> tuple[dict, dict]:
    """Observed numbers at t_d (laya_shadow.features keys where the recording has them) and what is missing, with why."""
    from souls import foes as foes_
    p = snap["player"]
    others = [c for c in _awake_foes(snap) if c.get("ptr") != tgt.get("ptr") and _horiz(p, c) < 4.5 and abs(c["y"] - p["y"]) < 1.5]
    h = round(_horiz(p, tgt), 1)
    foe = foes_.of(tgt.get("npc"))
    max_sp = p.get("max_sp") or 0
    f = {"my_hp_pct": round(p["hp"] / p["max_hp"], 2) if p.get("max_hp") else None,
         "my_stamina_pct": round(p["sp"] / max_sp, 2) if max_sp and p.get("sp") is not None else None,
         "target_kind": "ranged" if foe.ranged else foe.kind, "target_npc": tgt.get("npc"),
         "target_state": _anim_cat(tgt.get("anim")), "target_anim": tgt.get("anim"),
         "target_swing_age_s": swing_age,
         "target_hp_pct": round(tgt["hp"] / tgt["max_hp"], 2) if tgt.get("max_hp") else None,
         "distance_m": h, "height_diff_m": round(tgt["y"] - p["y"], 1),
         "weapon_reach_m": reach, "in_reach": (h <= reach) if reach else None,
         "facing_error_deg": _rel_deg(p, tgt), "target_facing_me_deg": _rel_deg(tgt, p),
         "others_within_4_5m": len(others),
         "other_swinging_near": any(_anim_cat(c.get("anim")) == "swinging" and _horiz(p, c) < 2.5 for c in others),
         "estus_left": estus_left, "fighting_style": style,
         "_shield": None if style is None else style == "guard", "_evade": None if style is None else style == "backstep",
         "_sp_ok": None, "_arena": None, "_may_retreat": True,
         "_room": (not basic and foe.circle_behind and h <= 3.5 and not others) if style is not None else
                  (foe.circle_behind and h <= 3.5 and not others)}
    if reach is None:                                       # unknown weapon: mask bounds from the weapon table (laya_shadow.allowed)
        from souls import weapons as W
        rs = [w.reach for w in vars(W).values() if isinstance(w, W.Weapon)]
        f["_reach_max"], f["_reach_min"] = max(rs), min(rs)
    f["estus_wanted"] = (estus_left > 0 and f["my_hp_pct"] is not None and f["my_hp_pct"] < 0.6) if estus_left is not None else None
    missing = {}
    for k, why in (("weapon_reach_m", "사람 시범엔 무기 정보 없음"), ("estus_left", "스냅샷에 에스트 수 없음(dsr_telemetry.flasks TODO), 봇 로그에서도 아직 안 나옴"),
                   ("fighting_style", "사람 시범엔 스타일 정보 없음"), ("my_stamina_pct", "최대 SP 없음"), ("facing_error_deg", "방향 없음")):
        if f.get(k) is None:
            missing[k] = why
    if f["in_reach"] is None:
        missing["in_reach"] = "무기 거리를 몰라 닿는지 모름"
    if f["target_state"] == "swinging" and swing_age is None:
        missing["target_swing_age_s"] = "휘두르기 시작이 이 클립 앞 — 시간 모름"
    missing["stamina_for_attack"] = "무기 sp_min 판정은 이 기록으로 안 함 (마스크에서 SP 조건은 모름으로 처리)"
    missing["arena"] = "끌어올 자리(arena)는 기록에 없음 — '자리 옮김'은 후보에서 빠짐"
    if f["estus_wanted"] is None:
        missing["estus_wanted"] = "에스트 수를 몰라 회복 후보는 HP만 보고 넣지 않음"
    return f, missing


def _swing_age(msgs: list, t_d: float, ptr) -> float | None:
    start = None
    for m in msgs:
        if m.get("type") != "snap" or m["rt"] > t_d + 0.05:
            continue
        c = next((x for x in m.get("chars") or [] if x.get("ptr") == ptr), None)
        if c is None:
            continue
        if _anim_cat(c.get("anim")) == "swinging":
            start = start if start is not None else m["rt"]
        else:
            start = None
    return round(t_d - start, 1) if start is not None else None


def _context(msgs: list, t_d: float, ptr, actor_lines: list) -> dict:
    """t_d − 3 s … t_d: target anim categories, my HP, what the actor did."""
    cats, hp, last = [], [], None
    for m in msgs:
        if m.get("type") != "snap" or not (t_d - CONTEXT_S <= m["rt"] <= t_d + 0.05):
            continue
        p = m["player"]
        if p.get("hp") is not None:
            hp.append(p["hp"])
        c = next((x for x in m.get("chars") or [] if x.get("ptr") == ptr), None)
        cat = _anim_cat(c.get("anim")) if c else "unseen"
        if cat != last:
            cats.append([round(m["rt"] - t_d, 1), cat])
            last = cat
    return {"target_states": cats, "my_hp_change": (hp[-1] - hp[0]) if hp else None, "actor_did": actor_lines}


def _buttons(msgs: list, t0: float, t1: float, slot: int = 0) -> list:
    out, prev, rt_held = [], None, False
    for m in msgs:
        if m.get("type") != "pad" or m.get("i") != slot:
            continue
        b, rt_now = m.get("btn") or 0, (m.get("rtr") or 0) > 128
        if t0 < m["rt"] <= t1 and prev is not None:
            for bit, name in BTN.items():
                if b & bit and not prev & bit:
                    out.append([round(m["rt"] - t0, 2), name])
            if rt_now and not rt_held:
                out.append([round(m["rt"] - t0, 2), "R2"])
        prev, rt_held = b, rt_now
    return out


def _hp_at(msgs: list, t: float, ptr=None):
    best = None
    for m in msgs:
        if m.get("type") == "snap" and m["rt"] <= t:
            best = m
    if best is None:
        return None
    if ptr is None:
        return best["player"].get("hp")
    c = next((x for x in best.get("chars") or [] if x.get("ptr") == ptr), None)
    return c.get("hp") if c else None


def _acts_tactics(acts: str) -> dict:
    import laya_eval
    done = collections.Counter()
    for part in acts.split():
        name, _, n = part.rpartition("×")
        t = laya_eval.note_tactic(name or part)
        if t:
            done[t] += int(n) if n.isdigit() else 1
    return dict(done)


def build_scene(c: dict, msgs: list) -> dict:
    t_d = c["t_d"]
    snap = _nearest([(m["rt"], m) for m in msgs if m.get("type") == "snap" and (m.get("player") or {}).get("x") is not None], t_d)
    if snap is None:
        raise ValueError("no snapshot at t_d")
    line = c.get("_line")
    tgt = _target(snap, line, c.get("npc"))
    if tgt is None:
        raise ValueError("no target near t_d")
    bot = c["source"] == "bot"
    reach = line["reach"] if bot else None
    style = line["style"] if bot else None
    estus_left = line["estus"] if bot else None
    obs, missing = _obs(snap, tgt, reach, style, line["basic"] if bot else False, estus_left, _swing_age(msgs, t_d, tgt.get("ptr")))
    allowed = LS.allowed(obs)
    if bot:
        fg = c["_fight"]
        prior = [l for l in fg["lines"] if t_d - CONTEXT_S < l["rt"] <= t_d]
        actor = [[round(l["rt"] - t_d, 1), _acts_tactics(l["acts"])] for l in prior]
        nxt = c["_next"]
        after_actor = {"bot_action": _acts_tactics(nxt["acts"]), "bot_acts_raw": nxt["acts"]}
        result = fg["result"] or "unknown"
    else:
        actor = _buttons(msgs, t_d - CONTEXT_S, t_d)
        actor = [[round(dt - CONTEXT_S, 2), b] for dt, b in actor]
        after_actor = {"human_pressed": _buttons(msgs, t_d, t_d + 1.5)}
        result = c["result"]
    hp0 = _hp_at(msgs, t_d)
    e0 = _hp_at(msgs, t_d, tgt.get("ptr"))
    after = {**after_actor,
             "my_hp_change_1_5s": (_hp_at(msgs, t_d + 1.5) - hp0) if hp0 is not None and _hp_at(msgs, t_d + 1.5) is not None else None,
             "my_hp_change_3s": (_hp_at(msgs, t_d + 3.0) - hp0) if hp0 is not None and _hp_at(msgs, t_d + 3.0) is not None else None,
             "target_hp_change_3s": (_hp_at(msgs, t_d + 3.0, tgt.get("ptr")) - e0) if e0 is not None and _hp_at(msgs, t_d + 3.0, tgt.get("ptr")) is not None else None,
             "fight_result": result}
    zone = c["zone"]
    test = zone in TEST_ZONES or tgt.get("npc") in TEST_NPCS or c.get("npc") in TEST_NPCS or (not bot and zone == "asylum")
    sid = hashlib.md5(f"{c['source_file']}|{t_d}".encode()).hexdigest()[:10]
    return {"scene_id": sid, "schema": SCENE_SCHEMA, "source": c["source"], "source_file": c["source_file"], "run_id": c["run_id"],
            "fight_id": c["fight_id"], "t_d": t_d, "clip": [round(t_d - PRE_S, 2), round(t_d + POST_S, 2)],
            "segment": zone, "enemy": {"npc": tgt.get("npc"), "kind": _kind(tgt.get("npc"))}, "event": c["event"],
            "code_commit": _commit_before(_file_epoch(c["run_id"]) + t_d) if bot else None, "code_commit_approx": bot,
            "obs": {k: v for k, v in obs.items() if not k.startswith("_")}, "mask_inputs": {k: v for k, v in obs.items() if k.startswith("_")},
            "context": _context(msgs, t_d, tgt.get("ptr"), actor),
            "obs_notes": {"target_swing_age_s": "10 Hz 스냅샷 기준, ±0.1 s", "target_state": "애니 번호 범위로 나눈 범주 (souls/moves.py)",
                          **({"estus_left": "봇 로그의 마지막 음용 때 남은 수 — 그 뒤 휴식했으면 다를 수 있음"} if estus_left is not None else {}),
                          **({"weapon_reach_m": "무기를 몰라 후보 계산은 무기표의 가장 짧은·긴 거리로"} if reach is None else {})},
            "allowed": allowed, "allowed_basis": "laya_shadow.allowed — 모르는 관측은 허용으로 봄(SP·옆 적), arena 없음 → 자리 옮김 제외",
            "after": after, "missing": missing, "test_candidate": bool(test),
            "test_rule": "zone in town#4/crossbow spot, enemy 255002, or human asylum (fixed before labeling)",
            "selection": {"event": c["event"], "zone": zone, "kind": _kind(c.get("npc")), "result": result, "source": c["source"]}}


def build(n: int = 40) -> None:
    t0 = time.time()
    cands = []
    for p in sorted((ROOT / "data" / "radar").glob("2026*.jsonl")):
        if p.stat().st_size < 1_000_000:
            continue
        cs = bot_candidates(p)
        cands += cs
        print(f"  bot   {p.name}: {len(cs)} candidates ({len({c['fight_id'] for c in cs})} fights)")
    human_msgs = {}
    for stem in HUMAN_FILES:
        human_msgs[stem] = _load_human(stem)
        cs = human_candidates(stem, human_msgs[stem])
        cands += cs
        print(f"  human {stem}: {len(cs)} candidates ({len({c['fight_id'] for c in cs})} fights)")
    print(f"{len(cands)} candidates, {len({c['fight_id'] for c in cands})} fights ({time.time() - t0:.0f} s)")
    picked = select(cands, n)
    CLIPS.mkdir(parents=True, exist_ok=True)
    scenes, by_file = [], collections.defaultdict(list)
    for c in picked:
        by_file[c["source_file"]].append(c)
    for src, cs in by_file.items():
        if src.startswith("data/observe/"):
            allm = human_msgs[Path(src).stem]
            clips = {id(c): [m for m in allm if c["t_d"] - PRE_S <= m["rt"] <= c["t_d"] + POST_S] for c in cs}
        else:
            clips = _clip_bot(ROOT / src, {id(c): (c["t_d"] - PRE_S, c["t_d"] + POST_S) for c in cs})
        for c in cs:
            try:
                s = build_scene(c, clips[id(c)])
            except ValueError as e:
                print(f"  skip {src} {c['t_d']}: {e}")
                continue
            msgs = [m for m in clips[id(c)] if s["clip"][0] <= m["rt"] <= s["clip"][1]]
            (CLIPS / f"{s['scene_id']}.jsonl").write_text("\n".join(json.dumps(m, ensure_ascii=False) for m in msgs) + "\n", encoding="utf-8")
            scenes.append(s)
    scenes.sort(key=lambda s: s["scene_id"])
    LABELS.mkdir(parents=True, exist_ok=True)
    SCENES.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in scenes) + "\n", encoding="utf-8")
    print(f"{len(scenes)} scenes → {SCENES}")
    summary(scenes)


def summary(scenes: list) -> None:
    for k in ("source", "event", "segment", "result"):
        c = collections.Counter(s["selection"][k] if k in s["selection"] else s[k] for s in scenes)
        print(f"  {k}: " + ", ".join(f"{a} {b}" for a, b in c.most_common()))
    print("  enemy: " + ", ".join(f"{a} {b}" for a, b in collections.Counter(s["enemy"]["kind"] for s in scenes).most_common()))
    print(f"  fights {len({s['fight_id'] for s in scenes})} · runs {len({s['run_id'] for s in scenes})} · test candidates "
          f"{sum(s['test_candidate'] for s in scenes)}")


# ── labels ──

def validate_label(d: dict, scene: dict) -> list:
    errs = []
    tac = set(LS.TACTICS)
    acc, forb = set(d.get("acceptable") or []), set(d.get("forbidden") or [])
    if not d.get("labeler_id") or len(str(d["labeler_id"])) > 40:
        errs.append("labeler_id")
    if not acc <= tac or not forb <= tac:
        errs.append("unknown tactic")
    if acc & forb:
        errs.append("a tactic is both acceptable and forbidden")
    if d.get("best") not in (None, "") and d["best"] not in acc:
        errs.append("best must be one of acceptable")
    if not d.get("unsure") and not acc and not forb:
        errs.append("choose at least one tactic, or mark unsure")
    if d.get("unsure") and d.get("unsure_reason") not in ("정보 부족", "화면으로 안 보임", "전술 정의가 애매", "기타"):
        errs.append("unsure_reason")
    keys = set(scene["obs"]) | {"context." + k for k in scene["context"]}
    if not set(d.get("evidence") or []) <= keys:
        errs.append("evidence must name obs/context keys")
    for k in ("rationale", "definition_note"):
        if len(str(d.get(k) or "")) > 400:
            errs.append(f"{k} too long")
    return errs


def make_label(d: dict, scene: dict) -> dict:
    """Only the fields a person chose — nothing from scene['after'] is copied."""
    return {"scene_id": scene["scene_id"], "schema": LABEL_SCHEMA, "label_source": "human_verified",
            "labeler_id": str(d["labeler_id"]), "labeled_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "duration_s": round(float(d.get("duration_s") or 0), 1), "saw_after": bool(d.get("saw_after")),
            "acceptable": sorted(set(d.get("acceptable") or [])), "forbidden": sorted(set(d.get("forbidden") or [])),
            "best": d.get("best") or None, "unsure": bool(d.get("unsure")), "unsure_reason": d.get("unsure_reason") if d.get("unsure") else None,
            "rationale": str(d.get("rationale") or ""), "evidence": sorted(set(d.get("evidence") or [])),
            "definition_note": str(d.get("definition_note") or "")}


def load_scenes() -> list:
    return [json.loads(l) for l in SCENES.read_text(encoding="utf-8").splitlines() if l.strip()]


def latest_labels() -> dict:
    out = {}
    if LABEL_FILE.exists():
        for l in LABEL_FILE.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                out[(r["scene_id"], r["labeler_id"])] = r
    return out


def scene_for_page(s: dict, phase: str) -> dict:
    """What the page shows: no test flag, no selection reasons; 'after' only once revealed."""
    out = {k: v for k, v in s.items() if k not in ("test_candidate", "test_rule", "selection", "mask_inputs") and (phase == "full" or k != "after")}
    return out


def clip_msgs(s: dict, phase: str) -> list:
    msgs = [json.loads(l) for l in (CLIPS / f"{s['scene_id']}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if phase == "pre":
        # before 'after' is opened: nothing past t_d, and none of the rules' output on the radar — the bot's log lines and its
        # intent on every snapshot (planned path, held spot, camera target, crate to smash: radar.intent_dict)
        msgs = [{k: v for k, v in m.items() if k not in INTENT_KEYS} for m in msgs if m["rt"] <= s["t_d"] and m.get("type") != "say"]
    msgs.append({"rt": s["t_d"], "type": "say", "t": s["t_d"], "line": "F9 marker ▶ 결정 시점"})
    return sorted(msgs, key=lambda m: m["rt"])


# ── server ──

def serve(port: int = HTTP_PORT) -> None:
    import radar_mesh
    import radar_record
    import radar_server as RS
    from urllib.parse import parse_qs, urlparse
    scenes = load_scenes()
    by_id = {s["scene_id"]: s for s in scenes}
    state = RS.State(english=False)
    try:
        state.mesh = radar_mesh.load(["m10_02_00_00", "m10_01_00_00", "m18_01_00_00"])
    except Exception as e:
        print(f"navmesh not drawn: {e!r}")
    first = clip_msgs(scenes[0], "pre")
    rp = radar_record.Replay(state, first, scenes[0]["scene_id"]).start()
    state.replay = rp
    lock = threading.Lock()

    def load_scene(s: dict, phase: str) -> None:
        msgs = clip_msgs(s, phase)
        with rp.lock:
            rp.msgs, rp.name = msgs, f"{s['scene_id']} ({'전체' if phase == 'full' else '결정 시점까지'})"
            rp.t0, rp.t1 = msgs[0]["rt"], msgs[-1]["rt"]
            rp.markers = [m["rt"] for m in msgs if m.get("type") == "say" and str(m.get("line", "")).startswith("F9 marker")]
            rp.playing = False
        rp.seek(s["t_d"] - rp.t0)

    Base = RS.make_handler(state)
    page = ROOT / "label.html"

    class H(Base):
        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path in ("/", "/label"):
                return self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/radar":
                return self._send(200, RS.PAGE.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/scenes":
                lab = latest_labels()
                who = q.get("labeler", [""])[0]
                body = [{"scene_id": s["scene_id"], "event": s["event"], "segment": s["segment"], "source": s["source"],
                         "labeled": (s["scene_id"], who) in lab} for s in scenes]
                return self._send(200, json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            if u.path == "/scene":
                s = by_id.get(q.get("id", [""])[0])
                if s is None:
                    return self._send(404, b"no scene", "text/plain")
                phase = "full" if q.get("phase", ["pre"])[0] == "full" else "pre"
                with lock:
                    load_scene(s, phase)
                body = {"scene": scene_for_page(s, phase), "tactics": LS.TACTICS, "tactics_ko": TACTIC_KO, "seek_rel": s["t_d"] - rp.t0,
                        "label": latest_labels().get((s["scene_id"], q.get("labeler", [""])[0]))}
                return self._send(200, json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            return super().do_GET()

        def do_POST(self):
            if urlparse(self.path).path != "/label":
                return self._send(404, b"not found", "text/plain")
            if not RS.same_origin(self.headers, self.server.server_address[1]):
                return self._send(403, b"forbidden", "text/plain")
            try:
                n = int(self.headers.get("Content-Length") or 0)
                d = json.loads(self.rfile.read(min(n, 20000)) or b"{}")
                s = by_id[d.get("scene_id")]
            except Exception as e:
                return self._send(400, json.dumps({"ok": False, "errors": [repr(e)[:100]]}).encode(), "application/json")
            errs = validate_label(d, s)
            if errs:
                return self._send(400, json.dumps({"ok": False, "errors": errs}, ensure_ascii=False).encode("utf-8"), "application/json")
            row = make_label(d, s)
            with lock, LABEL_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            self._send(200, json.dumps({"ok": True}).encode(), "application/json")

    srv = RS.RadarHTTPServer(("127.0.0.1", port), H)
    print(f"label pilot: http://127.0.0.1:{port}  ({len(scenes)} scenes, labels → {LABEL_FILE})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


# ── report ──

def report() -> None:
    scenes = {s["scene_id"]: s for s in load_scenes()}
    labs = list(latest_labels().values())
    print(f"scenes {len(scenes)} · fights {len({s['fight_id'] for s in scenes.values()})} · labels {len(labs)}")
    miss = collections.Counter(k for s in scenes.values() for k in s["missing"])
    print("  missing observations (scenes): " + ", ".join(f"{k} {v}" for k, v in miss.most_common()))
    for who in sorted({l["labeler_id"] for l in labs}):
        ls = [l for l in labs if l["labeler_id"] == who]
        d = sorted(l["duration_s"] for l in ls)
        uns = [l for l in ls if l["unsure"]]
        print(f"\n  labeler {who}: {len(ls)} scenes, fights {len({scenes[l['scene_id']]['fight_id'] for l in ls if l['scene_id'] in scenes})}")
        print(f"    time per scene: median {d[len(d) // 2]:.0f} s · p90 {d[int(.9 * (len(d) - 1))]:.0f} s · total {sum(d) / 60:.0f} min")
        print(f"    unsure {len(uns)} ({100 * len(uns) / len(ls):.0f} %): " + ", ".join(f"{k} {v}" for k, v in collections.Counter(l['unsure_reason'] for l in uns).items()))
        print(f"    saw 'after' before saving: {sum(l['saw_after'] for l in ls)}")
        print(f"    acceptable set size: " + ", ".join(f"{k} {v}" for k, v in sorted(collections.Counter(len(l['acceptable']) for l in ls).items())))
        off = [(l["scene_id"], t) for l in ls for t in l["acceptable"] if l["scene_id"] in scenes and t not in scenes[l["scene_id"]]["allowed"]]
        print(f"    acceptable but outside the rule mask: {len(off)} " + str(off[:6]))
        for l in ls:
            if l["definition_note"]:
                print(f"    definition note [{l['scene_id']}]: {l['definition_note']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--n", type=int, default=40)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=HTTP_PORT)
    sub.add_parser("report")
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.n)
    elif a.cmd == "serve":
        serve(a.port)
    else:
        report()


if __name__ == "__main__":
    main()
