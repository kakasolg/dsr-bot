"""Blind spells in fights — stretches where the duel loop wrote no status line, from bot logs. No game.

  python blind_report.py                                 newest data/samples/burg-bonfire-radar-*.txt vs the rest
  python blind_report.py data/samples/burg-bonfire-radar-2026-09-30*.txt     these runs

Why: the average decision rate (ticks/s over a fight) stayed the same while MoKa saw the bot get slower (2026-10-01).
The duel writes a status line ("[ 4.4s] 거리 … | 반사×28") about once a second while it is deciding; when an action
runs as one block (the walk back after a backstab, a grip switch + heavy + light, a backstab sweep) no line is written —
the bot isn't deciding, and the reflex isn't blocking. A gap of more than GAP_S between two status lines of one fight
is a blind spell; what was logged inside it says what the bot was busy with, and the black-box lines whose window
overlaps it (they are written just after the hits) say what it cost (HP lost while not deciding).
"""
from __future__ import annotations

import argparse
import glob
import re
import sys
from collections import defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
GAP_S = 2.0
_STATUS = re.compile(r"^\[\s*([\d.]+)\]\s+\[\s*([\d.]+)s\]")          # [wall time] [time into the fight s]
_HIT = re.compile(r"^\[\s*([\d.]+)\].*블랙박스 #\d+: ([\d.]+) s 동안 -(\d+)")   # written after the hits: its window is
BB_LATE_S = 1.5                                                                   # [t − d, t], up to this after the spell
CAUSES = [("edge retreat", "발밑 가장자리"),           # duel._back_to_safe: walk back after a backstab, no guard/reflex
          ("heavy / grip", "강공|양손"),               # wall heavy: grip switch + heavy (+ light) as one block
          ("backstab", "뒤잡기"),
          ("separate", "떼어놓기"),
          ("approach", "붙는 중"),
          ("target switch", "목표 바꿈")]


def spells(path: str, gap: float = GAP_S) -> list[dict]:
    """[{t, s, cause, hp, text}] — blind spells of one run: t = wall time at the end, s = length, hp = HP lost inside."""
    lines = [l.rstrip("\n") for l in open(path, encoding="utf-8", errors="replace")]
    out, prev = [], None
    for i, line in enumerate(lines):
        m = _STATUS.match(line)
        if not m:
            continue
        wall, ft = float(m.group(1)), float(m.group(2))
        if prev is not None and gap < ft - prev[1] < 60.0:           # same fight (time into it goes on), long gap
            mid = lines[prev[2] + 1:i]
            text = " ".join(mid)
            cause = next((c for c, pat in CAUSES if re.search(pat, text)), "other")
            hp = 0
            for line2 in lines[prev[2] + 1:]:                         # black-box windows overlapping the spell
                h = _HIT.match(line2)
                tb = _STATUS.match(line2) or re.match(r"^\[\s*([\d.]+)\]", line2)
                if tb and float(tb.group(1)) > wall + BB_LATE_S:
                    break
                if h and float(h.group(1)) - float(h.group(2)) < wall and float(h.group(1)) > prev[0]:
                    hp += int(h.group(3))
            out.append({"t": wall, "s": round(ft - prev[1], 1), "cause": cause, "hp": hp,
                        "text": " / ".join(x.split("]", 1)[-1].strip()[:50] for x in mid if x.strip())[:200]})
        prev = (wall, ft, i)
    return out


def table(runs: dict[str, list[dict]]) -> str:
    names = [c for c, _ in CAUSES] + ["other"]
    lines = [f"{'run':<34}" + "".join(f"{n:>22}" for n in names) + f"{'total':>16}"]
    for run, sp in runs.items():
        agg = defaultdict(lambda: [0, 0.0, 0])
        for x in sp:
            a = agg[x["cause"]]
            a[0] += 1
            a[1] += x["s"]
            a[2] += x["hp"]
        cell = lambda a: f"{a[0]:2d}× {a[1]:5.1f}s −{a[2]:<4d}"
        lines.append(f"{run[:34]:<34}" + "".join(f"{cell(agg[n]):>22}" for n in names)
                     + f"{sum(x['s'] for x in sp):7.1f}s −{sum(x['hp'] for x in sp):<5d}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--gap", type=float, default=GAP_S)
    ap.add_argument("--list", action="store_true", help="every blind spell of the newest run")
    a = ap.parse_args()
    files = a.files or sorted(glob.glob(str(ROOT / "data" / "samples" / "burg-bonfire-radar-*.txt"))   # + sample.py names (<stamp>_<cmd>…)
                              + glob.glob(str(ROOT / "data" / "samples" / "20*_burg-*.txt")), key=lambda f: Path(f).stat().st_mtime)
    if not files:
        print("no bot logs")
        return
    runs = {Path(f).stem.replace("burg-bonfire-radar-", ""): spells(f, a.gap) for f in files}
    import runinfo
    print(f"newest: {Path(files[-1]).name} — {runinfo.describe(files[-1])}")
    print(f"blind spells (> {a.gap:.0f} s without a duel status line inside one fight): count × seconds −HP lost meanwhile")
    print(table(runs))
    if a.list:
        last = list(runs)[-1]
        print(f"\n{last}:")
        for x in sorted(runs[last], key=lambda x: -x["s"]):
            print(f"  {x['t']:7.1f} s  {x['s']:4.1f} s  {x['cause']:<14} −{x['hp']:<4d} {x['text']}")


if __name__ == "__main__":
    main()
