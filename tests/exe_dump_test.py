"""exe_dump offline test — a tiny fake PE64 image in memory, no game.

  python tests/exe_dump_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import struct

import exe_dump as X
from dsr_telemetry import AOBS


def fake_image(size=0x4000) -> bytearray:
    img = bytearray(size)
    img[:2] = b"MZ"
    pe = 0x80
    struct.pack_into("<I", img, 0x3C, pe)
    img[pe:pe + 4] = b"PE\0\0"
    struct.pack_into("<H", img, pe + 6, 2)          # sections
    struct.pack_into("<H", img, pe + 20, 0xF0)      # SizeOfOptionalHeader
    opt = pe + 24
    struct.pack_into("<H", img, opt, 0x20B)
    struct.pack_into("<Q", img, opt + 24, 0x140000000)
    struct.pack_into("<II", img, opt + 32, 0x1000, 0x200)
    for i, (name, vsize, va, raw_size, raw_ptr) in enumerate(((b".text", 0x1800, 0x1000, 0x400, 0x400),
                                                              (b".data", 0x2000, 0x3000, 0x200, 0x800))):
        s = opt + 0xF0 + 40 * i
        img[s:s + 8] = name.ljust(8, b"\0")
        struct.pack_into("<IIII", img, s + 8, vsize, va, raw_size, raw_ptr)
    return img


def test_fix_pe():
    img = fake_image()
    secs = X.fix_pe(img, 0x7FF600000000)
    opt = 0x80 + 24
    assert struct.unpack_from("<Q", img, opt + 24)[0] == 0x7FF600000000
    assert struct.unpack_from("<I", img, opt + 36)[0] == 0x1000
    # .data's virtual size runs past the image end → clamped to what was read
    assert secs == [{"name": ".text", "va": 0x1000, "size": 0x1800}, {"name": ".data", "va": 0x3000, "size": 0x1000}], secs
    s1 = opt + 0xF0 + 40
    assert struct.unpack_from("<II", img, s1 + 16) == (0x1000, 0x3000)


def test_fix_pe_rejects():
    for bad in (bytearray(0x400), (lambda b: (b.__setitem__(slice(0x80, 0x84), b"XX\0\0"), b)[1])(fake_image())):
        try:
            X.fix_pe(bad, 0)
        except ValueError:
            continue
        raise AssertionError("bad image accepted")


def test_read_image_zero_fills_bad_pages():
    data = bytes(range(256)) * 48                   # 0x3000
    def read(addr, n):
        if 0x10000 + 0x1000 <= addr < 0x10000 + 0x2000:
            raise OSError("no access")
        return data[addr - 0x10000: addr - 0x10000 + n]
    img, bad = X.read_image(read, 0x10000, 0x2800)
    assert bad == 1 and len(img) == 0x2800
    assert img[:0x1000] == data[:0x1000] and img[0x1000:0x2000] == bytes(0x1000) and img[0x2000:] == data[0x2000:0x2800]


def test_aob_check():
    pat, _ao, _il = AOBS["ChrDbg"]
    code = bytes.fromhex("803D11223344" "00" "488B8F55667788" "0FB6DB")
    assert X.aob_hits(b"\x90" * 7 + code + b"\x90", pat) == [7]
    assert X.aob_hits(code.replace(b"\x0f\xb6\xdb", b"\x0f\xb6\xdc"), pat) == []
    assert X.aob_hits(b"\x80\x3d\x0a\x00\x00\x00\x00\x48\x8b\x8f\x00\x00\x00\x00\x0f\xb6\xdb", pat) == [0]   # '?' matches 0x0A too
    hits = X.check(b"\x90" + code, AOBS)
    assert hits["ChrDbg"] == 1 and set(hits) == set(AOBS) and all(v == 0 for k, v in hits.items() if k != "ChrDbg")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
