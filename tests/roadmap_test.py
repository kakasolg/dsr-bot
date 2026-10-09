"""ROADMAP.md stays short and its problem index stays complete (CLAUDE.md). No game.

ROADMAP.md is read at the start of every session; at 307 KB (2026-10-09) it no longer fit in one read, so history moved
to docs/roadmap/ and ROADMAP.md keeps only open items. This fails when it starts growing back, or when a problem entry
in docs/roadmap/problems.md has no row in the index (or a row points at no entry)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 24_000          # ~2.5× today's size — move done items and details to docs/roadmap/ before raising this

roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
problems = (ROOT / "docs/roadmap/problems.md").read_text(encoding="utf-8")

size = len(roadmap.encode("utf-8"))
assert size <= MAX_BYTES, f"ROADMAP.md is {size} bytes (limit {MAX_BYTES}) — move [x] items and details to docs/roadmap/"

entries = {int(n) for n in re.findall(r"^### P-(\d+) ", problems, re.M)}
index = {int(n) for n in re.findall(r"^\| (\d+) \|", roadmap, re.M)}
assert entries, "no '### P-<n>' entries found in docs/roadmap/problems.md"
assert entries == index, (f"problem index out of sync — in problems.md only: {sorted(entries - index)}, "
                          f"in ROADMAP index only: {sorted(index - entries)}")

for f in ("plan.md", "relay.md", "changelog.md"):
    assert (ROOT / "docs/roadmap" / f).is_file(), f"docs/roadmap/{f} missing"

print(f"ROADMAP.md {size} bytes ≤ {MAX_BYTES}; problem index P-{min(entries)} … P-{max(entries)} ({len(entries)}) matches")
