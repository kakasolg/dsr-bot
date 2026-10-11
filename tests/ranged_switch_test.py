"""P-56: 'ranged first' target switching (duel._sense) on the ramp ledge 2:1 — only real throwers (foes.Foe.thrower) pull us
away, and any awake foe within MELEE_BUSY_R keeps us on what is in front. Before, both checks read foes.ranged, which the axe
hollow 254001 carries for lure / waiting: of 42 'ranged first' switches in the 10-10..10-11 seg 1-2 runs, 27 went to the axe
hollow and 9 left a target < 2 m, turning 90–160° with both foes on us (060959 on#1 71.7 s: to 254002 4.4 m, 254001 at 1.4 m)."""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))

import duel_golden_test as G

BASE = dict(sp=90, low=False, back=False, room=False, other=False, wait=False, style="guard", reflex=False)


def check(what: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        raise SystemExit(1)


def switches(sc: dict, extra: list) -> list:
    """Run one golden-style duel with extra foes [(ptr, npc, (x, y, z), anim)] → its 'ranged first' log lines."""
    def hook(mv, w):
        for ptr, npc, pos, anim in extra:
            w.add(ptr, 0x1000 + ptr, npc, pos, anim=anim)
    trace = G.run(dict(BASE, **sc), mv_hook=hook)
    return [t[1] for t in trace if t[0] == "log" and "원거리부터" in t[1]]


def main() -> None:
    y = -49.4
    got = switches(dict(foe="firebomb", anim=3003, h=1.4), [(5, 254002, (0.0, y, 4.4), 3008)])
    check(f"060959 71.7 s: axe hollow 254001 swinging at 1.4 m, firebomb 254002 throwing at 4.4 m → stay on the axe hollow {got}",
          got == [])
    got = switches(dict(foe="hollow", anim=-1, h=4.9), [(5, 254001, (0.0, y, 2.3), 3003)])
    check(f"axe hollow 254001 swinging at 2.3 m is not a thrower → no 'ranged first' to it {got}", got == [])
    got = switches(dict(foe="hollow", anim=3003, h=0.9), [(5, 254002, (0.0, y, 5.8), 3008)])
    check(f"a hollow on us at 0.9 m, a thrower at 5.8 m → stay {got}", got == [])
    got = switches(dict(foe="hollow", anim=-1, h=7.0), [(5, 254002, (0.0, y, 5.9), 3008)])
    check(f"nobody within 2 m, firebomb 254002 throwing at 5.9 m → still 'ranged first' (MoKa: the shooter first) {got}",
          len(got) == 1 and "254002" in got[0])
    got = switches(dict(foe="hollow", anim=-1, h=7.0), [(5, 255002, (0.0, y, 12.0), 3000)])
    check(f"… and the crossbowman 255002 at 12 m {got}", len(got) == 1 and "255002" in got[0])
    print("ranged_switch_test: 전부 통과")


if __name__ == "__main__":
    main()
