"""
엘든링 텔레메트리 리더 (pymem).

Cheat Engine 브릿지가 내보낸 symbols.json(테이블의 AOB 스캔 결과)을 재사용해서
플레이어·주변 캐릭터 상태를 초당 수십 회 읽는다. 아무것도 쓰지 않는다 (읽기 전용).

포인터 경로는 Hexinton All in One 8.0.4 테이블의 NPC Manager / Character Data 스크립트에서 가져왔다.

  WorldChrMan  = [symbol]
  ChrIns[]     = [[WorldChrMan]+0x1F1B8] .. [[WorldChrMan]+0x1F1C0]  (8바이트 포인터 배열)
  Player       = [[[WorldChrMan]+0x10EF8]+0]  (LocalPlayerOffset 은 PlayerIns 슬롯을 가리키고, 그 안의 첫 포인터가 ChrIns)
  ChrIns:
    +0x60  NpcParamId (int32)  → 이름표 (CharNames)
    +0x6C  team (byte)         6=Enemy, 47=Spirit Summon, 1=Live(플레이어) …
    +0x74  chrType? (int16)
    +0x190 → modules
        [modules+0x00] → +0x138 HP (int32), +0x13C MaxHP (int32)
        [modules+0x18] → +0x40  (int32, 애니메이션 관련 추정 — 검증 중)
        [modules+0x68] → +0x70 x, +0x74 y, +0x78 z (float)
        [modules+0x80] → +0x90 현재 애니메이션 ID (플레이어 Character Data 기준)

── 알려진 한계 ──────────────────────────────
 · 로딩 중에는 포인터가 잠깐 무효라 읽기가 실패한다 → snapshot() 이 None 을 돌려준다.
 · 테이블이 갱신되어 오프셋이 바뀌면 여기도 맞춰야 한다.
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔 cp1252 대비

import json
import math
import os
import struct
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import pymem
import pymem.exception

SYMBOLS_FILE = Path(os.environ.get("CHAOS_BRIDGE_DIR") or Path(os.environ["TEMP"]) / "chzzk-souls-chaos") / "symbols.json"

OFF_CHR_BEGIN = 0x1F1B8
OFF_CHR_END = 0x1F1C0
OFF_LOCAL_PLAYER = 0x10EF8

TEAM_NAMES = {
    0: "None", 1: "Live", 2: "WhiteGhost", 3: "BlackGhost", 6: "Enemy", 7: "Boss", 8: "Ally",
    12: "BattleAlly", 24: "Enemy2", 25: "StrongEnemy", 26: "FriendlyNPC", 27: "HostileNPC", 47: "SpiritSummon",
}


@dataclass
class Chr:
    ptr: int
    npc_param: int
    team: int
    hp: int
    max_hp: int
    x: float
    y: float
    z: float
    anim: Optional[int] = None
    dist: float = 0.0
    name: str = ""

    @property
    def team_name(self) -> str:
        return TEAM_NAMES.get(self.team, str(self.team))


@dataclass
class Snapshot:
    t: float
    player: Chr
    chars: list[Chr] = field(default_factory=list)  # 플레이어 제외, 거리순

    def hostile(self, within: float = 30.0) -> list[Chr]:
        return [c for c in self.chars if c.team in (6, 7, 24, 25, 27, 33) and c.hp > 0 and c.dist <= within]

    def to_dict(self) -> dict:
        return {"t": self.t, "player": asdict(self.player), "chars": [asdict(c) for c in self.chars]}


class Telemetry:
    def __init__(self, names: Optional[dict[int, str]] = None):
        self.pm = pymem.Pymem("eldenring.exe")
        self.names = names or {}
        self.symbols = self._load_symbols()
        self.world_chr_man = int(self.symbols["WorldChrMan"], 16)

    @staticmethod
    def _load_symbols() -> dict:
        if not SYMBOLS_FILE.exists():
            raise RuntimeError(f"{SYMBOLS_FILE} 없음 — 브릿지에 'symbols' 명령을 보내세요 (npm run attach 가 자동으로 함)")
        s = json.loads(SYMBOLS_FILE.read_text())
        if not s.get("WorldChrMan"):
            raise RuntimeError("symbols.json 에 WorldChrMan 이 없음 — 테이블 [ Enable ] 이 켜져 있는지 확인")
        return s

    # ── 저수준 읽기 (실패 시 None) ──
    def q(self, addr: int) -> Optional[int]:
        try:
            v = self.pm.read_ulonglong(addr)
            return v if v > 0x10000 else None
        except pymem.exception.PymemError:
            return None

    def i32(self, addr: int) -> Optional[int]:
        try:
            return self.pm.read_int(addr)
        except pymem.exception.PymemError:
            return None

    def f32(self, addr: int) -> Optional[float]:
        try:
            return self.pm.read_float(addr)
        except pymem.exception.PymemError:
            return None

    def u8(self, addr: int) -> Optional[int]:
        try:
            return self.pm.read_uchar(addr)
        except pymem.exception.PymemError:
            return None

    # ── ChrIns 해석 ──
    def read_chr(self, p: int) -> Optional[Chr]:
        modules = self.q(p + 0x190)
        if not modules:
            return None
        stats = self.q(modules + 0x00)
        phys = self.q(modules + 0x68)
        if not stats or not phys:
            return None
        hp, max_hp = self.i32(stats + 0x138), self.i32(stats + 0x13C)
        x, y, z = self.f32(phys + 0x70), self.f32(phys + 0x74), self.f32(phys + 0x78)
        if None in (hp, max_hp, x, y, z):
            return None
        npc = self.i32(p + 0x60) or 0
        team = self.u8(p + 0x6C) or 0
        anim = None
        m80 = self.q(modules + 0x80)
        if m80:
            anim = self.i32(m80 + 0x90)
        return Chr(ptr=p, npc_param=npc, team=team, hp=hp, max_hp=max_hp, x=x, y=y, z=z, anim=anim,
                   name=self.names.get(npc, ""))

    def player_ptr(self) -> Optional[int]:
        wcm = self.q(self.world_chr_man)
        slot = self.q(wcm + OFF_LOCAL_PLAYER) if wcm else None
        return self.q(slot + 0) if slot else None

    def chr_ptrs(self) -> list[int]:
        wcm = self.q(self.world_chr_man)
        if not wcm:
            return []
        begin, end = self.q(wcm + OFF_CHR_BEGIN), self.q(wcm + OFF_CHR_END)
        if not begin or not end or end <= begin or (end - begin) > 8 * 4096:
            return []
        n = (end - begin) // 8
        try:
            raw = self.pm.read_bytes(begin, n * 8)
        except pymem.exception.PymemError:
            return []
        return [p for p in struct.unpack(f"<{n}Q", raw) if p > 0x10000]

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
            if not c or c.max_hp <= 0:
                continue
            c.dist = math.dist((player.x, player.y, player.z), (c.x, c.y, c.z))
            if c.dist <= within:
                chars.append(c)
        chars.sort(key=lambda c: c.dist)
        return Snapshot(t=time.time(), player=player, chars=chars)


def load_names(ct_path: Optional[str] = None) -> dict[int, str]:
    """Hexinton 테이블의 CharNames 드롭다운(NpcParamId → 이름)을 읽는다. 없으면 빈 dict."""
    if not ct_path and not os.environ.get("HEXINTON_CT"):
        try:
            from dotenv import load_dotenv  # type: ignore
            load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        except ImportError:
            pass
    ct_path = ct_path or os.environ.get("HEXINTON_CT")
    if not ct_path or not Path(ct_path).exists():
        return {}
    import xml.etree.ElementTree as ET
    names: dict[int, str] = {}
    for ce in ET.parse(ct_path).iter("CheatEntry"):
        if ce.findtext("ID") == "22021343":
            dd = ce.find("DropDownList")
            if dd is not None and dd.text:
                for line in dd.text.strip().splitlines():
                    k, _, v = line.partition(":")
                    if k.strip().isdigit():
                        names[int(k)] = v.strip()
            break
    return names


if __name__ == "__main__":
    # 실시간 표시: python telemetry.py
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    tm = Telemetry(load_names())
    print("symbols:", tm.symbols)
    while True:
        s = tm.snapshot()
        if not s:
            print("(loading / no player)")
        else:
            p = s.player
            line = f"P hp={p.hp}/{p.max_hp} pos=({p.x:.1f},{p.y:.1f},{p.z:.1f}) anim={p.anim} | near={len(s.chars)}"
            for c in s.chars[:4]:
                line += f"\n   {c.dist:5.1f}m {c.team_name:12} {c.npc_param} {c.name[:20]:20} hp={c.hp}/{c.max_hp} anim={c.anim}"
            print(line)
        time.sleep(0.5)
