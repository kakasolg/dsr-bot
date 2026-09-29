"""dsr_telemetry.equip_quick_item offline test — fake PlayerGameData memory laid out like the 2026-09-28 measurement
(Estus 76, Firebomb 85, … knife at inventory index 88, slot 5 empty). No game.

  python tests/quick_slot_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import struct
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import dsr_telemetry as D

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


CB, PGD = 0x1000, 0x100000


class Mem:
    """Just enough of pymem.Pymem: a sparse little-endian memory."""
    def __init__(self):
        self.b = bytearray(0x10000)
        self.writes = []

    def _o(self, a):
        return a - PGD

    def read_bytes(self, a, n):
        return bytes(self.b[self._o(a):self._o(a) + n])

    def read_int(self, a):
        return struct.unpack_from("<i", self.b, self._o(a))[0]

    def write_int(self, a, v):
        self.writes.append((a - PGD, v))
        struct.pack_into("<i", self.b, self._o(a), v)

    def read_ulonglong(self, a):
        return PGD if a == CB + 0x10 else CB


def game(slots=((76, 205), (85, 292), (86, 310), (118, 330), (-1, -1)), goods=((76, 205, 19), (85, 292, 91), (86, 310, 14),
                                                                                 (88, 290, 86), (118, 330, 16))):
    t = D.DSRTelemetry.__new__(D.DSRTelemetry)
    t.pm, t.static = Mem(), {"ChrClassBase": 0x9000}
    t.q = lambda a: CB if a == 0x9000 else PGD if a == CB + 0x10 else None
    for i, iid, n in goods:
        struct.pack_into("<Iii", t.pm.b, D.INV_BASE + i * D.INV_ENTRY, 0x40000000, iid, n)
    for k, (i, iid) in enumerate(slots):
        for off, v in ((D.QS_IDX, i), (D.QS_ID, iid), (D.QS_IDX2, i)):
            struct.pack_into("<i", t.pm.b, off + 4 * k, v)
    return t


print("넣기")
t = game()
check("빈 5번째 칸에 넣음 → 4", t.equip_quick_item(290) == 4)
check("세 칸 모두 씀 (번호 88, ID 290, 복사본 88)", t.pm.writes == [(D.QS_IDX + 16, 88), (D.QS_ID + 16, 290), (D.QS_IDX2 + 16, 88)])
check("quick_items 에 보임", t.quick_items() == [205, 292, 310, 330, 290])
t.pm.writes.clear()
check("이미 있으면 그 칸, 안 씀", t.equip_quick_item(290) == 4 and t.pm.writes == [])

print("거절 (안 씀)")
t = game(goods=((76, 205, 19), (85, 292, 91), (86, 310, 14), (118, 330, 16)))
check("가진 게 없음 → None", t.equip_quick_item(290) is None and t.pm.writes == [])
t = game(goods=((76, 205, 19), (85, 292, 91), (86, 310, 14), (88, 290, 0), (118, 330, 16)))
check("0개 → None", t.equip_quick_item(290) is None and t.pm.writes == [])
t = game(slots=((76, 205), (85, 292), (86, 310), (118, 330), (88, 370)), goods=((76, 205, 19), (85, 292, 91), (86, 310, 14),
                                                                                (88, 370, 3), (90, 290, 5), (118, 330, 16)))
check("빈 칸 없음 → None", t.equip_quick_item(290) is None and t.pm.writes == [])
t = game(slots=((77, 205), (85, 292), (86, 310), (118, 330), (-1, -1)))
check("슬롯 번호가 인벤토리와 안 맞음(모양이 다름) → None", t.equip_quick_item(290) is None and t.pm.writes == [])
t = game()
struct.pack_into("<i", t.pm.b, D.QS_IDX2 + 4, 99)
check("복사본이 다름 → None", t.equip_quick_item(290) is None and t.pm.writes == [])

print("실패 0" if not fails else f"실패 {fails}")
sys.exit(1 if fails else 0)
