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
    +0x08  핸들 (int32, 예: 0x10008015)
    +0xEF0 (PlayerIns) 락온 대상의 핸들, 안 걸렸으면 -1 — R3 누르기 전후 PlayerIns 0x1000 바이트를 비교해 찾음 (2/2, 2026-09-23)
  ChrClassWarp = [static]: +0xB34 마지막 화톳불 ID (예: 1812960 = 불의 제전)
            **쓰면 귀환의 뼛조각이 그 화톳불로 간다** (실측: 어둠숲에서 이 값을 불의 제전으로 바꾸고
            뼛조각을 쓰니 불의 제전으로 이동). 다만 **사망 부활 지점은 아니다** — 값을 바꾸고 죽여도
            원래 자리에서 부활한다(2회 확인). 부활 지점은 다른 곳에 저장된다.
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
    # 게임 기록(이벤트 플래그) — JKAnderson/EventPocket DSOffsets.EventFlagsAOBR (DSR)
    "EventFlags": ("48 8B 0D ? ? ? ? 99 33 C2 45 33 C0 2B C2 8D 50 F6", 3, 7),
}
# 이벤트 플래그 id 8자리 = 그룹 1 · 지역 3 · 구역 1 · 번호 3 → 바이트 위치 (EventPocket DSProcess.getEventFlagAddress)
EVENT_GROUPS = {"0": 0x00000, "1": 0x00500, "5": 0x05F00, "6": 0x0B900, "7": 0x11300}
EVENT_AREAS = {"000": 0, "100": 1, "101": 2, "102": 3, "110": 4, "120": 5, "121": 6, "130": 7, "131": 8, "132": 9,
               "140": 10, "141": 11, "150": 12, "151": 13, "160": 14, "170": 15, "180": 16, "181": 17}
OFF_HP, OFF_MAXHP, OFF_SP, OFF_MAXSP = 0x3E8, 0x3EC, 0x3F8, 0x3FC
OFF_MAPDATA, OFF_MODEL, OFF_NPC = 0x68, 0x88, 0xC8
OFF_LASTBONFIRE = 0xB34
CHR_LIST_OFFSETS = (0xA8, 0xB0, 0xB8, 0xC0, 0xC8)   # WorldChrMan 안의 구역별 캐릭터 목록 (실측: 불의 제전은 0xB0)
OFF_ANIM2 = 0xA44
OFF_HANDLE, OFF_LOCK_TARGET = 0x8, 0xEF0
OFF_MENU_FLAG = 0x1A294F0   # 모듈 기준. 1=게임 조작 중, 0=메뉴 열림 (App ver 1.03.1 실측)
OFF_FLAGS1 = 0x2A4      # DSR-Gadget ChrFlags1(0x284) + 보정 0x20
FLAG_ACTIVE = 0x8000    # 실측: 월드에 실제로 있는(애니가 도는) 캐릭터만 켜짐
# 실측(불의 제전~묘지): 이 비트가 켜진 놈은 보이지도 맞지도 않는다 — c5330 HP 11120 (0x280c400), c3510 (0x2808800),
# 화톳불 옆 c2750 HP 32 (0x2808400). 진짜 적은 0x808400/0x808800. 봇이 c5330 을 1 m 앞에 두고 8 s 동안 헛스윙했다.
FLAG_GHOST = 0x2000000
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
        elif flags1 & FLAG_GHOST:
            team = 0
        else:
            team = 6
        return Chr(ptr=p, npc_param=npc, team=team, hp=hp, max_hp=mhp, sp=self.i32(p + OFF_SP) or 0, max_sp=self.i32(p + OFF_MAXSP) or 0,
                   x=x, y=y, z=z, anim=anim, name=self.names.get(npc, ""), gx=x, gy=y, gz=z, heading=ang, map_id=0)

    def chr_ptrs(self) -> list[int]:
        """로드된 **모든** 구역의 캐릭터. DS1 은 인접 구역을 같이 올려 두고 목록도 구역마다 따로 둔다.

        실측(불의 제전): +0xA8 은 174명이지만 전부 64 m 밖이고, 지금 서 있는 구역은 +0xB0 의 41명이었다
        (가장 가까운 NPC 5.1 m). 아스라이에선 마침 +0xA8 이 그 구역이라 하나만 읽어도 됐던 것 —
        그래서 불의 제전·묘지에서 적이 하나도 안 잡혔고, 봇이 해골에게 맞으면서도 "적 없음"으로 판단했다."""
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
        # 좌표만 먼저 싸게 읽고 가까운 것만 전체를 읽는다. 구역별 목록을 다 읽게 고친 뒤 목록이 391명까지
        # 늘어서, 전부 read_chr 하면 snapshot 하나에 14 ms 가 걸렸다 (틱이 65 ms 로 떨어짐, 초당 15회).
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
            if math.hypot(x - px, z - pz) > within + 2.0:   # 높이 차는 뒤에서 정확히 본다
                continue
            c = self.read_chr(p)
            if not c:
                continue
            c.dist = math.dist((px, py, pz), (c.x, c.y, c.z))
            if c.dist <= within:
                chars.append(c)
        chars.sort(key=lambda c: c.dist)
        return Snapshot(t=time.time(), player=player, chars=chars, cam_yaw=self.cam_yaw(), cam_pitch=None)

    # ── 엘든링 텔레메트리와 인터페이스 맞추기 (patrol/learn 이 게임을 모르게) ──
    def arm_style(self) -> Optional[int]:
        return None   # DS1 은 왼손이 비어도 LB 가 가드(맨손 가드) — 양손 검사 불필요

    def flasks(self) -> tuple[Optional[int], Optional[int]]:
        return None, None   # TODO 에스트 수 (인벤토리 오프셋 미확인) — Guard 는 "효과 없음 → 빈 병" 휴리스틱으로 폴백

    def handle(self, p: int) -> Optional[int]:
        return self.i32(p + OFF_HANDLE) if p else None

    def lock_target(self) -> Optional[int]:
        """락온 대상의 핸들, 안 걸렸으면 -1. R3 는 토글이라 이걸 봐야 몇 번 누를지 안다."""
        pp = self.player_ptr()
        return self.i32(pp + OFF_LOCK_TARGET) if pp else None

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
    def menu_open(self) -> Optional[bool]:
        """메뉴(START)가 열려 있나. 실측: 모듈 +0x1A294F0 바이트가 평소 1, 메뉴가 열리면 10 ms 안에 0 —
        시스템·확인창 같은 하위 메뉴에서도 0 을 유지하고, 완전히 닫혀야 1 로 돌아온다 (정적 메모리 diff 로 찾음).
        quit-out 에서 START 가 먹었는지 확인하는 데 쓴다 — 로드 직후엔 START 가 씹혀서 나머지 입력이 게임에 샜다."""
        try:
            return self.pm.read_uchar(self.base + OFF_MENU_FLAG) == 0
        except pymem.exception.PymemError:
            return None

    def quick_items(self) -> list[int]:
        """소모품 5칸의 아이템 ID (빈 칸은 -1). 에스트를 빼고 다크사인을 넣는 식으로 사용자가 바꾼다."""
        cb = self.q(self.static["ChrClassBase"])
        pgd = self.q(cb + 0x10) if cb else None
        return [self.i32(pgd + 0x360 + 4 * k) for k in range(5)] if pgd else []

    def selected_item(self) -> Optional[int]:
        """지금 선택된 소모품 칸의 아이템 ID (에스트 200~215, 파이어밤 292, 투척 나이프 290).

        실측(PlayerGameData = [ChrClassBase]+0x10): +0x2E0 부터 소모품 5칸의 **인벤토리 인덱스**,
        +0x360 부터 같은 5칸의 **아이템 ID**, +0x44C 가 지금 선택된 칸의 인벤토리 인덱스.
        (D-패드 ↓ 를 누르며 76 → 78 → 132 → 76 으로 바뀌는 것을 diff 로 찾음. 빈 칸은 건너뛴다)
        버튼만 누르고 믿으면 안 된다 — 초기화 직후 ↓ 가 씹혀서 폭탄 대신 에스트를 마신 적이 있다."""
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
        """오른손 무기 잡기: 3 = 양손, 1 = 한손. PlayerGameData+0x308 — Y 로 풀었다 잡으며 비교해 찾음 (3→1→3, 2026-09-23).
        (arm_style() 은 엘든링 인터페이스용이라 None 을 돌려준다 — 이걸 쓴다)"""
        cb = self.q(self.static["ChrClassBase"])
        pgd = self.q(cb + 0x10) if cb else None
        return self.i32(pgd + 0x308) if pgd else None

    def right_weapon(self) -> Optional[int]:
        """오른손 무기 ID (PlayerGameData+0x328, 츠바이헨더+5 = 350005)."""
        cb = self.q(self.static["ChrClassBase"])
        pgd = self.q(cb + 0x10) if cb else None
        return self.i32(pgd + 0x328) if pgd else None

    def event_flag(self, fid: int) -> Optional[bool]:
        """게임 기록(이벤트 플래그) 한 칸 — 보물(ItemLotParam.ItemFlag)을 주웠나, 보스·문·NPC 상태 등.
        EventPocket(DSR) 방식: static EventFlags → 포인터 → 포인터 = 기본 주소, id 를 그룹·지역·구역·번호로 나눠 비트 위치."""
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

    def stats(self) -> dict:
        """스탯 (PlayerGameData, 2026-09-25 덤프로 추정: 0x14 HP, 0x30 스태미나, 0x40 부터 8 바이트 간격 VIT·ATN·END·STR·DEX·INT·FTH,
        0x88 RES, 0x90 SL, 0x94 소울, 0x98 누적 소울). VIT 20 ↔ HP 793, STR 16, SL 24 는 확인; 나머지 라벨은 상태 화면과 대조할 것."""
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
        """인간성 (화면 왼쪽 위 숫자) — PlayerGameData+0x84 (JKAnderson/DSR-Gadget DSROffsets.ChrData2.Humanity).
        죽거나 다크사인을 쓰면 0 이 되고 핏자국에 남는다."""
        cb = self.q(self.static["ChrClassBase"])
        pgd = self.q(cb + 0x10) if cb else None
        return self.i32(pgd + 0x84) if pgd else None

    def souls(self) -> Optional[int]:
        """가진 소울 — PlayerGameData+0x94 (DSR-Gadget ChrData2.Souls)."""
        cb = self.q(self.static["ChrClassBase"])
        pgd = self.q(cb + 0x10) if cb else None
        return self.i32(pgd + 0x94) if pgd else None

    def goods_count(self, item: int) -> Optional[int]:
        """소모품(goods) 개수. PlayerGameData 안 인벤토리 항목 0x1C 바이트 = (분류 0x40000000, ID, 개수, ...).
        실측 2026-09-23: +0xF08 파이어밤 292 x2, +0xED0 에스트 205 x10, 나이프 290 x57. 항목이 없으면 0.
        (퀵슬롯 ID 만으로는 남은 개수를 모른다)"""
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
        """마지막 화톳불 ID 를 바꾼다 — 뼛조각·다크사인이 그 화톳불로 간다 (사망 부활 지점은 아님). 사용자 2026-09-24: 구역을 건너갈 때 워프 대신 이걸로."""
        w = self.static.get("ChrClassWarp")
        w = self.q(w) if w else None
        if not w:
            return False
        self.pm.write_int(w + OFF_LASTBONFIRE, bonfire_id)
        return self.i32(w + OFF_LASTBONFIRE) == bonfire_id

    def last_bonfire(self) -> Optional[int]:
        w = self.q(self.static["ChrClassWarp"])
        return self.i32(w + OFF_LASTBONFIRE) if w else None

    # ── 쓰기 (리셋용) ──
    # ChrDbg 바이트 플래그 (DSR-Gadget 순서 — +0x1 PlayerExterminate 는 kill_player 로 실측 확인)
    DBG_PLAYER_NO_DEAD, DBG_PLAYER_HIDE, DBG_ALL_NO_DAMAGE = 0x0, 0x6, 0x9

    def set_dbg(self, off: int, on: bool) -> None:
        """디버그 플래그 켜기/끄기 (오프라인 전용). 사용자: "캐릭터 무적 상태로 만들고 그 상태로 올라가게"."""
        self.pm.write_uchar(self.static["ChrDbg"] + off, 1 if on else 0)

    def get_dbg(self, off: int) -> int:
        return self.pm.read_uchar(self.static["ChrDbg"] + off)

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
