"""Layer 4 helper — watchers running separately from the decision loop: emergency escape (quit-out) and bloodstain tracking.

Quit-out (menu → Quit Game → Continue) **resets only enemy positions/alertness; dead enemies stay dead** (user confirmed 2026-09-24).
The fast byte quit-out (ChrClassWarp+0x19) does NOT keep them dead (P-25, game check 2026-10-10) — only falls use it (Escape._quit).
Resting (bonfire) revives every enemy. So to shake enemies off, use this instead of resting.
"""
from __future__ import annotations

import collections
import json
import threading
import time
from pathlib import Path

import ctl
import env
import navmesh
import quitout


ROOT = Path(__file__).resolve().parent.parent
BLOODSTAIN = ROOT / "data" / "bloodstain.json"
FALL_ANIMS = (1550, 121500)
NO_GROUND = (1500, 1550, 121500, 1600, 6074, 6174)


class Escape:
    """Emergency escape. Polls at 50 Hz; when firing, freezes the pad (Pad.freeze) so decision-loop input doesn't mix with menu input.
      · Fatal fall: falling (motion 1550, or dropped more than 2.5 m in 0.4 s) and the floor underfoot is more than 8 m below
        → recorded only (fall_seen, MoKa 10-12); with fall_quit (--fall-quit) the old quit-out: you stand again at the edge before the fall
      · Imminent death: two or more within 3.5 m and **predicted HP 2.8 s ahead** below 15 % (once per 60 s — it restarts on the spot)
        — you keep getting hit during the 2.4~2.5 s of quit input (once ended 298 → 24). Hence it watches incoming damage rate
    gen is +1 on every quit-and-return — all enemy pointers change, so upper layers re-find enemies when gen changes."""
    LETHAL_DROP = 8.0         # at 15 m, fell off the side of the ramp (~10~12 m) with HP 413 and died (2026-09-24)
    FALL_V = 2.5              # dropping this much in 0.4 s = falling — also catches falls with no anim ID (1550) (pushed off by a guard break)
    FALL_COOLDOWN = 4.0       # formerly 30 s: couldn't stop falling again right after respawning at the edge
    LEDGE_DROP = 3.0          # floor underfoot lower than this but not yet falling = on a cliff ledge
    LEDGE_SLIDE = 0.6         # (tuned 0.4~0.7 on 2 falls + a human recording: 0.6/0.5 fire 1.1~1.2 s before the fall, 1 false alarm) dropped this far below the last safe spot = sliding (bridges keep the same height, so they don't trigger)
    NUDGE_COOLDOWN = 0.6
    NUDGE_FUTILE = 2          # P-81: this many nudges in a row that leave us where the last one started → stop until we move or stand
                              # on floor again (clay18-1 zone 6: 23 nudges, 1 s apart, standing 1 m down on solid ground off the mesh;
                              # pull-off2 ramp ledge: 22 at 3.5 m down — no nudge moved us, each froze the pad and dropped the guard)
    NUDGE_SAME_R = 0.5        # … "where it started": within this (horizontal) and NUDGE_SAME_DY (height)
    NUDGE_SAME_DY = 0.15      # standing: ±0.1 m in both runs; a 0.35 m/s slide (152400) drops ≥ 0.2 m between nudges
    LEDGE_CREEP = 0.5         # descending while moving less than this in 1 s = sliding (stairs move faster)
    CROWD_COOLDOWN = 60.0     # avoid repeating at the same spot
    QUIT_S = 2.8

    def __init__(self, pad, nms: list, log=print, events=None):
        self.pad, self.nms, self.log, self.events = pad, nms, log, events
        self.escaping = False
        self.gen = 0
        self.quit_ok = True                                # False = never use quit-out (exit to menu and back) (for video recording, run.py --no-quit)
        # [MoKa] 2026-10-12: "낙사시 퀵 종료 포기하고, 최대한 도망치던가 반격 하던가" — a fall is only recorded; the layers above
        # keep running (flee / fight back) and a death is handled after respawn (souls/afterdeath.py). Quit-outs after falls put the
        # bot back on the same ledge, blind and with the pad frozen: 5 of 5 fall deaths after one came from that (P-71).
        # True = the old fall quit-out (run.py --fall-quit).
        self.fall_quit = False
        self.planned = None           # a drop we mean to make (Taurus plunge, asylum plunge, the crow) → not a fall: logged, no "fall" event
        self.nudge_ok = True                               # False = no ledge nudge-back (a deliberate drop — souls/asylum plunge onto the demon)
        self.last_fall = self.last_crowd = 0.0
        self.last_fall_pos = None     # so upper layers back away from the edge right after a fatal-fall escape
        self.safe_pos = None          # last spot with floor directly underfoot (_ledge)
        self.last_nudge = 0.0
        self.nudges = 0
        self._nudge_at = None         # where the last nudge started (x, y, z) — P-81: same spot again = it didn't work
        self._futile = 0              # nudges in a row that left us where the one before started
        self._pos = collections.deque(maxlen=120)
        self._lock = threading.Lock()
        self._stop = False
        self._hp = collections.deque(maxlen=60)
        self._y = collections.deque(maxlen=40)
        self.th = threading.Thread(target=self._run, daemon=True)

    FREEFALL = 4.0            # where the floor is unknown (navmesh gaps: stair tops, bridges), must drop this much in 0.8 s to count as a fatal fall
                              # — 2026-09-24: 2 false "99 m below" alarms from a 0.4 m y change at the same spot, each wasting a 10 s forced quit

    def floor_drop(self, p) -> float | None:
        """Distance to the floor underfoot. None (unknown) where there is no navmesh — using 99 caused false alarms at stair tops."""
        below = [y for nm in self.nms for y, f, _i in nm.tris_at(p.x, p.z) if not (f & navmesh.BLOCKED) and y <= p.y + 0.3]
        return p.y - max(below) if below else None

    def _dps(self, now: float) -> float:
        pts = [(t, hp) for t, hp in self._hp if now - t <= 1.5]
        if len(pts) < 2:
            return 0.0
        lost = sum(max(0, a[1] - b[1]) for a, b in zip(pts, pts[1:]))
        return lost / max(0.3, pts[-1][0] - pts[0][0])

    def _run(self) -> None:
        tm = env.make_telemetry({})
        while not self._stop:
            try:
                s = tm.snapshot(within=5.0)
            except Exception:
                s = None
            if s is None or s.player.hp is None or s.player.hp <= 0 or self.escaping:
                time.sleep(0.05)
                continue
            now, p = time.time(), s.player
            self._hp.append((now, p.hp))
            self._y.append((now, p.y))
            why = None
            ys = [y for t, y in self._y if now - t <= 0.4]
            falling = p.anim in FALL_ANIMS or (len(ys) >= 3 and max(ys) - p.y > self.FALL_V)
            if not falling and self.nudge_ok and now - self.last_nudge > self.NUDGE_COOLDOWN:
                self._ledge(s, p, now)
            if falling and now - self.last_fall > self.FALL_COOLDOWN:
                drop = self.floor_drop(p)
                if drop is None:
                    ys8 = [y for t, y in self._y if now - t <= 0.8]
                    if len(ys8) >= 4 and max(ys8) - p.y > self.FREEFALL:
                        why, kind = f"낙사 (바닥 모름, 0.8 s 에 {max(ys8) - p.y:.1f} m)", "fall"
                elif drop > self.LETHAL_DROP:
                    why, kind = f"낙사 (발밑 바닥 {drop:.0f} m 아래)", "fall"
            # 둘러싸였을 때 퀵 종료는 없앰 ([MoKa] 2026-09-28: "둘러싸였을 때는 퀵 종료하면 안 되고 후퇴해야 해") — 그 자리에서 다시
            # 시작해 같은 적 옆에서 이어 싸움 (Bandit Bot: 동시 피격 한 번에 피해 속도가 튀어 HP 65 %에서 걸림 → HP 441로 이어 싸우다 사망).
            # 둘러싸임은 duel 'crowd' → Field.fall_back 이 맡는다
            if why:
                if kind == "fall" and not self.fall_quit:
                    self.fall_seen(why, p)
                else:
                    self.fire(why, kind, tm, p)
            time.sleep(0.02)

    def fall_seen(self, why: str, p=None) -> dict:
        """A fall under the no-quit policy (fall_quit False): record it and keep the cooldown, nothing else — no freeze, no input,
        so the layers above keep the pad to flee or fight wherever we land. → the event row"""
        pos = None if p is None else [round(p.x, 2), round(p.y, 2), round(p.z, 2)]
        self.last_fall, self.last_fall_pos = time.time(), pos
        if self.planned:                                   # [win] 10-12: Taurus plunges came out as 낙하×2 in risk_report
            self.log(f"   (계획된 낙하: {self.planned}) {why} @ {pos}")
            ctl.emit("esc", ev="fall_planned", why=why, planned=self.planned, pos0=pos)
            return {"why": why, "kind": "fall", "pos0": pos, "planned": self.planned}
        self.log(f"   ⚠ 낙하: {why} @ {pos} — 퀵 종료 안 함, 계속")
        row = {"why": why, "kind": "fall", "pos0": pos, "hp": None if p is None else p.hp}
        ctl.emit("esc", ev="fall_seen", why=why, pos0=pos)  # record only
        if self.events:
            self.events("fall", **row)                     # not "escape" — risk_report counts those as quit-outs
        return row

    def _back_to_mesh(self, secs: float = 2.5) -> str | None:
        """After a fatal-fall quit-out: the game restarts at the spot just before the fall (on the ledge) — left alone it slides again,
        repeating fall → quit → restart on the ledge three times (2026-09-25 183328). Before other layers move (pad still frozen),
        walk to the nearest walkable floor."""
        import control
        import nav
        tm = env.make_telemetry({})
        t0 = time.time()
        goal = None
        while time.time() - t0 < secs:
            s = tm.snapshot(within=2.0)
            if s is None or s.cam_yaw is None:
                time.sleep(0.05)
                continue
            p = s.player
            if goal is None:
                cands = [g for nm in self.nms for g in [nm.nearest_walkable(p.x, p.y, p.z, r=8.0, dy=1.5)] if g]
                if not cands:
                    return "바닥 못 찾음"
                goal = min(cands, key=lambda g: (g[0] - p.x) ** 2 + (g[2] - p.z) ** 2)
            d = ((goal[0] - p.x) ** 2 + (goal[2] - p.z) ** 2) ** 0.5
            if d < 0.5:
                self.pad.move(0.0, 0.0)
                return f"{d:.1f} m"
            st = control.world_to_stick(goal[0] - p.x, goal[2] - p.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
            self.pad.move(st[0] * 0.6, st[1] * 0.6)          # inside fire() — only this thread, which froze the pad, gets input through
            time.sleep(0.05)
        self.pad.move(0.0, 0.0)
        return "시간 초과"

    def _ledge(self, s, p, now: float) -> None:
        """If sliding on a cliff ledge, step back toward the last safe spot before falling.
        Black box (2026-09-25 152400): the bot walked off the mesh on the ramp, slid on the ledge for 2.6 s from y −39.3 → −40.2,
        then fell and died — the fatal-fall watcher only quit out after the fall began, too late."""
        self._pos.append((now, p.x, p.z))
        drop = self.floor_drop(p)
        if drop is not None and drop < 0.6:
            self.safe_pos = (p.x, p.y, p.z)
            self._nudge_at, self._futile = None, 0
            return
        # no walkable floor underfoot (None — below that ledge were only inactive tiles) or more than 3 m below.
        # descending stairs also leaves the mesh empty and y dropping — but then we move fast sideways. Ledge sliding moved under 0.8 m in 1 s
        sp = self.safe_pos
        if sp is None or s.cam_yaw is None or (drop is not None and drop < self.LEDGE_DROP):
            return
        if sp[1] - p.y < self.LEDGE_SLIDE or ((p.x - sp[0]) ** 2 + (p.z - sp[2]) ** 2) ** 0.5 > 4.0:
            return
        old = [q for q in self._pos if now - q[0] <= 1.0]
        if len(old) < 3 or ((p.x - old[0][1]) ** 2 + (p.z - old[0][2]) ** 2) ** 0.5 > self.LEDGE_CREEP:
            return
        if not self._nudge_worth(p):
            return
        import control
        import nav
        st = control.world_to_stick(sp[0] - p.x, sp[2] - p.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
        if not self._nudge(st):
            return
        self._nudge_at = (p.x, p.y, p.z)
        self.last_nudge = time.time()
        self.nudges += 1
        self.log(f"   ⤺ 턱 위 미끄러짐 (바닥 {'없음' if drop is None else f'{drop:.0f} m 아래'}, {sp[1] - p.y:.1f} m 내려옴) — 안전 자리로 되돌림")
        if self.events:
            self.events("ledge", drop=None if drop is None else round(drop, 1), slide=round(sp[1] - p.y, 2), pos=[round(p.x, 2), round(p.y, 2), round(p.z, 2)])

    def _nudge_worth(self, p) -> bool:
        """P-81: False once NUDGE_FUTILE nudges in a row left us where the one before started — we stand there (solid floor the
        NavMesh doesn't have, or held against foes), so another nudge only freezes the pad and drops the guard again. Moving away from
        that spot or standing on floor again (_ledge) re-arms it."""
        q = self._nudge_at
        same = (q is not None and ((p.x - q[0]) ** 2 + (p.z - q[2]) ** 2) ** 0.5 <= self.NUDGE_SAME_R
                and abs(p.y - q[1]) <= self.NUDGE_SAME_DY)
        if not same:
            self._futile = 0
            return True
        if self._futile >= self.NUDGE_FUTILE:
            return False
        self._futile += 1
        if self._futile < self.NUDGE_FUTILE:
            return True
        self.log(f"   ⤺ 턱 되돌림 {self.NUDGE_FUTILE}번째도 제자리 ({p.x:.1f},{p.y:.1f},{p.z:.1f}) — 움직이거나 바닥에 설 때까지 그만")
        ctl.emit("esc", ev="nudge_futile", pos=[round(p.x, 2), round(p.y, 2), round(p.z, 2)])
        if self.events:
            self.events("ledge_futile", pos=[round(p.x, 2), round(p.y, 2), round(p.z, 2)])
        return False

    NUDGE_S = 0.35

    def _nudge(self, st) -> bool:
        """One writer for the nudge (P0-F): freeze → stick → neutral → unfreeze, the last two in finally. The decision loop's
        input is dropped meanwhile (guard included — [MoKa] accepted the guard being down for NUDGE_S); nav.Mover presses
        it again after unfreeze (Pad.epoch). False = a quit-out holds the pad, no nudge."""
        if not self.pad.freeze(take=False):
            ctl.emit("esc", ev="nudge_yield")              # P1-D: record only
            return False
        t0 = time.perf_counter()
        ctl.emit("esc", ev="nudge_start", stick=[round(st[0], 3), round(st[1], 3)])
        try:
            self.pad.move(st[0], st[1])
            time.sleep(self.NUDGE_S)
        finally:
            self.pad.neutral()
            self.pad.unfreeze()
            ctl.emit("esc", ev="nudge_end", dt_ms=round((time.perf_counter() - t0) * 1000, 1))
        return True

    def _quit(self, tm, kind: str, res: dict) -> float | None:
        """
        ── 어느 퀵 종료로 나가나 (P-25) ──────────────────────────────
         · byte (ChrClassWarp+0x19 = 1, 곧장 타이틀, 월드에서 1.1 s) — **그 지역에서 죽인 적이 되살아남**
           (2026-10-10 게임 확인: byte → Continue 직후 255041·255042 셋이 다시 섬 / menu → 넷 번 모두 죽은 그대로. 세이브는 둘 다 씀)
         · menu (Quit Game, 입력 0.94 s + 저장 1.0 s = 1.95 s) — 죽인 적은 그대로. 떨어지는 중엔 메뉴가 안 열린다고 봄
         · 그래서 낙사(fall)만 byte, 나머지(shake …)는 menu. 첫 방식이 실패하면 다른 방식으로
         · byte로 나갔으면 res["revive_risk"] = True — 위 층은 esc.gen 이 바뀌면 적을 새로 찾는다 (field 신원 묶기, pass_ramp 생존 확인)
        """
        byte = lambda: (lambda t0: time.time() - t0 if tm.quit_to_title(timeout=2.0) else None)(time.time())

        def menu():
            q = quitout.quit_out(tm, self.pad, gap=quitout.MENU_GAP, settle=0.03, ready_wait=0.05)
            res["quit_steps"] = dict(quitout.LAST_STEPS)
            return q
        order = (("byte", byte), ("menu", menu)) if kind == "fall" else (("menu", menu), ("byte", byte))
        for i, (how, go) in enumerate(order):
            if i:
                quitout.close_menu(tm, self.pad)          # a half-open menu from the first try
            res["how"] = how
            q = go()
            if q is not None:
                res["revive_risk"] = how == "byte"
                return q
        return None

    def fire(self, why: str, kind: str, tm=None, p=None) -> dict:
        """Quit to menu and come back. Upper layers also call this to shake off enemies (kind='shake'). → result"""
        if not self.quit_ok:
            # user 2026-09-26: quit-outs in the video make it unfit for YouTube — when disabled, just log and keep fighting
            self.log(f"   (퀵 종료 꺼짐) {why} — 나가지 않고 계속")
            ctl.emit("esc", ev="fire_skipped", kind=kind, why=why)          # P1-D: record only
            self.last_crowd = self.last_fall = time.time()   # keep the cooldown — so the same line isn't printed every tick
            return {"why": why, "kind": kind, "skipped": True}
        with self._lock:
            tm = tm or env.make_telemetry({})
            if p is None:
                s0 = tm.snapshot(within=5.0)
                p = s0.player if s0 else None
            pos0 = None if p is None else [round(p.x, 2), round(p.y, 2), round(p.z, 2)]
            self.log(f"   ⚠ 퀵 종료: {why} @ {pos0}")
            self.escaping = True
            t_fire = time.perf_counter()
            ctl.emit("esc", ev="fire_start", kind=kind, why=why, pos0=pos0)  # P1-D: record only
            self.pad.freeze()
            res: dict = {"why": why, "kind": kind, "pos0": pos0}
            try:
                q = self._quit(tm, kind, res)
                res["quit_s"] = None if q is None else round(q, 2)
                ctl.emit("esc", ev="quit", how=res["how"], ok=q is not None, quit_s=res["quit_s"])
                if q is None:
                    quitout.close_menu(tm, self.pad)
                else:
                    r = quitout.reload(self.pad)
                    res["reload_s"] = None if r is None else round(r, 1)
                    time.sleep(1.0)
                    if kind == "fall":
                        res["back"] = self._back_to_mesh()
                    if res.get("revive_risk"):
                        self.log("   ⚠ byte 퀵 종료 — 이 지역에서 죽인 적이 되살아났을 수 있음 (P-25)")
            finally:
                self.pad.neutral()
                self.pad.unfreeze()
            tm2 = env.make_telemetry({})
            s = tm2.snapshot(within=5.0)
            if s:
                res["pos"] = [round(s.player.x, 2), round(s.player.y, 2), round(s.player.z, 2)]
                res["hp"] = s.player.hp
            now = time.time()
            if kind == "fall":
                self.last_fall, self.last_fall_pos = now, pos0
            elif kind == "crowd":
                self.last_crowd = now
            self._hp.clear()
            self._y.clear()
            self.gen += 1
            self.escaping = False
            ctl.emit("esc", ev="fire_end", kind=kind, gen=self.gen, dt_ms=round((time.perf_counter() - t_fire) * 1000, 1),
                     how=res.get("how"), quit_s=res.get("quit_s"), reload_s=res.get("reload_s"), back=res.get("back"))
            self.log(f"   ⚠ 퀵 종료 결과: {res}")
            if self.events:
                self.events("escape", **res)
            return res

    def start(self) -> "Escape":
        self.th.start()
        return self

    def stop(self) -> None:
        self._stop = True
        self.th.join(timeout=2.0)


class Blood:
    """Bloodstain — on death, souls/humanity are left at that spot (if fell, at the edge just before the fall).
    It used to record the moment HP read 0, so fake 'deaths' during quit-out/loading left bloodstains at the bonfire,
    and going to pick one up and pressing A sat at the bonfire, reviving every killed enemy (measured twice, 2026-09-24).
    So it records **only when souls actually dropped after respawn**. While alive, a one-shot soul gain equal to the bloodstain counts as recovery and clears it."""

    def __init__(self, log=print, context=None, cause=None):
        self.log = log
        # death record ([cloud] 2026-10-12, docs/analysis-death-2026-10-12.md §3 a): context() at the death moment (escape state …),
        # cause() after the respawn (BlackBox.take_fatal: fall / hit split of the killing bundle) → one "death" event per real death
        self.context, self.cause = context, cause
        self._stop = False
        self.th = threading.Thread(target=self._run, daemon=True)

    @staticmethod
    def read() -> dict | None:
        try:
            return json.loads(BLOODSTAIN.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _run(self) -> None:
        tm = env.make_telemetry({})
        last, pending, prev_souls, last_attach = None, None, None, time.time()
        seen_sent = False                                  # death_seen sent; re-armed only after HP > 0 is seen again
        while not self._stop:
            try:
                s = tm.snapshot(within=1.0)
            except Exception:
                s = None
            if s is None:
                if time.time() - last_attach > 3.0:
                    last_attach = time.time()
                    try:
                        tm = env.make_telemetry({})
                    except Exception:
                        pass
                time.sleep(0.2)
                continue
            p = s.player
            if p.hp is not None and p.hp > 0:
                seen_sent = False
                souls = tm.souls() or 0
                if pending is not None:                    # alive — did we really die?
                    if souls < pending["souls"] or (pending["souls"] == 0 and (tm.humanity() or 0) < pending["humanity"]):
                        ctx = pending.pop("ctx", None)
                        rec = {**pending, "t": time.strftime("%Y-%m-%d %H:%M:%S")}
                        BLOODSTAIN.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
                        self.log(f"   ✝ 죽음 — 핏자국 {rec['pos']} (소울 {rec['souls']}, 인간성 {rec['humanity']})")
                        self._death_event(rec, ctx)
                    pending = None
                    prev_souls = souls
                rec = self.read()
                # kills also add souls — count as recovery only when that much was gained within 3 m of the bloodstain
                if (rec and prev_souls is not None and souls - prev_souls >= max(1, rec["souls"])
                        and ((p.x - rec["pos"][0]) ** 2 + (p.z - rec["pos"][2]) ** 2) ** 0.5 < 3.0):
                    BLOODSTAIN.unlink(missing_ok=True)
                    self.log(f"   핏자국 회수됨: 소울 {prev_souls} → {souls}")
                prev_souls = souls
                if p.anim not in NO_GROUND:
                    last = {"pos": [round(p.x, 2), round(p.y, 2), round(p.z, 2)], "souls": souls, "humanity": tm.humanity() or 0}
            elif pending is None and last is not None and (last["souls"] > 0 or last["humanity"] > 0):
                pending = dict(last)
                if self.context is not None:
                    try:                                   # record only — must not stop this thread
                        pending["ctx"] = self.context()
                    except Exception:
                        pass
                ev = getattr(self.log, "event", None)      # run.py's Log has it; the default print does not
                if ev is not None and not seen_sent:
                    seen_sent = True
                    try:                                   # record only — must not stop this thread
                        ev("death_seen", hp=p.hp, max_hp=p.max_hp, anim=p.anim,
                           pos=[None if v is None else round(v, 2) for v in (p.x, p.y, p.z)])
                    except Exception:
                        pass
            time.sleep(0.2)

    def _death_event(self, rec: dict, ctx: dict | None) -> None:
        """One "death" line: where / what was dropped, the state at the death moment, and the cause from the black box
        (cause 'fall' | 'hit', or 'unknown' with no feed). Record only."""
        ev = getattr(self.log, "event", None)
        if ev is None:
            return
        try:
            fatal = self.cause() if self.cause is not None else None
            row = {"pos": rec["pos"], "souls": rec["souls"], "humanity": rec["humanity"], **(ctx or {})}
            row.update({"cause": "unknown"} if not fatal else
                       {"cause": fatal["cause"], "lost_hit": fatal.get("lost_hit"), "lost_fall": fatal.get("lost_fall"),
                        "drop_m": fatal.get("drop_m"), "blame": fatal.get("blame"), "hit_n": fatal.get("n")})
            ev("death", **row)
            what = (f"낙하 {row.get('drop_m')} m (-{row.get('lost_fall')})" + (f" + 피격 -{row['lost_hit']}" if row.get("lost_hit") else "")
                    if row["cause"] == "fall" else "피격" if row["cause"] == "hit" else "원인 모름 (블랙박스 없음)")
            self.log(f"   ✝ 사망 원인: {what}")
        except Exception:
            pass

    def start(self) -> "Blood":
        self.th.start()
        return self

    def stop(self) -> None:
        self._stop = True
