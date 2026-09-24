"""
Jev 오프라인 재생 (1단계) — 게임을 켜지 않고, 이미 남은 DSR 싸움 기록으로 판단 모델이 쓸모 있는지 잰다.

  python jev_replay.py --dry            # 결정 순간 수만 센다 (호출 없음)
  python jev_replay.py --limit 60       # 앞 60 순간만 (비용 가늠)
  python jev_replay.py                  # 전부 (캐시 data/jev_replay.jsonl — 같은 순간은 다시 안 묻는다)
  python jev_replay.py --report         # 호출 없이 캐시로 표만

읽는 것: data/runs/<시각>_<명령>.log 의 duel 1 초 줄
  "[  46.6]       [29.2s] 거리 2.0 높이 +0.4 그놈 애니 3003 HP 75 | 나 HP 659 SP 75 애니 -1 각 +1° | 반사×25 막기×7"
  + 같은 이름 .jsonl 의 duel 사건 (npc·결과·받은 피해).  줄의 acts 는 **그 앞 1 초 동안** 봇이 한 일이다.

결정 순간 두 종류:
  A. 싸움 중 (줄마다):  상태 = 그 줄까지만 (뒤 줄은 절대 안 넘김 — 정보 누출 방지)
       hit5   noul   "5 초 안에 맞는다"                → 실제: 뒤 5 초 줄에서 내 HP 가 줄었나
       land3  noul   "3 초 안에 안 맞고 한 대 넣는다"   → 실제: 뒤 3 초 줄에서 그놈 HP 가 줄었나
       act    choice attack/block/back_off/drink/disengage → 규칙이 실제로 한 것(다음 줄 acts)과 비교
  B. 싸움 시작 (첫 줄):  prefight choice fight_here/pull_to_flat_ground/heal_first/skip
       + winclean noul "HP 20 % 안 잃고 이긴다"        → 실제: duel 결과·taken

판정선 (실행 전 고정, 2026-09-24):
  P1  hit5 AUROC ≥ 0.70 이고 규칙 기준선(공격 애니 & 2.5 m 안)보다 높다     ← 이게 안 되면 "위험 감지" 는 없음
  P2  land3 AUROC ≥ 0.65                                                  ← "틈 보기"
  P3  act: 규칙이 잘한 순간(줬고 안 맞음) 일치율 − 규칙이 못한 순간(맞았고 못 줌) 일치율 ≥ 0.15
       (못한 순간에 다른 답을 내야 개입할 가치가 있다. 둘이 같으면 규칙을 따라 말할 뿐)
  P4  prefight: 나쁜 싸움(me_dead/low_hp/lost 또는 taken ≥ 20 %) 경보율 ≥ 0.6, 깨끗한 싸움(killed & taken < 10 %) 오경보 ≤ 0.3
  P5  지연 p50 < 1000 ms
  P1·P4 둘 다 떨어지면 온라인(2단계)은 안 한다. P3 만 통과하면 "규칙이 막힌 순간의 2안" 자리만 검토.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # type: ignore  # noqa: E402
load_dotenv(ROOT.parent / ".env")
import jev  # noqa: E402
from souls import foes  # noqa: E402

RUNS = ROOT / "data" / "runs"
CACHE = ROOT / "data" / "jev_replay.jsonl"
MAX_HP = 659                     # 기록 당시 캐릭터 (escape 줄 "HP x/659")
MAX_SP = 91
GAP = 4.0                        # 호출 간격 s (게이트웨이 분당 한도)
LINE = re.compile(r"^\[\s*([\d.]+)\]\s+\[\s*([\d.]+)s\] 거리 ([\d.]+) 높이 ([+-][\d.]+) 그놈 애니 (-?\d+) HP (\d+) \| "
                  r"나 HP (\d+) SP (\d+) 애니 (-?\d+) 각 ([+-]\d+)° \| (.*)$")
ESCAPE = re.compile(r"^\[\s*([\d.]+)\]\s+⚠ 퀵 종료: ")

CONTEXT = ("Dark Souls Remastered. An autonomous knight (broadsword one-handed: two quick light attacks, reach 1.2 m; kite shield; "
           "Estus flask heals ~300 HP in 1.5 s and is unsafe with an enemy within 3 m) fights one target on the Undead Burg ramp. "
           "Enemy animation codes: -1 idle, 3000-3499 attacking (the swing lands within ~1.3 s of starting), 3500-3599 staggered "
           "(an opening: it cannot act), 9600 guard broken (opening), 9900+ knocked down. Own animation: -1 idle, 140 guarding a hit. "
           "Blocking costs stamina; below 25 stamina a block breaks and the knight is shoved (there are cliffs). "
           "Attacking while the enemy swings trades hits. The knight cannot attack or heal during its own animation.")
ACT = {
    "attack": "Swing now (light attack).",
    "block": "Hold the shield up facing the enemy and wait for an opening.",
    "back_off": "Step back to regain stamina / distance, shield up.",
    "drink": "Drink Estus now.",
    "disengage": "Leave this fight (quit-out / walk away) — it is not winnable right now.",
}
PRE = {
    "fight_here": "Engage on this spot as is.",
    "pull_to_flat_ground": "Back up to flat ground first and let the enemy come.",
    "heal_first": "Drink Estus before engaging.",
    "skip": "Do not fight this enemy now.",
}
# 봇이 실제로 한 일(acts) → 선택지
ACT_MAP = {"먼저치기": "attack", "마무리": "attack", "휘청반격": "attack",
           "막기": "block", "반사": "block", "막으며다가감": "block", "돌기": "block", "휘청돌기": "block", "누움대기": "block",
           "백스텝": "back_off", "SP회복": "back_off", "가장자리벗어남": "back_off", "끌어오기": "back_off", "자리옮김": "back_off",
           "에스트": "drink"}
PRIORITY = ["drink", "attack", "back_off", "block"]   # 한 줄에 여러 일이 섞이면 의미가 큰 것


def parse_run(log: Path) -> list[dict]:
    """한 실행 → duel 목록 [{npc, result, taken, secs, t0, t1, lines:[...], escapes:[t]}]."""
    js = log.with_suffix(".jsonl")
    if not js.exists():
        return []
    duels = [json.loads(l) for l in js.read_text(encoding="utf-8").splitlines() if l.strip()]
    duels = [d for d in duels if d.get("ev") == "duel"]
    lines, escapes = [], []
    for raw in log.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE.match(raw)
        if m:
            t, ft, dist, dy, ea, ehp, hp, sp, ma, ang, acts = m.groups()
            lines.append({"t": float(t), "ft": float(ft), "dist": float(dist), "dy": float(dy), "eanim": int(ea), "ehp": int(ehp),
                          "hp": int(hp), "sp": int(sp), "manim": int(ma), "angle": int(ang),
                          "acts": [a.split("×")[0].split(":")[0] for a in acts.split()]})
            continue
        e = ESCAPE.match(raw)
        if e:
            escapes.append(float(e.group(1)))
    out = []
    for d in duels:
        t1, t0 = d["t"], d["t"] - d["secs"]
        ls = [l for l in lines if t0 - 0.6 <= l["t"] <= t1 + 0.6 and l["ft"] <= d["secs"] + 0.6]
        if not ls:
            continue
        out.append({"run": log.stem, "npc": d["npc"], "result": d["result"], "taken": d["taken"], "dealt": d["dealt"], "secs": d["secs"],
                    "t0": t0, "t1": t1, "lines": ls, "escapes": [t for t in escapes if t1 - 1 <= t <= t1 + 1]})
    return out


def rule_action(next_line: dict | None, escaped: bool) -> str | None:
    if escaped:
        return "disengage"
    if not next_line:
        return None
    acts = {ACT_MAP[a] for a in next_line["acts"] if a in ACT_MAP}
    for p in PRIORITY:
        if p in acts:
            return p
    return None


def moments(duel: dict) -> list[dict]:
    """줄마다 결정 순간 + 실제 결과. 뒤 줄이 없으면 duel 결과로 채운다."""
    ls, out = duel["lines"], []
    foe = foes.of(duel["npc"])
    for i, l in enumerate(ls):
        fut5 = [x for x in ls[i + 1:] if x["t"] <= l["t"] + 5.0]
        fut3 = [x for x in ls[i + 1:] if x["t"] <= l["t"] + 3.0]
        ended = not ls[i + 1:] or (duel["t1"] - l["t"] <= 5.0)
        if fut5:
            hit5 = any(b["hp"] < a["hp"] for a, b in zip([l] + fut5, fut5))
        elif ended and duel["result"] in ("me_dead", "low_hp"):
            hit5 = True
        elif ended and duel["result"] == "killed":
            hit5 = False
        else:
            continue
        land3 = (any(x["ehp"] < l["ehp"] for x in fut3) or (not fut3 and ended and duel["result"] == "killed" and l["ehp"] > 0))
        escaped = any(l["t"] < t <= l["t"] + 2.0 for t in duel["escapes"])
        out.append({
            "id": f"{duel['run']}|{l['t']:.1f}|{i}",
            "first": i == 0,
            "state": {
                "context": CONTEXT,
                "enemy": {"type": foe.name, "kind": foe.kind, "hp": l["ehp"], "distance_m": l["dist"], "height_diff_m": l["dy"],
                          "animation": l["eanim"], "attack_ranged": foe.ranged, "guards_when_idle": foe.kick_when_idle},
                "knight": {"hp_pct": round(l["hp"] / MAX_HP, 2), "stamina_pct": round(min(1.0, l["sp"] / MAX_SP), 2),
                           "animation": l["manim"], "facing_offset_deg": l["angle"], "seconds_in_fight": l["ft"]},
                "last_second_actions": l["acts"],
            },
            "truth": {"hit5": hit5, "land3": land3, "rule_act": rule_action(ls[i + 1] if i + 1 < len(ls) else None, escaped),
                      "rule_hit5": (l["eanim"] in range(3000, 3500) and l["dist"] <= 2.5),
                      "duel_result": duel["result"], "duel_taken": duel["taken"], "npc": duel["npc"]},
        })
    return out


def ask_one(m: dict) -> dict:
    q = {
        "hit5": {"type": "noul", "instructions": "The knight will take damage within the next 5 seconds if it keeps doing what the rules do."},
        "land3": {"type": "noul", "instructions": "There is an opening right now: the knight can land a light attack within 3 seconds without being hit."},
        "act": {"type": "choice", "instructions": "What should the knight do right now?", "criteria": ACT},
    }
    if m["first"]:
        q["prefight"] = {"type": "choice", "instructions": "The fight is just starting. What should the knight do?", "criteria": PRE}
        q["winclean"] = {"type": "noul", "instructions": "The knight will kill this enemy without losing more than 20% of its HP."}
    # 게이트웨이 429 (4 스레드 → 489/527 거절) — 순차 + 간격 + 물러서기
    a, ms = None, 0
    for attempt in range(6):
        t0 = time.time()
        a = jev.ask(m["state"], q, tag="replay")
        ms = round((time.time() - t0) * 1000)
        if a:
            break
        time.sleep(2.0 * (attempt + 1))
    time.sleep(GAP)
    row = {"id": m["id"], "first": m["first"], "truth": m["truth"], "ms": ms, "t": time.time()}
    if not a:
        row["error"] = True
        return row
    row["hit5"] = a.get("hit5", {}).get("noul")
    row["land3"] = a.get("land3", {}).get("noul")
    act = a.get("act", {})
    row["act"], row["act_conf"] = act.get("choice"), act.get("confidence")
    if m["first"]:
        pf = a.get("prefight", {})
        row["prefight"], row["prefight_conf"] = pf.get("choice"), pf.get("confidence")
        row["winclean"] = a.get("winclean", {}).get("noul")
    return row


def auroc(pairs: list[tuple[float, bool]]) -> float | None:
    pos = [s for s, y in pairs if y]
    neg = [s for s, y in pairs if not y]
    if not pos or not neg:
        return None
    wins = sum((1.0 if p > n else 0.5 if p == n else 0.0) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def f2(x) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def report(rows: list[dict]) -> None:
    ok = [r for r in rows if not r.get("error")]
    print(f"순간 {len(rows)}  응답 {len(ok)}  오류 {len(rows) - len(ok)}")
    if not ok:
        return
    ms = sorted(r["ms"] for r in ok)
    p50, p90 = statistics.median(ms), ms[int(len(ms) * 0.9)]
    print(f"지연 p50 {p50:.0f} ms  p90 {p90:.0f} ms  → P5 {'통과' if p50 < 1000 else '탈락'}")

    a_j = auroc([(r["hit5"], r["truth"]["hit5"]) for r in ok if r["hit5"] is not None])
    a_r = auroc([(1.0 if r["truth"]["rule_hit5"] else 0.0, r["truth"]["hit5"]) for r in ok])
    base = statistics.mean(r["truth"]["hit5"] for r in ok)
    print(f"P1 hit5(5 초 안 피격, 실제 {base:.0%}): Jev AUROC {f2(a_j)}  규칙 기준선 {f2(a_r)}  "
          f"→ {'통과' if a_j is not None and a_j >= 0.70 and a_j > (a_r or 0) else '탈락'}")
    a_l = auroc([(r["land3"], r["truth"]["land3"]) for r in ok if r["land3"] is not None])
    print(f"P2 land3(3 초 안 한 대, 실제 {statistics.mean(r['truth']['land3'] for r in ok):.0%}): Jev AUROC {f2(a_l)}  "
          f"→ {'통과' if a_l is not None and a_l >= 0.65 else '탈락'}")

    with_rule = [r for r in ok if r["truth"]["rule_act"] and r["act"]]
    good = [r for r in with_rule if r["truth"]["land3"] and not r["truth"]["hit5"]]
    bad = [r for r in with_rule if r["truth"]["hit5"] and not r["truth"]["land3"]]
    ag = lambda xs: statistics.mean(r["act"] == r["truth"]["rule_act"] for r in xs) if xs else float("nan")
    dist = {k: sum(1 for r in ok if r["act"] == k) for k in ACT}
    rdist = {k: sum(1 for r in with_rule if r["truth"]["rule_act"] == k) for k in ACT}
    print(f"P3 act: Jev 분포 {dist}  규칙 분포 {rdist}")
    print(f"       규칙이 잘한 순간 {len(good)}건 일치 {ag(good):.0%} / 못한 순간 {len(bad)}건 일치 {ag(bad):.0%}  "
          f"차이 {ag(good) - ag(bad):+.2f} → {'통과' if good and bad and ag(good) - ag(bad) >= 0.15 else '탈락'}")
    confs = [r["act_conf"] for r in ok if r.get("act_conf") is not None]
    if confs:
        print(f"       act 신뢰도 중앙값 {statistics.median(confs):.2f}, ≥0.6 비율 {statistics.mean(c >= 0.6 for c in confs):.0%}")

    firsts = [r for r in ok if r["first"] and r.get("prefight")]
    if firsts:
        def badduel(r):
            t = r["truth"]
            return t["duel_result"] in ("me_dead", "low_hp", "lost") or t["duel_taken"] >= 0.2 * MAX_HP
        def clean(r):
            t = r["truth"]
            return t["duel_result"] == "killed" and t["duel_taken"] < 0.1 * MAX_HP
        warned = lambda r: r["prefight"] != "fight_here" or (r.get("winclean") or 1.0) < 0.5
        b, c = [r for r in firsts if badduel(r)], [r for r in firsts if clean(r)]
        wb = statistics.mean(warned(r) for r in b) if b else float("nan")
        wc = statistics.mean(warned(r) for r in c) if c else float("nan")
        pd = {k: sum(1 for r in firsts if r["prefight"] == k) for k in PRE}
        print(f"P4 prefight {len(firsts)}건 분포 {pd}: 나쁜 싸움 {len(b)}건 경보 {wb:.0%} / 깨끗한 싸움 {len(c)}건 오경보 {wc:.0%}  "
              f"→ {'통과' if b and c and wb >= 0.6 and wc <= 0.3 else '탈락'}")
        a_w = auroc([(1 - (r.get("winclean") or 0), badduel(r)) for r in firsts if r.get("winclean") is not None])
        if a_w is not None:
            print(f"       winclean 로 나쁜 싸움 가르기 AUROC {f2(a_w)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()

    runs = sorted(p for p in RUNS.glob("2026*.log"))
    duels = [d for p in runs for d in parse_run(p)]
    ms = [m for d in duels for m in moments(d)]
    print(f"실행 {len(runs)}  duel {len(duels)}  결정 순간 {len(ms)} (싸움 시작 {sum(m['first'] for m in ms)})  백엔드 {jev.describe()}")
    if args.dry:
        return
    cached: dict[str, dict] = {}
    if CACHE.exists():
        for l in CACHE.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                if not r.get("error"):
                    cached[r["id"]] = r
    todo = [m for m in ms if m["id"] not in cached]
    # 게이트웨이가 느리므로(분당 ~8) 싸움 시작 → 3 줄에 1 줄 → 나머지 순으로 묻는다: 도중에 --report 해도 표가 고르게 나온다
    todo.sort(key=lambda m: 0 if m["first"] else 1 if int(m["id"].rsplit("|", 1)[1]) % 3 == 0 else 2)
    if args.limit:
        todo = todo[:args.limit]
    if not args.report and todo:
        if not jev.available():
            print("Jev 사용 불가 — .env 키 / 로컬 서버 확인")
            return
        print(f"호출 {len(todo)}건 (캐시 {len(cached)})…", flush=True)
        with CACHE.open("a", encoding="utf-8") as f, ThreadPoolExecutor(args.workers) as ex:
            for i, row in enumerate(ex.map(ask_one, todo), 1):
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                if not row.get("error"):
                    cached[row["id"]] = row
                if i % 25 == 0:
                    print(f"  {i}/{len(todo)}", flush=True)
    rows = [cached[m["id"]] for m in ms if m["id"] in cached]
    report(rows)


if __name__ == "__main__":
    main()
