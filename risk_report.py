"""판 위험 채점 — 최종 결과(cleared/dead)만 보면 실패가 숨는다 (사용자 2026-09-25: "실패가 숨겨진 거야", "리스크 쌓아 올리다 결국 죽잖아").

  python risk_report.py [--since 20260925_0900] [--cmd burg-loop]   판별 표 + 묶음(같은 명령·스타일·캐릭터) 요약
  python risk_report.py --hits 20260925_101734_burg-loop            그 판의 블랙박스 피격 묶음을 프레임 단위로

판 하나의 판정 (나쁜 쪽이 이긴다):
  사망  me_dead 이 한 번이라도
  위험  죽기 직전(HP < NEAR_DEATH) · 강종 · 끝까지(desperate) 재교전 · 최저 HP < 25 %
  주의  low_hp·timeout·stuck·stalemate·no_path · 최저 HP < 50 % · 10 초 안에 HP 40 % 넘게 잃음
  깨끗  그 밖

HP 곡선은 blackbox.py 의 vital 사건(0.5 s)에서 — 그 전 판은 최저 HP 를 모른다("?"), 강종 사건의 hp 로만 본다.
묶음 비교는 같은 char 사건(스탯·반지·무기)끼리만 — 캐릭터가 세지면 봇이 나아진 것처럼 보인다 (사용자 2026-09-25).
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RUNS = Path(__file__).resolve().parent / "data" / "runs"
NEAR_DEATH = 0.10
SWING_S = 10.0
SWING_FRAC = 0.40
WARN_RESULTS = ("low_hp", "timeout", "stuck", "stalemate", "no_path")
RANK = {"깨끗": 0, "주의": 1, "위험": 2, "사망": 3, "중단": 2}


def _rows(path: Path) -> list:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass                                   # 봇이 쓰다 죽은 마지막 줄
    return out


def char_key(rows: list) -> str:
    c = next((r for r in rows if r["ev"] == "char"), None)
    if not c:
        return "캐릭터 기록 없음"
    st, eq = c.get("stats", {}), c.get("equip", {})
    return (f"SL{st.get('SL')} V{st.get('VIT')} E{st.get('END')} S{st.get('STR')} "
            f"무기{eq.get('오른손1')} 반지{eq.get('반지1')},{eq.get('반지2')}")


def score(path: Path) -> dict:
    """판 하나 → 위험 지표. path 는 .jsonl (없으면 같은 이름 .log 만 본다)."""
    path = Path(path)
    rows = _rows(path) if path.exists() else []
    lg = path.with_suffix(".log")
    txt = lg.read_text(encoding="utf-8", errors="replace") if lg.exists() else ""
    res = next((r for r in rows if r["ev"] == "result"), None)
    style = next((r["style"] for r in rows if r["ev"] == "style"), "guard")
    duels = Counter(r["result"] for r in rows if r["ev"] == "duel")
    esc = [r for r in rows if r["ev"] == "escape"]
    hits = [r for r in rows if r["ev"] == "hit"]
    vit = [(r["t"], r["hp"], r["max"]) for r in rows if r["ev"] == "vital" and r.get("max")]

    min_frac, near, swing = None, 0, 0.0
    if vit:
        fr = [(t, hp / mx) for t, hp, mx in vit]
        min_frac = min(f for _, f in fr)           # 사망이면 0 %
        below = False
        for _, f in fr:                            # 아래로 들어간 횟수 (머무는 동안은 한 번)
            if 0 < f < NEAR_DEATH and not below:
                near += 1
            below = 0 < f < NEAR_DEATH
        j = 0
        for i in range(len(fr)):                   # 10 초 창 안 최대 손실 (최대 HP 대비)
            while fr[i][0] - fr[j][0] > SWING_S:
                j += 1
            peak = max(f for _, f in fr[j:i + 1])
            swing = max(swing, peak - fr[i][1])
    if not vit:                                    # vital 없던 판도 강종 순간 HP 로는 잡는다 (최대 HP 를 몰라 80 = 약 10 %)
        near += sum(1 for e in esc if e.get("hp") is not None and 0 < e["hp"] < 80)
    desperate = txt.count("(끝까지)")
    rtxt = str(res.get("result", "")) if res else ""
    # 낙사는 duel 밖에서 죽어 me_dead 가 안 남는다 (2026-09-25 151502: 경사로 낙사인데 "위험"으로 나옴) — ✝ 줄·HP 0 으로도 본다
    dead = (duels.get("me_dead", 0) > 0 or "dead" in rtxt or "died" in rtxt or "✝ 죽음" in txt
            or (min_frac is not None and min_frac <= 0))

    flags = []
    if dead:
        verdict = "사망"
    else:
        if near:
            flags.append(f"죽기직전×{near}")
        if esc:
            flags.append("강종×%d(%s)" % (len(esc), ",".join(sorted({e.get('kind', '?') for e in esc}))))
        if desperate:
            flags.append(f"끝까지×{desperate}")
        if min_frac is not None and min_frac < 0.25:
            flags.append(f"최저{min_frac:.0%}")
        verdict = "위험" if flags else "깨끗"
        warn = [f"{k}×{duels[k]}" for k in WARN_RESULTS if duels.get(k)]
        warn += [f"결과:{k}" for k in ("stuck", "no_estus", "timeout") if k in rtxt]
        if min_frac is not None and 0.25 <= min_frac < 0.5:
            warn.append(f"최저{min_frac:.0%}")
        if swing > SWING_FRAC:
            warn.append(f"10s에-{swing:.0%}")
        if warn and verdict == "깨끗":
            verdict = "주의"
        flags += warn
    if res is None and not dead:
        verdict = "중단" if RANK[verdict] < RANK["중단"] else verdict
    blamed = Counter(h["blame"][0]["npc"] for h in hits if h.get("blame"))
    return {"run": path.stem, "cmd": res.get("cmd") if res else path.stem.split("_", 2)[-1],
            "result": res.get("result") if res else None, "verdict": verdict, "flags": flags,
            "style": style, "char": char_key(rows), "min_frac": min_frac, "near_death": near, "swing": swing,
            "escapes": len(esc), "desperate": desperate, "duels": dict(duels),
            "hits": len(hits), "hit_lost": sum(h["lost"] for h in hits), "blamed": dict(blamed),
            "secs": max((r["t"] for r in rows), default=0.0)}


def one_line(r: dict) -> str:
    mf = "?" if r["min_frac"] is None else f"{r['min_frac']:.0%}"
    who = ", ".join(f"{n}×{c}" for n, c in Counter(r["blamed"]).most_common(3))
    return (f"══ 위험 판정: {r['verdict']}  (결과 {r['result']}, 최저 HP {mf}, 큰 피격 {r['hits']}번 -{r['hit_lost']}"
            f"{', 범인 ' + who if who else ''})  {' '.join(r['flags'])}")


def table(since: str, cmd: str | None) -> None:
    runs = []
    for js in sorted(RUNS.glob("2026*.jsonl")):
        if js.stem < since or js.stem.endswith(".hits") or "_" not in js.stem[9:]:
            continue
        r = score(js)
        if cmd and r["cmd"] != cmd:
            continue
        runs.append(r)
    if not runs:
        print("판 없음")
        return
    print(f"{'판':<34} {'판정':<4} {'결과':<14} {'최저':>5} {'피격':>9}  표시")
    for r in runs:
        mf = "?" if r["min_frac"] is None else f"{r['min_frac']:.0%}"
        print(f"{r['run']:<34} {r['verdict']:<4} {str(r['result'])[:14]:<14} {mf:>5} "
              f"{r['hits']:>3}/-{r['hit_lost']:<4}  {' '.join(r['flags'])}")
    G = defaultdict(list)
    for r in runs:
        G[(r["cmd"], r["style"], r["char"])].append(r)
    print("\n── 묶음 (같은 명령·스타일·캐릭터끼리만 비교) ──")
    for (c, st, ch), rs in G.items():
        v = Counter(r["verdict"] for r in rs)
        mfs = [r["min_frac"] for r in rs if r["min_frac"] is not None]
        blamed = Counter()
        for r in rs:
            blamed.update(r["blamed"])
        print(f"{c} / {st} / {ch}: {len(rs)}판  " + " ".join(f"{k} {v[k]}" for k in RANK if v.get(k)))
        print(f"    죽기직전 {sum(r['near_death'] for r in rs)}회, 강종 {sum(r['escapes'] for r in rs)}, "
              f"끝까지 {sum(r['desperate'] for r in rs)}, 최저 HP 중앙 "
              f"{'?' if not mfs else f'{statistics.median(mfs):.0%}'}"
              f"{'' if not blamed else ', 큰 피격 범인 ' + ', '.join(f'{n}×{k}' for n, k in blamed.most_common(3))}")


def hits(run: str) -> None:
    p = RUNS / f"{run}.hits.jsonl"
    if not p.exists():
        print(f"{p} 없음 (블랙박스가 켜진 판만 있다)")
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        h = json.loads(line)
        t0 = h["t0"]
        print(f"\n━━ 피격 #{h['n']}: HP {h['hp0']} → {h['lo']}/{h['max']}  추정 {h['blame']}")
        last = None
        for f in h["frames"]:
            if last is not None and f["t"] - last < 0.2 and f["hp"] == prev_hp:
                continue                             # 0.2 s 간격 + HP 바뀐 프레임은 전부
            last, prev_hp = f["t"], f["hp"]
            foes = "  ".join(f"{e['npc']}:{e['anim']}@{e['d']}m/{e['face']}°" for e in sorted(f["foes"], key=lambda e: e["d"])[:5])
            mark = "◀" if last >= t0 else " "
            print(f"  {f['t'] - t0:+6.2f}s {mark} HP {f['hp']:>4} 내애니 {f['anim']}  | {foes}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="20260925_0000")
    ap.add_argument("--cmd")
    ap.add_argument("--hits", metavar="RUN")
    a = ap.parse_args()
    if a.hits:
        return hits(a.hits)
    table(a.since, a.cmd)


if __name__ == "__main__":
    main()
