"""drops.DropBook: which drop records are still worth walking to, and how window results are matched. No game.

  python tests/drops_test.py

Cases from 2026-11-01 (MoKa: "획득 후 잔존 기록을 다시 목표로 잡는 문제", "대응 관계가 불명확하면 임의로 모두 완료 처리하지 마"):
loop10 r03 (three drops within 1 m, A took a neighbour, closing A took another), r03·r07 (corpse fell out of the map).
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import struct
import sys
from types import SimpleNamespace as NS

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import drops as D

SHORTSWORD, AXE, LONGSWORD, ARMOR = 200000, 701000, 201000, 0x10000000 | 521000
ME = (-30.0, -49.3, 28.0)


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        raise SystemExit(1)


def rec(addr, pos, item, cnt=1, owner=0x1C000000):
    return D.Rec(addr, pos, item, cnt, owner)


def book_after_kill(recs, base_recs=(), owners=()):
    """Baseline from base_recs, then owners die, then recs show up."""
    b = D.DropBook()
    b.observe(list(base_recs), 0.0)
    b.observe_chars([NS(ptr=o, hp=100) for o in owners], 1.0)
    b.observe_chars([NS(ptr=o, hp=0) for o in owners], 2.0)
    new = b.observe(list(base_recs) + list(recs), 3.0)
    return b, new


# ── record parsing (bytes laid out as in the 11-01 records) ──
def blob(pos, item, cnt, back):
    b = bytearray(0x80)
    struct.pack_into("<3f", b, 0, *pos)
    struct.pack_into("<IiI", b, 0x0C, 0, -1, D.MARK)
    struct.pack_into("<IiI", b, 0x20, item, -1, cnt)
    struct.pack_into("<Q", b, 0x68, back)
    return bytes(b)


buf = b"\0" * 0x40 + blob((-30.25, -49.31, 28.55), 1406000, 1, 0x1C43CF00 + 0x390) + b"\0" * 0x40
rs = D.find_records(buf, 0x20000000)
check("record found with item, count, position, owner = back − 0x390",
      len(rs) == 1 and rs[0].addr == 0x20000040 and rs[0].item == 1406000 and rs[0].cnt == 1 and rs[0].owner == 0x1C43CF00
      and abs(rs[0].pos[0] + 30.25) < 1e-4)
check("bad category / count rejected", D.find_records(blob((0, 0, 0), 0x30000000 | 5, 1, 0) + b"\0" * 0x40, 0) == []
      and D.find_records(blob((0, 0, 0), 5, 0, 0) + b"\0" * 0x40, 0) == [])

# ── window list ──
mem = {0x21000: struct.pack("<QIII", 0x21020, 0x10000000, 521000, 1), 0x21020: struct.pack("<QIII", 0, 0, 701000, 1)}
raw = lambda p, n: mem.get(p)
check("walk_nodes reads head first", D.walk_nodes(raw, 0x21000) == [(0x10000000 | 521000, 1), (701000, 1)])
check("walk_nodes: empty list = [], unreadable = None", D.walk_nodes(raw, 0) == [] and D.walk_nodes(raw, 0x22000) is None
      and D.walk_nodes(raw, None) is None)
check("new_nodes: multiset difference (window still open from the last pickup)",
      D.new_nodes([(AXE, 1)], [(SHORTSWORD, 1), (AXE, 1)]) == [(SHORTSWORD, 1)] and D.new_nodes(None, []) is None)

# ── 1. a picked drop's record stays in memory → not chosen again ──
a = rec(0xA0, (-30.2, -49.3, 28.6), ARMOR)
b, new = book_after_kill([a], owners=[a.owner])
cl = b.select(ME)
r = b.visited(cl, [(ARMOR, 1)], ME)
b.observe([a], 10.0)                                     # the record is still there after the pickup
check("1 taken drop (record still in memory) is not selected again", r["taken"] and b.select(ME) == [])
b2 = D.DropBook()
b2.observe([a], 0.0)
b2.observe([a], 1.0)
check("1 records already there at the baseline are never candidates", b2.select(ME) == [])

# ── 2. two close drops, the other one came ──
s = rec(0xB0, (-31.0, -49.6, 30.0), SHORTSWORD, owner=0x1C1)
x = rec(0xC0, (-31.4, -49.6, 30.3), AXE, owner=0x1C2)
b, _ = book_after_kill([s, x], owners=[s.owner, x.owner])
cl = b.select((-31.0, -49.6, 29.5))
check("2 close drops come as one cluster", {d.rec.addr for d in cl} == {0xB0, 0xC0})
r = b.visited(cl, [(AXE, 1)], (-31.0, -49.6, 29.5))
st = {d.rec.addr: d.state for d in b.drops.values()}
check("2 the axe (not the aimed shortsword) is taken; shortsword stays pending", st == {0xB0: "pending", 0xC0: "taken"})
check("2 next cluster = the shortsword only", [d.rec.addr for d in b.select((-31.0, -49.6, 29.5))] == [0xB0])

# ── 3. partial: two in the cluster, one press gave one; same-item twins stay undecided ──
l1 = rec(0xD0, (-29.0, -49.3, 25.7), LONGSWORD, owner=0x1D1)
l2 = rec(0xD8, (-29.3, -49.3, 25.9), LONGSWORD, owner=0x1D2)
h = rec(0xE0, (-29.2, -49.3, 25.5), ARMOR, owner=0x1D3)
b, _ = book_after_kill([l1, l2, h], owners=[l1.owner, l2.owner, h.owner])
me = (-29.1, -49.3, 26.4)
r = b.visited(b.select(me), [(LONGSWORD, 1)], me)
st = {d.rec.addr: d.state for d in b.drops.values()}
check("3 one longsword came, two longsword records → neither marked taken (ambiguous)",
      st == {0xD0: "pending", 0xD8: "pending", 0xE0: "pending"} and r["ambiguous"] and all(b.drops[d.ident].ambiguous for d in (l1, l2)))
r = b.visited(b.select(me), [(ARMOR, 1)], me)
check("3 the armour came next → armour taken, longswords still pending", b.drops[h.ident].state == "taken"
      and b.drops[l1.ident].state == b.drops[l2.ident].state == "pending")

# ── 4. window unreadable → nothing taken, tries counted ──
b, _ = book_after_kill([a], owners=[a.owner])
r = b.visited(b.select(ME), None, ME)
d = b.drops[a.ident]
check("4 unreadable window: not taken, one try used", d.state == "pending" and d.tries == 1 and not r["taken"])

# ── 5. same address reused for another drop (other bytes) → a new candidate ──
b, _ = book_after_kill([a], owners=[a.owner])
b.visited(b.select(ME), [(ARMOR, 1)], ME)
a2 = rec(0xA0, (-25.0, -48.0, 27.0), AXE, owner=0x1C9)
b.observe_chars([NS(ptr=0x1C9, hp=50)], 11.0)
b.observe_chars([NS(ptr=0x1C9, hp=0)], 12.0)
b.observe([a2], 13.0)
check("5 reused address with other bytes = new candidate", [d.rec.item for d in b.select(ME)] == [AXE])

# ── 6. new run / rest: earlier exclusions don't carry over wrongly ──
b, _ = book_after_kill([a], owners=[a.owner])
b.visited(b.select(ME), [(ARMOR, 1)], ME)
b.reset("rest at Firelink")
b.observe([a], 20.0)                                     # baseline again: the stale record
check("6 after reset the stale record is baseline, not a candidate", b.select(ME) == [] and not b.drops)
b.observe_chars([NS(ptr=a.owner, hp=100)], 21.0)
b.observe_chars([NS(ptr=a.owner, hp=0)], 22.0)
b.observe([a], 23.0)                                     # same bytes, owner died again — stale or new drop, can't tell
cl = b.select(ME)
check("6 same bytes + owner died after the baseline → one visit allowed", len(cl) == 1 and cl[0].max_tries == D.REUSED_TRIES)
b.visited(cl, [], ME)
check("6 …and given up after that one empty visit", b.drops[a.ident].state == "failed" and b.select(ME) == [])
b3, _ = book_after_kill([a], owners=[a.owner])
check("6 a new DropBook (new run) knows nothing of the last run's taken", [d.rec.addr for d in b3.select(ME)] == [0xA0])

# ── 7. approach failures don't retry forever; unreachable = gone ──
b, _ = book_after_kill([a], owners=[a.owner])
n = 0
while b.select(ME) and n < 20:
    b.visited(b.select(ME), None, ME, why="approach timeout")
    n += 1
check("7 approach failure: given up after MAX_TRIES visits", n == D.MAX_TRIES and b.drops[a.ident].state == "failed")
f = rec(0xF0, (-131.7, -2496.8, -39.3), 0x40000000 | 292, owner=0x1F1)
b, _ = book_after_kill([f], owners=[f.owner])
check("7 record fallen out of the map → gone, not visited", b.select(ME, reachable=lambda p: p[1] > -100) == []
      and b.drops[f.ident].state == "gone")

# ── unexpected window item (no candidate) is logged, nothing marked ──
b, _ = book_after_kill([a], owners=[a.owner])
r = b.visited(b.select(ME), [(0x40000000 | 330, 6)], ME)
check("unexpected item logged, drop not taken", r["unexpected"] == [(0x40000000 | 330, 6)] and b.drops[a.ident].state == "pending")

print("drops_test: all ok")
