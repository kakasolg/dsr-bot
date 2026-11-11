"""MoKa demo 2026-10-19 (new-route-20261019): read-only analysis of the observe recording against existing data.
Nothing here changes rules, thresholds or the B-22 predictor — it only reads.

  python experiments/demo_route_20261019.py [data/observe/20261019_201734.jsonl] [--out FILE]

Sections: record check · foe roster (params / TAE coverage / foes.py entry) · attack runs (10 Hz, TAE window from the
first seen sample) · player HP drops · kills · predictor applicability (dsas_hitbox_predict2.predict contract).
"""
from __future__ import annotations

import collections
import io
import json
import math
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tae_verify as V  # noqa: E402
from souls import foes as FOES  # noqa: E402

REC = ROOT / "data" / "observe" / "20261019_201734.jsonl"
ROUTE = ROOT / "data" / "routes" / "new-route-20261019.json"
BTN = {0x100: "LB", 0x200: "RB", 0x1000: "A", 0x2000: "B", 0x4000: "X", 0x8000: "Y", 0x80: "RS"}
# 플레이어 애니 — 기존 코드·문서에서 뜻이 확인된 것만 (근거: souls/duel.py:448, souls/weapons.py:107, patrol.py:56, guard_anim_test)
P_ANIM = {253000: "약공(클레이모어)", 253001: "약공 2타", 20140: "방패에 막음(클레이모어)", 7585: "에스트", 7586: "에스트",
          7587: "에스트", 2002: "피격 경직", 2052: "피격 경직", -1: "기본"}
P_ANIM_GUESS = {485102: "LT 직후에만 나옴 → 패리 모션 추정 (코드·문서에 없음)"}
ATTACK = range(3000, 3500)
SLACK = 0.10      # 10 Hz: an anim change is seen up to one sample (~0.1 s) late


def load(path: Path):
    L = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    L.sort(key=lambda r: r["ms"])
    return L


def pad_state(P, t):
    """Last pad line at or before t (s) → (buttons held, lt, rt)."""
    last = None
    for r in P:
        if r["ms"] / 1000 > t:
            break
        last = r
    return (last["btn"], last["lt"], last["rt"]) if last else (0, 0, 0)


def pad_edges(P):
    ev, prev = [], {"btn": 0, "lt": 0, "rt": 0}
    for r in P:
        t = r["ms"] / 1000
        nb = r["btn"] & ~prev["btn"]
        for k, n in BTN.items():
            if nb & k:
                ev.append((t, n))
        if r["lt"] > 100 >= prev["lt"]:
            ev.append((t, "LT"))
        if r["rt"] > 100 >= prev["rt"]:
            ev.append((t, "RT"))
        prev = r
    return ev


def main():
    argv = sys.argv[1:]
    args = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] != "--out")]
    path = Path(args[0]) if args else REC
    out = io.StringIO()
    pr = lambda *a: print(*a, file=out)  # noqa: E731
    L = load(path)
    W = [r for r in L if r["k"] == "w"]
    P = [r for r in L if r["k"] == "pad"]
    MK = [r for r in L if r["k"] == "mk"]
    tae, combat = V.load(V.TAE), V.load(V.COMBAT)
    models = V.npc_models(combat)

    # ── 1. record check ──
    dt = [b["ms"] - a["ms"] for a, b in zip(W, W[1:])]
    pr(f"# record {path.name}")
    pr(f"w {len(W)} lines, {W[0]['ms'] / 1000:.1f}–{W[-1]['ms'] / 1000:.1f} s; interval median {st.median(dt):.1f} ms, max {max(dt):.1f} ms, "
       f"gaps >150 ms {sum(d > 150 for d in dt)}; read_ms median {st.median(r['read_ms'] for r in W):.2f} max {max(r['read_ms'] for r in W):.2f}")
    pr(f"e_fail total {sum(r['e_fail'] for r in W)}; epochs {sorted({r['epoch'] for r in W})}; player None fields "
       f"{dict(collections.Counter(k for r in W for k, v in r['p'].items() if v is None))}")
    pr(f"pad {len(P)} lines (on change, 120 Hz poll); markers {[(m['n'], round(m['ms'] / 1000, 1)) for m in MK]}; "
       f"sys {dict(collections.Counter(r['ev'] for r in L if r['k'] == 'sys'))}")
    pr("fields NOT in this format: anim time (ChrIns anim queue), hitbox state +0x2E0, map id, stamina of foes, video")
    for m in MK:
        w = min(W, key=lambda r: abs(r["ms"] - m["ms"]))
        pr(f"  marker {m['n']} at {m['ms'] / 1000:.1f} s, player {w['p']['pos']}")

    # ── 2. foe roster ──
    F = collections.defaultdict(list)
    for r in W:
        for e in r["e"]:
            if e["npc"] == 0:
                continue
            F[e["id"]].append((r["ms"] / 1000, e))
    pr("\n# foes in the record (radius 30 m)")
    engaged = []
    for fid, xs in sorted(F.items(), key=lambda kv: kv[1][0][0]):
        e0 = xs[0][1]
        dmin = min(xs, key=lambda x: x[1]["d"])
        anims = collections.Counter(x[1]["anim"] for x in xs)
        acts = sorted(a for a in anims if a != -1)
        m = models.get(e0["npc"])
        foe = FOES.BY_NPC.get(e0["npc"])
        hp0, hp1 = xs[0][1]["hp_raw"], xs[-1][1]["hp_raw"]
        fought = any(a in ATTACK for a in acts) or hp1 != hp0
        tag = "ENGAGED" if fought else ""
        if fought:
            engaged.append(fid)
        pr(f"{fid} npc {e0['npc']} {m} team {e0['team_bot']} seen {xs[0][0]:.1f}–{xs[-1][0]:.1f} s · dmin {dmin[1]['d']:.1f} m @ {dmin[0]:.1f} s "
           f"(dy {dmin[1]['dy']:+.1f}) · hp {hp0}→{hp1}/{e0['max_hp_raw']} · anims {acts or '[-1 only]'} · foes.py {foe.name if foe else '—'} {tag}")

    # ── 3. attack runs ──
    pr("\n# attack runs of engaged foes (anim 3000–3499; start = first 10 Hz sample, true start up to ~0.1 s earlier)")
    pr("foe npc anim | start | TAE type-1 window (abs, s) | judge→AtkParam phys radius | d at start → min d in window | "
       "player in window: anims · held · new presses | HP drop in window(+0.2 s)")
    hp_series = [(r["ms"] / 1000, r["p"]["hp_raw"], r["p"]["anim"]) for r in W]
    edges = pad_edges(P)
    runs = []
    for fid in engaged:
        xs = F[fid]
        prev = None
        for i, (t, e) in enumerate(xs):
            if e["anim"] != prev and e["anim"] in ATTACK:
                j = i
                while j + 1 < len(xs) and xs[j + 1][1]["anim"] == e["anim"]:
                    j += 1
                runs.append((t, xs[j][0], fid, e, [x for x in xs[i:j + 1]]))
            prev = e["anim"]
    runs.sort(key=lambda r: r[0])
    hp_drops = [(b[0], a[1] - b[1]) for a, b in zip(hp_series, hp_series[1:]) if b[1] < a[1]]
    attributed = {}
    for t0, t1, fid, e, seg in runs:
        npc, anim = e["npc"], e["anim"]
        m = models.get(npc)
        win = V.windows(tae["models"][m]["animations"], anim, (1,)) if m in tae["models"] else []
        beh = combat["foes"][str(npc)]["behaviors"]
        parts = []
        for w in win:
            j = str(w["p"][2])
            a = (beh.get(j) or {}).get("attack") or {}
            parts.append(f"{w['start']:.3f}–{w['end']:.3f} → [{t0 - SLACK + w['start']:.2f}, {t0 + w['end']:.2f}] judge {j}→{a.get('atk_id')} "
                         f"{a.get('PhysicalAttackPower')} r{a.get('radii')}")
        lo = t0 - SLACK + (min(w["start"] for w in win) if win else 0)
        hi = t0 + (max(w["end"] for w in win) if win else (t1 - t0))
        dws = [x[1]["d"] for x in seg if lo <= x[0] <= hi + SLACK] or [seg[-1][1]["d"]]
        pan = sorted({a for (t, h, a) in hp_series if lo - SLACK <= t <= hi + SLACK})
        held = sorted({BTN[k] for (t, h, a) in hp_series if lo <= t <= hi for k in BTN if pad_state(P, t)[0] & k})
        lt_held = any(pad_state(P, t)[1] > 100 for (t, h, a) in hp_series if lo <= t <= hi)
        new = [f"{n}@{t - t0:+.2f}" for t, n in edges if t0 - 0.6 <= t <= hi]
        drop = [(round(t, 1), d) for t, d in hp_drops if lo <= t <= hi + 0.2]
        for t, d in drop:
            attributed.setdefault(t, []).append(f"{npc}/{anim}")
        res = ("HP −" + "/".join(str(d) for _, d in drop)) if drop else (
            "guard bounce 20140" if 20140 in pan else "parry anim 485102" if 485102 in pan else "no HP loss")
        pr(f"{fid[2:10]} {npc} {anim} | {t0:6.1f} | {'; '.join(parts) or 'no type-1 window'} | d {seg[0][1]['d']:.2f} → {min(dws):.2f} | "
           f"{[P_ANIM.get(a, a) for a in pan]} · held {held + (['LT'] if lt_held else [])} · {new} | {res}")

    pr("\n# player HP changes and the attack runs whose window (+0.2 s) holds them")
    for (t, d) in hp_drops:
        w = min(W, key=lambda r: abs(r["ms"] / 1000 - t))
        near = sorted(((e["d"], e["npc"], e["anim"]) for e in w["e"] if e["npc"] and e["d"] < 6), key=lambda x: x[0])
        pr(f"{t:6.1f} s −{d:4} at {w['p']['pos']} anim {w['p']['anim']} | windows: {attributed.get(round(t, 1), '—')} | within 6 m: "
           + ", ".join(f"{n}/{a} {dd:.1f} m" for dd, n, a in near))
    ups = [(b[0], b[1] - a[1], b[2]) for a, b in zip(hp_series, hp_series[1:]) if b[1] > a[1]]
    pr("HP gains: " + ", ".join(f"{t:.1f} s +{d} (anim {a})" for t, d, a in ups))

    pr("\n# kills (foe hp → 0) and the player's last inputs / anims before it")
    for fid in engaged:
        xs = F[fid]
        k = next((i for i, (t, e) in enumerate(xs) if e["hp_raw"] == 0), None)
        if k is None:
            continue
        tk = xs[k][0]
        hist = []
        for i in range(max(0, k - 30), k + 1):
            if i == 0 or xs[i][1]["hp_raw"] != xs[i - 1][1]["hp_raw"] or xs[i][1]["anim"] != xs[i - 1][1]["anim"]:
                hist.append(f"{xs[i][0]:.1f}:{xs[i][1]['anim']}/{xs[i][1]['hp_raw']}")
        pin = [f"{n}@{t:.1f}" for t, n in edges if tk - 3 <= t <= tk]
        pan = [f"{t:.1f}:{a}" for (t, h, a), (_, _, pa) in zip(hp_series[1:], hp_series) if tk - 3 <= t <= tk and a != pa]
        pr(f"{fid[2:10]} {xs[k][1]['npc']} dead at {tk:.1f} s | foe anim/hp: {' '.join(hist)} | pad {pin} | player anims {pan}")

    pr("\n# LT presses (with a shield: parry) → what followed within 1.2 s")
    for t, n in edges:
        if n != "LT":
            continue
        seq = [(r["ms"] / 1000, r) for r in W if t <= r["ms"] / 1000 <= t + 1.2]
        pa = sorted({r["p"]["anim"] for _, r in seq})
        dmg = sum(d for tt, d in hp_drops if t <= tt <= t + 1.2)
        fa = sorted({(e["npc"], e["anim"]) for _, r in seq for e in r["e"] if e["id"] in engaged and e["d"] < 3})
        parried = any(a == 2100 for _, a in fa)
        pr(f"LT {t:6.1f} | player {pa} | foes <3 m {fa} | HP −{dmg} | {'foe 2100 follows (parried?)' if parried else ''}")

    # ── 4. predictor applicability ──
    import dsas_hitbox_predict2 as P2  # noqa: E402
    pr(f"\n# predictor (experiments/dsas_hitbox_predict2.predict): NPC_OK {P2.NPC_OK}, ANIM_OK {P2.ANIM_OK}, τ {P2.TAU_OK}")
    reasons = collections.Counter()
    for t0, t1, fid, e, seg in runs:
        r = []
        if e["npc"] not in P2.NPC_OK:
            r.append("npc")
        if e["anim"] != P2.ANIM_OK:
            r.append("anim")
        r.append("no anim time (10 Hz anim id only)")
        reasons[" + ".join(r)] += 1
    pr(f"attack runs {len(runs)} (distinct foes {len({x[2] for x in runs})}); applicable 0; reasons: {dict(reasons)}")

    # ── 5. route ──
    rt = json.loads(ROUTE.read_text(encoding="utf-8"))
    pts = rt["points"]
    pr(f"\n# route {ROUTE.name}: {len(pts)} points, {sum(math.hypot(b[0] - a[0], b[2] - a[2]) for a, b in zip(pts, pts[1:])):.1f} m, "
       f"bonfires {rt.get('bonfires')}")
    pr("player track every 5 s: " + " ".join(f"{r['ms'] / 1000:.0f}:({r['p']['pos'][0]:.0f},{r['p']['pos'][1]:.1f},{r['p']['pos'][2]:.0f})"
                                             for r in W[::50]))
    text = out.getvalue()
    print(text)
    if "--out" in sys.argv:
        Path(sys.argv[sys.argv.index("--out") + 1]).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
