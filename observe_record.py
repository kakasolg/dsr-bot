"""
관찰 기록기 (Phase 1) — 사람이 플레이하는 동안 게임 메모리와 컨트롤러·F9 를 **읽기만** 해서 한 파일에 남긴다.
사용자 2026-09-26: 전투 정책·학습이 아니라 관찰(observability) 실험. 뷰어(Phase 2)가 이 파일을 읽는다.

  python observe_record.py [--radius 30] [--minutes N] [--out data/observe]

출력: data/observe/<YYYYmmdd_HHMMSS>.jsonl  (스키마·수동 점검표: OBSERVE.md)
  hdr  첫 줄 — 세션 정보, 벽시계 기준점(wall_ns)
  w    10 Hz 월드 스냅샷 — 플레이어, 락온, 반경 안 캐릭터 전부 + 락온 대상 (원시 값만)
  pad  120 Hz 로 보고 바뀔 때만 — XInput 원시 값
  mk   F9 누름(상승 에지, 300 ms 디바운스) — 표시만
  sys  loading/loaded/sync/pad_lost/pad_found/error/end

읽기 전용 보장:
  · 게임 프로세스를 PROCESS_VM_READ | PROCESS_QUERY_INFORMATION 으로만 연다 (쓰기 권한 없는 핸들, SeDebugPrivilege 안 켬).
  · DSRTelemetry.__init__ 을 부르지 않는다 — 읽기 메서드만 통과시키는 GameReader 로 감싼다. 나머지 이름은 AttributeError.
  · 가상 패드·control·env·feed·souls·botlock 을 import 하지 않는다. 키보드는 GetAsyncKeyState 폴링만 (훅·SendInput 없음).

기록 규칙:
  · 적 읽기가 실패하면 그 스냅샷에서 빼기만 한다 — 추정·보간 값을 쓰지 않는다 (뷰어가 빈칸으로 보여준다).
  · 원시 애니 번호만 남긴다. 공격 중·후딜·빈틈 같은 의미 판정은 하지 않는다.
  · alive_derived 는 hp>0 로 만든 값이다 (alive_rule). 원시 사망 플래그는 아직 모른다.
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import argparse
import ctypes
import json
import math
import queue
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data" / "observe"

SCHEMA_V = 1
WORLD_HZ = 10
PAD_HZ = 120
SYNC_S = 10.0
MARKER_DEBOUNCE_MS = 300.0
VK_F9 = 0x78
READ_ACCESS = 0x0010 | 0x0400          # PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
ALIVE_RULE = "hp_gt_zero"


# ── 게임 읽기 (읽기 전용) ─────────────────────────────────────────────

class GameReader:
    """DSRTelemetry 의 읽기 메서드만 통과시킨다. 쓰기·워프·디버그 플래그 메서드는 이름부터 막는다."""
    ALLOWED = frozenset({"player_ptr", "chr_ptrs", "read_chr", "handle", "lock_target", "cam_yaw", "q", "i32", "f32"})

    def __init__(self, tm, pid: Optional[int] = None):
        object.__setattr__(self, "_tm", tm)
        object.__setattr__(self, "pid", pid)

    def __getattr__(self, name):
        if name not in GameReader.ALLOWED:
            raise AttributeError(f"GameReader: '{name}' 는 읽기 전용 관찰기에서 막혀 있다")
        return getattr(self._tm, name)

    def __setattr__(self, name, value):
        raise AttributeError("GameReader 는 고칠 수 없다")

    # 스냅샷 전에 싸게 거르는 좌표 — dsr_telemetry.snapshot 과 같은 경로
    def pos_xz(self, p: int) -> Optional[tuple[float, float]]:
        import dsr_telemetry as D
        tm = self._tm
        mapd = tm.q(p + D.OFF_MAPDATA)
        posd = tm.q(mapd + 0x28) if mapd else None
        if not posd:
            return None
        x, z = tm.f32(posd + 0x10), tm.f32(posd + 0x18)
        if x is None or z is None or not (math.isfinite(x) and math.isfinite(z)):
            return None
        return x, z

    def flags1(self, p: int) -> Optional[int]:
        import dsr_telemetry as D
        v = self._tm.i32(p + D.OFF_FLAGS1)
        return None if v is None else v & 0xFFFFFFFF

    def vt_kind(self, p: int) -> Optional[str]:
        vt = self._tm.q(p)
        if vt is None:
            return None
        return "player" if vt == self._tm.vt_player else "enemy" if vt == self._tm.vt_enemy else "other"


def open_game_reader() -> GameReader:
    """쓰기 권한 없는 핸들로 DSR 을 연다. DSRTelemetry.__init__ 은 PROCESS_ALL_ACCESS + SeDebugPrivilege 라 쓰지 않는다."""
    import pymem
    import pymem.pattern
    import pymem.process
    import dsr_telemetry as D

    pr = pymem.process.process_from_name("DarkSoulsRemastered.exe")
    if not pr:
        raise RuntimeError("DarkSoulsRemastered.exe 가 안 떠 있다")
    pm = pymem.Pymem()
    pm.process_id = pr.th32ProcessID
    pm.process_handle = pymem.process.open(pm.process_id, debug=False, process_access=READ_ACCESS)
    if not pm.process_handle:
        raise RuntimeError("읽기 전용 핸들을 못 열었다")
    pm.check_wow64()
    tm = D.DSRTelemetry.__new__(D.DSRTelemetry)
    tm.pm = pm
    tm.mod = pymem.process.module_from_name(pm.process_handle, "DarkSoulsRemastered.exe")
    tm.base = tm.mod.lpBaseOfDll
    tm.names, tm.static, tm.phantom, tm._overlap = {}, {}, set(), {}
    for k in ("WorldChrBase", "ChrFollowCam"):          # 관찰에 필요한 둘만 (dsr_telemetry.DSRTelemetry.__init__ 과 같은 계산)
        pat, ao, il = D.AOBS[k]
        a = pymem.pattern.pattern_scan_module(pm.process_handle, tm.mod, D.DSRTelemetry._aob(pat))
        if not a:
            raise RuntimeError(f"AOB 실패: {k}")
        tm.static[k] = a + il + pm.read_int(a + ao)
    tm.vt_player = tm.base + 0x13251F0                  # dsr_telemetry.py DSRTelemetry.__init__ 과 같은 값
    tm.vt_enemy = tm.base + 0x1322E68
    return GameReader(tm, pid=pm.process_id)


# ── 입력 읽기 (읽기 전용) ─────────────────────────────────────────────

class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", wintypes.WORD), ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short), ("sThumbRY", ctypes.c_short)]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XINPUT_GAMEPAD)]


class XInputPads:
    """XInputGetState 만 부른다 (XInputSetState·진동 없음). record_play.py 와 같은 방식, 값은 반올림 없이 원시."""

    def __init__(self):
        self.xi = None
        for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                self.xi = getattr(ctypes.windll, name)
                break
            except OSError:
                continue

    def read(self) -> dict[int, Optional[tuple]]:
        out: dict[int, Optional[tuple]] = {}
        for i in range(4):
            st = XINPUT_STATE()
            if self.xi is None or self.xi.XInputGetState(i, ctypes.byref(st)) != 0:
                out[i] = None
                continue
            g = st.Gamepad
            out[i] = (st.dwPacketNumber, g.wButtons, g.bLeftTrigger, g.bRightTrigger, g.sThumbLX, g.sThumbLY, g.sThumbRX, g.sThumbRY)
        return out


class Win32Keys:
    """GetAsyncKeyState 상위 비트만 본다 — 입력을 소비하지도, 훅을 걸지도 않는다. 하위 비트(지난 호출 뒤 눌림)는 다른 프로그램과 공유라 안 쓴다."""

    def f9_down(self) -> bool:
        return bool(ctypes.windll.user32.GetAsyncKeyState(VK_F9) & 0x8000)


# ── 기록기 ─────────────────────────────────────────────────────────────

def _r(v, n=3):
    return None if v is None else round(v, n)


def _pct(xs: list[float], q: float) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 2)


class Observer:
    def __init__(self, reader, pads, keys, out_path: Path, radius: float = 30.0,
                 clock: Callable[[], int] = time.perf_counter_ns, wall: Callable[[], int] = time.time_ns):
        self.reader, self.pads, self.keys = reader, pads, keys
        self.path, self.radius = Path(out_path), radius
        self.clock, self.wall = clock, wall
        self.t0 = clock()
        self.q: "queue.Queue[dict]" = queue.Queue()
        self._stop = threading.Event()
        self._f = None
        # 상태
        self.epoch = 0
        self.loading = False
        self.last_sync_ms = -SYNC_S * 1000
        self.pad_last: dict[int, tuple] = {}
        self.pad_on: set[int] = set()
        self.f9_prev = False
        self.last_marker_ms: Optional[float] = None
        self.marker_seq = 0
        self.overlap_since: dict[int, float] = {}      # dsr_telemetry 의 phantom 규칙을 진단용으로만 따라 한다
        self.phantom_ptrs: set[int] = set()
        # 요약
        self.n = {"w": 0, "pad": 0, "mk": 0, "sys": 0}
        self.enemy_read_fail = 0
        self.lock_unresolved = 0
        self.errors = 0
        self.read_ms: list[float] = []

    def ms(self) -> float:
        return round((self.clock() - self.t0) / 1e6, 1)

    def emit(self, row: dict) -> None:
        self.q.put(row)

    # ── 파일 ──
    def open(self) -> None:
        import dsr_telemetry as D
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f = self.path.open("x", encoding="utf-8")          # 새 파일만 — 기존 기록을 덮지 않는다
        self._write({"k": "hdr", "v": SCHEMA_V, "ms": 0.0, "wall_ns": self.wall(), "tool": "observe_record.py",
                     "game": "DarkSoulsRemastered.exe", "pid": getattr(self.reader, "pid", None),
                     "hz_world": WORLD_HZ, "hz_pad_poll": PAD_HZ, "radius_m": self.radius,
                     "read_access": "PROCESS_VM_READ|PROCESS_QUERY_INFORMATION",
                     "alive_rule": ALIVE_RULE, "marker_key": "F9", "marker_debounce_ms": MARKER_DEBOUNCE_MS,
                     "bot_phantom_rule": {"npc": sorted(D.PHANTOM_NPC), "overlap_r_m": D.PHANTOM_R, "overlap_s": D.PHANTOM_S},
                     "note": "raw evidence only; no semantic combat labels; 10 Hz world is context, not frame-accurate"})

    def _write(self, row: dict) -> None:
        self._f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        k = row.get("k")
        if k in self.n:
            self.n[k] += 1

    def drain(self) -> None:
        while True:
            try:
                row = self.q.get_nowait()
            except queue.Empty:
                break
            self._write(row)
        if self._f:
            self._f.flush()

    def summary(self, reason: str) -> dict:
        return {"reason": reason, "world_rows": self.n["w"], "pad_rows": self.n["pad"], "markers": self.n["mk"],
                "enemy_read_fail": self.enemy_read_fail, "lock_unresolved": self.lock_unresolved, "errors": self.errors,
                "read_ms_p50": _pct(self.read_ms, 0.5), "read_ms_p95": _pct(self.read_ms, 0.95),
                "duration_s": round(self.ms() / 1000, 1), "path": str(self.path)}

    def close(self, reason: str) -> dict:
        self.drain()
        s = self.summary(reason)
        self._write({"k": "sys", "ms": self.ms(), "ev": "end", "wall_ns": self.wall(), **s})
        self._f.flush()
        self._f.close()
        self._f = None
        return s

    # ── 패드 + F9 (120 Hz) ──
    def pad_step(self) -> None:
        now = self.ms()
        for i, st in self.pads.read().items():
            if st is None:
                if i in self.pad_on:
                    self.pad_on.discard(i)
                    self.pad_last.pop(i, None)
                    self.emit({"k": "sys", "ms": now, "ev": "pad_lost", "i": i})
                continue
            if i not in self.pad_on:
                self.pad_on.add(i)
                self.emit({"k": "sys", "ms": now, "ev": "pad_found", "i": i})
            if st[1:] != self.pad_last.get(i, (None,))[1:]:
                self.pad_last[i] = st
                pkt, btn, lt, rt, lx, ly, rx, ry = st
                self.emit({"k": "pad", "ms": now, "i": i, "pkt": pkt, "btn": btn, "lt": lt, "rt": rt,
                           "lx": lx, "ly": ly, "rx": rx, "ry": ry})
        down = self.keys.f9_down()
        if down and not self.f9_prev and (self.last_marker_ms is None or now - self.last_marker_ms >= MARKER_DEBOUNCE_MS):
            self.last_marker_ms = now
            self.marker_seq += 1
            self.emit({"k": "mk", "ms": now, "n": self.marker_seq})
        self.f9_prev = down

    # ── 월드 (10 Hz) ──
    def world_step(self) -> None:
        r = self.reader
        now = self.ms()
        if now - self.last_sync_ms >= SYNC_S * 1000:
            self.last_sync_ms = now
            self.emit({"k": "sys", "ms": now, "ev": "sync", "wall_ns": self.wall()})
        c0 = self.clock()
        pp = r.player_ptr()
        pl = r.read_chr(pp) if pp else None
        if pl is None:
            if not self.loading:
                self.loading = True
                self.emit({"k": "sys", "ms": now, "ev": "loading", "epoch": self.epoch})
            return
        if self.loading:
            self.loading = False
            self.epoch += 1
            self.emit({"k": "sys", "ms": now, "ev": "loaded", "epoch": self.epoch})
        cam = r.cam_yaw()
        lock_h = r.lock_target()
        locking = lock_h not in (None, -1, 0)
        es, fail, lock_id = [], 0, None
        for p in r.chr_ptrs():
            if p == pp:
                continue
            h = r.handle(p) if locking else None
            is_lock = locking and h == lock_h
            xz = r.pos_xz(p)
            if xz is None and not is_lock:
                continue                                   # 좌표도 못 읽으면 반경 안인지조차 모른다 — 실패로 세지 않는다
            if xz is not None and math.hypot(xz[0] - pl.x, xz[1] - pl.z) > self.radius + 2.0 and not is_lock:
                continue
            c = r.read_chr(p)
            if c is None:
                fail += 1                                  # 빈칸으로 남긴다 — 추정 값 없음
                continue
            d = math.dist((pl.x, pl.y, pl.z), (c.x, c.y, c.z))
            if d > self.radius and not is_lock:
                continue
            if h is None:
                h = r.handle(p)
            if h not in (None, 0, -1):
                eid, src = f"h:{h & 0xFFFFFFFF:08x}#{self.epoch}", "handle"
            else:
                eid, src = f"p:{p:x}#{self.epoch}", "ptr"
            why = (["near"] if d <= self.radius else []) + (["lock"] if is_lock else [])
            if is_lock:
                lock_id = eid
            es.append({"id": eid, "id_src": src, "handle": h, "ptr": p, "npc": c.npc_param,
                       "team_bot": c.team, "flags1_raw": r.flags1(p), "vt": r.vt_kind(p),
                       "pos": [_r(c.x), _r(c.y), _r(c.z)], "hd": _r(c.heading),
                       "hp_raw": c.hp, "max_hp_raw": c.max_hp, "alive_derived": c.hp > 0, "alive_rule": ALIVE_RULE,
                       "anim": c.anim, "d": _r(d, 2), "dy": _r(c.y - pl.y, 2), "why": why,
                       "bot_phantom": self._phantom(p, c, pl, now)})
        read_ms = round((self.clock() - c0) / 1e6, 2)
        self.read_ms.append(read_ms)
        self.enemy_read_fail += fail
        if lock_h is None:
            lock = {"h": None, "resolved": None, "id": None}
        elif not locking:
            lock = {"h": lock_h, "resolved": None, "id": None}
        else:
            lock = {"h": lock_h, "resolved": lock_id is not None, "id": lock_id}
            if lock_id is None:
                self.lock_unresolved += 1
        self.emit({"k": "w", "ms": now, "read_ms": read_ms, "epoch": self.epoch,
                   "p": {"pos": [_r(pl.x), _r(pl.y), _r(pl.z)], "hd": _r(pl.heading), "anim": pl.anim,
                         "hp_raw": pl.hp, "max_hp_raw": pl.max_hp, "sp": pl.sp, "max_sp": pl.max_sp, "handle": r.handle(pp)},
                   "cam_yaw": _r(cam), "lock": lock, "e": es, "e_fail": fail})

    def _phantom(self, p: int, c, pl, now_ms: float) -> bool:
        """dsr_telemetry.snapshot 의 '몸 없음' 규칙을 그대로 따라 한 진단 값. 관찰에서 적을 빼는 데 쓰지 않는다."""
        import dsr_telemetry as D
        if c.npc_param in D.PHANTOM_NPC or p in self.phantom_ptrs:
            return True
        if c.team == 6 and c.hp > 0 and math.hypot(c.x - pl.x, c.z - pl.z) < D.PHANTOM_R and abs(c.y - pl.y) < 0.6:
            t0 = self.overlap_since.setdefault(p, now_ms)
            if now_ms - t0 >= D.PHANTOM_S * 1000:
                self.phantom_ptrs.add(p)
                return True
        else:
            self.overlap_since.pop(p, None)
        return False

    # ── 실행 ──
    def _loop(self, step: Callable[[], None], hz: float, where: str) -> None:
        period = 1.0 / hz
        nxt = time.perf_counter()
        while not self._stop.is_set():
            try:
                step()
            except Exception as ex:                        # 한 틱 실패로 기록 전체를 멈추지 않는다
                self.errors += 1
                self.emit({"k": "sys", "ms": self.ms(), "ev": "error", "where": where, "msg": f"{type(ex).__name__}: {ex}"[:200]})
            nxt += period
            self._stop.wait(max(0.0, nxt - time.perf_counter()))

    def _writer(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(0.25)
            self.drain()

    def run(self, minutes: Optional[float] = None, sleep: Callable[[float], None] = time.sleep) -> dict:
        self.open()
        ths = [threading.Thread(target=self._loop, args=(self.pad_step, PAD_HZ, "pad"), daemon=True),
               threading.Thread(target=self._loop, args=(self.world_step, WORLD_HZ, "world"), daemon=True),
               threading.Thread(target=self._writer, daemon=True)]
        for t in ths:
            t.start()
        reason = "time"
        try:
            while minutes is None or self.ms() < minutes * 60_000:
                sleep(0.2)
        except KeyboardInterrupt:
            reason = "ctrl_c"
        finally:
            self._stop.set()
            for t in ths:
                t.join(timeout=2.0)
        return self.close(reason)


def print_summary(s: dict) -> None:
    print(f"기록 끝 ({s['reason']}): {s['path']}\n"
          f"  월드 {s['world_rows']} 줄 · 패드 {s['pad_rows']} 줄 · 마커 {s['markers']}\n"
          f"  적 읽기 실패 {s['enemy_read_fail']} · 락온 못 찾음 {s['lock_unresolved']} · 오류 {s['errors']}\n"
          f"  read_ms p50 {s['read_ms_p50']} · p95 {s['read_ms_p95']} · {s['duration_s']} s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="읽기 전용 관찰 기록기 (OBSERVE.md)")
    ap.add_argument("--radius", type=float, default=30.0)
    ap.add_argument("--minutes", type=float, default=None)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    a = ap.parse_args()
    path = a.out / f"{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    obs = Observer(open_game_reader(), XInputPads(), Win32Keys(), path, radius=a.radius)
    print(f"관찰 기록 → {path}  (읽기 전용 · F9 = 마커 · Ctrl+C 로 끝)", flush=True)
    print_summary(obs.run(minutes=a.minutes))


if __name__ == "__main__":
    main()
