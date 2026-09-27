"""
Dark Souls Remastered (DSR) telemetry — attaches directly to DarkSoulsRemastered.exe via pymem (no EAC, no CE/bridge needed).
Read-only + two writes for resets (instant-death flag, coordinate warp). **Always run offline** (online soft ban).

Pointer map from JKAnderson/DSR-Gadget's DSROffsets.cs (AOB → RIP-relative address → static pointer). Measured 2026-09-21, module size 0x319B000
(newer than the 1.03 that DSR-Gadget knows — the 1.03 correction offsets (+0x20/+0x10) matched as-is).

  WorldChrMan  = [WorldChrBase]                (AOB 48 8B 05 ? ? ? ? 48 8B 48 68 ...)
  Player       = [WorldChrMan+0x68]            (ChrIns)
  Character list = [[WorldChrMan+0xA8]+0x50]      entries 0x38 bytes, first 8 bytes = ChrIns pointer. Count = [WorldChrMan+0xA8]+0x48 (int)
  ChrIns:
    +0x00  vtable  (PlayerIns 0x1413251F0 / EnemyIns 0x141322E68 — stored relative to base)
    +0x88  model name (UTF-16, "c2500" etc.)
    +0xC8  NpcParam ID (int32, e.g. 250023 Hollow, 279070 Crestfallen Warrior) — key for enemy/non-enemy judgment
    +0x68  → ChrMapData: +0x28 → ChrPosData(+0x4 angle, +0x10 x, +0x14 y(height), +0x18 z)
                          +0x48 → +0x80 current animation ID
                          +0x108 Warp(byte) +0x110/114/118 WarpXYZ +0x124 WarpAngle  (coordinate teleport)
    +0x3E8 HP  +0x3EC MaxHP  +0x3F8 stamina  +0x3FC max stamina   (DSR-Gadget 0x3D8/0x3DC/0x3E8/0x3EC + correction 0x10)
    +0x2A4  ChrFlags1 — only characters with 0x8000 set are actually spawned (unset ones are in the list but invisible and don't move)
    +0xA44  special-action anim ID (int32, -1 if none) — 77xx while sitting at a bonfire (upper bonfire 7711, lower 7721). +0xA48 = 1 while in that action.
            The mapd "current anim" (+0x48→+0x80) shows attack 304000/Estus 7585/backstep 690 but not sitting.
    +0x08  handle (int32, e.g. 0x10008015)
    +0xEF0 (PlayerIns) handle of the lock-on target, -1 if none — found by diffing 0x1000 bytes of PlayerIns before/after pressing R3 (2/2, 2026-09-23)
  ChrClassWarp = [static]: +0xB34 last bonfire ID (e.g. 1812960 = Firelink Shrine)
            **Writing it makes the Homeward Bone go to that bonfire** (measured: in Darkroot, changed this value to Firelink Shrine
            and used a bone, which went to Firelink Shrine). But it is **not the death respawn point** — changing it and dying
            still respawns at the original spot (confirmed 2x). The respawn point is stored elsewhere.
  ChrDbg (static byte array): +0x1 PlayerExterminate = 1 means instant death
  ChrFollowCam = [[[static]+0x60]+0x60]: 4x4 matrix (float) from +0x10 — row 3 = camera forward, row 4 = position. yaw = atan2(fwd.x, fwd.z)

Couldn't find the team-type (enemy/ally) byte → judged by NpcParam ID: non-enemy if in FRIENDLY, enemy if EnemyIns and not in it.
Stick measured: forward = camera forward, right = +90° (same as Elden Ring).

── Known limitations ──────────────────────────────
 · During loading the pointers are invalid → snapshot() is None.
 · The character list is everything loaded (including far away) — filter with within.
"""
from __future__ import annotations

import math
import re
import struct
import sys
import time
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pymem
import pymem.exception
import pymem.pattern
import pymem.process

from telemetry import Chr, Snapshot   # same shape as Elden Ring → nav/patrol use it as-is

AOBS = {
    "WorldChrBase": ("48 8B 05 ? ? ? ? 48 8B 48 68 48 85 C9 0F 84 ? ? ? ? 48 39 5E 10 0F 84 ? ? ? ? 48", 3, 7),
    "ChrClassWarp": ("48 8B 05 ? ? ? ? 66 0F 7F 80 ? ? ? ? 0F 28 02 66 0F 7F 80 ? ? ? ? C6 80", 3, 7),
    "ChrDbg": ("80 3D ? ? ? ? 00 48 8B 8F ? ? ? ? 0F B6 DB", 2, 7),
    "ChrFollowCam": ("48 8B 0D ? ? ? ? E8 ? ? ? ? 48 8B 4E 68 48 8B 05 ? ? ? ? 48 89 48 60", 3, 7),
    "ChrClassBase": ("48 8B 05 ? ? ? ? 48 85 C0 ? ? F3 0F 58 80 AC 00 00 00", 3, 7),
    # game records (event flags) — JKAnderson/EventPocket DSOffsets.EventFlagsAOBR (DSR)
    "EventFlags": ("48 8B 0D ? ? ? ? 99 33 C2 45 33 C0 2B C2 8D 50 F6", 3, 7),
}
# event flag id, 8 digits = group 1 · area 3 · block 1 · number 3 → byte position (EventPocket DSProcess.getEventFlagAddress)
EVENT_GROUPS = {"0": 0x00000, "1": 0x00500, "5": 0x05F00, "6": 0x0B900, "7": 0x11300}
EVENT_AREAS = {"000": 0, "100": 1, "101": 2, "102": 3, "110": 4, "120": 5, "121": 6, "130": 7, "131": 8, "132": 9,
               "140": 10, "141": 11, "150": 12, "151": 13, "160": 14, "170": 15, "180": 16, "181": 17}
OFF_HP, OFF_MAXHP, OFF_SP, OFF_MAXSP = 0x3E8, 0x3EC, 0x3F8, 0x3FC
OFF_MAPDATA, OFF_MODEL, OFF_NPC = 0x68, 0x88, 0xC8
OFF_LASTBONFIRE = 0xB34
BONFIRE_WARP_AOB = "48 89 5C 24 08 57 48 83 EC 20 48 8B D9 8B FA 48 8B 49 08 48 85 C9 0F 84 ? ? ? ? E8 ? ? ? ? 48 8B 4B 08"  # DSR-Gadget DSROffsets
QUIT_GONE_S = 0.5          # quit-out: the character must be invisible this long in a row to count as having exited to title
QUIT_REQ = 0x19            # ChrClassWarp — writing 1 exits to the title screen (quit-out, found with warp_re.py)
CHR_LIST_OFFSETS = (0xA8, 0xB0, 0xB8, 0xC0, 0xC8)   # per-area character lists inside WorldChrMan (measured: Firelink Shrine is 0xB0)
OFF_ANIM2 = 0xA44
OFF_HANDLE, OFF_LOCK_TARGET = 0x8, 0xEF0
OFF_MENU_FLAG = 0x1A294F0   # module-relative. 1=in gameplay, 0=menu open (App ver 1.03.1 measured)
OFF_FLAGS1 = 0x2A4      # DSR-Gadget ChrFlags1(0x284) + correction 0x20
FLAG_ACTIVE = 0x8000    # measured: set only for characters actually in the world (anim running)
# measured (Firelink Shrine~graveyard): ones with this bit set are neither visible nor hittable — c5330 HP 11120 (0x280c400), c3510 (0x2808800),
# c2750 HP 32 next to the bonfire (0x2808400). Real enemies are 0x808400/0x808800. The bot whiffed at c5330 1 m ahead for 8 s.
FLAG_GHOST = 0x2000000
PHANTOM_NPC = {254013, 254014}   # two HP 150 ones next to the Undead Burg bonfire room — no body (user saw on screen: "there's nothing there, why is it swinging").
                                 # before overlap/whiff detection caught them, the bot hit them for 15 s at a time next to a hole and fell three times (2026-09-25) — exclude by ID directly
PHANTOM_S = 1.0
PHANTOM_R = 0.45           # an enemy overlapping closer than this = no body (once caught, that ptr is not an enemy for the rest of the process)
FRIENDLY = {279070, 100000}   # Crestfallen Warrior, human NPC (c1000) — move to data/dsr_friendly.json if needed


class DSRTelemetry:
    def __init__(self, names: Optional[dict[int, str]] = None):
        self.pm = pymem.Pymem("DarkSoulsRemastered.exe")
        self.mod = pymem.process.module_from_name(self.pm.process_handle, "DarkSoulsRemastered.exe")
        self.base = self.mod.lpBaseOfDll
        self.names = names or {}
        self.static: dict[str, int] = {}
        self.phantom: set[int] = set()   # enemies with no body (ptr) — snapshot finds them and sets them to team 0
        self._overlap: dict[int, float] = {}   # ptr → time overlap started
        for k, (pat, ao, il) in AOBS.items():
            a = pymem.pattern.pattern_scan_module(self.pm.process_handle, self.mod, self._aob(pat))
            if not a:
                raise RuntimeError(f"AOB 실패: {k} — 게임 버전이 바뀌었나?")
            self.static[k] = a + il + self.pm.read_int(a + ao)
        self.vt_player = self.base + 0x13251F0
        self.vt_enemy = self.base + 0x1322E68
        self.symbols = {"version": f"0x{self.mod.SizeOfImage:X}", **{k: hex(v) for k, v in self.static.items()}}

    @staticmethod
    def _aob(p: str) -> bytes:
        return b"".join(b"." if t == "?" else re.escape(bytes([int(t, 16)])) for t in p.split())

    # ── low level ──
    def q(self, a: int) -> Optional[int]:
        try:
            v = self.pm.read_ulonglong(a)
            return v if 0x10000 < v < 0x7FFFFFFFFFFF else None
        except pymem.exception.PymemError:
            return None

    def i32(self, a: int) -> Optional[int]:
        try:
            return self.pm.read_int(a)
        except pymem.exception.PymemError:
            return None

    def f32(self, a: int) -> Optional[float]:
        try:
            return self.pm.read_float(a)
        except pymem.exception.PymemError:
            return None

    # ── characters ──
    def world_chr_man(self) -> Optional[int]:
        return self.q(self.static["WorldChrBase"])

    def player_ptr(self) -> Optional[int]:
        w = self.world_chr_man()
        return self.q(w + 0x68) if w else None

    def read_chr(self, p: int) -> Optional[Chr]:
        hp, mhp = self.i32(p + OFF_HP), self.i32(p + OFF_MAXHP)
        if hp is None or mhp is None or mhp <= 0 or mhp > 100000:
            return None
        mapd = self.q(p + OFF_MAPDATA)
        posd = self.q(mapd + 0x28) if mapd else None
        if not posd:
            return None
        x, y, z, ang = self.f32(posd + 0x10), self.f32(posd + 0x14), self.f32(posd + 0x18), self.f32(posd + 0x4)
        if None in (x, y, z) or not all(math.isfinite(c) and abs(c) < 1e5 for c in (x, y, z)):
            return None
        animst = self.q(mapd + 0x48)
        anim = self.i32(animst + 0x80) if animst else None
        npc = self.i32(p + OFF_NPC) or 0
        vt = self.q(p)
        flags1 = (self.i32(p + OFF_FLAGS1) or 0) & 0xFFFFFFFF
        if vt == self.vt_player:
            team = 1
        elif npc in FRIENDLY:
            team = 26   # FriendlyNPC (mimics Elden Ring team numbers — Snapshot.hostile() only treats 6/7/24/25/27/33 as enemies)
        elif not (flags1 & FLAG_ACTIVE):
            team = 0    # inactive (not spawned / disabled by event) — in the list but not in the world. Measured: invisible Hollow is 0x800400, a moving one 0x808400
        elif flags1 & FLAG_GHOST:
            team = 0
        else:
            team = 6
        return Chr(ptr=p, npc_param=npc, team=team, hp=hp, max_hp=mhp, sp=self.i32(p + OFF_SP) or 0, max_sp=self.i32(p + OFF_MAXSP) or 0,
                   x=x, y=y, z=z, anim=anim, name=self.names.get(npc, ""), gx=x, gy=y, gz=z, heading=ang, map_id=0)

    def chr_ptrs(self) -> list[int]:
        """Characters of **all** loaded areas. DS1 keeps adjacent areas loaded too, with a separate list per area.

        Measured (Firelink Shrine): +0xA8 had 174 but all beyond 64 m; the area we stood in was +0xB0 with 41
        (nearest NPC 5.1 m). In the Asylum +0xA8 happened to be that area, so reading one was enough —
        hence no enemies were detected at Firelink Shrine/graveyard, and the bot judged "no enemies" even while being hit by skeletons."""
        w = self.world_chr_man()
        if not w:
            return []
        out, seen_holder, seen = [], set(), set()
        for off in CHR_LIST_OFFSETS:
            holder = self.q(w + off)
            if not holder or holder in seen_holder:
                continue
            seen_holder.add(holder)
            arr = self.q(holder + 0x50)
            n = self.i32(holder + 0x48)
            if not arr or not n or n <= 0 or n > 2000:
                continue
            try:
                raw = self.pm.read_bytes(arr, n * 0x38)
            except pymem.exception.PymemError:
                continue
            for i in range(n):
                v = struct.unpack_from("<Q", raw, i * 0x38)[0]
                if 0x10000 < v < 0x7FFFFFFFFFFF and v not in seen:
                    seen.add(v)
                    out.append(v)
        return out

    def model(self, p: int) -> str:
        try:
            raw = self.pm.read_bytes(p + OFF_MODEL, 16)
            return raw.decode("utf-16le", "ignore").split("\x00")[0]
        except pymem.exception.PymemError:
            return ""

    # ── camera ──
    def cam_yaw(self) -> Optional[float]:
        c1 = self.q(self.static["ChrFollowCam"])
        c2 = self.q(c1 + 0x60) if c1 else None
        cam = self.q(c2 + 0x60) if c2 else None
        if not cam:
            return None
        fx, fz = self.f32(cam + 0x10 + 8 * 4), self.f32(cam + 0x10 + 10 * 4)
        if fx is None or fz is None:
            return None
        return math.atan2(fx, fz)

    def snapshot(self, within: float = 60.0) -> Optional[Snapshot]:
        pp = self.player_ptr()
        if not pp:
            return None
        player = self.read_chr(pp)
        if not player:
            return None
        # read only coordinates cheaply first, and fully read only nearby ones. After fixing it to read all per-area lists, the list
        # grew to 391, and read_chr on all of them took 14 ms per snapshot (tick dropped to 65 ms, 15/s).
        chars = []
        px, py, pz = player.x, player.y, player.z
        for p in self.chr_ptrs():
            if p == pp:
                continue
            mapd = self.q(p + OFF_MAPDATA)
            posd = self.q(mapd + 0x28) if mapd else None
            if not posd:
                continue
            x = self.f32(posd + 0x10)
            z = self.f32(posd + 0x18)
            if x is None or z is None or not (math.isfinite(x) and math.isfinite(z)):
                continue
            if math.hypot(x - px, z - pz) > within + 2.0:   # height difference is checked precisely later
                continue
            c = self.read_chr(p)
            if not c:
                continue
            c.dist = math.dist((px, py, pz), (c.x, c.y, c.z))
            # if bodies overlap, that enemy isn't in the world — real enemies can't get this close due to collision capsules. The flags (0x808400)
            # are the same as live ones, so they can't separate it: at Undead Burg, got to 0.19 m of 254014, 18 light attacks in a row for 0 damage (2026-09-25)
            # backstabs/ripostes overlap momentarily — only when overlapping continuously for more than PHANTOM_S
            if c.team == 6 and c.hp > 0 and math.hypot(c.x - px, c.z - pz) < PHANTOM_R and abs(c.y - py) < 0.6:
                t0 = self._overlap.setdefault(p, time.time())
                if time.time() - t0 >= PHANTOM_S:
                    self.phantom.add(p)
            else:
                self._overlap.pop(p, None)
            if p in self.phantom or c.npc_param in PHANTOM_NPC:
                c.team = 0
            if c.dist <= within:
                chars.append(c)
        chars.sort(key=lambda c: c.dist)
        return Snapshot(t=time.time(), player=player, chars=chars, cam_yaw=self.cam_yaw(), cam_pitch=None)

    # ── match the Elden Ring telemetry interface (so patrol/learn don't need to know the game) ──
    def arm_style(self) -> Optional[int]:
        return None   # in DS1, LB guards even with an empty left hand (bare-hand guard) — no two-hand check needed

    def flasks(self) -> tuple[Optional[int], Optional[int]]:
        return None, None   # TODO Estus count (inventory offset unknown) — Guard falls back to the "no effect → empty flask" heuristic

    def handle(self, p: int) -> Optional[int]:
        return self.i32(p + OFF_HANDLE) if p else None

    def lock_target(self) -> Optional[int]:
        """Handle of the lock-on target, -1 if none. R3 is a toggle, so this tells how many times to press."""
        pp = self.player_ptr()
        return self.i32(pp + OFF_LOCK_TARGET) if pp else None

    def last_grace(self) -> Optional[int]:
        return self.last_bonfire()

    def sitting(self) -> bool:
        """Sitting at a bonfire? — ChrIns+0xA48 == 1 and +0xA44 is 77xx (measured: upper bonfire 7711, lower bonfire 7721)."""
        pp = self.player_ptr()
        if not pp:
            return False
        a = self.i32(pp + OFF_ANIM2)
        try:
            flag = self.pm.read_uchar(pp + OFF_ANIM2 + 4)   # 1 byte — the upper bytes carry other values (measured 0x1C260001 after death)
        except pymem.exception.PymemError:
            return False
        return flag == 1 and a is not None and 7700 <= a < 7800 and a % 10 == 1   # 7720 = sitting down (flag 0), 77x1 = seated (7701/7711/7721)

    def face(self, pad, heading: float, tries: int = 5, tol: float = 0.25) -> bool:
        """Turn the character to heading (+0x4 angle, measured world yaw = heading + π) — rotate in place with short stick taps.
        DS1 bonfire/door interaction prompts require facing them head-on (user measured)."""
        import control, nav
        for _ in range(tries):
            s = self.snapshot(within=1.0)
            if not s or s.cam_yaw is None or s.player.heading is None:
                return False
            d = (heading - s.player.heading + math.pi) % (2 * math.pi) - math.pi
            if abs(d) < tol:
                return True
            yaw = heading + math.pi
            sx, sy = control.world_to_stick(math.sin(yaw), math.cos(yaw), s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
            pad.move(sx, sy)
            time.sleep(0.10)
            pad.neutral()
            time.sleep(0.45)
        s = self.snapshot(within=1.0)
        return bool(s) and abs((heading - s.player.heading + math.pi) % (2 * math.pi) - math.pi) < tol

    # ── progress state ──
    def menu_open(self) -> Optional[bool]:
        """Is the menu (START) open. Measured: the byte at module +0x1A294F0 is normally 1 and goes 0 within 10 ms of the menu opening —
        stays 0 in submenus like system/confirm dialogs and returns to 1 only when fully closed (found by static memory diff).
        Used to confirm START registered during quit-out — right after loading START got dropped and the remaining inputs leaked into the game."""
        try:
            return self.pm.read_uchar(self.base + OFF_MENU_FLAG) == 0
        except pymem.exception.PymemError:
            return None

    def weapon_durability(self, weapon_id: int | None = None) -> Optional[int]:
        """Durability of the right-hand weapon (or weapon_id). +0x14 of the inventory entry (category 0, ID, count, handle, ?, **durability**, ?).
        Measured 2026-09-25: Claymore 188 → 200 after repair powder (Claymore max 200)."""
        wid = weapon_id or self.right_weapon()
        cb = self.q(self.static["ChrClassBase"])
        pgd = self.q(cb + 0x10) if cb else None
        if not pgd or not wid:
            return None
        try:
            raw = self.pm.read_bytes(pgd, 0x8000)
        except pymem.exception.PymemError:
            return None
        for o in range(0x600, 0x8000 - 0x1C, 4):
            cat, iid = struct.unpack_from("<Ii", raw, o)
            if cat == 0 and iid == wid:
                return struct.unpack_from("<i", raw, o + 0x14)[0]
        return None

    def quick_items(self) -> list[int]:
        """Item IDs of the 5 consumable slots (-1 for empty). The user changes them, e.g. removing Estus and adding Darksign."""
        cb = self.q(self.static["ChrClassBase"])
        pgd = self.q(cb + 0x10) if cb else None
        return [self.i32(pgd + 0x360 + 4 * k) for k in range(5)] if pgd else []

    def selected_item(self) -> Optional[int]:
        """Item ID of the currently selected consumable slot (Estus 200~215, Firebomb 292, Throwing Knife 290).

        Measured (PlayerGameData = [ChrClassBase]+0x10): from +0x2E0 the **inventory indices** of the 5 consumable slots,
        from +0x360 the **item IDs** of the same 5 slots, +0x44C the inventory index of the currently selected slot.
        (found by diff as it changed 76 → 78 → 132 → 76 while pressing D-pad ↓. Empty slots are skipped)
        Don't just press the button and trust it — right after init ↓ got dropped and it drank Estus instead of a bomb."""
        cb = self.q(self.static["ChrClassBase"])
        pgd = self.q(cb + 0x10) if cb else None
        if not pgd:
            return None
        sel = self.i32(pgd + 0x44C)
        for k in range(5):
            if self.i32(pgd + 0x2E0 + 4 * k) == sel:
                return self.i32(pgd + 0x360 + 4 * k)
        return None

    def grip(self) -> Optional[int]:
        """Right-hand weapon grip: 3 = two-handed, 1 = one-handed. PlayerGameData+0x308 — found by comparing while releasing/regripping with Y (3→1→3, 2026-09-23).
        (arm_style() is for the Elden Ring interface and returns None — use this)"""
        cb = self.q(self.static["ChrClassBase"])
        pgd = self.q(cb + 0x10) if cb else None
        return self.i32(pgd + 0x308) if pgd else None

    def right_weapon(self) -> Optional[int]:
        """Right-hand weapon ID (PlayerGameData+0x328, Zweihander+5 = 350005)."""
        cb = self.q(self.static["ChrClassBase"])
        pgd = self.q(cb + 0x10) if cb else None
        return self.i32(pgd + 0x328) if pgd else None

    def event_flag(self, fid: int) -> Optional[bool]:
        """One entry of game records (event flags) — whether a treasure (ItemLotParam.ItemFlag) was picked up, boss/door/NPC state, etc.
        EventPocket (DSR) method: static EventFlags → pointer → pointer = base address; split the id into group/area/block/number for the bit position."""
        sid = f"{fid:08d}"
        if len(sid) != 8 or sid[0] not in EVENT_GROUPS or sid[1:4] not in EVENT_AREAS:
            return None
        p = self.q(self.static["EventFlags"])
        base = self.q(p) if p else None
        if not base:
            return None
        num = int(sid[5:8])
        off = EVENT_GROUPS[sid[0]] + EVENT_AREAS[sid[1:4]] * 0x500 + int(sid[4]) * 128 + (num - num % 32) // 8
        try:
            v = self.pm.read_uint(base + off)
        except pymem.exception.PymemError:
            return None
        return bool(v & (0x80000000 >> (num % 32)))

    STAT_OFF = {"VIT": 0x40, "ATN": 0x48, "END": 0x50, "STR": 0x58, "DEX": 0x60, "INT": 0x68, "FTH": 0x70, "RES": 0x88, "SL": 0x90}

    EQUIP_OFF = {"왼손1": 0x324, "오른손1": 0x328, "왼손2": 0x32C, "오른손2": 0x330, "화살": 0x344, "머리": 0x348, "몸": 0x34C, "팔": 0x350,
                 "반지1": 0x358, "반지2": 0x35C}   # 2026-09-25 dump: aligned to right hand 1 = 701000 (axe). Names of ring IDs 146/147 unconfirmed (user: wearing Wolf Ring)

    def equipment(self) -> dict:
        cb = self.q(self.static["ChrClassBase"])
        pgd = self.q(cb + 0x10) if cb else None
        return {k: self.i32(pgd + o) for k, o in self.EQUIP_OFF.items()} if pgd else {}

    def char_stats(self) -> dict:
        """Stats (PlayerGameData — if named stats it would be shadowed by feed.Feed.stats (feed statistics)), estimated from 2026-09-25 dump: 0x14 HP, 0x30 stamina, from 0x40 at 8-byte intervals VIT·ATN·END·STR·DEX·INT·FTH,
        0x88 RES, 0x90 SL, 0x94 souls, 0x98 total souls). VIT 20 ↔ HP 793, STR 16, SL 24 confirmed; check the other labels against the status screen."""
        cb = self.q(self.static["ChrClassBase"])
        pgd = self.q(cb + 0x10) if cb else None
        if not pgd:
            return {}
        out = {k: self.i32(pgd + o) for k, o in self.STAT_OFF.items()}
        out["소울"] = self.i32(pgd + 0x94)
        out["누적소울"] = self.i32(pgd + 0x98)
        out["인간성"] = self.humanity()
        return out

    def humanity(self) -> Optional[int]:
        """Humanity (number at top-left of the screen) — PlayerGameData+0x84 (JKAnderson/DSR-Gadget DSROffsets.ChrData2.Humanity).
        Dying or using Darksign sets it to 0 and it stays in the bloodstain."""
        cb = self.q(self.static["ChrClassBase"])
        pgd = self.q(cb + 0x10) if cb else None
        return self.i32(pgd + 0x84) if pgd else None

    def souls(self) -> Optional[int]:
        """Souls held — PlayerGameData+0x94 (DSR-Gadget ChrData2.Souls)."""
        cb = self.q(self.static["ChrClassBase"])
        pgd = self.q(cb + 0x10) if cb else None
        return self.i32(pgd + 0x94) if pgd else None

    def goods_count(self, item: int) -> Optional[int]:
        """Consumable (goods) count. Inventory entry in PlayerGameData, 0x1C bytes = (category 0x40000000, ID, count, ...).
        Measured 2026-09-23: +0xF08 Firebomb 292 x2, +0xED0 Estus 205 x10, Knife 290 x57. 0 if no entry.
        (the quick-slot ID alone doesn't tell the remaining count)"""
        cb = self.q(self.static["ChrClassBase"])
        pgd = self.q(cb + 0x10) if cb else None
        if not pgd:
            return None
        try:
            raw = self.pm.read_bytes(pgd, 0x8000)
        except pymem.exception.PymemError:
            return None
        for o in range(0x600, 0x8000 - 12, 4):
            cat, iid, qty = struct.unpack_from("<Iii", raw, o)
            if cat == 0x40000000 and iid == item and 0 <= qty < 10000:
                return qty
        return 0

    def set_last_bonfire(self, bonfire_id: int) -> bool:
        """Change the last bonfire ID — Homeward Bone/Darksign go to that bonfire (not the death respawn point). User 2026-09-24: use this instead of warping when crossing areas."""
        w = self.static.get("ChrClassWarp")
        w = self.q(w) if w else None
        if not w:
            return False
        self.pm.write_int(w + OFF_LASTBONFIRE, bonfire_id)
        return self.i32(w + OFF_LASTBONFIRE) == bonfire_id

    def last_bonfire(self) -> Optional[int]:
        w = self.q(self.static["ChrClassWarp"])
        return self.i32(w + OFF_LASTBONFIRE) if w else None

    # ── writes (for resets) ──
    # ChrDbg byte flags (DSR-Gadget order — +0x1 PlayerExterminate confirmed by measurement with kill_player)
    DBG_PLAYER_NO_DEAD, DBG_PLAYER_HIDE, DBG_ALL_NO_DAMAGE = 0x0, 0x6, 0x9

    def set_dbg(self, off: int, on: bool) -> None:
        """Turn a debug flag on/off (offline only). User: "make the character invincible and have it climb up in that state"."""
        self.pm.write_uchar(self.static["ChrDbg"] + off, 1 if on else 0)

    def get_dbg(self, off: int) -> int:
        return self.pm.read_uchar(self.static["ChrDbg"] + off)

    def kill_player(self) -> None:
        """ChrDbg.PlayerExterminate — turn on, then off after confirming death (if left on, it dies again right after respawning)."""
        a = self.static["ChrDbg"] + 0x1
        self.pm.write_uchar(a, 1)
        for _ in range(40):
            time.sleep(0.1)
            s = self.snapshot(within=1.0)
            if s and s.player.hp <= 0:
                break
        self.pm.write_uchar(a, 0)

    def bonfire_warp(self, bonfire_id: int, timeout: float = 40.0, log=print, unlit_ok: bool = False) -> bool:
        """**Teleport across areas** — calls the game's bonfire warp function directly (same path as the bonfire menu warp, including the loading screen).

        pos_warp only changes coordinates, so in distant areas you fall through the ground (2026-09-25, lost 3840 souls). This makes the game load the destination
        area. Method is exactly DSR-Gadget (JKAnderson) DSRHook.BonfireWarp: change the last bonfire, write machine code into the game that calls
        func(*ChrClassBase, 1), and run it as a thread. Souls/humanity are not lost."""
        import bonfires
        if not unlit_ok and bonfire_id not in bonfires.load():
            log(f"   화톳불 워프 {bonfire_id}: 불 붙인 목록(bonfires.py)에 없음 — 안 감 (unlit_ok=True 로 강제)")
            return False
        if not self.set_last_bonfire(bonfire_id):
            return False
        fn = pymem.pattern.pattern_scan_module(self.pm.process_handle, self.mod, self._aob(BONFIRE_WARP_AOB))
        if not fn:
            log("   화톳불 워프: 함수 AOB 못 찾음 — 게임 버전?")
            return False
        # movabs rcx,<ChrClassBase>; mov rcx,[rcx]; mov edx,1; sub rsp,0x38; movabs r14,<fn>; call r14; add rsp,0x38; ret
        code = (b"\x48\xB9" + struct.pack("<Q", self.static["ChrClassBase"]) + b"\x48\x8B\x09" + b"\xBA\x01\x00\x00\x00"
                + b"\x48\x83\xEC\x38" + b"\x49\xBE" + struct.pack("<Q", fn) + b"\x41\xFF\xD6" + b"\x48\x83\xC4\x38" + b"\xC3")
        mem = self.pm.allocate(len(code))
        try:
            self.pm.write_bytes(mem, code, len(code))
            self.pm.start_thread(mem)
        finally:
            self.pm.free(mem)
        t0, gone = time.time(), False
        while time.time() - t0 < timeout:
            s = self.snapshot(within=1.0)
            if s is None:
                gone = True
            elif gone:
                time.sleep(1.0)                          # just landed — let the coordinates settle
                s = self.snapshot(within=1.0)
                if s:
                    log(f"   화톳불 워프 {bonfire_id}: {time.time() - t0:.1f} s → ({s.player.x:.1f},{s.player.y:.1f},{s.player.z:.1f})")
                    return True
            time.sleep(0.05)
        log(f"   화톳불 워프 {bonfire_id}: {timeout:.0f} s 안에 안 끝남 (로딩 시작={gone})")
        return False

    def quit_to_title(self, timeout: float = 10.0) -> bool:
        """**Quit-out without going through the menu** — writing 1 to ChrClassWarp+0x19 makes the game exit straight to the title screen.

        Reverse engineering (2026-09-25, warp_re.py): at first misread as a Darksign warp request — when the user pressed it, it was the title's first screen
        ("pressing that brings up the menu's first screen. Nice, I needed that"). Loading starts within 0.6 s.
        quitout.py presses through the menu with the pad, takes 2~2.8 s, and the menu wouldn't open while falling — this needs no menu.
        Still unknown: does it work while falling/being hit, and can Continue at the title be pressed automatically (the latter part of quitout.py)."""
        w = self.q(self.static["ChrClassWarp"])
        if not w:
            return False
        self.pm.write_uchar(w + QUIT_REQ, 1)
        # don't call it "exited" after one invisible frame — during the transition to title it briefly vanished and reappeared, so Continue (quitout.reload)
        # ended with "already in world" (0.0 s) and the game stalled at the title. With no character the bot thought it died and ended the run (2026-09-25, two runs)
        t0, gone = time.time(), None
        while time.time() - t0 < timeout:
            if self.snapshot(within=1.0) is None:
                gone = gone or time.time()
                if time.time() - gone >= QUIT_GONE_S:
                    return True
            else:
                gone = None
            time.sleep(0.02)
        return False

    def safe_warp(self, x: float, y: float, z: float, angle: float = 0.0, hold_s: float = 8.0, log=print) -> bool:
        """**Use this for teleporting** — pos_warp only changes coordinates, so in a distant area whose collision hasn't loaded you fall through the ground.

        2026-09-25: Undead Burg room → Firelink Shrine bonfire (137 m) via pos_warp → fell to y −138 and died, lost 3840 souls.
        1) Turn on PlayerNoDead meanwhile (falling won't kill; stays at HP 1) — restore the original value when done.
        2) Keep rewriting the target coordinates to hold it there; release for 0.3 s and if it doesn't drop more than 1 m, the floor has loaded → success.
        3) If the floor doesn't settle within hold_s, go back to the start spot the same way and return False."""
        s = self.snapshot(within=1.0)
        if not s:
            return False
        home = (s.player.x, s.player.y, s.player.z, s.player.heading or 0.0)
        nodead = self.get_dbg(self.DBG_PLAYER_NO_DEAD)
        self.set_dbg(self.DBG_PLAYER_NO_DEAD, True)
        landed = False
        try:
            if self._hold_warp(x, y, z, angle, hold_s):
                landed = True
                return True
            log(f"   순간이동: ({x:.1f},{y:.1f},{z:.1f}) 바닥이 {hold_s:.0f} s 안에 안 섬 — 출발 자리로 되돌림")
            landed = self._hold_warp(*home, hold_s)
            if not landed:
                log("   순간이동: 되돌아가기도 실패 — 사람이 봐야 함 (PlayerNoDead 는 켜 둔다)")
            return False
        finally:
            if landed:                                # restore only when feet are on the ground — turning it off mid-fall kills
                self.set_dbg(self.DBG_PLAYER_NO_DEAD, bool(nodead))

    def _hold_warp(self, x, y, z, angle, hold_s) -> bool:
        t0 = time.time()
        while time.time() - t0 < hold_s:
            for _ in range(10):                       # hold 0.5 s — the area loads meanwhile
                self.pos_warp(x, y, z, angle)
                time.sleep(0.05)
            time.sleep(0.3)                           # release to test
            s = self.snapshot(within=1.0)
            if s and math.hypot(s.player.x - x, s.player.z - z) < 1.5 and y - s.player.y < 1.0:
                time.sleep(0.5)                       # once more — check whether freshly loaded floor collapses
                s = self.snapshot(within=1.0)
                if s and y - s.player.y < 1.0:
                    return True
        return False

    def pos_warp(self, x: float, y: float, z: float, angle: float = 0.0) -> bool:
        """Low layer that only changes coordinates — for short moves within the same area (terrain scan). For long moves, safe_warp."""
        pp = self.player_ptr()
        mapd = self.q(pp + OFF_MAPDATA) if pp else None
        if not mapd:
            return False
        self.pm.write_float(mapd + 0x110, x)
        self.pm.write_float(mapd + 0x114, y)
        self.pm.write_float(mapd + 0x118, z)
        self.pm.write_float(mapd + 0x124, angle)
        self.pm.write_uchar(mapd + 0x108, 1)
        return True

    def set_hp(self, hp: int) -> bool:
        """Invincibility for terrain scan — call every frame to pin HP (prevents fall deaths/instant-death traps during a scan)."""
        pp = self.player_ptr()
        if not pp:
            return False
        try:
            self.pm.write_int(pp + OFF_HP, hp)
            return True
        except pymem.exception.PymemError:
            return False


if __name__ == "__main__":
    tm = DSRTelemetry()
    print("symbols:", tm.symbols, "lastBonfire:", tm.last_bonfire())
    while True:
        s = tm.snapshot()
        if not s:
            print("(loading / no player)")
        else:
            p = s.player
            line = (f"P hp={p.hp}/{p.max_hp} sp={p.sp}/{p.max_sp} pos=({p.x:.1f},{p.y:.1f},{p.z:.1f}) heading={p.heading:.2f} "
                    f"cam_yaw={s.cam_yaw} anim={p.anim} | near={len(s.chars)} hostile20={len(s.hostile(20))}")
            for c in s.chars[:5]:
                line += f"\n   {c.dist:5.1f}m {c.team_name:12} {c.npc_param} {tm.model(c.ptr)} hp={c.hp}/{c.max_hp} anim={c.anim}"
            print(line, flush=True)
        time.sleep(0.5)
