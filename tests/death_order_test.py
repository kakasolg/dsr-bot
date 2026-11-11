"""P-68: a dead character gets no more actions. 10-11 zone 5: HP 0 at 299.97 s, yet for 10 s the bot lured, fought ('cancel'),
recovered (escape pick, two light attacks) and rolled — the roll's stick_to hit cam_yaw None (death/loading) → TypeError.
Fake worlds, no game.  python tests/death_order_test.py

Checks:
  · duel._sense: HP 0 and cancel() true at once → 'me_dead' (it used to check cancel first → 'cancel')
  · Field.recover: HP 0 → False at once, no roll / back-off / attack
  · Moves.stick_to: no camera yaw → stick (0, 0) instead of an exception
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from field_fakes import World, make_field
from souls import duel as D
from souls import field as F
from souls import moves as M
from souls import style as style_


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def main() -> None:
    world = World(hp=0)
    world.add(3, 103, 255001, (0.0, -49.4, 1.2), anim=3003)
    f = make_field(world)
    Fi = D.Fight(f.mv, None, 3, None, print, 45.0, 0.25, lambda: True, None, None, None, style_.of("guard"),
                 False, 0, None, None)
    r = D._sense(Fi)
    check(f"duel._sense: HP 0 + cancel() → me_dead (got {getattr(r, 'result', r)})", getattr(r, "result", None) == "me_dead")

    world.player.hp = 793
    r = D._sense(Fi)
    check("duel._sense: alive + cancel() → cancel (unchanged)", getattr(r, "result", None) == "cancel")

    world.player.hp = 0
    acted = []
    f.mv.roll_toward = lambda *a, **k: acted.append("roll")
    f.escape_choice = lambda *a, **k: acted.append("escape_choice")
    f.heal = lambda *a, **k: acted.append("heal")
    ok = F.Field.recover(f, "구역5-1 255000: 같이 온 놈 cancel", None)
    check(f"Field.recover: HP 0 → False, nothing done ({acted})", ok is False and acted == [])

    mv = M.Moves.__new__(M.Moves)
    s = NS(player=NS(x=0.0, z=0.0), cam_yaw=None)
    check("Moves.stick_to: cam_yaw None → (0, 0)", mv.stick_to(s, 3.0, 4.0) == (0.0, 0.0))
    s.cam_yaw = 0.0
    check("Moves.stick_to: with a camera → a real direction", mv.stick_to(s, 3.0, 4.0) != (0.0, 0.0))
    print("death_order_test: 전부 통과")


if __name__ == "__main__":
    main()
