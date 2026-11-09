"""Ledge firebomb line (M1109-07, MoKa 2026-11-09): a burg-upper zone fight doesn't walk in toward a target that stands in a
ledge firebomb hollow's line — 20261109_022350 zone 2 walked 22 m to 255001 under the ledge 254012 (−111, −89).
Geometry from that run and the map data only (no game). python tests/ledge_fire_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

from types import SimpleNamespace as NS

from souls import missions as MI


def check(msg: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        raise SystemExit(1)


def pt(x, y, z, npc=0, hp=85):
    return NS(x=x, y=y, z=z, npc_param=npc, hp=hp, ptr=id((x, y, z)))


def main() -> None:
    led = MI.UPPER_IGNORE
    check("zone 2 ledge firebomb (0.2, −4.0, −90.2) is in the ignore list", (0.2, -4.0, -90.2) in led)
    safe = pt(-7.0, -10.0, -75.5)                          # 145.2 s: where the bot stood before walking in
    spear = pt(-1.3, -10.1, -95.4, 255001)                 # 255001 at its spawn, 22 m away
    q = MI.ledge_fire_block(safe, spear, led)
    check(f"walking from the safe spot to 255001 at its spawn → blocked by ledge {q}", q is not None)
    check("same target already close (3 m) — a fight in progress, not a walk in → allowed",
          MI.ledge_fire_block(pt(-2.5, -10.0, -92.8), spear, led) is None)
    came = pt(-7.6, -10.0, -69.5, 255001)                  # it came out past the safe spot (15+ m from every ledge)
    check("target that came out of the line (≥ 14 m from every ledge) → allowed", MI.ledge_fire_block(safe, came, led) is None)
    check("all ledge hollows dead → allowed", MI.ledge_fire_block(safe, spear, led, dead=set(led)) is None)
    check("me up on the ledge level (not 3 m below) → not counted", MI.ledge_fire_block(pt(-7.0, -2.0, -75.5), spear, led) is None)
    deeper = pt(-1.0, -10.0, -93.0)                         # already deeper in the line than the target → no walk *into* it
    check("I am already closer to the ledge than the target → allowed (backing out is not walking in)",
          MI.ledge_fire_block(deeper, pt(-7.0, -10.0, -84.0, 255001), led) is None)
    zone5 = pt(36.3, -9.1, -107.0, 255000)                  # zone 5 shield soldier, far from the ledges
    check("a zone 5 foe far from the ledges → allowed", MI.ledge_fire_block(pt(31.5, -7.5, -99.5), zone5, led) is None)

    dead_sn = NS(player=safe, chars=[pt(0.3, -4.0, -90.0, 254012, hp=0)])
    check("dead_ledges: a dead 254012 next to the zone 2 ledge spot marks it", MI.dead_ledges(dead_sn) == {(0.2, -4.0, -90.2)})

    logs = []
    m = object.__new__(MI.Missions)
    m.log = logs.append
    may = m._ledge_fire_guard("구역2-1 255001")
    sn = NS(player=safe, chars=[])
    check("guard: refuses the walk in, says why once", may(spear, sn) is False and may(spear, sn) is False and len(logs) == 1
          and "M1109-07" in logs[0])
    check("guard: allows it once the target came out", may(came, sn) is True)
    print("  " + logs[0])
    print("ledge_fire_test: 전부 통과")


if __name__ == "__main__":
    main()
