"""Every death in data/samples: what the log blames vs what my own height did (offline, read-only).

Why ([cloud] 2026-10-12, answer to docs/code-read-fall-death-2026-10-11.md §6): `✝ 죽음` carries no cause and the
black box blames the nearest swinging foe even when the HP went in a fall. One row per death:
  run · death time · y drop before the first HP-0 frame (track, 0.5 s) · fall quit-out in the 30 s before ·
  black box guess for the killing bundle · verdict (fall = y fell ≥ FALL_M before HP hit 0, or no track and the
  black box saw no attacker right after a `낙사` line).

    python experiments/death_audit.py [data/samples]
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

FALL_M = 3.0        # y drop between the highest point in the last LOOK_S and the first HP-0 frame
LOOK_S = 3.0
CHAIN_S = 30.0      # a fall quit-out this long before the death counts as part of the chain
T = re.compile(r"^\[\s*([\d.]+)\]")


def log_rows(path: str):
    out = []
    for line in open(path, encoding="utf-8", errors="replace"):
        m = T.match(line)
        out.append((float(m.group(1)) if m else None, line.rstrip("\n")))
    return out


def track_death(path: str):
    """→ (t of first HP-0 frame, y drop before it, HP just before) or None."""
    snaps = []
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        if r.get("type") == "snap" and r.get("player"):
            snaps.append((r["rt"], r["player"].get("hp"), r["player"].get("y")))
    for i in range(1, len(snaps)):
        t, hp, y = snaps[i]
        if hp == 0 and (snaps[i - 1][1] or 0) > 0:
            top = max(s[2] for s in snaps[:i] if t - LOOK_S <= s[0])
            return t, top - y, snaps[i - 1][1]
    return None


def audit(folder: str):
    rows = []
    for txt in sorted(glob.glob(os.path.join(folder, "*.txt"))):
        L = log_rows(txt)
        for i, (t, line) in enumerate(L):
            if "✝ 죽음" not in line:
                continue
            bb = next((L[j] for j in range(i, max(0, i - 300), -1) if "블랙박스" in L[j][1] and "HP 0/" in L[j][1]), None)
            t_dead = bb[0] if bb else t
            falls = [r for r in L[max(0, i - 400):i] if r[0] is not None and t_dead - CHAIN_S <= r[0] <= t_dead and "낙사" in r[1]]
            blame = bb[1].split("추정", 1)[1].strip() if bb else "-"
            no_attacker = blame.startswith("공격 애니 중인 적 없음")
            stem = txt[:-4]
            tr = glob.glob(stem + ".track.jsonl") or glob.glob(stem.replace("-radar", "") + ".track.jsonl")
            td = track_death(tr[0]) if tr else None
            if td:
                fall = td[1] >= FALL_M
            else:
                fall = no_attacker and bool(falls)
            rows.append({"run": os.path.basename(stem), "t": t_dead, "drop": None if td is None else round(td[1], 1),
                         "fall_quit_before": sum("퀵 종료: 낙사" in r[1] for r in falls), "blame": blame,
                         "verdict": "fall" if fall else "hit", "blame_wrong": fall and not no_attacker})
    return rows


def main() -> None:
    rows = audit(sys.argv[1] if len(sys.argv) > 1 else "data/samples")
    for r in rows:
        drop = "  -  " if r["drop"] is None else f"{r['drop']:5.1f}"
        flag = "  ← blame wrong" if r["blame_wrong"] else ""
        print(f"{r['run'][:44]:44s} {r['t']:6.1f}s drop {drop} quit-before {r['fall_quit_before']} "
              f"{r['verdict']:4s} | {r['blame'][:58]}{flag}")
    falls = [r for r in rows if r["verdict"] == "fall"]
    print(f"\n{len(rows)} deaths · {sum(r['drop'] is not None for r in rows)} with a track · fall {len(falls)} "
          f"(black box blamed a foe in {sum(r['blame_wrong'] for r in falls)}) · "
          f"a fall quit-out in the {CHAIN_S:.0f} s before: {sum(r['fall_quit_before'] > 0 for r in rows)}")


if __name__ == "__main__":
    main()
