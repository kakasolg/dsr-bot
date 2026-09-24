"""1층 — 기본 동작. **버튼과 타이밍만** 안다: 무엇을, 언제 누르나.
누구를 칠지·언제 마실지·어디로 갈지는 위층이 정한다. 이 층은 무기도 적도 모른다 (무기 값은 인자로 받는다).

이 층에만 있는 규칙 (다른 곳에 다시 쓰지 않는다):
  · 공격 버튼(R1·R2)은 스틱을 놓고 0.16 s 뒤 — control.Pad 가 강제한다. 앞+R1 = 발차기, 앞+R2 = 점프 공격 (조작표)
  · 달리기(B 홀드)는 경로 하나 내내 유지 — 점마다 B 를 떼면 '짧은 B' = 구르기·백스텝·(달리는 중) 점프 (nav.follow)
  · 점프 안 함 (사용자)
  · 에스트는 아이템 칸을 고른 **뒤에** 다시 안전한지 보고 마신다. 개수가 줄었는지로 성공을 판정한다
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import control
import farm
import nav
import patrol
import quitout

ATTACK = range(3000, 3600)       # 적 공격 애니 (DS1 인간형 공통)
DOWNED = range(9900, 10000)      # 넘어짐·누움·일어남 (9920 = 일어나는 중)
GETTING_UP = 9920
ESTUS_IDS = range(200, 216)      # 에스트 아이템 번호는 강화 단계별 (새 캐릭터 201)
SECOND_R1_AT = 0.45              # 약공 2연타: 첫 R1 뒤 이때 한 번 더 (입력 버퍼)
B = control.B


@dataclass
class Hit:
    """공격 한 번(연타 포함)의 결과."""
    kind: str                     # light | heavy | kick
    presses: int = 0
    dmg: int = 0                  # 그놈 HP 감소
    dead: bool = False            # 그놈 HP 0 (목록에서 사라진 것도 죽음으로 친다)
    taken: int = 0                # 그동안 내가 잃은 HP
    e_anims: list = field(default_factory=list)
    my_anims: list = field(default_factory=list)
    skipped: str | None = None

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def horiz(p, c) -> float:
    return math.hypot(c.x - p.x, c.z - p.z)


class Moves:
    def __init__(self, tm, pad: control.Pad):
        self.tm, self.pad = tm, pad
        self._estus: int | None = None

    # ── 보기 ────────────────────────────────────────────────
    def snap(self, within: float = 40.0):
        return self.tm.snapshot(within=within)

    @staticmethod
    def find(s, ptr):
        return next((x for x in s.chars if x.ptr == ptr), None) if s else None

    def stick_to(self, s, x: float, z: float, scale: float = 1.0) -> tuple[float, float]:
        st = control.world_to_stick(x - s.player.x, z - s.player.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
        return st[0] * scale, st[1] * scale

    # ── 몸 돌리기 ─────────────────────────────────────────────
    def face(self, s, c, deg: float = 20.0) -> bool:
        """락온 없이 겨누기 (사용자: DS1 고수는 락온 안 씀). 몸이 그놈에서 deg 넘게 벗어나면 스틱을 살짝 그쪽으로 → False.
        안이면 스틱을 놓고 True (공격 버튼의 스틱 대기는 Pad 가 한다)."""
        p = s.player
        if p.heading is None or s.cam_yaw is None:
            return False
        if abs(math.degrees(patrol.rel_angle(p, c))) > deg:
            self.pad.move(*self.stick_to(s, c.x, c.z, 0.55))     # 0.35 로는 방패 든 채 거의 안 돌았다
            return False
        self.pad.move(0.0, 0.0)
        return True

    def guard(self, on: bool) -> None:
        self.pad.guard(on)

    # ── 공격 ─────────────────────────────────────────────────
    def _watch(self, hit: Hit, ptr, hp0: int, ehp0: int, secs: float, on_tick=None) -> None:
        t1 = time.time()
        my_min, e_min = hp0, ehp0
        while time.time() - t1 < secs:
            self.pad.release_due()
            if on_tick is not None:
                on_tick(time.time() - t1, hit)
            s2 = self.snap(10.0)
            if s2:
                my_min = min(my_min, s2.player.hp)
                c2 = self.find(s2, ptr)
                e_min = 0 if c2 is None else min(e_min, c2.hp)
                if c2 is not None and (not hit.e_anims or hit.e_anims[-1][1] != c2.anim):
                    hit.e_anims.append((round(time.time() - t1, 2), c2.anim))
                if not hit.my_anims or hit.my_anims[-1][1] != s2.player.anim:
                    hit.my_anims.append((round(time.time() - t1, 2), s2.player.anim))
                if e_min <= 0:
                    break
            time.sleep(0.01)
        hit.dmg, hit.dead, hit.taken = ehp0 - e_min, e_min <= 0, hp0 - my_min

    def light(self, s, c, n: int = 1, sp_second: int = 40) -> Hit:
        """약공(R1) n 번 (1 또는 2). 두 번째는 첫 R1 뒤 SECOND_R1_AT 에, 스태미나가 sp_second 넘을 때만.
        방패는 마지막 공격 애니가 시작된 뒤에 올린다 (두 번째 R1 이 가드에 덮이지 않게)."""
        hit = Hit("light")
        ptr, hp0, ehp0 = c.ptr, s.player.hp, c.hp
        self.pad.guard(False)
        self.pad.tap(B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06)      # 스틱 대기는 Pad
        hit.presses = 1
        want_second = n >= 2 and (s.player.sp or 0) >= sp_second
        state = {"second": not want_second, "guard": False}

        def tick(t, h):
            if not state["second"] and t >= SECOND_R1_AT:
                state["second"] = True
                if not h.dead:
                    self.pad.tap(B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06)
                    h.presses = 2
            # 마지막 R1 을 누르고 0.6 s(한 번이면 0.35 s) 뒤에 방패 — 더 일찍 LB 를 누르면 버퍼된 R1 이 가드로 덮일 수 있다
            if not state["guard"] and state["second"] and t >= (SECOND_R1_AT + 0.6 if h.presses == 2 else 0.35):
                state["guard"] = True
                self.pad.guard(True)
        self._watch(hit, ptr, hp0, ehp0, 1.5 if want_second else 0.9, tick)
        self.pad.move(0.0, 0.0)
        return hit

    def heavy(self, s, c) -> Hit:
        """강공(R2) — 스틱을 놓고 누른다 (앞+R2 는 점프 공격). 무기가 강공을 쓸 때만 위층이 부른다."""
        hit = Hit("heavy", presses=1)
        ptr, hp0, ehp0 = c.ptr, s.player.hp, c.hp
        self.pad.guard(False)
        self.pad.heavy()
        self._watch(hit, ptr, hp0, ehp0, 1.3,
                    lambda t, h: self.pad.guard(True) if t > 0.9 else None)
        return hit

    def kick(self, s, c) -> Hit:
        """발차기 = 그놈 쪽 스틱 + R1 을 같은 입력에 (control.kick). 방패 가드를 깬다 (위키: 가드 올린 적은 휘청)."""
        hit = Hit("kick", presses=1)
        ptr, hp0, ehp0 = c.ptr, s.player.hp, c.hp
        self.pad.guard(False)
        st = self.stick_to(s, c.x, c.z) if s.cam_yaw is not None else (0.0, 1.0)
        self.pad.kick(*st)
        t0 = time.time()
        while time.time() - t0 < 0.12:
            self.pad.release_due()
            time.sleep(0.01)
        self.pad.move(0.0, 0.0)
        self._watch(hit, ptr, hp0, ehp0, 1.2)
        return hit

    def backstep(self) -> None:
        """스틱 중립 + B 톡. DS1 은 B 를 뗄 때 판정 — 스틱을 놓고 0.1 s 뒤에 누른다 (안 그러면 구르기)."""
        self.pad.release_stick()
        self.pad.guard(False)
        self.pad.tap(B.XUSB_GAMEPAD_B, 0.06)
        t0 = time.time()
        while time.time() - t0 < 0.7:
            self.pad.release_due()
            time.sleep(0.02)

    def roll_toward(self, s, x: float, z: float) -> None:
        """그쪽으로 스틱 + B 톡 = 구르기 (상자 깨기 등)."""
        self.pad.move(*self.stick_to(s, x, z))
        time.sleep(0.3)                                      # 몸을 돌릴 틈
        self.pad.dodge()
        t0 = time.time()
        while time.time() - t0 < 1.2:
            self.pad.release_due()
            time.sleep(0.02)
        self.pad.move(0.0, 0.0)
        time.sleep(0.2)

    # ── 아이템 ───────────────────────────────────────────────
    def estus_id(self) -> int | None:
        """지금 가진 에스트의 아이템 번호 (한 번 찾으면 캐시, 0 개가 되면 다시 찾는다)."""
        if self._estus is not None and self.tm.goods_count(self._estus):
            return self._estus
        self._estus = next((i for i in ESTUS_IDS if self.tm.goods_count(i)), None)
        return self._estus

    def estus_left(self) -> int:
        e = self.estus_id()
        return (self.tm.goods_count(e) or 0) if e is not None else 0

    def select_item(self, item: int, timeout: float = 3.0) -> bool:
        t0 = time.time()
        while self.tm.selected_item() != item and time.time() - t0 < timeout:
            self.pad.item_next()
            t1 = time.time()
            while time.time() - t1 < 0.35:
                self.pad.release_due()
                time.sleep(0.01)
        return self.tm.selected_item() == item

    def drink(self, safe) -> dict:
        """에스트 한 모금. safe(snapshot) 가 참일 때만 — 칸을 고르는 데 최대 3 s 가 걸리니 **고른 뒤에 다시** 본다.
        → {"ok": 개수가 줄었나, "hp": [전, 후], "left": 남은 개수, "why": 못 마신 이유}"""
        e = self.estus_id()
        if e is None:
            return {"ok": False, "why": "에스트 없음"}
        if not self.select_item(e):
            return {"ok": False, "why": "에스트 칸을 못 고름"}
        s = self.snap(15.0)
        if s is None or not safe(s):
            return {"ok": False, "why": "칸 고르는 사이 적이 옴"}
        n0, hp0 = self.tm.goods_count(e) or 0, s.player.hp
        self.pad.guard(False)
        self.pad.neutral()
        self.pad.use_item()
        t0 = time.time()
        while time.time() - t0 < 2.2:
            self.pad.release_due()
            time.sleep(0.02)
        s2 = self.snap(10.0)
        n1 = self.tm.goods_count(e) or 0
        return {"ok": n1 < n0, "hp": [hp0, s2.player.hp if s2 else None], "left": n1,
                "why": None if n1 < n0 else "끊김 (개수 그대로)"}

    # ── 이동 ─────────────────────────────────────────────────
    def walk_path(self, path: list, nm, mode="walk", stop=None, on_tick=None, tol: float = 1.0,
                  timeout_per: float = 10.0) -> str:
        """경로 따라 걷기·달리기. mode 는 'walk'|'sprint'|'guard' 또는 snapshot → 그 문자열 함수.
        stop(snapshot) 이 참이면 **그 틱에** 멈춘다 → 'stopped'. 가파른 곳은 nav.path_tolerances 가 좁게 밟는다.
        → 'arrived' | 'stopped' | 'dead' | goto 실패 값"""
        if not path:
            return "arrived"
        mode_fn = mode if callable(mode) else (lambda _s: mode)

        def fn(sn):
            if stop is not None and stop(sn):
                return "retreat"          # goto 는 'retreat' 를 받으면 바로 돌아온다
            return mode_fn(sn)
        r = nav.follow(self.tm, self.pad, [tuple(q) for q in path], terrain=nm, mode_fn=fn, on_tick=on_tick,
                       default_tol=tol, timeout_per=timeout_per)
        return "stopped" if r == "retreat" else r

    # ── 메뉴 ─────────────────────────────────────────────────
    def quit_reload(self) -> dict:
        """메뉴 → Quit Game → 이어하기. 적은 스폰 자리로 돌아가 경계가 풀린다. 죽은 적은 그대로 (사용자 확인 2026-09-24).
        쉬면(화톳불) 적이 전부 살아나니, 적을 떼어내기만 할 땐 이걸 쓴다."""
        self.pad.neutral()
        q = quitout.quit_out(self.tm, self.pad, gap=quitout.MENU_GAP, settle=0.1, ready_wait=0.05)
        if q is None:
            quitout.close_menu(self.tm, self.pad)
            return {"ok": False}
        r = quitout.reload(self.pad)
        time.sleep(1.0)
        return {"ok": r is not None, "quit_s": round(q, 2), "reload_s": None if r is None else round(r, 1)}

    def rest(self, nm, bonfire: dict) -> bool:
        """화톳불까지 걸어가 앉았다 일어난다 (farm.rest). 적이 전부 살아나고 HP·에스트가 찬다."""
        return farm.rest(self.tm, self.pad, nm, bonfire)

    def press(self, button, hold: float = 0.1, gap: float = 0.1) -> None:
        """메뉴용 한 번 누르기 (누르고 떼고 gap). 메뉴 입력은 0.1 s 간격 (사용자: 연속이면 입력 버퍼가 꼬인다)."""
        self.pad.tap(button, hold)
        time.sleep(hold + 0.03)
        self.pad.release_due()
        time.sleep(gap)
