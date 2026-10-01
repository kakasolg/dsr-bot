"""blind_report.py offline test — blind spells (no duel status line for > 2 s inside a fight) and what they cost. No game.

  python tests/blind_report_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import blind_report as B

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


log = Path(tempfile.mkdtemp()) / "burg-bonfire-radar-x.txt"
log.write_text("\n".join([
    "[  100.0]       [ 1.0s] 거리 1.9 높이 +0.0 그놈 애니 -1 HP 85 | 나 HP 793 | 기다림×23",
    "[  101.0]       [ 2.0s] 거리 1.7 | 기다림×21",
    "[  101.3]       벽 1.1 m — 강공(수직)",
    "[  101.6]       방패병: 양손으로",
    "[  104.4]       [ 5.4s] 거리 1.6 | heavy+light×1",
    "[  104.5]    ▣ 블랙박스 #12: 1.36 s 동안 -362 → HP 431/793",              # written after, window 103.1~104.5
    "[  105.4]       [ 6.4s] 거리 1.8 | 반사×31",
    "[  105.6]       뒤잡기 뒤 발밑 가장자리 — 싸움 자리 (-30.0,29.0)로 물러남",
    "[  106.0]    ▣ 블랙박스 #13: 0.0 s 동안 -91 → HP 340/793",
    "[  110.4]       [11.4s] 거리 2.0 | 반사×10",
    "[  111.0]    #6 이동: 따라온 255000: killed — 11 s",
    "[  130.0]       [ 1.0s] 거리 3.0 | 기다림×10",                             # a new fight: time into it restarts
    "[  131.0]       [ 2.0s] 거리 2.0 | 기다림×10",
]), encoding="utf-8")
sp = B.spells(str(log))
check("two blind spells: 3.4 s heavy/grip, 5.0 s edge retreat (the new fight's restart isn't one)",
      [(x["s"], x["cause"]) for x in sp] == [(3.4, "heavy / grip"), (5.0, "edge retreat")])
check("HP lost in a spell: black-box windows overlapping it (written just after the hits) — 362 and 91",
      [x["hp"] for x in sp] == [362, 91])
log2 = log.with_name("y.txt")
log2.write_text("\n".join(["[  10.0]       [ 1.0s] a", "[  13.0]       [ 4.0s] b",
                            "[  20.0]    ▣ 블랙박스 #1: 0.5 s 동안 -50 → HP 1/1"]), encoding="utf-8")
check("a black box well after the spell isn't counted", B.spells(str(log2))[0]["hp"] == 0)
check("a shorter gap setting finds the 1 s steps too", len(B.spells(str(log), gap=0.5)) > 2)
t = B.table({"x": sp})
check("table: one row per run, edge retreat 1× 5.0 s −91", "1×   5.0s −91" in t and "1×   3.4s −362" in t)
check("committed 09-30c log: the 3.4 s wall-heavy spell at 346.6 s is found, with its −362",
      any(x["cause"] == "heavy / grip" and x["s"] == 3.4 and x["hp"] == 362 for x in
          B.spells(str(Path(__file__).resolve().parent.parent / "data" / "samples" / "burg-bonfire-radar-2026-09-30c.txt"))))

print(f"\n{'all ok' if not fails else f'{fails} FAILED'}")
sys.exit(1 if fails else 0)
