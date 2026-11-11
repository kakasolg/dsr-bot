"""Duel simulator, first vertical slice — one sword hollow (c2540, NpcParam 254010, AI goal 254000) against a scripted player.

  python duel_sim.py                         every player policy, 200 episodes × 30 s each → summary
  python duel_sim.py --policy stand --log    one episode, every event
  python duel_sim.py --compare               sim 'stand' hits by animation vs recorded hits on 254010 (data/samples)

Offline only, not imported by the bot. 1-D: only the distance between the two matters (no facing, walls, other foes).

Every number has a source tag (`SOURCES`, printed with the summary):
  tae     data/gamefiles/tae.json — attack event active windows (type 1 only; level 2 passed for c2540, docs/tae-verify.md)
  param   data/gamefiles/combat.json — judge id → AtkParam PhysicalAttackPower (raw, before the player's defense)
  lua     data/gamefiles/ai/HusiFight_Sword254000Battle.lua + common_battle_func / common_func(2) — which act at which
          distance and with what odds, which animations each act chains, the after-attack spacing odds
  note    measured earlier and written in the repo (souls/duel.py comments)
  ASSUME  not in any file and not measured — a guess to make the slice run; replace by runtime numbers (tae_verify probe)

Left out on purpose (not verified or not in this slice): type 2 bullets (3008 firebomb, act 5 has weight 0 anyway),
type 5 common behaviors (steps 701–703 are modelled as movement only), the Interupt reactions (step / guard when the
player attacks or is hit), the player attacking, guard stamina, poise, root motion other than the lunge assumption.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
DT = 1 / 30                                   # tae: every c2540 window is on a 30 fps frame boundary
MODEL, NPC = "c2540", "254010"

SOURCES = {
    "windows": "tae", "damage": "param", "act odds / chains / spacing odds": "lua",
    "WALK 1.5 m/s, DASH 3.5 m/s": "ASSUME",
    "LUNGE 3.5 m/s during 3005-3007 until the window ends": "note (duel.py: lunge 3005 3-4.5 m/s)",
    "REACH = the AI's own attack distance for that animation (lua Att30xx_Dist_max), lunges 2.0 m after moving": "ASSUME",
    "anim length = last window end + 0.5 s; combo link = next anim at window end + 0.25 s": "ASSUME",
    "hit rule: once per active window (`window`) or once per AttackIndex p[1] (`index`)": "ASSUME — records: one 3010 took 192 = ~2 × 98; window gives 6 hits, index 3",
    "guard blocks all physical damage": "ASSUME",
    "after-attack Leave / Sideway / step: 2.5 m / 3 s / 1.5 m": "lua (leave dist) + ASSUME (speeds, step length)",
}
WALK, DASH, LUNGE = 1.5, 3.5, 3.5
RECOVERY, COMBO_LINK = 0.5, 0.25
LUNGES = {3005: 2.0, 3006: 2.0, 3007: 2.0}
# lua HusiFight_Sword254000Battle.lua locals (Att30xx_Dist_max) as reach per animation; combo follow-ups take the opener's
REACH = {3000: 1.6, 3001: 1.6, 3002: 1.6, 3003: 2.2, 3004: 2.2, 3009: 2.2, 3010: 2.0, **LUNGES}

# lua Activate: distance bands → act weights (actPerArr). eventNo == 1 → act 8 (wait) is an event request, left out.
BANDS = [(8.0, {1: 5, 2: 35, 3: 20, 5: 0, 7: 40}), (4.0, {1: 10, 2: 50, 3: 25, 5: 0, 7: 15}),
         (2.5, {1: 30, 2: 50, 3: 15, 5: 0, 7: 5}), (0.0, {1: 20, 2: 50, 3: 30, 5: 0, 7: 0})]
AFTER = {"guard": 100, "no_act": 75, "back_and_side": 9, "back": 8, "bit_wait": 0, "backstep": 4, "sidestep": 4}


def load_windows(tae_path: Path = ROOT / "data/gamefiles/tae.json", combat_path: Path = ROOT / "data/gamefiles/combat.json") -> dict:
    """{anim: [(active_start, active_end, damage, attack_index)]} — type 1 windows of c2540 with 254010's AtkParam power."""
    anims = json.loads(tae_path.read_text(encoding="utf-8"))["models"][MODEL]["animations"]
    beh = json.loads(combat_path.read_text(encoding="utf-8"))["foes"][NPC]["behaviors"]
    out = {}
    for aid in REACH:
        a = anims[str(aid)]
        if not a["events"] and a.get("ref") is not None:
            a = anims[str(a["ref"])]
        out[aid] = [(e["start"], e["end"], ((beh.get(str(e["p"][2])) or {}).get("attack") or {}).get("PhysicalAttackPower", 0),
                     e["p"][1]) for e in a["events"] if e["type"] == 1]
    return out


def act_chain(act: int, dist: float, rng: random.Random) -> list[tuple]:
    """One Activate: the subgoal list the lua act would push. Each item: ("approach", to_m, dash_from_m) ·
    ("attack", [anims…]) · after-attack spacing odds (int) as the last item."""
    if act == 1:                                   # defAct01 {Att3010_Dist_max 2.0, guard 0, 3010}
        return [("approach", 2.0, 4.0), ("attack", [3010]), 100]
    if act == 2:                                   # HumanCommon_Approach_and_ComboAtk {1.6, 50, 5, 15, …, GWS 80}
        f = rng.randint(1, 100)
        chain = [3000] if f <= 5 else [3000, 3001] if f <= 20 else [3000, 3001, 3002]
        return [("approach", 1.6, 3.6), ("attack", chain), 80]
    if act == 3:                                   # HusiFight_Sword254000_Act03
        f = rng.randint(1, 100)
        chain = [3003] if f <= 20 else [3003, 3004] if f <= 55 else [3003, 3004, 3009]
        return [("approach", 2.2, 4.2), ("attack", chain), 100]
    if act == 7:                                   # HusiFight_Sword254000_Act07
        f, f2 = rng.randint(1, 100), rng.randint(1, 100)
        if dist >= 8.4 and f <= 20:
            return [("approach", 10.0, 12.0), ("attack", [3007]), 100]
        if dist >= 5.7 and f2 <= 50:
            return [("approach", 6.8, 8.8), ("attack", [3006]), 100]
        return [("approach", 4.2, 6.2), ("attack", [3005]), 100]
    raise ValueError(f"act {act} not in this slice")


def pick_act(dist: float, rng: random.Random) -> int:
    """Common_Battle_Activate: weighted pick over actPerArr of the distance band."""
    weights = next(w for lo, w in BANDS if dist >= lo)
    acts = [a for a, w in weights.items() if w > 0]
    return rng.choices(acts, weights=[weights[a] for a in acts])[0]


def after_attack(rng: random.Random) -> list[tuple]:
    """GetWellSpace_Act_IncludeSidestep with Sword254000's odds {100, 75, 9, 8, 0, 4, 4}."""
    f = rng.randint(1, 100)
    o = AFTER
    if f <= o["no_act"]:
        return []
    if f <= o["no_act"] + o["back_and_side"]:
        return [("leave", 2.0), ("side", 3.0)]
    if f <= o["no_act"] + o["back_and_side"] + o["back"]:
        return [("leave", 3.0)]
    if f <= o["no_act"] + o["back_and_side"] + o["back"] + o["bit_wait"]:
        return [("wait", rng.uniform(0.5, 1.0))]
    return [("step", 1.5)]


@dataclass
class Foe:
    windows: dict
    rng: random.Random
    queue: list = field(default_factory=list)
    anim: int | None = None
    anim_t: float = 0.0
    chain: list = field(default_factory=list)
    hit_windows: set = field(default_factory=set)
    gws: int = 0
    acts: dict = field(default_factory=dict)
    timer: float = 0.0
    hit_rule: str = "window"

    def length(self, anim: int) -> float:
        return max(e for _s, e, *_ in self.windows[anim]) + RECOVERY

    def next_anim_at(self, anim: int) -> float:
        return max(e for _s, e, *_ in self.windows[anim]) + COMBO_LINK


def step(foe: Foe, dist: float, log) -> tuple[float, list]:
    """Advance the foe one frame. Returns (new distance, hits [(anim, damage)] whose window opens or is live)."""
    hits = []
    if foe.anim is not None:                                       # in an attack animation
        foe.anim_t += DT
        if foe.anim in LUNGES and foe.anim_t <= max(e for _s, e, *_ in foe.windows[foe.anim]) and dist > LUNGES[foe.anim]:
            dist = max(LUNGES[foe.anim], dist - LUNGE * DT)
        for k, (s, e, dmg, idx) in enumerate(foe.windows[foe.anim]):
            key = k if foe.hit_rule == "window" else idx
            if s <= foe.anim_t <= e and key not in foe.hit_windows and dist <= REACH[foe.anim]:
                foe.hit_windows.add(key)
                hits.append((foe.anim, dmg))
        if foe.chain and foe.anim_t >= foe.next_anim_at(foe.anim):
            start_anim(foe, foe.chain.pop(0), log)
        elif foe.anim_t >= foe.length(foe.anim):
            log(f"anim {foe.anim} end")
            foe.anim = None
            if foe.rng.randint(1, 100) <= foe.gws:
                foe.queue[:0] = after_attack(foe.rng)
        return dist, hits
    if not foe.queue:                                              # Activate
        act = pick_act(dist, foe.rng)
        foe.acts[act] = foe.acts.get(act, 0) + 1
        *goals, foe.gws = act_chain(act, dist, foe.rng)
        foe.queue = goals
        log(f"act {act} at {dist:.2f} m → {goals}")
    g = foe.queue[0]
    if g[0] == "approach":
        _, to, dash_from = g
        if dist <= to:
            foe.queue.pop(0)
        else:
            dist = max(to, dist - (DASH if dist >= dash_from else WALK) * DT)
    elif g[0] == "attack":
        foe.queue.pop(0)
        start_anim(foe, g[1][0], log)
        foe.chain = list(g[1][1:])
    elif g[0] in ("leave", "step"):
        foe.timer += DT
        dist += (WALK if g[0] == "leave" else 1.5 / 0.5) * DT
        if foe.timer >= (g[1] / WALK if g[0] == "leave" else 0.5):
            foe.queue.pop(0)
            foe.timer = 0.0
    elif g[0] in ("side", "wait"):
        foe.timer += DT
        if foe.timer >= g[1]:
            foe.queue.pop(0)
            foe.timer = 0.0
    return dist, hits


def start_anim(foe: Foe, anim: int, log) -> None:
    foe.anim, foe.anim_t, foe.hit_windows = anim, 0.0, set()
    log(f"anim {anim} start")


# ── player policies: (dist, foe) → (move m/s away (+) / toward (−), guarding) ──
def p_stand(dist, foe, mem):
    return 0.0, False


def p_guard_on_swing(dist, foe, mem, react=0.2):
    """Raise the guard `react` s after an attack animation starts (ASSUME reaction time), keep it until it ends."""
    return 0.0, foe.anim is not None and foe.anim_t >= react


def p_back_off(dist, foe, mem, keep=3.0):
    """Walk away (WALK) whenever the foe is closer than `keep` m."""
    return (WALK if dist < keep else 0.0), False


POLICIES = {"stand": p_stand, "guard_on_swing": p_guard_on_swing, "back_off": p_back_off}


def episode(windows: dict, policy, seed: int, secs: float = 30.0, start_dist: float = 6.0, hp: int = 742, log=None,
            hit_rule: str = "window") -> dict:
    """hp 742 = the bot character's max HP in the 10-12 runs (data/samples `vital`)."""
    rng = random.Random(seed)
    foe = Foe(windows=windows, rng=rng, hit_rule=hit_rule)
    dist, t, taken, hits = start_dist, 0.0, 0, []
    mem: dict = {}
    say = (lambda m: log(f"{t:6.2f}s {dist:5.2f}m  {m}")) if log else (lambda m: None)
    while t < secs and hp > 0:
        move, guard = policy(dist, foe, mem)
        mem["guarding"] = guard
        dist = max(0.3, dist + move * DT)
        dist, new = step(foe, dist, say)
        for anim, dmg in new:
            got = 0 if guard else dmg
            hp -= got
            taken += got
            hits.append({"t": round(t, 3), "anim": anim, "damage": got, "blocked": guard})
            say(f"hit {anim} {'(guard)' if guard else f'-{dmg}'} → hp {hp}")
        t += DT
    return {"seed": seed, "secs": round(t, 2), "taken": taken, "dead": hp <= 0, "hits": hits, "acts": foe.acts}


def summary(rows: list[dict]) -> dict:
    by_anim: dict[int, int] = {}
    acts: dict[int, int] = {}
    for r in rows:
        for h in r["hits"]:
            if not h["blocked"]:
                by_anim[h["anim"]] = by_anim.get(h["anim"], 0) + 1
        for a, n in r["acts"].items():
            acts[a] = acts.get(a, 0) + n
    n = len(rows)
    return {"episodes": n, "mean_taken": round(sum(r["taken"] for r in rows) / n, 1),
            "deaths": sum(r["dead"] for r in rows), "hits_by_anim": dict(sorted(by_anim.items())), "acts": dict(sorted(acts.items()))}


def recorded_hits(npc: int = int(NPC)) -> dict[int, int]:
    """Recorded `hit` events with this foe as the only one blamed → {anim: n} (data/samples)."""
    import glob
    out: dict[int, int] = {}
    for f in glob.glob(str(ROOT / "data/samples/*.jsonl")):
        if f.endswith((".track.jsonl", ".ctl.jsonl")):
            continue
        for line in open(f, encoding="utf-8"):
            if '"ev": "hit"' in line:
                b = json.loads(line).get("blame", [])
                if len(b) == 1 and b[0].get("npc") == npc:
                    out[b[0]["anim"]] = out.get(b[0]["anim"], 0) + 1
    return dict(sorted(out.items()))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--policy", choices=list(POLICIES))
    ap.add_argument("--episodes", type=int, default=200)
    ap.add_argument("--secs", type=float, default=30.0)
    ap.add_argument("--log", action="store_true", help="one episode, every event")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--hit-rule", choices=("window", "index"), default="window")
    a = ap.parse_args()
    windows = load_windows()
    print("출처:", json.dumps(SOURCES, ensure_ascii=False, indent=1))
    if a.log:
        r = episode(windows, POLICIES[a.policy or "stand"], seed=1, secs=a.secs, log=print, hit_rule=a.hit_rule)
        print({k: v for k, v in r.items() if k != "hits"})
        return
    if a.compare:
        s = summary([episode(windows, p_stand, seed=i, secs=a.secs, hit_rule=a.hit_rule) for i in range(a.episodes)])
        rec = recorded_hits()
        tot_s, tot_r = sum(s["hits_by_anim"].values()), sum(rec.values())
        print("anim  sim(stand) share | recorded 254010 share")
        for anim in sorted(set(s["hits_by_anim"]) | set(rec)):
            print(f"{anim:5} {s['hits_by_anim'].get(anim, 0) / tot_s:10.2f} | {rec.get(anim, 0):4} {rec.get(anim, 0) / tot_r:5.2f}")
        print(f"(sim {tot_s} hits / recorded {tot_r} — recorded hits come from bot fights, not a foe hitting a still target)")
        return
    for name in ([a.policy] if a.policy else POLICIES):
        s = summary([episode(windows, POLICIES[name], seed=i, secs=a.secs, hit_rule=a.hit_rule) for i in range(a.episodes)])
        print(name, json.dumps(s, ensure_ascii=False))


if __name__ == "__main__":
    main()
