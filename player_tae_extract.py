"""Player (c0000) animation events from the game files — what the practice room's character (sim/godot) runs on
(MoKa 2026-11-09: "더 나은 것을 원해" — the room's character should move by DSR's own timings, not made-up ones).

  python player_tae_extract.py                       → data/gamefiles/tae_c0000.json
  python player_tae_extract.py --show 690 7585 8000  print those animations' events

Reads chr/c0000*.anibnd.dcx with tae_extract's reader, keeping every event type. Full animation id = the TAE's
section × 10000 + the animation's own id (the bot reads e.g. 304000 light attack, 7585 Estus, 690 backstep,
8000 lever, 7010 ladder) — the section rule is checked by --show on those known ids, not assumed.

Event types named here (DSAnimStudio TAE.Template.DS1.xml, read in the 11-09 research):
  0 ChrActionFlag (p[0] = flag: 1 R-attack input, 4 R-cancel, 7 disable turning, 8 invincible, 11 cancel by move,
    24 super armor, 25/26 roll input / cancel, 49 disable lock-on, 73 parry possible, 94 perfect invincibility)
  1 AttackBehavior · 2 BulletBehavior · 5 CommonBehavior · 224 SetTurnSpeed (p[0] as float)
Times are seconds from the animation start ("file" evidence: not yet checked against DSAnimStudio or the game).
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import tae_extract as TE
from navmesh import GAME_DIR

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "gamefiles" / "tae_c0000.json"
FLAG_NAMES = {1: "R-attack input", 4: "R-cancel", 7: "disable turning", 8: "invincible", 11: "cancel by move",
              24: "super armor", 25: "roll input", 26: "roll cancel", 49: "disable lock-on", 73: "parry possible",
              94: "perfect invincibility"}
TYPE_NAMES = {0: "ChrActionFlag", 1: "AttackBehavior", 2: "BulletBehavior", 5: "CommonBehavior", 224: "SetTurnSpeed"}


class _All(set):
    def __contains__(self, x) -> bool:
        return True


class _Fmt(dict):
    def __missing__(self, k):
        return "<4i"


def _patch() -> None:
    """Keep every event type, read 4 × i32 for the ones tae_extract has no layout for."""
    TE.KEEP = _All()
    TE.PARAMS = _Fmt(TE.PARAMS)


def section_of(tae_name: str) -> int | None:
    """a00.tae → 0, a01.tae → 1 … (c0000_a0x anibnds hold several)."""
    stem = Path(tae_name).stem.lower()
    if stem.startswith("a") and stem[1:].isdigit():
        return int(stem[1:])
    return None


def extract() -> dict:
    from soulstruct.containers import Binder
    _patch()
    out: dict[int, dict] = {}
    files = sorted((GAME_DIR / "chr").glob("c0000*.anibnd.dcx"))
    for f in files:
        b = Binder.from_path(f)
        for ent in b.entries:
            if not ent.name.lower().endswith(".tae"):
                continue
            sec = section_of(ent.name)
            t = TE.read_tae(bytes(ent.data))
            for aid, a in t["animations"].items():
                full = aid if sec is None else sec * 10000 + aid
                for ev in a["events"]:
                    if ev["type"] == 224 and ev["p"]:
                        ev["turn"] = round(struct.unpack("<f", struct.pack("<i", ev["p"][0]))[0], 4)
                out[full] = {"file": f.name, "tae": Path(ent.name).name, "id": aid, **a}
    return {"evidence": "file", "source": "chr/c0000*.anibnd.dcx", "type_names": TYPE_NAMES, "flag_names": FLAG_NAMES,
            "animations": {str(k): v for k, v in sorted(out.items())}}


def show(d: dict, ids: list[str]) -> None:
    for i in ids:
        a = d["animations"].get(i)
        if a is None:
            print(f"{i}: 없음")
            continue
        print(f"{i}  ({a['file']} {a['tae']} id {a['id']}, ref {a.get('ref')})")
        for ev in a["events"]:
            name = TYPE_NAMES.get(ev["type"], "")
            extra = FLAG_NAMES.get(ev["p"][0], "") if ev["type"] == 0 and ev["p"] else ev.get("turn", "")
            print(f"   {ev['start']:6.3f}–{ev['end']:6.3f}  {ev['type']:4d} {name:15s} {ev['p']}  {extra}")


def main() -> None:
    if "--show" in sys.argv:
        d = json.loads(OUT.read_text(encoding="utf-8"))
        show(d, sys.argv[sys.argv.index("--show") + 1:])
        return
    d = extract()
    OUT.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    print(f"{len(d['animations'])} animations → {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
