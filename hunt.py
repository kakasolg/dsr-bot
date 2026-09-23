"""
적마다 정해 둔 공략으로 경사로 무리를 하나씩 치운다 — 먼저 "모를 때 폭탄" 을 시험한다.

  python hunt.py [시도 수] [--throw 10] [--targets 1,2,3]

사용자: "몹의 위치가 고정이고 패턴도 일정하다 — 제대로 접근하면 해결 가능", "네가 감독하고 3.8 Flash 로 이미지 판독시켜 성공 확률을 올려봐".
적 지도(enemy_map.py, 화톳불 휴식 직후 스폰 자리)의 순서대로:
  1) 경로를 천천히 걸어 그 적 스폰에서 --throw m 떨어진 경로점에 선다 (적 25 m 안부터는 creep)
  2) 카메라 정렬, 메모리로 '준비' 확인 (스폰에서 1 m 안, 최근 4 s 몸 15° 미만 돎), 3.8 Flash 판독은 **기록만** (믿을지는 결과와 비교해 정한다)
  3) 파이어밤 칸 확인 → 락온(R3) → 던지기(X) → 4 s 동안 그 적 HP 로 결과: 처치 / 명중 / 빗나감
  4) 잡았으면 다음 적, 살아서 알아챘으면 화톳불로 돌아가 초기화하고 다음 시도
결과: data/hunt.jsonl (던질 때마다 한 줄)
"""
from __future__ import annotations

import json
import math
import sys
import threading
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import merchantrun as mr
import nav
import patrol
import tactic_llm
import vision_probe as vp

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "hunt.jsonl"
MAP = json.loads((ROOT / "data" / "enemy-map.json").read_text(encoding="utf-8"))["enemies"]
ITEM_BOMB = 292
ITEM_KNIFE = 290
ITEM_ESTUS = 205
ITEM_BLACK_BOMB = 297
JUDGE_MODEL = "gemini-3.8-flash"
# 경사로 아래 평지. 처음 쓴 (-31.0, -49.7, 26.0) 은 150~270° 쪽 2 m 에 바닥이 없는 낭떠러지 끝이었다 (1.25 m) —
# 거기서 두 번 추락사(애니 1500, 931 한 번에). 반경 3 m 16방향 바닥이 다 있고 가장 가까운 낙차까지 4.0 m 인 자리로 옮김.
ARENA = (-30.0, -49.25, 29.0)


class Trace:
    """사용자: "몹들과 캐릭터 위치를 1초 단위로 저장해서 나중에 리뷰" — 시도 하나를 data/trace/*.jsonl 로.
    줄마다 {"t", "phase", "me": [x,y,z,heading,hp,sp,anim,LB], "e": {번호: [x,y,z,heading,hp,anim]}} (40 m 안, 지도 밖 적은 "?ptr").
    event() 는 그 순간 바로 한 줄 (맞음·반격 결과) — 1 s 사이에 끝나는 일도 남도록."""

    def __init__(self, hunter, name: str, period: float = 1.0):
        self.h, self.period = hunter, period
        d = ROOT / "data" / "trace"
        d.mkdir(parents=True, exist_ok=True)
        self.path = d / f"{name}.jsonl"
        self.t0 = time.time()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._th = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._th.start()
        return self

    def stop(self):
        self._stop.set()
        self._th.join(2.0)

    def _write(self, row: dict) -> None:
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def event(self, kind: str, **kw) -> None:
        self._write({"t": round(time.time() - self.t0, 2), "phase": self.h.phase, "ev": kind, **kw})

    def _run(self):
        last_full, last_anim = 0.0, {}
        while not self._stop.is_set():
            try:
                s = self.h.tm.snapshot(within=40.0)
                if s:
                    # 0.1 s 마다 적 애니가 바뀐 것만 — 멀리서 109 씩 맞는데 1 s 표본엔 누가 던졌는지 안 잡혔다
                    idx = {v: k_ for k_, v in getattr(self.h, "ptr_of", {}).items()}
                    ch = {}
                    for c in s.hostile(40.0):
                        if last_anim.get(c.ptr) != c.anim:
                            last_anim[c.ptr] = c.anim
                            ch[str(idx.get(c.ptr, f"?{c.ptr:x}"))] = [c.anim, round(c.dist, 1)]
                    if ch:
                        self._write({"t": round(time.time() - self.t0, 2), "a": ch, "my": s.player.anim})
                if s and time.time() - last_full >= self.period:
                    last_full = time.time()
                    p = s.player
                    idx = {v: k_ for k_, v in getattr(self.h, "ptr_of", {}).items()}
                    self._write({"t": round(time.time() - self.t0, 2), "phase": self.h.phase,
                                 "me": [round(p.x, 2), round(p.y, 2), round(p.z, 2), None if p.heading is None else round(p.heading, 2),
                                        p.hp, p.sp, p.anim, self.h.pad.guard_held()],
                                 "e": {str(idx.get(c.ptr, f"?{c.ptr:x}")): [round(c.x, 2), round(c.y, 2), round(c.z, 2),
                                                                           None if c.heading is None else round(c.heading, 2), c.hp, c.anim]
                                       for c in s.hostile(40.0)}})
            except Exception as ex:           # 로딩 중 등 — 기록이 싸움을 멈추게 하면 안 된다
                self._write({"t": round(time.time() - self.t0, 2), "err": str(ex)[:120]})
            self._stop.wait(0.1)


class Hunter(vp.Probe):
    phase = ""
    trace = None

    def _ev(self, kind: str, **kw) -> None:
        if self.trace is not None:
            self.trace.event(kind, **kw)

    def find(self, spawn, s=None, r=3.0):
        """스폰 자리 근처(r m)의 살아 있는 적 — 포인터는 휴식마다 바뀌어서 위치로 찾는다."""
        s = s or self.tm.snapshot(within=40.0)
        if not s:
            return None, None
        c = min((c for c in s.hostile(250.0) if c.hp > 0), key=lambda c: math.dist((c.x, c.y, c.z), spawn), default=None)   # 화톳불에서도 지도 적을 잡도록 넓게
        return (c, s) if c is not None and math.dist((c.x, c.y, c.z), spawn) < r else (None, s)

    def judge(self, b64, dist) -> dict:
        pick, ms, extra = tactic_llm.gemini_choice(JUDGE_MODEL, "You judge enemy awareness in a game screenshot.",
                                                   vp.PROMPT.format(d=dist), vp.STATES, timeout=30.0, retry_429=1, image_jpeg_b64=b64)
        return {"state": pick, "ms": round(ms), **({"error": extra["error"][:100]} if extra.get("error") else {})}

    def select_bomb(self) -> bool:
        """폭탄 칸 — 검은 파이어밤(297)이 퀵슬롯에 있고 남아 있으면 그것, 아니면 파이어밤(292). 둘 다 없으면 False."""
        quick = self.tm.quick_items()
        for item in (ITEM_BLACK_BOMB, ITEM_BOMB):
            if item in quick and self.tm.goods_count(item):
                return self.select_item(item)
        return False

    def select_item(self, item: int) -> bool:
        t0 = time.time()
        while self.tm.selected_item() != item and time.time() - t0 < 3.0:
            self.pad.item_next()
            t1 = time.time()
            while time.time() - t1 < 0.35:
                self.pad.release_due()
                time.sleep(0.01)
        return self.tm.selected_item() == item

    def aim_fine(self, ptr, deg: float = 4.0, timeout: float = 3.0) -> float | None:
        """던지기용 정밀 조준 — 락온 없이 몸을 그놈에 deg 안으로. 스틱을 짧게 쳐서 조금씩 돌리고 놓은 뒤 결과를 본다.
        → 마지막 각도(°) (None = 그놈 없음)."""
        t = time.time()
        off = None
        while time.time() - t < timeout:
            s = self.tm.snapshot(within=40.0)
            c = next((x for x in s.chars if x.ptr == ptr), None) if s else None
            if c is None or s.player.heading is None or s.cam_yaw is None:
                return None
            off = math.degrees(patrol.rel_angle(s.player, c))
            if abs(off) <= deg:
                break
            # 실측(화톳불, 2026-09-23): 스틱 0.6 을 0.05~0.08 s 치면 몸이 그 방향으로 딱 선다 — ±40° 에서 한 번에 0.15° 안(4/4),
            # 3~10° 에서도 0.9° 안(10/10). 0.3 이하는 게임이 안 받아서 2~5° 에서 멈췄고 칠 때마다 걷기만 했다 (나이프 6/6 빗나감)
            st = control.world_to_stick(c.x - s.player.x, c.z - s.player.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
            self.pad.move(*[0.6 * v for v in st])
            time.sleep(0.08 if abs(off) > 10 else 0.05)
            self.pad.move(0.0, 0.0)
            time.sleep(0.25)
        self.pad.move(0.0, 0.0)
        time.sleep(self.STICK_RELEASE_S)
        return off

    # 5번(화염병) 뒤 3.2 m 위 — 경로 92~96 m 가 5번 등 뒤 위를 지난다. 여기서 5번 쪽으로 걸어 떨어지며 R1 = 낙하 공격.
    # 사용자: "화염병 던지는 몹부터, 내가 상단에서 하단으로 공격". 5번은 북서(낭떠러지 쪽)를 보고 있어 등 뒤에서 덮친다.
    PLUNGE_FROM = {5: (-20.5, -36.0, 12.2)}

    def plunge(self, ti: int, ptr, nm) -> bool:
        """위에서 뛰어내리며 공격. 떨어지기 시작하면(높이가 0.3 m 넘게 줄면) 곧바로 R1."""
        top = self.PLUNGE_FROM[ti]
        s = self.tm.snapshot(within=1.0)
        path = nm.find_path((s.player.x, s.player.y, s.player.z), top) or [top]
        t_go = time.time()
        for q in path[1:]:
            r = nav.goto(self.tm, self.pad, q, tolerance=0.6 if q == path[-1] else 1.2, timeout=12, log=lambda *a: None, terrain=nm,
                         on_tick=lambda sn, _d=None: self.note(sn), mode_fn=lambda _s: "sprint")
            if r == "dead":
                return False
        self.pad.neutral()
        s = self.tm.snapshot(within=40.0)
        c = next((x for x in s.chars if x.ptr == ptr), None) if s else None
        if c is None:
            print(f"   #{ti}: 낙하 자리에서 안 보임", flush=True)
            return False
        print(f"   #{ti}: 낙하 자리 도착 {time.time() - t_go:.1f} s — 그놈 {c.dist:.1f} m, 높이차 {s.player.y - c.y:+.1f}, 애니 {c.anim}", flush=True)
        off = self.aim_fine(ptr, deg=6.0, timeout=1.5)
        s = self.tm.snapshot(within=40.0)
        c = next((x for x in s.chars if x.ptr == ptr), None)
        y0, hp0 = s.player.y, c.hp
        st = control.world_to_stick(c.x - s.player.x, c.z - s.player.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
        self.pad.move(*[0.6 * v for v in st])                 # 걸어서 떨어진다 (달리면 너무 멀리 날아간다)
        t = time.time()
        fell, r1_at, my_anims = False, None, []
        while time.time() - t < 3.0:
            s2 = self.tm.snapshot(within=40.0)
            if not s2:
                continue
            if not my_anims or my_anims[-1][1] != s2.player.anim:
                my_anims.append((round(time.time() - t, 2), s2.player.anim, round(s2.player.y - y0, 1)))
            if not fell and s2.player.y < y0 - 0.3:
                fell = True
                self.pad.move(0.0, 0.0)
                self._press(control.B.XUSB_GAMEPAD_RIGHT_SHOULDER)   # 공중 R1 = 낙하 공격
                r1_at = round(time.time() - t, 2)
            c2 = next((x for x in s2.chars if x.ptr == ptr), None)
            if fell and (c2 is None or c2.hp <= 0 or time.time() - t > (r1_at or 0) + 1.8):
                break
            if not fell and time.time() - t > 1.5:
                break
            time.sleep(0.01)
        self.pad.move(0.0, 0.0)
        s3 = self.tm.snapshot(within=40.0)
        c3 = next((x for x in s3.chars if x.ptr == ptr), None) if s3 else None
        dead = c3 is None or c3.hp <= 0
        res = {"plan": "plunge", "fell": fell, "r1_at": r1_at, "aim_off": off, "enemy_hp": [hp0, None if c3 is None else c3.hp],
               "dead": dead, "my_anims": my_anims[:12]}
        self._record(0, ti, MAP[ti - 1], None, None, {}, res)
        self._ev("plunge", **res)
        print(f"   #{ti} 낙하 공격: {'처치' if dead else '실패'} — {res}", flush=True)
        return dead

    # 락온 거리는 ~20 m (평지 중앙 20.7 m 에선 안 걸림, 19.8 m 에선 걸림) — 5번 쪽으로 1.1 m 나간 19.7 m 자리
    SNIPE_FROM = {5: (-29.46, -49.13, 28.04)}

    def snipe(self, ti: int, ptr, nm, max_knives: int = 5) -> bool:
        """평지(5번에서 20.7 m)에서 5번을 나이프로 저격 — 5번은 19.1~19.3 m 부터 자리를 안 뜨고 화염병(3008)을 던진다.
        그 안으로 들어가 경사로를 오르면 계속 맞고(152, 날려감), 낙하 자리로 가다 5·4 사이에 끼어 죽었다.
        10 m 위라 곧게 던지면 안 닿으니 **이때만 락온** — PlayerIns+0xEF0 으로 5번에 걸렸는지 확인하고 던진다."""
        spot = self.SNIPE_FROM.get(ti, ARENA)
        s = self.tm.snapshot(within=1.0)
        path = nm.find_path((s.player.x, s.player.y, s.player.z), spot) or [spot]
        for q in path[1:]:
            if nav.goto(self.tm, self.pad, q, tolerance=0.4 if q == path[-1] else 0.8, timeout=10, log=lambda *a: None, terrain=nm,
                        on_tick=lambda sn, _d=None: self.note(sn), mode_fn=lambda _s: "walk") == "dead":
                return False
        self.pad.neutral()
        if not self.select_item(ITEM_KNIFE):
            print(f"   #{ti}: 투척 나이프 칸을 못 고름", flush=True)
            return False
        if self.snipe_nolock:
            return self.snipe_free(ti, ptr)
        self.reset_camera()
        self.aim_fine(ptr, deg=8.0, timeout=2.0)     # 락온이 그놈을 잡도록 몸·카메라를 그쪽으로
        # 5번은 10 m 위(올려다보는 각 ~27°) — 세로 시야가 ±23.5° 라 카메라를 옆으로만 돌리면 화면 밖이라 락온할 게 없었다.
        # 오른 스틱 위아래로 카메라를 들어 본다 (방향 부호를 몰라 양쪽)
        im = self._shot()
        if im is not None:
            im.save(vp.IMG_DIR / f"snipe_{time.strftime('%H%M%S')}_0.jpg", quality=80)
        locked = self.lock_verified(ptr)
        tries = []
        for ly, dur in ((0.7, 0.3), (-0.7, 0.6), (-0.7, 0.3)):
            if locked:
                break
            self.pad.look(0.0, ly)
            time.sleep(dur)
            self.pad.look(0.0, 0.0)
            time.sleep(0.1)
            im = self._shot()
            if im is not None:
                im.save(vp.IMG_DIR / f"snipe_{time.strftime('%H%M%S')}_{ly:+.1f}.jpg", quality=80)
            locked = self.lock_verified(ptr, align=False)
            tries.append((ly, dur, locked, self.tm.lock_target()))
        print(f"   #{ti}: 락온 {'됨' if locked else '안 걸림'} (카메라 들기 {tries})", flush=True)
        if not locked:
            self.reset_camera()
            self.block_test(ptr, 14.0)
            return False
        thrown, log = 0, []
        try:
            while thrown < max_knives:
                if self.lock_state(ptr) != "target":
                    if not self.lock_verified(ptr, align=False):
                        break
                sn = self.tm.snapshot(within=40.0)
                c = next((x for x in sn.chars if x.ptr == ptr), None) if sn else None
                if c is None or c.hp <= 0:
                    break
                if c.anim == 3008:
                    # 화염병을 던지는 중(2.4 s 뒤 떨어진다) — 락온이라 몸이 그놈을 향한다, 방패로 받는다
                    self.pad.guard(True)
                    tw = time.time()
                    while time.time() - tw < 3.0:
                        sn2 = self.tm.snapshot(within=40.0)
                        c2 = next((x for x in sn2.chars if x.ptr == ptr), None) if sn2 else None
                        if c2 is None or c2.anim != 3008:
                            break
                        time.sleep(0.03)
                    time.sleep(0.3)
                    self.pad.guard(False)
                    continue
                hp0 = c.hp
                self.pad.use_item()
                thrown += 1
                t = time.time()
                hit = None
                while time.time() - t < 1.6:
                    self.pad.release_due()
                    sn = self.tm.snapshot(within=40.0)
                    c = next((x for x in sn.chars if x.ptr == ptr), None) if sn else None
                    if c is None or c.hp < hp0:
                        hit = hp0 - (c.hp if c is not None else 0)
                        if c is None or c.hp <= 0:
                            break
                    time.sleep(0.03)
                log.append({"n": thrown, "dmg": hit, "d": None if c is None else round(c.dist, 1), "anim": None if c is None else c.anim})
                print(f"   #{ti}: 저격 {thrown} → 피해 {hit} ({'죽음' if c is None or c.hp <= 0 else f'HP {c.hp}, {c.dist:.1f} m, 애니 {c.anim}'})", flush=True)
                if c is None or c.hp <= 0:
                    break
        finally:
            if self.lock_state(ptr) == "target":
                self._r3(0.15)                    # 락온 풀기 (그 뒤는 락온 없이)
            self.reset_camera()                   # 들어 올린 카메라를 되돌린다 — 안 그러면 다음 나이프가 발밑으로
        sn = self.tm.snapshot(within=60.0)
        c = next((x for x in sn.chars if x.ptr == ptr), None) if sn else None
        dead = c is None or c.hp <= 0
        self._record(0, ti, MAP[ti - 1], None, None, {}, {"plan": "snipe", "throws": log, "dead": dead})
        self._ev("snipe", target=ti, throws=log, dead=dead)
        if dead:
            sk = self.tm.snapshot(within=1.0)
        return dead

    snipe_nolock = True

    def snipe_free(self, ti: int, ptr, max_knives: int = 6) -> bool:
        """락온 없이 저격 — 몸을 그놈에 맞추고(aim_fine) 카메라를 올려다보는 각에 맞춘 뒤 던진다. 5번은 10 m 위(~27°)라
        락온이 끝내 안 걸렸다 (카메라를 들어도). 던지는 중(3008)이면 몸을 맞춘 채 방패로 받고 기다린다."""
        self._press(control.B.XUSB_GAMEPAD_A)          # 핏자국('잃은 힘 되찾기') 위면 소울 회수 — 전에 여기서 죽었다
        thrown, log = 0, []
        bias = 0.0                                      # 맞지 않으면 기울기를 조금씩 바꿔 본다
        while thrown < max_knives:
            s = self.tm.snapshot(within=40.0)
            c = next((x for x in s.chars if x.ptr == ptr), None) if s else None
            if c is None or c.hp <= 0:
                break
            if c.anim == 3008:
                self.pad.guard(True)
                tw = time.time()
                while time.time() - tw < 3.0:
                    s2 = self.tm.snapshot(within=40.0)
                    c2 = next((x for x in s2.chars if x.ptr == ptr), None) if s2 else None
                    if c2 is None or c2.anim != 3008:
                        break
                    self.aim(s2, c2)
                    time.sleep(0.02)
                time.sleep(0.3)
                self.pad.guard(False)
                self.pad.move(0.0, 0.0)
                continue
            off = self.aim_fine(ptr, deg=1.0, timeout=2.0)
            s = self.tm.snapshot(within=40.0)
            c = next((x for x in s.chars if x.ptr == ptr), None) if s else None
            if c is None:
                break
            want = self.elevation(c, s) + bias
            pitch = self.set_pitch(want)
            hp0 = c.hp
            self.pad.use_item()
            thrown += 1
            t = time.time()
            hit = None
            while time.time() - t < 1.8:
                self.pad.release_due()
                sn = self.tm.snapshot(within=40.0)
                cc = next((x for x in sn.chars if x.ptr == ptr), None) if sn else None
                if cc is None or cc.hp < hp0:
                    hit = hp0 - (cc.hp if cc is not None else 0)
                    break
                time.sleep(0.03)
            log.append({"n": thrown, "off": None if off is None else round(off, 1), "want": round(want, 1),
                        "pitch": None if pitch is None else round(pitch, 1), "dmg": hit, "d": round(c.dist, 1)})
            print(f"   #{ti}: 저격 {thrown} (몸 {log[-1]['off']}°, 기울기 {log[-1]['pitch']}° / 목표 {log[-1]['want']}°, {c.dist:.1f} m) → 피해 {hit}", flush=True)
            if hit is None:
                bias = [2.0, -2.0, 4.0, -4.0, 6.0][min(thrown - 1, 4)]
        sn = self.tm.snapshot(within=60.0)
        c = next((x for x in sn.chars if x.ptr == ptr), None) if sn else None
        dead = c is None or c.hp <= 0
        self._record(0, ti, MAP[ti - 1], None, None, {}, {"plan": "snipe_free", "throws": log, "dead": dead})
        self._ev("snipe", target=ti, throws=log, dead=dead)
        if not dead:
            self.block_test(ptr, 8.0)
        return dead

    def block_bomb(self, ptr, t_start: float) -> None:
        """화염병이 떨어질 때(시작 + 2.4 s)까지 그놈 쪽으로 몸을 맞추고 방패를 든다. 맞으면 적는다."""
        self.pad.neutral()
        hp0 = None
        while time.time() - t_start < 2.8:
            s = self.tm.snapshot(within=40.0)
            c = next((x for x in s.chars if x.ptr == ptr), None) if s else None
            if c is None:
                break
            hp0 = hp0 if hp0 is not None else s.player.hp
            self.pad.guard(True)
            self.aim(s, c)
            time.sleep(0.02)
        self.pad.move(0.0, 0.0)
        s = self.tm.snapshot(within=5.0)
        lost = (hp0 - s.player.hp) if (s and hp0 is not None) else None
        print(f"      화염병 방패로 받음 → 피해 {lost}", flush=True)
        self._ev("bomb_block", dmg=lost)
        self.pad.guard(False)

    def block_test(self, ptr, secs: float) -> list:
        """화염병(3008)을 방패로 받을 수 있나 — 그놈 쪽으로 몸을 맞추고, 던지기 시작하면 방패. 맞은 피해·내 애니를 적는다.
        (등지고 맞으면 109, 날아가 낭떠러지로 떨어진 적도 있다)"""
        self._press(control.B.XUSB_GAMEPAD_A)          # 핏자국('잃은 힘 되찾기') 위면 소울 회수 — 전에 여기서 죽었다
        t0 = time.time()
        out, last_anim, hp_last, t_throw = [], None, None, None
        while time.time() - t0 < secs:
            s = self.tm.snapshot(within=40.0)
            c = next((x for x in s.chars if x.ptr == ptr), None) if s else None
            if c is None:
                break
            p = s.player
            if hp_last is not None and p.hp < hp_last:
                out.append({"t": round(time.time() - t0, 2), "dmg": hp_last - p.hp, "my_anim": p.anim, "lb": self.pad.guard_held(),
                            "rel": round(math.degrees(patrol.rel_angle(p, c))) if p.heading is not None else None})
                print(f"      화염병 맞음 {out[-1]}", flush=True)
            hp_last = p.hp
            if c.anim != last_anim:
                if c.anim == 3008:
                    print(f"      +{time.time() - t0:.1f}s 5번 던지기 시작 ({c.dist:.1f} m)", flush=True)
                    t_throw = time.time()
                last_anim = c.anim
            if t_throw is not None and time.time() - t_throw > 2.35:
                im = self._shot()                 # 떨어지는 순간 — 방패로 받았나, 턱에 걸렸나
                if im is not None:
                    im.save(vp.IMG_DIR / f"bomb_{time.strftime('%H%M%S')}.jpg", quality=80)
                t_throw = None
            self.pad.guard(True)
            self.aim(s, c)
            time.sleep(0.02)
        self.pad.guard(False)
        self.pad.move(0.0, 0.0)
        self._ev("block_test", hits=out)
        return out

    # 5번(가만히 서서 화염병만 던진다)을 폭탄으로 — 경사로 위 #3 스폰 옆(경로 81 m), 5번과 수평 6.1 m·1.1 m 아래
    # 4번: 경로 83 m (4번과 9.1 m, 같은 높이) — 모를 때 9.5~10 m 폭탄은 1번에게 11/11. 달려오는 놈에게 던진 미끼 폭탄은 5/5 빗나감.
    # 6번: 5번 위 계단 꼭대기(사람이 서 있던 자리, 오르기 10/10) — 6번과 5.4 m, 2.3 m 아래
    BOMB_FROM = {5: (-20.7, -40.4, 19.3), 4: (-18.9, -39.9, 18.7), 6: (-20.61, -36.04, 11.92)}

    def bomb_at(self, k: int, ti: int, e: dict, ptr, nm) -> bool:
        """사용자: "firebomb 을 잘 써 봐. 제대로 맞추면 즉사". 자리로 달려가(멈추면 화염병을 맞는다) 락온(메모리로 확인) → 던지기.
        가장자리만 맞으면(살아 있음) 락온·폭탄 칸 그대로 한 번 더."""
        spot = self.BOMB_FROM[ti]
        if not self.select_bomb():                 # 달려가기 전에 골라 둔다 (칸 넘기기 0.35 s × 몇 번)
            print(f"   #{ti}: 폭탄이 없다", flush=True)
            return False
        # 걸어서 간다. 5번 쪽은 달리다 화염병 폭발에 날려 경사로에서 떨어졌고(2/2) 아래층 2번에게 죽었다 →
        # 5번이 던지기 시작하면(3008) 멈춰서 5번을 보고 방패로 받고(막으면 안 날아간다) 다시 걷는다. 4·6번은 기습이라 걷는다
        p5 = self.ptr_of.get(5)
        seen = {"a": None, "t": 0.0}

        def bomb_started(sn):
            c5 = next((x for x in sn.chars if x.ptr == p5 and x.hp > 0), None) if p5 else None
            if c5 is None or c5.dist > 20.0:
                return False
            new = c5.anim == 3008 and seen["a"] != 3008
            seen["a"] = c5.anim
            if new:
                seen["t"] = time.time()
            return new
        for _ in range(14):
            s = self.tm.snapshot(within=1.0)
            if math.dist((s.player.x, s.player.y, s.player.z), spot) < 1.0:
                break
            path = nav.trim_path((nm.find_path((s.player.x, s.player.y, s.player.z), spot) or [spot])[1:], spot)
            r_ = nav.follow(self.tm, self.pad, path, terrain=nm, mode_fn=lambda _s: "walk", default_tol=0.8,
                            on_tick=lambda sn, _d=None: self.note(sn), timeout_per=12, stop_fn=bomb_started)
            if r_ == "dead":
                return False
            if r_ == "stopped":
                self.block_bomb(p5, seen["t"])
                continue
            if r_ != "arrived":
                break
        self.pad.neutral()
        pt = self.cam_pitch()
        if pt is None or abs(pt) > 15:
            self.reset_camera()                    # 카메라가 많이 숙거나 들렸을 때만
        res, n = None, 0
        idx = {v: k_ for k_, v in self.ptr_of.items()}
        for attempt in range(6):
            sc = self.tm.snapshot(within=10.0)
            close = [x for x in (sc.hostile(3.5) if sc else []) if x.hp > 0]
            if self.BRUTE:                         # 강인도 세팅 — 옆에 다른 놈이 있어도 던진다 (사용자: 폭탄은 그래도 잘 써야). 목표가 2 m 안에 붙었을 때만 접는다
                close = [x for x in close if x.ptr == ptr and x.dist < 2.0]
            if close:
                # 이미 깨서 붙은 놈이 있다 — 방패 내리고 락온·던지기를 붙들고 있으면 맞는다(4번 84~136 씩) → 근접으로
                print(f"   #{ti}: {close[0].dist:.1f} m 안에 적 — 폭탄 접고 근접", flush=True)
                if self.lock_state(ptr) == "target":
                    self._r3(0.1)
                return False
            self.pad.guard(True)                    # 락온 맞추는 동안은 방패
            st = self.lock_state(ptr)
            if st == "none":
                sa = self.tm.snapshot(within=30.0)
                ca = next((x for x in sa.chars if x.ptr == ptr), None) if sa else None
                if ca is None or abs(math.degrees(self._cam_angle(ca, sa))) > 20:
                    self.align(ptr)                # 화면 밖일 때만 카메라를 돌린다 (~1 s)
                self._r3(0.3)
                st = self.lock_state(ptr)
            if st == "other":
                # 락온이 옆 놈(4번 등)에게 — 그놈도 잡을 놈이니 그놈부터 폭탄 (둘째 판: 4번에 두 번 걸려 5번을 못 던지고 600 잃음)
                h = self.tm.lock_target()
                so = self.tm.snapshot(within=20.0)
                other = next((x for x in (so.hostile(20.0) if so else []) if x.hp > 0 and self.tm.handle(x.ptr) == h), None)
                # 10 m 안·높이차 2.5 m 안인 놈만 (아래층 2번에게 걸려 던진 폭탄은 6 피해로 낭비)
                if other is not None and (other.dist > 10.0 or abs(other.y - so.player.y) > 2.5):
                    print(f"   #{ti}: 락온이 멀리 있는 #{idx.get(other.ptr, '?')} ({other.dist:.1f} m) 에게 — 풀고 다시", flush=True)
                    self._r3(0.1)
                    self.align(ptr)
                    self._r3(0.3)
                    continue
                if other is not None and self.tm.goods_count(self.tm.selected_item() or 0):
                    ro = self.throw_at(other.ptr, locked_already=True, release_if_alive=True)
                    print(f"   #{ti}: 락온이 #{idx.get(other.ptr, '?')} 에게 — 그놈부터 폭탄 → {ro['result']} (HP {ro['hp0']}→{ro['hp_after']})", flush=True)
                    self._ev("bomb", target=idx.get(other.ptr, "?"), result=ro["result"], via=ti)
                else:
                    self._r3(0.1)
                continue
            if st != "target":
                continue
            n += 1
            self.pad.guard(False)                   # 던질 때만 방패를 내린다
            res = self.throw_at(ptr, locked_already=True, release_if_alive=(n >= 3))
            print(f"   #{ti} 폭탄 {n}: {res['result']} (HP {res['hp0']}→{res['hp_after']})", flush=True)
            self._record(k, ti, e, None, None, {}, {**res, "plan": "bomb_at", "n": n})
            self._ev("bomb", target=ti, n=n, result=res["result"], hp=[res["hp0"], res["hp_after"]])
            if res["result"] == "처치" or n >= 3 or not self.tm.goods_count(self.tm.selected_item() or 0):
                break
        if self.lock_state(ptr) == "target":
            self._r3(0.1)
        return res is not None and res["result"] == "처치"

    def walk_fight(self, path: list, nm, tag: str, fight_r: float = 4.5, mode: str = "walk") -> str:
        """경로를 걷다가 적이 fight_r m 안에 붙으면 멈춰서 그놈부터 (근접 — 지금 스타일). 잡으면 같은 경로점부터 다시.
        → 'arrived' | 'dead' | 'hp' | 'stuck'"""
        tols = nav.path_tolerances(path, 1.0)
        i, fights, fails = 0, 0, 0
        while i < len(path):
            q, tol = path[i], tols[i]

            def enemy_close(sn):
                return any(c.hp > 0 and c.dist < fight_r and abs(c.y - sn.player.y) < 2.5 and not patrol.dormant(c)
                           for c in sn.hostile(fight_r))
            r = nav.goto(self.tm, self.pad, tuple(q), tolerance=tol, timeout=15, log=lambda *a: None, terrain=nm,
                         on_tick=lambda sn, _d=None: self.note(sn), mode_fn=lambda sn: "retreat" if enemy_close(sn) else mode)
            if r == "dead":
                return "dead"
            s = self.tm.snapshot(within=fight_r + 1.0)
            if s and s.player.hp <= 0:
                return "dead"
            near = [c for c in (s.hostile(fight_r) if s else []) if c.hp > 0 and abs(c.y - s.player.y) < 2.5 and not patrol.dormant(c)]
            if near and fights < 12:
                c = min(near, key=lambda x: x.dist)
                fights += 1
                print(f"   {tag}: {c.npc_param} 가 {c.dist:.1f} m — 싸운다", flush=True)
                self.phase = f"{tag} 싸움 {c.npc_param}"
                ok = self.melee(0, 0, {"npc": c.npc_param, "pos": [round(c.x, 2), round(c.y, 2), round(c.z, 2)]}, c.ptr, nm, pull_to=None)
                s2 = self.tm.snapshot(within=5.0)
                if s2 is None or s2.player.hp <= 0:
                    return "dead"
                if not ok and s2.player.hp < s2.player.max_hp * 0.25:
                    return "hp"
                self.heal_if_needed()
                self.phase = tag
                continue                                    # 같은 경로점부터 다시
            if r != "arrived":
                fails += 1
                if fails >= 3:
                    return "stuck"
            else:
                fails = 0
            i += 1
        self.pad.neutral()
        return "arrived"

    def go_merchant(self) -> str:
        """경사로 무리를 치운 뒤 상인까지 — 사용자: "10판 끝나면 상인까지 가는 길도 해봐".
        계단 꼭대기 → (녹화 경로 A67~A70: 다리 높이로) → 내비메시로 경계 → 성벽 마을(구간 B, 녹화 경로) → 상인.
        내비메시의 꼭대기→경계 경로는 14 m 떨어졌다가 16 m 를 1.2 m 안에서 오르는 연결 오류가 있어 그 구간만 녹화 경로로."""
        na, nb = self.run.nm[mr.MAP_A], self.run.nm[mr.MAP_B]
        top = tuple(json.loads((ROOT / "data" / "climb-goal.json").read_text(encoding="utf-8"))["top"])
        t0 = time.time()
        self.phase = "상인: 꼭대기"
        s = self.tm.snapshot(within=1.0)
        p1 = nav.trim_path((na.find_path((s.player.x, s.player.y, s.player.z), top) or [top])[1:], top)
        r = self.walk_fight(p1, na, "상인 A-꼭대기")
        if r != "arrived":
            return f"꼭대기까지 {r}"
        A = [tuple(q) for q in mr.ROUTE["segments"][0]["points"]]
        bridge = A[67:71]                                   # 다리 높이(y -33.8)로 올라서는 녹화 점
        p2 = (na.find_path(bridge[-1], mr.BOUND_A) or [mr.BOUND_A])[1:]
        # 혹시 남은 연결 오류(짧은 수평에 3 m 넘는 높이 차) 는 버린다
        clean = [bridge[-1]]
        for q in p2:
            h = math.dist((clean[-1][0], clean[-1][2]), (q[0], q[2]))
            if abs(q[1] - clean[-1][1]) > 3.0 and h < 3.0:
                continue
            clean.append(q)
        self.phase = "상인: 다리→경계"
        r = self.walk_fight(bridge + clean[1:], na, "상인 A-다리")
        if r != "arrived":
            return f"경계까지 {r}"
        print(f"   경계 도착 {time.time() - t0:.0f} s", flush=True)
        self.phase = "상인: 성벽 마을"
        time.sleep(1.0)
        self.run.cur_nm = nb
        B = [tuple(q) for q in mr.ROUTE["segments"][1]["points"]]
        r = self.walk_fight(B + [tuple(mr.MERCHANT)], nb, "상인 B")
        s = self.tm.snapshot(within=5.0)
        d = None if not s else math.dist((s.player.x, s.player.y, s.player.z), tuple(mr.MERCHANT))
        self.run.cur_nm = na
        res = "도착" if (r == "arrived" and d is not None and d < 3.0) else f"구간 B {r} (상인까지 {d if d is None else round(d, 1)} m)"
        print(f"   상인: {res} — {time.time() - t0:.0f} s, HP {s.player.hp if s else '?'}", flush=True)
        self._ev("merchant", result=res, secs=round(time.time() - t0), left=None if d is None else round(d, 1))
        return res

    def climb_to(self, goal, mode: str = "walk") -> str:
        """사냥 봇 이동 코드(nav.follow)로 goal 까지 — 사용자: "사냥 봇에 계단 수정 넣고, 몹 없는 상태로 천천히 올라가게".
        화톳불에서 쉬지 않는다 (쉬면 몹이 되살아난다)."""
        nm = self.run.nm[mr.MAP_A]
        s = self.tm.snapshot(within=5.0)
        path = nav.trim_path((nm.find_path((s.player.x, s.player.y, s.player.z), goal) or [goal])[1:], goal)
        tols = nav.path_tolerances(path, 1.0)
        print(f"── 오르기: {len(path)} 점, 좁게(0.4 m) {sum(1 for t in tols if t < 1.0)} 점 → {tuple(round(v, 2) for v in goal)}", flush=True)
        self.phase = "오르기"
        t0 = time.time()
        r = nav.follow(self.tm, self.pad, path, terrain=nm, mode_fn=lambda _s: mode, default_tol=1.0,
                       on_tick=lambda sn, _d=None: self.note(sn), log=lambda *a: print("     ", *a, flush=True))
        s = self.tm.snapshot(within=5.0)
        left = None if not s else round(math.dist((s.player.x, s.player.y, s.player.z), goal), 2)
        print(f"   오르기: {r} — {time.time() - t0:.0f} s, 목표까지 {left} m, HP {s.player.hp if s else '?'}", flush=True)
        self._ev("climb", result=r, left=left)
        return r

    def bombs_left(self) -> bool:
        q = self.tm.quick_items()
        return any(i in q and self.tm.goods_count(i) for i in (ITEM_BLACK_BOMB, ITEM_BOMB))

    def close_bomb(self, ptr) -> dict:
        """붙은 채로 폭탄 — 락온(가까우니 정렬 없이) → 던지기. 내게는 피해가 없다 (사용자)."""
        if not self.select_bomb():
            return {"done": False, "why": "폭탄 없음"}
        if not (self.lock_state(ptr) == "target" or self.lock_verified(ptr, align=False)):
            return {"done": False, "why": "락온 안 걸림"}
        self.pad.guard(False)
        res = self.throw_at(ptr, locked_already=True, release_if_alive=True)
        self.pad.guard(True)
        return {"done": True, "enemy_dead": res["result"] == "처치", "result": res["result"], "hp": [res["hp0"], res["hp_after"]]}

    def sip_estus(self, s, nm) -> dict | None:
        """싸우는 중 에스트 한 모금. 4 m 안 적이 전부 넘어져 있거나(99xx) 공격 중이 아니고 2.5 m 넘게 떨어져 있을 때만.
        붙어 있으면 뒤에 바닥이 있을 때 백스텝으로 거리를 벌리고 다음 틱에 다시 본다. 마시는 중 맞으면 끊긴다.
        → 마셨으면 {"hp": [전, 후]}, 백스텝만 했으면 {"backstep": True}, 못 하면 None."""
        p = s.player
        near = [c for c in s.hostile(4.0) if c.hp > 0]
        busy = [c for c in near if not (9900 <= (c.anim or 0) < 10000) and (3000 <= (c.anim or 0) < 3600 or c.dist < 2.5)]
        if self.BRUTE:
            busy = []                   # 사용자: "강인도로 세팅, 에스트 마시면서 공격" — 맞아도 안 끊기니 적을 가리지 않고 마신다
        if busy:
            if (p.heading is not None and min(c.dist for c in busy) < 2.5 and not any(3000 <= (c.anim or 0) < 3600 for c in busy)
                    and nav.ground_ahead(nm, p, math.sin(p.heading), math.cos(p.heading), reach=2.2)):
                self.pad.move(0.0, 0.0)
                self.pad.guard(False)
                time.sleep(0.1)
                self._press(control.B.XUSB_GAMEPAD_B)       # 백스텝으로 거리를 벌린다
                time.sleep(0.7)
                return {"backstep": True}
            return None
        if not self.select_item(ITEM_ESTUS):
            return None
        hp0 = p.hp
        self.pad.guard(False)
        self.pad.neutral()
        self.pad.use_item()
        t = time.time()
        while time.time() - t < 2.2:
            self.pad.release_due()
            time.sleep(0.02)
        s2 = self.tm.snapshot(within=10.0)
        return {"hp": [hp0, s2.player.hp if s2 else None]}

    def heal_if_needed(self, frac: float = 0.7, max_sips: int = 2) -> None:
        """잡은 뒤 HP 가 frac 아래고 5 m 안에 적이 없으면 에스트 (사용자가 2번 칸에 넣어 줌, 10회분)."""
        for _ in range(max_sips):
            s = self.tm.snapshot(within=10.0)
            if not s or s.player.hp >= s.player.max_hp * frac:
                return
            if any(c.hp > 0 for c in s.hostile(5.0)):
                print("      에스트: 5 m 안에 적 — 안 마심", flush=True)
                return
            if not self.tm.goods_count(ITEM_ESTUS):
                print("      에스트 없음", flush=True)
                return
            if not self.select_item(ITEM_ESTUS):
                print("      에스트 칸을 못 고름", flush=True)
                return
            hp0 = s.player.hp
            self.pad.neutral()
            self.pad.use_item()
            t = time.time()
            while time.time() - t < 2.6:
                self.pad.release_due()
                time.sleep(0.02)
            s2 = self.tm.snapshot(within=10.0)
            print(f"      에스트: HP {hp0} → {s2.player.hp if s2 else '?'} (남은 {self.tm.goods_count(ITEM_ESTUS)})", flush=True)
            self._ev("estus", hp0=hp0, hp1=s2.player.hp if s2 else None)

    def knife_pull(self, ti: int, ptr, nm) -> bool:
        """평지(ARENA)에서 투척 나이프로 그놈을 부른다 — 걸어서 다가가면 좁은 띠(서쪽 낭떠러지)에서 싸우게 됐다.
        지도 적은 휴식하면 늘 같은 자리·같은 방향이라 평지에서 곧게 던지면 닿는다."""
        s = self.tm.snapshot(within=1.0)
        path = self.run.cur_nm.find_path((s.player.x, s.player.y, s.player.z), ARENA) or [ARENA]
        for q in path[1:]:
            if nav.goto(self.tm, self.pad, q, tolerance=0.8, timeout=10, log=lambda *a: None, terrain=nm,
                        on_tick=lambda sn, _d=None: self.note(sn), mode_fn=lambda _s: "walk") == "dead":
                return False
        self.pad.neutral()
        if not self.tm.goods_count(ITEM_KNIFE):
            print(f"   #{ti}: 투척 나이프가 없다 (인벤토리 0)", flush=True)
            return False
        if not self.select_item(ITEM_KNIFE):
            print(f"   #{ti}: 투척 나이프 칸을 못 고름", flush=True)
            return False
        self.reset_camera()
        spawn = tuple(MAP[ti - 1]["pos"])
        for attempt in range(3):
            off = self.aim_fine(ptr, deg=1.2, timeout=4.0)   # 14 m 에서 3.3~4.6° 는 6/6 빗나감, 0.2° 는 2/2 맞음
            sp_ = self.tm.snapshot(within=40.0)
            cp_ = next((x for x in sp_.chars if x.ptr == ptr), None) if sp_ else None
            pitch = self.set_pitch(self.elevation(cp_, sp_)) if cp_ is not None else None
            c0 = next((x for x in (self.tm.snapshot(within=40.0) or type("S", (), {"chars": []})).chars if x.ptr == ptr), None)
            if c0 is None:
                return False
            hp0 = c0.hp
            n0 = self.tm.goods_count(ITEM_KNIFE)
            self.pad.use_item()
            t = time.time()
            woke, my_anims, shot = False, [], None
            while time.time() - t < 2.5:
                self.pad.release_due()
                if shot is None and time.time() - t > 0.6:
                    im = self._shot()                 # 조준 0.1° 인데 반응 없음 3/3 — 던지는 동작이 나갔나, 가려서 막혔나
                    if im is not None:
                        shot = f"knife_{time.strftime('%H%M%S')}_{attempt + 1}.jpg"
                        im.save(vp.IMG_DIR / shot, quality=80)
                sn = self.tm.snapshot(within=40.0)
                if sn and (not my_anims or my_anims[-1][1] != sn.player.anim):
                    my_anims.append((round(time.time() - t, 2), sn.player.anim))
                c = next((x for x in sn.chars if x.ptr == ptr), None) if sn else None
                if c is not None and (c.hp < hp0 or math.dist((c.x, c.y, c.z), spawn) > 1.0):
                    woke = True
                    break
                time.sleep(0.05)
            n1 = self.tm.goods_count(ITEM_KNIFE)
            print(f"   #{ti}: 나이프 {attempt + 1}번째 (몸-그놈 {off if off is None else round(off, 1)}°, 카메라 {pitch if pitch is None else round(pitch, 1)}°, {c0.dist:.1f} m) → "
                  f"{'알아챔' if woke else '반응 없음'} | 나이프 {n0}→{n1}, 내 애니 {my_anims[:5]} {shot or ''}", flush=True)
            self._ev("knife", target=ti, off=off, dist=round(c0.dist, 1), woke=woke)
            if woke:
                return True
        return False


    def throw_at(self, ptr, locked_already: bool = False, release_if_alive: bool = True) -> dict:
        """락온 → 던지기 → 4 s 동안 대상 HP·애니. 락온은 대상이 살아 있을 때만 풀어 준다 (죽으면 게임이 푼다)."""
        s0 = self.tm.snapshot(within=40.0)
        c0 = next((c for c in s0.hostile(40.0) if c.ptr == ptr), None) if s0 else None
        hp0 = c0.hp if c0 else None
        if not locked_already:
            self.pad.lock_on()
            t = time.time()
            while time.time() - t < 0.35:
                self.pad.release_due()
                time.sleep(0.01)
        shots = []                    # 던지기 전 화면 캡처는 뺐다 — 사용자: "화염병 던지기 전에 시간을 너무 끈다"
        # 락온 대상은 메모리(PlayerIns+0xEF0)로 확인 — 노린 놈이 아니면 풀고 안 던진다 (옆 놈에게 폭탄이 간 적이 있다)
        st = self.lock_state(ptr)
        if st != "target":
            if st == "other":
                self._r3(0.1)
            return {"hp0": hp0, "hp_after": hp0, "result": "락온 대상 다름" if st == "other" else "락온 안 걸림",
                    "anims_after": [], "shots": []}
        self.pad.use_item()
        t_throw = time.time()
        anims, hp_min = [], hp0
        want = []
        # 누르고 ~1.2 s 뒤에 손을 떠나고 10 m 를 날아간다 — 2.2 s 로 끊었더니 떨어지기 전에 '빗나감' 으로 판정했다 (락온은 걸려 있었다).
        # 죽으면 바로 끝내고, 아니면 2.8 s 까지만 본다 (4 s 는 다음 행동을 늦췄다)
        while time.time() - t_throw < 2.8:
            if want and time.time() - t_throw >= want[0]:
                shots.append((f"+{want.pop(0)}s", self._shot()))
            self.pad.release_due()
            s = self.tm.snapshot(within=40.0)
            c = next((c for c in s.hostile(40.0) if c.ptr == ptr), None) if s else None
            if c is not None:
                hp_min = min(hp_min, c.hp) if hp_min is not None else c.hp
                if not anims or anims[-1] != c.anim:
                    anims.append(c.anim)
            else:
                hp_min = 0 if hp_min is not None else None   # 목록에서 빠졌다 = 죽음
            if hp_min is not None and hp_min <= 0:
                break
            time.sleep(0.05)
        alive = hp_min is not None and hp_min > 0
        if alive and release_if_alive and self.lock_state(ptr) == "target":
            self._r3(0.1)               # 풀기
        res = "처치" if not alive else ("명중" if hp0 is not None and hp_min < hp0 else "빗나감")
        tag = time.strftime("%H%M%S")
        names = []
        for label, im in shots:
            if im is not None:
                nm_ = f"throw_{tag}_{label.replace('+', 'p')}.jpg"
                im.save(vp.IMG_DIR / nm_, quality=80)
                names.append(nm_)
        return {"hp0": hp0, "hp_after": hp_min, "result": res, "anims_after": anims[:10], "shots": names}

    def _shot(self):
        from PIL import ImageGrab
        rc = vp.window_rect()
        if not rc:
            return None
        img = ImageGrab.grab(bbox=rc, all_screens=True)
        return img.resize((800, round(img.size[1] * 800 / img.size[0])))

    def standpoint(self, path, spawn, dist):
        """경로를 따라가다 처음으로 스폰까지 dist m 안에 드는 점 (그 앞 점과 사이를 보간)."""
        for i in range(1, len(path)):
            if math.dist(path[i], spawn) <= dist:
                a, b = path[i - 1], path[i]
                da, db = math.dist(a, spawn), math.dist(b, spawn)
                f = 0.0 if da <= db else min(1.0, (da - dist) / max(1e-6, da - db))
                return i, tuple(a[k] + (b[k] - a[k]) * f for k in range(3))
        return None, None

    def hunt(self, k: int, targets: list[int], dist: float) -> None:
        self.phase = "휴식"
        self.trace = Trace(self, f"hunt_{time.strftime('%Y%m%d_%H%M%S')}_{k}").start()
        try:
            self._hunt(k, targets, dist)
        finally:
            self.phase = "끝"
            self.trace.event("end")
            self.trace.stop()
            print(f"   위치 기록: {self.trace.path.name}", flush=True)

    def go_home(self) -> bool:
        """살아서 화톳불에서 먼 곳이면 다크사인으로 복귀 — 사용자: "돌아갈 때 darksign 쓰는 게 좋아 보여. 낙사하고 길을 못 찾아
        힘들어 한다". 소울·인간성을 잃지만 지금 소울 0. 확인창을 화면으로 확인한 뒤에만 누르고, 누른 뒤엔 다시 쓰지 않는다
        (merchantrun.darksign). 죽었으면 어차피 화톳불에서 깬다."""
        s = self.tm.snapshot(within=1.0)
        if not s or s.player.hp <= 0:
            return False
        far = math.dist((s.player.x, s.player.y, s.player.z), tuple(mr.BONFIRE["stand"]))
        if far < 15.0 or not self.tm.goods_count(117):
            return False
        if not hasattr(self.run, "gl"):
            self.run.gl = lambda *a: print(*a, flush=True)
        self.pad.guard(False)
        self.pad.neutral()
        try:
            ok = self.run.darksign()
        except Exception as ex:                 # 실패하면 예전처럼 걸어서 돌아간다
            print(f"   다크사인 오류: {ex}", flush=True)
            ok = False
        self.tm = self.run.tm                   # 로딩 뒤 다시 붙었을 수 있다
        print(f"   다크사인으로 복귀 ({far:.0f} m 밖에서): {'됨' if ok else '실패 — 걸어서'}", flush=True)
        self._ev("darksign", ok=ok, far=round(far))
        return ok

    def _hunt(self, k: int, targets: list[int], dist: float) -> None:
        print(f"── 시도 {k}: 화톳불 휴식 (적 초기화)", flush=True)
        self.go_home()
        if not self.run.rest():
            self.pad.reconnect()          # 가상 패드를 게임이 놓칠 때가 있다 (휴식 실패 — 안내가 키보드 E 로 바뀜)
            control.focus_game()
            if not self.run.rest():
                print("   휴식 실패 — 중단", flush=True)
                return
        self.ensure_two_hand()
        nm = self.run.nm[mr.MAP_A]
        self.run.cur_nm = nm
        self.hist.clear()
        self.last_kill_pos = None
        # 쉰 직후 = 전부 스폰 자리. 포인터를 잡아 두면 스폰을 떠나도 따라갈 수 있다 (3번은 1번이 죽으면 자리를 뜬다)
        time.sleep(1.0)                   # 일어나자마자 잡았더니 1번이 아직 안 놓여 '포인터 없음' 이 난 적이 있다
        s0 = self.tm.snapshot(within=200.0)
        self.ptr_of = {}
        for i, e in enumerate(MAP, 1):
            c0, _ = self.find(tuple(e["pos"]), s0, r=1.5)
            if c0 is not None:
                self.ptr_of[i] = c0.ptr
        for ti in targets:
            e = MAP[ti - 1]
            spawn = tuple(e["pos"])
            self.phase = f"#{ti} 접근"
            s = self.tm.snapshot(within=1.0)
            path = nm.find_path((s.player.x, s.player.y, s.player.z), mr.BOUND_A)
            # 사람 순서(fight)는 경사로에서 만난다 — 3 m 까지 올라간다 (9.5 m 앞에서 기다리면 3번이 평지로 내려와 1번과 같이 붙었다)
            idx, stand = self.standpoint(path, spawn, 3.0 if self.plans.get(ti) == "fight" else dist)
            if stand is None:
                if self.plans.get(ti, "sneak") in ("fight", "knife", "rushg", "rush", "snipe", "plunge", "bomb", "bait"):
                    idx, stand = 1, None                    # 경로 밖(이미 지나친 1번, 경로에서 3 m 안에 안 드는 4번) — 걷지 않고 바로 그 공략으로
                    path = [path[0]] if path else []
                else:
                    print(f"   #{ti}: 경로에서 {dist} m 안에 드는 점 없음 — 건너뜀", flush=True)
                    continue
            near = {"v": False}

            bomb = {"ptr": None, "t": 0.0, "anim": {}}

            def on_tick(sn, _d=None):
                self.note(sn)
                near["v"] = any(c.hp > 0 and not patrol.dormant(c) for c in sn.hostile(25.0))
                for c in sn.hostile(30.0):             # 화염병(3008)을 던지기 시작한 놈 — 떨어지기(2.4 s) 전에 멈춰 방패
                    if c.anim == 3008 and bomb["anim"].get(c.ptr) != 3008:
                        bomb["ptr"], bomb["t"] = c.ptr, time.time()
                    bomb["anim"][c.ptr] = c.anim
            plan = self.plans.get(ti, "sneak")
            tptr = self.ptr_of.get(ti)
            left = {"v": False}

            def mode_fn(_s):
                if bomb["ptr"] is not None and time.time() - bomb["t"] < 2.8:
                    return "retreat"                        # goto 를 끊고 방패로 받는다
                if plan in ("bait", "melee", "study", "fight") and tptr is not None:
                    tc = next((x for x in _s.chars if x.ptr == tptr), None)
                    if tc is not None and math.dist((tc.x, tc.y, tc.z), spawn) > 1.0:
                        left["v"] = True
                        return "retreat"                    # 알아채고 스폰을 떠났다 → 멈춰서 맞이한다
                if plan == "fight":
                    return "sprint"                         # 사람은 달려 올라갔다 (1번은 뒤에 두고)
                return "creep" if near["v"] else "walk"
            walk = (path[1:idx] + [stand]) if (stand is not None and plan not in ("knife", "plunge", "snipe", "rush", "rushg", "bomb")) else []
            if plan == "fight" and tptr is not None:
                tc0 = next((x for x in (self.tm.snapshot(within=200.0) or type("S", (), {"chars": []})).chars if x.ptr == tptr), None)
                if tc0 is not None and math.dist((tc0.x, tc0.y, tc0.z), spawn) > 1.5:
                    walk = []                           # 이미 깨서 따라오는 놈(1번) — 걸어가지 않고 바로 싸운다
            from_flat = False
            if self.last_kill_pos is not None and plan in ("melee", "study") and walk:
                # 앞 적을 잡은 평평한 자리에서 곧게 이어지면(15 m 안) 거기서 다가가 알아채게 하고 그 자리로 끌어온다.
                # 2번은 경로 쪽에선 5.5 m 아래라 못 닿았다(2 s 진전 없음 반복) — 평평한 자리와는 같은 높이, 12.4 m 직선
                fp = nm.find_path(self.last_kill_pos, spawn)
                if fp and sum(math.dist(fp[j], fp[j + 1]) for j in range(len(fp) - 1)) <= 18.0:
                    # 스폰 10 m 앞(평지에서 ~4 m)에서 멈춘다 — 7 m 까지 들어가면 좁은 띠(폭 3~5 m, 서쪽이 통째로 낭떠러지)에서
                    # 싸우게 돼 백스텝이 막히고 결국 떨어졌다 (위치 기록 지도, 2026-09-23)
                    i2, st2 = self.standpoint(fp, spawn, 10.0)
                    if st2 is not None:
                        stand = st2
                        from_flat = True
                        # 평지까지도 내비메시 경로로 — 곧장 걸어가다 떨어져 죽었다 (3번을 잡은 자리 → 평지)
                        to_flat = nm.find_path((s.player.x, s.player.y, s.player.z), self.last_kill_pos) or [self.last_kill_pos]
                        walk = to_flat[1:] + fp[1:i2] + [st2]
                        print(f"   #{ti}: 평평한 자리에서 다가간다 ({len(walk)} 점)", flush=True)
            wi, blocks = 0, 0
            tols = nav.path_tolerances(walk, 1.5)           # 가파른 구간(계단·경사로) 입구는 0.4 m 로 정확히
            while wi < len(walk):
                q = walk[wi]
                r = nav.goto(self.tm, self.pad, q, tolerance=0.8 if q == stand else tols[wi], timeout=20, log=lambda *a: None,
                             on_tick=on_tick, mode_fn=mode_fn, terrain=nm)
                if r == "dead":
                    print("   사망", flush=True)
                    return
                if left["v"]:
                    break
                if bomb["ptr"] is not None and time.time() - bomb["t"] < 2.8 and blocks < 8:
                    # 5번 화염병 — 던지는 놈 쪽으로 몸을 돌리고 방패. 등지고 맞으면 109~152 에 날아가 낭떠러지로 떨어졌다
                    blocks += 1
                    self.block_bomb(bomb["ptr"], bomb["t"])
                    bomb["ptr"] = None
                    continue                                # 같은 경로점부터 다시
                wi += 1
            self.pad.neutral()
            time.sleep(0.3)
            if plan == "bait":
                if self.bait(k, ti, e, tptr):
                    self.heal_if_needed()
                    continue
                # 폭탄이 안 먹었으면(빗나감·붙음·락온 실패) 그 자리에서 근접으로 (전엔 화톳불로 돌아갔다)
                print(f"   #{ti}: 미끼 폭탄 실패 — 근접", flush=True)
                if not self.melee(k, ti, e, tptr, nm, pull_to=None):
                    return
                self.heal_if_needed()
                continue
            if plan == "bomb":
                self.phase = f"#{ti} 폭탄"
                if self.bomb_at(k, ti, e, tptr, nm):
                    self.heal_if_needed()
                    continue
                if ti == 5:
                    print(f"   #{ti}: 폭탄으로 못 잡음 — 방패 들고 붙어 근접", flush=True)
                    plan = "rushg"
                else:
                    print(f"   #{ti}: 폭탄으로 못 잡음 — 그 자리에서 근접", flush=True)
                    if not self.melee(k, ti, e, tptr, nm, pull_to=None):
                        return
                    self.heal_if_needed()
                    continue
            if plan == "rushg":
                # 사람 기록(2026-09-23): 5번에게 방패(LB)를 든 채 걸어서 붙었다 — 걷는 쪽이 5번이라 방패가 늘 5번을 향한다.
                # 화염병 하나는 방패로 받고(76) 하나는 움직이는 중이라 빗나감. 1.6 m 에서 R1 로 처치
                self.phase = f"#{ti} 방패 들고 붙기"
                sp_ = self.tm.snapshot(within=1.0)
                rp = nav.trim_path((nm.find_path((sp_.player.x, sp_.player.y, sp_.player.z), spawn) or [spawn])[1:], spawn)
                t_r = time.time()
                r_ = nav.follow(self.tm, self.pad, rp, terrain=nm, mode_fn=lambda _s: "guard", default_tol=1.0,
                                on_tick=lambda sn, _d=None: self.note(sn),
                                stop_fn=lambda sn: any(x.ptr == tptr and x.dist < 3.0 for x in sn.chars))
                if r_ == "dead":
                    print("   사망", flush=True)
                    return
                self.pad.neutral()
                print(f"   #{ti}: 방패 들고 붙음 {time.time() - t_r:.1f} s", flush=True)
                if not self.melee(k, ti, e, tptr, nm, pull_to=None):
                    return
                self.heal_if_needed()
                continue
            if plan == "rush":
                # 사용자: "화염병 던지는 몹부터, 내가 위에서 아래로". 아래에선 5번이 절벽 턱 뒤라 칼이 안 닿고(0/12), 멈춰서 막으면
                # 3.6 s 마다 던져서 한 걸음도 못 갔다(19 m 에 20 s). 화염병은 던질 때 자리로 떨어지니 멈추지 않고 달려 붙는다
                self.phase = f"#{ti} 달려 붙기"
                sp_ = self.tm.snapshot(within=1.0)
                rp = nm.find_path((sp_.player.x, sp_.player.y, sp_.player.z), spawn) or [spawn]
                t_r = time.time()
                for q in rp[1:]:
                    tc = next((x for x in (self.tm.snapshot(within=40.0) or type("S", (), {"chars": []})).chars if x.ptr == tptr), None)
                    if tc is not None and tc.dist < 3.0:
                        break
                    if nav.goto(self.tm, self.pad, q, tolerance=1.0, timeout=8, log=lambda *a: None, terrain=nm,
                                on_tick=lambda sn, _d=None: self.note(sn), mode_fn=lambda _s: "sprint") == "dead":
                        print("   사망", flush=True)
                        return
                self.pad.neutral()
                print(f"   #{ti}: 달려 붙음 {time.time() - t_r:.1f} s", flush=True)
                if not self.melee(k, ti, e, tptr, nm, pull_to=None):
                    return
                continue
            if plan == "snipe":
                self.phase = f"#{ti} 저격"
                if not self.snipe(ti, tptr, nm):
                    return
                continue
            if plan == "plunge":
                self.phase = f"#{ti} 낙하"
                if not self.plunge(ti, tptr, nm):
                    return
                continue
            if plan == "knife":
                self.phase = f"#{ti} 나이프"
                if not self.knife_pull(ti, tptr, nm):
                    return
                if not self.melee(k, ti, e, tptr, nm, pull_to=None, wait_first=True):
                    return
                self.heal_if_needed()
                continue
            if plan == "fight":
                # 사람 순서: 만나는 자리에서 그대로 막고 리포스트 (평지로 끌어오지 않는다)
                if not self.melee(k, ti, e, tptr, nm, pull_to=None):
                    return
                self.heal_if_needed()
                continue
            if plan in ("melee", "study"):
                # 알아채고 스폰을 떠났으면 앞 적을 잡은 평평한 자리로 물러나 거기서 맞이한다 (사용자: 원하는 지형까지 끌고 가기).
                # 경사로 한가운데서 3번과 싸우다 2.2 m 아래 놈에게 강공이 헛돌고 325 맞았다.
                # 평평한 자리에서 다가간 경우(2번)도 끌어온다 — 그놈을 본 채 백스텝(띠 방향이라 뒤에 바닥이 있다). 등 돌려 달리면 3005(210)를 등에 맞는다
                if not self.melee(k, ti, e, tptr, nm, pull_to=self.last_kill_pos if left["v"] else None, study=plan == "study"):
                    return
                continue
            c, s = self.find(spawn)
            if c is None:
                print(f"   #{ti} {e['npc']}: 스폰 자리에 없음 (이미 움직였거나 죽음)", flush=True)
                self._record(k, ti, e, None, None, {}, {"result": "스폰에 없음"})
                return
            self.align(c.ptr)
            c, s = self.find(spawn)
            if c is None:
                print(f"   #{ti}: 정렬 중에 움직였다 — 알아챔", flush=True)
                self._record(k, ti, e, None, None, {}, {"result": "정렬 중 움직임"})
                return
            trk = self.tracking(c.ptr, time.time())
            mem_state = "준비" if (trk["turned_deg"] or 0) < 15 else "경계"
            img, b64, full = vp.capture_crop(self.tm, c)
            name = f"hunt_{time.strftime('%H%M%S')}_{k}_{ti}_{c.dist:.0f}m.jpg"
            if img is not None:
                img.save(vp.IMG_DIR / name, quality=85)
                full.save(vp.IMG_DIR / name.replace(".jpg", "_full.jpg"), quality=80)
            # 판독은 기록용이라 던진 뒤에 받는다 — 먼저 기다리면 2~4 s 를 적 앞에 서 있게 된다
            jd: dict = {}
            jt = threading.Thread(target=lambda: jd.update(self.judge(b64, c.dist)), daemon=True) if b64 else None
            if jt:
                jt.start()
            if not self.select_bomb():
                print("   파이어밤 칸을 못 고름 — 중단", flush=True)
                return
            c2, _ = self.find(spawn)
            if c2 is None:
                print(f"   #{ti}: 폭탄 고르는 동안 움직였다 — 알아챔", flush=True)
                self._record(k, ti, e, c, trk, jd, {"result": "판독 중 움직임", "mem_state": mem_state}, name)
                return
            res = self.throw_at(c2.ptr)
            res["mem_state"] = mem_state
            if jt:
                jt.join(30)
            self._record(k, ti, e, c2, trk, jd, res, name)
            print(f"   #{ti} {e['npc']} {c2.dist:.1f} m 보는 각 {vp.facing_player(c2, s.player):.0f}° 몸 {trk['turned_deg']}° 돎 → 메모리 {mem_state}, "
                  f"3.8 {jd.get('state')}({jd.get('ms')} ms) | 폭탄 {res['result']} (HP {res['hp0']}→{res['hp_after']}) 애니 {res['anims_after'][:5]}  [{name}]",
                  flush=True)
            if res["result"] != "처치":
                print("   못 잡음 — 화톳불로", flush=True)
                return
            sk = self.tm.snapshot(within=1.0)
            if sk:
                self.last_kill_pos = (sk.player.x, sk.player.y, sk.player.z)
            if self.observe_s > 0:
                self.observe(k, ti)
        print("   목표 전부 처치", flush=True)
        if self.to_merchant:
            self.go_merchant()
            return
        if self.lure_group:
            if not self.lure_fight(k, nm, self.lure_group):
                return
        if self.then_run:
            self.run_past(nm)

    observe_s = 0.0
    plans: dict = {}
    then_run = False
    to_merchant = False
    lure_group: list = []

    def lure_fight(self, k: int, nm, group: list[int]) -> bool:
        """위 무리(4·5·6 + 지도 밖 한 놈)를 하나씩 평지로 꾀어 잡는다. 그냥 달려 지나가면 굽이(~90 m)에서 4·6·5 가 한꺼번에
        붙어 23 s 만에 죽었다. 평지에서 경로를 따라 천천히 올라가다 누구든 자리를 뜨면(알아챔) 곧장 평지로 돌아와
        방패 들고 기다리고, 먼저 온 놈부터 근접 반격. 평지는 5번(화염병)에서 20.7 m — 사거리(~18 m) 밖."""
        idx = {v: k_ for k_, v in self.ptr_of.items()}
        home = {}
        s0 = self.tm.snapshot(within=80.0)
        for c in (s0.hostile(80.0) if s0 else []):
            if c.hp > 0 and (idx.get(c.ptr) in group or c.ptr not in idx):
                home[c.ptr] = (c.x, c.y, c.z)
        for rnd in range(5):
            sn = self.tm.snapshot(within=80.0)
            alive = {c.ptr: c for c in (sn.hostile(80.0) if sn else []) if c.ptr in home and c.hp > 0}
            if not alive:
                print("   위 무리 전부 처치", flush=True)
                return True
            self.phase = f"꾀기 {rnd + 1}"
            # 이미 누가 오고 있으면 올라가지 않는다
            moving = [p_ for p_, c in alive.items() if math.dist((c.x, c.y, c.z), home[p_]) > 1.5]
            if not moving:
                path = nm.find_path(ARENA, mr.BOUND_A) or []
                woke = {"p": None}

                def on_tick(sn_, _d=None):
                    self.note(sn_)
                    for c in sn_.hostile(80.0):
                        if c.ptr in alive and c.hp > 0 and math.dist((c.x, c.y, c.z), home[c.ptr]) > 1.5:
                            woke["p"] = c.ptr

                def mode_fn(_s):
                    return "retreat" if woke["p"] else "creep"
                for q in path[1:]:
                    r = nav.goto(self.tm, self.pad, q, tolerance=1.2, timeout=12, log=lambda *a: None, terrain=nm,
                                 on_tick=on_tick, mode_fn=mode_fn)
                    if r == "dead":
                        return False
                    if woke["p"]:
                        break
                if not woke["p"]:
                    print("   꾀기: 경로 끝까지 아무도 안 움직임", flush=True)
                    return True
                who = idx.get(woke["p"], "?")
                print(f"   꾀기 {rnd + 1}: #{who} 가 알아챔 — 평지로 돌아간다", flush=True)
            # 평지로 (경로를 따라). 달려야 먼저 닿는다
            sp = self.tm.snapshot(within=1.0)
            back = nm.find_path((sp.player.x, sp.player.y, sp.player.z), ARENA) or [ARENA]
            for q in back[1:]:
                if nav.goto(self.tm, self.pad, q, tolerance=1.0, timeout=10, log=lambda *a: None, terrain=nm,
                            on_tick=lambda sn_, _d=None: self.note(sn_), mode_fn=lambda _s: "sprint") == "dead":
                    return False
            self.pad.neutral()
            # 먼저 오는 놈을 기다린다 (20 s)
            t_w = time.time()
            tgt = None
            while time.time() - t_w < 20.0:
                sn = self.tm.snapshot(within=40.0)
                if sn:
                    near = [c for c in sn.hostile(12.0) if c.ptr in home and c.hp > 0]
                    if near:
                        tgt = min(near, key=lambda c: c.dist)
                        if tgt.dist < 7.0:
                            break
                    far = min((c for c in sn.hostile(40.0) if c.ptr in home and c.hp > 0), key=lambda c: c.dist, default=None)
                    self.pad.guard(True)
                    if far is not None:
                        self.aim(sn, far)
                time.sleep(0.02)
            if tgt is None:
                print("   꾀기: 아무도 평지로 안 옴", flush=True)
                continue
            ti = idx.get(tgt.ptr, 0)
            e = MAP[ti - 1] if ti else {"npc": tgt.npc_param, "pos": list(home[tgt.ptr])}
            print(f"   꾀기: #{ti or '?'} ({tgt.npc_param}) 가 평지로 옴 — 근접", flush=True)
            if not self.melee(k, ti, e, tgt.ptr, nm, pull_to=None, wait_first=True):
                return False
        return True

    def run_past(self, nm) -> dict:
        """아래 무리(1·3·2)를 치운 뒤 남은 4·5·6 을 싸우지 않고 달려서 지나간다 — 목표는 상인까지 가는 것.
        경로(내비메시)로 BOUND_A 까지 달리며 맞은 것·쫓아오는 놈을 적는다."""
        self.phase = "달려 지나가기"
        s = self.tm.snapshot(within=1.0)
        hp0, t0 = s.player.hp, time.time()
        path = nm.find_path((s.player.x, s.player.y, s.player.z), mr.BOUND_A) or [mr.BOUND_A]
        tols = nav.path_tolerances(path[1:], 1.5)
        hits, chasers = [], set()
        last = {"hp": hp0}

        def on_tick(sn, _d=None):
            self.note(sn)
            if sn.player.hp < last["hp"]:
                idx = {v: k_ for k_, v in self.ptr_of.items()}
                who = [(f"#{idx.get(x.ptr, '?')}", round(x.dist, 1), x.anim) for x in sn.hostile(20.0) if x.hp > 0]
                hits.append((round(time.time() - t0, 1), last["hp"] - sn.player.hp, who))
                self._ev("hit", dmg=last["hp"] - sn.player.hp, who=who)
                print(f"      달리다 맞음 {last['hp'] - sn.player.hp} ← {who}", flush=True)
            last["hp"] = sn.player.hp
            for x in sn.hostile(6.0):
                if x.hp > 0:
                    chasers.add(x.ptr)
        res = "도착"
        for q, tol in zip(path[1:], tols):
            r = nav.goto(self.tm, self.pad, q, tolerance=tol, timeout=15, log=lambda *a: None, terrain=nm,
                         on_tick=on_tick, mode_fn=lambda _s: "sprint")
            if r == "dead":
                res = "사망"
                break
        s = self.tm.snapshot(within=1.0)
        idx = {v: k_ for k_, v in self.ptr_of.items()}
        out = {"result": res if s else "로딩/사망", "hp_lost": (hp0 - s.player.hp) if s else None, "secs": round(time.time() - t0, 1),
               "hits": hits, "near": sorted(f"#{idx.get(q, '?')}" for q in chasers)}
        print(f"   달려 지나가기: {out}", flush=True)
        self._ev("run_past", **out)
        return out

    def approach_speed(self, ptr) -> float:
        h = [x for x in self.hist.get(ptr, []) if time.time() - x[0] <= 0.6]
        if len(h) < 3 or h[-1][0] - h[0][0] < 0.2:
            return 0.0
        return (h[0][3] - h[-1][3]) / (h[-1][0] - h[0][0])

    def _raw(self, a, n) -> str | None:
        try:
            return self.tm.pm.read_bytes(a, n).hex() if a else None
        except Exception:
            return None

    def _cam_angle(self, c, s) -> float:
        """카메라 **위치**에서 본 적 방향 − 카메라 정면 (rad). 플레이어 위치에서 재면 1.2 m 앞 놈은 어깨 너머 카메라에선
        옆으로 치우쳐 보여서, 락온이 제대로 걸렸는데도 15 m 뒤 5번이 '가운데' 로 뽑혀 락온을 풀어 버렸다 (세 번 연속)."""
        m = vp.cam_matrix(self.tm)
        if m is None:
            return vp.rel_to_camera(s, c)
        fx, fz = float(m[2][0]), float(m[2][2])
        return (math.atan2(c.x - float(m[3][0]), c.z - float(m[3][2])) - math.atan2(fx, fz) + math.pi) % (2 * math.pi) - math.pi

    def backstep_pull(self, ptr, pull_to, nm, max_steps: int = 6) -> int:
        """사용자: "후진을 백스텝으로" — 스틱 중립 + B 짧게 = 백스텝. 그놈을 본 채 뒤로 뛰고 무적 프레임이 있어 방패가 늘 그놈 쪽이다
        (등 돌려 달려가다 2번 3005 를 등에 맞고(210), 한 번은 끌어오다 죽었다). 등 뒤 60° 안에 평평한 자리가 있고
        뒤 2.2 m 에 바닥이 있을 때만 뛴다. 그놈이 1.8 m 안이면 그만. → 뛴 횟수."""
        n = 0
        for _ in range(max_steps):
            s = self.tm.snapshot(within=30.0)
            c = next((x for x in s.chars if x.ptr == ptr), None) if s else None
            if c is None or c.hp <= 0 or s.player.heading is None:
                break
            p = s.player
            if math.dist((p.x, p.z), (pull_to[0], pull_to[2])) < 1.5 or c.dist < 1.8:
                break
            bx, bz = math.sin(p.heading), math.cos(p.heading)        # 정면 = heading + π → 등 뒤 = heading
            ax, az = pull_to[0] - p.x, pull_to[2] - p.z
            off = abs((math.atan2(ax, az) - math.atan2(bx, bz) + math.pi) % (2 * math.pi) - math.pi)
            if abs(math.degrees(patrol.rel_angle(p, c))) > 30 and not self.turn_to(ptr, 0.5):
                break
            if math.degrees(off) > 60 or not nav.ground_ahead(nm, p, bx, bz, reach=2.2):
                print(f"      백스텝 그만: 평평한 자리가 등 뒤에서 {math.degrees(off):.0f}° / 뒤 바닥 {nav.ground_ahead(nm, p, bx, bz, reach=2.2)}", flush=True)
                break
            self.pad.move(0.0, 0.0)
            self.pad.guard(False)
            time.sleep(0.1)                           # 스틱 놓음 인식 여유 (백스텝 공격과 같은 이유)
            self._press(control.B.XUSB_GAMEPAD_B)
            t1 = time.time()
            while time.time() - t1 < 0.65:
                s2 = self.tm.snapshot(within=30.0)
                if s2:
                    self.note(s2)
                    self._track(next((x for x in s2.chars if x.ptr == ptr), None))
                time.sleep(0.02)
            self.pad.guard(True)
            n += 1
        return n

    use_lock = False
    AIM_DEG = 20.0
    STICK_RELEASE_S = 0.16    # 사용자: 스틱을 놓은 걸 게임이 알아채는 데 60fps ~0.16 s (30fps 0.33 s) — 그 전에 R1 이면 발차기

    def aim(self, s, c) -> bool:
        """락온 없이 겨누기 — 사용자: "DS1 은 락온 자체가 문제가 많아 정렬·카메라에 능숙한 고수는 락온을 안 한다".
        몸(heading)이 그놈에서 AIM_DEG 넘게 벗어나면 스틱을 살짝 그놈 쪽으로(방패 든 채면 방패 걸음으로 돈다), 안이면 놓는다.
        → 스틱을 놓은 지 STICK_RELEASE_S 가 지나 R1·B 를 눌러도 되나 (약공이 발차기로, 백스텝이 구르기로 안 바뀌게)."""
        p = s.player
        if p.heading is None or s.cam_yaw is None:
            return False
        if abs(math.degrees(patrol.rel_angle(p, c))) > self.AIM_DEG:
            # 0.35 로는 거의 안 돌았다 (방패 든 채 64° 가 그대로)
            self.pad.move(*[0.55 * v for v in control.world_to_stick(c.x - p.x, c.z - p.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)])
            self._stick_zero_t = None
            return False
        if self._stick_zero_t is None:
            self.pad.move(0.0, 0.0)
            self._stick_zero_t = time.time()
        return time.time() - self._stick_zero_t >= self.STICK_RELEASE_S

    def turn_to(self, ptr, timeout: float = 0.8) -> bool:
        """방패 든 채 그놈 쪽으로 몸을 돌리고 스틱을 놓을 때까지 (백스텝으로 물러나기 전에)."""
        self._stick_zero_t = None
        t = time.time()
        while time.time() - t < timeout:
            s = self.tm.snapshot(within=30.0)
            c = next((x for x in s.chars if x.ptr == ptr), None) if s else None
            if c is None:
                return False
            self.pad.guard(True)
            if self.aim(s, c):
                return True
            time.sleep(0.01)
        self.pad.move(0.0, 0.0)
        return False

    def lock_state(self, ptr) -> str:
        """"target" / "other" / "none" — PlayerIns+0xEF0(락온 대상 핸들, 없으면 -1)을 그놈 핸들과 비교.
        카메라 각도로 짐작하던 때는 1.2 m 앞 놈을 잡고도 '15 m 뒤 5번' 이라 판정해 풀고, 먼 2번에 걸린 채로는 '됨' 이라 해서
        옆구리를 62~66 씩 맞았다."""
        h = self.tm.lock_target()
        if h is None or h == -1:
            return "none"
        return "target" if h == self.tm.handle(ptr) else "other"

    def cam_pitch(self) -> float | None:
        """카메라 상하 기울기(°, + 가 위). ChrFollowCam 정면 행의 y = sin(기울기) — 실측 2026-09-23: 오른 스틱 +0.7 을 0.15 s 치면
        ~10° 씩 올라가 −40°(−0.65) → +40°(+0.64). (vision_probe.cam_matrix 주석의 '기울기 없음' 은 틀렸다)"""
        m = vp.cam_matrix(self.tm)
        if m is None:
            return None
        return math.degrees(math.asin(max(-1.0, min(1.0, float(m[2][1])))))

    def set_pitch(self, deg: float, tol: float = 1.5) -> float | None:
        """카메라를 deg 기울기로. 락온 없이 던지면 카메라 기울기대로 날아간다 (−40° 로 숙인 채 던진 나이프 3/3 발밑)."""
        pt = None
        for _ in range(14):
            pt = self.cam_pitch()
            if pt is None or abs(deg - pt) <= tol:
                break
            err = deg - pt
            self.pad.look(0.0, 0.7 if err > 0 else -0.7)
            time.sleep(max(0.02, min(0.25, abs(err) / 10.0 * 0.15)))
            self.pad.look(0.0, 0.0)
            time.sleep(0.12)
        return pt

    def elevation(self, c, s) -> float:
        """그놈 가슴(발 +1.2 m)을 내 손(발 +1.3 m)에서 올려다보는 각(°)."""
        p = s.player
        return math.degrees(math.atan2((c.y + 1.2) - (p.y + 1.3), math.dist((p.x, p.z), (c.x, c.z))))

    def reset_camera(self) -> None:
        """카메라 기울기 초기화 — R3 를 누르면 카메라가 등 뒤 기본 높이로 돌아온다. 그때 락온이 걸리면 한 번 더 눌러 푼다.
        락온 없이 던지면 **카메라 기울기대로** 날아간다: 저격 때 오른 스틱으로 카메라를 숙여 둔 채 2번에게 던졌더니
        조준 0.0° 인데 3/3 발밑에 꽂혔다 (화면: 카메라가 캐릭터를 거의 수직으로 내려다봄)."""
        self._r3(0.35)
        if self.tm.lock_target() not in (None, -1):
            self._r3(0.2)

    def _r3(self, wait: float = 0.3) -> None:
        self.pad.lock_on()
        t = time.time()
        while time.time() - t < wait:
            self.pad.release_due()
            time.sleep(0.01)

    def lock_verified(self, ptr, align: bool = True) -> bool:
        """그놈에게 락온. 이미 걸려 있으면 그대로, 딴 놈이면 R3 로 풀고, 정렬(align) 뒤 R3. 결과는 메모리로 확인해
        딴 놈에게 걸리면 다시 푼다 (R3 는 토글).
        붙은 적에겐 align=False — 카메라를 돌리는 동안 1.2 m 에서 3000 에 57 씩 맞았다 (락온은 가까운 놈을 먼저 잡는다)."""
        st = self.lock_state(ptr)
        if st == "target":
            return True
        if st == "other":
            self._r3(0.15)
        if align:
            self.align(ptr)
        self._r3(0.3)
        st = self.lock_state(ptr)
        if st == "target":
            return True
        if st == "other":
            h = self.tm.lock_target()
            idx = {v: k_ for k_, v in getattr(self, "ptr_of", {}).items()}
            who = next((f"#{idx.get(q, '?')}" for q in idx if self.tm.handle(q) == h), "?")
            print(f"      락온이 다른 놈({who})에게 — 푼다", flush=True)
            self._r3(0.1)
        return False

    last_kill_pos = None
    melee_style = "block"     # "block": 막고 → 강공 / "roll": 적 공격 시작 → 구르기(무적) → 약공, 휘두르지 않을 땐 강공
    ROLL_DELAY = 0.35         # 공격 애니 시작 뒤 이만큼 기다렸다 구른다 — 맞기까지 0.5~0.9 s(중앙 ~0.75), 구르기 무적은 누르고 ~0.1~0.5 s
    # 구르기 누르고 이만큼 뒤 약공 — 구르는 중에 눌러 구르기 공격(구른 방향 그대로)이 나가게 한다. 2~3.5 m 에서 그놈 쪽으로
    # 굴렀으니 그 방향에 그놈이 있다 (사용자: "구르기와 약공 간격이 짧아야"). 0.70 s(구른 뒤 일반 약공)는 옆 구르기와 함께 6/6 헛돎.
    ROLL_TO_R1 = 0.45
    # 적 애니 → 대응 (style "counter"). 254000 관찰 — 락온하고 방패로 받아 '애니 시작 → 막은 순간' 을 쟀다:
    #   3003 1.28 s → 시작하자마자 강공(~0.7 s)이 먼저 닿는다 — 0.9·1.2 m 에서 2/2 한 방, 1.7·2.1 m 에선 헛침(170 맞음)
    #   3010 1.10 s 인데 1.2 m 강공도 0 피해·45 맞음 → 방패
    #   3001 0.83 s · 3004 1.05 s 는 연타 둘째 — 약공 반격 0/3 (81 맞음) → 방패
    #   3000 0.63 s · 3005 (구르다 맞음 2/2) · 3002 (168 맞음, 가장 셈) → 방패
    #   3500 = 방패에 튕겨 휘청 (앞선 공격을 막은 직후에 나온다, 스스로는 안 닿음 2/2). 이때 약공 = **리포스트** — 피해는 누르고 ~1 s 뒤에
    #          들어가 약공 창(0.9 s)엔 0 으로 찍히고 곧 HP 0 (9/9 처치). 1.6 m 밖이면 구르며 들어가 약공 (5/5)
    #   2xxx (맞고 휘청) → 곧바로 약공 한 번 더
    #   (추가) 락온 없이 3003 강공은 0/10 (333600 이 나가지만 안 닿거나 139 맞바꿈) → 방패. 254000 은 막고 3500 리포스트로만 잡는다
    REACT = {3003: "guard", 3010: "guard", 3004: "guard", 3001: "guard", 3000: "guard", 3002: "guard", 3005: "guard", 3500: "roll"}
    # 255010(2번, HP 85, 3005 한 방 210): 막으면 똑같이 3500 으로 1.38 s 휘청이지만 약공은 리포스트가 안 된다 (0 피해 → 703) → 강공
    #   3003 강공은 1.2 m 에서 0 피해 → 이어진 3009·3004 에 466 맞고 사망 (254000 과 다르다) → 방패, 막으면 3500 이 온다
    #   막아도 한 대에 31~74 가 들어오고 가드가 깨지면 322 → 막지 말고 백스텝으로 피한 뒤 백스텝 공격 ("bs"). 3009 는 0.22 s 라 방패
    REACT_NPC = {255010: {3000: "bs", 3003: "bs", 3004: "bs", 3005: "bs", 3009: "guard", 3500: "roll_heavy"}}
    # 백스텝 시작(스틱 중립 0.1 s 전) = 닿는 시각 − 0.55. 닿는 시각: 3000 0.89·3003 0.93·3005 1.10 (막은 순간), 3004 는 254000 의 1.05
    BS_AT = {3000: 0.34, 3003: 0.38, 3004: 0.45, 3005: 0.55}
    # 실측(화톳불, 2026-09-23): 스틱을 놓은 **그 순간** B 여도 10/10 백스텝(애니 680, 뒤로 2.06 m) — 멈춰 설 시간은 필요 없다.
    # R1 을 B 뒤 0.1·0.25 s 에 누르면 씹히고, 0.4·0.55 s 면 백스텝 공격(333500)이 B 뒤 0.66 s 에 시작해 앞으로 1.7~2.8 m 파고든다.
    BS_TO_R1 = 0.45
    # 츠바이헨더 +5 양손 (사용자: 하벨 반지·츠바이헨더 5강, 힘이 모자라 양손). 방패가 없어 막고 튕겨 리포스트(3500)가 잘 안 나올 것 —
    # 사용자가 가장 잘 맞는다고 본 **백스텝 → 백스텝 공격** 을 거의 모든 공격에. 할로우 HP 75 라 닿으면 한 방.
    # 화톳불 실측: 약공 264000 후딜 ~2.7 s, 백스텝 공격 B 뒤 ~0.7 s 에 264500 시작, 구르기 공격 264900. 3009 는 0.22 s 라 막는다
    ZWEI = False
    HEAVY_FIRST = False
    BRUTE = False                       # 가드 안 함 + 강공 + 적을 가리지 않고 에스트 (강인도 세팅)
    REACT_ZWEI = {3000: "bs", 3001: "bs", 3002: "bs", 3003: "bs", 3004: "bs", 3005: "bs", 3006: "bs", 3007: "bs",
                  3010: "bs", 3009: "guard", 3500: "roll"}
    BS_AT_ZWEI = {3000: 0.08, 3001: 0.28, 3002: 0.45, 3003: 0.73, 3004: 0.5, 3005: 0.55, 3006: 0.4, 3007: 0.4, 3010: 0.55}
    REACH = {"light": 1.4, "heavy": 1.6}      # 중심 거리. 처치는 전부 1.2 m 안, 1.6 m 넘으면 약공·강공 5/5 헛침

    def backstep_attack(self, c, s, ptr, nm) -> dict:
        """백스텝(스틱 중립 + B) → BS_TO_R1 뒤 R1 = 백스텝 공격. 뒤 2.2 m 에 바닥이 없으면 안 한다."""
        p = s.player
        if p.heading is None or not nav.ground_ahead(nm, p, math.sin(p.heading), math.cos(p.heading), reach=2.2):
            return {"done": False, "why": "뒤에 바닥 없음"}
        if abs(math.degrees(patrol.rel_angle(p, c))) > 40:                   # 백스텝·그 공격은 몸이 보는 쪽 기준
            return {"done": False, "why": f"몸이 {math.degrees(patrol.rel_angle(p, c)):.0f}° 딴 데"}
        if not nav.ground_ahead(nm, p, -math.sin(p.heading), -math.cos(p.heading), reach=3.0):   # 백스텝 공격은 앞으로 1.7~2.8 m 파고든다
            return {"done": False, "why": "앞에 바닥 없음"}
        hp0, ehp0 = p.hp, c.hp
        self.pad.move(0.0, 0.0)
        self.pad.guard(False)
        # 스틱 중립 → B. DS1 은 B 를 **뗄 때** 판정해 누름(0.06 s)까지 합쳐 ~0.07 s 로도 10/10 백스텝이었다.
        # 사용자: 스틱 놓음 인식이 60fps 에서 ~0.16 s → 여유로 0.1 s 더 (공격이 닿기 0.45 s 전에 눌러야 해서 더 길게는 못 둔다)
        time.sleep(0.1)
        self._press(control.B.XUSB_GAMEPAD_B)
        t1 = time.time()
        my_min, e_min, e_anims, r1_done = hp0, ehp0, [], False
        while time.time() - t1 < self.BS_TO_R1 + 1.3:
            if not r1_done and time.time() - t1 >= self.BS_TO_R1:
                self._press(control.B.XUSB_GAMEPAD_RIGHT_SHOULDER)
                r1_done = True
            if time.time() - t1 > self.BS_TO_R1 + 0.9:
                self.pad.guard(True)
            s2 = self.tm.snapshot(within=10.0)
            if s2:
                my_min = min(my_min, s2.player.hp)
                c2 = next((x for x in s2.chars if x.ptr == ptr), None)
                e_min = 0 if c2 is None else min(e_min, c2.hp)
                self._track(c2)
                if c2 is not None and (not e_anims or e_anims[-1][1] != c2.anim):
                    e_anims.append((round(time.time() - t1, 2), c2.anim, round(c2.dist, 1)))
                if e_min <= 0:
                    break
            time.sleep(0.01)
        return {"done": True, "enemy_dmg": ehp0 - e_min, "enemy_dead": e_min <= 0, "hit_after": hp0 - my_min, "e_anims": e_anims}

    def follow_heavy(self, r: dict, ptr, nm, locked: bool) -> dict | None:
        """약공이 맞았는데 안 죽었으면(HP 85 인 2번 등) 곧장 강공 — 츠바이헨더 강공(세로 내려찍기)은 인간형 작은 놈을
        경직시키거나 넘어뜨린다 (사용자)."""
        if not self.ZWEI or not r.get("enemy_dmg") or r.get("enemy_dead"):
            return None
        s = self.tm.snapshot(within=10.0)
        c = next((x for x in s.chars if x.ptr == ptr), None) if s else None
        if c is None or c.hp <= 0 or c.dist > 2.8:
            return None
        r2 = self.strike("heavy", c, s, ptr, locked=locked, nm=nm)
        print(f"      이어서 강공 → 적 피해 {r2.get('enemy_dmg')}, 적 애니 {r2.get('e_anims')}", flush=True)
        self._ev("act", act="heavy_follow", **r2)
        return r2

    def ensure_two_hand(self) -> None:
        """양손으로 잡혀 있나 (PlayerGameData+0x308 = 3). 아니면 Y — 힘이 모자라 한손이면 츠바이헨더가 제대로 안 나간다."""
        if not self.ZWEI:
            return
        for _ in range(2):
            g = self.tm.grip()
            if g == 3:
                return
            print(f"   양손 아님 ({g}) — Y", flush=True)
            self.pad.tap(control.B.XUSB_GAMEPAD_Y, 0.1)
            time.sleep(0.15)
            self.pad.release_due()
            time.sleep(1.2)

    def _track(self, c) -> None:
        if c is not None and c.anim != self._etrk["anim"]:
            self._etrk = {"anim": c.anim, "t": time.time()}

    def strike(self, kind: str, c, s, ptr, watch: float | None = None, locked: bool = False, nm=None) -> dict:
        """약공(R1)/강공(R2) 한 번. 약공 0.9 s·강공 1.3 s(watch 로 바꿈) 동안 적 HP·내 HP·적 애니를 본다.
        **스틱 + R1 을 같이 넣으면 발차기다** (control.kick 실측) — '약공 0 피해' 가 전부 이것이었다(리포스트만 우선이라 들어감).
        그래서 약공은 락온이면 스틱 없이, 아니면 스틱으로 먼저 돌려 놓고 놓은 뒤에 R1."""
        p = s.player
        st = control.world_to_stick(c.x - p.x, c.z - p.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X) if s.cam_yaw is not None else (0.0, 0.0)
        hp0, ehp0 = p.hp, c.hp
        if p.heading is not None and abs(math.degrees(patrol.rel_angle(p, c))) > 40 and locked:
            # 락온이면 몸이 그놈을 향해 있어야 한다 — 아니면 락온이 풀렸거나 딴 놈. 치면 엉뚱한 데로 나간다
            return {"enemy_dmg": 0, "enemy_dead": False, "hit_after": 0, "e_anims": [], "skipped": f"몸이 {math.degrees(patrol.rel_angle(p, c)):.0f}° 딴 데"}
        fx, fz = ((-math.sin(p.heading), -math.cos(p.heading)) if (locked and p.heading is not None) else (c.x - p.x, c.z - p.z))
        if kind == "heavy" and nm is not None and not nav.ground_ahead(nm, p, fx, fz, reach=1.8):
            return {"enemy_dmg": 0, "enemy_dead": False, "hit_after": 0, "e_anims": [], "skipped": "앞에 바닥 없음"}
        self.pad.guard(False)
        if kind == "heavy":
            self.pad.heavy(stick=None if locked else st)
        else:
            if not locked and p.heading is not None and abs(math.degrees(patrol.rel_angle(p, c))) > self.AIM_DEG:
                self.pad.move(*[0.4 * v for v in st])
                time.sleep(0.08)
                self.pad.move(0.0, 0.0)
                time.sleep(self.STICK_RELEASE_S)      # 스틱 놓음이 먹기 전에 R1 이면 발차기
            self._press(control.B.XUSB_GAMEPAD_RIGHT_SHOULDER)
        t1 = time.time()
        my_min, e_min, e_anims, my_anims = hp0, ehp0, [], [(0.0, p.anim)]
        while time.time() - t1 < (watch or (1.3 if kind == "heavy" else 0.9)):
            if time.time() - t1 > 0.25:
                self.pad.guard(True)   # 휘두른 뒤 바로 방패 — 누르고 있으면 회복 끝나자마자 올라간다 (강공 뒤 1.3 s 무방비로 3009·3004 에 맞았다)
            self.pad.release_due()
            s2 = self.tm.snapshot(within=10.0)
            if s2:
                my_min = min(my_min, s2.player.hp)
                c2 = next((x for x in s2.chars if x.ptr == ptr), None)
                e_min = 0 if c2 is None else min(e_min, c2.hp)
                self._track(c2)
                if c2 is not None and (not e_anims or e_anims[-1][1] != c2.anim):
                    e_anims.append((round(time.time() - t1, 2), c2.anim, round(c2.y - s.player.y, 1)))   # 높이차 — 3500 뒤 사라지는 게 떨어져서인가
                if not my_anims or my_anims[-1][1] != s2.player.anim:
                    my_anims.append((round(time.time() - t1, 2), s2.player.anim))    # 우리 공격이 실제로 나갔나 (막은 경직 중엔 씹힐 수 있다)
                if e_min <= 0:
                    break
            time.sleep(0.01)
        self.pad.neutral()
        return {"enemy_dmg": ehp0 - e_min, "enemy_dead": e_min <= 0, "hit_after": hp0 - my_min, "e_anims": e_anims, "my_anims": my_anims}

    def _press(self, button, hold: float = 0.06) -> None:
        """누르고 **뗀다** — tap 만 하고 release_due 를 안 부르면 눌린 채 남아 다음 누름이 게임에 안 간다 (farm.rest 에서 겪음)."""
        self.pad.tap(button, hold)
        time.sleep(hold + 0.03)
        self.pad.release_due()

    def roll_attack(self, c, p, cam_yaw, nm, ptr) -> dict:
        """그놈 쪽으로 구르고(스틱과 B 를 같은 입력에) ROLL_TO_R1 뒤 약공(R1, 스틱은 그놈 쪽). 구를 방향 2.5 m 에 바닥이 없으면 안 구른다.
        기록: 구르는 동안 내가 맞았나(무적 성공?), 약공이 들어갔나."""
        dx, dz = c.x - p.x, c.z - p.z
        if cam_yaw is None:
            return {"rolled": False, "why": "카메라 없음"}
        # 2~3.5 m 에서 공격을 시작한 놈 쪽으로 구른다 — 무적으로 그 공격을 뚫고 들어가 코앞에서 구르기 공격.
        # (붙은 적 쪽으로 구르면 뚫고 지나가 등 뒤(0.96 m → 2.83 m, −157°), 옆으로 구르면 그놈이 돌진해 지나가 등 뒤 3~4 m — 둘 다 헛돎.
        #  2.2 m 에서 그놈 쪽으로 구른 한 번은 약공 때 정면 9°·1.0 m 였다)
        if not nav.ground_ahead(nm, p, dx, dz, reach=2.5):
            return {"rolled": False, "why": "구를 방향에 바닥 없음"}
        st = control.world_to_stick(dx, dz, cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
        hp0, ehp0 = p.hp, c.hp
        self.pad.guard(False)
        self.pad.move(*st)
        self._press(control.B.XUSB_GAMEPAD_B)
        t_roll = time.time()
        my_min, e_min = hp0, ehp0
        while time.time() - t_roll < self.ROLL_TO_R1:
            s = self.tm.snapshot(within=10.0)
            if s:
                my_min = min(my_min, s.player.hp)
                ce = next((x for x in s.chars if x.ptr == ptr), None)
                e_min = 0 if ce is None else min(e_min, ce.hp)
                self._track(ce)
            time.sleep(0.01)
        hit_in_roll = hp0 - my_min
        s = self.tm.snapshot(within=10.0)
        ce = next((x for x in s.chars if x.ptr == ptr), None) if s else None
        geo = {}
        if ce is not None and s.player.heading is not None:
            # 약공을 누르는 순간 그놈이 어디 있나 — 12번 중 10번이 헛돌았다. 적 쪽으로 구르면 지나쳐 등 뒤로 가는지 본다
            geo = {"d_at_r1": round(ce.dist, 2), "off_at_r1": round(math.degrees(patrol.rel_angle(s.player, ce))),
                   "d_start": round(c.dist, 2), "moved": round(math.dist((p.x, p.z), (s.player.x, s.player.z)), 2)}
        if ce is not None and s.cam_yaw is not None:
            self.pad.move(*control.world_to_stick(ce.x - s.player.x, ce.z - s.player.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X))
        self._press(control.B.XUSB_GAMEPAD_RIGHT_SHOULDER)
        self.pad.move(0.0, 0.0)
        t_a = time.time()
        my_after = my_min
        e_anims = []
        while time.time() - t_a < 1.2:        # 0.9 s 로는 구르기 끝(~0.7 s) 뒤 나가는 공격이 닿기 전에 끝날 수 있다
            s = self.tm.snapshot(within=10.0)
            if s:
                my_after = min(my_after, s.player.hp)
                ce = next((x for x in s.chars if x.ptr == ptr), None)
                e_min = 0 if ce is None else min(e_min, ce.hp)
                self._track(ce)
                if ce is not None and (not e_anims or e_anims[-1][1] != ce.anim):
                    e_anims.append((round(time.time() - t_a, 2), ce.anim))
            time.sleep(0.02)
        geo["e_anims"] = e_anims
        return {"rolled": True, "hit_in_roll": hit_in_roll, "hit_after": my_min - my_after, "enemy_dmg": ehp0 - e_min,
                "enemy_dead": e_min <= 0, **geo}

    @staticmethod
    def study_table(ev: list) -> list[dict]:
        """공격 애니마다 시작 → 첫 막기(스태미나 감소)/피격(HP 감소)까지 걸린 시간. 그 애니가 이어지는 동안(다음 애니 전)의 것만 센다."""
        out = []
        es = [x for x in ev if x[0] == "e"]
        for i, (_, t, anim, d) in enumerate(es):
            if not (3000 <= (anim or 0) < 3600):
                continue
            t_end = es[i + 1][1] if i + 1 < len(es) else t + 2.0
            hit = next((x for x in ev if x[0] in ("sp", "hp") and t < x[1] <= t_end), None)
            out.append({"anim": anim, "dist": d, "dur": round(t_end - t, 2),
                        "next": es[i + 1][2] if i + 1 < len(es) else None,
                        "hit_at": None if hit is None else round(hit[1] - t, 3), "kind": None if hit is None else hit[0],
                        "amount": None if hit is None else hit[2]})
        return out

    def melee(self, k: int, ti: int, e: dict, ptr, nm, pull_to=None, study: bool = False, wait_first: bool = False) -> bool:
        """정면 돌파 — 사용자: "폭탄이 없으면 근접으로 정면 돌파, 캐릭터가 강해서 강공이 먹히면 한 방에 끝난다".
        같은 높이(높이차 0.8 m 미만)로 2 m 안이면 막고 → R2 강공 (적이 휘두르는 중엔 방패, 끝나면 스틱을 그놈 쪽으로 + R2).
        pull_to 가 있으면 먼저 그 평평한 자리로 물러나 기다린다. 다가가다 2 s 진전이 없으면(낙차·다른 층) 밀지 않고 기다리고,
        10 s 를 기다려도 안 오면 다시 다가간다. 내 HP 40 % 아래면 포기. 30 s 안에 못 끝내면 포기."""
        if ptr is None:
            print(f"   #{ti}: 포인터 없음", flush=True)
            return False
        t0 = time.time()
        swings, locked, hits = 0, False, []
        hp_start = None
        why = None
        att_start, waits = 0.0, 0
        rolled_for, rolls = None, []
        getting_up_hit = False
        mode, wait_since, prog_pos, prog_t = "approach", 0.0, None, time.time()
        # 관찰(study): 4.5 m 안에 오면 락온하고 방패만 든 채, 적 공격 애니 시작 → 막은 순간(내 스태미나 감소)을 잰다.
        # 애니마다 맞는 시점을 알아야 구르기를 그 직전에 넣을 수 있다 (3500 돌진은 0.35 s 뒤 구르기로 4/4, 3000·3005 연타는 0/4).
        style = "counter" if study else self.melee_style
        ev, study_t0, lock_tried, prev_sp, prev_hp, prev_eanim = [], None, False, None, None, None
        lock_at = [6.0, 3.5, 2.0]
        lock_lost_since = None
        self._etrk = {"anim": None, "t": 0.0}
        acted_for, idle_near_since, counters = None, None, []
        last_hp, dmg_log, close_since, last_seen = None, [], None, None
        orig_ptr, switched_at = ptr, 0.0
        estus_left, last_sip_t = self.tm.goods_count(ITEM_ESTUS) or 0, 0.0
        if self.BRUTE and not getattr(self, "_guard_off", False):
            # 사용자: "방어도 하지 마 — 공격력으로 찍어누르고 에스트 마시면서". 이 싸움 동안 가드(LB)는 누르지 않는다
            self._guard_real, self._guard_off = self.pad.guard, True
            self.pad.guard = lambda on: self._guard_real(False)
        last_dmg_t, last_ehp = time.time(), None
        self._stick_zero_t = None
        self.phase = f"#{ti} 근접"
        if not self.use_lock:
            lock_at.clear()
            if self.tm.lock_target() not in (None, -1):
                self._r3(0.15)                    # 락온 안 쓴다 — 걸려 있으면 푼다
        if pull_to is not None:
            # 그놈 쪽으로 몸을 돌리고(방패 든 채) → 백스텝으로 물러난다. 백스텝이 안 되는 방향이면 방패 든 채 걸어서
            self.pad.guard(True)
            locked = self.lock_verified(ptr) if self.use_lock else False
            if locked:
                lock_at.clear()
            if not locked:
                self.turn_to(ptr)
            n_bs = self.backstep_pull(ptr, pull_to, nm)
            sp_ = self.tm.snapshot(within=30.0)
            left_m = math.dist((sp_.player.x, sp_.player.z), (pull_to[0], pull_to[2])) if sp_ else 0.0
            if left_m > 1.5:
                nav.goto(self.tm, self.pad, pull_to, tolerance=1.0, timeout=3.0, log=lambda *a: None, terrain=nm,
                         on_tick=lambda sn, _d=None: self.note(sn), mode_fn=lambda _s: "guard")
            print(f"      알아챘다 — 락온 {'됨' if locked else ('실패' if self.use_lock else '안 씀')}, 백스텝 {n_bs}번으로 평평한 자리 쪽으로 (남은 {left_m:.1f} m)", flush=True)
            mode, wait_since = "wait", time.time()
        if wait_first:                            # 나이프로 부른 놈 — 평지에서 기다린다 (걸어 나가면 좁은 띠에서 싸우게 된다)
            mode, wait_since = "wait", time.time()
        while time.time() - t0 < 30.0:
            s = self.tm.snapshot(within=30.0)
            if not s:
                time.sleep(0.05)
                continue
            self.note(s)
            p = s.player
            hp_start = hp_start or p.hp
            if last_hp is not None and p.hp < last_hp:
                # 누가 때렸나 — 4 m 안 적과 그 애니 (둘째 시도 4번: 반격 한 번 없이 509 잃음, 원인을 못 봤다)
                idx = {v: k_ for k_, v in self.ptr_of.items()}
                who = [(f"#{idx.get(x.ptr, '?')}", round(x.dist, 1), x.anim) for x in s.hostile(4.0) if x.hp > 0]
                ca = next((x for x in s.chars if x.ptr == ptr), None)
                rel = round(math.degrees(patrol.rel_angle(p, ca))) if (ca is not None and p.heading is not None) else None
                shot = None
                if last_hp - p.hp >= 40:                  # 막았는데 크게 들어오나 — 화면으로 본다
                    im = self._shot()
                    if im is not None:
                        shot = f"hit_{time.strftime('%H%M%S')}_{last_hp - p.hp}.jpg"
                        im.save(vp.IMG_DIR / shot, quality=80)
                self._ev("hit", dmg=last_hp - p.hp, my_anim=p.anim, who=who, rel=rel, lb=self.pad.guard_held(), sp=p.sp, shot=shot)
                dmg_log.append({"t": round(time.time() - t0, 2), "dmg": last_hp - p.hp, "my_anim": p.anim, "who": who,
                                "pos": [round(p.x, 1), round(p.y, 1), round(p.z, 1)], "rel": rel, "guard_btn": self.pad.guard_held(),
                                "sp": p.sp, "lock": self.tm.lock_target(), "shot": shot})
                print(f"      맞음 {last_hp - p.hp} (내 애니 {p.anim}) ← {who} | 몸-그놈 {rel}°, LB {self.pad.guard_held()}, SP {p.sp} {shot or ''}", flush=True)
            last_hp = p.hp
            if p.hp <= 0:
                why = "사망"
                break
            # 에스트가 남아 있으면 20 % 까지 버틴다 (싸우는 중에도 마신다 — 사용자: "에스트 잘 마시면서 플레이")
            if p.hp < p.max_hp * (0.2 if estus_left else 0.4):
                why = f"내 HP {p.hp}"
                break
            c = next((x for x in s.chars if x.ptr == ptr), None)
            if (c is None or c.hp <= 0) and ptr != orig_ptr:
                # 옆에서 끼어든 놈을 잡았다 — 원래 목표로 돌아간다
                co = next((x for x in s.chars if x.ptr == orig_ptr and x.hp > 0), None)
                if co is not None:
                    print(f"      끼어든 놈 처치 — 원래 목표로 ({co.dist:.1f} m)", flush=True)
                    self._ev("retarget_back", to=orig_ptr)
                    ptr, c = orig_ptr, co
                    self._etrk = {"anim": None, "t": 0.0}
                    acted_for, idle_near_since = None, None
            if c is not None and c.hp > 0:
                # 다른 놈이 3 m 안에서 휘두르기 시작했는데(3000~3599) 지금 목표는 안 휘두르면, 또는 1 m 넘게 더 가까우면 그놈부터
                # (사람 순서 첫 시도: 5번에게 붙었을 때 4번이 옆에서 3006 — 5번만 보다 230 맞고 둘과 함께 턱에서 떨어짐)
                cand = [x for x in s.hostile(3.0) if x.ptr != ptr and x.hp > 0 and abs(x.y - p.y) < 1.5]
                if cand:
                    o = min(cand, key=lambda x: x.dist)
                    o_sw = 3000 <= (o.anim or 0) < 3600
                    c_sw = 3000 <= (c.anim or 0) < 3600
                    # 바꾼 뒤 1.2 s 는 그대로 (5번↔4번 을 틱마다 오갔다), 지금 목표가 휘두르는 중이면 '더 가깝다' 만으로는 안 바꾼다
                    if time.time() - switched_at > 1.2 and ((o_sw and not c_sw) or (o.dist + 1.0 < c.dist and not c_sw)):
                        switched_at = time.time()
                        idx_ = {v: k_ for k_, v in self.ptr_of.items()}
                        print(f"      목표 바꿈: #{idx_.get(o.ptr, '?')} ({o.dist:.1f} m, 애니 {o.anim}) — 지금 목표 {c.dist:.1f} m 애니 {c.anim}", flush=True)
                        self._ev("retarget", to=o.ptr, anim=o.anim, d=round(o.dist, 1))
                        ptr, c = o.ptr, o
                        self._etrk = {"anim": None, "t": 0.0}
                        acted_for, idle_near_since = None, None
            if c is None:
                # 30 m 밖으로 갔거나 죽어서 목록에서 빠졌다 — 넓게 다시 본다 (전엔 둘 다 '처치' 로 셌다)
                sw = self.tm.snapshot(within=250.0)
                cw = next((x for x in sw.chars if x.ptr == ptr), None) if sw else None
                why = "처치" if cw is None or cw.hp <= 0 else f"멀어짐 {cw.dist:.0f} m (HP {cw.hp})"
                print(f"      목록에서 빠짐 — 마지막으로 본 애니·높이차 {last_seen}, 넓게 다시 보니 {None if cw is None else (cw.hp, round(cw.y - p.y, 1))}", flush=True)
                break
            if c.hp <= 0:
                why = "처치"
                break
            last_seen = (c.anim, round(c.y - p.y, 1), c.hp)
            if last_ehp is None or c.hp < last_ehp:
                last_dmg_t = time.time()              # 그놈에게 피해를 넣은 마지막 시각 (교착 판단)
            last_ehp = c.hp
            if p.hp < p.max_hp * 0.5 and estus_left and time.time() - last_sip_t > 3.0:
                last_sip_t = time.time()
                r_ = self.sip_estus(s, nm)
                estus_left = self.tm.goods_count(ITEM_ESTUS) or 0
                if r_ is not None:
                    print(f"      싸우는 중 에스트: {r_}", flush=True)
                    self._ev("estus_mid", **r_)
                    continue
            self._track(c)                        # 애니가 **바뀐** 순간 — 우리 공격을 지켜보는 동안에도 잰다 (늦게 보면 이미 닿을 때)
            if 3000 <= (c.anim or 0) < 3600:
                att_start = self._etrk["t"]
            enemy_swinging = 3000 <= (c.anim or 0) < 3600 and time.time() - att_start < 1.3
            if time.time() - getattr(self, "_mdbg", 0) > 2.0:
                self._mdbg = time.time()
                print(f"      근접 +{time.time() - t0:4.1f}s: 거리 {c.dist:.1f} m (높이차 {c.y - p.y:+.1f}), 나 ({p.x:.1f},{p.y:.1f},{p.z:.1f}), "
                      f"적 ({c.x:.1f},{c.y:.1f},{c.z:.1f}) 애니 {c.anim}", flush=True)
            same_level = abs(c.y - p.y) < 0.8
            if study:
                now = time.time()
                if c.anim != prev_eanim:
                    ev.append(("e", now, c.anim, round(c.dist, 2)))
                    prev_eanim = c.anim
                if prev_sp is not None and p.sp < prev_sp - 2:
                    ev.append(("sp", now, prev_sp - p.sp, p.anim))
                if prev_hp is not None and p.hp < prev_hp:
                    ev.append(("hp", now, prev_hp - p.hp, p.anim))
                prev_sp, prev_hp = p.sp, p.hp
                if c.dist <= 4.5 and same_level:
                    if study_t0 is None:
                        study_t0 = now
                    if not lock_tried:
                        lock_tried = True
                        self.pad.guard(True)
                        locked = self.lock_verified(ptr) if self.use_lock else False
                        print(f"      관찰 시작 — 락온 {'됨' if locked else '실패'}", flush=True)
                        continue
                    n_att = sum(1 for x in ev if x[0] == "e" and 3000 <= (x[2] or 0) < 3600 and x[1] >= study_t0)
                    stop = ("공격 8번" if n_att >= 8 else "25 s" if now - study_t0 > 25.0 else
                            f"스태미나 {p.sp}" if p.sp < p.max_sp * 0.3 else f"HP {p.hp}" if p.hp < p.max_hp * 0.6 else None)
                    if stop is None:
                        self.pad.move(0.0, 0.0)
                        self.pad.guard(True)
                        time.sleep(0.005)
                        continue
                    study = False
                    tab = self.study_table([x for x in ev if x[1] >= study_t0 - 1.5])
                    print(f"      관찰 끝 ({stop}) — 공격 {len(tab)}번:", flush=True)
                    for r in tab:
                        got = "안 닿음" if r["hit_at"] is None else f"{'막음' if r['kind'] == 'sp' else '맞음'} {r['amount']} @ {r['hit_at']} s"
                        print(f"        {r['anim']} (거리 {r['dist']} m, {r['dur']} s 뒤 {r['next']}) → {got}", flush=True)
                    self.pad.guard(False)
            if style == "counter" and locked and self.lock_state(ptr) != "target":
                # 락온은 게임이 스스로 풀기도 한다(시야가 가리면). 풀린 줄 모르고 스틱 없이 치고 막다가: 방패가 딴 데를 봐서 62~66 씩
                # 그대로 맞고, 리포스트 0/2, 강공은 캐릭터가 보던 쪽(낭떠러지)으로 나가 추락사. PlayerIns+0xEF0 으로 매 틱 확인
                print(f"      락온 풀림/바뀜 ({self.lock_state(ptr)}) — 스틱으로 겨눈다", flush=True)
                locked = False
                if self.use_lock:
                    lock_at = [min(c.dist + 0.1, 6.0), 2.0]
            if style == "counter" and not (9900 <= (c.anim or 0) < 10000):
                if not locked and lock_at and c.dist <= lock_at[0]:
                    # 6 m 에서 못 잡으면(5번이 먼저 잡힘 → 2번 3005 에 210 두 번) 3.5·2 m 에서 다시 — 가까울수록 그놈이 잡힌다
                    lock_at.pop(0)
                    self.pad.guard(True)       # 카메라 돌리는 ~1 s 동안 방패가 내려가 있어 락온 직후 110~426 을 맞았다
                    locked = self.lock_verified(ptr, align=c.dist > 3.0)      # 락온하면 방패·공격이 늘 그놈을 향한다
                    print(f"      락온 {'됨' if locked else '실패 — 스틱으로 겨눔'} ({c.dist:.1f} m)", flush=True)
                    continue
                if same_level and c.dist <= 3.5:
                    a = c.anim if c.anim is not None else -1
                    age = time.time() - self._etrk["t"]
                    if self.HEAVY_FIRST and c.dist <= 2.8 and not (9900 <= a < 10000):
                        # 사용자: "강공 위주로 — 상대 공격을 무시하고 공격". 특대검 강공은 휘두르는 중 안 끊기고(강인도),
                        # 세로 내려찍기로 인간형을 경직·넘어뜨린다. 몸이 그놈을 향하면(25°) 공격 중이든 아니든 강공
                        off_ = abs(math.degrees(patrol.rel_angle(p, c))) if p.heading is not None else 180.0
                        if p.sp < 40:
                            if not self.BRUTE:
                                self.pad.guard(True)      # 강공 한 번 36 — 스태미나가 모자라면 방패 들고 한숨 돌린다
                            self.aim(s, c)
                            time.sleep(0.02)
                            continue
                        if off_ > 25:
                            if not self.BRUTE:
                                self.pad.guard(True)
                            self.aim(s, c)
                            time.sleep(0.01)
                            continue
                        # 강공은 2.9 m, 약공은 1.6 m 앞으로 나간다 — 계단 꼭대기에서 강공이 6번 너머로 나가 떨어져 죽었다 (바닥은 1.8 m 만 봤다).
                        # 앞 3.0 m(±20°)에 바닥이 있으면 강공, 1.8 m 면 약공(가로 베기), 둘 다 없으면 잠깐 기다린다
                        kind = None
                        # 붙어 있으면(1.7 m 안) 강공은 2.9 m 전진해서 그놈을 지나쳐 헛친다 (0.9~1.0 m 강공 0 피해, 몸-그놈 79~127°) → 가로 베기 약공
                        opts = (("heavy", 3.0, (-0.35, 0.0, 0.35)), ("light", 1.8, (0.0,))) if c.dist >= 1.7 else (("light", 1.8, (0.0,)),)
                        for kk, reach, cone in opts:
                            if all(nav.ground_ahead(nm, p, math.sin(math.atan2(c.x - p.x, c.z - p.z) + da), math.cos(math.atan2(c.x - p.x, c.z - p.z) + da), reach=reach)
                                   for da in cone):
                                kind = kk
                                break
                        if kind is None and self.bombs_left() and acted_for != ("nog", round(time.time() / 3)):
                            # 좁은 계단에서 붙은 6번 — 휘두를 바닥이 없다(30 s 기다리다 시간 초과). 폭탄은 내게 피해가 없으니 붙은 채 던진다
                            acted_for = ("nog", round(time.time() / 3))
                            r = self.close_bomb(ptr)
                            r = {"vs": a, "age": round(age, 2), "act": "bomb", "d": round(c.dist, 2), **r}
                            counters.append(r)
                            self._ev("act", **r)
                            print(f"      {c.dist:.1f} m 앞에 바닥 없음 → 붙어서 폭탄: {r}", flush=True)
                            if r.get("enemy_dead"):
                                if ptr != orig_ptr:
                                    continue
                                why = "처치"
                                break
                            continue
                        if kind is None:
                            if time.time() - getattr(self, "_noground_t", 0) > 2.0:
                                self._noground_t = time.time()
                                print(f"      {c.dist:.1f} m — 앞에 바닥이 없어 안 휘두름", flush=True)
                            self.aim(s, c)
                            time.sleep(0.15)
                            continue
                        r = self.strike(kind, c, s, ptr, locked=locked, nm=None)   # 바닥은 위에서 봤다
                        r = {"vs": a, "age": round(age, 2), "act": "heavy_first" if kind == "heavy" else "light_first", "d": round(c.dist, 2), **r}
                        counters.append(r)
                        self._ev("act", **r)
                        print(f"      {a} {c.dist:.1f} m → {'강공' if kind == 'heavy' else '약공'}: 적 피해 {r.get('enemy_dmg')}, 내 피해 {r.get('hit_after')}, 적 애니 {r.get('e_anims')}", flush=True)
                        if r.get("enemy_dead"):
                            if ptr != orig_ptr:
                                continue
                            why = "처치"
                            break
                        continue
                    table = self.REACT_ZWEI if self.ZWEI else {**self.REACT, **self.REACT_NPC.get(c.npc_param, {})}
                    act = table.get(a) if 3000 <= a < 3600 else "light" if 2000 <= a < 3000 else None
                    stale = time.time() - last_dmg_t > 10.0
                    if a == 3500 and act == "roll" and c.dist < self.REACH["light"] and c.y - p.y > 0.4:
                        # 그놈이 0.6~0.7 m 위(비탈·계단)면 리포스트가 안 나간다 (0/3) — 6번이 계단 위에서 30 s 버텨 3/3 시간 초과.
                        # 사용자: "폭탄은 나한테 피해 안 주니 붙어도 써도 된다" → 휘청일 때 폭탄
                        act = "bomb" if self.bombs_left() else "guard"
                    elif stale and not (3000 <= a < 3600) and c.dist < 4.0 and self.bombs_left() and acted_for != ("stale", round(last_dmg_t)):
                        act = "bomb"                      # 10 s 넘게 한 대도 못 넣음 — 공격 중이 아닐 때 폭탄
                    if act == "bomb":
                        acted_for = ("stale", round(last_dmg_t)) if a != 3500 else (a, self._etrk["t"])
                        r = self.close_bomb(ptr)
                        r = {"vs": a, "age": round(age, 2), "act": "bomb", "d": round(c.dist, 2), **r}
                        counters.append(r)
                        self._ev("act", **r)
                        print(f"      {a} {c.dist:.1f} m (높이차 {c.y - p.y:+.1f}) → 붙어서 폭탄: {r}", flush=True)
                        if r.get("enemy_dead"):
                            if ptr != orig_ptr:
                                continue
                            why = "처치"
                            break
                        last_dmg_t = time.time()
                        continue
                    if act in ("roll", "roll_heavy"):     # 3500 휘청 — 붙어 있으면 구를 것 없이 바로 친다
                        act = "roll" if c.dist >= self.REACH["heavy" if act == "roll_heavy" else "light"] else ("light" if act == "roll" else "heavy")
                    ready = locked or self.aim(s, c)       # 락온 없으면 몸을 그놈에 맞추고 스틱을 놓은 뒤라야 R1·B
                    # 약공은 가로 베기라 붙은 놈에게도 닿는다 (사용자) — 1.2 m 조건을 뺐다 (0.9~1.0 m 에서 뒤 바닥 없음 5연속, 막다가 347)
                    if (act == "bs" and self.ZWEI and acted_for != (a, self._etrk["t"]) and ready and age < 0.3
                            and p.heading is not None and not nav.ground_ahead(nm, p, math.sin(p.heading), math.cos(p.heading), reach=2.2)):
                        # 뒤에 바닥이 없어 백스텝을 못 한다 (5번 턱·위쪽에서 7번 연속) — 무기 가드는 약하니(사용자) 막지 말고
                        # 공격 시작에 맞춰 곧장 휘두른다: 특대검은 휘두르는 중 안 끊기고, 할로우는 한 방이다 (맞바꿈)
                        acted_for = (a, self._etrk["t"])
                        r = self.strike("light", c, s, ptr, locked=locked, nm=nm)
                        r = {"vs": a, "age": round(age, 2), "act": "trade", "d": round(c.dist, 2), **r}
                        counters.append(r)
                        self._ev("act", **r)
                        print(f"      {a} +{age:.2f}s {c.dist:.1f} m → 맞바꿔 휘두름(뒤 바닥 없음): 적 피해 {r.get('enemy_dmg')}, 내 피해 {r.get('hit_after')}", flush=True)
                        if r.get("enemy_dead"):
                            if ptr != orig_ptr:
                                continue
                            why = "처치"
                            break
                        self.follow_heavy(r, ptr, nm, locked)
                        continue
                    if act == "bs" and acted_for != (a, self._etrk["t"]):
                        bs_at = (self.BS_AT_ZWEI if self.ZWEI else self.BS_AT).get(a, 0.5)
                        if (age < bs_at or not ready) and age < bs_at + 0.25:
                            self.pad.guard(True)          # 백스텝 전까지는 방패 (다른 놈 대비)
                            time.sleep(0.005)
                            continue
                        if age < bs_at + 0.25 and c.dist <= 3.0 and ready:
                            acted_for = (a, self._etrk["t"])
                            r = self.backstep_attack(c, s, ptr, nm)
                            r = {"vs": a, "age": round(age, 2), "act": "bs", "d": round(c.dist, 2), **r}
                            counters.append(r)
                            self._ev("act", **r)
                            print(f"      {a} +{age:.2f}s {c.dist:.1f} m → 백스텝 공격: {r}", flush=True)
                            if r.get("enemy_dead"):
                                if ptr != orig_ptr:
                                    continue            # 끼어든 놈을 잡았다 — 다음 틱에 원래 목표로 돌아간다 (전엔 여기서 '처치' 로 끝내 3번이 살아서 따라왔다)
                                why = "처치"
                                break
                            continue
                        act = "guard"
                    if act is not None and act != "guard" and acted_for != (a, self._etrk["t"]):
                        if act == "roll" and age < self.ROLL_DELAY:
                            self.pad.move(0.0, 0.0)
                            time.sleep(0.005)
                            continue
                        win = 1.0 if a == 3500 else 0.3       # 3500 휘청은 1.38 s — 몸을 맞출 시간이 있다
                        if act == "light" and not ready and age < win:
                            self.pad.guard(True)
                            time.sleep(0.005)
                            continue
                        if (act == "roll" and age < self.ROLL_DELAY + 0.3) or (act != "roll" and age < win and c.dist <= self.REACH[act]):
                            acted_for = (a, self._etrk["t"])
                            r = (self.roll_attack(c, p, s.cam_yaw, nm, ptr) if act == "roll" else
                                 self.strike(act, c, s, ptr, watch=1.8 if a == 3500 else None, locked=locked, nm=nm))   # 리포스트 피해는 ~1 s 뒤
                            r = {"vs": a, "age": round(age, 2), "act": act, "d": round(c.dist, 2), **r}
                            counters.append(r)
                            self._ev("act", **r)
                            print(f"      {a} +{age:.2f}s {c.dist:.1f} m → {act}: 적 피해 {r.get('enemy_dmg')}, "
                                  f"내 피해 {r.get('hit_in_roll', 0) + r.get('hit_after', 0)}, 적 애니 {r.get('e_anims')}, 내 애니 {r.get('my_anims')}", flush=True)
                            if r.get("enemy_dead"):
                                if ptr != orig_ptr:
                                    continue            # 끼어든 놈을 잡았다 — 다음 틱에 원래 목표로 돌아간다 (전엔 여기서 '처치' 로 끝내 3번이 살아서 따라왔다)
                                why = "처치"
                                break
                            idle_near_since = None
                            continue
                    # 공격 중이 아니고 붙어 있는데 1 s 넘게 안 휘두르면 약공으로 찌른다 (약공 ~0.4 s 가 3000 의 0.63 s 보다 빠르다)
                    zone = self.ZWEI and c.dist <= 2.6   # 사용자: "길이가 길어서 유리" — 사거리 안이면 바로 (가로 베기라 붙어도 닿는다)
                    if not (3000 <= a < 3600) and c.dist <= self.REACH["light"]:
                        idle_near_since = idle_near_since or time.time()
                        if (zone or time.time() - idle_near_since > 1.0) and ready:
                            idle_near_since = None
                            r = self.strike("light", c, s, ptr, locked=locked)
                            r = {"vs": a, "age": round(age, 2), "act": "poke", "d": round(c.dist, 2), **r}
                            counters.append(r)
                            self._ev("act", **r)
                            print(f"      가만있음 {c.dist:.1f} m → 약공: 적 피해 {r['enemy_dmg']}, 내 피해 {r['hit_after']}, 적 애니 {r['e_anims']}", flush=True)
                            if r["enemy_dead"]:
                                if ptr != orig_ptr:
                                    continue
                                why = "처치"
                                break
                            self.follow_heavy(r, ptr, nm, locked)
                            continue
                    else:
                        idle_near_since = None
                    self.pad.guard(True)
                    if locked:
                        self.pad.move(0.0, 0.0)
                    time.sleep(0.005)
                    continue
                # 6 m 안이면 방패 들고 오게 둔다 — 다가가는 동안 방패를 내리고 있다가 3002 에 168 씩 두 번 맞았다. 4 s 안 오면 방패 든 채 다가간다
                if c.dist <= 6.0:
                    close_since = close_since or time.time()
                    if time.time() - close_since < 4.0:
                        self.pad.guard(True)
                        self.pad.move(0.0, 0.0)
                        time.sleep(0.01)
                        continue
                else:
                    close_since = None
            # 구르기 반격 (사용자: "적과 정렬할 수 있다면 구르고 약공 — 간격이 짧아야, 구르기 무적 프레임을 이용"):
            # 공격 애니가 시작되면 ROLL_DELAY 뒤 그놈 쪽으로 구르고 ROLL_TO_R1 뒤 약공. 기다리는 동안엔 다가가지 않는다 (타이밍이 흐트러진다)
            if (style == "roll" and enemy_swinging and same_level and 2.0 <= c.dist <= 3.5 and att_start != rolled_for):
                if time.time() - att_start < self.ROLL_DELAY:
                    self.pad.move(0.0, 0.0)
                    time.sleep(0.01)
                    continue
                rolled_for = att_start
                rr = self.roll_attack(c, p, s.cam_yaw, nm, ptr)
                rolls.append(rr)
                print(f"      구르기 반격: {rr}", flush=True)
                if rr.get("enemy_dead"):
                    why = "처치"
                    break
                continue
            if c.dist > 2.0 or not same_level:
                if mode == "wait":
                    self.pad.guard(True)        # 방패 들고 제자리 — 오게 둔다 (오는 쪽으로 몸을 돌려 둔다)
                    if locked:
                        self.pad.move(0.0, 0.0)
                    else:
                        self.aim(s, c)
                    if time.time() - wait_since > (20.0 if wait_first else 10.0):
                        mode, prog_pos, prog_t = "approach", None, time.time()
                        self.pad.guard(False)
                    time.sleep(0.03)
                    continue
                if prog_pos is None or math.dist((p.x, p.z), prog_pos) > 0.5:
                    prog_pos, prog_t = (p.x, p.z), time.time()
                elif time.time() - prog_t > 2.0:
                    print(f"      2 s 진전 없음 (거리 {c.dist:.1f} m, 높이차 {c.y - p.y:+.1f}) — 밀지 않고 기다린다", flush=True)
                    mode, wait_since = "wait", time.time()
                    continue
                path = nm.find_path((p.x, p.y, p.z), (c.x, c.y, c.z))
                q = path[1] if path and len(path) > 1 else (c.x, c.y, c.z)
                d_now = c.dist
                # 4 m 안에선 goto 를 짧게 끊는다 — 1.2 s 동안 막혀 있으면 적 공격 시작을 늦게 봐서 구르기 타이밍이 틀어진다
                nav.goto(self.tm, self.pad, q, tolerance=1.8 if len(path or []) <= 2 else 1.0, timeout=0.4 if c.dist < 4.0 else 1.2, log=lambda *a: None,
                         on_tick=lambda sn, _d=None: self.note(sn), terrain=nm,
                         mode_fn=lambda _s: "guard" if style == "counter" and d_now < 10.0 else "creep" if d_now < 4.0 else "walk")
                continue
            # 넘어진 놈(99xx: 9910 쓰러짐 → 9930 누움 → 9920 일어남)은 맞지 않는다 — 강공 62 로 넘어뜨린 뒤 휘두른 강공이 전부 0 이었다.
            # 누워 있는 동안은 방패 들고 기다리다, 일어나기 시작하면(9920) 곧바로 약공 — 강공보다 빨라 일어나며 휘두르는 놈(1.2 s 뒤 3003)보다 먼저 닿는다.
            if 9900 <= (c.anim or 0) < 10000:
                if c.anim == 9920 and not getting_up_hit:
                    getting_up_hit = True
                    st_ = control.world_to_stick(c.x - p.x, c.z - p.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X) if s.cam_yaw is not None else (0.0, 0.0)
                    self.pad.guard(False)
                    if not locked:                        # 스틱 + R1 을 같이 넣으면 발차기 — 돌려 놓고 놓은 뒤 R1
                        self.pad.move(*[0.4 * v for v in st_])
                        time.sleep(0.08)
                        self.pad.move(0.0, 0.0)
                    self._press(control.B.XUSB_GAMEPAD_RIGHT_SHOULDER)
                    ehp = c.hp
                    t1 = time.time()
                    while time.time() - t1 < 0.9:
                        s2 = self.tm.snapshot(within=10.0)
                        c2 = next((x for x in s2.chars if x.ptr == ptr), None) if s2 else None
                        ehp = 0 if c2 is None else min(ehp, c2.hp)
                        time.sleep(0.03)
                    print(f"      일어날 때 약공 → 피해 {c.hp - ehp}", flush=True)
                    hits.append(c.hp - ehp)
                    if ehp <= 0:
                        why = "처치"
                        break
                    continue
                self.pad.move(0.0, 0.0)
                self.pad.guard(True)
                time.sleep(0.02)
                continue
            getting_up_hit = False
            # 막고 → 한 대 (사용자 원칙): 적이 휘두르는 중(공격 애니 시작 뒤 1.3 s)이면 방패만 든다. 그 사이에 R2 를 누르면
            # 우리 공격이 나가기 전에 맞아서 끊긴다 — 첫 근접에서 강공 4번 중 3번이 0 피해, 그동안 421 맞았다 (적 애니 3003·3006 중에 휘두름).
            if enemy_swinging:
                self.pad.move(0.0, 0.0)
                self.pad.guard(True)
                waits += 1
                time.sleep(0.03)
                continue
            self.pad.guard(False)
            self.pad.neutral()
            # 락온 없이 겨눈다 — 붙은 적에게 정렬·락온 확인은 너무 느렸다 (1번이 2.4 s 만에 0.9 m 로 붙어 치는 동안 락온 확인 중 90 맞음).
            # 공격을 누르는 순간의 스틱 방향으로 몸이 틀어진다.
            if s.cam_yaw is None:
                time.sleep(0.05)
                continue
            st_ = control.world_to_stick(c.x - p.x, c.z - p.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
            hp_before = c.hp
            self.pad.heavy(stick=st_)
            swings += 1
            t1 = time.time()
            hp_min = hp_before
            e_anims = []
            while time.time() - t1 < 1.3:
                s2 = self.tm.snapshot(within=10.0)
                c2 = next((x for x in s2.chars if x.ptr == ptr), None) if s2 else None
                hp_min = 0 if c2 is None else min(hp_min, c2.hp)
                if c2 is not None and (not e_anims or e_anims[-1][1] != c2.anim):
                    e_anims.append((round(time.time() - t1, 2), c2.anim))   # 0 피해일 때 방패로 막았나 (막기 반응 애니)
                self.pad.release_due()
                time.sleep(0.03)
            hits.append(hp_before - hp_min)
            print(f"      강공 → 피해 {hp_before - hp_min}, 그놈 애니 {e_anims}", flush=True)
            if hp_min <= 0:
                why = "처치"
                break
            if swings >= 4:
                why = "4번 쳐도 안 죽음"
                break
        if why == "처치":
            sk = self.tm.snapshot(within=1.0)
            if sk:
                # 다음 적을 끌어올 평평한 자리 — 1번 스폰 옆 고정 자리. 잡은 자리를 쓰면 경사로 위일 때가 있어
                # 2번(아래층)으로 가는 길이 끊겼다 (2 s 진전 없음 반복, 그동안 3번에게 701 맞음)
                self.last_kill_pos = ARENA if math.dist(ARENA, (sk.player.x, sk.player.y, sk.player.z)) < 12.0 else (sk.player.x, sk.player.y, sk.player.z)
        self.pad.guard(False)
        self.pad.neutral()
        s = self.tm.snapshot(within=5.0)
        res = {"plan": "melee", "style": style, "rolls": rolls, "counters": counters, "hits_taken": dmg_log, "study": self.study_table(ev) if ev else None,
               "result": why or "시간 초과", "swings": swings, "dmg_per_swing": hits, "guard_ticks": waits,
               "my_hp_lost": (hp_start - s.player.hp) if (s and hp_start) else None}
        self._record(k, ti, e, None, None, {}, res)
        self._ev("melee_end", target=ti, result=res["result"], my_hp_lost=res["my_hp_lost"])
        if getattr(self, "_guard_off", False):
            self.pad.guard, self._guard_off = self._guard_real, False
        print(f"   #{ti} {e['npc']} 근접: {res['result']} — 강공 {swings}번, 피해 {hits}, 내가 잃은 HP {res['my_hp_lost']}", flush=True)
        if why != "처치":
            if locked:
                self.pad.lock_on()
                time.sleep(0.1)
                self.pad.release_due()
            return False
        return True

    def bait(self, k: int, ti: int, e: dict, ptr) -> bool:
        """알아채고 오게 둔다 — 폭탄을 고르고, 스폰을 떠난 그놈에 **먼저** 정렬·락온(확인)해 둔 채 방패를 들고 기다리다,
        초속 1 m 넘게 달려들며 4.5~8 m 에 들면(공격 단계) 던진다. 누르고 ~1.2 s 뒤에 손을 떠나므로 초속 3 m 로 오는 놈은
        7 m 쯤에서 눌러야 3~4 m 에서 맞는다 (처음엔 3~6 m 에서 눌러 1.2~1.4 m 에서 던졌고 빗나갔다).
        3 m 안까지 붙으면 폭탄은 포기 (기록만). 15 s 안에 안 오면 포기."""
        if ptr is None:
            print(f"   #{ti}: 포인터 없음", flush=True)
            return False
        if not self.select_bomb():
            print("   파이어밤 칸을 못 고름", flush=True)
            return False
        locked = self.lock_state(ptr) == "target" or self.lock_verified(ptr) or self.lock_verified(ptr, align=False)
        if not locked:
            print(f"   #{ti}: 락온이 그놈에 안 걸림 (두 번)", flush=True)
            self._record(k, ti, e, None, None, {}, {"result": "락온 실패", "plan": "bait"})
            return False
        self.pad.guard(True)
        t0 = time.time()
        why, c = None, None
        while time.time() - t0 < 15.0:
            s = self.tm.snapshot(within=30.0)
            if not s:
                time.sleep(0.05)
                continue
            self.note(s)
            if s.player.hp <= 0:
                why = "사망"
                break
            c = next((x for x in s.chars if x.ptr == ptr), None)
            if c is None or c.hp <= 0:
                why = "사라짐"
                break
            v = self.approach_speed(ptr)
            # 4.5~8 m 에서 초속 1 m 넘게 달려들 때만 던졌더니 그 전에 붙어 버려(3/3) 근접으로 넘어갔다 — 8 m 안에서 다가오거나 6 m 안이면 던진다
            if (c.dist <= 8.0 and v >= 0.5) or 3.0 <= c.dist <= 6.0:
                why = f"{c.dist:.1f} m, {v:.1f} m/s"
                break
            if c.dist < 3.0:
                why = "붙음"
                break
            time.sleep(0.03)
        self.pad.guard(False)
        if why == "붙음":
            self.pad.lock_on()          # 락온 풀기 (살아 있다)
            time.sleep(0.1)
            self.pad.release_due()
        if why is None or c is None or why in ("사망", "사라짐", "붙음"):
            print(f"   #{ti} {e['npc']} 미끼: {why or '15 s 안에 안 옴'} — 화톳불로", flush=True)
            self._record(k, ti, e, c, None, {}, {"result": f"미끼 실패: {why or '안 옴'}", "plan": "bait"})
            return False
        c2 = next((x for x in (self.tm.snapshot(within=30.0) or s).chars if x.ptr == ptr), c)
        res = self.throw_at(ptr, locked_already=True, release_if_alive=False)
        res.update({"plan": "bait", "trigger": why})
        self._record(k, ti, e, c2, None, {}, res)
        print(f"   #{ti} {e['npc']} 미끼: {why}, {c2.dist:.1f} m 에서 던짐 → 폭탄 {res['result']} (HP {res['hp0']}→{res['hp_after']})"
              f"{' 락온 ' + str(res.get('locked_npc')) if res['result'] == '락온 대상 다름' else ''}", flush=True)
        # 달려오는 놈은 손을 떠날 때 자리를 겨누니 떨어질 무렵엔 앞으로 와 있다 — 가장자리만 맞으면(75→57) 한 방 더.
        # 락온·폭탄 칸은 그대로라 곧바로 던질 수 있다. 3 m 안이면 폭탄은 접는다 (막고 한 대 몫).
        n_more = 0
        while res["result"] == "명중" and n_more < 2:
            s3 = self.tm.snapshot(within=30.0)
            c3 = next((x for x in s3.chars if x.ptr == ptr), None) if s3 else None
            if c3 is None or c3.hp <= 0:
                res["result"] = "처치"
                break
            if c3.dist < 3.0:
                break
            n_more += 1
            res = self.throw_at(ptr, locked_already=True, release_if_alive=False)
            res.update({"plan": "bait", "trigger": f"한 방 더 #{n_more}"})
            self._record(k, ti, e, c3, None, {}, res)
            print(f"      한 방 더 ({c3.dist:.1f} m) → {res['result']} (HP {res['hp0']}→{res['hp_after']})", flush=True)
        if res["result"] != "처치" and res.get("hp_after"):
            self.pad.lock_on()          # 살아 있으면 락온 풀기
            time.sleep(0.1)
            self.pad.release_due()
        if res["result"] == "처치":
            sk = self.tm.snapshot(within=1.0)
            if sk:
                self.last_kill_pos = (sk.player.x, sk.player.y, sk.player.z)
        if res["result"] != "처치":
            print("   못 잡음 — 화톳불로", flush=True)
            return False
        return True

    def observe(self, k: int, after: int) -> None:
        """처치 직후 제자리에서 방패를 들고 observe_s 초 동안 나머지 지도 적의 움직임을 본다 (1 s 마다 한 줄)."""
        self.pad.guard(True)
        t0 = time.time()
        rows = []
        while time.time() - t0 < self.observe_s:
            s = self.tm.snapshot(within=60.0)
            if s:
                self.note(s)
                line = []
                for i, ptr in self.ptr_of.items():
                    c = next((x for x in s.chars if x.ptr == ptr), None)
                    if c is None or c.hp <= 0:
                        continue
                    moved = math.dist((c.x, c.y, c.z), tuple(MAP[i - 1]["pos"]))
                    fp = vp.facing_player(c, s.player)
                    line.append(f"#{i} {c.dist:4.1f}m 스폰서 {moved:4.1f}m 보는각 {'-' if fp is None else round(fp)}° 애니 {c.anim}")
                    rows.append({"t": round(time.time() - t0, 1), "id": i, "dist": round(c.dist, 1), "moved": round(moved, 1),
                                 "facing": None if fp is None else round(fp), "anim": c.anim, "pos": [round(c.x, 1), round(c.y, 1), round(c.z, 1)]})
                print(f"     +{time.time() - t0:4.1f}s  " + " | ".join(line), flush=True)
            time.sleep(1.0)
        self.pad.guard(False)
        with (ROOT / "data" / "hunt-observe.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "trial": k, "after": after, "rows": rows}, ensure_ascii=False) + "\n")

    def _record(self, k, ti, e, c, trk, jd, res, img=None) -> None:
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "trial": k, "target": ti, "npc": e["npc"], "spawn": e["pos"],
                                "dist": None if c is None else round(c.dist, 1), **(trk or {}), "judge": jd, **res, "img": img},
                               ensure_ascii=False) + "\n")


def main() -> None:
    args = sys.argv[1:]
    dist = 10.0
    targets = [1]
    if "--throw" in args:
        dist = float(args[args.index("--throw") + 1])
        del args[args.index("--throw"):args.index("--throw") + 2]
    if "--targets" in args:
        targets = [int(x) for x in args[args.index("--targets") + 1].split(",")]
        del args[args.index("--targets"):args.index("--targets") + 2]
    obs = 0.0
    if "--observe" in args:
        obs = float(args[args.index("--observe") + 1])
        del args[args.index("--observe"):args.index("--observe") + 2]
    plans = {}
    if "--plan" in args:                  # 예: --plan 1:sneak,3:bait  (적마다 공략)
        for kv in args[args.index("--plan") + 1].split(","):
            i, v = kv.split(":")
            plans[int(i)] = v
        del args[args.index("--plan"):args.index("--plan") + 2]
    style = "block"
    if "--style" in args:                 # block (막고 → 강공) | roll (공격 시작 → 구르기 → 약공)
        style = args[args.index("--style") + 1]
        del args[args.index("--style"):args.index("--style") + 2]
    n = int(args[0]) if args else 1
    h = Hunter()
    h.observe_s = obs
    h.plans = plans
    h.melee_style = style
    h.use_lock = "--lock" in sys.argv          # 기본은 락온 없이 (사용자: DS1 고수는 락온을 안 쓴다)
    h.then_run = "--run" in sys.argv           # 목표를 다 잡으면 BOUND_A 까지 달려서 지나간다
    h.to_merchant = "--merchant" in sys.argv   # 목표를 다 잡으면 상인까지 (다리 → 경계 → 성벽 마을)
    h.HEAVY_FIRST = "--heavy" in sys.argv or "--brute" in sys.argv   # 강공 위주 (사용자: 상대 공격을 무시하고 강공)
    h.BRUTE = "--brute" in sys.argv
    if "--zwei" in sys.argv:                    # 츠바이헨더 양손 — 백스텝 공격 위주, 사거리가 길다
        h.ZWEI = True
        h.REACH = {"light": 2.6, "heavy": 2.6}
    if "--lure" in args:                        # 예: --lure 4,5,6 — 목표를 잡은 뒤 위 무리를 하나씩 평지로 꾀어 잡는다
        h.lure_group = [int(x) for x in args[args.index("--lure") + 1].split(",")]
        del args[args.index("--lure"):args.index("--lure") + 2]
    if "--climb" in args:                        # 몹 없는 상태로 사용자가 서 있던 자리(5번 위)까지 — 휴식 없이
        # n 번: 오르기 → 화톳불 자리로 걸어 내려오기 → 다시 (사용자: "10번은 성공해야 믿겠어")
        goal = tuple(json.loads((ROOT / "data" / "climb-goal.json").read_text(encoding="utf-8"))["top"])
        home = tuple(mr.BONFIRE["stand"])
        ok_up = ok_down = 0
        god = "--god" in args
        # 무적: 안 죽음·피해 없음만 켰더니 피해는 0 인데 적 셋이 계단에서 계속 때려 휘청(2007)이고 몸으로 막아 내려오지 못했다 →
        # 적이 못 보게(PlayerHide)·아무도 공격 안 하게(AllNoAttack 0xB)도 켠다
        GOD = (h.tm.DBG_PLAYER_NO_DEAD, h.tm.DBG_ALL_NO_DAMAGE, h.tm.DBG_PLAYER_HIDE, 0xB)
        if god:
            for o in GOD:
                h.tm.set_dbg(o, True)
            print(f"무적 켬: {[h.tm.get_dbg(o) for o in GOD]}", flush=True)
            s_ = h.tm.snapshot(within=5.0)
            if s_ and s_.player.hp < s_.player.max_hp * 0.5:
                print(f"HP {s_.player.hp} — 화톳불에서 쉬고 시작 (몹은 되살아나도 못 본다)", flush=True)
                h.run.rest()
        h.trace = Trace(h, f"climb_{time.strftime('%Y%m%d_%H%M%S')}").start()
        try:
            for k in range(1, n + 1):
                s0 = h.tm.snapshot(within=5.0)
                hp0 = s0.player.hp if s0 else None
                print(f"── 오르기 {k}/{n}", flush=True)
                r_up = h.climb_to(goal, mode="walk")
                s1 = h.tm.snapshot(within=5.0)
                up_ok = r_up == "arrived" and s1 is not None and math.dist((s1.player.x, s1.player.y, s1.player.z), goal) < 0.8
                ok_up += up_ok
                if not up_ok or s1 is None or s1.player.hp <= 0:
                    print(f"   {k}: 오르기 실패 ({r_up}) — 멈춤", flush=True)
                    break
                r_dn = h.climb_to(home, mode="walk")
                s2 = h.tm.snapshot(within=5.0)
                dn_ok = r_dn == "arrived" and s2 is not None and s2.player.hp > 0
                ok_down += dn_ok
                print(f"   {k}: 오르기 성공, 내려오기 {r_dn} — HP {hp0} → {s2.player.hp if s2 else '?'}  (누적 오르기 {ok_up}/{k})", flush=True)
                if not dn_ok:
                    print(f"   {k}: 내려오기 실패 — 멈춤", flush=True)
                    break
        finally:
            h.trace.stop()
            h.pad.neutral()
            if god:
                # 화톳불 옆이 아닐 때 끄면 둘러싼 적에게 죽는다 (첫 시험: 계단 꼭대기에서 끄자마자 사망) — 그땐 켜 둔다
                se = h.tm.snapshot(within=5.0)
                if se and math.dist((se.player.x, se.player.y, se.player.z), home) < 10.0:
                    for o in GOD:
                        h.tm.set_dbg(o, False)
                    print(f"무적 끔: {[h.tm.get_dbg(o) for o in GOD]}", flush=True)
                else:
                    print("화톳불 옆이 아니라 무적은 켜 둠 — 필요하면 직접 끄거나 말해 달라", flush=True)
        print(f"결과: 오르기 {ok_up}/{n}, 내려오기 {ok_down}/{n}", flush=True)
        return
    for k in range(1, n + 1):
        h.hunt(k, targets, dist)
    h.pad.neutral()
    h.go_home()
    h.run.rest()


if __name__ == "__main__":
    main()
