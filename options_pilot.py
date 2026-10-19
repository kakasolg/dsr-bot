"""Player options vs one foe attack — feasibility pilot (docs/design-player-options.md step 1, MoKa 2026-10-17: "1번하고 2번으로
진행해줘" = stop the window-end probe, run this pilot instead).

Question: with the same input at the same moment, do the options give consistent, different outcomes against c2540's 3000?
If yes, state values (anim ID, age, distance) are enough to choose — for this foe, this anim, these options and this τ only.

  python options_pilot.py run [secs=900] --refill 500 793      [win]: pre-record + precheck → the pilot record
  python options_pilot.py check FILE [FILE ...]                 the verdict (several records are pooled)

Setup as probe 3 / 4 (docs/tae-verify.md B-4): one awake sword hollow 254010, nothing else hostile within 25 m. At the target's first
3000 read the next option in turn is chosen; at age τ (first read past it) its pad input goes out:
  stand        nothing (control: probe 3 standing at 0.85 m was hit 12 / 12)
  circle_cw    stick along the tangent around the foe, clockwise seen from above in world x-z (x right, z up), re-aimed every
  circle_ccw   read for CIRCLE_S; counter-clockwise. Which of these is "the foe's right" is read off the record (`turn`), not assumed.
  roll_cw      stick on the clockwise tangent + B (one roll), stick let go after ROLL_HOLD
No lock-on (the bot does not use it). After each 3000 the player is warped back to the first rep's spot (game-memory write, offline
only) so every rep starts from the same floor; HP refill as probe 3. Every read is written from the 3000's start to TAIL reads after.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import tae_verify as V

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OPTIONS = ("stand", "circle_cw", "circle_ccw", "roll_cw")
TAU = 0.6               # s after the 3000's first read — before the 0.89 s contact (probe 3)
CIRCLE_S = 1.0          # how long the circle stick is held (past the TAE window end 1.033 s)
ROLL_HOLD = 0.15        # stick held this long after B so the roll takes its direction
INPUT_LATE = 0.05       # the input went out later than τ + this → excluded
TAIL = 10
HOME_R = 0.5
ROLL_ANIMS = range(700, 800)   # player roll animations (souls/moves.py roll_toward)
N_MIN = 16              # valid reps per option for a verdict (of the planned 20)
HALF_DIFF = 0.3         # an option is "stable" if its two halves' hit rates differ by at most this (proposed, MoKa may change)
PAIR_P = 0.01           # a pair "differs clearly" at Fisher exact two-sided p below this (proposed)
STAND_MIN = 0.8         # stand below this hit rate → the setup is not probe 3's (reported, not a verdict on the options)


def _tangent(px, pz, fx, fz, cw: bool) -> tuple[float, float]:
    """Unit tangent around the foe at the player, x right / z up: clockwise from (0, 1) goes to (1, 0)."""
    vx, vz = px - fx, pz - fz
    n = math.hypot(vx, vz) or 1e-6
    return (vz / n, -vx / n) if cw else (-vz / n, vx / n)


class PadAct:
    """The game side of the pilot: pad inputs (control.Pad) and the home warp. Game-memory write (warp), offline only."""

    def __init__(self, tm, pad, world_to_stick, yaw_offset: float, flip_x: bool):
        self.tm, self.pad, self.w2s, self.yaw_offset, self.flip_x = tm, pad, world_to_stick, yaw_offset, flip_x
        self.home = None

    def _stick(self, s, ptr, cw: bool):
        foe = next((c for c in s.chars if c.ptr == ptr), None)
        if foe is None or getattr(s, "cam_yaw", None) is None:
            return None
        dx, dz = _tangent(s.player.x, s.player.z, foe.x, foe.z, cw)
        return self.w2s(dx, dz, s.cam_yaw, self.yaw_offset, self.flip_x)

    def start(self, opt: str, s, ptr) -> dict:
        if self.home is None:
            self.home = (s.player.x, s.player.y, s.player.z, s.player.heading or 0.0)
        if opt == "stand":
            return {"in": "none"}
        st = self._stick(s, ptr, opt.endswith("_cw"))
        if st is None:
            return {"in": "no_stick"}
        self.pad.move(*st)
        if opt.startswith("roll"):
            self.pad.dodge()
        return {"in": opt, "stick": [round(st[0], 3), round(st[1], 3)]}

    def steer(self, opt: str, s, ptr) -> None:
        st = self._stick(s, ptr, opt.endswith("_cw"))
        if st is not None:
            self.pad.move(*st)

    def stop(self) -> None:
        self.pad.move(0.0, 0.0)

    def tick(self) -> None:
        self.pad.release_due()

    def rehome(self, s) -> dict:
        if self.home is None:
            return {}
        hx, hy, hz, hh = self.home
        if V._dxz((s.player.x, s.player.y, s.player.z), (hx, hy, hz)) <= HOME_R and abs(s.player.y - hy) <= V.FALL_DY:
            return {}
        self.tm.pos_warp(hx, hy, hz, hh)
        return {"home": [round(hx, 3), round(hy, 3), round(hz, 3)]}

    def close(self) -> None:
        try:
            self.pad.neutral("options_pilot end")
        except Exception:
            self.stop()


class OptionGate:
    """record3 hook. At the target's first `anim` read (after a read in another anim): next option, `rep` / `opt` on the line.
    At age ≥ τ: the input (`pad` = what was sent, `pad_t` = when). Circles re-aim every read until CIRCLE_S; a roll lets go after
    ROLL_HOLD. When the run ends: stick neutral, `rep_end`, then the home warp (`home`) on the next read with the player away."""

    def __init__(self, act, options=OPTIONS, tau=TAU, anim=V.P3_ANIM, target=V.P3_TARGET, iso_r=V.ISO_R, clock=time.perf_counter):
        self.act, self.options, self.tau, self.anim, self.target, self.iso_r, self.clock = act, list(options), tau, anim, target, iso_r, clock
        self.k, self.active, self.ptr, self.opt, self.t0, self.sent, self.stopped = 0, False, None, None, None, None, False
        self.prev, self.tail, self.need_home = {}, 0, False

    def dense(self) -> bool:
        return self.active or self.tail > 0

    def __call__(self, t: float, foes: list[dict], line: dict, s=None) -> bool:
        self.act.tick()
        event = False
        if self.tail > 0 and not self.active:
            self.tail -= 1
        if self.active:
            mine = next((x for x in foes if x["ptr"] == self.ptr), None)
            if mine is None or mine["anim"] != self.anim:
                self.act.stop()
                line.update(rep_end=round(self.clock(), 5))
                self.active, self.tail, self.need_home, event = False, TAIL, True, True
            elif self.sent is None and t - self.t0 >= self.tau:
                line.update(pad=self.act.start(self.opt, s, self.ptr), pad_t=round(self.clock(), 5))
                self.sent, event = t, True
            elif self.sent is not None and not self.stopped:
                hold = CIRCLE_S if self.opt.startswith("circle") else ROLL_HOLD if self.opt.startswith("roll") else 0.0
                if t - self.sent >= hold:
                    self.act.stop()
                    self.stopped = True
                    line.update(pad_stop=round(self.clock(), 5))
                elif self.opt.startswith("circle"):
                    self.act.steer(self.opt, s, self.ptr)
        else:
            tg = [f for f in foes if f["npc"] in self.target and f["d"] <= self.iso_r]
            f = tg[0] if len(tg) == 1 else None
            if f is not None and f["anim"] == self.anim and self.prev.get(f["ptr"], self.anim) != self.anim and "rep_end" not in line:
                self.opt = self.options[self.k % len(self.options)]
                self.k += 1
                self.active, self.ptr, self.t0, self.sent, self.stopped = True, f["ptr"], t, None, False
                line.update(rep=self.k, opt=self.opt, tau=self.tau)
                event = True
            elif self.need_home and self.tail == 0 and s is not None:
                home = self.act.rehome(s)
                if home:
                    line.update(home)
                    event = True
                self.need_home = False
        self.prev = {x["ptr"]: x["anim"] for x in foes}
        return event

    def close(self) -> None:
        self.act.close()


def _ang(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def fisher_p(a: int, n1: int, b: int, n2: int) -> float:
    """Two-sided Fisher exact p for hits a / n1 vs b / n2."""
    k, n = a + b, n1 + n2
    pr = lambda x: math.comb(n1, x) * math.comb(n2, k - x) / math.comb(n, k)
    lo, hi = max(0, k - n2), min(k, n1)
    p0 = pr(a)
    return min(1.0, sum(pr(x) for x in range(lo, hi + 1) if pr(x) <= p0 * (1 + 1e-9)))


def rep_rows(lines: list[dict], anim: int = V.P3_ANIM, target: tuple = V.P3_TARGET, iso_r: float = V.ISO_R) -> list[dict]:
    """One row per rep. Excluded (reasons kept, first one counted): start not seen / bound > MAX_GAP, not isolated in any read of
    the run, run open, possible same-ID restart (`tae_verify.restart_reason`: anim time broken, or > 1.5 × median closed run in records
    without anim time), refill or HP floor in the run, no input or input later
    than τ + INPUT_LATE, no stick (camera yaw unread), more than one HP drop. Per rep (reference): hit, damage, hit age, distance and
    foe-to-player angle at the hit, foe turn and player's angle moved around the foe (+ = clockwise) start → hit or run end, roll seen."""
    head, frames = V._frames(lines)
    runs = V.anim_runs(frames)
    closed = [r for rs in runs.values() for r in rs if r["anim"] == anim and r["start"] and r["end"]]
    lens = sorted((r["end"][0] + r["end"][1] - r["start"][0] - r["start"][1]) / 2 for r in closed)
    median = lens[len(lens) // 2] if lens else None
    drops = V._drops(frames)
    rows = []
    for i, fr in enumerate(frames):
        if "rep" not in fr:
            continue
        tg = V._near(fr, iso_r, target)[0]
        ptr = tg[0]["ptr"] if len(tg) == 1 else None
        r = V._run_at(runs.get(ptr, []), i) if ptr else None
        row = {"t": fr["t"], "rep": fr["rep"], "opt": fr["opt"], "tau": fr.get("tau")}
        why = []
        if r is None or r["start"] is None:
            row["reasons"] = ["start_unseen"]
            rows.append(row)
            continue
        i1 = r["i1"] if r["i1"] is not None else len(frames)
        seg = frames[r["i0"]:i1]
        st = r["start"]
        if st[1] - st[0] > V.MAX_GAP:
            why.append("start_gap")
        if any(len(V._near(x, iso_r, target)[0]) != 1 or V._near(x, iso_r, target)[1] for x in seg):
            why.append("not_isolated")
        if r["end"] is None:
            why.append("run_open")
        else:
            ln = (r["end"][0] + r["end"][1] - st[0] - st[1]) / 2
            row["run_len"] = round(ln, 4)
            if rr := V.restart_reason(seg, ptr, st, ln, median, len(lens)):
                why.append(rr)
        if any("refill" in x for x in seg):
            why.append("refill_in_run")
        if any(x["hp"] <= 1 for x in seg):
            why.append("hp_floor_in_run")
        sent = next((x for x in seg if "pad_t" in x), None)
        if sent is None:
            why.append("no_input")
        else:
            row["input_age"] = [round(sent["pad_t"] - st[1], 4), round(sent["pad_t"] - st[0], 4)]
            if sent["pad_t"] - st[1] > (row["tau"] or TAU) + INPUT_LATE:
                why.append("input_late")
            if sent["pad"].get("in") == "no_stick":
                why.append("no_stick")
        hs = [(j, lost) for j, lost in drops if r["i0"] < j <= i1 and j < len(frames)]
        if len(hs) > 1:
            why.append("multi_hit_in_run")
        foe = lambda x: next((f for f in x["foes"] if f["ptr"] == ptr), None)
        f0 = foe(seg[0])
        row["d_start"] = f0["d"] if f0 else None
        end_fr = frames[hs[0][0]] if hs else seg[-1]
        f1 = foe(end_fr)
        if hs:
            j, lost = hs[0]
            lo, hi = V._bounds(frames[j - 1], frames[j])
            row.update(hit=True, lost=lost, hit_age=[round(lo - st[1], 4), round(hi - st[0], 4)])
            if f1:
                row["d_hit"] = f1["d"]
                if f1.get("h") is not None and "x" in f1:
                    # the foe's facing vs the direction to the player (0 = straight ahead). Assumes the foe's heading has the
                    # player's convention: the body faces heading + π in atan2(dx, dz) (dsr_telemetry face(), souls/reflex.py)
                    to_p = math.atan2(end_fr["p"][0] - f1["x"], end_fr["p"][2] - f1["z"])
                    row["angle_hit"] = round(math.degrees(_ang(to_p - f1["h"] - math.pi)), 1)
        else:
            row["hit"] = False
        if f0 and f1 and f0.get("h") is not None and f1.get("h") is not None:
            row["foe_turn"] = round(math.degrees(_ang(f1["h"] - f0["h"])), 1)
        if f0 and f1 and "x" in f0 and "x" in f1:
            a0 = math.atan2(seg[0]["p"][0] - f0["x"], seg[0]["p"][2] - f0["z"])
            a1 = math.atan2(end_fr["p"][0] - f1["x"], end_fr["p"][2] - f1["z"])
            row["turn"] = round(math.degrees(_ang(a1 - a0)), 1)      # atan2(dx, dz) from +z toward +x: grows clockwise
        row["roll_seen"] = any(x.get("pa") in ROLL_ANIMS for x in seg)
        row["reasons"] = why
        rows.append(row)
    return rows


def summarize(rows: list[dict], tau: float = TAU, anim: int = V.P3_ANIM, target: tuple = V.P3_TARGET) -> dict:
    """Per option: valid / hits / rate / halves (in time order) / stable; Fisher p per pair; the verdict (rule: proposed)."""
    ok = [x for x in rows if not x["reasons"]]
    per = {}
    for o in sorted({x["opt"] for x in rows}, key=lambda o: OPTIONS.index(o) if o in OPTIONS else 99):
        v = [x for x in ok if x["opt"] == o]
        h = len(v) // 2
        a, b = v[:h], v[h:]
        rate = lambda xs: round(sum(x["hit"] for x in xs) / len(xs), 3) if xs else None
        per[o] = {"valid": len(v), "of": sum(1 for x in rows if x["opt"] == o), "hits": sum(x["hit"] for x in v), "rate": rate(v),
                  "halves": [[sum(x["hit"] for x in a), len(a)], [sum(x["hit"] for x in b), len(b)]],
                  "stable": bool(a and b) and abs(rate(a) - rate(b)) <= HALF_DIFF,
                  "roll_seen": sum(x["roll_seen"] for x in v),
                  "turn_median": sorted(x["turn"] for x in v if "turn" in x)[len(v) // 2] if any("turn" in x for x in v) else None}
    pairs = []
    names = list(per)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if per[a]["valid"] and per[b]["valid"]:
                pairs.append({"pair": [a, b], "p": round(fisher_p(per[a]["hits"], per[a]["valid"], per[b]["hits"], per[b]["valid"]), 5)})
    enough = all(per[o]["valid"] >= N_MIN for o in per) and len(per) >= 2
    if not enough:
        verdict = "표본 부족"
    elif not all(per[o]["stable"] for o in per):
        verdict = "흩어짐"          # the same input at the same moment gives scattered results → something outside state values matters
    elif any(p["p"] < PAIR_P for p in pairs):
        verdict = "상태값으로 갈림 (이 조건만)"
    else:
        verdict = "차이 없음"
    excluded: dict[str, int] = {}
    for x in rows:
        if x["reasons"]:
            excluded[x["reasons"][0]] = excluded.get(x["reasons"][0], 0) + 1
    stand = per.get("stand", {}).get("rate")
    return {"anim": anim, "target": list(target), "tau": tau, "age": "age_since_seen (play position not read)",
            "reps": len(rows), "valid": len(ok), "excluded": excluded, "per_option": per, "pairs": pairs,
            "stand_control": {"rate": stand, "ok": stand is not None and stand >= STAND_MIN},
            "rule": {"n_min": N_MIN, "half_diff": HALF_DIFF, "pair_p": PAIR_P, "status": "proposed (MoKa may change)"},
            "verdict": verdict, "rows": rows}


def run(secs: float, pre: float, refill, options: list, tau: float, force: bool, max_lines: int) -> None:
    import control
    import dsr_telemetry
    import nav
    from botlock import BotLock
    lock = BotLock()
    if not lock.acquire():
        raise SystemExit("봇이 돌고 있음 (data/bot.lock)")
    tm = dsr_telemetry.DSRTelemetry({})
    stamp = time.strftime('%Y%m%d_%H%M%S')
    header = {"probe": "options", "anim": V.P3_ANIM, "target": list(V.P3_TARGET), "iso_r": V.ISO_R, "refill": refill,
              "options": options, "tau": tau, "circle_s": CIRCLE_S, "roll_hold": ROLL_HOLD,
              "age": "age_since_seen (play position not read)", "tangent": "cw = clockwise from above, world x right / z up"}
    pre_out = V.SAMPLES / f"{stamp}_options-pre.jsonl"
    V.record3(tm, pre, pre_out, {**header, "pre": True}, refill=refill, max_lines=max_lines)
    pc = V.precheck([json.loads(l) for l in pre_out.read_text(encoding="utf-8").splitlines() if l.strip()], pre, secs, max_lines=max_lines)
    for c in pc["checks"]:
        print(f"  {'OK ' if c['ok'] else 'FAIL'} {c['check']:13} {c['detail']}")
    if not pc["ok"] and not force:
        print(f"예비 점검 실패 — 본 기록 안 함 ({pre_out}).")
        lock.release()
        return
    control.focus_game()
    pad = control.Pad()
    gate = OptionGate(PadAct(tm, pad, control.world_to_stick, nav.YAW_OFFSET, nav.FLIP_X), options, tau)
    out = V.SAMPLES / f"{stamp}_options.jsonl"
    try:
        r = V.record3(tm, secs, out, {**header, "precheck": pc["checks"], "forced": not pc["ok"]}, refill=refill,
                      max_lines=max_lines, gate=gate)
    finally:
        pad.close()
        lock.release()
    print(f"읽기 {r['reads']}번, 기록 {r['written']}줄 ({r['stopped']}), 3000 반복 {gate.k}번 → {out}\n"
          f"다음: python options_pilot.py check {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("secs", type=float, nargs="?", default=900.0)
    p.add_argument("--pre", type=float, default=5.0)
    p.add_argument("--refill", type=int, nargs=2, metavar=("BELOW", "TO"))
    p.add_argument("--options", default=",".join(OPTIONS))
    p.add_argument("--tau", type=float, default=TAU)
    p.add_argument("--force", action="store_true")
    p.add_argument("--max-lines", type=int, default=V.MAX_LINES)
    p = sub.add_parser("check")
    p.add_argument("files", type=Path, nargs="+")
    a = ap.parse_args()
    if a.cmd == "run":
        opts = [o for o in a.options.split(",") if o]
        bad = [o for o in opts if o not in OPTIONS]
        if bad:
            raise SystemExit(f"모르는 선택지 {bad} — {', '.join(OPTIONS)}")
        run(a.secs, a.pre, tuple(a.refill) if a.refill else None, opts, a.tau, a.force, a.max_lines)
        return
    rows, tau = [], TAU
    for f in a.files:     # several records pooled: exclusions are decided per record, the summary over all rows
        ls = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        tau = ls[0].get("tau", TAU) if ls and ls[0].get("kind") == "header" else TAU
        rows += [dict(x, file=f.name) for x in rep_rows(ls)]
    r = summarize(rows, tau)
    for x in r["rows"]:
        print(" ", x)
    print(json.dumps({k: v for k, v in r.items() if k != "rows"}, ensure_ascii=False, indent=1))


def check(lines: list[dict]) -> dict:
    head = lines[0] if lines and lines[0].get("kind") == "header" else {}
    return summarize(rep_rows(lines), head.get("tau", TAU))


if __name__ == "__main__":
    main()
