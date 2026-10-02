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
SCENE_SCHEMA, LABEL_SCHEMA = "dsr-scene/0.2", "dsr-label/0.3"
CONFIDENCE = ("low", "mid", "high")
REVEALS = LABELS / "pilot_reveals.jsonl"   # who opened 'after' for which scene, when — decides a label's stage
OUTSIDE_INPUT = {"terrain": "지형 (가장자리·벽·좁은 곳)", "my_anim": "내 동작 (구르는 중·경직·공격 중)", "lock_on": "락온",
                 "weapon_reach": "무기 거리", "far_enemies": "4.5 m 밖 적", "enemy_identity": "적 이름·스폰 번호",
                 "ai_range": "적 인식 범위 (AI ranges)", "replay_motion": "재생으로 본 움직임 (속도·방향)", "other": "기타"}
UNSURE_REASONS = ("정보 부족", "화면으로 안 보임", "전술 정의가 애매", "기타")
LABEL_SOURCE = "human_verified"   # serve --labels-dir (trying the page out) writes "ui_trial" instead — never counted
REVIEW_BOT = False                 # serve --review-bot: bot scenes open pre-filled with what the bot did; the labeler fixes what's wrong


def bot_prefill(scene: dict) -> dict | None:
    """What the bot did in the second after t_d, as a starting answer ([MoKa] 2026-10-01: "아닌 것만 내가 변경") —
    best = the tactic it spent most ticks on, acceptable = every tactic it did. None for human demos or when the bot's
    log names map to no tactic."""
    a = scene.get("after") or {}
    done = {t: n for t, n in (a.get("bot_action_as_tactic") or {}).items() if t in LS.TACTICS}
    if scene.get("source") != "bot" or not done:
        return None
    return {"best": max(done, key=done.get), "acceptable": sorted(done), "bot_logged": a.get("bot_logged", "")}
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


EVENT_RANK = ["before_death", "before_retreat", "before_big_hit", "opening", "swing", "close_idle", "far"]


def select_fights(cands: list, per_fight: int = 2, seed: int = SEED) -> list:
    """For a set made from chosen recordings (e.g. ramp runs): every fight, up to per_fight scenes with different events,
    ≥ 3 s apart, rarer events first. Deterministic."""
    rng = random.Random(seed)
    by_fight = collections.defaultdict(list)
    for c in cands:
        by_fight[c["fight_id"]].append(c)
    out = []
    for fid in sorted(by_fight):
        cs = by_fight[fid][:]
        rng.shuffle(cs)
        cs.sort(key=lambda c: EVENT_RANK.index(c["event"]) if c["event"] in EVENT_RANK else 99)
        got = []
        for c in cs:
            if len(got) >= per_fight:
                break
            if all(g["event"] != c["event"] and abs(g["t_d"] - c["t_d"]) >= 3.0 for g in got):
                got.append(c)
        out += got
    return out


def use_set(name: str) -> None:
    """'pilot' = the first 40 scenes (data/labels/pilot_*). Any other name: data/labels/<name>_scenes/labels/reveals.jsonl."""
    global SCENES, LABEL_FILE, REVEALS
    SCENES, LABEL_FILE, REVEALS = (LABELS / f"{name}_scenes.jsonl", LABELS / f"{name}_labels.jsonl", LABELS / f"{name}_reveals.jsonl")


_SHOTS = None


def _shots_for(epoch: float | None, hz: float = 2.0) -> list:
    """Screenshots (shots.py, data/shots/*/<epoch ms>.jpg) from t_d − PRE_S to t_d + POST_S, at most hz per second."""
    global _SHOTS
    if epoch is None:
        return []
    if _SHOTS is None:
        _SHOTS = sorted((int(p.stem) / 1000.0, p) for p in (ROOT / "data" / "shots").glob("*/*.jpg") if p.stem.isdigit())
    out, last = [], -1e9
    for t, p in _SHOTS:
        if epoch - PRE_S <= t <= epoch + POST_S and t - last >= 1.0 / hz - 1e-3:
            out.append({"dt": round(t - epoch, 2), "file": str(p.relative_to(ROOT)).replace("\\", "/")})
            last = t
    return out


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
         # mask inputs. Human demos: the question is what *the current bot* could do there, so its default setup is assumed
         # (guard style, backstab on) — obs_provenance says so. Rolling is never a tactic.
         "_shield": (style or "guard") == "guard", "_evade": (style or "guard") == "backstep",
         "_sp_ok": None, "_arena": None, "_may_retreat": True, "_backstab_on": not basic,
         "_room": not basic and foe.circle_behind and h <= 3.5 and not others}
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


PROV_COMMON = {
    "target_state": ("derived", "애니 번호 범위 → 범주 (souls/moves.py)"),
    "target_kind": ("derived", "npc 번호 → souls/foes.py 표"),
    "target_swing_age_s": ("derived", "10 Hz 스냅샷에서 휘두르기 시작부터 잼, ±0.1 s"),
    "in_reach": ("derived", "distance_m ≤ weapon_reach_m"),
    "other_swinging_near": ("derived", "2.5 m 안 다른 적의 애니 범주"),
}
PROV_BOT = {
    "weapon_reach_m": ("logged", "실행 로그 '무기:' 줄 (souls/weapons.py 값)"),
    "fighting_style": ("logged", "실행 로그 '스타일:' 줄"),
    "estus_left": ("estimated", "실행 로그의 마지막 음용 'left' — 그 뒤 휴식·사망했으면 다름"),
    "estus_wanted": ("estimated", "estus_left 추정값 > 0 이고 HP < 60 %"),
    "mask._backstab_on": ("logged", "'기본 플레이' 줄(--basic) 유무"),
    "mask._room": ("estimated", "--basic 아님 + 망자 + 3.5 m 안 + 4.5 m 안 다른 적 없음 — 뒤 공간(NavMesh)은 안 봄"),
}
PROV_HUMAN = {
    "mask._shield": ("assumed", "사람 시범: 지금 봇의 기본 설정(guard 스타일)으로 후보를 계산"),
    "mask._evade": ("assumed", "사람 시범: 기본 guard 스타일엔 백스텝 회피 없음 — 사람이 구른 것과 무관"),
    "mask._backstab_on": ("assumed", "사람 시범: 봇 기본값(뒤잡기 켜짐)"),
    "mask._room": ("estimated", "망자 + 3.5 m 안 + 4.5 m 안 다른 적 없음 — 뒤 공간(NavMesh)은 안 봄"),
    "mask._reach_max": ("assumed", "무기 모름 → souls/weapons.py 표의 가장 긴 거리로 공격 후보"),
    "mask._reach_min": ("assumed", "무기 모름 → 표의 가장 짧은 거리로 접근 후보"),
}


def _provenance(obs: dict, bot: bool) -> dict:
    """Values that are not plain readings of the recording: where they came from. Anything not listed = read directly."""
    p = {**PROV_COMMON, **(PROV_BOT if bot else PROV_HUMAN)}
    return {k: {"kind": kind, "how": how} for k, (kind, how) in p.items()
            if (k.startswith("mask.") and k[5:] in obs) or obs.get(k) is not None}


def _b_detail(msgs: list, t_press: float) -> dict:
    """A B press in a human demo: how long it was held and the player's first anim after it. B is roll, backstep or sprint
    in DSR — the anim tells them apart only partly (690 = backstep: the bot's backstep logs it; 710 is the usual tap result
    and looks like a roll, not confirmed). Kept as an observed fact; never turned into a tactic."""
    release = next((m["rt"] for m in msgs if m.get("type") == "pad" and m.get("i") == 0 and m["rt"] > t_press
                    and not (m.get("btn") or 0) & 0x2000), None)
    hold = round(release - t_press, 2) if release is not None else None
    anim = next((m["player"].get("anim") for m in msgs if m.get("type") == "snap" and t_press < m["rt"] <= t_press + 0.6
                 and m["player"].get("anim") not in (-1, None)), None)
    if anim == 690:
        guess = "백스텝 (애니 690 — 봇 백스텝 기록과 같음)"
    elif anim is not None and 600 <= anim < 800:
        guess = f"구르기로 보임 (애니 {anim}, 번호 미확인)"
    elif hold is not None and hold >= 0.3:
        guess = "달리기로 보임 (길게 누름, 애니 변화 없음)"
    else:
        guess = "모름"
    return {"hold_s": hold, "my_anim_after": anim, "guess": guess}


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


def _buttons(msgs: list, t0: float, t1: float, origin: float, slot: int = 0) -> list:
    """Presses in (t0, t1] as raw buttons, time relative to origin (t_d). B presses carry _b_detail."""
    out, prev, rt_held = [], None, False
    for m in msgs:
        if m.get("type") != "pad" or m.get("i") != slot:
            continue
        b, rt_now = m.get("btn") or 0, (m.get("rtr") or 0) > 128
        if t0 < m["rt"] <= t1 and prev is not None:
            for bit, name in BTN.items():
                if b & bit and not prev & bit:
                    e = {"dt": round(m["rt"] - origin, 2), "button": name}
                    if name == "B":
                        e.update(_b_detail(msgs, m["rt"]))
                    out.append(e)
            if rt_now and not rt_held:
                out.append({"dt": round(m["rt"] - origin, 2), "button": "R2"})
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
    # observed actions stay in the recording's own words: the bot's log names (Fight.note), the human's raw buttons —
    # not tactic names, so they can't be read as candidates or answers
    if bot:
        fg = c["_fight"]
        prior = [l for l in fg["lines"] if t_d - CONTEXT_S < l["rt"] <= t_d]
        actor = [{"dt": round(l["rt"] - t_d, 1), "logged": l["acts"]} for l in prior]
        nxt = c["_next"]
        after_actor = {"bot_logged": nxt["acts"],
                       "bot_action_as_tactic": _acts_tactics(nxt["acts"]),
                       "bot_action_as_tactic_note": "규칙 기록 이름을 전술 이름으로 옮긴 것 — 규칙 기준선 비교용, 정답 아님"}
        result = fg["result"] or "unknown"
    else:
        actor = _buttons(msgs, t_d - CONTEXT_S, t_d, t_d)
        after_actor = {"human_pressed": _buttons(msgs, t_d, t_d + 1.5, t_d)}
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
            "obs_provenance": _provenance(obs, bot),
            "t_epoch": round(snap["t"], 3) if (snap.get("t") or 0) > 1e9 else None,
            "shots": _shots_for(snap["t"] if (snap.get("t") or 0) > 1e9 else None),
            "context": _context(msgs, t_d, tgt.get("ptr"), actor),
            "allowed": allowed, "unavailable": LS.why_not(obs),
            "after": after, "missing": missing, "test_candidate": bool(test),
            "test_rule": "zone in town#4/crossbow spot, enemy 255002, or human asylum (fixed before labeling)",
            "selection": {"event": c["event"], "zone": zone, "kind": _kind(c.get("npc")), "result": result, "source": c["source"]}}


# what MoKa says a foe is, where the bot's data (souls/foes.py) differs — shown to the labeler next to the bot's kind;
# obs.target_kind stays the bot's belief (that is what the bot acted on)
FOE_NOTE = {254001: "망자 — 방패 없이 도끼를 양손으로 잡고 공격 (MoKa 2026-10-01). 봇 데이터(foes.py)는 아직 화염병 투척병으로 분류"}


def _tag_runs(scenes: list) -> None:
    """Chosen-recording sets: which bot run (data/runs/<stamp>_<cmd>.log: start = stamp, end = last write) each scene is
    from, and the test rule fixed before labeling — the set's last run is the test candidate."""
    logs = []
    for p in (ROOT / "data" / "runs").glob("*.log"):
        try:
            logs.append((_file_epoch(p.stem), p.stat().st_mtime, p.stem))
        except ValueError:
            pass
    for s in scenes:
        t = s.get("t_epoch")
        hit = [stem for t0, t1, stem in logs if t is not None and t0 <= t <= t1 + 1.0]
        s["bot_run"] = hit[0] if hit else None
        s["run_id"] = s["bot_run"] or s["run_id"]
        if s["enemy"]["npc"] in FOE_NOTE:
            s["enemy"]["note"] = FOE_NOTE[s["enemy"]["npc"]]
    runs = sorted({s["bot_run"] for s in scenes if s["bot_run"]})
    for s in scenes:
        s["test_candidate"] = bool(runs) and s["bot_run"] == runs[-1]
        s["test_rule"] = "last bot run of the set (fixed before labeling)"


FIGHT_LEAD_S, MAX_PRE_S = 2.0, 20.0   # chosen-recording sets: replay from the fight's start (− 2 s), at most 20 s back


def build(n: int = 40, radar: list | None = None, per_fight: int = 2) -> None:
    """Without radar: the original 40-scene pilot (all recordings, stratified select). With radar: only those bot
    recordings, every fight (select_fights), replay from the fight's start, screenshots attached."""
    t0 = time.time()
    cands = []
    files = [ROOT / r for r in radar] if radar else [p for p in sorted((ROOT / "data" / "radar").glob("2026*.jsonl"))
                                                    if p.stat().st_size >= 1_000_000]
    for p in files:
        cs = bot_candidates(p)
        cands += cs
        print(f"  bot   {p.name}: {len(cs)} candidates ({len({c['fight_id'] for c in cs})} fights)")
    human_msgs = {}
    for stem in ([] if radar else HUMAN_FILES):
        human_msgs[stem] = _load_human(stem)
        cs = human_candidates(stem, human_msgs[stem])
        cands += cs
        print(f"  human {stem}: {len(cs)} candidates ({len({c['fight_id'] for c in cs})} fights)")
    print(f"{len(cands)} candidates, {len({c['fight_id'] for c in cands})} fights ({time.time() - t0:.0f} s)")
    picked = select_fights(cands, per_fight) if radar else select(cands, n)

    def pre_from(c) -> float:
        if not radar:
            return c["t_d"] - PRE_S
        return max(c["_fight"]["start"] - FIGHT_LEAD_S, c["t_d"] - MAX_PRE_S) if c.get("_fight") else c["t_d"] - PRE_S

    CLIPS.mkdir(parents=True, exist_ok=True)
    scenes, by_file = [], collections.defaultdict(list)
    for c in picked:
        by_file[c["source_file"]].append(c)
    for src, cs in by_file.items():
        if src.startswith("data/observe/"):
            allm = human_msgs[Path(src).stem]
            clips = {id(c): [m for m in allm if c["t_d"] - PRE_S <= m["rt"] <= c["t_d"] + POST_S] for c in cs}
        else:
            clips = _clip_bot(ROOT / src, {id(c): (min(pre_from(c), c["t_d"] - PRE_S), c["t_d"] + POST_S) for c in cs})
        for c in cs:
            try:
                s = build_scene(c, clips[id(c)])
            except ValueError as e:
                print(f"  skip {src} {c['t_d']}: {e}")
                continue
            s["clip"][0] = round(min(pre_from(c), s["clip"][0]), 2)
            msgs = [m for m in clips[id(c)] if s["clip"][0] <= m["rt"] <= s["clip"][1]]
            (CLIPS / f"{s['scene_id']}.jsonl").write_text("\n".join(json.dumps(m, ensure_ascii=False) for m in msgs) + "\n", encoding="utf-8")
            scenes.append(s)
    if radar:
        _tag_runs(scenes)
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
    """Three different 'no answer' cases stay apart: unsure (the labeler lacks information), no_good_action (nothing in the
    bot's current tactic set fits — e.g. only a roll would do), model_input_sufficient = False (the labeler can judge, but
    only from things the model input doesn't have)."""
    errs = []
    tac = set(LS.TACTICS)
    acc, forb = set(d.get("acceptable") or []), set(d.get("forbidden") or [])
    if not d.get("labeler_id") or len(str(d["labeler_id"])) > 40:
        errs.append("labeler_id")
    if not acc <= tac or not forb <= tac:
        errs.append("unknown tactic")
    if acc & forb:
        errs.append("a tactic is both acceptable and forbidden")
    if d.get("best") not in (None, "") and (d["best"] not in tac or d["best"] in forb):
        errs.append("best must be a tactic that is not forbidden")
    if d.get("unsure") and d.get("no_good_action"):
        errs.append("unsure (missing information) and no_good_action (nothing fits) are different — pick one")
    if d.get("no_good_action") and (acc or d.get("best")):
        errs.append("no_good_action means no acceptable tactic")
    if not (d.get("best") or d.get("unsure") or d.get("no_good_action")):
        errs.append("choose the best tactic, or mark unsure / no_good_action")         # 0.3: best is the core answer
    if d.get("confidence") not in CONFIDENCE:
        errs.append("confidence: low / mid / high")
    if d.get("unsure") and d.get("unsure_reason") not in UNSURE_REASONS:
        errs.append("unsure_reason")
    outside = d.get("outside_set") or []
    if len(outside) > 5 or any(not isinstance(x, str) or not x.strip() or len(x) > 40 or x.strip() in tac for x in outside):
        errs.append("outside_set: up to 5 short names of moves the bot does not have (not tactic names)")
    oi = set(d.get("outside_input") or [])
    if not oi <= set(OUTSIDE_INPUT):
        errs.append("outside_input")
    if d.get("model_input_sufficient") is False and not oi:
        errs.append("model input not sufficient: name what the judgment needed (outside_input)")
    keys = set(scene["obs"]) | {"context." + k for k in scene["context"]}
    if not set(d.get("evidence") or []) <= keys:
        errs.append("evidence must name obs/context keys")
    for k in ("rationale", "definition_note"):
        if len(str(d.get(k) or "")) > 400:
            errs.append(f"{k} too long")
    return errs


def make_label(d: dict, scene: dict, stage: str = "pre_reveal", revision_of: str | None = None) -> dict:
    """Only the fields a person chose — nothing from scene['after'] is copied. stage/revision_of come from the server
    (label_rows + revealed), never from the page."""
    return {"scene_id": scene["scene_id"], "schema": LABEL_SCHEMA, "label_source": LABEL_SOURCE,
            "labeler_id": str(d["labeler_id"]), "labeled_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "stage": stage, "revision_of": revision_of,
            "duration_s": round(float(d.get("duration_s") or 0), 1),
            "acceptable": sorted(set(d.get("acceptable") or []) | ({d["best"]} if d.get("best") else set())),   # best is acceptable
            "forbidden": sorted(set(d.get("forbidden") or [])),
            "best": d.get("best") or None, "confidence": d.get("confidence"), "unsure": bool(d.get("unsure")), "unsure_reason": d.get("unsure_reason") if d.get("unsure") else None,
            "no_good_action": bool(d.get("no_good_action")), "outside_set": [x.strip() for x in d.get("outside_set") or []],
            "model_input_sufficient": d.get("model_input_sufficient") is not False,
            "outside_input": sorted(set(d.get("outside_input") or [])),
            "rationale": str(d.get("rationale") or ""), "evidence": sorted(set(d.get("evidence") or [])),
            "definition_note": str(d.get("definition_note") or "")}


def load_scenes() -> list:
    return [json.loads(l) for l in SCENES.read_text(encoding="utf-8").splitlines() if l.strip()]


def _rows(path: Path) -> list:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []


def label_rows(scene_id: str, labeler: str) -> list:
    return [r for r in _rows(LABEL_FILE) if r["scene_id"] == scene_id and r["labeler_id"] == labeler]


def revealed(scene_id: str, labeler: str) -> bool:
    return any(r["scene_id"] == scene_id and r["labeler_id"] == labeler for r in _rows(REVEALS))


def label_views(rows: list) -> dict:
    """primary = the last label saved before 'after' was opened (the first judgment), final = the last row,
    revisions = rows saved after 'after' — appended, never replacing the primary."""
    pre = [r for r in rows if r.get("stage") == "pre_reveal"]
    post = [r for r in rows if r.get("stage") == "post_reveal"]
    return {"primary": pre[-1] if pre else None, "final": rows[-1] if rows else None, "revisions": post}


_WRITE = threading.Lock()


def request_reveal(scene_id: str, labeler: str) -> tuple[bool, str]:
    """'after' opens only once this labeler has a first-pass label for the scene; the opening is logged (REVEALS),
    so every later save is a post_reveal revision."""
    if not labeler:
        return False, "라벨러 ID가 없음"
    if label_views(label_rows(scene_id, labeler))["primary"] is None:
        return False, "1차 라벨(결과 보기 전)을 먼저 저장해야 결과를 볼 수 있음"
    if not revealed(scene_id, labeler):
        with _WRITE, REVEALS.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"scene_id": scene_id, "labeler_id": labeler, "revealed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
                               ensure_ascii=False) + "\n")
    return True, ""


def save_label(d: dict, scene: dict) -> tuple[bool, object]:
    """Validate, decide the stage from the reveal log (not from the page), append. Nothing is overwritten."""
    errs = validate_label(d, scene)
    if errs:
        return False, errs
    who = str(d["labeler_id"])
    rows = label_rows(scene["scene_id"], who)
    views = label_views(rows)
    if revealed(scene["scene_id"], who):
        stage, prev = "post_reveal", views["primary"]
    else:
        stage, prev = "pre_reveal", views["primary"]          # a correction before opening 'after' — still first-pass
    row = make_label(d, scene, stage, prev["labeled_at"] if prev else None)
    pre = bot_prefill(scene) if REVIEW_BOT else None
    row["mode"] = "review_bot" if pre else "blind"
    if pre:                                                  # kept apart: confirmed the bot vs corrected it
        row["prefill"] = {"best": pre["best"], "acceptable": pre["acceptable"]}
        row["changed_from_prefill"] = (row["best"] != pre["best"] or set(row["acceptable"]) != set(pre["acceptable"])
                                       or bool(row["forbidden"]) or row["unsure"] or row["no_good_action"])
    with _WRITE, LABEL_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True, row


def latest_labels() -> dict:
    out = {}
    for r in _rows(LABEL_FILE):
        out[(r["scene_id"], r["labeler_id"])] = r
    return out


def scene_for_page(s: dict, phase: str) -> dict:
    """What the page shows: no test flag, no selection reasons, no mask internals. Before 'after' is opened also no
    'after' and no 'event' — before_big_hit / before_retreat / before_death are worked out from what happened next."""
    hidden = {"test_candidate", "test_rule", "selection", "mask_inputs"} | (set() if phase == "full" else {"after", "event"})
    out = {k: v for k, v in s.items() if k not in hidden}
    out["shots"] = [dict(x, i=i) for i, x in enumerate(s.get("shots") or []) if phase == "full" or x["dt"] <= 0]
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
    rp.rewind_at_end = True
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
            if u.path == "/shot":
                s = by_id.get(q.get("id", [""])[0])
                try:
                    shot = s["shots"][int(q.get("i", ["-1"])[0])]
                except Exception:
                    return self._send(404, b"no shot", "text/plain")
                if shot["dt"] > 0 and not revealed(s["scene_id"], q.get("labeler", [""])[0].strip()):
                    return self._send(403, b"after the decision - open 'after' first", "text/plain")
                return self._send(200, (ROOT / shot["file"]).read_bytes(), "image/jpeg")
            if u.path == "/radar":
                return self._send(200, RS.PAGE.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/scenes":
                lab = latest_labels()
                who = q.get("labeler", [""])[0]
                body = [{"scene_id": s["scene_id"], "source": s["source"], "labeled": (s["scene_id"], who) in lab} for s in scenes]
                return self._send(200, json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            if u.path == "/scene":
                s = by_id.get(q.get("id", [""])[0])
                if s is None:
                    return self._send(404, b"no scene", "text/plain")
                phase = "full" if q.get("phase", ["pre"])[0] == "full" else "pre"
                who = q.get("labeler", [""])[0].strip()
                if phase == "full":
                    ok, why = request_reveal(s["scene_id"], who)
                    if not ok:
                        return self._send(409, json.dumps({"error": why}, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                with lock:
                    load_scene(s, phase)
                views = label_views(label_rows(s["scene_id"], who))
                body = {"scene": scene_for_page(s, phase), "tactics": LS.TACTICS, "tactics_ko": TACTIC_KO, "seek_rel": s["t_d"] - rp.t0,
                        "label": views["final"], "primary": views["primary"], "revealed": revealed(s["scene_id"], who),
                        "outside_input": OUTSIDE_INPUT, "unsure_reasons": UNSURE_REASONS,
                        "prefill": bot_prefill(s) if REVIEW_BOT else None}
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
            ok, out = save_label(d, s)
            if not ok:
                return self._send(400, json.dumps({"ok": False, "errors": out}, ensure_ascii=False).encode("utf-8"), "application/json")
            self._send(200, json.dumps({"ok": True, "stage": out["stage"]}).encode(), "application/json")

    srv = RS.RadarHTTPServer(("127.0.0.1", port), H)
    print(f"label pilot: http://127.0.0.1:{port}  ({len(scenes)} scenes, labels → {LABEL_FILE})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


# ── report ──

def report() -> None:
    """Rates are per first-pass (primary) label; changes made after opening 'after' are counted separately."""
    scenes = {s["scene_id"]: s for s in load_scenes()}
    rows = [r for r in _rows(LABEL_FILE) if r.get("label_source") == "human_verified"]
    print(f"scenes {len(scenes)} · fights {len({s['fight_id'] for s in scenes.values()})} · label rows {len(rows)}")
    miss = collections.Counter(k for s in scenes.values() for k in s["missing"])
    print("  missing observations (scenes): " + ", ".join(f"{k} {v}" for k, v in miss.most_common()))
    unav = collections.Counter((t, u["why"]) for s in scenes.values() for t, u in s["unavailable"].items())
    print("  not candidates (tactic, why): " + ", ".join(f"{t}:{w} {n}" for (t, w), n in unav.most_common()))
    for who in sorted({r["labeler_id"] for r in rows}):
        per = {sid: label_views([r for r in rows if r["scene_id"] == sid and r["labeler_id"] == who]) for sid in scenes}
        prim = [v["primary"] for v in per.values() if v["primary"]]
        if not prim:
            continue
        n = len(prim)
        d = sorted(l["duration_s"] for l in prim)
        pct = lambda k: f"{k} ({100 * k / n:.0f} %)"
        print(f"\n  labeler {who}: {n} scenes (first pass), fights {len({scenes[l['scene_id']]['fight_id'] for l in prim})}")
        print(f"    time per scene: median {d[n // 2]:.0f} s · p90 {d[int(.9 * (n - 1))]:.0f} s · total {sum(d) / 60:.0f} min")
        uns = [l for l in prim if l["unsure"]]
        print(f"    unsure (missing information): {pct(len(uns))} — " + ", ".join(f"{k} {v}" for k, v in collections.Counter(l['unsure_reason'] for l in uns).items()))
        print(f"    no fitting tactic in the current set: {pct(sum(l['no_good_action'] for l in prim))} — wanted: "
              + ", ".join(f"{k} {v}" for k, v in collections.Counter(x for l in prim for x in l['outside_set']).most_common()))
        print(f"    model input alone not enough: {pct(sum(not l['model_input_sufficient'] for l in prim))} — needed: "
              + ", ".join(f"{OUTSIDE_INPUT[k]} {v}" for k, v in collections.Counter(x for l in prim for x in l['outside_input']).most_common()))
        print(f"    acceptable set size: " + ", ".join(f"{k} {v}" for k, v in sorted(collections.Counter(len(l['acceptable']) for l in prim).items())))
        off = [(l["scene_id"], t, scenes[l["scene_id"]]["unavailable"][t]["why"]) for l in prim for t in l["acceptable"]
               if t in scenes[l["scene_id"]]["unavailable"]]
        print(f"    acceptable although not a candidate: {len(off)} " + str(off[:6]))
        changed = [sid for sid, v in per.items() if v["revisions"] and v["primary"] and
                   (v["final"]["acceptable"], v["final"]["forbidden"]) != (v["primary"]["acceptable"], v["primary"]["forbidden"])]
        print(f"    opened 'after': {sum(revealed(sid, who) for sid in per)} · changed the judgment afterwards: {len(changed)} {changed[:6]}")
        for l in prim:
            if l["definition_note"]:
                print(f"    definition note [{l['scene_id']}]: {l['definition_note']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--n", type=int, default=40)
    b.add_argument("--set", default="pilot", help="scene set name (pilot = the first 40) → data/labels/<set>_*.jsonl")
    b.add_argument("--radar", nargs="*", default=None, help="only these bot radar recordings (every fight, replay from its start)")
    b.add_argument("--per-fight", type=int, default=2)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=HTTP_PORT)
    s.add_argument("--set", default="pilot")
    s.add_argument("--labels-dir", default=None, help="write labels/reveals here instead of data/labels — for trying the page out")
    s.add_argument("--review-bot", action="store_true", help="open bot scenes pre-filled with what the bot did (labels record mode/prefill)")
    r = sub.add_parser("report")
    r.add_argument("--set", default="pilot")
    a = ap.parse_args()
    if a.set != "pilot":
        use_set(a.set)
    if a.cmd == "build":
        build(a.n, a.radar, a.per_fight)
    elif a.cmd == "serve":
        if a.review_bot:
            global REVIEW_BOT
            REVIEW_BOT = True
        if a.labels_dir:
            global LABEL_FILE, REVEALS, LABEL_SOURCE
            LABEL_FILE, REVEALS = Path(a.labels_dir) / f"{a.set}_labels.jsonl", Path(a.labels_dir) / f"{a.set}_reveals.jsonl"
            LABEL_SOURCE = "ui_trial"
            print(f"labels go to {a.labels_dir} as label_source 'ui_trial', not data/labels")
        serve(a.port)
    else:
        report()


if __name__ == "__main__":
    main()
