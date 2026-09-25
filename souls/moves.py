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
import quitout

ATTACK = range(3000, 3500)       # 적 공격 애니 (DS1 인간형 공통)
GUARD_BROKEN = 9600              # 가드가 깨져 휘청 (방패병 발차기 뒤) — 틈
STAGGER = range(3500, 3600)      # 휘청 — 내 방패에 막혀 튕김 등. **공격이 아니라 틈** (2026-09-24: 이걸 공격으로 봐서 12 s 동안 막기만 했다)
DOWNED = range(9900, 10000)      # 넘어짐·누움·일어남 (9920 = 일어나는 중)
GETTING_UP = 9920
ESTUS_IDS = range(200, 216)      # 에스트 아이템 번호는 강화 단계별 (새 캐릭터 201)
ITEM_DARKSIGN = 117
ITEM_KNIFE = 290                 # 투척 나이프 (퀵 슬롯에 있어야 고를 수 있다)
SECOND_R1_AT = 0.45              # 약공 2연타: 첫 R1 뒤 이때 한 번 더 (입력 버퍼)
BS_TO_R1 = 0.45                  # 백스텝 공격: B 뒤 이때 R1 (옛 hunt.backstep_attack 실측값) — 앞으로 1.7~2.8 m 파고든다
KICK_TO_R1 = 0.6                 # 발차기 뒤 늦어도 이때 R1 (닿으면 그 순간) — 방패병이 9600 된 게 0.45~0.61 s
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


def rel_angle(p, c) -> float:
    """c 가 내 정면에서 몇 rad 옆에 있나 (−π..π, + 가 오른쪽). 실측: 월드 yaw = heading + π. (옛 patrol.rel_angle — 1층으로 옮김)"""
    fwd = p.heading + math.pi
    return (math.atan2(c.x - p.x, c.z - p.z) - fwd + math.pi) % (2 * math.pi) - math.pi


class Moves:
    def __init__(self, tm, pad: control.Pad):
        self.tm, self.pad = tm, pad
        self._estus: int | None = None
        self.guard_ok = True     # False = 방패를 절대 안 든다 (백스텝 스타일. 사용자: "백스텝 할 땐 가드하지 마 — 피하고 공격 심플하게")

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
        if abs(math.degrees(rel_angle(p, c))) > deg:
            self.pad.move(*self.stick_to(s, c.x, c.z, 0.55))     # 0.35 로는 방패 든 채 거의 안 돌았다
            return False
        self.pad.move(0.0, 0.0)
        return True

    def guard(self, on: bool) -> None:
        self.pad.guard(on and self.guard_ok)

    # ── 공격 ─────────────────────────────────────────────────
    def _watch(self, hit: Hit, ptr, hp0: int, ehp0: int, secs: float, on_tick=None, early_exit=None) -> None:
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
                # 공격 애니가 한 번 나간 뒤 -1(서 있음)로 돌아왔고 더 누를 것이 없으면 끝 — 남은 시간을 기다리며 아무것도 못 보는 일을 줄인다
                if (early_exit is not None and early_exit(time.time() - t1, hit) and len(hit.my_anims) >= 2
                        and hit.my_anims[-1][1] in (-1, None)):
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
                self.guard(True)
        self._watch(hit, ptr, hp0, ehp0, 1.5 if want_second else 0.9, tick,
                    early_exit=lambda t, h: state["second"] and t > (SECOND_R1_AT + 0.3 if h.presses == 2 else 0.3))
        self.pad.move(0.0, 0.0)
        return hit

    def heavy(self, s, c) -> Hit:
        """강공(R2) — 스틱을 놓고 누른다 (앞+R2 는 점프 공격). 무기가 강공을 쓸 때만 위층이 부른다."""
        hit = Hit("heavy", presses=1)
        ptr, hp0, ehp0 = c.ptr, s.player.hp, c.hp
        self.pad.guard(False)
        self.pad.heavy()
        self._watch(hit, ptr, hp0, ehp0, 1.3,
                    lambda t, h: self.guard(True) if t > 0.9 else None)
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

    def kick_combo(self, s, c, n: int = 2) -> Hit:
        """발차기 → 가드가 깨지는 순간 곧장 약공 n 연타 (한 동작, 판단 루프를 안 거친다).
        사용자: "발차기 이후 공격이 너무 시간 간격이 커서 방패병이 다시 가드해서 실패함" — 발차기가 닿아 9600(가드 깨짐)·9920 이
        되는 건 0.45~0.6 s 인데, 발차기 결과를 1.2 s 지켜본 뒤 몸 맞추고 판단하느라 약공이 1.5 s 넘게 늦었다.
        그놈 애니가 -1 에서 바뀌면(맞음) 또는 늦어도 KICK_TO_R1 에 R1 — 발차기 모션이 끝나기 전 누른 R1 은 버퍼에 들어간다."""
        hit = Hit("kick+light", presses=1)
        ptr, hp0, ehp0 = c.ptr, s.player.hp, c.hp
        self.pad.guard(False)
        st = self.stick_to(s, c.x, c.z) if s.cam_yaw is not None else (0.0, 1.0)
        self.pad.kick(*st)
        t0 = time.time()
        while time.time() - t0 < 0.12:
            self.pad.release_due()
            time.sleep(0.01)
        self.pad.move(0.0, 0.0)
        state = {"r1": 0, "broke_t": None}

        def tick(t, h):
            if state["broke_t"] is None and h.e_anims and h.e_anims[-1][1] not in (-1, None) and t > 0.2:
                state["broke_t"] = t                       # 발차기가 닿았다 (9600 가드 깨짐 / 9920 등)
            due = state["broke_t"] is not None or t >= KICK_TO_R1
            if due and state["r1"] < n and t >= (state["broke_t"] or KICK_TO_R1) + state["r1"] * SECOND_R1_AT:
                if not h.dead:
                    self.pad.tap(B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06, stick_ok=True)   # 스틱은 이미 놓았다
                    state["r1"] += 1
                    h.presses = 1 + state["r1"]
            if state["r1"] >= n and t >= (state["broke_t"] or KICK_TO_R1) + n * SECOND_R1_AT + 0.3:
                self.guard(True)
        self._watch(hit, ptr, hp0, ehp0, 2.4, tick,
                    early_exit=lambda t, h: state["r1"] >= n and t > (state["broke_t"] or KICK_TO_R1) + n * SECOND_R1_AT + 0.3)
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

    def backstep_attack(self, s, c, nm=None) -> Hit:
        """백스텝 + R1 을 **한 동작**으로 (사용자 2026-09-24: "백스텝 후 공격이 두 동작이면 안 된다, 하나의 동작이어야").
        스틱 중립 → B → BS_TO_R1 뒤 R1. 뒤 2.6 m·앞 3.0 m 에 바닥이 있어야 한다 (앞으로 파고든다). 몸이 그놈을 40° 안에 봐야 한다."""
        hit = Hit("bsattack", presses=0)
        p = s.player
        if p.heading is None:
            hit.skipped = "heading 없음"
            return hit
        if nm is not None:
            back = (math.sin(p.heading), math.cos(p.heading))
            if not nav.ground_ahead(nm, p, back[0], back[1], reach=2.6):
                hit.skipped = "뒤에 바닥 없음"
                return hit
            if not nav.ground_ahead(nm, p, -back[0], -back[1], reach=2.2):
                hit.skipped = "앞에 바닥 없음"
                return hit
        if abs(math.degrees(rel_angle(p, c))) > 40:
            hit.skipped = "몸이 딴 데"
            return hit
        return self.combo("backstep_r1", s, c, nm=None)   # 바닥은 위에서 검사했다

    # ── 조합 = 시퀀스 (사용자 2026-09-24: "공격 조합을 하나의 시퀀스로 — 구르기 약공, 점프 강공, 백스텝 약공 이런 식으로") ──
    # 한 줄 = (시각 s, 동작). 동작: "stick_fwd" 그놈 쪽 스틱 | "stick_off" 스틱 놓기 | "B" | "R1" | "R2"(트리거)
    # 시각: B 앞 단계는 시작 기준, **B 뒤 단계는 B 를 누른 순간 기준** (스틱 놓기 대기 0.16 s 가 끼어도 간격이 유지되게)
    # 한 번의 _watch 로 결과를 본다. 새 조합은 여기 한 줄로 추가하고 위 층은 이름만 부른다.
    COMBOS = {
        "backstep_r1": ((0.0, "stick_off"), (0.0, "B"), (BS_TO_R1, "R1")),                 # 백스텝 약공 — 앞으로 1.7~2.8 m 파고든다
        "roll_r1":     ((0.0, "stick_fwd"), (0.3, "B"), (0.55, "R1")),                      # 구르기 약공 — B 뒤 0.55 s R1 (B 이후 시각은 B 기준)
        "jump_r2":     ((0.0, "stick_fwd"), (0.1, "R2"), (0.25, "stick_off")),             # 점프 강공 — 앞+R2 (조작표)
    }
    COMBO_WATCH = {"backstep_r1": BS_TO_R1 + 1.1, "roll_r1": 2.0, "jump_r2": 1.8}

    def combo(self, name: str, s, c, nm=None, need_back: float = 0.0, need_front: float = 3.0) -> Hit:
        """조합 하나를 한 동작으로. 바닥 검사: 뒤 need_back m·앞 need_front m (구르기·점프는 앞으로 나간다)."""
        hit = Hit(name, presses=0)
        p = s.player
        if p.heading is None or s.cam_yaw is None:
            hit.skipped = "heading 없음"
            return hit
        if nm is not None:
            back = (math.sin(p.heading), math.cos(p.heading))
            if need_back and not nav.ground_ahead(nm, p, back[0], back[1], reach=need_back):
                hit.skipped = "뒤에 바닥 없음"
                return hit
            if need_front and not nav.ground_ahead(nm, p, c.x - p.x, c.z - p.z, reach=need_front):
                hit.skipped = "앞에 바닥 없음"
                return hit
        if abs(math.degrees(rel_angle(p, c))) > 40:
            hit.skipped = "몸이 딴 데"
            return hit
        steps = list(self.COMBOS[name])
        hp0, ehp0 = p.hp, c.hp
        self.pad.guard(False)
        fwd = self.stick_to(s, c.x, c.z)
        state = {"i": 0}

        def do(act):
            if act == "stick_fwd":
                self.pad.move(*fwd)
            elif act == "stick_off":
                self.pad.move(0.0, 0.0)
                self.pad.release_stick()
            elif act == "B":
                self.pad.tap(B.XUSB_GAMEPAD_B, 0.06, stick_ok=True)
                hit.presses += 1
            elif act == "R1":
                self.pad.tap(B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06, stick_ok=True)
                hit.presses += 1
            elif act == "R2":
                self.pad._r2(0.12)
                hit.presses += 1

        # 시각은 **B 를 누른 순간 기준** — 절대 시각으로 두면 스틱 놓기 대기(0.16 s)만큼 R1 이 당겨져 0.45 가 0.29 가 됐다 (moves_test 가 잡음)
        state["anchor"] = None

        t_start = time.time()

        def tick(t, h):
            while state["i"] < len(steps):
                st_t, act = steps[state["i"]]
                now = time.time()                          # _watch 의 t 는 틱 시작 시각이라 do() 안의 대기(0.16 s)를 못 본다 — 실시간으로
                base = state["anchor"] if (state["anchor"] is not None and st_t > 0) else t_start
                if now - base < st_t:
                    break
                do(act)
                if act == "B" and state["anchor"] is None:
                    state["anchor"] = time.time()          # B 이후 단계의 시각은 B 를 누른 순간 기준
                state["i"] += 1
        self._watch(hit, c.ptr, hp0, ehp0, self.COMBO_WATCH[name] + 0.3, tick,
                    early_exit=lambda t, h: state["i"] >= len(steps) and time.time() > (state["anchor"] or t_start) + steps[-1][0] + 0.4)
        self.pad.move(0.0, 0.0)
        return hit

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

    def darksign(self, bonfire_stand) -> bool:
        """다크사인 — 소울·인간성을 전부 잃고 마지막으로 쉰 화톳불로. 칸(117)·확인창 글자·YES 칸을 **확인한 뒤에만** A
        (기본값이 YES). A 를 누른 뒤엔 결과를 못 읽어도 **다시 쓰지 않는다** (merchantrun 실측: 도착해 놓고 '실패' 로 보고 또 썼다).
        쓸지는 위층이 정한다 (잃을 게 거의 없을 때만 — 사용자 2026-09-24 "다크사인 쓰자")."""
        import env
        for _ in range(3):
            s0 = self.snap(5.0)
            pre = (s0.player.x, s0.player.y, s0.player.z) if s0 else None
            self.pad.guard(False)
            self.pad.neutral()
            quitout.close_menu(self.tm, self.pad)
            if not self.select_item(ITEM_DARKSIGN):
                continue
            quitout._press(self.pad, B.XUSB_GAMEPAD_X, 0.0)
            ok = quitout._wait(lambda: quitout._is_screen("darksign_q") is True and quitout._is_screen("darksign_yes") is True, 1.5)
            if not ok:
                quitout._press(self.pad, B.XUSB_GAMEPAD_B, 0.4)      # 창이 아니면 닫고 다시 (맞아서 끊겼을 수도)
                continue
            quitout._press(self.pad, B.XUSB_GAMEPAD_A, 0.0)
            t0 = last = time.time()
            while time.time() - t0 < 40.0:                         # 로딩 뒤 포인터가 바뀐다 — 4 s 마다 새로 붙는다
                try:
                    s = self.tm.snapshot(within=1.0)
                except Exception:
                    s = None
                if s and s.player.hp and s.player.hp > 0:
                    here = (s.player.x, s.player.y, s.player.z)
                    if (pre is not None and math.dist(here, pre) > 20.0) or math.dist(here, tuple(bonfire_stand)) < 15.0:
                        time.sleep(1.5)
                        e = self.estus_id()
                        if e is not None:
                            self.select_item(e)                      # 칸을 에스트로 되돌려 둔다
                        return True
                if time.time() - last > 4.0:
                    last = time.time()
                    try:
                        self.tm = env.make_telemetry({})
                    except Exception:
                        pass
                time.sleep(0.3)
            return False
        return False

    # ── 던지기 ───────────────────────────────────────────────
    def aim(self, ptr, deg: float = 1.5, timeout: float = 3.0) -> float | None:
        """락온 없는 정밀 조준 — 스틱을 0.6 으로 짧게 쳐 몸을 그놈 쪽으로 (hunt.aim_fine 실측: 한 번에 0.15~0.9° 안).
        → 마지막 어긋난 각도(°), 그놈이 없으면 None."""
        t, off = time.time(), None
        while time.time() - t < timeout:
            s = self.snap(40.0)
            c = self.find(s, ptr)
            if c is None or s.player.heading is None or s.cam_yaw is None:
                return None
            off = math.degrees(rel_angle(s.player, c))
            if abs(off) <= deg:
                break
            self.pad.move(*[0.6 * v for v in self.stick_to(s, c.x, c.z)])
            time.sleep(0.08 if abs(off) > 10 else 0.05)
            self.pad.move(0.0, 0.0)
            time.sleep(0.25)
        self.pad.move(0.0, 0.0)
        time.sleep(0.16)
        return off

    def lock_state(self, ptr) -> str:
        """'target' | 'other' | 'none' — 락온이 그놈에 걸렸나 (PlayerIns+0xEF0 핸들)."""
        h = self.tm.lock_target()
        if h is None or h == -1:
            return "none"
        return "target" if ptr and h == self.tm.handle(ptr) else "other"

    def unlock(self) -> None:
        if self.tm.lock_target() not in (None, -1):
            self.pad.lock_on()                    # R3 는 토글
            time.sleep(0.15)

    def _r3(self, wait: float = 0.3) -> None:
        self.pad.lock_on()
        t = time.time()
        while time.time() - t < wait:
            self.pad.release_due()
            time.sleep(0.01)

    def reset_camera(self) -> None:
        """R3 = 락온 대상이 없으면 카메라가 등 뒤 기본 높이로. 락온 없이 던지면 나이프가 **카메라 방향·기울기**대로 날아간다
        (옛 실측: 카메라 숙인 채 조준 0.0° 로 던진 3 개가 발밑). 걸리면 한 번 더 눌러 푼다."""
        self._r3(0.35)
        if self.tm.lock_target() not in (None, -1):
            self._r3(0.2)

    def throw_knife(self, ptr, watch: float = 1.8, require_lock: bool = False) -> dict:
        """투척 나이프 한 개 — 던질 때만 락온 (사용자: 평소엔 락온 안 씀. 옛 실측: 락온 없이는 14 m 에서 1.2° 안이어야 하고
        위에 선 놈은 3/3 반응 없음, 락온이면 20 m 위 5번도 맞음). 락온이 안 걸리면 정밀 조준으로 던진다.
        → {"ok": 던졌나, "locked", "hit": 피해, "woke": 움직였나, "dist", "knives": 남은 개수, "why"}"""
        if not self.tm.goods_count(ITEM_KNIFE):
            return {"ok": False, "why": "나이프 없음"}
        if not self.select_item(ITEM_KNIFE):
            return {"ok": False, "why": "나이프 칸을 못 고름"}
        s = self.snap(40.0)
        c = self.find(s, ptr)
        if c is None:
            return {"ok": False, "why": "그놈 없음"}
        self.pad.guard(False)
        self.aim(ptr, deg=8.0, timeout=1.5)       # 락온이 그놈을 잡도록 몸을 그쪽으로
        locked = False
        for _ in range(2):
            self.pad.lock_on()
            t = time.time()
            while time.time() - t < 0.4:
                self.pad.release_due()
                time.sleep(0.02)
            st = self.lock_state(ptr)
            if st == "target":
                locked = True
                break
            if st == "other":
                self.pad.lock_on()                # 옆 놈에 걸림 → 풀고 다시
                time.sleep(0.15)
        off = None
        if not locked and require_lock:
            return {"ok": False, "locked": False, "why": "락온 안 걸림 — 안 던짐 (락온 없는 나이프는 오늘 0/5)", "dist": round(c.dist, 1)}
        if not locked:
            # 사용자 2026-09-24: "나이프 던질 때 조준 문제 — 적과 방향 정렬". 몸을 맞춘 뒤 카메라를 몸 뒤로 되돌려야
            # 카메라 방향 = 몸 방향이 된다 (그 전엔 걷던 카메라가 옆을 보고 있었다)
            self.reset_camera()
            off = self.aim(ptr, deg=1.5, timeout=3.0)
            self.reset_camera()
        s = self.snap(40.0)
        c = self.find(s, ptr)
        if c is None:
            self.unlock()
            return {"ok": False, "why": "그놈 없음", "locked": locked}
        hp0, pos0, n0 = c.hp, (c.x, c.y, c.z), self.tm.goods_count(ITEM_KNIFE) or 0
        self.pad.release_due()                    # 예약된 버튼 뗌이 남아 있으면 X 가 씹힌다 ("안 던져짐 (개수 그대로)" 2/3)
        time.sleep(0.05)
        self.pad.use_item()
        t, hit, woke = time.time(), 0, False
        while time.time() - t < watch:
            self.pad.release_due()
            s2 = self.snap(40.0)
            c2 = self.find(s2, ptr)
            if c2 is not None:
                hit = max(hit, hp0 - c2.hp)
                if math.dist((c2.x, c2.y, c2.z), pos0) > 0.8 or c2.anim not in (-1, None):
                    woke = True
                if hit > 0 and woke:
                    break
            time.sleep(0.03)
        self.unlock()
        n1 = self.tm.goods_count(ITEM_KNIFE) or 0
        return {"ok": n1 < n0, "locked": locked, "aim_off": None if off is None else round(off, 1), "hit": hit, "woke": woke,
                "dist": round(c.dist, 1), "knives": n1, "why": None if n1 < n0 else "안 던져짐 (개수 그대로)"}

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
