"""Enemy drops after death — find the drop records, keep which ones are still worth walking to, and match what the item-get
window actually gave against them. No movement or input here: the caller walks, presses A and reads the window, then reports.

  find_records(buf, base)   drop records in one memory block (pure)
  scan(tm)                  find_records over every committed read-write region (read-only, ~1.5 s)
  itemget_nodes(tm)         the item-get window's list [(item, amount)] — None if unreadable
  DropBook                  per-run state: baseline, owner deaths, candidates, taken / gone / failed, reset

Record shape (2026-11-01, Firelink ramp, 11 drops): pos f32×3 · 0 · -1 · 0.4f · ? · item u32 (category bits | id) · -1 · count,
qword at pos+0x68 → owner chr + 0x390 (11/11). Item-get list: [base + 0x1C891A8] + 0x8, nodes (next, +0x8 cat, +0xC id,
+0x10 amount) — DSAP offsets, read on module base 0x140000000 only.

── 알려진 한계 (2026-11-01 관측 기준) ──────────────────────────────
 · 기록 자체에는 "주웠음" 필드를 못 찾았다: dropwatch01에서 주운 뒤 pos·item·count·+0x20·+0x2c 그대로(기록 0x60 바이트만 봄).
   바뀐 것은 원소 1개짜리 목록 0x1cd75240/48의 head/tail(→0) 하나뿐(1회, 정적 루트 못 찾음). 그래서 "메모리에 있음" ≠ "아직 땅에 있음".
   → 주웠다는 판단은 획득 창 목록에 그 아이템이 새로 생긴 것으로만 한다. 주소만으로 완료 처리하지 않는다.
 · loop10 r03: Shortsword 기록으로 갔는데 옆 Battle Axe가 주워졌고, 창을 닫으려던 A가 Shortsword를 주웠다(1 m 안 3개 겹침).
   → 목표와 다른 것이 주워지는 것은 정상 결과. 같은 아이템 후보가 둘 이상이면 어느 쪽인지 정하지 않는다.
 · loop10 r03·r07: 254002(위 수로 화염병) 시체가 맵 밖으로 떨어져 기록 y −2496 → reachable() 콜백이 거른다.
 · 휴식·워프·죽음·로딩 뒤에는 적 객체·기록 주소가 다시 쓰일 수 있다 → reset()으로 기준을 새로 잡는다. 실행이 바뀌면 새 DropBook.
 · 기준(baseline)은 "처치 전 메모리에 있던 기록 전부"를 뺀다 — 주운 뒤 남은 기록만이 아니라 **아직 땅에 있는 진짜 드롭도 함께 빠진다**
   (바이트로 둘을 못 가르기 때문). 11-01 저녁부터 책은 실행 하나에 하나(souls/loot.Loot)라 같은 실행 안의 재시도(pass_ramp 등)는
   첫 회에 못 주운 드롭을 계속 후보로 본다. 기준을 다시 잡는 휴식·부활·워프·퀵 종료(esc.gen) 앞의 못 주운 드롭은 빠진다 —
   휴식·워프 뒤 기록이 사라진 관측(11-01, 3회)과 맞지만, 퀵 종료 뒤 드롭이 땅에 남는지는 확인 안 함.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import math
import struct
from dataclasses import dataclass, field

import numpy as np

MARK = 0x3ECCCCCD                 # 0.4f at pos+0x14
OWNER_OFF = 0x390                 # pos+0x68 → owner chr + this
ITEMGET_OFF = 0x1C891A8           # module offset of the ItemGetMenuMan pointer
CATS = (0, 0x10000000, 0x20000000, 0x40000000)
MAX_NODES = 16
CLUSTER_R = 1.2                   # m — drops this close are taken as one spot (r03: three within 1 m, one A took a neighbour)
MATCH_R = 2.5                     # m from the player — a window item is matched only against candidates this close
MAX_TRIES = 3                     # visits per drop before it is given up (approach failures and misses both count)
REUSED_TRIES = 1                  # a record whose bytes equal a baseline record — one visit only (stale or new, can't tell)
MAX_HOLDS = 2                     # times a drop may be put off for a foe near it before it is given up (souls/loot.Loot)


@dataclass(frozen=True)
class Rec:
    addr: int
    pos: tuple
    item: int
    cnt: int
    owner: int | None             # owner chr pointer (pos+0x68 − 0x390), None if the qword doesn't look like one

    @property
    def ident(self) -> tuple:
        """Same address with other bytes = another drop (record reuse)."""
        return (self.addr, self.item, self.cnt, self.owner)


def find_records(buf: bytes, base: int) -> list[Rec]:
    u = np.frombuffer(buf[: len(buf) // 4 * 4], dtype=np.uint32)
    if len(u) < 32:
        return []
    idx = np.nonzero(u[:-30] == MARK)[0]
    idx = idx[(idx >= 5) & (u[idx - 1] == 0xFFFFFFFF) & (u[idx - 2] == 0)]
    out = []
    for i in idx:
        item, cnt = int(u[i + 3]), int(u[i + 5])
        if item & 0xF0000000 not in CATS or not 0 < item & 0x0FFFFFFF < 3000000 or not 0 < cnt < 100:
            continue
        p = (int(i) - 5) * 4
        x, y, z = struct.unpack_from("<3f", buf, p)
        if not all(math.isfinite(v) for v in (x, y, z)):
            continue
        back = struct.unpack_from("<Q", buf, p + 0x68)[0] if p + 0x70 <= len(buf) else 0
        owner = back - OWNER_OFF if 0x10000 + OWNER_OFF <= back <= 0x7FFFFFFFFFFF and back % 8 == 0 else None
        out.append(Rec(base + p, (x, y, z), item, cnt, owner))
    return out


class _MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_uint64), ("AllocationBase", ctypes.c_uint64), ("AllocationProtect", wt.DWORD),
                ("_a", wt.DWORD), ("RegionSize", ctypes.c_uint64), ("State", wt.DWORD), ("Protect", wt.DWORD),
                ("Type", wt.DWORD), ("_b", wt.DWORD)]


def _regions(h):
    k = ctypes.windll.kernel32
    k.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_uint64, ctypes.POINTER(_MBI), ctypes.c_size_t]
    a, m = 0x10000, _MBI()
    while a < 0x7FFFFFFFFFFF and k.VirtualQueryEx(h, a, ctypes.byref(m), ctypes.sizeof(m)):
        if m.State == 0x1000 and m.Protect in (0x04, 0x40) and m.RegionSize <= 512 << 20:
            yield m.BaseAddress, m.RegionSize
        a = m.BaseAddress + m.RegionSize


def scan(tm) -> list[Rec]:
    out = []
    for base, size in _regions(tm.pm.process_handle):
        try:
            b = tm.pm.read_bytes(base, size)
        except Exception:  # noqa: BLE001 — a region can go away between query and read
            continue
        out += find_records(b, base)
    return out


def read_rec(tm, rec: Rec) -> Rec | None:
    """The same record read again (position follows a pushed corpse). None if unreadable or the bytes now say another drop."""
    try:
        b = tm.pm.read_bytes(rec.addr, 0x70)
    except Exception:  # noqa: BLE001
        return None
    r = next((x for x in find_records(b + b"\0" * 0x60, rec.addr) if x.addr == rec.addr), None)
    return r if r is not None and r.ident == rec.ident else None


def walk_nodes(raw, head) -> list[tuple] | None:
    """raw(p, n) -> bytes | None. → [(item, amount)] head first (= last picked), None if a read or pointer is bad."""
    if head is None:
        return None
    out, seen, p = [], set(), head
    while p:
        if not 0x10000 <= p <= 0x7FFFFFFFFFFF or p % 8 or p in seen or len(out) >= MAX_NODES:
            return None
        seen.add(p)
        b = raw(p, 0x14)
        if not b or len(b) < 0x14:
            return None
        cat, iid, amt = struct.unpack_from("<3I", b, 8)
        out.append((cat | iid, amt))
        p = struct.unpack_from("<Q", b, 0)[0]
    return out


def itemget_nodes(tm) -> list[tuple] | None:
    def raw(p, n):
        try:
            return tm.pm.read_bytes(p, n)
        except Exception:  # noqa: BLE001
            return None
    b = raw(tm.base + ITEMGET_OFF, 8)
    igm = struct.unpack("<Q", b)[0] if b else 0
    if not 0x10000 <= igm <= 0x7FFFFFFFFFFF:
        return None
    b = raw(igm + 8, 8)
    return walk_nodes(raw, struct.unpack("<Q", b)[0]) if b else None


def new_nodes(before: list | None, after: list | None) -> list[tuple] | None:
    """Window items added between two reads (multiset difference — the list may still hold an earlier pickup, r03).
    None if either read failed."""
    if before is None or after is None:
        return None
    left = list(before)
    out = []
    for n in after:
        if n in left:
            left.remove(n)
        else:
            out.append(n)
    return out


@dataclass
class Drop:
    rec: Rec
    seen_t: float
    state: str = "pending"        # pending · taken · gone · failed
    tries: int = 0
    max_tries: int = MAX_TRIES
    ambiguous: bool = False       # a window item matched it and another same-item drop — not marked taken
    why: str = ""
    holds: int = 0                # put off for a foe near it (held()), not a visit


@dataclass
class DropBook:
    """One per run. observe() every scan, select() for the next spot, visited() after each A press (or a failed approach).
    reset() after rest · warp · own death · load — the baseline is taken again at the next observe()."""
    baseline: set = field(default_factory=set)
    based: bool = False
    drops: dict = field(default_factory=dict)       # ident → Drop
    hp: dict = field(default_factory=dict)          # chr ptr → last hp
    deaths: dict = field(default_factory=dict)      # chr ptr → time of the last hp>0 → 0 seen
    unexpected: list = field(default_factory=list)  # window items no candidate explained
    log: list = field(default_factory=list)

    def reset(self, why: str) -> None:
        self.baseline, self.based = set(), False
        self.drops, self.hp, self.deaths = {}, {}, {}
        self.log.append(f"reset: {why}")

    def observe_chars(self, chars, now: float) -> None:
        """chars: objects with .ptr .hp. Owner deaths seen here decide whether a baseline-identical record may be a new drop."""
        for c in chars:
            last = self.hp.get(c.ptr)
            if last is not None and last > 0 and (c.hp or 0) <= 0:
                self.deaths[c.ptr] = now
            self.hp[c.ptr] = c.hp or 0

    def observe(self, recs: list[Rec], now: float) -> list[Drop]:
        """→ drops new this call. The first call after construction/reset only takes the baseline (records left from earlier
        pickups or other runs are never candidates)."""
        if not self.based:
            self.baseline = {r.ident for r in recs}
            self.based = True
            self.log.append(f"baseline: {len(self.baseline)} records")
            return []
        new = []
        live = {r.ident: r for r in recs}
        for ident, r in live.items():
            d = self.drops.get(ident)
            if d is not None:
                d.rec = r                                   # position follows a pushed corpse
                continue
            if ident in self.baseline:
                t = self.deaths.get(r.owner) if r.owner is not None else None
                if t is None:
                    continue
                # 같은 주소·같은 내용인데 그 주인이 이번 기준 뒤에 죽었다 — 남은 옛 기록인지 새 드롭인지 바이트로는 못 가른다 → 한 번만 가 본다
                self.baseline.discard(ident)
                d = Drop(r, now, max_tries=REUSED_TRIES, why="same bytes as baseline, owner died since")
            else:
                d = Drop(r, now)
            self.drops[ident] = d
            new.append(d)
        for ident, d in self.drops.items():
            if ident not in live and d.state == "pending":
                d.state, d.why = "gone", "record no longer found"
        return new

    def pending(self) -> list[Drop]:
        return [d for d in self.drops.values() if d.state == "pending"]

    def select(self, me, reachable=lambda pos: True) -> list[Drop]:
        """→ the cluster to visit next (nearest pending drop + pending drops within CLUSTER_R of it), [] if none.
        reachable(pos) → False marks a drop gone (fell out of the map, no path)."""
        for d in self.pending():
            if not reachable(d.rec.pos):
                d.state, d.why = "gone", f"unreachable at {tuple(round(v, 1) for v in d.rec.pos)}"
        ps = self.pending()
        if not ps:
            return []
        first = min(ps, key=lambda d: math.dist(d.rec.pos, me))
        return [d for d in ps if math.dist(d.rec.pos, first.rec.pos) <= CLUSTER_R]

    def held(self, cluster: list[Drop], why: str) -> list[Drop]:
        """The cluster was put off (a foe near it that is not ours to fight now). → drops given up by this call (MAX_HOLDS reached)."""
        out = []
        for d in cluster:
            if d.state != "pending":
                continue
            d.holds += 1
            d.why = f"held: {why}"
            if d.holds >= MAX_HOLDS:
                d.state, d.why = "failed", f"held {d.holds}× ({why})"
                out.append(d)
        return out

    def visited(self, cluster: list[Drop], got: list[tuple] | None, me, why: str = "") -> dict:
        """After one visit: got = new_nodes(before, after) of the A presses there, [] if nothing came, None if the window
        couldn't be read (or the approach failed — then pass why). Each visited drop's tries go up; matching drops only
        become 'taken' when exactly one pending candidate near me has that item. → {'taken', 'ambiguous', 'unexpected'}"""
        res = {"taken": [], "ambiguous": [], "unexpected": []}
        for item, amt in got or []:
            near = [d for d in self.pending() if d.rec.item == item and math.dist(d.rec.pos, me) <= MATCH_R]
            exact = [d for d in near if d.rec.cnt == amt] or near
            if len(exact) == 1:
                exact[0].state, exact[0].why = "taken", f"window {item:#x}×{amt}"
                res["taken"].append(exact[0])
            elif exact:
                for d in exact:
                    d.ambiguous = True
                res["ambiguous"].append((item, amt, [d.rec.addr for d in exact]))
            else:
                self.unexpected.append((item, amt, tuple(me)))
                res["unexpected"].append((item, amt))
        for d in cluster:
            if d.state != "pending":
                continue
            d.tries += 1
            if got is None:
                d.why = why or "window unreadable"
            elif not got:
                d.why = why or "A gave nothing"
            if d.tries >= d.max_tries:
                d.state = "failed"
                d.why = (d.why or "tries used") + f" ({d.tries} visits)"
        return res
