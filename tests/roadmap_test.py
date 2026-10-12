"""ROADMAP.md stays short, its lines keep the checked format, and every problem has exactly one index row (CLAUDE.md). No game.

ROADMAP.md is read at the start of every session; at 307 KB (2026-10-09) it no longer fit in one read, so history moved to
docs/roadmap/. Since 2026-10-12 ([MoKa]: "끝난 것은 다른 곳으로 옮기고") each item is one fixed-format line and `roadmap.py tidy`
moves finished things out. This runs `roadmap.check()` on the real files, then `tidy` / `queue` on a throw-away copy.

  python tests/roadmap_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import shutil
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import roadmap as RM

ROOT = Path(__file__).resolve().parent.parent


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def main() -> None:
    errs = RM.check()
    check("the real ROADMAP.md passes roadmap.check()" + ("" if not errs else ":\n  " + "\n  ".join(errs)), not errs)
    for f in ("plan.md", "relay.md", "changelog.md"):
        check(f"docs/roadmap/{f} exists", (ROOT / "docs/roadmap" / f).is_file())

    real = (RM.ROADMAP, RM.PLAN, RM.PROBLEMS, RM.RELAY)
    tmp = Path(tempfile.mkdtemp(prefix="roadmap_"))
    try:
        for p in real:
            shutil.copy(p, tmp / p.name)
        RM.ROADMAP, RM.PLAN, RM.PROBLEMS, RM.RELAY = (tmp / p.name for p in real)
        text = RM.ROADMAP.read_text(encoding="utf-8")
        first = next(it for it in RM.items(text) if not it.get("bad"))

        # a broken line, an unknown role, a stage that doesn't fit the mark, a too-long now/next, a missing plan: id
        bad = ["- [~] Bad Id | cloud | doing | x | -", "- [ ] ok-id | robot | todo | x | -", "- [!] ok-id2 | win | doing | x | -",
               "- [ ] ok-id3 | win | todo | " + "x" * (RM.TEXT_MAX + 1) + " | -", "- [ ] ok-id4 | win | todo | x | plan:no-such-id"]
        RM.ROADMAP.write_text(text.replace(first["raw"], first["raw"] + "\n" + "\n".join(bad), 1), encoding="utf-8")
        errs = RM.check()
        for word in ("not '- [m] id", "who 'robot'", "with stage 'doing'", "chars (max", "plan:no-such-id"):
            check(f"check() catches: {word}", any(word in e for e in errs))

        # tidy: a done item, a fixed problem row, a handled relay entry → out of ROADMAP.md, into the archive files
        done = first["raw"].replace(f"[{first['mark']}]", "[x]", 1).replace(f"| {first['stage']} |", "| doing |", 1)
        text2 = text.replace(first["raw"], done, 1)
        row = next(r for r in RM.index_rows(text2, "## 4."))
        text2 = text2.replace(row["raw"], row["raw"].rsplit("|", 2)[0] + "| fixed — test |", 1)
        relay_line = "- 2026-10-12 [board→cloud] → done 10-12 [cloud] test entry"
        text2 = text2.replace("## 5. Relay — [cloud] ↔ board\n", "## 5. Relay — [cloud] ↔ board\n\n" + relay_line + "\n", 1)
        RM.ROADMAP.write_text(text2, encoding="utf-8")
        n = RM.tidy()
        after = RM.ROADMAP.read_text(encoding="utf-8")
        check(f"tidy moved 1 item, 1 problem row, 1 relay entry ({n})", n == {"items": 1, "problems": 1, "relay": 1})
        check("… gone from ROADMAP.md", done not in after and relay_line not in after
              and f"| {row['n']} |" not in after.split("## 4.")[1].split("## 5.")[0])
        check("… the item is in plan.md 'Done items', the row in the closed index (sorted), the entry in relay.md",
              done[2:] in RM.PLAN.read_text(encoding="utf-8")
              and row["n"] in [r["n"] for r in RM.index_rows(RM.PROBLEMS.read_text(encoding="utf-8"), RM.CLOSED_HEAD)]
              and relay_line in RM.RELAY.read_text(encoding="utf-8"))
        rows = RM.index_rows(RM.PROBLEMS.read_text(encoding="utf-8"), RM.CLOSED_HEAD)
        check("closed index stays sorted", [r["n"] for r in rows] == sorted(r["n"] for r in rows))
        check("after tidy the copy passes check()", RM.check() == [])

        q = RM.queue("win")
        check("queue('win'): only win's open items, doing / verify first",
              q and all("win" in it["who"] for it in q) and q[0]["stage"] in ("doing", "verify"))
        check("show(id) prints the line and its plan.md details", "`alignment`" in RM.show("alignment"))
    finally:
        RM.ROADMAP, RM.PLAN, RM.PROBLEMS, RM.RELAY = real
        shutil.rmtree(tmp, ignore_errors=True)
    size = len(RM.ROADMAP.read_text(encoding="utf-8").encode("utf-8"))
    print(f"roadmap_test: all ok — ROADMAP.md {size} bytes ≤ {RM.MAX_BYTES}")


if __name__ == "__main__":
    main()
