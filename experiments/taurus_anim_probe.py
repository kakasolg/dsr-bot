"""Taurus anim clock probe (P-142 follow-up, [cloud] 2026-11-09 board request, MoKa 11-09 "측정 먼저") — read-only, runs next to
`run.py taurus` in a second process. Writes nothing to the game.

  python experiments/taurus_anim_probe.py record [secs] [out]     # default 240 s → data/runs/<time>_taurus_anim.jsonl
  python experiments/taurus_anim_probe.py report <file>

Measures the three things [cloud] asked for before an in-fight sip rule can be built:
  1. whether the boss's anim_time (DSRTelemetry.anim_time) reads in its 3000-series attacks (P-97: unverified)
  2. each 3000–3006 anim's length: the largest anim_time an instance reaches before the anim id changes
     (an instance cut short by another anim shows a smaller max — the report gives max and median per anim)
  3. Estus: when HP rises, measured from the start of the player anim it rose in (anim id + anim_time at the rise)
Each line: t (perf_counter s), boss anim / anim_time / HP / distance, player anim / anim_time / HP. ~100 Hz.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BOSS_NPC = 225000         # Taurus Demon (risk lines name it 225000)


def _r(v, n=4):
    return None if v is None else round(v, n)


def record(secs: float, out: Path) -> None:
    from dsr_telemetry import DSRTelemetry
    tm = DSRTelemetry()
    n, t_end = 0, time.perf_counter() + secs
    with out.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "header", "boss_npc": BOSS_NPC, "secs": secs, "wall": time.time()}) + "\n")
        while time.perf_counter() < t_end:
            s = tm.snapshot(within=80.0)
            if s is None:
                time.sleep(0.05)
                continue
            p = s.player
            b = next((c for c in s.chars if c.npc_param == BOSS_NPC), None)
            line = {"t": round(time.perf_counter(), 4), "hp": p.hp, "pa": p.anim, "pat": _r(tm.anim_time(p.ptr))}
            if b is not None:
                line.update(ba=b.anim, bat=_r(tm.anim_time(b.ptr)), bhp=b.hp, d=round(math.hypot(b.x - p.x, b.z - p.z), 2))
            fh.write(json.dumps(line) + "\n")
            n += 1
            if n % 1000 == 0:
                fh.flush()
            time.sleep(0.008)
    print(f"{n} lines → {out}")


def _runs(rows, key_a, key_t):
    """Consecutive rows with the same anim id and a non-decreasing anim_time = one instance (a restart of the same id splits)."""
    out, cur = [], None
    for r in rows:
        a, at = r.get(key_a), r.get(key_t)
        if a is None:
            cur = None
            continue
        if cur is not None and cur["a"] == a and (at is None or cur["last"] is None or at >= cur["last"] - 0.02):
            cur["rows"].append(r)
            cur["last"] = at if at is not None else cur["last"]
            continue
        cur = {"a": a, "rows": [r], "last": at}
        out.append(cur)
    return out


def report(path: Path) -> None:
    rows = [json.loads(l) for l in path.open(encoding="utf-8")]
    rows = [r for r in rows if r.get("kind") != "header"]
    if not rows:
        print("no rows")
        return
    span = rows[-1]["t"] - rows[0]["t"]
    print(f"{path.name}: {len(rows)} lines, {span:.1f} s, {len(rows) / max(span, 1e-6):.0f} Hz")

    boss = [r for r in rows if "ba" in r]
    atk = [r for r in boss if r["ba"] is not None and 3000 <= r["ba"] < 4200]
    read = [r for r in atk if r.get("bat") is not None]
    print(f"\n1. 보스 anim_time 읽힘 (3000·4000·4100번대): {len(read)}/{len(atk)} 줄"
          + ("" if not atk else f" — 0이 아닌 값 {sum(1 for r in read if r['bat'] > 0)}"))

    print("\n2. 보스 애니 길이 (한 번 재생 = 같은 id, anim_time이 줄지 않는 동안; 최대값 = 끝까지 갔을 때 길이)")
    print("   애니   횟수  최대 anim_time  중앙값   다음 애니 (끝난 뒤)")
    by = {}
    for i, run in enumerate(_runs(boss, "ba", "bat")):
        ts = [r["bat"] for r in run["rows"] if r.get("bat") is not None]
        if not ts or not (3000 <= run["a"] < 4200):
            continue
        nxt = None
        rest = boss[boss.index(run["rows"][-1]) + 1:]
        if rest:
            nxt = rest[0].get("ba")
        by.setdefault(run["a"], []).append((max(ts), nxt, run["rows"][0].get("d")))
    for a in sorted(by):
        mx = [m for m, _n, _d in by[a]]
        nx = sorted({str(n) for _m, n, _d in by[a]})
        print(f"   {a}  {len(mx):4d}  {max(mx):8.3f} s     {statistics.median(mx):6.3f}   {', '.join(nx)}")

    print("\n3. 에스트: HP가 오른 순간 (그때 내 애니 · 그 애니 안의 anim_time)")
    pr = _runs(rows, "pa", "pat")
    for i in range(1, len(rows)):
        a, b = rows[i - 1], rows[i]
        if a.get("hp") is not None and b.get("hp") is not None and b["hp"] > a["hp"]:
            run = next((x for x in pr if b in x["rows"]), None)
            start = run["rows"][0]["t"] if run else None
            end = run["rows"][-1] if run else None
            length = max((r["pat"] for r in run["rows"] if r.get("pat") is not None), default=None) if run else None
            print(f"   +{b['hp'] - a['hp']:4d} HP  애니 {b.get('pa')}  anim_time {b.get('pat')}  (애니 시작 뒤 {b['t'] - start:.2f} s, "
                  f"애니 최대 {length} s, 보스 {b.get('ba')} {b.get('d')} m)")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "record"
    if cmd == "record":
        secs = float(sys.argv[2]) if len(sys.argv) > 2 else 240.0
        out = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / "data/runs" / (time.strftime("%Y%m%d_%H%M%S") + "_taurus_anim.jsonl")
        record(secs, out)
    else:
        report(Path(sys.argv[2]))


if __name__ == "__main__":
    main()
