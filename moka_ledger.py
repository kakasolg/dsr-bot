"""MoKa instruction ledger: what MoKa said (docs/moka_ledger.jsonl) → in one run, did the situation come up, did the bot do
what MoKa said, and what happened. Nothing MoKa said is dropped silently: an instruction that isn't built, or has no
detector yet, is still listed every run.

[MoKa] 2026-11-08: "내가 말 한 것들이 뭔가 저장 되어 있고, 실제로 테스트 하는 상황에서 나오는지 않나오는지 그대로 했는데 문제가 되는지,
않되는지 등을 데이타를 쌓으면 언젠가 decision 할때 판정 기준과 데이타가 나오는데" · "몇 번 이야기 해도 조용히 씹혀 버리면 …
잊어먹은 건지 나도 판단이 않되."

  python moka_ledger.py [<run.log | run name>] [--json]     newest log in data/runs by default

Detectors read the run log only (lines the bot already writes). Counts are what the log shows — a detector can miss a
situation the log doesn't spell out; each detector says what it counts.

── 안 됐다 ≠ 지시가 틀렸다 ([MoKa] 11-08) ──────────────────────────────
 "않되도 않된게 아니라 다른 팩터가 영향을 줘서 않되는 경우가 다반사야. 심지어 아주 대단한 다크소울 고수도 … 이 모든 변수를 한번에
 고려 못해 실수 하게 하는게 다크 소울이야." → 경우마다 그때 조건 (계획된 적 수 · 내 HP · 기력 · 그놈 거리)을 같이 남김 (--cases),
 요약은 적 수별로 나눔. 결과가 나쁜 경우를 '지시 실패'로 묶지 않음.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "docs" / "moka_ledger.jsonl"
RUNS = ROOT / "data" / "runs"
STATUS = {"built": "만듦", "not_built": "안 만듦", "held": "보류", "noted": "기록만", "principle": "원칙"}

T_RE = re.compile(r"^\[\s*([0-9.]+)\]")
HIT_RE = re.compile(r"피해 (\d+), 내 피해 (\d+)")
BOX_RE = re.compile(r"블랙박스 #\d+: [0-9.]+ s 동안 -(\d+)")
ME_HP_RE = re.compile(r"나 HP (\d+)")
HP_OF_RE = re.compile(r"HP (\d+)/(\d+)")
FOE_HP_RE = re.compile(r"그놈 애니 \S+ HP (\d+)")
PLAN_RE = re.compile(r"전투 계획 (\d+)놈")


STATUS_RE = re.compile(r"거리 ([0-9.]+) .*나 HP (\d+) SP (\d+)")
CASES: list = []                                       # (ledger detector, t, ok, note, ctx) — filled by detectors, read by --cases


def ctx(lines, i) -> dict:
    """Conditions at line i: foes in the last fight plan, my newest HP, SP and foe distance from the last status line
    (SP and distance can be a second or two old)."""
    out = {"foes": None, "hp": None, "sp": None, "d": None}
    for x in reversed(lines[max(0, i - 60):i + 1]):
        if out["hp"] is None:                              # newest HP from any line ('HP 127/682' after a hit, or a status line)
            m = HP_OF_RE.search(x) or ME_HP_RE.search(x)
            if m:
                out["hp"] = int(m.group(1))
        if out["sp"] is None:
            m = STATUS_RE.search(x)
            if m:
                out.update(d=float(m.group(1)), sp=int(m.group(3)))
        if out["foes"] is None:
            m = PLAN_RE.search(x)
            if m:
                out["foes"] = int(m.group(1))
        if out["hp"] is not None and out["sp"] is not None and out["foes"] is not None:
            break
    return out


def _case(det, lines, i, ok, note="") -> None:
    CASES.append((det, _t(lines[i]), ok, note, ctx(lines, i)))


def _by_foes(det) -> str:
    """'1놈 따름 a/n · 2놈+ 따름 b/m' over this detector's cases."""
    parts = []
    for lab, f in (("1놈", lambda n: n == 1), ("2놈+", lambda n: n is not None and n >= 2), ("모름", lambda n: n is None)):
        cs = [c for c in CASES if c[0] == det and f(c[4]["foes"])]
        if cs:
            parts.append(f"{lab} {sum(1 for c in cs if c[2])}/{len(cs)}")
    return " · ".join(parts)


def load_ledger(path: Path = LEDGER) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _t(line: str) -> float | None:
    m = T_RE.match(line)
    return float(m.group(1)) if m else None


def _taken_after(lines, i, secs=5.0) -> int:
    """HP lost in the black-box lines within secs after line i."""
    t0 = _t(lines[i])
    out = 0
    for x in lines[i + 1:]:
        t = _t(x)
        if t is not None and t0 is not None and t - t0 > secs:
            break
        m = BOX_RE.search(x)
        if m:
            out += int(m.group(1))
    return out


def d_guard_counter(lines):
    """Shield hit (140) lines: light pressed → followed; '반격 안 함' → not (with why). Outcome = dealt / taken of the light."""
    n = k = dealt = taken = cut = 0
    why: dict = {}
    for i, x in enumerate(lines):
        if "방패에 맞음 (" not in x:
            continue
        n += 1
        if "→ light" in x:
            k += 1
            m = HIT_RE.search(x)
            if m:
                dealt += int(m.group(1))
                taken += int(m.group(2))
                cut += int(m.group(1)) == 0 and int(m.group(2)) > 0
                _case("guard_counter", lines, i, int(m.group(1)) > 0, f"피해 {m.group(1)} · 내 피해 {m.group(2)}")
        elif "반격 안 함" in x:
            _case("guard_counter", lines, i, False, "안 침: " + x.split("반격 안 함:", 1)[-1].strip())
            w = x.split("반격 안 함:", 1)[-1].strip()
            w = re.sub(r"\d+", "#", w)
            why[w] = why.get(w, 0) + 1
    out = f"약공 피해 합 {dealt}, 그동안 내 피해 {taken}, 치기 전에 맞아 끊김 {cut} · 맞힘/경우 적 수별 {_by_foes('guard_counter')}"
    if why:
        out += " · 안 친 이유 " + ", ".join(f"{w} ×{c}" for w, c in why.items())
    return n, k, out


def d_wall_bounce(lines):
    """'무기가 벽에 튕김' = came up; a '벽 튕긴 자리 — 통로 가운데 / 백스텝' after it = followed. Outcome = bounces again."""
    n = k = again = 0
    last_t = None
    for i, x in enumerate(lines):
        if "무기가 벽에 튕김" not in x:
            continue
        n += 1
        t = _t(x)
        if last_t is not None and t is not None and t - last_t < 15.0:
            again += 1
        last_t = t
        moved = any("벽 튕긴 자리 —" in y and ("가운데" in y or "백스텝" in y) for y in lines[i + 1:i + 12])
        k += moved
        _case("wall_bounce", lines, i, moved, "옮김" if moved else "안 옮김")
    return n, k, f"15 s 안에 또 튕김 {again} · 옮김/경우 적 수별 {_by_foes('wall_bounce')}"


def d_crowd_wait(lines):
    """'옆에 N명 —' (no knife, a crowd): waited = followed. Outcome = one came while waiting / nobody came → body run."""
    n = k = came = 0
    for x in lines:
        if "옆에 " in x and "명 —" in x:
            n += 1
            if "기다" in x:
                k += 1
                came += "기다리니 옴" in x
    return n, k, f"기다리니 옴 {came} · 안 와서 몸으로 {k - came}"


def d_low_hp_estus(lines):
    """Estus decisions while our HP is under 30 % of max (max = largest HP the log shows): drank = followed."""
    hp = mx = None
    n = k = 0
    refused: dict = {}
    for i, x in enumerate(lines):
        m = HP_OF_RE.search(x)
        if m:
            hp, mx = int(m.group(1)), max(mx or 0, int(m.group(2)))
        m = ME_HP_RE.search(x)
        if m:
            hp = int(m.group(1))
            mx = max(mx or 0, hp)
        m = re.search(r"'hp': \[(\d+), (\d+)\]", x)
        if "에스트" not in x or hp is None or not mx or hp >= 0.3 * mx:
            if m and "에스트" in x:
                hp = int(m.group(2))
            continue
        n += 1
        _case("low_hp_estus", lines, i, "'ok': True" in x, x.split("에스트", 1)[-1].strip()[:40])
        if "'ok': True" in x:
            k += 1
            hp = int(m.group(2)) if m else hp
        else:
            w = "근처에 적" if "근처에 적" in x else "끊김" if "끊김" in x else "미룸" if "미룸" in x else "기타"
            refused[w] = refused.get(w, 0) + 1
    return n, k, "안 마신 이유 " + (", ".join(f"{w} ×{c}" for w, c in refused.items()) or "없음") + f" · 마심/경우 적 수별 {_by_foes('low_hp_estus')}"


def d_damaged_switch(lines):
    """'목표 바꿈' away from a target we had already damaged (its HP in the last status line < the first one in this fight).
    Not built — every one counts as not followed. Outcome = HP lost within 5 s after the switch."""
    n = taken = 0
    first = last = None
    for i, x in enumerate(lines):
        if PLAN_RE.search(x) or "목표 바꿈" in x:
            if "목표 바꿈" in x and first is not None and last is not None and last < first:
                n += 1
                taken += _taken_after(lines, i)
            first = last = None
            continue
        m = FOE_HP_RE.search(x)
        if m:
            last = int(m.group(1))
            first = last if first is None else first
    return n, 0, f"바꾼 뒤 5 s 안 내 피해 {taken}"


def d_multi_fight(lines):
    """Fight plans with 2+ foes; 'followed' = backstab used in the run (rough — not tied to that fight)."""
    plans = [int(m.group(1)) for x in lines for m in [PLAN_RE.search(x)] if m]
    multi = sum(1 for p in plans if p >= 2)
    bs = sum(1 for x in lines if "backstab" in x and ("→ 피해" in x or "처치" in x))
    return multi, bs, f"계획 중 3놈 이상 {sum(1 for p in plans if p >= 3)} · 뒤잡 공격 줄 {bs}"


def d_two_foes(lines):
    """Fight plans with exactly 2 foes."""
    n = sum(1 for x in lines for m in [PLAN_RE.search(x)] if m and int(m.group(1)) == 2)
    return n, 0, "(b) 계단 밑 — 안 만듦"


def d_heavy_use(lines):
    """Attack summary lines: heavy × vs light ×."""
    heavy = sum(x.count("heavy×") for x in lines)
    light = sum(x.count("light×") for x in lines)
    return heavy + light, heavy, f"강공 {heavy} · 약공 {light} (공격 줄 기준)"


def d_taurus_close(lines):
    """Taurus close fight: lights pressed with the stamina then, and HP lost while close."""
    on = any("양손 가드 들고 들어감" in x for x in lines)
    hits = [x for x in lines if "타우로스 약공×" in x]
    sps = [m.group(1) for x in hits for m in [re.search(r"기력 (\d+)", x)] if m]
    taken = sum(int(m.group(2)) for x in hits for m in [HIT_RE.search(x)] if m)
    killed = any("타우로스 처치" in x for x in lines)
    return int(on), int(on), f"약공 {len(hits)}번 (기력 {', '.join(sps) or '-'}), 약공 중 내 피해 {taken}, 처치 {'예' if killed else '아니오'}"


def d_arm_room(lines):
    n = sum(1 for x in lines if "오른팔 공간" in x)
    k = sum(1 for x in lines if "오른팔 공간" in x and "왼쪽으로" in x and "0.00 m" not in x)
    return n, k, "움직인 것만 따름으로 셈"


def d_noise_wait(lines):
    n = sum(1 for x in lines if "나이프 뒤 기다리니 옴" in x or "나이프 뒤" in x and "아무도 안 옴" in x)
    k = sum(1 for x in lines if "나이프 뒤 기다리니 옴" in x)
    return n, k, "나이프 반응 없을 때"


def d_above_foe(lines):
    return None


DETECTORS = {f.__name__[2:]: f for f in (d_guard_counter, d_wall_bounce, d_crowd_wait, d_low_hp_estus, d_damaged_switch,
                                          d_multi_fight, d_two_foes, d_heavy_use, d_taurus_close, d_arm_room, d_noise_wait,
                                          d_above_foe)}


CHECK = {"agrees": "맞음", "partial": "일부 다름", "differs": "다름"}


def report(lines: list[str], ledger: list[dict]) -> list[dict]:
    CASES.clear()
    out = []
    done: dict = {}
    for e in ledger:
        det = e.get("detector")
        f = DETECTORS.get(det) if det else None
        r = (done[det] if det in done else done.setdefault(det, f(lines))) if f else None
        row = {"id": e["id"], "topic": e["topic"], "status": e["status"], "why": e.get("why"), "detector": det,
               "check": e.get("check")}
        if r is None:
            row.update(came=None, followed=None, outcome="감지기 없음 — 이 상황이 나왔는지 기록이 못 셈")
        else:
            row.update(came=r[0], followed=r[1], outcome=r[2])
        out.append(row)
    return out


def _find_log(arg: str | None) -> Path:
    if arg is None:
        return max(RUNS.glob("*.log"), key=lambda p: p.stat().st_mtime)
    p = Path(arg)
    if p.exists():
        return p
    for cand in (RUNS / f"{arg}.log", ROOT / "data" / "samples" / f"{arg}.txt"):
        if cand.exists():
            return cand
    raise SystemExit(f"no log for {arg}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    log = _find_log(args[0] if args else None)
    rows = report(log.read_text(encoding="utf-8", errors="replace").splitlines(), load_ledger())
    if "--json" in sys.argv:
        print(json.dumps({"log": log.name, "rows": rows}, ensure_ascii=False, indent=1))
        return
    print(f"MoKa 지시 장부 — {log.name}  (나옴 = 그 상황이 로그에 나온 횟수, 따름 = 말씀대로 한 횟수)")
    quiet = [] if "--all" in sys.argv else [r for r in rows if r["came"] is None and r["status"] in ("built", "principle")]
    for r in rows:
        if r in quiet:
            continue
        st = STATUS.get(r["status"], r["status"])
        came = "-" if r["came"] is None else r["came"]
        fol = "-" if r["followed"] is None else r["followed"]
        print(f"  {r['id']} [{st}] {r['topic']}")
        print(f"      나옴 {came} · 따름 {fol} · {r['outcome']}" + (f" · 이유: {r['why']}" if r["status"] != "built" and r.get("why") else ""))
        ck = r.get("check") or {}
        if ck.get("verdict") in ("partial", "differs"):
            print(f"      외부 자료 ({ck['by']}): {CHECK[ck['verdict']]} — {ck['note']}")
    if quiet:
        print(f"  감지기 없는 만듦·원칙 줄 {len(quiet)}개 — 나왔는지 로그로 못 셈 (--all 이면 줄마다): "
              + " ".join(r["id"] for r in quiet))
    if "--cases" in sys.argv:
        print()
        print("경우마다 그때 조건 (계획 적 수 · 내 HP · 기력 · 그놈 거리) — 결과가 나쁜 건 다른 조건 탓일 수 있음 (MoKa 11-08)")
        for det, t_, ok, note, c in CASES:
            print(f"  {t_:7.1f} s  {det:14s} {'○' if ok else '×'}  적 {c['foes'] or '?'} · HP {c['hp']} · SP {c['sp']} · {c['d']} m  {note}")


if __name__ == "__main__":
    main()
