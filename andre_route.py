"""Sunlight Altar → Andre's plaza → Andre's bonfire (MoKa M1111-64/65): the route from MoKa's recordings 20261111_220431 /
20261111_222903, then the 10-19 route (data/routes/new-route-20261019.json) reversed to the bonfire, rest, kindle if needed.
One process, steps in order (a step LIST, not yet a state machine — M1111-72, board review 8ccf86e4); stops at the first
failure or death and prints RESULT, then guards in place.   python andre_route.py [first_step_index]
Precondition: backup-20261111-181431-altar-claymore-equipped-sl17-str16-dex10-souls5012 (altar, lever not pulled).
Results (11-11): try 1 died (P-161), 2 fell at ladder top (P-162), 3 reached the plaza alive (HP 745, est 6),
4 died at the lower stairs pinned by 2 (P-164). Rest step: P-163. Gate-open and kindle checks: not game-checked yet."""
import sys, os, time, math
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT); os.chdir(ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
import control, env, navmesh, track
import screen_prompt
from botlock import BotLock
from run import Log
from souls import missions, moves as M, props, weapons
from souls import field as FM
from souls.field import Field
from souls.watch import Escape
from souls.altar import Altar

BOAR = 346000
TARGET = (30.8, 26.6, 114.6)
ANDRE_STAND = (88.46, 14.97, 106.96)   # spots.json andre-bonfire (sitting_verified)
FOG = (0.7, 27.6, 37.1)
HOLLOWS = {255040, 255041, 255042, 250050, 250053, 349002}
L = missions.SPOTS["altar-lever"]
# 게이트 상태 (MoKa M1111-70/71/77 — '닫혀 있으면 상태값 읽어서 연다'). soulstruct vanilla m10_01_00_00.evs.py + 세이브 비교 (11-12):
#  ALTAR_GATE_OPEN 11010621 — 제단 레버 1011120/게이트 1011121, 켜지면 열린 채 고정. 백업 181431 False · 시도 4 뒤 True.
#  GATE2_CLOSED 61010610 — 아래 계단 위 게이트 1011101 (7.9, 19.8, 40.4), 켜짐 = 닫힘(애니 2 + 내브메시 1013100 막음).
#   영역 1012200에 들어오면 병사 6010이 레버 1011100으로 닫음(Event 11015116/11010609). MoKa가 말한 게이트인지는 가설 → 기록만.
ALTAR_GATE_OPEN = 11010621
GATE2_CLOSED = 61010610


class Route:
    def __init__(self):
        self.log = Log("altar-andre-route")
        self.lock = BotLock()
        if not self.lock.acquire():
            raise SystemExit("lock busy")
        tm = env.make_telemetry({})
        self.tr = track.Track(str(self.log.path).replace(".jsonl", ".track.jsonl")).attach(tm)
        self.log.on_line = self.tr.say
        control.focus_game(); time.sleep(0.5)
        self.pad = control.Pad(); time.sleep(2.0)
        self.nm = navmesh.Navmesh(missions.MAP_B)
        props.attach({missions.MAP_B: self.nm}, self.log)
        self.nm.edge_kinds()
        self.mv = M.Moves(tm, self.pad); self.tr.follow(self.mv)
        self.w = weapons.of(tm.right_weapon()); self.mv.weapon = self.w
        self.esc = Escape(self.pad, [self.nm], log=self.log, events=self.log.event).start()
        self.f = Field(self.mv, self.w, self.esc, bonfires=[missions.FIRELINK["stand"], missions.BURG_BONFIRE],
                       log=self.log, events=self.log.event)
        if FOG not in FM.FOG_WALLS:
            FM.FOG_WALLS.append(FOG)
        self.alt = object.__new__(Altar)
        self.alt.f, self.alt.mv, self.alt.nm, self.alt.tm, self.alt.pad = self.f, self.mv, self.nm, tm, self.pad
        self.alt.log, self.alt.events = self.log, self.log.event
        self.tm = tm

    # ── helpers ──
    def say(self, m):
        print(m); self.log(m)

    def state(self, tag):
        s = self.mv.snap(30.0)
        if not s:
            self.say(f"[{tag}] no snapshot"); return None
        p = s.player
        near = sorted((round(c.dist, 1), c.npc_param, c.hp) for c in s.chars if c.hp > 0 and c.npc_param != 100000 and c.dist < 20)[:7]
        g1, g2 = self.tm.event_flag(ALTAR_GATE_OPEN), self.tm.event_flag(GATE2_CLOSED)
        self.say(f"[{tag}] {time.strftime('%H:%M:%S')} pos ({p.x:.2f}, {p.y:.2f}, {p.z:.2f}) HP {p.hp} estus {self.mv.estus_left()} "
                 f"gate altar_open={g1} gate2_closed={g2} near {near}")
        if g2 != getattr(self, "_g2", g2):
            self.say(f"  ⚑ 두 번째 게이트 플래그 {GATE2_CLOSED}: {self._g2} → {g2} (pos ({p.x:.1f}, {p.y:.1f}, {p.z:.1f}))")
        self._g2 = g2
        return s

    def dead(self):
        return not self.f.alive()

    def walk(self, pts, tag, mode="walk", ignore=()):
        self.f.ignore_npcs = set(ignore) | {BOAR}
        self.f.walk_heal = mode != "sprint"
        try:
            r = self.f.walk([tuple(q) for q in pts], self.nm, tag, mode=mode)
        finally:
            self.f.walk_heal = True
            self.f.ignore_npcs = set()
            self.pad.sprint(False)
        self.say(f"  {tag}: {r}")
        return r

    def clear(self, r, quiet, tag, center=None, exclude=(), max_dy=1.5):
        """Fight hostiles within r (never the boar) one at a time until none for `quiet` s."""
        t_q = time.time(); n = 0; t0 = time.time()
        while time.time() - t_q < quiet and time.time() - t0 < 120:
            if self.dead():
                return "dead"
            s = self.mv.snap(r + 3)
            # 시도 2 (230518): 사다리 위에서 뒤따라 오르던 망자(anim 72xx, 높이 −4.4)를 향해 돌아 휘두름 → 공격 전진으로 사다리 구멍에
            #  떨어짐(−68), 아래층으로 돌아가 버림. 높이 차 1.5 m 넘는 적(사다리·아래층)은 치지 않고 올라올 때까지 기다림.
            foes = [c for c in s.hostile(r) if c.hp > 0 and c.npc_param != BOAR and c.npc_param not in exclude
                    and abs(c.y - s.player.y) <= max_dy] if s else []
            if foes:
                c = min(foes, key=lambda c: c.dist)
                # 시도 1: HP 343에 망자 250050 셋이 2.5 m — fight가 0 s 만에 low_hp로 끝나기만 반복, 치지도 마시지도 않고 죽음.
                #  붙어 있으면(3 m 안) 끝까지 싸움(desperate), 떨어져 있고 HP 낮으면 먼저 마심.
                hp_low = s.player.hp < 0.5 * s.player.max_hp
                if hp_low and c.dist > 3.5:
                    self.f.heal(0.7); continue
                # 시도 4 (235422): 아래 계단 서쪽에서 250050 + 위층에서 따라 내려온 255041에 붙잡힘. fight 한 번이 14 s 동안
                #  '떼어놓기'에 머물며 HP 368 → 245 → 0, SP 98·에스트 10인데 안 마시고 안 굴러 죽음. → fight는 6 s씩만 맡기고,
                #  HP 55 % 미만에 3 m 안 적이 있으면 적들 반대쪽으로 두 번 구른 뒤 마심.
                close = [o for o in foes if o.dist < 3.0]
                if s.player.hp < 0.55 * s.player.max_hp and close and self.mv.estus_left() > 0:
                    cx = sum(o.x for o in close) / len(close); cz = sum(o.z for o in close) / len(close)
                    px, pz = s.player.x, s.player.z
                    d = math.hypot(px - cx, pz - cz) or 1.0
                    for _ in range(2):
                        s2 = self.mv.snap(8.0)
                        self.mv.roll_toward(s2, px + (px - cx) / d * 5, pz + (pz - cz) / d * 5); time.sleep(0.9)
                    self.say(f"  {tag}: HP {s.player.hp} · 붙은 적 {len(close)} → 구르고 마심")
                    self.f.heal(0.7); continue
                res = self.f.fight(c.ptr, self.nm, f"{tag} {c.npc_param}", desperate=hp_low, limit=6.0)
                self.say(f"  {tag}: {c.npc_param} {c.dist:.1f} m → {getattr(res, 'result', res)} (dealt {getattr(res, 'dealt', '?')}, taken {getattr(res, 'taken', '?')})")
                n += 1; t_q = time.time()
                if center is not None and not self.dead():
                    self.f.walk_to(center, self.nm, f"{tag} back")
            else:
                self.pad.neutral(); time.sleep(0.3)
        return f"cleared {n}"

    def heal_if(self, below=0.6):
        s = self.mv.snap(8.0)
        if s and s.player.hp < below * s.player.max_hp and not [c for c in s.hostile(6.0) if c.hp > 0]:
            self.f.heal(below)
            self.say(f"  heal → HP {self.mv.snap(5.0).player.hp}")

    def to_andre(self):
        import json
        pts = [tuple(q) for q in json.load(open("data/routes/new-route-20261019.json", encoding="utf-8"))["points"]]
        k = min(range(len(pts)), key=lambda i: math.dist(pts[i], TARGET))
        path = list(reversed(pts[:k + 1]))[1:] + [ANDRE_STAND]   # 10-19 녹화(안드레 → 광장)를 거꾸로
        return self.walk(path, "안드레 화톳불로")

    def rest(self):
        """A at Andre's bonfire until seated (first A may only light it). Success = sitting and last_bonfire 1012964. No warp."""
        r = self.f.walk_to(ANDRE_STAND, self.nm, "화톳불 자리")
        if r == "dead":
            return "dead"
        s = self.mv.snap(8.0)
        if s and [c for c in s.hostile(6.0) if c.hp > 0 and abs(c.y - s.player.y) < 1.5]:
            return "foe at bonfire"
        before = self.tm.last_bonfire()
        # 1차 (232524): 자리에 섰지만 화톳불을 등지고 있어 프롬프트 없음(px 620) → A 4번 헛누름. 기록된 앉는 방향 heading 2.34
        #  (월드 정면 = heading + π)으로 1 m 앞 점을 향해 살짝 밀고, 프롬프트(px ≥ 750)가 보일 때만 A.
        fx, fz = ANDRE_STAND[0] + math.sin(2.34 + math.pi), ANDRE_STAND[2] + math.cos(2.34 + math.pi)
        for k in range(4):
            for j in range(4):
                if screen_prompt.prompt_px() >= 750:
                    break
                s = self.mv.snap(5.0)
                self.pad.move(*self.mv.stick_to(s, fx, fz, 0.6)); time.sleep(0.2 if j else 0.35); self.pad.move(0, 0); time.sleep(0.6)
            px = screen_prompt.prompt_px()
            self.say(f"  화톳불 프롬프트 px {px}")
            if px < 750:
                continue
            self.pad.press(control.B.XUSB_GAMEPAD_A, 0.1)
            for _ in range(16):
                time.sleep(0.25)
                if self.tm.sitting() or self.tm.menu_open() is True:
                    break
            if self.tm.sitting() or self.tm.menu_open() is True:
                time.sleep(1.5)
                after = self.tm.last_bonfire()
                self.say(f"  앉음 (A {k + 1}번), 마지막 화톳불 {before} → {after}")
                if after != 1012964:
                    return f"sat but last_bonfire {after}"
                return self.kindle_if()
            time.sleep(1.5)   # 처음 A는 불 붙이기일 수 있음
        return "not seated"

    def kindle_if(self):
        """MoKa M1111-17 '중요한 화톳불이라 불 키우기' + M1111-70 (상황이 오면 확인하고 한다): 앉은 뒤 인간성 ≥ 1 이고 에스트 < 10
        (안 지핀 화톳불)이면 불 지피기. 메뉴 Leave/Level Up/Kindle/Reverse Hollowing (11-11 23:4x 화면) — 아래 2 → A → YES(왼쪽) → A.
        확인 = 인간성 1 줄고 에스트 10. 망자 되돌리기는 망자 상태를 못 읽어서 안 함(M1111-68, MoKa '망자 아니라 필요 없어')."""
        hum, est = self.tm.humanity(), self.mv.estus_left()
        if not hum or est >= 10:
            self.say(f"  불 지피기 안 함: 인간성 {hum}, 에스트 {est}")
            return "rested"
        if self.tm.menu_open() is not True:
            return f"rested, kindle skipped: menu not open (인간성 {hum}, 에스트 {est})"
        for b, w in ((control.B.XUSB_GAMEPAD_DPAD_DOWN, 0.8), (control.B.XUSB_GAMEPAD_DPAD_DOWN, 0.8), (control.B.XUSB_GAMEPAD_A, 1.2),
                     (control.B.XUSB_GAMEPAD_DPAD_LEFT, 0.8), (control.B.XUSB_GAMEPAD_A, 5.0)):
            self.pad.press(b, 0.1); time.sleep(w)
        hum2, est2 = self.tm.humanity(), self.mv.estus_left()
        self.say(f"  불 지피기: 인간성 {hum} → {hum2}, 에스트 {est} → {est2}")
        return "rested" if hum2 == hum - 1 else f"kindle unconfirmed (인간성 {hum} → {hum2})"

    # ── steps ──
    def lever(self):
        g = self.tm.event_flag(ALTAR_GATE_OPEN)
        self.say(f"  lever: 제단 게이트 플래그 {ALTAR_GATE_OPEN} = {g}")
        if g is True:
            return "gate open"          # 한 번 열면 안 닫힘 (MoKa M1111-77) → 레버로 안 감
        if g is None:
            self.say("  lever: 플래그 못 읽음 → 안내·걷기로 판단 (예전 방식)")
        r = self._pull_lever()
        if r == "pulled":
            time.sleep(1.0)
            g2 = self.tm.event_flag(ALTAR_GATE_OPEN)
            self.say(f"  lever: 당긴 뒤 플래그 {ALTAR_GATE_OPEN} = {g2}")
            if g2 is False:
                return "pulled but flag off"
        return r

    def _pull_lever(self):
        ap, st = tuple(L["approach"]["stand"]), tuple(L["stand"])
        lv = L["objact"]["pos"]
        self.mv.walk_path([ap], self.nm, tol=0.3, timeout_per=10)
        self.mv.walk_path([st], self.nm, tol=0.25, timeout_per=6)
        # 11-11 시도 1: stand에서 px 547(안내 없음)인데 A → 레버 안 당겨짐, 게이트 길 unreachable. 안내가 뜬 두 번은 nudge(0.5, 0.4 s)
        #  뒤 (19.1, −26.1) — 그래서 먼저 nudge, px ≥ 750 일 때만 A, 누른 뒤 px가 떨어졌는지(안내 사라짐) 확인.
        for k in range(5):
            s = self.mv.snap(30.0)
            self.pad.move(*self.mv.stick_to(s, lv[0], lv[2], 0.5)); time.sleep(0.4 if k == 0 else 0.15); self.pad.move(0, 0); time.sleep(0.8)
            px = screen_prompt.prompt_px()
            p = self.mv.snap(5.0).player
            self.say(f"  lever: nudge {k} at ({p.x:.2f}, {p.z:.2f}) prompt px {px}")
            if px >= 750:
                self.pad.press(control.B.XUSB_GAMEPAD_A, 0.1); time.sleep(2.0)
                px2 = screen_prompt.prompt_px()
                self.say(f"  lever: A → px {px2}")
                time.sleep(4.0)
                return "pulled" if px2 < 500 else "A but prompt stayed"
        # MoKa M1111-70 "게이트가 닫혀 있으면 레버로 열기": 레버 안내가 없으면 이미 당긴 레버(게이트 열림)일 수 있음 →
        #  게이트 안쪽 점까지 걸어가 봄. 가면 열린 것("gate open"), 못 가면 닫혔는데 레버도 못 당김 → 멈춤.
        r = self.walk([(5.9, 16.0, -4.6)], "게이트 열렸나 확인")
        self.say(f"  lever: 안내 없음 → 게이트 안쪽 걷기 {r}")
        return "gate open" if r == "arrived" else "no prompt, gate closed"

    def drop(self):
        """Upper floor → lower stairs: walk off the edge toward MoKa's landing (rec 222903 t69.9: (13.22, 23.07, 27.79) heading 2.51
        → (10.39, 19.86, 29.41) → landed (10.7, 16.5, 31.7))."""
        # 시도 1 (225856): walk_to로 드롭 자리 가는 사이 따라온 255040(−229)·위층 석궁병 255042에게 맞음, 849 → 343.
        #  MoKa는 계단 끝에서 멈추지 않고 그대로 달려 떨어짐 → 걷기 없이 바로 질주 스틱으로 가장자리 넘김.
        saved = (self.esc.nudge_ok, self.esc.planned)
        self.esc.nudge_ok, self.esc.planned = False, "위층 → 아래 계단 드롭 (MoKa)"
        try:
            t0 = time.time(); y0 = None
            while time.time() - t0 < 6.0:
                s = self.mv.snap(5.0)
                if s is None:
                    time.sleep(0.05); continue
                p = s.player
                y0 = y0 or p.y
                goal = (13.22, 27.79) if (p.y > 22.5 and math.hypot(p.x - 13.22, p.z - 27.79) > 0.8 and p.z < 27.6) else ((10.4, 29.4) if p.y > 20.5 else (10.7, 31.7))
                self.pad.sprint(p.y > 22.5)
                self.pad.move(*self.mv.stick_to(s, goal[0], goal[1], 1.0))
                if p.y < 17.3 and abs(p.y - 16.5) < 0.8:
                    break
                time.sleep(0.03)
            self.pad.sprint(False); self.pad.move(0, 0); time.sleep(0.8)
        finally:
            self.esc.nudge_ok, self.esc.planned = saved
        s = self.state("drop")
        return "landed" if s and s.player.y < 17.5 else "not dropped"

    def run(self, first=0):
        steps = [
            ("lever", self.lever),
            ("gate", lambda: self.walk([(5.9, 16.0, -4.6), (6.9, 16.0, 0.6)], "게이트 안 (첫 적)")),
            ("stairs", lambda: self.walk([(10.2, 16.0, 4.7), (13.5, 16.4, 8.7), (13.9, 18.1, 13.5), (15.3, 20.7, 17.7),
                                          (16.6, 23.1, 22.0), (14.1, 23.1, 26.3)], "계단 → 위층 (질주, 안 싸움)", "sprint", HOLLOWS)),
            ("drop", self.drop),
            ("land_heal", lambda: (self.heal_if(0.6), "ok")[1]),
            ("lower", lambda: self.walk([(11.4, 14.0, 36.3), (8.4, 13.0, 40.3), (2.8, 13.0, 39.6), (-0.8, 13.0, 39.5)],
                                        "아래 계단 → 서쪽 (질주)", "sprint", HOLLOWS)),
            ("followers", lambda: self.clear(6.0, 6.0, "따라온 놈", center=(-0.8, 13.0, 39.5))),
            ("lure_up", lambda: self.walk([(-4.7, 13.8, 40.3)], "계단 1/3 (끌어내기)")),
            ("lure_back", lambda: self.walk([(-2.2, 13.0, 40.9)], "계단 밑으로")),
            ("lure_fight", lambda: self.clear(6.0, 8.0, "계단 밑", center=(-2.2, 13.0, 40.9))),
            ("to_ladder1", lambda: self.walk([(-10.24, 16.64, 38.71), (-10.3, 16.64, 33.0)], "사다리 1 앞 (안 싸움)", "walk", {250053})),
            ("ladder1", lambda: self.alt._ladder_up((-10.45, 16.64, 31.35), (-10.58, 23.14, 30.24), (-10.3, 16.64, 32.2), None)),
            ("top1_off", lambda: self.walk([(-8.4, 22.78, 26.9)], "사다리 구멍에서 떨어짐")),
            ("top1", lambda: self.clear(6.0, 6.0, "사다리 위", center=(-8.4, 22.78, 26.9))),
            ("to_ladder2", lambda: self.walk([(-8.4, 22.78, 26.9), (-4.0, 22.78, 27.4)], "사다리 2 앞")),
            ("ladder2", lambda: self.alt._ladder_up((-2.65, 22.79, 27.5), (-2.95, 26.29, 28.48), (-3.4, 22.78, 27.45), None)),
            ("fog", lambda: self.walk([(-3.3, 26.3, 36.0), (-1.0, 27.6, 37.1), (4.5, 27.6, 37.1)], "안개벽")),
            ("corridor", lambda: self.walk([(12.7, 27.6, 37.3), (15.1, 29.5, 44.7), (21.3, 32.5, 48.8), (29.1, 30.6, 48.8),
                                            (37.0, 29.8, 50.0), (37.3, 29.8, 58.1), (37.8, 29.8, 66.1), (37.0, 29.9, 74.2),
                                            (37.8, 29.8, 82.2), (37.5, 29.5, 89.5)], "통로")),
            ("plaza_safe", lambda: self.walk([(31.9, 27.6, 95.5), (22.0, 26.6, 94.6)], "광장 안전 자리")),
            ("plaza_heal", lambda: (self.heal_if(0.7), "ok")[1]),
            ("plaza_lure", lambda: self.walk([(24.5, 26.6, 98.0), (22.0, 26.6, 94.6)], "방패병 끌어내기")),
            ("plaza_fight", lambda: self.clear(7.0, 8.0, "광장", center=(22.0, 26.6, 94.6))),
            ("crossbow", lambda: self.walk([TARGET], "석궁병 자리")),
            ("crossbow_fight", lambda: self.clear(6.0, 5.0, "석궁병")),
            ("to_andre", self.to_andre),
            ("rest", self.rest),
        ]
        result = "ok"
        try:
            self.state("start")
            names = [n for n, _ in steps]
            UPPER = {"top1_off", "top1", "to_ladder2"}   # 사다리 1 위(y≈22.8)에 있어야 하는 단계
            redo = 0
            i = first
            while i < len(steps):
                name, fn = steps[i]
                self.say(f"STEP {i} {name}")
                r = fn()
                self.state(name)
                if self.dead() or r == "dead":
                    result = f"died at {i} {name}"; break
                s = self.mv.snap(5.0)
                if name in UPPER and s and s.player.y < 20.0 and redo < 2:
                    # 아래층으로 떨어짐 → 사다리 1부터 다시 (아래층 마당으로 걸어가 코뿔소 근처로 가지 않게)
                    redo += 1
                    self.say(f"  {name}: 아래층으로 떨어짐 (y {s.player.y:.1f}) — 사다리 1부터 다시 ({redo}/2)")
                    i = names.index("to_ladder1"); continue
                ok = r in ("arrived", "done", "ok", "pulled", "landed", "rested", "gate open") or (isinstance(r, str) and r.startswith("cleared"))
                if not ok:
                    result = f"stopped at {i} {name}: {r}"; break
                i += 1
            s = self.mv.snap(10.0)
            if result == "ok" and s:
                d = math.dist((s.player.x, s.player.y, s.player.z), TARGET)
                d2 = math.dist((s.player.x, s.player.y, s.player.z), ANDRE_STAND)
                result = f"rested at Andre (d {d2:.1f} m)" if d2 < 3 else (f"reached (d {d:.1f} m)" if d < 5 else f"ended {d:.1f} m from target")
        finally:
            self.pad.neutral()
            self.state("end")
            print(f"RESULT {result} · log {self.log.path}")
            # stay guarded instead of standing idle (P-160): fight what comes within 5 m until killed by TaskStop
            if not self.dead():
                try:
                    while True:
                        self.clear(5.0, 3600, "대기 가드")
                except KeyboardInterrupt:
                    pass
            try:
                self.esc.stop()
            except Exception:
                pass
            self.pad.close()
            self.lock.release()


if __name__ == "__main__":
    Route().run(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
