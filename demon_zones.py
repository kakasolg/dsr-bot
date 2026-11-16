"""Asylum Demon hit zones — where do we stand when it hits? (MoKa 11-16 M1116-08 "무적 상태로 수용소 데몬 테스트 해줘";
[cloud] board c4a93727 post 99e28576: stage 1 only — record, no attacks).

    python demon_zones.py [--limit 1800] [--rows 300] [--per-cell 10] [--cell-s 120]

Offline drill only — game-memory writes (CLAUDE.md: offline use only, MoKa asked for it):
  ChrDbg PlayerNoDead (our HP still drops, never to 0) · AllNoDead (the demon never dies) · set_hp refill under REFILL.
Start: the save before the demon's upper fog wall (backup-20260929-070944-asylum-test-before-demon-fog) or on the arena floor.
  upper floor → the fog wall (souls/asylum.Asylum._fog, door centre) → walk off the ledge toward it, no R1 (no plunge).
Then, never pressing R1 · R2 · roll · guard, it takes up each CELL (band × angle round the demon's facing) in turn and stands
still there ((가) "서 있기") while it attacks; between attacks, if the live angle / distance left the cell, it walks back in.

Records (data/runs/<run>.zones.jsonl):
  "win"    one row per demon hit window (souls/parry.windows_for on c2232 — tae_turn.json): demon anim, window, its pos/heading,
           ours, signed angle off its facing (+ = its right), horizontal distance (and minus HitRadius 2.5), my anim, HP, SP,
           cell, mode, hurt_2s (lost HP in the 2 s before = maybe knocked down), then lost = HP dropped from the window start to
           its end + HIT_S, my anims in that span.
  "attack" each time the demon starts an attack anim (3000–3999): anim, distance, our angle (AI distance → attack table).
  "refill" HP set back to max · "cell" cell start / end · "end".
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEMON = 223200
BODY_R = 2.5             # combat.json 223200 HitRadius
HIT_S = 0.4              # HP lost up to this after a window's end counts for it
HURT_S = 2.0             # HP lost this long before a window start → "hurt_2s" (maybe still knocked down — tainted row)
REFILL = 0.4             # set HP back to max under this share
ANG_TOL = 30.0           # in the cell: live angle within this of the cell's angle …
R_TOL = 1.0              # … and distance within this of the cell's
# (name, distance from its centre m, angle off its facing deg; + = its right) — [cloud] 99e28576 plan, distance bands:
#   embedded (inside the body, 3008 "dist ≤ 0"?) · contact (3004/3005/3006) · mid 4–7 (3002 chain, 3003) · far 7–12 (3000/3001/3014)
CELLS = [("붙음-정면", 3.0, 0), ("붙음-옆", 3.0, 90), ("붙음-뒤", 3.0, 180),
         ("중간-정면", 5.5, 0), ("중간-옆", 5.5, 90), ("중간-뒤", 5.5, 180),
         ("멂-정면", 9.0, 0), ("멂-옆", 9.0, 90),
         ("파묻힘-정면", 1.5, 0), ("파묻힘-뒤", 1.5, 180)]


def signed_off(c, p) -> float:
    """Where p is round c, deg off c's facing, −180..180, + = c's right (world yaw of its facing = heading + π)."""
    if c.heading is None:
        return 0.0
    fwd = c.heading + math.pi
    a = (math.atan2(p.x - c.x, p.z - c.z) - fwd + math.pi) % (2 * math.pi) - math.pi
    return math.degrees(a)          # same sign as moves.rel_angle (duel.backstab_stick: + = on its right)


def cell_point(c, r: float, ang: float) -> tuple[float, float]:
    """World (x, z) r m from c's centre, ang deg off its facing (+ = its right)."""
    yaw = (c.heading or 0.0) + math.pi + math.radians(ang)
    return c.x + math.sin(yaw) * r, c.z + math.cos(yaw) * r


def in_cell(c, p, r: float, ang: float) -> bool:
    d = math.hypot(p.x - c.x, p.z - c.z)
    da = abs((signed_off(c, p) - ang + 180) % 360 - 180)
    return abs(d - r) <= R_TOL and da <= ANG_TOL


class ZoneRec:
    """Pure recorder (tests/demon_zones_test.py): feed every snapshot; it writes "win" / "attack" rows through emit."""

    def __init__(self, emit, windows_for):
        self.emit, self.windows_for = emit, windows_for
        self.seen: set = set()
        self.open: list = []           # [row, w1_abs_deadline, hp_prev, lost, my_anims]
        self.hp_hist: list = []        # (t, hp)
        self.last_anim = None
        self.cell, self.mode = None, "가"
        self.rows = 0

    def tick(self, t: float, p, c, at) -> None:
        hp = p.hp
        self.hp_hist = [(tt, h) for tt, h in self.hp_hist if t - tt <= HURT_S + 0.5] + [(t, hp)]
        for o in self.open:
            if hp < o[2]:
                o[3] += o[2] - hp
            o[2] = hp
            if p.anim is not None and (not o[4] or o[4][-1] != p.anim):
                o[4].append(p.anim)
        done = [o for o in self.open if t >= o[1]]
        self.open = [o for o in self.open if t < o[1]]
        for o in done:
            self.emit("win", **o[0], lost=o[3], my_anims=o[4][:8])
            self.rows += 1
        if c is None:
            return
        a = c.anim if c.anim is not None else -1
        if 3000 <= a < 4000 and a != self.last_anim:
            self.emit("attack", anim=a, d=round(math.hypot(p.x - c.x, p.z - c.z), 2), off=round(signed_off(c, p)),
                      cell=self.cell)
        self.last_anim = a
        if not 3000 <= a < 4000 or at is None:
            return
        wins = self.windows_for(DEMON, a) or []
        for i, (w0, w1) in enumerate(wins):
            key = (c.ptr, a, i, round(t - at, 1))       # one play of this anim (start time) × window
            if at < w0 or any(k[:3] == key[:3] and abs(k[3] - key[3]) < 0.3 for k in self.seen):
                continue
            self.seen.add(key)
            d = math.hypot(p.x - c.x, p.z - c.z)
            hurt = max(0, max((h for tt, h in self.hp_hist if t - tt <= HURT_S), default=hp) - hp)
            row = {"anim": a, "win": i, "w0": w0, "w1": w1, "at": round(at, 3), "demon": [round(c.x, 2), round(c.z, 2)],
                   "dhd": None if c.heading is None else round(c.heading, 3), "me": [round(p.x, 2), round(p.z, 2)],
                   "off": round(signed_off(c, p)), "d": round(d, 2), "d_body": round(d - BODY_R, 2), "my": p.anim,
                   "hp": hp, "sp": p.sp, "cell": self.cell, "mode": self.mode, "hurt_2s": hurt}
            self.open.append([row, t + (w1 - at) + HIT_S, hp, 0, [p.anim]])

    def close(self) -> None:
        for o in self.open:
            self.emit("win", **o[0], lost=o[3], my_anims=o[4][:8], cut=True)
            self.rows += 1
        self.open = []


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=float, default=1800.0, help="s, whole drill")
    ap.add_argument("--rows", type=int, default=300, help="stop after this many window rows")
    ap.add_argument("--per-cell", type=int, default=10, help="window rows per cell before the next")
    ap.add_argument("--cell-s", type=float, default=120.0, help="s at most per cell")
    ap.add_argument("--mode", choices=["가", "나"], default="가",
                    help="가: stand still while it swings (walk back into the cell only between attacks) · 나: keep going for the "
                         "cell point the whole time, swings too (it turns to face us, so 가 gives almost only its front — 042034)")
    ap.add_argument("--cells", default=None, help="comma list of cell names (default: all)")
    a = ap.parse_args()

    import control, env, navmesh, track
    from botlock import BotLock
    from run import Log
    from souls import asylum as AS, moves as M, parry as PARRY, weapons
    from souls.field import Field
    from souls.watch import Escape

    log = Log("demon-zones")
    zpath = str(log.path).replace(".jsonl", ".zones.jsonl")
    zf = open(zpath, "a", encoding="utf-8")
    t0 = time.time()

    def emit(kind, **kw):
        d = {"t": round(time.time() - t0, 3), "kind": kind, **kw}
        zf.write(json.dumps(d, ensure_ascii=False) + "\n"); zf.flush()
        if kind in ("win",):
            log(f"   판정 {kw['anim']}#{kw['win']} {kw['cell']} 정면에서 {kw['off']:+d}° · {kw['d']} m → "
                f"{'맞음 −' + str(kw['lost']) if kw['lost'] else '안 맞음'}")
        elif kind != "attack":
            log(f"   [{kind}] {kw}")

    lock = BotLock()
    if not lock.acquire():
        raise SystemExit("봇이 돌고 있음 (data/bot.lock)")
    tm = env.make_telemetry({})
    tr = track.Track(str(log.path).replace(".jsonl", ".track.jsonl")).attach(tm)
    log.on_line = tr.say
    control.focus_game(); time.sleep(0.5)
    pad = control.Pad(); time.sleep(2.0)
    nm = navmesh.Navmesh(AS.MAP)
    mv = M.Moves(tm, pad); tr.follow(mv)
    w = weapons.of(tm.right_weapon()); mv.weapon = w
    esc = Escape(pad, [nm], log=log, events=log.event)    # not started: no fall quit-out (the drop into the arena is ~10 m)
    esc.quit_ok = False
    fld = Field(mv, w, esc, bonfires=[], log=log, events=log.event)
    asy = AS.Asylum(fld, nm, log=log, events=log.event)
    win = PARRY.load_windows()
    rec = ZoneRec(emit, lambda npc, anim: PARRY.windows_for(win, npc, anim))
    nd0, and0 = tm.get_dbg(tm.DBG_PLAYER_NO_DEAD), tm.get_dbg(tm.DBG_ALL_NO_DEAD)
    tm.set_dbg(tm.DBG_PLAYER_NO_DEAD, True)
    tm.set_dbg(tm.DBG_ALL_NO_DEAD, True)
    emit("start", nodead_before=[nd0, and0], nodead_now=[tm.get_dbg(tm.DBG_PLAYER_NO_DEAD), tm.get_dbg(tm.DBG_ALL_NO_DEAD)],
         windows_c2232=sum(1 for k in win if k[0] == "c2232"))
    result = "?"
    try:
        s = mv.snap(40.0)
        if s is None:
            raise SystemExit("스냅숏 없음")
        if s.player.y > 205.0:                            # upper floor: fog wall, then off the ledge (no plunge R1)
            r = asy._fog(AS.FOG_CENTER[AS.PLUNGE_AT], (3.64, 210.11, -32.68), "데몬 위 안개벽")
            emit("fog", r=r)
            if r != "ok":
                raise SystemExit("안개벽 못 지남")
            y0, t1 = mv.snap(40.0).player.y, time.time()
            while time.time() - t1 < 8.0:
                s = mv.snap(40.0)
                d = AS.Asylum._demon_c(s)
                if s is not None and s.cam_yaw is not None:
                    tx, tz = (d.x, d.z) if d is not None else (3.0, -29.5)
                    pad.move(*mv.stick_to(s, tx, tz, 1.0))
                if s is not None and s.player.y < y0 - 8.0:
                    break
                time.sleep(0.03)
            pad.neutral()
            s = mv.snap(40.0)
            emit("drop", y=None if s is None else round(s.player.y, 2), hp=None if s is None else s.player.hp)
        t_end = t0 + a.limit
        rec.mode = a.mode
        cells = [x for x in CELLS if a.cells is None or x[0] in a.cells.split(",")]
        for name, r_, ang in cells:
            if time.time() > t_end or rec.rows >= a.rows:
                break
            rec.cell, n0, tc = name, rec.rows, time.time()
            emit("cell", cell=name, r=r_, ang=ang, phase="start")
            moving_since = None
            while time.time() - tc < a.cell_s and rec.rows - n0 < a.per_cell and time.time() < t_end and rec.rows < a.rows:
                s = mv.snap(40.0)
                if s is None:
                    time.sleep(0.02); continue
                p, c = s.player, AS.Asylum._demon_c(s)
                if c is None:
                    c = next((x for x in s.chars if x.npc_param == DEMON), None)
                at = None if c is None else tm.anim_time(c.ptr)
                rec.tick(time.time(), p, c, at)
                if p.max_hp and p.hp < REFILL * p.max_hp:
                    tm.set_hp(p.max_hp)
                    emit("refill", hp=p.hp, to=p.max_hp)
                if c is None:
                    pad.neutral(); time.sleep(0.05); continue
                swinging = c.anim is not None and 3000 <= c.anim < 4000
                if (swinging and a.mode == "가") or in_cell(c, p, r_, ang) or s.cam_yaw is None:
                    pad.move(0.0, 0.0)
                    moving_since = None
                else:
                    tx, tz = cell_point(c, r_, ang)
                    if nm.floor_at(tx, tz, p.gy if getattr(p, "gy", None) is not None else p.y) is None:
                        tx, tz = cell_point(c, r_, -ang)  # its right side has no floor → its left
                    moving_since = moving_since or time.time()
                    pad.move(*mv.stick_to(s, tx, tz, 1.0))
                time.sleep(0.03)
            emit("cell", cell=name, phase="end", rows=rec.rows - n0, secs=round(time.time() - tc, 1))
        result = f"rows {rec.rows}"
    except KeyboardInterrupt:
        result = "ctrl-c"
    finally:
        pad.neutral()
        rec.close()
        s = mv.snap(40.0)
        near = s is not None and any(x.npc_param == DEMON and math.hypot(x.x - s.player.x, x.z - s.player.z) < 20.0
                                     for x in s.chars)
        if not near:                                       # 데몬 옆에서 끄면 서 있는 채로 죽음 — 그땐 켜 둔 채 끝내고, 세이브를 되돌린 뒤 끈다
            tm.set_dbg(tm.DBG_PLAYER_NO_DEAD, bool(nd0))
            tm.set_dbg(tm.DBG_ALL_NO_DEAD, bool(and0))
        emit("end", result=result, rows=rec.rows, secs=round(time.time() - t0, 1),
             nodead_now=[tm.get_dbg(tm.DBG_PLAYER_NO_DEAD), tm.get_dbg(tm.DBG_ALL_NO_DEAD)])
        print(f"RESULT demon zones: {result} · {zpath}")
        zf.close()
        pad.close()
        lock.release()


if __name__ == "__main__":
    main()
