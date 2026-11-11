"""stage_report.py on the real data (offline): per-zone terrain / foes / runs come out, deaths are judged by the run's own
height (the 10-12 zone 1 falls), and regenerating keeps the hand-written part of docs/stages/<area>.md. No game.

  python tests/stage_report_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import stage_report as SR


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def main() -> None:
    rep = SR.build("burg-upper")
    Z = {z["n"]: z for z in rep["zones"]}
    check(f"8 zones, {rep['runs_read']} run logs read", sorted(Z) == list(range(1, 9)) and rep["runs_read"] >= 30)
    d1 = Z[1]["runs"]["deaths"]
    check("zone 1: the three 10-12 deaths are falls (track height), not '254010' as the old black box said",
          [x["cause"] for x in d1 if x["run"].startswith("20261012_0034") or x["run"].startswith("20261012_0036")
           or x["run"].startswith("20261012_0038")] == ["fall", "fall", "fall"])
    check("zone 5: deaths are by the spear shield soldier 255001", Z[5]["runs"]["deaths"]
          and all(x["by"] == 255001 for x in Z[5]["runs"]["deaths"]))
    check("terrain: zone 1's safe spot is far from drops, zone 4's is beside one",
          Z[1]["terrain"]["safe_drop_m"] > 8 and Z[4]["terrain"]["safe_drop_m"] < 1)
    k4 = Z[4]["foes"]
    check("foes: zone 4's three hollows wake together; ThinkParam sight / hearing read",
          {(g["a"], g["b"]) for g in k4["together"]} >= {(1, 2), (1, 3), (2, 3)}
          and all(k["sight_m"] and k["hearing_m"] for k in k4["kills"]))
    check("ignored ledge bombers are marked near zone 3", any(o["ignored"] and o["npc"] == 254012 for o in Z[3]["foes"]["others"]))
    md = SR.markdown(rep)
    check("markdown block has the summary table and one auto section per zone",
          md.startswith(SR.BEGIN) and md.endswith(SR.END) and md.count("— 자동") == 8)

    # regenerating keeps what is written by hand around the block
    real = SR.ROOT
    tmp = Path(tempfile.mkdtemp(prefix="stage_"))
    try:
        SR.ROOT = tmp
        doc = tmp / "docs" / "stages" / "burg-upper.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("# hand title\n\nhand text above\n\n" + SR.BEGIN + "\nold\n" + SR.END + "\n\nhand text below\n", encoding="utf-8")
        SR.write(rep)
        text = doc.read_text(encoding="utf-8")
        check("write(): hand-written text above and below kept, the block replaced",
              text.startswith("# hand title\n\nhand text above") and text.rstrip().endswith("hand text below")
              and "\nold\n" not in text and "구역 8 — 자동" in text and (tmp / "data" / "stages" / "burg-upper.json").exists())
    finally:
        SR.ROOT = real
    print("stage_report_test: all ok")


if __name__ == "__main__":
    main()
