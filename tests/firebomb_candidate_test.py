"""firebomb-candidate (ROADMAP, [MoKa] 10-12 · M1013-03 "앞으로 화염병 위주로 플레이 해봐"): firebombs are a choice next to knife /
melee whenever some are held in a quick slot — the lure's first throw at a sleeping foe on our level 5–10.1 m off, and the
burg-upper group / ledge throws (no longer only with --throw, no 2-per-call stock limit). None held = as before.
Offline: fake Field / Moves (tests/field_fakes.py). Not a game check."""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(1, str(_pl.Path(__file__).resolve().parent))

from types import SimpleNamespace as NS

from field_fakes import World, make_field
from souls import field as F
from souls import missions as MS
from souls import moves as M


def check(what: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        raise SystemExit(1)


class Line:
    def find_path(self, a, b):
        return [tuple(a), tuple(b)]


def rig(dist: float, dy: float = 0.0, bombs: int = 5, quick=(M.ITEM_KNIFE, M.ITEM_FIREBOMB), fb_ok=True, on=True):
    """Field.lure from where we stand (lure_at spot = here) at a sleeping 254010 `dist` m ahead."""
    w = World(player=(0.0, 0.0, 0.0))
    w.add(7, 0x1007, 254010, (0.0, dy, dist))
    f = make_field(w)
    del f.lure
    f.firebomb = on
    f._asleep = lambda ptr, hold=0.4: True
    f._settle = lambda spot, tol=None, tries=10: 0.0
    f.events = lambda *a, **k: None
    f.mv.tm.goods_count = lambda item: {M.ITEM_KNIFE: 20, M.ITEM_FIREBOMB: bombs}.get(item, 0)
    f.mv.tm.quick_items = lambda: list(quick)
    thrown = []

    def knife(ptr, **kw):
        thrown.append("knife")
        return {"ok": True, "locked": True, "hit": 30, "woke": True}

    def bomb(ptr, watch=2.2):
        thrown.append("firebomb")
        return {"ok": fb_ok, "locked": fb_ok, "hit": 75 if fb_ok else None, "woke": fb_ok,
                "why": None if fb_ok else "락온 안 됨"}
    f.mv.throw_knife, f.mv.throw_firebomb = knife, bomb
    f.walk_to = lambda goal, nm_, tag, mode="walk", tol=None, done=None: "arrived"
    r = F.Field.lure(f, 7, [0.0, dy, dist], Line(), "#7", lure_at={"spot": (0.0, 0.0, 0.0), "min": 0.0, "max": 15.0})
    return r, thrown, f


r, t, f = rig(7.0)
check(f"7 m, same level, firebombs in the quick slot → the lure opens with a firebomb ({t}, {r})", t[:1] == ["firebomb"])
check("… and it is logged", any("화염병으로 유인" in line for line in f.logs))
r, t, f = rig(7.0, fb_ok=False)
check(f"firebomb not thrown (no lock) → knife on the same try ({t})", t[:2] == ["firebomb", "knife"])
r, t, f = rig(12.0)
check(f"12 m (past FB_OPEN_MAX {F.FB_OPEN_MAX}) → knife as before ({t})", t[:1] == ["knife"])
r, t, f = rig(4.0)
check(f"4 m (inside FB_OPEN_MIN {F.FB_OPEN_MIN}) → knife ({t})", t[:1] == ["knife"])
r, t, f = rig(7.0, dy=-2.5)
check(f"2.5 m below (MoKa: 1.7–3.1 m below did 6) → knife ({t})", t[:1] == ["knife"])
r, t, f = rig(7.0, bombs=0)
check(f"no firebombs held → knife, as before ({t})", t[:1] == ["knife"])
r, t, f = rig(7.0, quick=(M.ITEM_KNIFE,))
check(f"firebombs held but not in a quick slot → knife ({t})", t[:1] == ["knife"])
r, t, f = rig(7.0, on=False)
check(f"--no-firebomb (Field.firebomb False) → knife ({t})", t[:1] == ["knife"])


# ── burg-upper group / ledge throws: on whenever Field.has_firebomb, no 2-per-call limit ───────────────────────────────
def mrig(bombs: int, on=True, throw=False):
    w = World(player=(0.0, -10.0, 0.0))
    f = make_field(w)
    f.firebomb = on
    f.events = lambda *a, **k: None
    f.mv.tm.goods_count = lambda item: {M.ITEM_FIREBOMB: bombs["n"]}.get(item, 0)
    f.mv.tm.quick_items = lambda: [M.ITEM_FIREBOMB]
    m = MS.Missions.__new__(MS.Missions)
    m.f, m.mv, m.log, m.throw = f, f.mv, f.log, throw
    thrown = []

    def bomb(ptr, watch=2.2):
        thrown.append(ptr)
        bombs["n"] -= 1
        return {"ok": True, "dist": 6.0, "locked": True, "hit": 20}
    m.mv.throw_firebomb = bomb
    two = [NS(npc_param=254010, ptr=61, x=0.0, y=-10.0, z=6.0, hp=75, anim=3000),
           NS(npc_param=254011, ptr=62, x=0.0, y=-10.0, z=8.0, hp=75, anim=3000)]
    m.mv.snap = lambda r=5.0: NS(player=NS(x=0.0, y=-10.0, z=0.0, hp=742, max_hp=742), hostile=lambda rr: two)
    return m, thrown


m, t = mrig({"n": 5})
m._firebomb_group("t")
check(f"two coming, 5 firebombs, no --throw → all 5 at the nearest ({len(t)})", len(t) == 5 and set(t) == {61})
m, t = mrig({"n": 0})
m._firebomb_group("t")
check("no firebombs → nothing thrown", t == [])
m, t = mrig({"n": 5}, on=False)
m._firebomb_group("t")
check("--no-firebomb → nothing thrown, even with stock", t == [])
m, t = mrig({"n": 50})
m._firebomb_group("t")
check(f"one call stops at FB_MAX_THROWS {MS.FB_MAX_THROWS} if they keep coming ({len(t)})", len(t) == MS.FB_MAX_THROWS)
print("firebomb_candidate_test: 전부 통과")
