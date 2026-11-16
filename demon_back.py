"""Asylum Demon stage 2 — get behind it and hit after its swings (MoKa 11-16 M1116-10 "보드 확인 하고 2단계 진행해줘";
[cloud] board c4a93727 post 2bc22464, built on stage 1 = demon_zones.py · data/samples/demon_zones_20261116).

    python demon_back.py [--hold-s 180] [--hold-cw-s 60] [--strike-s 900] [--gaps 100] [--limit 1200]

Offline drill only — game-memory writes (CLAUDE.md: offline use only, MoKa asked for it): ChrDbg PlayerNoDead + AllNoDead,
our HP refilled under REFILL, the demon's HP written back to max under DEMON_REFILL (its damage is read from its HP first).
Start: the save before its upper fog wall (backup-20260929-070944-asylum-test-before-demon-fog) or on the arena floor.
No roll, no guard, no lock-on: walk / sprint and R1 only.

Phases
  hold     no R1. Circle to its back the shorter way (the old asylum._demon_move way: wide WIDE_R until behind, then in to
           HOLD_R), run out on 3008. Then hold-cw: the same but always circling one way (+ = its right → its back).
           ("데몬이 도는 반대쪽" would cut across its front, so the comparison is one-way vs shorter-way.)
  gate     share of its hit-window starts with us ≥ BACK_DEG behind, over both hold phases. Under GATE_BACK → stop and report.
  strike   the same moves, plus R1 inside a GAP (below) when every condition holds.

The answer table ([cloud] 2bc22464 draft; values fixed here before the run from stage 1 + tae_turn.json c2232):
  usual            behind (≥ BACK_DEG off its facing) at HOLD_R_LO..HOLD_R_HI from its centre (2.5 m inside calls 3008).
  3008 starts      out to SLAM_OUT from its centre until its last hit window ends (tae 4.1 s), then back in and hit in its gap.
  GAP              from the anim's last hit-window end to the end of the "disable turning" (flag 7) span holding it (tae_turn).
                   3004 1.30–2.77 · 3005 1.80–3.20 · 3006 1.87–3.73 · 3003 1.73–3.00 · 3008 4.10–6.90 · 3012 2.10–3.97 s.
  3002 · 3011      chain heads (AI: 80 % 3002→3011→3012): their gap counts only if the anim is still the same CHAIN_WAIT after
                   their last hit (no follow-up came); otherwise wait for 3012's gap.
  other attacks    no hit, keep the spot, record only.
  hit only when    in a GAP · at least SWING_ONE left · within HIT_R of its centre · ≥ SIDE_DEG off its facing · not 3008 before
                   its hit. Two R1 when at least SWING_TWO left (and stamina), else one.

Records (data/runs/<run>.back.jsonl), on top of demon_zones.ZoneRec's "win" / "attack" / "hpdrop" rows:
  "gap"    one per gap: anim, open / close (s from its anim start), angle · distance at open and at close, R1 press times,
           damage dealt, HP we lost from the gap open to the end of the next attack's first hit window (or GAP_TAIL_S),
           used or why not (front · far · slam · busy · no_time · chain_cut · record_only).
  "slam"   one per 3008: distance at its start, at its first hit window, hit or not, did we hit in its gap.
  "zone"   seconds spent behind · side · front per phase, and every behind stay's length.
  "demon_hp" its HP before / after a refill; "phase", "end".
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import demon_zones as DZ

DEMON = DZ.DEMON
BACK_DEG = 120.0         # "behind" (stage 1: nothing but 3008 hit from here, 0 / 23)
SIDE_DEG = 60.0          # hit only this far off its facing or more (front = most attacks hit about half the time)
HOLD_R_LO, HOLD_R, HOLD_R_HI = 2.7, 3.0, 3.5   # behind: stay in this band (2.5 m inside → 3008 start distance median 2.4 m)
WIDE_R = 5.5             # not behind yet: circle at this radius (asylum.DEMON_WIDE_R — [MoKa] "뒤로 크게 돌았어야 했어")
ORBIT_STEP = 45.0        # deg further round per tick while circling (asylum.DEMON_ORBIT_STEP)
HIT_R = 3.5              # R1 only within this of its centre (asylum.DEMON_HIT_R: two recordings of MoKa hit at 2.0–3.5 m)
SLAM = 3008
SLAM_OUT = 5.0           # run out past 4.5 m (stage 1: ≥ 3.2 m only 63 or nothing; one 63 at 4.0 m)
SLAM_HIT_END = 4.1       # tae c2232 3008 last hit window end
CHAIN_HEADS = {3002, 3011}
CHAIN_WAIT = 0.7         # s past a chain head's last hit with no new anim → its gap counts
STRIKE_AFTER = {3003, 3004, 3005, 3006, 3008, 3012} | CHAIN_HEADS
SWING_ONE = 0.7          # s of gap left to start one light (startup + active of a light ≈ 0.5–0.6 s; the rest overlaps)
SWING_TWO = 1.6          # … two lights
SPRINT_M = 1.2
GAP_TAIL_S = 6.0         # a gap's "HP lost after" stops here if no next attack window ends first
GATE_BACK = 1 / 3        # [cloud] 2bc22464: under this share of window starts behind → stop before hitting
REFILL = 0.4
DEMON_REFILL = 0.4
STUCK_S, STUCK_M = 6.0, 0.3


def gap_of(entry: dict) -> tuple[float, float] | None:
    """(open, close) s from the anim start: its last hit-window end → end of the flag-7 ("disable turning") span holding it."""
    hits = entry.get("hit") or []
    if not hits:
        return None
    h_end = max(h[1] for h in hits)
    spans = sorted((f[0], f[1]) for f in entry.get("flags", []) if f[2] == 7 and f[1] > h_end and f[0] <= h_end + 0.3)
    return (round(h_end, 4), round(spans[0][1], 4)) if spans else None


def load_gaps(path="data/gamefiles/tae_turn.json") -> dict[int, tuple[float, float]]:
    with open(path, encoding="utf-8") as f:
        m = json.load(f)["models"]["c2232"]
    return {int(a): g for a, e in m.items() if (g := gap_of(e)) is not None}


def band(off: float) -> str:
    o = abs(off)
    return "back" if o >= BACK_DEG else "side" if o >= SIDE_DEG else "front"


def hold_target(c, p, way: str) -> tuple[float, float, float]:
    """(x, z, r) to steer to this tick. way 'short' = the shorter way round to its back, 'cw' = always round its right side."""
    dx, dz = p.x - c.x, p.z - c.z
    r = math.hypot(dx, dz) or 1e-6
    fwd = (c.heading or 0.0) + math.pi                   # world yaw of its facing
    back = fwd + math.pi
    cur = math.atan2(dx, dz)
    diff = (back - cur + math.pi) % (2 * math.pi) - math.pi
    if abs(math.degrees(diff)) <= 180.0 - BACK_DEG:      # behind already: slide toward right behind, keep the band
        ang = cur + math.copysign(min(abs(diff), math.radians(30.0)), diff)
        rr = min(max(r, HOLD_R_LO), HOLD_R_HI) if HOLD_R_LO <= r <= HOLD_R_HI else HOLD_R
    else:
        sign = math.copysign(1.0, diff) if way == "short" else 1.0   # 'cw': always the same way round (world angle grows)
        ang = cur + sign * min(abs(diff), math.radians(ORBIT_STEP))
        rr = WIDE_R
    return c.x + math.sin(ang) * rr, c.z + math.cos(ang) * rr, rr


class BackPlan:
    """Pure: gap bookkeeping and the hit decision (tests/demon_back_test.py). feed() every snapshot; decide() says what to do."""

    def __init__(self, emit, gaps: dict):
        self.emit, self.gaps = emit, gaps
        self.anim, self.anim_t0, self.raw = None, None, None
        self.gap = None                    # open gap dict
        self.pend = []                     # closed gaps waiting for their "HP lost after"
        self.slam = None
        self.n_gaps = 0
        self.hp_prev = None

    def feed(self, now: float, p, c, at) -> None:
        hp = p.hp
        lost = max(0, (self.hp_prev or hp) - hp)
        self.hp_prev = hp
        for g in self.pend + ([self.gap] if self.gap else []):
            g["lost_after"] += lost
        if self.slam is not None:
            self.slam["lost"] += lost
        a = -1 if c is None or c.anim is None else c.anim
        new = 3000 <= a < 4000 and a != self.raw          # the id lingers after the move — a change starts a new one
        self.raw = a
        if c is not None and at is not None and 3000 <= a < 4000 and new:
            self.anim_t0 = now - at
        if new and self.gap is not None:                 # the next anim came while the gap was open
            self._close(now, p, c, "chain_cut" if self.gap["anim"] in CHAIN_HEADS else None)
        if new:
            for g in self.pend:                          # the next attack started: its first hit-window end closes "lost after"
                if g.get("next_anim") is None:
                    g["next_anim"], g["next_t0"] = a, self.anim_t0
            if self.slam is not None:
                self._slam_out()
            if a == SLAM and c is not None:
                self.slam = {"d_start": round(math.hypot(p.x - c.x, p.z - c.z), 2), "d_hit": None, "lost": 0,
                             "t0": self.anim_t0, "struck": False}
            if a in self.gaps:
                o, e = self.gaps[a]
                if a in CHAIN_HEADS:
                    o = o + CHAIN_WAIT
                self.gap = {"anim": a, "open_s": round(o, 3), "close_s": e, "t_open": self.anim_t0 + o,
                            "t_close": self.anim_t0 + e, "opened": False, "presses": [], "dmg": 0, "lost_after": 0,
                            "why": None if a in STRIKE_AFTER else "record_only"}
        if new:
            self.anim = a
        if self.slam is not None and c is not None and at is not None and a == SLAM and self.slam["d_hit"] is None and at >= 3.7:
            self.slam["d_hit"] = round(math.hypot(p.x - c.x, p.z - c.z), 2)
        g = self.gap
        if g is not None and c is not None:
            if not g["opened"] and now >= g["t_open"]:
                g["opened"] = True
                g["off_open"], g["d_open"] = round(DZ.signed_off(c, p)), round(math.hypot(p.x - c.x, p.z - c.z), 2)
                g["lost_after"] = 0                      # count from the gap open
            if now >= g["t_close"]:
                self._close(now, p, c, None)
        keep = []
        for g in self.pend:
            na = g.get("next_anim")
            first_end = None
            if na is not None:
                ws = DZ_WIN.get(na)
                first_end = g["next_t0"] + (ws[0][1] + DZ.HIT_S if ws else 0.0)
            if (first_end is not None and now >= first_end) or now - g["t_close"] > GAP_TAIL_S:
                self._emit_gap(g)
            else:
                keep.append(g)
        self.pend = keep

    def _close(self, now, p, c, why) -> None:
        g, self.gap = self.gap, None
        if not g["opened"]:
            g.update(off_open=None, d_open=None, why=g["why"] or why or "cut_before_open", lost_after=0)
        if c is not None:
            g["off_close"], g["d_close"] = round(DZ.signed_off(c, p)), round(math.hypot(p.x - c.x, p.z - c.z), 2)
        if why and not g["presses"]:
            g["why"] = g["why"] or why
        self.pend.append(g)

    def _emit_gap(self, g) -> None:
        self.n_gaps += 1
        if not g["presses"] and g["why"] is None:
            g["why"] = g.get("skip") or "unknown"
        self.emit("gap", **{k: v for k, v in g.items() if k not in ("t_open", "t_close", "opened", "next_t0")},
                  used=bool(g["presses"]))

    def _slam_out(self) -> None:
        s, self.slam = self.slam, None
        self.emit("slam", d_start=s["d_start"], d_hit=s["d_hit"], hit=s["lost"] > 0, lost=s["lost"], struck=s["struck"])

    def slam_running(self, now: float) -> bool:
        return self.slam is not None and self.anim == SLAM and self.slam["t0"] is not None and now < self.slam["t0"] + SLAM_HIT_END + 0.1

    def decide(self, now: float, p, c, my_busy: bool) -> tuple[str, int]:
        """('hit', n) or ('no', 0). Notes on the open gap why it wasn't used (the last reason seen wins)."""
        g = self.gap
        if g is None or not g["opened"] or g["why"] == "record_only" or c is None:
            return "no", 0
        left = g["t_close"] - now
        off, d = abs(DZ.signed_off(c, p)), math.hypot(p.x - c.x, p.z - c.z)
        skip = ("no_time" if left < SWING_ONE else "front" if off < SIDE_DEG else "far" if d > HIT_R
                else "slam" if self.slam_running(now) else "busy" if my_busy else None)
        if skip:
            g["skip"] = skip
            return "no", 0
        return "hit", 2 if left >= SWING_TWO and (p.sp or 0) >= 40 else 1

    def struck(self, now: float, dmg: int) -> None:
        if self.gap is not None:
            self.gap["presses"].append(round(now - self.gap["t_open"], 2))
            self.gap["dmg"] += max(0, dmg)
            if self.gap["anim"] == SLAM and self.slam is not None:
                self.slam["struck"] = True

    def close(self) -> None:
        if self.gap is not None:
            self.gap["why"] = self.gap["why"] or "end"
            self.pend.append(self.gap)
            self.gap = None
        for g in self.pend:
            self._emit_gap(g)
        self.pend = []
        if self.slam is not None:
            self._slam_out()


DZ_WIN: dict = {}          # anim → hit windows (filled in main from tae_turn; tests set it)


class ZoneTime:
    """Seconds behind / side / front and the length of every behind stay."""

    def __init__(self):
        self.t = {"back": 0.0, "side": 0.0, "front": 0.0}
        self.stays, self.in_back, self.last = [], None, None

    def tick(self, now: float, c, p) -> None:
        if c is None:
            self.last = None
            return
        b = band(DZ.signed_off(c, p))
        if self.last is not None:
            self.t[b] += now - self.last
        self.last = now
        if b == "back" and self.in_back is None:
            self.in_back = now
        elif b != "back" and self.in_back is not None:
            self.stays.append(round(now - self.in_back, 2))
            self.in_back = None

    def summary(self, now: float) -> dict:
        if self.in_back is not None:
            self.stays.append(round(now - self.in_back, 2))
            self.in_back = None
        tot = sum(self.t.values()) or 1e-6
        st = sorted(self.stays)
        return {"secs": {k: round(v, 1) for k, v in self.t.items()}, "share": {k: round(v / tot, 3) for k, v in self.t.items()},
                "stays": len(st), "stay_median": st[len(st) // 2] if st else None, "stay_max": st[-1] if st else None,
                "stay_list": st}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hold-s", type=float, default=180.0)
    ap.add_argument("--hold-cw-s", type=float, default=60.0)
    ap.add_argument("--strike-s", type=float, default=900.0)
    ap.add_argument("--gaps", type=int, default=100)
    ap.add_argument("--limit", type=float, default=1200.0)
    ap.add_argument("--skip-gate", action="store_true", help="hit even under GATE_BACK (not used in the M1116-10 run)")
    a = ap.parse_args()

    import control, env, navmesh, track
    from botlock import BotLock
    from dsr_telemetry import OFF_HP
    from run import Log
    from souls import asylum as AS, moves as M, parry as PARRY, weapons
    from souls.field import Field
    from souls.watch import Escape

    log = Log("demon-back")
    bpath = str(log.path).replace(".jsonl", ".back.jsonl")
    bf = open(bpath, "a", encoding="utf-8")
    t0 = time.time()

    def emit(kind, **kw):
        d = {"t": round(time.time() - t0, 3), "kind": kind, "phase": phase[0], **kw}
        bf.write(json.dumps(d, ensure_ascii=False) + "\n"); bf.flush()
        if kind == "win":
            log(f"   판정 {kw['anim']}#{kw['win']} 정면에서 {kw['off']:+d}° · {kw['d']} m → "
                f"{'맞음 −' + str(kw['lost']) if kw['lost'] else '안 맞음'}")
        elif kind == "gap":
            log(f"   틈 {kw['anim']} {'씀 R1×' + str(len(kw['presses'])) + ' 피해 ' + str(kw['dmg']) if kw['used'] else '안 씀 (' + str(kw['why']) + ')'}"
                f" · 열릴 때 {kw.get('off_open')}° {kw.get('d_open')} m · 그 뒤 잃은 HP {kw['lost_after']}")
        elif kind not in ("attack", "hpdrop"):
            log(f"   [{kind}] {kw}")

    phase = ["setup"]
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
    mv.guard_ok = False
    esc = Escape(pad, [nm], log=log, events=log.event)
    esc.quit_ok = False
    fld = Field(mv, w, esc, bonfires=[], log=log, events=log.event)
    asy = AS.Asylum(fld, nm, log=log, events=log.event)
    win = PARRY.load_windows()
    with open("data/gamefiles/tae_turn.json", encoding="utf-8") as f:
        DZ_WIN.update({int(k): v["hit"] for k, v in json.load(f)["models"]["c2232"].items() if v.get("hit")})
    rec = DZ.ZoneRec(emit, lambda npc, anim: PARRY.windows_for(win, npc, anim))
    plan = BackPlan(emit, load_gaps())
    nd0, and0 = tm.get_dbg(tm.DBG_PLAYER_NO_DEAD), tm.get_dbg(tm.DBG_ALL_NO_DEAD)
    tm.set_dbg(tm.DBG_PLAYER_NO_DEAD, True)
    tm.set_dbg(tm.DBG_ALL_NO_DEAD, True)
    emit("start", nodead_before=[nd0, and0], nodead_now=[tm.get_dbg(tm.DBG_PLAYER_NO_DEAD), tm.get_dbg(tm.DBG_ALL_NO_DEAD)],
         weapon=getattr(w, "name", None), gaps={k: v for k, v in plan.gaps.items() if k in STRIKE_AFTER})
    result = "?"
    zt = ZoneTime()
    win_starts = {"hold": [], "hold-cw": [], "strike": []}
    rec_emit = rec.emit

    def rec_emit2(kind, **kw):
        if kind == "win" and kw.get("win") == 0:
            win_starts.setdefault(phase[0], []).append(band(kw["off"]))
        rec_emit(kind, **kw)
    rec.emit = rec_emit2
    demon_seen_hp = None
    try:
        s = mv.snap(40.0)
        if s is None:
            raise SystemExit("스냅숏 없음")
        if s.player.y > 205.0:                            # upper floor → fog → off the ledge (demon_zones, no plunge)
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
        emit("grip", two_hand=asy._two_hand("데몬 2단계"))   # 과거 _demon과 같게 양손 약공 ([cloud] 2bc22464)
        t_end = t0 + a.limit
        plan_phases = [("hold", a.hold_s, "short", False), ("hold-cw", a.hold_cw_s, "cw", False),
                       ("strike", a.strike_s, "short", True)]
        for name, secs, way, hitting in plan_phases:
            if time.time() > t_end:
                break
            if hitting:
                ws = win_starts["hold"] + win_starts["hold-cw"]
                share = sum(1 for b in ws if b == "back") / len(ws) if ws else 0.0
                emit("gate", window_starts=len(ws), back=sum(1 for b in ws if b == "back"), share=round(share, 3),
                     need=round(GATE_BACK, 3))
                if share < GATE_BACK and not a.skip_gate:
                    result = f"gate: 판정 시작 때 뒤 {share:.0%} < {GATE_BACK:.0%} — 치기 안 함"
                    break
            phase[0] = name
            zt = ZoneTime()
            emit("phase", name=name, way=way, hitting=hitting)
            tp, moved_at, last_pos = time.time(), time.time(), None
            while time.time() - tp < secs and time.time() < t_end and not (hitting and plan.n_gaps >= a.gaps):
                s = mv.snap(40.0)
                if s is None:
                    time.sleep(0.02); continue
                now = time.time()
                p = s.player
                c = AS.Asylum._demon_c(s) or next((x for x in s.chars if x.npc_param == DEMON), None)
                at = None if c is None else tm.anim_time(c.ptr)
                rec.tick(now, p, c, at)
                plan.feed(now, p, c, at)
                zt.tick(now, c, p)
                if p.max_hp and p.hp < REFILL * p.max_hp:
                    tm.set_hp(p.max_hp)
                    emit("refill", hp=p.hp, to=p.max_hp)
                if c is not None and c.max_hp and c.hp < DEMON_REFILL * c.max_hp:
                    tm.pm.write_int(c.ptr + OFF_HP, c.max_hp)
                    emit("demon_hp", before=c.hp, to=c.max_hp)
                if c is not None and demon_seen_hp is None:
                    demon_seen_hp = c.hp
                    emit("demon_hp", seen=c.hp, max=c.max_hp)
                if tm.get_dbg(tm.DBG_PLAYER_NO_DEAD) != 1 or tm.get_dbg(tm.DBG_ALL_NO_DEAD) != 1 or p.hp <= 0:
                    result = "무적 이상 — 멈춤"
                    raise StopIteration
                if c is None:
                    pad.sprint(False); pad.neutral(); time.sleep(0.05); continue
                pos = (round(p.x, 1), round(p.z, 1))
                if last_pos is None or math.hypot(p.x - last_pos[0], p.z - last_pos[1]) > STUCK_M:
                    last_pos, moved_at = (p.x, p.z), now
                elif now - moved_at > STUCK_S and c.anim not in range(3000, 4000):
                    result = f"끼임 — {pos}에서 {STUCK_S:.0f} s 못 움직임"
                    raise StopIteration
                if hitting:
                    busy = p.anim is not None and p.anim not in (-1,) and not (0 <= p.anim < 1000)
                    act, n = plan.decide(now, p, c, busy)
                    if act == "hit":
                        pad.sprint(False)
                        if mv.face(s, c, deg=35.0):
                            hp0 = c.hp
                            hit = mv.light(s, c, n=n, sp_second=40)
                            plan.struck(now, hit.dmg)
                            emit("strike", anim=plan.anim, n=n, presses=hit.presses, dmg=hit.dmg, taken=hit.taken,
                                 demon_hp=[hp0, hp0 - hit.dmg], off=round(DZ.signed_off(c, p)),
                                 d=round(math.hypot(p.x - c.x, p.z - c.z), 2))
                        time.sleep(0.02)
                        continue
                    if plan.gap is not None and plan.gap["opened"] and plan.gap["why"] is None \
                            and math.hypot(p.x - c.x, p.z - c.z) > HIT_R and plan.gap["t_close"] - now > SWING_ONE + 0.5:
                        tx, tz = DZ.cell_point(c, HOLD_R, DZ.signed_off(c, p))   # in straight at the current angle
                        pad.sprint(math.hypot(tx - p.x, tz - p.z) > SPRINT_M)
                        pad.move(*mv.stick_to(s, tx, tz, 1.0))
                        time.sleep(0.03)
                        continue
                if plan.slam_running(now):
                    dx, dz = p.x - c.x, p.z - c.z
                    r = math.hypot(dx, dz) or 1e-6
                    if r < SLAM_OUT:
                        tx, tz = c.x + dx / r * (SLAM_OUT + 0.5), c.z + dz / r * (SLAM_OUT + 0.5)
                        pad.sprint(True)
                        pad.move(*mv.stick_to(s, tx, tz, 1.0))
                    else:
                        pad.sprint(False); pad.move(0.0, 0.0)
                    time.sleep(0.03)
                    continue
                off = abs(DZ.signed_off(c, p))
                d = math.hypot(p.x - c.x, p.z - c.z)
                if off >= 150.0 and HOLD_R_LO <= d <= HOLD_R_HI:
                    pad.sprint(False); pad.move(0.0, 0.0)
                else:
                    tx, tz, _ = hold_target(c, p, way)
                    if nm.floor_at(tx, tz, p.y) is None:
                        tx, tz, _ = hold_target(c, p, "cw" if way == "short" else "short")
                    pad.sprint(math.hypot(tx - p.x, tz - p.z) > SPRINT_M)
                    pad.move(*mv.stick_to(s, tx, tz, 1.0))
                time.sleep(0.03)
            emit("zone", **zt.summary(time.time()), window_starts={b: win_starts.get(name, []).count(b)
                                                                   for b in ("back", "side", "front")})
        if result == "?":
            result = f"gaps {plan.n_gaps}"
    except StopIteration:
        pass
    except KeyboardInterrupt:
        result = "ctrl-c"
    finally:
        pad.sprint(False)
        pad.neutral()
        rec.close()
        plan.close()
        s = mv.snap(40.0)
        near = s is not None and any(x.npc_param == DEMON and math.hypot(x.x - s.player.x, x.z - s.player.z) < 20.0
                                     for x in s.chars)
        if not near:                                       # 데몬 옆에서 끄면 서 있는 채로 죽음 — 켜 둔 채 끝내고, 세이브를 되돌린 뒤 끈다
            tm.set_dbg(tm.DBG_PLAYER_NO_DEAD, bool(nd0))
            tm.set_dbg(tm.DBG_ALL_NO_DEAD, bool(and0))
        emit("end", result=result, gaps=plan.n_gaps, secs=round(time.time() - t0, 1),
             nodead_now=[tm.get_dbg(tm.DBG_PLAYER_NO_DEAD), tm.get_dbg(tm.DBG_ALL_NO_DEAD)])
        print(f"RESULT demon back: {result} · {bpath}")
        bf.close()
        pad.close()
        lock.release()


if __name__ == "__main__":
    main()
