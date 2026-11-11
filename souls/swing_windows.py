"""When a foe's swing is live: animation id → (active start, active end) in seconds from the swing's start (P-121).

From data/gamefiles/tae.json (tae_extract.py, type 1 attack events) and combat.json (NpcParam → model). Checked against
DSAnimStudio for c2540 (level 2, docs/tae-verify.md); not yet checked against the running game. Only the first live
window of an animation is used — a later one in the same swing (rare in c2540) is the follow-up the bot doesn't plan for.

  window(npc, anim) → (start, end) | None
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def _tables() -> tuple[dict, dict]:
    try:
        tae = json.loads((ROOT / "data/gamefiles/tae.json").read_text(encoding="utf-8"))["models"]
        foes = json.loads((ROOT / "data/gamefiles/combat.json").read_text(encoding="utf-8"))["foes"]
    except (OSError, KeyError, ValueError):
        return {}, {}
    return tae, {k: v.get("model") for k, v in foes.items()}


def model_of(npc) -> str | None:
    return _tables()[1].get(str(npc))


@lru_cache(maxsize=512)
def window(npc, anim) -> tuple[float, float] | None:
    tae, models = _tables()
    m = tae.get(models.get(str(npc)) or "", {}).get("animations", {})
    a = m.get(str(anim))
    if a is not None and not a.get("events") and a.get("ref") is not None:
        a = m.get(str(a["ref"]))
    if not a:
        return None
    ev = sorted((e["start"], e["end"]) for e in a.get("events", []) if e.get("type") == 1)
    return ev[0] if ev else None
