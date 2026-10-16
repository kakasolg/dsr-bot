"""Foe attack timing from the game files — TAE events: in which animation, from when to when, each attack is live.

  python tae_extract.py                 every model in data/gamefiles/combat.json → data/gamefiles/tae.json
  python tae_extract.py c2540 c2250     only these models

Reads chr/<model>.anibnd.dcx (DSR install folder, DSR_GAME_DIR like navmesh.py): every .tae inside. soulstruct 2.3.2's
own TAE module does not import (its header struct fails with our constrata), and it raises on any unknown event type —
so this is a small reader of only what we need, laid out as soulstruct / SoulsFormats describe DSR's 64-bit TAE:

  header  "TAE " … +0x50 tae id (i32) · +0x54 animation count (i32) · +0x58 animations offset (i64)
  animation entry (16 B)  id (i64) · offset (i64) → events offset · groups offset · times offset · file offset (i64 ×4),
                          event count · group count · time count (i32 ×3)
  event (24 B)  start-time offset · end-time offset · data offset (i64 ×3); times are f32 seconds;
                data = type (i64) · offset to params (i64, = here + 8) · params

Animation ids are the ones the bot reads per foe (`Chr.anim`, e.g. 3000–3009). An animation with no events of its own
may borrow another's (file entry type 1, `ref` = the other id) — kept as `ref`, not followed.

Event types kept with their first four i32 params (`p`): 1 · 2 · 5 — in DS1 these invoke a behavior (attack / bullet /
common). Which param is the BehaviorJudgeID is not certain from documentation: soulstruct names type 1's third i32
"condition". `judge_check` counts, per type 1 and 2, how many p[2] values are judge ids of that model's foes in
combat.json (numerator / denominator, mismatch samples). A high share supports p[2] = judge id; it does not verify the
layout or the times — that is DSAnimStudio and runtime (tae_verify.py, docs/tae-verify.md). Type 5's p[2] is no judge id,
so `attacks` (judge → animation + active window) uses types 1 and 2 only. Other event types are only counted.

`python tae_extract.py --rebuild` recomputes counts / attacks / judge_check from the raw animations in tae.json (no game).

Evidence grade: "file" (LAYERS.md). Times are seconds from the animation start, as the game data says — the "active
window" of the attack behavior, not the time the player is hit.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import navmesh   # noqa: F401 — stubs the soulstruct modules whose data files the wheel lacks (see navmesh.py)
from navmesh import GAME_DIR

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUT_DIR = Path(__file__).parent / "data" / "gamefiles"
KEEP = {1: "attack", 2: "bullet", 5: "common"}          # DS1 behavior-invoking event types (see docstring)
JUDGE_PARAM = 2                                          # p[2] = BehaviorJudgeID? — checked by judge_check
JUDGE_TYPES = (1, 2)                                     # event types whose p[2] is read as a judge id


class TAEError(ValueError):
    pass


def _q(b: bytes, o: int) -> int:
    return struct.unpack_from("<q", b, o)[0]


def _i(b: bytes, o: int) -> int:
    return struct.unpack_from("<i", b, o)[0]


def _f(b: bytes, o: int) -> float:
    return struct.unpack_from("<f", b, o)[0]


def read_tae(b: bytes) -> dict:
    """{"tae_id", "animations": {anim_id: {"events": [...], "other_types": {type: n}, "ref": id | None}}}."""
    if b[:4] != b"TAE ":
        raise TAEError("not a TAE file")
    if b[7] == 0 and _i(b, 8) == 0x1000B:
        return _read_tae32(b)
    if b[7] != 0xFF:
        raise TAEError("not a 64-bit TAE (DSR)")
    version = _i(b, 8)
    if version != 0x1000C:
        raise TAEError(f"unexpected TAE version 0x{version:X}")
    tae_id, count, anims_off = _i(b, 0x50), _i(b, 0x54), _q(b, 0x58)
    if not (0 <= count < 100000) or not (0 < anims_off < len(b)):
        raise TAEError(f"bad header: count {count}, animations at 0x{anims_off:X}")
    anims = {}
    for k in range(count):
        e = anims_off + 16 * k
        anim_id, a = _q(b, e), _q(b, e + 8)
        events_off, file_off = _q(b, a), _q(b, a + 0x18)
        n_events = _i(b, a + 0x20)
        events, other = [], {}
        for j in range(n_events):
            h = events_off + 24 * j
            start, end, data = _f(b, _q(b, h)), _f(b, _q(b, h + 8)), _q(b, h + 16)
            etype = _q(b, data)
            if etype in KEEP:
                p = list(struct.unpack_from("<4i", b, data + 16)) if data + 32 <= len(b) else []
                events.append({"type": etype, "start": round(start, 4), "end": round(end, 4), "p": p})
            else:
                other[etype] = other.get(etype, 0) + 1
        ref = None
        if not events and 0 < file_off < len(b) and _q(b, file_off) == 1:
            ref = _i(b, file_off + 0x18)
        anims[int(anim_id)] = {"events": sorted(events, key=lambda ev: (ev["start"], ev["type"])),
                               "other_types": {str(t): n for t, n in sorted(other.items())}, "ref": ref}
    return {"tae_id": tae_id, "animations": anims}


def _read_tae32(b: bytes) -> dict:
    """32-bit TAE (version 0x1000B) — what DSR's chr/*.anibnd.dcx actually hold (10-16 [win]: all 66 models).

    Same fields as the 64-bit reader, every offset an i32: animation entry {id, data} (8 bytes), animation data
    {n_events, event_headers, …, file @0x18}, event header {start, end, data} (12 bytes), event data {type, params}.
    Borrowed animation: file {1, …, …, ref id @0xC}."""
    tae_id, count, anims_off = _i(b, 0x50), _i(b, 0x54), _i(b, 0x58)
    if not (0 <= count < 100000) or not (0 < anims_off < len(b)):
        raise TAEError(f"bad header: count {count}, animations at 0x{anims_off:X}")
    anims = {}
    for k in range(count):
        e = anims_off + 8 * k
        anim_id, a = _i(b, e), _i(b, e + 4)
        n_events, events_off, file_off = _i(b, a), _i(b, a + 4), _i(b, a + 0x18)
        events, other = [], {}
        for j in range(n_events):
            h = events_off + 12 * j
            start, end, data = _f(b, _i(b, h)), _f(b, _i(b, h + 4)), _i(b, h + 8)
            etype, params = _i(b, data), _i(b, data + 4)
            if etype in KEEP:
                p = list(struct.unpack_from("<4i", b, params)) if params + 16 <= len(b) else []
                events.append({"type": etype, "start": round(start, 4), "end": round(end, 4), "p": p})
            else:
                other[etype] = other.get(etype, 0) + 1
        ref = None
        if not events and 0 < file_off < len(b) and _i(b, file_off) == 1:
            ref = _i(b, file_off + 0xC)
        anims[anim_id] = {"events": sorted(events, key=lambda ev: (ev["start"], ev["type"])),
                          "other_types": {str(t): n for t, n in sorted(other.items())}, "ref": ref}
    return {"tae_id": tae_id, "animations": anims}


def model_animations(binder_entries) -> dict:
    """All .tae files of one anibnd merged: {anim_id: entry}; the tae file name is kept per animation."""
    out = {}
    for ent in binder_entries:
        if not ent.name.lower().endswith(".tae"):
            continue
        t = read_tae(bytes(ent.data))
        for aid, a in t["animations"].items():
            out[aid] = {"tae": ent.name, **a}
    return dict(sorted(out.items()))


def attacks_by_judge(anims: dict, types=JUDGE_TYPES) -> dict:
    """{judge id: [{anim, type, active_start, active_end}]} from events of `types` only (type 5 'common' carries no
    judge id in p[2] — its 0 / 1 / 5 / 16 values are something else).

    active_start / active_end = the TAE event's window: when the game *runs* that attack behavior (hitbox live). Not the
    time the player is hit — that is a runtime fact (tae_runtime_probe.py), kept apart on purpose."""
    out: dict[int, list] = {}
    for aid, a in anims.items():
        for ev in a["events"]:
            if ev["type"] in types and len(ev["p"]) > JUDGE_PARAM:
                out.setdefault(ev["p"][JUDGE_PARAM], []).append(
                    {"anim": int(aid), "type": KEEP[ev["type"]], "active_start": ev["start"], "active_end": ev["end"]})
    return {str(j): v for j, v in sorted(out.items())}


def judge_check(anims: dict, known: set[int]) -> dict:
    """Per event type 1 / 2: how many p[JUDGE_PARAM] values are judge ids of this model in combat.json (numerator /
    denominator) and the values that are not (mismatch samples). A high share supports p[2] = BehaviorJudgeID — it does
    not by itself prove the layout or the times (docs/tae-verify.md)."""
    out = {}
    for t in JUDGE_TYPES:
        rows = [(int(aid), ev["p"][JUDGE_PARAM]) for aid, a in anims.items() for ev in a["events"]
                if ev["type"] == t and len(ev["p"]) > JUDGE_PARAM]
        miss = [(aid, v) for aid, v in rows if v not in known]
        out[KEEP[t]] = {"n": len(rows), "in_combat_json": len(rows) - len(miss),
                        "share": round((len(rows) - len(miss)) / len(rows), 3) if rows else None,
                        "mismatch": [{"anim": aid, "value": v} for aid, v in miss[:20]]}
    return out


def counts(anims: dict) -> dict:
    by_type = {}
    for a in anims.values():
        for ev in a["events"]:
            by_type[KEEP[ev["type"]]] = by_type.get(KEEP[ev["type"]], 0) + 1
    return {"animations": len(anims), "borrowed": sum(1 for a in anims.values() if a.get("ref") is not None),
            "events": by_type, "other_events": sum(sum(a["other_types"].values()) for a in anims.values())}


def summarize(model: str, anims: dict, known: set[int]) -> dict:
    """Everything derived from the raw animations — rerun offline with `--rebuild` (no game files needed)."""
    return {"model": model, "status": "parsed", "counts": counts(anims),
            "animations": {str(k): v for k, v in anims.items()},
            "attacks": attacks_by_judge(anims), "judge_check": judge_check(anims, known)}


def models_from_combat(path: Path) -> dict[str, set[int]]:
    """{model: judge ids of every foe with that model} from combat.json."""
    d = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, set[int]] = {}
    for f in d["foes"].values():
        m = f.get("model")
        if m:
            out.setdefault(m, set()).update(int(j) for j in f.get("behaviors", {}))
    return out


def extract(model: str, entries, known: set[int]) -> dict:
    return summarize(model, model_animations(entries), known)


def line(m: dict) -> str:
    c, j = m["counts"], m["judge_check"]
    ev = " ".join(f"{k} {n}" for k, n in sorted(c["events"].items()))
    jc = " · ".join(f"{k} {v['in_combat_json']}/{v['n']}" for k, v in j.items() if v["n"])
    return f"{m['model']}: 애니 {c['animations']} (빌림 {c['borrowed']}), 이벤트 {ev or '-'} (그 밖 {c['other_events']}), judge {jc or '-'}"


def write(path: Path, out: dict, failed: dict) -> None:
    data = {"evidence": "file", "source": "chr/<model>.anibnd.dcx (.tae)", "judge_param": JUDGE_PARAM,
            "judge_types": list(JUDGE_TYPES), "times": "attacks: active_start / active_end = TAE event window (s), not hit time",
            "counts": {"models": len(out), "failed": len(failed)}, "failed": failed, "models": out}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for m in out.values():
        print(line(m))
    num = sum(v["in_combat_json"] for m in out.values() for v in m["judge_check"].values())
    den = sum(v["n"] for m in out.values() for v in m["judge_check"].values())
    print(f"모델 {len(out)} 파싱, 실패 {len(failed)} {list(failed)[:5]} — judge {num}/{den} → {path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("models", nargs="*", help="e.g. c2540 (default: every model in combat.json)")
    ap.add_argument("--combat", type=Path, default=OUT_DIR / "combat.json")
    ap.add_argument("--out", type=Path, default=OUT_DIR / "tae.json")
    ap.add_argument("--rebuild", action="store_true",
                    help="no game files: recompute counts / attacks / judge_check from the raw animations already in --out")
    a = ap.parse_args()
    judges = models_from_combat(a.combat) if a.combat.exists() else {}
    if a.rebuild:
        old = json.loads(a.out.read_text(encoding="utf-8"))
        out = {m: summarize(m, {int(k): v for k, v in d["animations"].items()}, judges.get(m, set()))
               for m, d in old["models"].items() if not a.models or m in a.models}
        write(a.out, out, old.get("failed", {}))
        return
    from soulstruct.containers import Binder
    models = a.models or sorted(judges)
    if not models:
        raise SystemExit("모델 없음 — combat.json 이 없으면 모델 이름을 주세요 (예: c2540)")
    out, failed = {}, {}
    for m in models:
        path = GAME_DIR / "chr" / f"{m}.anibnd.dcx"
        try:
            out[m] = extract(m, Binder.from_path(path).entries, judges.get(m, set()))
        except Exception as ex:            # one bad file must not stop the rest — reported below and in the json
            failed[m] = f"{type(ex).__name__}: {ex}"
    write(a.out, out, failed)


if __name__ == "__main__":
    main()
