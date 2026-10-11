"""rule_footing (P-58 · P-49, docs/design-floor-check.md §3-A, [MoKa] 2026-10-11): on dangerous footing in a fight, a guarded step
toward wider floor — during a swing only when it can't be blocked; floor = NavMesh + walked cells; before rule_after_swing; no roll."""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))
_sys.path.insert(2, str(_pl.Path(__file__).resolve().parent.parent / "experiments"))

import json
import math
from types import SimpleNamespace

import ground
import motion
import nav
from souls import duel as D

ROOT = _pl.Path(__file__).resolve().parent.parent
RUN = "20261010_073031_burg-bonfire_r2-on3-fell-died"      # P-58: fell 4.4 m at 83.5 s off the ramp ledge, 254001 + 254002 on us
NM = motion.load_navmeshes()["m10_02_00_00"]
G = ground.Ground(NM, ground.Walked(ground.load("m10_02_00_00"), exclude=(RUN,)))   # its own steps left out


def check(what: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        raise SystemExit(1)


def frame(t: float) -> dict:
    for ln in open(ROOT / "data" / "samples" / f"{RUN}.track.jsonl", encoding="utf-8"):
        d = json.loads(ln)
        if d.get("type") == "snap" and abs(d["rt"] - t) < 0.05:
            return d
    raise KeyError(t)


def scene(d: dict, anims: dict | None = None):
    """(F, T, calls) for rule_footing at a track frame; anims overrides foes' anims by npc."""
    p = d["player"]
    me = SimpleNamespace(x=p["x"], y=p["y"], z=p["z"], gx=p["x"], gy=p["y"], gz=p["z"], hp=p["hp"], anim=p["anim"])
    chars = [SimpleNamespace(x=c["x"], y=c["y"], z=c["z"], hp=c["hp"], npc_param=c["npc"], ptr=c["ptr"],
                             anim=(anims or {}).get(c["npc"], c["anim"])) for c in d["chars"]]
    s = SimpleNamespace(player=me, hostile=lambda r: [c for c in chars if math.hypot(c.x - me.x, c.z - me.z) <= r])
    calls = []
    mv = SimpleNamespace(guard=lambda on: calls.append(("guard", on)),
                         pad=SimpleNamespace(move=lambda x, y: calls.append(("move", round(x, 2), round(y, 2)))),
                         stick_to=lambda s_, x, z, scale=1.0: (x - me.x, z - me.z))
    F = SimpleNamespace(nm=G, mv=mv, log=lambda *a: calls.append(("log",) + a), note=lambda *a: calls.append(("note", a[0])))
    T = SimpleNamespace(p=me, s=s, now=d["rt"], c=chars[0] if chars else None)
    return F, T, calls


def main() -> None:
    sleep = D.time.sleep
    D.time.sleep = lambda x: None
    D.FOOTING = True
    try:
        # 1. the P-58 ledge: danger from 2 s before the fall, the step goes east (away from the drop at x ≈ −22)
        for t in (81.48, 81.98):
            F, T, calls = scene(frame(t), anims={254001: -1, 254002: -1})
            r = D.rule_footing(F, T)
            mv = [c for c in calls if c[0] == "move" and (c[1] or c[2])]
            check(f"P-58 {t} s ledge (−20.6, 14.8), both foes idle → a guarded step east, away from the drop ({mv[:1]})",
                  r == D.CONT and ("guard", True) in calls and mv and mv[0][1] > 0.4)
        F, T, calls = scene(frame(82.49), anims={254001: 3003, 254002: -1})
        check("① axe hollow swinging a blockable 3003 → no step, left to the block", D.rule_footing(F, T) is None and not calls)
        F, T, calls = scene(frame(83.01), anims={254001: 3009, 254002: 3500})
        r = D.rule_footing(F, T)
        check(f"① … its unblockable 3009 (the P-58 hit) → step anyway ({[c for c in calls if c[0] == 'log'][:1]})",
              r == D.CONT and any(c[0] == "move" and (c[1] or c[2]) for c in calls)
              and any("막을 수 없는 공격 3009" in str(c) for c in calls))
        F, T, calls = scene(frame(80.95), anims={254001: -1, 254002: -1})
        check("80.95 s, back on wide floor (footing 0.67, no push over a drop) → nothing", D.rule_footing(F, T) is None)

        # 2. stall: same way for over FOOT_STALL_S without moving → rest FOOT_REST_S
        d = frame(81.98)
        F, T, calls = scene(d, anims={254001: -1, 254002: -1})
        D.rule_footing(F, T)
        T.now += D.FOOT_STALL_S + 0.1
        r = D.rule_footing(F, T)
        T.now += 0.5
        check("stall: same step for > 1 s with no ground gained → rests 2 s (no rubbing a wall)", r is None and D.rule_footing(F, T) is None
              and F._foot_rest > T.now)

        # 3. off: nothing; flat ramp ground: nothing
        D.FOOTING = False
        F, T, calls = scene(frame(81.98), anims={254001: -1, 254002: -1})
        check("FOOTING off (default) → rule_footing does nothing", D.rule_footing(F, T) is None and not calls)
        D.FOOTING = True
        st = nav.footing_state(G, SimpleNamespace(gx=-27.0, gy=-49.3, gz=28.5), [(-27.0, -49.3, 29.5)])
        check(f"middle of the ramp flat (−27, 28.5), a foe 1 m off → not danger (footing {st['foot']:.2f})", not st["danger"])
    finally:
        D.FOOTING = False
        D.time.sleep = sleep

    # 4. wiring
    i = D.RULES.index(D.rule_footing)
    check("② rule_footing sits right after prep_reflex, before rule_after_swing", D.RULES[i - 1] is D.prep_reflex
          and D.RULES[i + 1] is D.rule_after_swing)
    check("FOOTING is off by default (run.py --footing)", D.FOOTING is False and "--footing" in (ROOT / "run.py").read_text(encoding="utf-8"))
    import inspect
    check("rule_edge stands down when FOOTING is on", "not FOOTING" in inspect.getsource(D.rule_edge))
    check("④ no roll in rule_footing", "roll" not in inspect.getsource(D.rule_footing).split('"""')[2])
    print("footing_test: 전부 통과")


if __name__ == "__main__":
    main()
