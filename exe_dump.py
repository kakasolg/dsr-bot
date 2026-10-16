"""Dump the decrypted DarkSoulsRemastered.exe image from the running game, for reverse engineering (rea-trial).

  python exe_dump.py                       → data/dump/DarkSoulsRemastered.dump.exe (+ .json next to it)
  python exe_dump.py --out D:/tools/rea-target/dsr.dump.exe

Why: the exe on disk is protected — its code is encrypted and only decrypted at run time (rea-trial 10-16: the ChrDbg
AOB occurs 0x in the file, Ghidra ran > 60 min on it). The image in memory has the real code.

What it does: reads the module image page by page (unreadable pages → zeros, counted), then fixes the PE headers so a
disassembler can load the dump as a file — every section's file offset = its virtual address, sizes = virtual sizes,
ImageBase = the runtime base (addresses in Ghidra = addresses the bot reads). Read-only: nothing is written to the game.
Check before trusting it: every AOB in dsr_telemetry.AOBS must hit exactly once in the dump (printed and in the .json).

The dump is the game's code: keep it local — data/dump/ is git-ignored, never commit it.
Run it offline, in game (title screen is enough), not during a bot run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

EXE = "DarkSoulsRemastered.exe"
OUT = Path(__file__).parent / "data" / "dump" / "DarkSoulsRemastered.dump.exe"
PAGE = 0x1000


def aob(p: str) -> re.Pattern:
    """dsr_telemetry's AOB text ('48 8B ? ?') → a bytes regex."""
    return re.compile(b"".join(b"." if t == "?" else re.escape(bytes([int(t, 16)])) for t in p.split()), re.DOTALL)


def aob_hits(data: bytes, pattern: str) -> list[int]:
    return [m.start() for m in aob(pattern).finditer(data)]


def read_image(read, base: int, size: int) -> tuple[bytearray, int]:
    """read(addr, n) → bytes, raising on an unreadable page. Returns (image, unreadable page count)."""
    img, bad = bytearray(size), 0
    for off in range(0, size, PAGE):
        n = min(PAGE, size - off)
        try:
            img[off:off + n] = read(base + off, n)
        except Exception:
            bad += 1
    return img, bad


def fix_pe(img: bytearray, base: int) -> list[dict]:
    """Make a memory image loadable as a PE file: raw offset = virtual address, raw size = virtual size,
    FileAlignment = SectionAlignment, ImageBase = base. Returns the section list."""
    if img[:2] != b"MZ":
        raise ValueError("no MZ header (page 0 unreadable?)")
    pe = struct.unpack_from("<I", img, 0x3C)[0]
    if img[pe:pe + 4] != b"PE\0\0":
        raise ValueError("no PE signature")
    n_sec, opt_size = struct.unpack_from("<H", img, pe + 6)[0], struct.unpack_from("<H", img, pe + 20)[0]
    opt = pe + 24
    if struct.unpack_from("<H", img, opt)[0] != 0x20B:
        raise ValueError("not PE32+ (64-bit)")
    struct.pack_into("<Q", img, opt + 24, base)                                        # ImageBase
    struct.pack_into("<I", img, opt + 36, struct.unpack_from("<I", img, opt + 32)[0])   # FileAlignment = SectionAlignment
    sections = []
    for i in range(n_sec):
        s = opt + opt_size + 40 * i
        name = bytes(img[s:s + 8]).rstrip(b"\0").decode("latin-1")
        vsize, va = struct.unpack_from("<II", img, s + 8)
        size = max(0, min(vsize or struct.unpack_from("<I", img, s + 16)[0], len(img) - va))
        struct.pack_into("<II", img, s + 16, size, va)                                   # SizeOfRawData, PointerToRawData
        sections.append({"name": name, "va": va, "size": size})
    return sections


def check(img: bytes, aobs: dict) -> dict:
    """{name: hit count} for every telemetry AOB — each must be 1 in a good dump (0 on the protected disk exe)."""
    return {k: len(aob_hits(img, pat)) for k, (pat, _ao, _il) in aobs.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    import pymem
    import pymem.process
    from dsr_telemetry import AOBS
    pm = pymem.Pymem(EXE)
    mod = pymem.process.module_from_name(pm.process_handle, EXE)
    base, size = mod.lpBaseOfDll, mod.SizeOfImage
    print(f"{EXE}: base 0x{base:X}, size 0x{size:X} — 읽는 중 …")
    img, bad = read_image(pm.read_bytes, base, size)
    sections = fix_pe(img, base)
    hits = check(img, AOBS)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_bytes(img)
    meta = {"exe": EXE, "base": hex(base), "size": hex(size), "unreadable_pages": bad,
            "sha256": hashlib.sha256(img).hexdigest(), "sections": sections, "aob_hits": hits}
    a.out.with_suffix(".json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    for s in sections:
        print(f"  {s['name']:<8} va 0x{s['va']:08X} size 0x{s['size']:X}")
    print(f"못 읽은 페이지 {bad} / {(size + PAGE - 1) // PAGE}")
    print("AOB (모두 1이어야 함):", ", ".join(f"{k} {n}" for k, n in hits.items()))
    print(("OK" if all(n == 1 for n in hits.values()) else "주의: 1이 아닌 AOB가 있음") + f" → {a.out}")


if __name__ == "__main__":
    main()
