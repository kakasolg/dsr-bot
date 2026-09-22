"""
다크소울 리마스터(DSR) 텔레메트리 — pymem 으로 DarkSoulsRemastered.exe 에 직접 붙는다 (EAC 없음, CE/브릿지 불필요).
읽기 전용 + 리셋용 쓰기 두 개(즉사 플래그, 좌표 워프). **반드시 오프라인으로 실행** (온라인 소프트밴).

포인터 지도는 JKAnderson/DSR-Gadget 의 DSROffsets.cs 에서 (AOB → RIP 상대 주소 → 정적 포인터). 실측 2026-09-21, 모듈 크기 0x319B000
(DSR-Gadget 이 아는 1.03 보다 새 버전 — 1.03 용 보정 오프셋(+0x20/+0x10)이 그대로 맞았다).

  WorldChrMan  = [WorldChrBase]                (AOB 48 8B 05 ? ? ? ? 48 8B 48 68 ...)
  Player       = [WorldChrMan+0x68]            (ChrIns)
  캐릭터 목록   = [[WorldChrMan+0xA8]+0x50]      항목 0x38 바이트, 첫 8바이트 = ChrIns 포인터. 개수 = [WorldChrMan+0xA8]+0x48 (int)
  ChrIns:
    +0x00  vtable  (PlayerIns 0x1413251F0 / EnemyIns 0x141322E68 — 베이스 상대로 저장)
    +0x88  모델 이름 (UTF-16, "c2500" 등)
    +0xC8  NpcParam ID (int32, 예: 250023 할로우, 279070 낙담한 전사) — 적/비적 판정 키
    +0x68  → ChrMapData: +0x28 → ChrPosData(+0x4 각도, +0x10 x, +0x14 y(높이), +0x18 z)
                          +0x48 → +0x80 현재 애니메이션 ID
                          +0x108 Warp(byte) +0x110/114/118 WarpXYZ +0x124 WarpAngle  (좌표 순간이동)
    +0x3E8 HP  +0x3EC MaxHP  +0x3F8 스태미나  +0x3FC 최대 스태미나   (DSR-Gadget 0x3D8/0x3DC/0x3E8/0x3EC + 보정 0x10)
    +0x2A4  ChrFlags1 — 0x8000 이 켜진 것만 실제로 스폰된 캐릭터 (꺼진 건 목록엔 있지만 안 보이고 안 움직임)
    +0xA44  특수 동작 애니 ID (int32, 없으면 -1) — 화톳불에 앉아 있는 동안 77xx (위 화톳불 7711, 아래 7721). +0xA48 = 1 이면 그 동작 중.
            mapd 쪽 "현재 애니"(+0x48→+0x80) 는 공격 304000/에스트 7585/백스텝 690 은 보이지만 앉기는 안 보인다.
  ChrClassWarp = [static]: +0xB34 마지막 화톳불 ID (예: 1812960 = 불의 제전)
  ChrDbg (static 바이트 배열): +0x1 PlayerExterminate = 1 이면 즉사
  ChrFollowCam = [[[static]+0x60]+0x60]: +0x10 부터 4x4 행렬(float) — 3행 = 카메라 forward, 4행 = 위치. yaw = atan2(fwd.x, fwd.z)

팀 타입(적/아군) 바이트는 못 찾았다 → NpcParam ID 로 판정: FRIENDLY 에 있으면 비적, EnemyIns 인데 없으면 적.
스틱 실측: 앞 = 카메라 forward, 오른쪽 = +90° (엘든링과 같음).

── 알려진 한계 ──────────────────────────────
 · 로딩 중엔 포인터가 무효 → snapshot() 이 None.
 · 캐릭터 목록은 로드된 것 전부(멀리 있는 것 포함) — within 으로 거른다.
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

from telemetry import Chr, Snapshot   # 엘든링과 같은 모양 → nav/patrol 이 그대로 쓴다

AOBS = {
    "WorldChrBase": ("48 8B 05 ? ? ? ? 48 8B 48 68 48 85 C9 0F 84 ? ? ? ? 48 39 5E 10 0F 84 ? ? ? ? 48", 3, 7),
    "ChrClassWarp": ("48 8B 05 ? ? ? ? 66 0F 7F 80 ? ? ? ? 0F 28 02 66 0F 7F 80 ? ? ? ? C6 80", 3, 7),
    "ChrDbg": ("80 3D ? ? ? ? 00 48 8B 8F ? ? ? ? 0F B6 DB", 2, 7),
    "ChrFollowCam": ("48 8B 0D ? ? ? ? E8 ? ? ? ? 48 8B 4E 68 48 8B 05 ? ? ? ? 48 89 48 60", 3, 7),
    "ChrClassBase": ("48 8B 05 ? ? ? ? 48 85 C0 ? ? F3 0F 58 80 AC 00 00 00", 3, 7),
}
OFF_HP, OFF_MAXHP, OFF_SP, OFF_MAXSP = 0x3E8, 0x3EC, 0x3F8, 0x3FC
OFF_MAPDATA, OFF_MODEL, OFF_NPC = 0x68, 0x88, 0xC8
OFF_LASTBONFIRE = 0xB34
OFF_ANIM2 = 0xA44
OFF_FLAGS1 = 0x2A4      # DSR-Gadget ChrFlags1(0x284) + 보정 0x20
FLAG_ACTIVE = 0x8000    # 실측: 월드에 실제로 있는(애니가 도는) 캐릭터만 켜짐
FRIENDLY = {279070, 100000}   # 낙담한 전사, 사람 NPC(c1000) — 필요하면 data/dsr_friendly.json 으로


class DSRTelemetry:
    def __init__(self, names: Optional[dict[int, str]] = None):
        self.pm = pymem.Pymem("DarkSoulsRemastered.exe")
        self.mod = pymem.process.module_from_name(self.pm.process_handle, "DarkSoulsRemastered.exe")
        self.base = self.mod.lpBaseOfDll
        self.names = names or {}
        self.static: dict[str, int] = {}
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

    # ── 저수준 ──
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

    # ── 캐릭터 ──
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
            team = 26   # FriendlyNPC (엘든링 팀 번호를 흉내 — Snapshot.hostile() 이 6/7/24/25/27/33 만 적으로 본다)
        elif not (flags1 & FLAG_ACTIVE):
            team = 0    # 비활성(스폰 안 됨/이벤트로 꺼짐) — 목록엔 있지만 월드에 없다. 실측: 안 보이는 할로우가 0x800400, 움직이는 놈은 0x808400
        else:
            team = 6
        return Chr(ptr=p, npc_param=npc, team=team, hp=hp, max_hp=mhp, sp=self.i32(p + OFF_SP) or 0, max_sp=self.i32(p + OFF_MAXSP) or 0,
                   x=x, y=y, z=z, anim=anim, name=self.names.get(npc, ""), gx=x, gy=y, gz=z, heading=ang, map_id=0)

    def chr_ptrs(self) -> list[int]:
        w = self.world_chr_man()
        holder = self.q(w + 0xA8) if w else None
        arr = self.q(holder + 0x50) if holder else None
        n = self.i32(holder + 0x48) if holder else None
        if not arr or not n or n <= 0 or n > 2000:
            return []
        try:
            raw = self.pm.read_bytes(arr, n * 0x38)
        except pymem.exception.PymemError:
            return []
        out = []
        for i in range(n):
            v = struct.unpack_from("<Q", raw, i * 0x38)[0]
            if 0x10000 < v < 0x7FFFFFFFFFFF:
                out.append(v)
        return out

    def model(self, p: int) -> str:
        try:
            raw = self.pm.read_bytes(p + OFF_MODEL, 16)
            return raw.decode("utf-16le", "ignore").split("\x00")[0]
        except pymem.exception.PymemError:
            return ""

    # ── 카메라 ──
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
        chars = []
        for p in self.chr_ptrs():
            if p == pp:
                continue
            c = self.read_chr(p)
            if not c:
                continue
            c.dist = math.dist((player.x, player.y, player.z), (c.x, c.y, c.z))
            if c.dist <= within:
                chars.append(c)
        chars.sort(key=lambda c: c.dist)
        return Snapshot(t=time.time(), player=player, chars=chars, cam_yaw=self.cam_yaw(), cam_pitch=None)

    # ── 엘든링 텔레메트리와 인터페이스 맞추기 (patrol/learn 이 게임을 모르게) ──
    def arm_style(self) -> Optional[int]:
        return None   # DS1 은 왼손이 비어도 LB 가 가드(맨손 가드) — 양손 검사 불필요

    def flasks(self) -> tuple[Optional[int], Optional[int]]:
        return None, None   # TODO 에스트 수 (인벤토리 오프셋 미확인) — Guard 는 "효과 없음 → 빈 병" 휴리스틱으로 폴백

    def last_grace(self) -> Optional[int]:
        return self.last_bonfire()

    def sitting(self) -> bool:
        """화톳불에 앉아 있는가 — ChrIns+0xA48 == 1 이고 +0xA44 가 77xx (실측: 위 화톳불 7711, 아래 화톳불 7721)."""
        pp = self.player_ptr()
        if not pp:
            return False
        a = self.i32(pp + OFF_ANIM2)
        try:
            flag = self.pm.read_uchar(pp + OFF_ANIM2 + 4)   # 1바이트 — 상위 바이트엔 다른 값이 섞인다 (사망 뒤 0x1C260001 실측)
        except pymem.exception.PymemError:
            return False
        return flag == 1 and a is not None and 7700 <= a < 7800 and a % 10 == 1   # 7720 = 앉는 중(플래그 0), 77x1 = 앉음 (7701/7711/7721)

    def face(self, pad, heading: float, tries: int = 5, tol: float = 0.25) -> bool:
        """캐릭터를 heading(+0x4 각도, 실측 월드 yaw = heading + π) 방향으로 돌린다 — 스틱을 짧게 쳐서 제자리 회전.
        DS1 은 화톳불·문 상호작용 프롬프트가 정면 정렬을 요구한다 (사용자 실측)."""
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

    # ── 진행 상태 ──
    def last_bonfire(self) -> Optional[int]:
        w = self.q(self.static["ChrClassWarp"])
        return self.i32(w + OFF_LASTBONFIRE) if w else None

    # ── 쓰기 (리셋용) ──
    def kill_player(self) -> None:
        """ChrDbg.PlayerExterminate — 켰다가 사망 확인 후 끈다 (켜 둔 채면 리스폰하자마자 또 죽는다)."""
        a = self.static["ChrDbg"] + 0x1
        self.pm.write_uchar(a, 1)
        for _ in range(40):
            time.sleep(0.1)
            s = self.snapshot(within=1.0)
            if s and s.player.hp <= 0:
                break
        self.pm.write_uchar(a, 0)

    def pos_warp(self, x: float, y: float, z: float, angle: float = 0.0) -> bool:
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
        """지형 스캔용 무적 — 매 프레임 호출해서 HP 를 고정한다 (스캔 중 추락사/즉사 함정 방지)."""
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
