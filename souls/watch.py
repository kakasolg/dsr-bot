"""Layer 4 helper — watchers running separately from the decision loop: emergency escape (quit-out) and bloodstain tracking.

Quit-out (menu → Quit Game → Continue) **resets only enemy positions/alertness; dead enemies stay dead** (user confirmed 2026-09-24).
Resting (bonfire) revives every enemy. So to shake enemies off, use this instead of resting.
"""
from __future__ import annotations

import collections
import json
import threading
import time
from pathlib import Path

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
        → after quitting you stand again at the edge before the fall
      · Imminent death: two or more within 3.5 m and **predicted HP 2.8 s ahead** below 15 % (once per 60 s — it restarts on the spot)
        — you keep getting hit during the 2.4~2.5 s of quit input (once ended 298 → 24). Hence it watches incoming damage rate
    gen is +1 on every quit-and-return — all enemy pointers change, so upper layers re-find enemies when gen changes."""
    LETHAL_DROP = 8.0         # at 15 m, fell off the side of the ramp (~10~12 m) with HP 413 and died (2026-09-24)
    FALL_V = 2.5              # dropping this much in 0.4 s = falling — also catches falls with no anim ID (1550) (pushed off by a guard break)
    FALL_COOLDOWN = 4.0       # formerly 30 s: couldn't stop falling again right after respawning at the edge
    LEDGE_DROP = 3.0          # floor underfoot lower than this but not yet falling = on a cliff ledge
    LEDGE_SLIDE = 0.6         # (tuned 0.4~0.7 on 2 falls + a human recording: 0.6/0.5 fire 1.1~1.2 s before the fall, 1 false alarm) dropped this far below the last safe spot = sliding (bridges keep the same height, so they don't trigger)
    NUDGE_COOLDOWN = 0.6
    LEDGE_CREEP = 0.5         # descending while moving less than this in 1 s = sliding (stairs move faster)
    CROWD_COOLDOWN = 60.0     # avoid repeating at the same spot
    QUIT_S = 2.8

    def __init__(self, pad, nms: list, log=print, events=None):
        self.pad, self.nms, self.log, self.events = pad, nms, log, events
        self.escaping = False
        self.gen = 0
        self.quit_ok = True                                # False = never use quit-out (exit to menu and back) (for video recording, run.py --no-quit)
        self.nudge_ok = True                               # False = no ledge nudge-back (a deliberate drop — souls/asylum plunge onto the demon)
        self.last_fall = self.last_crowd = 0.0
        self.last_fall_pos = None     # so upper layers back away from the edge right after a fatal-fall escape
        self.safe_pos = None          # last spot with floor directly underfoot (_ledge)
        self.last_nudge = 0.0
        self.nudges = 0
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
                self.fire(why, kind, tm, p)
            time.sleep(0.02)

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
        import control
        import nav
        st = control.world_to_stick(sp[0] - p.x, sp[2] - p.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
        if not self._nudge(st):
            return
        self.last_nudge = time.time()
        self.nudges += 1
        self.log(f"   ⤺ 턱 위 미끄러짐 (바닥 {'없음' if drop is None else f'{drop:.0f} m 아래'}, {sp[1] - p.y:.1f} m 내려옴) — 안전 자리로 되돌림")
        if self.events:
            self.events("ledge", drop=None if drop is None else round(drop, 1), slide=round(sp[1] - p.y, 2), pos=[round(p.x, 2), round(p.y, 2), round(p.z, 2)])

    NUDGE_S = 0.35

    def _nudge(self, st) -> bool:
        """One writer for the nudge (P0-F): freeze → stick → neutral → unfreeze, the last two in finally. The decision loop's
        input is dropped meanwhile (guard included — [MoKa] accepted the guard being down for NUDGE_S); nav.Mover presses
        it again after unfreeze (Pad.epoch). False = a quit-out holds the pad, no nudge."""
        if not self.pad.freeze(take=False):
            return False
        try:
            self.pad.move(st[0], st[1])
            time.sleep(self.NUDGE_S)
        finally:
            self.pad.neutral()
            self.pad.unfreeze()
        return True

    def fire(self, why: str, kind: str, tm=None, p=None) -> dict:
        """Quit to menu and come back. Upper layers also call this to shake off enemies (kind='shake'). → result"""
        if not self.quit_ok:
            # user 2026-09-26: quit-outs in the video make it unfit for YouTube — when disabled, just log and keep fighting
            self.log(f"   (퀵 종료 꺼짐) {why} — 나가지 않고 계속")
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
            self.pad.freeze()
            res: dict = {"why": why, "kind": kind, "pos0": pos0}
            try:
                # straight to title without the menu (ChrClassWarp+0x19, 0.58 s) — the menu route takes 2~2.8 s and the menu wouldn't open mid-fall.
                # fall back to the old menu route if that fails
                t_q = time.time()
                q = time.time() - t_q if tm.quit_to_title(timeout=2.0) else None
                res["how"] = "byte" if q is not None else "menu"
                if q is None:
                    q = quitout.quit_out(tm, self.pad, gap=quitout.MENU_GAP, settle=0.03, ready_wait=0.05)
                    res["quit_steps"] = dict(quitout.LAST_STEPS)
                res["quit_s"] = None if q is None else round(q, 2)
                if q is None:
                    quitout.close_menu(tm, self.pad)
                else:
                    r = quitout.reload(self.pad)
                    res["reload_s"] = None if r is None else round(r, 1)
                    time.sleep(1.0)
                    if kind == "fall":
                        res["back"] = self._back_to_mesh()
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

    def __init__(self, log=print):
        self.log = log
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
                souls = tm.souls() or 0
                if pending is not None:                    # alive — did we really die?
                    if souls < pending["souls"] or (pending["souls"] == 0 and (tm.humanity() or 0) < pending["humanity"]):
                        rec = {**pending, "t": time.strftime("%Y-%m-%d %H:%M:%S")}
                        BLOODSTAIN.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
                        self.log(f"   ✝ 죽음 — 핏자국 {rec['pos']} (소울 {rec['souls']}, 인간성 {rec['humanity']})")
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
            time.sleep(0.2)

    def start(self) -> "Blood":
        self.th.start()
        return self

    def stop(self) -> None:
        self._stop = True
