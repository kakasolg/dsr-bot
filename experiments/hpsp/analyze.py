"""HP / stamina analysis over recorded game runs (read-only). Outputs CSVs next to this file."""
import csv, glob, json, math, os, re, sys, collections

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(REPO, "data", "analysis", "hpsp_20261112")
FALL_ANIMS = (1500, 1550, 121500)
HOSTILE = (6, 7, 24, 25, 27, 33)
BOSS = 225000


def my_attack(a):
    return a is not None and 200000 <= a < 400000 and (a // 1000) % 10 in (3, 4)


def cat(a):
    """my action category from my anim (souls/moves.py, souls/reflex.py, patrol.py constants)."""
    if a is None or a == -1:
        return "idle"          # walking/standing, decided by movement later
    if 7585 <= a <= 7587:
        return "estus"
    if my_attack(a):
        return "attack"
    if 0 <= a < 1000000 and a % 10000 in range(140, 150):
        return "guard_block"   # shield struck (140 / 20140 / 100140..)
    if 0 <= a < 1000000 and a % 10000 == 160:
        return "guard_broken"  # 160: long stun while blocking (patrol.py: guard break, presumed)
    if a == 9600:
        return "guard_broken"
    if 690 <= a < 700 or 700 <= a < 800 or a == 900 or (a >= 10000 and a % 10000 in range(690, 800)):
        return "roll"
    if 2000 <= a < 2100:
        return "hit_stun"
    if 9900 <= a < 10000:
        return "downed"
    if a in FALL_ANIMS:
        return "fall"
    if 6000 <= a < 6200:
        return "death_anim"
    if a == 7540:
        return "throw"
    if 7000 <= a < 7100:
        return "ladder"
    return "other"


def cmd_of(name):
    m = re.match(r"^\d{8}_\d{6}_([^_]+)", name)
    if m:
        return m.group(1)
    m = re.match(r"^(.*?)-2026-", name)
    return m.group(1) if m else name


def group(cmd):
    return "taurus" if cmd == "taurus" else "general"


def horiz(a, b):
    return math.hypot(a["x"] - b["x"], a["z"] - b["z"])


def load(track):
    snaps, says = [], []
    for l in open(track, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(l)
        except Exception:
            continue
        if d.get("type") == "snap" and d.get("player"):
            snaps.append(d)
        elif d.get("type") == "say":
            says.append((d.get("rt", 0), d.get("line", "")))
    return snaps, says


def load_events(name):
    f = os.path.join(REPO, "data/samples", name + ".jsonl")
    ev = []
    if os.path.exists(f):
        for l in open(f, encoding="utf-8", errors="replace"):
            try:
                ev.append(json.loads(l))
            except Exception:
                pass
    return ev


def foes(s):
    p = s["player"]
    out = []
    for c in s.get("chars") or []:
        if c.get("ptr") == p.get("ptr") or (c.get("hp") or 0) <= 0:
            continue
        if c.get("team") not in HOSTILE and c.get("npc") != BOSS:
            continue
        if abs(c["y"] - p["y"]) > 3.0 and c.get("npc") != BOSS:
            continue
        if 9000 <= (c.get("anim") or 0) < 9100:
            continue                                     # asleep (reflex.awake)
        out.append((horiz(p, c), c))
    out.sort(key=lambda x: x[0])
    return out


def is_att(a):
    return a is not None and (3000 <= a < 3500 or 4000 <= a < 4200)


def act_label(prev, cur):
    c = cat(prev["player"].get("anim"))
    if c == "idle":
        dt = max(cur["rt"] - prev["rt"], 0.01)
        # movement over the interval before: use prev and the one before if given
        return "idle"
    return c


BOSS_RE = re.compile(r"보스 (\d+) 맞음 −(\d+): ([\d.]+) m.*나 (.+)$")


def main():
    tracks = sorted(glob.glob(os.path.join(REPO, "data/samples/*.track.jsonl")))
    tracks = [t for t in tracks if not os.path.basename(t).startswith("room-") and "_room" not in os.path.basename(t)]
    big, gb, est, low, deaths, runs = [], [], [], [], [], []
    for tr in tracks:
        name = os.path.basename(tr)[: -len(".track.jsonl")]
        cmd = cmd_of(name)
        g = group(cmd)
        snaps, says = load(tr)
        if len(snaps) < 3:
            continue
        evs = load_events(name)
        hit_ev = [e for e in evs if e.get("ev") == "hit"]
        est_ev = [e for e in evs if e.get("ev") == "estus"]
        boss_lines = []
        for rt, line in says:
            m = BOSS_RE.search(line)
            if m:
                boss_lines.append((rt, int(m.group(1)), int(m.group(2)), float(m.group(3)), m.group(4).strip()))
        runs.append((name, cmd, g, len(snaps), snaps[-1]["rt"]))

        # movement-refined idle label
        def label(i):
            a = snaps[i]["player"].get("anim")
            c = cat(a)
            if c != "idle":
                return c
            j = max(i - 1, 0)
            d = horiz(snaps[i]["player"], snaps[j]["player"]) if i > 0 else 0
            dt = snaps[i]["rt"] - snaps[j]["rt"] if i > 0 else 1
            return "walk" if dt > 0 and d / dt > 0.8 else "stand"

        labels = [label(i) for i in range(len(snaps))]

        def killer(i, lost, hp_after):
            rt = snaps[i]["rt"]
            src, who, fa, fd, me = "", "", "", "", ""
            for e in hit_ev:
                if e.get("hp") == hp_after and -1.5 <= e["t"] - rt <= 4.0:
                    bl = [b for b in e.get("blame") or [] if b.get("anim") is not None]
                    att = [b for b in bl if is_att(b['anim'])]
                    pick = min(att or bl, key=lambda b: b.get("d", 99)) if (att or bl) else None
                    if pick:
                        src, who, fa, fd = "hit_ev", pick.get("npc"), pick.get("anim"), pick.get("d")
                    else:
                        src = "hit_ev(no blame)"
                    break
            for (bt, ban, bdmg, bd, bme) in boss_lines:
                if -1.0 <= bt - rt <= 6.0 and abs(bdmg - lost) <= max(3, 0.05 * lost):
                    src, who, fa, fd, me = "boss_log", BOSS, ban, bd, bme
                    break
            if not who:
                # fallback: nearest awake foe in attack anim in prev/cur snap
                for s in (snaps[i - 1], snaps[i]):
                    for d, c in foes(s):
                        a = c.get("anim") or 0
                        if is_att(a) and d < 6:
                            src, who, fa, fd = "snap_attack_anim", c.get("npc"), a, round(d, 2)
                            break
                    if who:
                        break
            return src, who, fa, fd, me

        n = len(snaps)
        for i in range(1, n):
            p0, p1 = snaps[i - 1]["player"], snaps[i]["player"]
            if p0.get("ptr") != p1.get("ptr") or not p0.get("max_hp"):
                continue
            mx = p0["max_hp"]
            drop = p0["hp"] - p1["hp"]
            if p0["hp"] <= 0:
                continue
            fall = (p0["y"] - p1["y"] > 2.5) or cat(p0.get("anim")) == "fall" or cat(p1.get("anim")) == "fall"
            # ---- 1 big hits
            if drop >= 0.2 * mx or drop >= 100:
                prev_lab = labels[i - 1]
                # previous non-hitstun label within 1.5 s (I may already be in hit stun from an earlier hit)
                fz = foes(snaps[i - 1])
                src, who, fa, fd, me = killer(i, drop, p1["hp"])
                sp_seq = [snaps[k]["player"]["sp"] for k in range(i, min(i + 3, n))]
                big.append(dict(run=name, cmd=cmd, group=g, rt=snaps[i]["rt"], hp_before=p0["hp"], hp_after=p1["hp"], max_hp=mx,
                                drop=drop, drop_pct=round(100 * drop / mx, 1), ge20=int(drop >= 0.2 * mx),
                                sp_before=p0["sp"], max_sp=p0["max_sp"], sp_frac=round(p0["sp"] / p0["max_sp"], 2) if p0["max_sp"] else "",
                                sp_after=p1["sp"], my_anim_before=p0.get("anim"), act_before=prev_lab,
                                act_before2=labels[i - 2] if i >= 2 else "", my_anim_at=p1.get("anim"), act_at=labels[i],
                                fall=int(fall), killed=int(p1["hp"] <= 0),
                                foe_src=src, foe_npc=who, foe_anim=fa, foe_d=fd, bot_me_label=me,
                                nearest_foe=fz[0][1]["npc"] if fz else "", nearest_d=round(fz[0][0], 2) if fz else "",
                                sp_next=";".join(map(str, sp_seq))))
            # ---- 2 guard breaks / sp<=0 after hit while guarding
            a1 = p1.get("anim")
            c1 = cat(a1)
            if c1 == "guard_broken" and cat(p0.get("anim")) != "guard_broken":
                gb.append(dict(run=name, cmd=cmd, group=g, rt=snaps[i]["rt"], kind="anim_" + str(a1), hp_before=p0["hp"], hp_after=p1["hp"],
                               max_hp=mx, sp_before=p0["sp"], sp_after=p1["sp"], max_sp=p0["max_sp"], my_anim_before=p0.get("anim"),
                               act_before=labels[i - 1]))
            elif p1["sp"] <= 0 < p0["sp"] and (labels[i - 1] in ("guard_block",) or c1 == "guard_block"):
                gb.append(dict(run=name, cmd=cmd, group=g, rt=snaps[i]["rt"], kind="sp<=0_while_block", hp_before=p0["hp"], hp_after=p1["hp"],
                               max_hp=mx, sp_before=p0["sp"], sp_after=p1["sp"], max_sp=p0["max_sp"], my_anim_before=p0.get("anim"),
                               act_before=labels[i - 1]))
        # ---- 3 Estus drinks (track based)
        i = 1
        while i < n:
            p0, p1 = snaps[i - 1]["player"], snaps[i]["player"]
            if labels[i] == "estus" and labels[i - 1] != "estus":
                t0 = snaps[i]["rt"]
                hp0 = p0["hp"]
                mx = p0["max_hp"]
                j = i
                while j + 1 < n and labels[j + 1] == "estus":
                    j += 1
                t_end = snaps[j]["rt"]
                win = [k for k in range(i, n) if snaps[k]["rt"] <= t0 + 3.0]
                hps = [snaps[k]["player"]["hp"] for k in win]
                t_rise = next((snaps[k]["rt"] for k in win if snaps[k]["player"]["hp"] > hp0 + 5), None)
                t_drop = next((snaps[k]["rt"] for k in win if k >= 1 and snaps[k]["player"]["hp"] < snaps[k - 1]["player"]["hp"]), None)
                rose = t_rise is not None
                died5 = any(snaps[k]["player"]["hp"] <= 0 for k in range(i, n) if snaps[k]["rt"] <= t0 + 5.0)
                fz = foes(snaps[i - 1])
                near_d = round(fz[0][0], 2) if fz else ""
                near_npc = fz[0][1]["npc"] if fz else ""
                near_anim = fz[0][1].get("anim") if fz else ""
                foe_att = int(any(is_att(c.get("anim")) and d < 8 for d, c in fz)) if fz else 0
                if died5:
                    out = "died<5s"
                elif rose and t_drop is None:
                    out = "healed_clean"
                elif rose and t_drop >= t_rise:
                    out = "healed_then_hit"
                elif rose:
                    out = "hit_then_healed"
                elif t_drop is not None:
                    out = "hit_no_heal"
                else:
                    out = "no_rise_no_hit"
                hp3 = snaps[win[-1]]["player"]["hp"]
                # matching estus event (bot's own verdict)
                evm = None
                for e in est_ev:
                    if -0.5 <= e["t"] - t0 <= 5.0 and "hp" in e:
                        evm = e
                        break
                est.append(dict(run=name, cmd=cmd, group=g, rt=t0, hp_before=hp0, max_hp=mx, hp_pct=round(100 * hp0 / mx, 1),
                                sp=p0["sp"], max_sp=p0["max_sp"], act_before=labels[i - 1], anim_frames=j - i + 1,
                                est_dur_snap=round(t_end - t0 + 0.5, 2),
                                hp_max_3s=max(hps), hp_at_3s=hp3, t_rise=round(t_rise-t0,2) if rose else '', t_drop=round(t_drop-t0,2) if t_drop is not None else '', near_foe=near_npc, near_d=near_d, near_anim=near_anim, foe_attacking=foe_att,
                                outcome=out, ev_ok=evm.get("ok") if evm else "", ev_why=evm.get("why", "") if evm else "",
                                ev_hp=json.dumps(evm.get("hp")) if evm else ""))
                i = j + 1
                continue
            i += 1
        # ---- 4 low-HP episodes
        for thr in (0.3, 0.5):
            i = 1
            while i < n:
                p0, p1 = snaps[i - 1]["player"], snaps[i]["player"]
                mx = p1.get("max_hp") or 1
                if 0 < p1["hp"] < thr * mx and not (0 < p0["hp"] < thr * mx) and p0.get("ptr") == p1.get("ptr"):
                    t0 = snaps[i]["rt"]
                    nxt = [k for k in range(i, n) if snaps[k]["rt"] <= t0 + 3.0]
                    labs = [labels[k] for k in nxt]
                    fz0 = foes(snaps[i])
                    d0 = fz0[0][0] if fz0 else None
                    # first deliberate action in 3 s
                    first = "none"
                    for L in labs:
                        if L in ("attack", "estus", "guard_block", "roll"):
                            first = L
                            break
                    did = set(labs)
                    # retreat: nearest foe distance grew >= 1.5 m over 3 s without attack/estus
                    fz1 = foes(snaps[nxt[-1]])
                    d1 = fz1[0][0] if fz1 else None
                    retreat = int(d0 is not None and (d1 is None or d1 - d0 >= 1.5))
                    w10 = [k for k in range(i, n) if snaps[k]["rt"] <= t0 + 10.0]
                    died = any(snaps[k]["player"]["hp"] <= 0 for k in w10)
                    drank = any(labels[k] == "estus" for k in w10)
                    rose = max(snaps[k]["player"]["hp"] for k in w10) > p1["hp"] + 5
                    tdeath = next((round(snaps[k]["rt"] - t0, 1) for k in w10 if snaps[k]["player"]["hp"] <= 0), "")
                    out = "died" if died else ("drank_ok" if drank and rose else ("drank_no_rise" if drank else "survived"))
                    low.append(dict(run=name, cmd=cmd, group=g, thr=thr, rt=t0, hp=p1["hp"], max_hp=mx, hp_pct=round(100 * p1["hp"] / mx, 1),
                                    sp=p1["sp"], max_sp=p1["max_sp"], near_foe=fz0[0][1]["npc"] if fz0 else "",
                                    near_d=round(d0, 2) if d0 is not None else "", first_action=first,
                                    attacked_3s=int("attack" in did), drank_3s=int("estus" in did), blocked_3s=int("guard_block" in did),
                                    rolled_3s=int("roll" in did), retreat_3s=retreat, outcome_10s=out, t_death=tdeath,
                                    labels_3s="|".join(labs)))
                i += 1
        # ---- 5 deaths
        for i in range(1, n):
            p0, p1 = snaps[i - 1]["player"], snaps[i]["player"]
            if p1["hp"] <= 0 < p0["hp"] and p0.get("ptr") == p1.get("ptr"):
                t0 = snaps[i]["rt"]
                w = [k for k in range(n) if t0 - 10.0 <= snaps[k]["rt"] <= t0]
                traj = " ".join(f"{snaps[k]['rt'] - t0:+.1f}:{snaps[k]['player']['hp']}/{snaps[k]['player']['sp']}/{labels[k]}" for k in w)
                fall = any(snaps[k - 1]["player"]["y"] - snaps[k]["player"]["y"] > 2.5 or labels[k] == "fall" for k in w if k > 0)
                src, who, fa, fd, me = killer(i, p0["hp"], 0)
                acts = collections.Counter(labels[k] for k in w)
                deaths.append(dict(run=name, cmd=cmd, group=g, rt=t0, fall=int(fall), killer=who, killer_anim=fa, killer_d=fd, src=src,
                                   bot_me=me, hp_10s_ago=snaps[w[0]]["player"]["hp"], max_hp=p0["max_hp"],
                                   min_sp_10s=min(snaps[k]["player"]["sp"] for k in w),
                                   n_big_hits_10s=sum(1 for b in big if b["run"] == name and t0 - 10 <= b["rt"] <= t0),
                                   estus_10s=int(any(labels[k] == "estus" for k in w)),
                                   acts=";".join(f"{a}:{c}" for a, c in acts.most_common()), traj=traj))
    for fn, rows in (("big_hits", big), ("guard_breaks", gb), ("estus", est), ("low_hp", low), ("deaths", deaths)):
        if rows:
            with open(os.path.join(OUT, fn + ".csv"), "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
    with open(os.path.join(OUT, "runs.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["run", "cmd", "group", "snaps", "last_rt"])
        w.writerows(runs)
    print("runs", len(runs), "big", len(big), "gb", len(gb), "estus", len(est), "low", len(low), "deaths", len(deaths))


if __name__ == "__main__":
    main()
