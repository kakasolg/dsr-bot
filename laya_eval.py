"""Offline evaluation of Laya tactic suggestions against the rules (LAYA.md 5). No game.

  python laya_eval.py cases golden                    duel_golden situations → data/laya/cases_golden.jsonl (bot venv)
  python laya_eval.py cases logs                      fight status lines of data/samples/*.txt → data/laya/cases_logs.jsonl
  <laya venv> python laya_eval.py score data/laya/cases_golden.jsonl [--backend laya|fake:guard] [--device cuda] [--limit N]
                                                      → data/laya/results_<cases>_<backend>.jsonl
  python laya_eval.py report RESULTS.jsonl [more …] [--min-conf 0.5] [--split test]
                                                      also reads shadow runs (data/runs/*.laya.jsonl)

Split: whole groups go to dev or test (golden: foe·anim·distance; logs and shadow runs: one run = one group), so near-
identical frames of one scene never sit on both sides. Identical (state, candidates, rule tactic) rows are kept once.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import laya_shadow as LS

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "laya"
DEV_SHARE = 3                       # of 10 hash buckets


def split_of(group: str) -> str:
    return "dev" if int(hashlib.md5(group.encode("utf-8")).hexdigest(), 16) % 10 < DEV_SHARE else "test"


def _write(path: Path, rows) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def _read(path) -> list:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


# ── cases ──

def cases_golden(limit=None) -> list:
    """Every tick of every golden situation where a rule acted, with the exact features the shadow would send."""
    sys.path.insert(0, str(ROOT / "tests"))
    import itertools
    import duel_golden_test as G
    rows = []
    sits = itertools.chain(G.situations(), G.situations_terrain(), G.situations_axe())
    for i, sc in enumerate(sits):
        if limit and i >= limit:
            break
        reqs = []
        G.run(sc, advisor=LS.Advisor(reqs.append, min_interval=0.0, source="golden",
                                     group=f"{sc.get('weapon', 'sword')}|{sc['foe']}|{sc['anim']}|{sc['h']}"))
        for r in reqs:
            r["situation"] = sc
            rows.append(r)
    return rows


STATUS = re.compile(r"\]\s+\[\s*([\d.]+)s\] 거리 ([\d.]+) 높이 ([+-]?[\d.]+) 그놈 애니 (-?\d+|None) HP (-?\d+) \| "
                    r"나 HP (-?\d+) SP (-?\d+) 애니 (-?\d+|None) 각 ([+-]?\d+)° \| (.*)$")
REACH = re.compile(r"무기: .*닿는 거리 ([\d.]+) m")
# Fight.note labels → tactic (souls/duel.py). None = not a tactic (turning, splitting, explaining why no backstab)
NOTE_TACTIC = [("막으며다가감", "guard"), ("막기", "guard"), ("반사", "guard"), ("늦은windup막기", "guard"), ("누움대기", "guard"),
               ("먼저치기", "attack"), ("마무리", "attack"), ("휘청반격", "attack"), ("휘청돌기", "attack"), ("빠른발차기", "attack"),
               ("백스텝공격", "attack"), ("뒤치기", "attack"), ("light", "attack"), ("heavy", "attack"), ("kick", "attack"),
               ("붙기:", "approach"), ("기다림", "hold_position"), ("안옴→", "hold_position"), ("SP회복", "hold_position"),
               ("끌어오기:", "reposition"), ("자리옮김:", "reposition"), ("가장자리방어", "reposition"),
               ("에스트", "heal"), ("백스텝", "heal"), ("뒤잡기:", "backstab"),
               ("뒤잡기안함", None), ("방향", None), ("돌기", None), ("떼어놓기:", None), ("피함대기", None)]


def note_tactic(name: str):
    for pre, t in NOTE_TACTIC:
        if name.startswith(pre):
            return t
    return None


def cases_logs(paths) -> list:
    """Fight status lines (one per ~1 s): distance, height, its anim and HP, my HP·SP·anim, angle, and what was done in that
    second. Max HP isn't printed — my max = highest HP seen in the run, its max = highest seen in that fight (approximate,
    marked). Unknown inputs (others nearby, Estus, arena) are left out of the state and permitted in the mask."""
    from souls import moves as M
    rows = []
    for path in paths:
        text = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        reach, basic = 1.6, any("기본 플레이: 방패 + 약공만" in l for l in text)
        shield = not any(re.search(r"스타일: (backstep|rush)", l) for l in text)
        evade = any("스타일: backstep" in l for l in text)
        parsed = []
        for line in text:
            m = REACH.search(line)
            if m:
                reach = float(m.group(1))
            m = STATUS.search(line)
            if m:
                parsed.append((reach, m.groups()))
        my_max = max((int(g[5]) for _, g in parsed), default=0)
        fight, foe_max, last_t = 0, 0, 1e9
        for reach, g in parsed:
            t, h, dy, ea, ehp, hp, sp, ma, ang, acts = g
            t, h, dy, ehp, hp, sp = float(t), float(h), float(dy), int(ehp), int(hp), int(sp)
            if t < last_t:
                fight, foe_max = fight + 1, 0                  # the fight clock restarted
            last_t, foe_max = t, max(foe_max, ehp)
            ea = -1 if ea == "None" else int(ea)
            done = Counter()
            for part in acts.split():
                name, _, n = part.rpartition("×")
                tac = note_tactic(name or part)
                if tac == "guard" and not shield:              # same as laya_shadow.policy_tactic
                    tac = "evade" if (name or part).startswith("반사") else "hold_position"
                if tac:
                    done[tac] += int(n) if n.isdigit() else 1
            if not done:
                continue
            policy = done.most_common(1)[0][0] if len(done) == 1 else "mixed"
            f = {"my_hp_pct": round(hp / my_max, 2) if my_max else None, "my_stamina_pct": None,
                 "target_state": LS.target_state(ea, None, M), "target_hp_pct": round(ehp / foe_max, 2) if foe_max else None,
                 "distance_m": h, "height_diff_m": dy, "weapon_reach_m": reach, "in_reach": h <= reach,
                 "facing_error_deg": abs(int(ang)),
                 "_shield": shield, "_evade": evade, "_room": (not basic) and h <= 3.5 and abs(dy) <= 1.0,
                 "estus_wanted": bool(my_max) and hp < my_max * 0.6, "approx": True}
            rows.append({"source": "logs", "group": Path(path).name, "kind": "tick", "fight": f"{Path(path).stem}#{fight}",
                         "rule": "+".join(sorted(done)), "policy": policy, "acts": dict(done),
                         "allowed": LS.allowed(f), "feat": f})
    return rows


# ── score ──

def _key(r) -> str:
    return json.dumps([LS.state_for(r["feat"]), r["allowed"], r["policy"]], sort_keys=True)


def score(cases_path, backend_spec, device=None, limit=None, min_conf=LS.MIN_CONF):
    rows, seen = [], set()
    for r in _read(cases_path):
        k = r["group"] + _key(r)
        if k in seen:
            continue
        seen.add(k)
        rows.append(r)
    if limit:
        rows = rows[:limit]
    t0 = time.perf_counter()
    backend = LS.make_backend(backend_spec, revision=LS.PINNED_REVISION, device=device) if backend_spec == "laya" \
        else LS.make_backend(backend_spec)
    load_ms = (time.perf_counter() - t0) * 1000
    out = OUT / f"results_{Path(cases_path).stem.removeprefix('cases_')}_{backend_spec.replace(':', '-')}.jsonl"
    print(f"{len(rows)} cases (deduplicated) · backend {backend.info} · load {load_ms:.0f} ms")
    res = []
    warm = rows[:3]
    for r in warm:                                          # warm-up (first CUDA calls) — not counted
        LS.answer({k: v for k, v in r.items() if k != "t_offer"}, backend, min_conf)
    for i, r in enumerate(rows):
        req = {k: v for k, v in r.items() if k not in ("t_offer",)}
        a = LS.answer(req, backend, min_conf)
        a["backend"] = backend.info
        res.append(a)
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(rows)}")
    _write(out, res)
    print(f"→ {out}")


# ── report ──

def pct(n, d) -> str:
    return f"{100 * n / d:5.1f} %" if d else "    –"


def quant(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def report(paths, min_conf=LS.MIN_CONF, split=None, examples=8) -> None:
    rows = []
    for p in paths:
        for r in _read(p):
            if r.get("type") == "answer":
                r["split"] = split_of(r.get("group") or Path(p).name)
                r["file"] = Path(p).name
                rows.append(r)
            elif r.get("type") in ("ready", "error"):
                print(f"[{Path(p).name}] {r.get('type')}: " + json.dumps({k: v for k, v in r.items() if k != 'type'}, ensure_ascii=False)[:300])
    if split:
        rows = [r for r in rows if r["split"] == split]
    by_src = defaultdict(list)
    for r in rows:
        by_src[(r.get("source", "?"), r["split"])].append(r)
    for (src, sp), rs in sorted(by_src.items()):
        _report_one(f"{src} / {sp}", rs, min_conf, examples)


def _report_one(title, rs, min_conf, examples) -> None:
    n = len(rs)
    print(f"\n══ {title}: {n} 사례, 묶음 {len({r.get('group') for r in rs})}개")
    # re-gate at min_conf (rows carry conf, status was set with the worker's own min_conf)
    for r in rs:
        if r.get("status") in ("ok", "abstain"):
            r["status"] = "ok" if (r.get("conf") or 0) >= min_conf else "abstain"
    st = Counter(r.get("status") for r in rs)
    print(f"  상태: " + " · ".join(f"{k} {v} ({pct(v, n).strip()})" for k, v in st.most_common()))
    invalid = [r for r in rs if r.get("status") == "invalid"]
    print(f"  금지·잘못된 제안 (허용 후보 밖 / 형식 오류): {len(invalid)} ({pct(len(invalid), n).strip()})")
    outside = [r for r in rs if r.get("policy") not in (None, "mixed") and r["policy"] not in r.get("allowed", [])]
    print(f"  규칙 행동이 마스크 밖: {len(outside)} ({pct(len(outside), n).strip()})  ← 0이 아니면 마스크가 규칙보다 좁음"
          + (" · 예: " + ", ".join(sorted({f"{r['rule']}→{r['policy']}" for r in outside})[:6]) if outside else ""))
    comp = [r for r in rs if r.get("policy") not in (None, "mixed")]
    mixed = sum(1 for r in rs if r.get("policy") == "mixed")
    if mixed:
        print(f"  라벨 섞임(1 s 안에 두 전술 이상 — 비교에서 뺌): {mixed}")
    labels_of = defaultdict(set)
    for r in comp:
        labels_of[json.dumps([LS.state_for(r["feat"]), r["allowed"]], sort_keys=True)].add(r["policy"])
    amb = sum(1 for r in comp if len(labels_of[json.dumps([LS.state_for(r["feat"]), r["allowed"]], sort_keys=True)]) > 1)
    print(f"  같은 상태·후보에 규칙 전술이 둘 이상: {amb}/{len(comp)} ({pct(amb, len(comp)).strip()})"
          f"  ← 상태에 안 보이는 것(반사 상태·끌어오기 여부 등)으로 규칙이 갈림 — 일치율의 상한을 깎음")
    ok = [r for r in comp if r.get("status") == "ok"]
    agree = [r for r in ok if r.get("choice") == r["policy"]]
    maj = Counter(r["policy"] for r in comp).most_common(1)
    maj_n = maj[0][1] if maj else 0
    print(f"  보류율 (conf < {min_conf}): {pct(sum(1 for r in comp if r.get('status') == 'abstain'), len(comp)).strip()}"
          f" · 답한 것 중 규칙과 일치: {len(agree)}/{len(ok)} ({pct(len(agree), len(ok)).strip()})"
          f" · 전체 대비: {pct(len(agree), len(comp)).strip()}")
    print(f"  기준선 — 늘 '{maj[0][0] if maj else '-'}'라고 답하면: {pct(maj_n, len(comp)).strip()}"
          f" · 허용 후보 중 무작위: {pct(sum(1 / len(r['allowed']) for r in comp if r.get('allowed')), len(comp)).strip()}")
    print("  임계값별 (범위 = 답한 비율, 일치 = 답한 것 중):")
    for th in (0.0, 0.3, 0.5, 0.7, 0.9):
        ans = [r for r in comp if r.get("conf") is not None and r.get("status") in ("ok", "abstain") and r["conf"] >= th]
        ag = sum(1 for r in ans if r.get("choice") == r["policy"])
        print(f"    ≥{th:.1f}: 범위 {pct(len(ans), len(comp))} · 일치 {pct(ag, len(ans))}")
    labels = sorted({r["policy"] for r in comp} | {r.get("choice") for r in ok if r.get("choice")})
    print("  혼동표 (행 = 규칙, 열 = Laya, 답한 것만):")
    print("    " + " " * 14 + "".join(f"{l[:9]:>10}" for l in labels) + "      합계  일치율")
    for pl in labels:
        line = [r for r in ok if r["policy"] == pl]
        if not line and not any(r["policy"] == pl for r in comp):
            continue
        cnt = Counter(r["choice"] for r in line)
        print(f"    {pl:<14}" + "".join(f"{cnt.get(l, 0):>10}" for l in labels)
              + f"{len(line):>10}  {pct(cnt.get(pl, 0), len(line))}   (사례 {sum(1 for r in comp if r['policy'] == pl)})")
    for name, key in (("봇 쪽 상태 준비", "prep_bot_ms"), ("워커 상태·질문 준비", "prep_ms"), ("추론", "infer_ms"),
                      ("큐+전송", "queue_ms"), ("합계 (요청→답)", "total_ms")):
        xs = [r.get(key) for r in rs if r.get(key) is not None]
        if xs:
            cross = " (두 시계 — 근사)" if key in ("queue_ms", "total_ms") and any(r.get("clock_cross") for r in rs) else ""
            print(f"  {name:<16} p50 {quant(xs, 0.5):8.2f} ms · p95 {quant(xs, 0.95):8.2f} ms · 최대 {max(xs):8.2f} ms · n {len(xs)}{cross}")
    trunc = sum(1 for r in rs if r.get("truncated"))
    if trunc:
        print(f"  상태가 잘림 (truncated): {trunc}")
    bad = sorted((r for r in ok if r.get("choice") != r["policy"]), key=lambda r: -(r.get("conf") or 0))
    if bad:
        print(f"  불일치 중 확신 높은 것 {min(examples, len(bad))}개:")
        for r in bad[:examples]:
            st = LS.state_for(r["feat"])
            short = {k: st[k] for k in ("target_kind", "target_state", "distance_m", "height_diff_m", "my_hp_pct", "my_stamina_pct",
                                        "others_within_4_5m", "other_swinging_near", "estus_wanted") if k in st}
            print(f"    규칙 {r['rule']}→{r['policy']} · Laya {r['choice']} ({r['conf']:.2f}) · 후보 {r['allowed']} · {short}")
    errs = Counter((r.get("why") or "")[:80] for r in rs if r.get("status") in ("invalid", "error"))
    for why, k in errs.most_common(3):
        print(f"  오류 {k}: {why}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cases")
    c.add_argument("source", choices=["golden", "logs"])
    c.add_argument("--limit", type=int, default=None)
    c.add_argument("--out", default=None)
    s = sub.add_parser("score")
    s.add_argument("cases")
    s.add_argument("--backend", default="laya")
    s.add_argument("--device", default=None)
    s.add_argument("--limit", type=int, default=None)
    r = sub.add_parser("report")
    r.add_argument("results", nargs="+")
    r.add_argument("--min-conf", type=float, default=LS.MIN_CONF)
    r.add_argument("--split", choices=["dev", "test"], default=None)
    a = ap.parse_args()
    if a.cmd == "cases":
        rows = cases_golden(a.limit) if a.source == "golden" else cases_logs(sorted((ROOT / "data" / "samples").glob("*.txt")))
        out = Path(a.out) if a.out else OUT / f"cases_{a.source}.jsonl"
        n = _write(out, rows)
        dup = len({r["group"] + _key(r) for r in rows})
        pol = Counter(r["policy"] for r in rows)
        print(f"{n} 사례 ({dup} 서로 다름, 묶음 {len({r['group'] for r in rows})}) → {out}")
        print("  규칙 전술: " + ", ".join(f"{k} {v}" for k, v in pol.most_common()))
    elif a.cmd == "score":
        score(a.cases, a.backend, a.device, a.limit)
    else:
        report(a.results, a.min_conf, a.split)


if __name__ == "__main__":
    main()
