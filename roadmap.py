"""ROADMAP.md as checked, fixed-format lines — and the tool that keeps it small ([MoKa] 2026-10-12: "끝난 것은 다른 곳으로 옮기고").

  python roadmap.py check            format, size, problem index ↔ problems.md (tests/roadmap_test.py runs this)
  python roadmap.py tidy             move what is finished out: [x]/[-] items → plan.md, fixed / won't-fix problem rows →
                                     problems.md "Closed problem index", handled relay entries (→ done / → moved) → relay.md
  python roadmap.py queue win        what one role has to do now (cloud · win · MoKa), by stage
  python roadmap.py show <id>        an item and its details (plan.md "Open-item details")

An item is one line, five fields:

  - [~] shop | cloud | doing | greeting can run several lines — wait on the screen, not a fixed time | docs/shop-undead-merchant.md
    mark   id     who     stage   now / next (≤ TEXT_MAX chars)                                       where the details are

  mark   [ ] not started · [~] going · [!] blocked · [x] done · [-] dropped (the last two are moved out by tidy)
  id     lower-case words joined by '-', unique
  who    whose move it is now: cloud · win · MoKa, several joined by '+'
  stage  todo · doing · verify (built, waits for a game check) · decide (waits for MoKa) · blocked · parked
  where  files / P-numbers; `plan:<id>` = that item's line in plan.md "Open-item details" (history, numbers, quotes)
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
ROADMAP = ROOT / "ROADMAP.md"
PLAN = ROOT / "docs" / "roadmap" / "plan.md"
PROBLEMS = ROOT / "docs" / "roadmap" / "problems.md"
RELAY = ROOT / "docs" / "roadmap" / "relay.md"

MAX_BYTES = 20_000      # was 24,000 with closed problems and item histories inside — now those live in the archive
TEXT_MAX = 150          # the "now / next" field
ROLES = ("cloud", "win", "MoKa")
STAGES = ("todo", "doing", "verify", "decide", "blocked", "parked")
MARKS = {" ": ("todo", "decide", "parked"), "~": ("doing", "verify", "decide"), "!": ("blocked",),
         "x": STAGES, "-": STAGES}
ITEM = re.compile(r"^- \[(?P<mark>.)\] (?P<id>[a-z0-9][a-z0-9-]*) \| (?P<who>[^|]+?) \| (?P<stage>[a-z]+) \| "
                  r"(?P<text>[^|]+?) \| (?P<ref>[^|]+?)\s*$")
ROW = re.compile(r"^\| (?P<n>\d+) \| (?P<text>.*) \| (?P<status>[^|]*) \|\s*$")
CLOSED = re.compile(r"^(fixed|won't fix)\b", re.I)
HANDLED = re.compile(r"^- \d{4}-\d{2}-\d{2} \[[^\]]+\] → (done|moved|처리|옮김)\b")
DETAILS_HEAD = "## Open-item details"
CLOSED_HEAD = "## Closed problem index"
DONE_HEAD = "## Done items (moved out of ROADMAP.md by roadmap.py tidy)"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _section(text: str, head_prefix: str) -> tuple[int, int]:
    """(start, end) line indexes of the section whose heading starts with head_prefix (heading line excluded)."""
    lines = text.split("\n")
    i = next((k for k, l in enumerate(lines) if l.startswith(head_prefix)), None)
    if i is None:
        return -1, -1
    j = next((k for k in range(i + 1, len(lines)) if lines[k].startswith("## ")), len(lines))
    return i + 1, j


def items(text: str | None = None) -> list[dict]:
    """Every item line in sections 1–3 (each line starting '- [')."""
    text = _read(ROADMAP) if text is None else text
    out = []
    lines = text.split("\n")
    a, _ = _section(text, "## 1.")
    b, _ = _section(text, "## 4.")
    for k in range(max(0, a), (b - 1) if b > 0 else len(lines)):
        l = lines[k]
        if l.startswith("- ["):
            m = ITEM.match(l)
            out.append({"line": k + 1, "raw": l, **(m.groupdict() if m else {"bad": True})})
    return out


def index_rows(text: str, head: str) -> list[dict]:
    a, b = _section(text, head)
    if a < 0:
        return []
    out = []
    for l in text.split("\n")[a:b]:
        m = ROW.match(l)
        if m:
            out.append({"n": int(m["n"]), "status": m["status"].strip(), "raw": l})
    return out


def detail_ids(plan: str | None = None) -> set[str]:
    plan = _read(PLAN) if plan is None else plan
    a, b = _section(plan, DETAILS_HEAD)
    if a < 0:
        return set()
    return {m.group(1) for l in plan.split("\n")[a:b] for m in [re.match(r"^- `([a-z0-9-]+)`", l)] if m}


def check() -> list[str]:
    """→ problems (empty = fine)."""
    errs = []
    text, problems, plan = _read(ROADMAP), _read(PROBLEMS), _read(PLAN)
    size = len(text.encode("utf-8"))
    if size > MAX_BYTES:
        errs.append(f"ROADMAP.md is {size} bytes (limit {MAX_BYTES}) — `python roadmap.py tidy`, shorten lines, details → plan.md")
    seen, details = set(), detail_ids(plan)
    for it in items(text):
        where = f"ROADMAP.md:{it['line']}"
        if it.get("bad"):
            errs.append(f"{where}: not '- [m] id | who | stage | now / next | where': {it['raw'][:80]}")
            continue
        if it["id"] in seen:
            errs.append(f"{where}: id '{it['id']}' used twice")
        seen.add(it["id"])
        who = [w.strip() for w in it["who"].split("+")]
        if not all(w in ROLES for w in who):
            errs.append(f"{where}: who '{it['who']}' — use {' / '.join(ROLES)} joined by '+'")
        if it["stage"] not in STAGES:
            errs.append(f"{where}: stage '{it['stage']}' — one of {', '.join(STAGES)}")
        elif it["mark"] not in MARKS:
            errs.append(f"{where}: mark '[{it['mark']}]' — one of [ ] [~] [!] [x] [-]")
        elif it["stage"] not in MARKS[it["mark"]]:
            errs.append(f"{where}: [{it['mark']}] with stage '{it['stage']}' (allowed: {', '.join(MARKS[it['mark']])})")
        if len(it["text"]) > TEXT_MAX:
            errs.append(f"{where}: now/next is {len(it['text'])} chars (max {TEXT_MAX}) — the rest goes to plan.md")
        for ref in re.findall(r"plan:([a-z0-9-]+)", it["ref"]):
            if ref not in details:
                errs.append(f"{where}: plan:{ref} — no '- `{ref}`' line in plan.md \"{DETAILS_HEAD}\"")
        if it["mark"] in "x-":
            errs.append(f"{where}: [{it['mark']}] still here — `python roadmap.py tidy`")
    entries = {int(n) for n in re.findall(r"^### P-(\d+) ", problems, re.M)}
    if not entries:
        errs.append("no '### P-<n>' entries in docs/roadmap/problems.md")
    open_rows, closed_rows = index_rows(text, "## 4."), index_rows(problems, CLOSED_HEAD)
    ns = [r["n"] for r in open_rows + closed_rows]
    dup = sorted({n for n in ns if ns.count(n) > 1})
    if dup:
        errs.append(f"problem rows twice: {dup}")
    if set(ns) != entries:
        errs.append(f"problem index out of sync — entries without a row: {sorted(entries - set(ns))}, rows without an entry: "
                    f"{sorted(set(ns) - entries)}")
    for r in open_rows:
        if CLOSED.match(r["status"]):
            errs.append(f"P-{r['n']} is '{r['status'][:30]}' — closed rows go to problems.md (`python roadmap.py tidy`)")
    for r in closed_rows:
        if not CLOSED.match(r["status"]):
            errs.append(f"P-{r['n']} in the closed index is '{r['status'][:30]}' — reopened? put the row back in ROADMAP.md")
    return errs


def _insert_section_rows(text: str, head: str, rows: list[str], intro: str, before: str | None = None) -> str:
    """Add rows at the end of section `head`, creating it (with intro) before the line starting with `before` (or at the end)."""
    lines = text.split("\n")
    a, b = _section(text, head)
    if a < 0:
        block = [head, "", *intro.split("\n"), *rows, ""]
        k = next((i for i, l in enumerate(lines) if before and l.startswith(before)), None)
        if k is None:
            while lines and lines[-1] == "":
                lines.pop()
            lines += ["", *block]
        else:
            lines[k:k] = block
        return "\n".join(lines).rstrip("\n") + "\n"
    end = b
    while end > a and lines[end - 1] == "":
        end -= 1
    lines[end:end] = rows
    return "\n".join(lines).rstrip("\n") + "\n"


def tidy(write: bool = True) -> dict:
    """Move finished things out of ROADMAP.md. → counts moved."""
    text, problems, plan, relay = _read(ROADMAP), _read(PROBLEMS), _read(PLAN), _read(RELAY)
    lines = text.split("\n")
    today = time.strftime("%Y-%m-%d")
    done = [it for it in items(text) if not it.get("bad") and it["mark"] in "x-"]
    closed = [r for r in index_rows(text, "## 4.") if CLOSED.match(r["status"])]
    a, b = _section(text, "## 5.")
    handled = [l for l in lines[a:b] if HANDLED.match(l)] if a >= 0 else []
    drop = {it["raw"] for it in done} | {r["raw"] for r in closed} | set(handled)
    if drop:
        kept = [l for l in lines if l not in drop]
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept))
    if done:
        plan = _insert_section_rows(plan, DONE_HEAD, [f"- {today} {it['raw'][2:]}" for it in done],
                                    "Items as they left ROADMAP.md (mark, id, who, stage, result, where). Older done items are "
                                    "in the sections above.")
    if closed:
        old = sorted(index_rows(problems, CLOSED_HEAD) + closed, key=lambda r: r["n"])
        a2, b2 = _section(problems, CLOSED_HEAD)
        if a2 >= 0:                                        # rebuild the table sorted
            pl = problems.split("\n")
            body = [l for l in pl[a2:b2] if not ROW.match(l)]
            k = next((i for i, l in enumerate(body) if l.startswith("|---")), None)
            body[k + 1:k + 1] = [r["raw"] for r in old]
            problems = "\n".join(pl[:a2] + body + pl[b2:])
        else:
            problems = _insert_section_rows(problems, CLOSED_HEAD, [r["raw"] for r in old],
                                            "Rows leave ROADMAP.md's problem index when they are fixed / won't fix "
                                            "(`python roadmap.py tidy`). The full entries are below.\n\n| P | Problem | Status |\n|---|---|---|",
                                            before="### P-1 ")
    if handled:
        relay = relay.rstrip("\n") + "\n\n" + "\n\n".join(handled) + "\n"
    if write and (done or closed or handled):
        ROADMAP.write_text(text, encoding="utf-8")
        PLAN.write_text(plan, encoding="utf-8")
        PROBLEMS.write_text(problems, encoding="utf-8")
        RELAY.write_text(relay, encoding="utf-8")
    return {"items": len(done), "problems": len(closed), "relay": len(handled)}


def queue(role: str) -> list[dict]:
    order = {s: i for i, s in enumerate(("doing", "verify", "todo", "decide", "blocked", "parked"))}
    out = [it for it in items() if not it.get("bad") and role in [w.strip() for w in it["who"].split("+")]
           and it["mark"] not in "x-"]
    return sorted(out, key=lambda it: (order.get(it["stage"], 9), it["line"]))


def show(item_id: str) -> str:
    it = next((x for x in items() if x.get("id") == item_id), None)
    plan = _read(PLAN)
    a, b = _section(plan, DETAILS_HEAD)
    det = [l for l in plan.split("\n")[a:b] if l.startswith(f"- `{item_id}`")] if a >= 0 else []
    return "\n".join(([it["raw"]] if it else [f"(no item '{item_id}' in ROADMAP.md)"]) + det)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        errs = check()
        size = len(_read(ROADMAP).encode("utf-8"))
        print("\n".join(errs) if errs else f"ok — ROADMAP.md {size} bytes ≤ {MAX_BYTES}, {len(items())} items")
        raise SystemExit(1 if errs else 0)
    if cmd == "tidy":
        n = tidy()
        print(f"moved: {n['items']} items → plan.md, {n['problems']} problem rows → problems.md, {n['relay']} relay entries → relay.md")
        errs = check()
        print("\n".join(errs) if errs else "check ok")
        return
    if cmd == "queue":
        role = sys.argv[2] if len(sys.argv) > 2 else "cloud"
        for it in queue(role):
            print(f"[{it['mark']}] {it['stage']:<7} {it['id']:<26} {it['text']}  ({it['ref']})")
        return
    if cmd == "show" and len(sys.argv) > 2:
        print(show(sys.argv[2]))
        return
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
