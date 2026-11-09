"""P-131 zone 4: how["knife_from"] reaches Field.lure as lure_at (throw only from the safe spot), and the map gives it to
254011 · 254012 · 254010 in MoKa's demo order (observe 20261104_063807). Fakes only — no game, no pad.
python tests/zone4_knife_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import json
from types import SimpleNamespace as NS

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8")

from souls import missions as MS

ROOT = _pl.Path(__file__).resolve().parent.parent


def main() -> None:
    z = next(z for z in json.loads((ROOT / "data" / "burg-upper-map.json").read_text(encoding="utf-8"))["zones"] if z["n"] == 4)
    order = [k[0] for k in z["kills"]]
    assert order[:3] == [254011, 254012, 254010], order
    for k in z["kills"][:3]:
        kf = k[2]["knife_from"]
        assert kf["spot"] == z["safe"] and kf["min"] <= 7.3 and kf["max"] >= 13.5, kf
    print(f"ok  map zone 4: order {order}, knife_from = safe spot, range covers the demo's 7.3–13.5 m")

    safe = tuple(z["safe"])
    t = NS(ptr=5, npc_param=254011, x=17.8, y=-5.7, z=-103.7, hp=75, anim=-1)
    nb_ = NS(ptr=6, npc_param=254010, x=15.5, y=-5.7, z=-103.6, hp=75, anim=-1)       # 2.3 m from it → crowd
    snap = NS(player=NS(x=safe[0], y=safe[1], z=safe[2], hp=1018), hostile=lambda r: [t, nb_])
    got = {}
    m = MS.Missions.__new__(MS.Missions)
    m.log = lambda *a, **k: None
    m.zone_n = 4
    m._has = lambda item: True
    m.mv = NS(snap=lambda r: snap, find=lambda s, ptr: t)
    m.f = NS(lure=lambda ptr, spawn, nm, tag, arena=None, lure_at=None: got.update(arena=arena, lure_at=lure_at) or "lured",
             alive=lambda: True)
    r = m._lure(t, t.ptr, safe, None, "구역4-1 254011", z["kills"][0][2])
    assert r == "here" and got["lure_at"] == z["kills"][0][2]["knife_from"] and tuple(got["arena"]) == safe, (r, got)
    print("ok  _lure: crowd next to it → knife, Field.lure gets lure_at = knife_from")

    got.clear()
    m._lure(t, t.ptr, safe, None, "구역4-1 254011", {})
    assert got.get("lure_at") is None, got
    print("ok  _lure without knife_from: lure_at None (old behaviour)")


if __name__ == "__main__":
    main()
