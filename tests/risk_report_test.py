"""P-62: risk_report counted escape.pick's back-off (field.Field.escape_choice, ev "escape" with src / point in the 10-10 …
10-11 runs) as a quit-out (강종) — three clean pull r2 runs (071213, 072424, 072043) came out '위험'. Now the back-off is
"escape_pick", and an "escape" row with src is not counted either (the runs already recorded)."""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))

import inspect
import json
import tempfile

import risk_report
from souls import field


def check(what: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        raise SystemExit(1)


def score(rows: list) -> dict:
    with tempfile.TemporaryDirectory() as d:
        p = _pl.Path(d) / "20261011_071213_burg-bonfire.jsonl"
        p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        return risk_report.score(p)


def main() -> None:
    base = [{"t": 0.0, "ev": "style", "style": "guard"},
            {"t": 1.0, "ev": "vital", "hp": 700, "max": 742}, {"t": 2.0, "ev": "vital", "hp": 650, "max": 742},
            {"t": 120.0, "ev": "result", "result": "통로 끝", "cmd": "burg-bonfire"}]
    pick_old = {"t": 50.0, "ev": "escape", "src": "trail", "point": [-30.0, -49.2, 29.0], "kept": 4, "cands": 7}
    pick_new = dict(pick_old, ev="escape_pick")
    quit_ = {"t": 60.0, "ev": "escape", "why": "낙사 (바닥 모름, 0.8 s 에 4.1 m)", "kind": "fall", "how": "byte", "hp": 610}

    r = score(base + [pick_old])
    check(f"a 10-10 … 10-11 run with only escape.pick's 'escape' row → no 강종, '{r['verdict']}' ({r['flags']})",
          r["escapes"] == 0 and r["verdict"] == "깨끗")
    r = score(base + [pick_new])
    check(f"… and with the renamed 'escape_pick' → '{r['verdict']}'", r["escapes"] == 0 and r["verdict"] == "깨끗")
    r = score(base + [pick_old, quit_])
    check(f"a real quit-out still counts: {r['flags']}", r["escapes"] == 1 and r["verdict"] == "위험" and "강종×1(fall)" in r["flags"])
    check("Field.escape_choice logs 'escape_pick', not 'escape'",
          '"escape_pick"' in inspect.getsource(field.Field.escape_choice) and '"escape",' not in inspect.getsource(field.Field.escape_choice))
    print("risk_report_test: 전부 통과")


if __name__ == "__main__":
    main()
