"""hotspots offline test — repeated walking problems from run logs.

  python tests/hotspots_test.py
"""
from __future__ import annotations

import glob
import sys
import tempfile
from pathlib import Path

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import hotspots as H

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


LOG1 = """[  231.3]       #4 이동: 32/39번 점 (-9.8, -11.3, -68.6) 못 감 (unreachable, 1번째) — 나 (-11.1, -9.8, -70.1), 2.5 m
[  245.6]       #6 이동: 길 막은 o1321 (o1321_0021) 부숨 시도 — (-22.7,-13.4,-64.3)
[  250.0]    something else
"""
LOG2 = """[  253.8]       #4 이동: 43/50번 점 (-9.8, -11.3, -68.6) 못 감 (unreachable, 1번째) — 나 (-11.0, -9.8, -70.1), 2.4 m
[  300.0]       #1 이동: 3/9번 점 (40.0, 0.0, 40.0) 못 감 (timeout, 1번째) — 나 (39.0, 0.0, 39.0), 1.4 m
"""
d = Path(tempfile.mkdtemp())
(d / "a.log").write_text(LOG1, encoding="utf-8")
(d / "b.log").write_text(LOG2, encoding="utf-8")
ev = H.parse(str(d / "a.log"))
check("못 감·부숨 두 줄 읽음", [e["kind"] for e in ev] == ["point-fail", "smash"])
check("위치·이유·높이차", ev[0]["pos"] == (-9.8, -11.3, -68.6) and ev[0]["why"] == "unreachable" and ev[0]["dy"] == -1.5)
places = H.group(ev + H.parse(str(d / "b.log")))
check("같은 자리 두 실행이 한 곳으로", len(places[0]["runs"]) == 2 and places[0]["pos"] == (-9.8, -11.3, -68.6))
rep = H.report(places, 2)
check("리포트: 2번 이상 실행된 곳만", "1 places in ≥2 runs" in rep and "(-9.8, -11.3, -68.6)  2/2 runs" in rep and "40.0" not in rep)

(d / "a_copy.log").write_text(LOG1, encoding="utf-8")
runs = H.dedupe({str(d / n): H.parse(str(d / n)) for n in ("a.log", "b.log", "a_copy.log")})
check("같은 실행의 복사본은 한 번만 셈 (P-12)", len(runs) == 2 and str(d / "a_copy.log") not in runs)

samples = sorted(glob.glob("data/samples/burg-bonfire-radar-*.txt"))
if samples:
    real = H.group([e for p in samples for e in H.parse(p)])
    top = next((r for r in real if r["pos"] == (-9.8, -11.3, -68.6)), None)   # not pinned to 1st: new sample runs reorder the list
    check(f"실제 로그 {len(samples)}개: (-9.8, -11.3, -68.6) {len(top['runs']) if top else 0}번 (4번 이상)",
          top is not None and len(top["runs"]) >= 4)

print("전부 통과" if not fails else f"실패 {fails}")
sys.exit(1 if fails else 0)
