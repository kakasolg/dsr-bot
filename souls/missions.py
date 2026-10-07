"""Layer 5 — missions. Only decides which playbooks to use in what order. How to fight and walk lives in the lower layers.

Missions:
  burg_bonfire   Firelink Shrine → ramp group one at a time → top of stairs → bridge·passage → Undead Burg → merchant → light the Undead Burg bonfire and sit
  clear_ramp     ramp group only, one at a time (for testing)
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import nav

from . import moves as M
from .field import Field

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MAP_A, MAP_B = "m10_02_00_00", "m10_01_00_00"        # Firelink Shrine side / Undead Burg side navmesh
SPOTS = json.loads((DATA / "spots.json").read_text(encoding="utf-8"))
FIRELINK = SPOTS["firelink-bonfire"]
FIRELINK_ID = 1022960                                  # last bonfire ID (measured 2026-09-24, Firelink Shrine)
BURG_BONFIRE_ID = 1012962                              # Undead Burg bonfire (2026-09-24 confirmed by lighting it and sitting)
BURG_BONFIRE = (3.2, -10.0, -61.2)                     # Undead Burg bonfire (o0200_0002) — 42 m east of the merchant, 10 m up
BURG_BONFIRE_SIDE = (1.7, -10.02, -61.2)               # floor next to it
RAMP = json.loads((DATA / "enemy-map.json").read_text(encoding="utf-8"))["enemies"]   # 6 on the ramp, spawn spots right after resting
# Flat ground below the ramp — floor exists in all 16 directions at 3 m radius, nearest drop 4.0 m away (measured by hunt.py). Meet them here instead of fighting next to the cliff
RAMP_ARENA = (-30.0, -49.25, 29.0)
# Kill order (map numbers). #2 shield soldier goes last — its spot is too bad (west cliff + firebombs from the ledge above, user 2026-09-24:
# "Try doing the second one you go attack last", "That position is too bad"). Engaging there first took 275 in 1 s or fell off
RAMP_ORDER = [1, 3, 2, 5, 4, 6]      # 5 first (2026-09-26 user: start with two knives on the bomber)
# 2026-09-26 user: "Take out #1, #3 first, and throw daggers at the shield soldier only from a distance as far as where I threw — that's
# the distance firebombs don't reach". Both user demo runs (observe 083705·084654) were 1 → 3 → 2, and on the shield soldier, from flat ground (-30.3,-49.4,27.9)
# lock-on knives at 13.65·13.7 m both hit (85→51). The "#2 last" above was because closing in took 275 in 1 s,
# but waking it from afar and having it come to the flat ground means we don't fight at its spot. 4·5 order varied per demo (first run 5→4, second 4→5).
# Lure spot·distance set per enemy — #2 only from where the user threw, never closer than 13 m (field.lure's lure_at)
# hold: if the lure fails, don't walk to the shield soldier, hold that spot (user: "You have to hold the position where you killed the first enemy") — the bot
# was spotted every time at 8.8~9.1 m from the shield soldier, while the user killed #1·#3 at 12.3~17.7 m from it. max 14.5 → 15.0: stood a bit over 1 m
# off the throw spot, at 14.5 m, and refused to throw as 'too far' (094231)
RAMP_LURE_AT = {2: {"spot": (-30.35, -49.43, 27.91), "min": 13.0, "max": 15.0, "hold": True}}
# Upper ledge #4~#6 — exactly the throw spots from user demo 140708 (mid-ramp). Lock-on is a 3D radius from the character's feet
# (LockCamParam.chrLockRangeMaxRadius) — demo max 14.97 m (same height)·14.19 m (height diff +3.2) → only up to 14.5 m.
# knives: keep throwing until this many hits (don't stop even if it wakes). #5 died in two (75→31→0), #4·#6 came down after one to melee
RAMP_LURE_AT.update({
    5: {"spot": (-23.8, -43.5, 23.1), "min": 0.0, "max": 14.5, "knives": 2},
    4: {"spot": (-23.6, -42.4, 21.5), "min": 0.0, "max": 14.5, "knives": 1},
    6: {"spot": (-20.7, -40.5, 19.3), "min": 0.0, "max": 14.5, "knives": 1},
})
# Measured 2026-09-25: [3,1,…] (luring #3 first from the upper ledge at the same height) died 2 in 8 runs — #3's throw spot is the ledge beside #4·#5, so it got surrounded by three,
# and on the way the shield soldier chased it for 790. Starting from the flat ground below, [1,3,…] (10/10, median damage 282) is better — safer to let the upper-ledge ones come down one at a time
RAMP_SURVIVOR_R = 15.0   # a live ramp foe this close to a spawn of its type counts as a survivor (pass_ramp)
RAMP_RETRIES = 2         # …and the ramp is cleared again at most this many times before the mission stops
NO_LURE = {1}            # #1 is on a high spot: from afar it's blocked by rocks, up close it's already coming down (user 2026-09-24) — walk to the flat ground and it comes on its own
# Undead Burg 6 — exactly the order the user killed them (recording analysis, 2026-09-25): "Code it to kill in the order I kill"
# ("Not a good method, but for now it breaks the order too much, no choice" — script the demo order as-is instead of generalized judgment).
# The firebomb one (254012) early, the two shield soldiers (255000·255002) last — also consistent with the existing "ranged first"·"shield soldiers later" principles.
BURG_TOWN = json.loads((DATA / "burg-town-map.json").read_text(encoding="utf-8"))["enemies"]
STAIRS_TOP_K = 22       # route b (passage-merchant.json) point at the top of the town entrance stairs (−64.3, −23.3, −21.4)
BURG_CAREFUL = {1, 2, 3, 4, 5, 6}   # BURG_TOWN walks done slowly, stopping to pull one at a time (Field.careful_walk_to) — #4 이동 died to three
                         # twice (09-30b, 10-01a). MoKa 2026-10-01: "그쪽으로 가게 되면 천천히 가고, 대기하면서 한 명씩 끌어당겨야 함", then "행동이 아니라
                         # 천천히 움직이며 하나씩 끌어당기려는 전술적 플레이가 부족" → all six, not just #4
# Undead Burg bonfire → Taurus fog wall (ROADMAP 1-m), from [MoKa]'s recordings 2026-10-06 (observe 151317·173431).
# MoKa pressed F9 on the spot they count as safe for each zone, then pulled that zone's foes there one by one; once the zone is
# clear the safe spot moves on. Zone 7 = just before the fog wall, no foes.
UPPER = json.loads((DATA / "burg-upper-map.json").read_text(encoding="utf-8"))
UPPER_IGNORE = [tuple(p) for _n, p in UPPER["ignore"]]
UPPER_IGNORE_R = 4.0     # a foe this close to an ignored ledge spot is one of the ledge firebomb hollows — never a target
UPPER_MOVED_M = 0.5      # a target counts as awake once it has an anim and is this far off where it stood
UPPER_CLOSE_R = 3.0      # running in: stop this close even if it hasn't woken…
UPPER_NOTICE_S = 2.0     # …and stand guarding this long for it to notice, then run back anyway
UPPER_COME_R = 8.0       # a target already this close to the safe spot (or already moving) isn't run at — wait for it there
UPPER_NEAR_SAFE_R = 4.0  # within this of the safe spot, don't turn our back to run there — fight (10-06d died 2–3 m from it)
UPPER_TRIES = 4          # same target until dead, at most this many lure + fight rounds (a round may go to a foe that came along)
UPPER_ENCOUNTER_R = 10.0 # running in: any awake, moving foe on our level this close → turn back to the safe spot
UPPER_HEAL_FRAC = 0.7    # before each lure: below this share of max HP, Estus first
LADDER_TRIES = 3         # zone 8 ladder: face + A + climb attempts
LADDER_CLIMB_S = 15.0    # …give one climb this long (souls/asylum CLIMB_S)
UPPER_SIP_FRAC = 0.7     # back at the safe spot: drink only below this share (10-06g spent one on 713/742; [MoKa] 90 → 80 → 70 %)
UPPER_SWING_R = 2.5      # …and not while a foe this close is mid-swing (10-06g: interrupted by a firebomb from 2.4 m)


def _route():
    """The path the user walked and recorded (2026-09-23): top of stairs → bridge height → passage → boundary → Undead Burg → boxes → storeroom → merchant."""
    run = json.loads((DATA / "routes" / "firelink-merchant-run.json").read_text(encoding="utf-8"))
    R = json.loads((DATA / "routes" / "passage-merchant.json").read_text(encoding="utf-8"))
    top = tuple(json.loads((DATA / "climb-goal.json").read_text(encoding="utf-8"))["top"])
    A = [tuple(q) for q in run["segments"][0]["points"]]
    return top, _no_void([top] + A[67:71] + [tuple(q) for q in R["a"]]), R


_VOID_NM = None


def _no_void(pts: list) -> list:
    """Drop recorded points over the void — points with no floor at the same height underfoot, only floor more than 3 m below.
    Passage point 4 (-24.0,-33.8,10.6) had floor 16 m below: during recording it stepped on the cliff ledge above the ramp. Heading to that point on the way back,
    cliff avoidance blocked it — "passage stuck" four runs, and crossing means a fatal fall (2026-09-25). Points with no navmesh at all, like the bridge, are kept."""
    global _VOID_NM
    if _VOID_NM is None:
        import navmesh
        _VOID_NM = navmesh.Navmesh(MAP_A)
    out = []
    for q in pts:
        ys = [y for y, _f, _i in _VOID_NM.tris_at(q[0], q[2])]
        if ys and min(abs(y - q[1]) for y in ys) > 1.0 and any(q[1] - y > 3.0 for y in ys):
            continue
        out.append(q)
    return out


# The corner the user turned at the passage entrance (firelink-merchant-run point 70, on the bridge arch). _no_void drops it — the NavMesh
# only has floor 16 m below there — and 69 → a0 then runs diagonally into the entrance's side: the bot rubbed the wall 2–4 s on every
# run (radar records 2026-09-27, 15/15 passes at (−25.1, −33.7, 8.8), worst 4.4 s + two escapes; user: "turns early at the secret passage").
# Put it back on the way in only — the way back avoided it on purpose (_no_void note).
ENTRY_CORNER = (-23.97, -33.82, 10.57)
# where the user actually walks in (observe 20260927_224715, F9 at the entrance): ~1.2 m further west than 70 → a0 — the opening
# is west of the recorded points, 70 → a0 still brushed its east side (27w: down to 1.0 m/s there). Normal corners match within 0.13 m.
ENTRY_WALK = [(-25.18, -33.8, 9.56), (-26.09, -33.72, 8.99), (-26.38, -33.8, 7.87)]
ENTRY_AFTER = (-23.05, -34.26, 10.42)                      # run point 69
PASSAGE_A0 = (-25.32, -33.86, 6.68)


def _with_entry_corner(pts: list) -> list:
    out = list(pts)
    for i in range(len(out) - 1):
        if math.dist(out[i], ENTRY_AFTER) < 0.3 and math.dist(out[i + 1], PASSAGE_A0) < 0.3:
            out[i + 1:i + 1] = [ENTRY_CORNER] + ENTRY_WALK
            break
    return out


class Missions:
    def __init__(self, fld: Field, nms: dict, log=print, lure: bool = True):
        self.f, self.nms, self.log = fld, nms, log
        self.lure = lure                                  # False = --no-lure (every mission that clears the ramp, not just clear-ramp)
        self.mv: M.Moves = fld.mv

    # ── Pieces ───────────────────────────────────────────────
    def passage_drill(self, rounds: int = 5, warp_back: bool = True) -> str:
        """Walk Firelink bonfire ↔ just inside the passage entrance, rounds times, no resting (ramp stays cleared) — to watch the entrance
        turn repeatedly (user 2026-09-28). Same way in as to_merchant: top of the stairs, then the recorded route with the entry corner."""
        na = self.nms[MAP_A]
        top, route, _R = _route()
        path_in = _with_entry_corner(route)
        i0 = next(i for i, q in enumerate(path_in) if math.dist(q, PASSAGE_A0) < 0.3)
        path_in = path_in[:i0 + 4]                         # a0 + 3 points into the passage
        for n in range(1, rounds + 1):
            t0 = time.time()
            if warp_back:                                  # the way out stalls/fell (P-17) — warp back, to repeat only the way in
                ok = self.mv.tm.bonfire_warp(FIRELINK_ID, log=self.log)
                r = "warped" if ok else "warp_failed"
                time.sleep(2.0)
            else:
                r = self.f.walk_to(tuple(FIRELINK["stand"]), na, f"드릴{n} 화톳불로")
            self.log(f"   드릴 {n}: 화톳불까지 {r} {time.time() - t0:.1f} s")
            t1 = time.time()
            r = self.f.walk_to(top, na, f"드릴{n} 꼭대기로")
            if r != "arrived":
                return f"드릴 {n} 꼭대기 {r}"
            t2 = time.time()
            r = self.f.walk(path_in, na, f"드릴{n} 통로", tol=0.8)
            self.log(f"   드릴 {n}: 꼭대기 {t2 - t1:.1f} s → 통로 입구 {r} {time.time() - t2:.1f} s")
            if r != "arrived":
                return f"드릴 {n} 통로 {r}"
        return "done"

    def start_fresh(self) -> bool:
        """Rest at Firelink Shrine and start (all enemies revived, full HP·Estus)."""
        last = self.mv.tm.last_bonfire()
        if last != FIRELINK_ID:
            self.log(f"   ⚠ 마지막 화톳불이 불의 제전이 아님 ({last}) — 죽으면 거기서 깬다")
        ok = self.f.rest_at(self.nms[MAP_A], FIRELINK)
        self.log(f"── 불의 제전 휴식: {'됨' if ok else '실패'}")
        return ok

    def ramp_passed(self, r: str) -> bool:
        """Go on past the ramp? 'cleared', or 'left' with only '#N?' (identity lost, e.g. after a quit-out — dead or wandering,
        unknown). '#N' (tried and lived) and '#N~' (moved away, seen alive) still stop the mission. (ROADMAP P-18, #7)
        '#N?' is NOT proof of death: a quit-out can bring killed foes back (P-25, #14) — pass_ramp checks for survivors first."""
        if r == "cleared":
            return True
        tags = r.split()[1:] if r.startswith("left ") else []
        if tags and all(t.endswith("?") for t in tags):
            self.log(f"   경사로 {r} — 살았는지 모름(신원 끊김)만 남음, 살아 있는 적이 근처에 없어 계속 (있으면 따라와서 싸움)")
            return True
        return False

    @staticmethod
    def _only_unknown(r: str) -> bool:
        tags = r.split()[1:] if r.startswith("left ") else []
        return bool(tags) and all(t.endswith("?") for t in tags)

    def ramp_survivors(self) -> list | None:
        """Live ramp foes near a ramp spawn (same type, RAMP_SURVIVOR_R, same level) — what P-25 leaves behind after a quit-out revives
        killed ones. None if the world can't be read (then nothing is known)."""
        s = self.mv.snap(200.0)
        if s is None:
            return None
        spawns = [(e["npc"], e["pos"]) for e in RAMP]
        return [c for c in s.chars if c.hp > 0 and any(
            c.npc_param == n and math.dist((c.x, c.z), (p[0], p[2])) < RAMP_SURVIVOR_R and abs(c.y - p[1]) <= 3.0 for n, p in spawns)]

    def pass_ramp(self, lure: bool | None = None) -> tuple[bool, str]:
        """Clear the ramp and decide whether to go on. → (passed, result line).
        'left #N?' only → look for live ramp foes: none → pass (P-18); some → clear again, at most RAMP_RETRIES times, then stop
        (P-25: a quit-out revived killed foes — walking on with them alive behind us is how 28-bandit-c died)."""
        r = self.clear_ramp(lure)
        for k in range(RAMP_RETRIES):
            if not self._only_unknown(r):
                break
            alive = self.ramp_survivors()
            if not alive:
                break
            self.log(f"   경사로 {r} — 그런데 살아 있는 적 {len(alive)}마리 ({' '.join(str(c.npc_param) for c in alive[:6])}): "
                     f"퀵 종료로 되살아났을 수 있음(P-25) — 경사로를 다시 ({k + 1}/{RAMP_RETRIES})")
            r = self.clear_ramp(lure)
        if self._only_unknown(r) and self.ramp_survivors():
            return False, f"{r} (살아 있는 적 남음)"
        return self.ramp_passed(r), r

    def clear_ramp(self, lure: bool | None = None) -> str:
        lure = self.lure if lure is None else lure
        targets = [dict(RAMP[i - 1], label=i, lure=(i not in NO_LURE), lure_at=RAMP_LURE_AT.get(i)) for i in RAMP_ORDER]
        r = self.f.clear(targets, self.nms[MAP_A], arena=RAMP_ARENA, lure=lure)
        self.log(f"── 경사로: {r}")
        return r

    def _climb_entry_stairs(self, nb) -> None:
        """Town entrance → top of the stairs (route b point STAIRS_TOP_K) as a normal walk — [MoKa] 2026-10-01: "계단까지는 안전 구역이니
        쭉 올라가도 돼". The slow pull-one-at-a-time walk (BURG_CAREFUL) starts at the top. Only when we stand on those stairs now."""
        _, _, R = _route()
        stairs = [tuple(q) for q in R["b"][:STAIRS_TOP_K + 1]]
        s = self.f.snap_settled(5.0)
        if s is None:
            return
        here = (s.player.x, s.player.y, s.player.z)
        k = min(range(len(stairs)), key=lambda j: math.dist(stairs[j], here))
        if math.dist(stairs[k], here) > 4.0 or k >= STAIRS_TOP_K:
            return
        r = self.f.walk(stairs[k:], nb, "계단 위로", tol=0.8)
        self.log(f"   계단 위로 (안전 구역): {r}")

    def clear_burg_town(self, only: set | None = None) -> str:
        """Kill the 6 in Undead Burg in exactly the order the user killed them (BURG_TOWN).
        **Uses walk_to() instead of field.clear()** — initially used clear() and it failed when measured (2026-09-25, burg-loop 101100):
        #1~3 (close) worked but #4~6 (near the bonfire room, far and behind walls) couldn't be reached by duel()'s local approach (_approach) alone,
        repeating "stuck" 4 times each — wasting 110 s+ in place and dying right after. 4~6 were at distances needing real pathfinding (navmesh).
        So for each target, first walk_to() along a real path to its coordinates (awake enemies on the way are engaged by walk()'s
        chaser automatically — sometimes the target itself is already killed on the way), and after arriving, fight() it if alive."""
        nb = self.nms[MAP_B]
        self._climb_entry_stairs(nb)
        for i, e in enumerate(BURG_TOWN, 1):
            if only is not None and i not in only:
                continue
            if not self.f.alive():
                return "died"
            s0 = self.mv.snap(40.0)
            if (s0 is not None and math.dist((s0.player.x, s0.player.y, s0.player.z), tuple(e["pos"])) < 15.0
                    and self.f.find_at(e["npc"], e["pos"], 15.0) is None):
                # 163921: the spawn (-36.0,-13.5,-70.1) of #6 (255000), already killed after it chased us, is against boxes·wall and can't be stood on, so it
                # circled 2.6 m in front for 35 s. If the spawn is close (15 m) and that enemy isn't seen around it, don't walk there
                self.log(f"   #{i} {e['npc']}: 스폰 15 m 안인데 안 보임 — 이미 잡음, 걸어가지 않음")
                continue
            # If that enemy chased us while walking and got killed, don't go to an unstandable spawn (163921·next run: 17~35 s 2.2 m in front of #6 spawn)
            gone = (lambda sn, e=e: math.dist((sn.player.x, sn.player.y, sn.player.z), tuple(e["pos"])) < 8.0
                    and self.f.find_at(e["npc"], e["pos"], 15.0) is None)
            if i in BURG_CAREFUL:
                r = self.f.careful_walk_to(tuple(e["pos"]), nb, f"#{i} 이동", done=gone)
            else:
                r = self.f.walk_to(tuple(e["pos"]), nb, f"#{i} 이동", done=gone)
            if r == "dead":
                return "died"
            if r != "arrived":
                self.log(f"   #{i} 이동: {r} — 지금 자리에서 찾아본다")
            c = self.f.find_at(e["npc"], e["pos"], 5.0) or self.f.find_at(e["npc"], e["pos"], 15.0)
            if c is None:
                self.log(f"   #{i} {e['npc']}: 안 보임 — 가는 길에 이미 잡았거나 죽음")
                continue
            res = self.f.fight(c.ptr, nb, f"#{i} {e['npc']}")
            if res.result == "me_dead":
                return "died"
            if res.result != "killed":
                ok = self.f.recover(f"#{i} {res.result}", nb)
                if not ok and self.f.estus_left() <= 0:
                    return "no_estus"
        self.log("── 성벽 마을(순서 고정): 끝")
        return "cleared"

    def upper_zone(self, n: int) -> str:
        """Zone n of the Burg bonfire → fog wall stretch (UPPER): walk carefully to the zone's safe spot (a marked fall-back spot
        and the fight tether while the zone runs), then for each foe in MoKa's kill order go wake it and fight it back there."""
        nb = self.nms[MAP_B]
        z = UPPER["zones"][n - 1]
        safe = tuple(z["safe"])
        # home = where recover() backs off to drink. Not the safe spot (10-06d: already there, foe on us → never drank) and not
        # the run's default (Firelink — another NavMesh, no path) → the Undead Burg bonfire
        home0, self.f.home = self.f.home, BURG_BONFIRE_SIDE
        # 10-06b 구역 2: 255001이 깨우러 가는 걸음 중간에 따라붙어, 걷기의 '따라온 놈' 싸움이 안전 자리 13 m 앞(턱 화염병 9 m)에서 바로 시작 → 사망.
        # 걷기는 따라온 놈을 싸우기 전에 찍어 둔 자리(ZONE_REACH 15 m 안)로 가드 든 채 물러나므로, 이 구역 동안 안전 자리를 거기 넣는다
        # [MoKa]: "적이 붙으면 그 다음에 안전 구역으로 가야 하는데, 그냥 있으면 화염폭탄에 맞아서 죽지" → 싸움 도중에도 벗어나면 끊고 돌아옴 (Field.fight tether)
        zones0, tether0 = getattr(self.f, "extra_zones", ()), getattr(self.f, "tether", None)
        no_safe = bool(z.get("no_safe"))                  # 구역 3 — [MoKa] "적이 하나씩 만나니깐 그냥 공격 … 안전 구역 자체가 필요 없어"
        self.f.extra_zones, self.f.tether = ((), None) if no_safe else ((safe,), safe)
        try:
            if z.get("before") and not self._top_up(nb, f"구역{n}"):   # fog wall · ladder ahead — no fighting there, drink first
                return "no_estus"
            for step in z.get("before", []):
                r = self._before(step, nb, f"구역{n}")
                if r == "dead":
                    return "died"
                if r != "ok":
                    return f"{next(iter(step))} {r}"
            if no_safe:
                r = "arrived"
            elif z.get("run_to_safe"):
                r = self._sprint(safe, nb, None)
                r = "dead" if r == "dead" else ("arrived" if r in ("arrived", "stopped") else r)
            else:
                r = self.f.careful_walk_to(safe, nb, f"구역{n} 안전 자리")
            if r == "dead":
                return "died"
            if r != "arrived":
                self.log(f"   구역{n} 안전 자리까지 {r} — 지금 자리에서 이어감")
            left = []
            for i, k in enumerate(z["kills"], 1):
                if not self.f.alive():
                    return "died"
                npc, pos, how = k[0], k[1], (k[2] if len(k) > 2 else {})
                r = self._pull_to_safe(npc, tuple(pos), safe, nb, f"구역{n}-{i} {npc}", how)
                if r in ("died", "no_estus"):
                    return r
                if r not in ("killed", "gone"):
                    left.append(f"#{i} {npc} {r}")
        finally:
            self.f.home = home0
            self.f.extra_zones, self.f.tether = zones0, tether0
        if left:                                       # 10-06 구역 8: 석궁 둘이 살아 있는데 'cleared' (P-47)
            self.log(f"── 구역{n}: 끝 — 남은 적 {', '.join(left)}")
            return "left " + " ".join(s.split()[0] for s in left)
        self.log(f"── 구역{n}: 끝")
        return "cleared"

    def _pull_to_safe(self, npc: int, pos, safe, nb, tag: str, how: dict | None = None) -> str:
        """── 안전 자리로 끌어와 싸우기 ([MoKa] 2026-10-06 녹화) ──────────────────────────────
         MoKa는 구역 적을 그 자리에서 싸우지 않고 깨운 뒤 안전 자리까지 데리고 와서 잡았다 (구역 2: 255001을 스폰에서 20 m 끌고 옴).
         나이프가 없는 캐릭터라 던져서 깨우지 않는다. 녹화 그대로 **달려 들어가서**(~4.7 m/s) 그놈이 깨어 움직이면 곧바로
         **달려서 나온다**(가드 없이) — [MoKa] 10-06: "유인하러 들어갔다 빠르게 나와야 해". 10-06b·c는 천천히 걷기(4 m + 1.5 s 멈춤)·
         가드 걷기로 물러나다 255001에게 따라잡혀 화염병 사정권에서 싸웠다(P-45). UPPER_CLOSE_R까지 가도 안 깨면 그 자리에서 싸움.
         턱 위 화염병(UPPER_IGNORE)은 사다리·낙사 구간이라 목표로 삼지 않는다.
         10-06d (P-45): 이미 깨어 안전 자리 4 m 앞까지 온 254011에게 또 달려 나갔다가, 안전 자리 2 m 앞에서 "달려서 돌아가기"만 하며
         세 번 맞고 죽음([MoKa]: "왜 다시 돌아가려 한거야?") → 이미 오는 놈·안전 자리 가까운 놈엔 안 나가고, 안전 자리 UPPER_NEAR_SAFE_R
         안이면 돌아서지 않고 싸움. 그 전엔 255001을 HP 334로 남겨 두고 다음 놈으로 넘어감 → 그놈이 죽을 때까지 UPPER_TRIES번,
         나가기 전마다 에스트 먼저([MoKa]: "hp가 많이 줄었으면, 에스트를 마셔야 하는 것이 우선")."""
        c = self.f.find_at(npc, pos, 8.0) or self.f.find_at(npc, pos, 20.0)
        if c is not None and any(math.dist((c.x, c.y, c.z), q) < UPPER_IGNORE_R for q in UPPER_IGNORE):
            c = None
        if c is None:
            self.log(f"   {tag}: 안 보임 — 이미 잡았거나 죽음")
            return "gone"
        ptr = c.ptr
        res = None
        if (how or {}).get("attack"):                      # 구역 8 석궁 — [MoKa] "가자 마자 공격해": no lure, no waiting, close in now
            desperate = False                          # 10-06 구역 8: low_hp 뒤 물러남·에스트 없이 0 s 싸움을 4번 → 사망 (P-47)
            for k in range(UPPER_TRIES):
                if not self.f.alive():
                    return "died"
                res = self.f.fight(ptr, nb, tag, desperate=desperate)
                if res.result in ("me_dead", "killed"):
                    return "died" if res.result == "me_dead" else "killed"
                t = self.mv.find(self.mv.snap(200.0), ptr)
                if t is None or t.hp <= 0:
                    return "killed"
                ok = self.f.recover(f"{tag} {res.result}", nb)
                if not ok and self.f.estus_left() <= 0:
                    return "no_estus"
                desperate = not ok
            return res.result
        for k in range(UPPER_TRIES):
            if not self.f.alive():
                return "died"
            if not self._top_up(nb, tag):
                return "no_estus"
            t = self.mv.find(self.mv.snap(200.0), ptr)
            if t is None or t.hp <= 0:
                self.log(f"   {tag}: 죽음")
                return "killed"
            if self._lure(t, ptr, safe, nb, tag, how or {}) == "died":
                return "died"
            self._drink_back(tag)
            foe = self._first_foe(ptr)
            ftag = tag if foe == ptr else f"{tag}: 같이 온 놈"
            res = self.f.fight(foe, nb, ftag, wait_far=True)
            if res.result == "me_dead":
                return "died"
            if res.result == "killed" and foe == ptr:
                return "killed"
            if res.result != "killed":
                ok = self.f.recover(f"{ftag} {res.result}", nb)
                if not ok and self.f.estus_left() <= 0:
                    return "no_estus"
                self.log(f"   {ftag}: {res.result} — 살아 있음, 다시 ({k + 1}/{UPPER_TRIES})")
        return res.result if res is not None else "gone"

    def _top_up(self, nb, tag: str) -> bool:
        """Estus before going out: below UPPER_HEAL_FRAC drink here, or — a foe too close to drink — back off toward the bonfire
        (Field.home) until clear, drink, and the next lure runs from there. False = low and no Estus left."""
        s = self.mv.snap(15.0)
        if s is None or s.player.hp >= s.player.max_hp * UPPER_HEAL_FRAC:
            return True
        self.f.heal(UPPER_HEAL_FRAC)
        s = self.mv.snap(15.0)
        if s is None or s.player.hp >= s.player.max_hp * UPPER_HEAL_FRAC:
            return True
        if self.f.estus_left() <= 0:
            return False
        back = self.f.retreat(nb, self.f.home)
        self.log(f"   {tag}: HP {s.player.hp}/{s.player.max_hp} — 적이 가까워 화톳불 쪽으로 물러나 에스트: {back}")
        self.f.heal(UPPER_HEAL_FRAC)
        return True

    def _drink_back(self, tag: str) -> None:
        """── 돌아오면 에스트부터 ([MoKa] 2026-10-06) ──────────────────────────────
         "그 구간이 화염병 맞는 구간이라 안전 구역으로 오고, 무조건 에스트부터 마시게 해" · "반응이 느려서 화염병을 거의 맞는다고
         가정해야 해" → 안전 자리에 오면 근처에 적이 있어도(Field.safe 안 봄) 한 모금, 그래도 UPPER_HEAL_FRAC 밑이면 한 모금 더.
         10-06g 뒤 [MoKa] 승인으로 두 예외: HP UPPER_SIP_FRAC 위면 안 마심(713/742에 한 개 씀) · UPPER_SWING_R 안에서 휘두르는
         적이 있으면 미룸(2.4 m 화염병에 끊겨 −109, 개수 그대로) — 그땐 싸움 중 에스트(duel care)가 틈을 봄."""
        for sip in range(2):
            s = self.mv.snap(15.0)
            if s is None or s.player.hp >= s.player.max_hp * (UPPER_SIP_FRAC if sip == 0 else UPPER_HEAL_FRAC):
                return
            if self.f.estus_left() <= 0:
                self.log(f"   {tag}: 에스트 없음")
                return
            swing = [c for c in s.hostile(UPPER_SWING_R + 1.0) if c.hp > 0 and (c.anim or -1) in M.ATTACK
                     and M.horiz(s.player, c) < UPPER_SWING_R] if hasattr(s, "hostile") else []
            if swing:
                self.log(f"   {tag}: 에스트 미룸 — {swing[0].npc_param} {M.horiz(s.player, swing[0]):.1f} m에서 휘두르는 중")
                return
            r = self.mv.drink(lambda _s: True)
            self.log(f"   {tag}: 안전 자리 — 에스트 먼저 (HP {s.player.hp}/{s.player.max_hp}): {r}")
            self.f.events("estus", **r)
            if not r.get("ok"):
                return

    def _encounters(self, sn, ptr) -> list:
        """Awake, moving foes on our level within UPPER_ENCOUNTER_R — the target or anyone else ([MoKa]: "적을 조우하면 안전구역으로")."""
        p = sn.player
        return [c for c in sn.hostile(UPPER_ENCOUNTER_R) if c.hp > 0 and c.anim not in (None, -1)
                and abs(c.y - p.y) < 2.5 and M.horiz(p, c) < UPPER_ENCOUNTER_R]

    def _first_foe(self, ptr):
        """Back at the safe spot: fight whoever is closest and coming (it may not be the target), else the target."""
        s = self.mv.snap(UPPER_ENCOUNTER_R + 1.0)
        near = self._encounters(s, ptr) if s is not None and hasattr(s, "hostile") else []
        return min(near, key=lambda c: M.horiz(s.player, c)).ptr if near else ptr

    def _lure(self, t, ptr, safe, nb, tag: str, how: dict | None = None) -> str:
        """── 유인: 조우하면 돌아오는 게 먼저 ([MoKa] 2026-10-06) ──────────────────────────────
         "적을 유인하다 목표 지점까지 가려는 게 우선이 아니라 적을 조우하면 안전구역으로 돌아오는 것이 우선".
         이미 오는 중·안전 자리 가까운 목표 → 나가지 않음. 아니면 목표 쪽으로 달려가다 **누구든** 깨어 움직이면(목표가 아니어도)
         그 틱에 멈추고 달려서 돌아옴. 목표 UPPER_CLOSE_R까지 갔는데 아무도 안 움직이면 가드 들고 UPPER_NOTICE_S 기다린 뒤 돌아옴.
         안전 자리 UPPER_NEAR_SAFE_R 안이면 돌아서지 않음.
         how (UPPER kills의 셋째 칸, 구역 5 — [MoKa] "계단으로 내려가지 않고 처음에 난간으로 가면 255001이 순찰 돌아 옴"):
          · wait: 먼저 안전 자리에서 가드 든 채 이만큼 기다림 — 순찰하는 놈(255000)은 스스로 올라온다
          · lure_at: 그놈 스폰 대신 여기까지만 달려가서 알아채게 함 (계단 아래로 안 내려감) · notice: 거기서 기다리는 시간
         → 'here' | 'died'"""
        how = how or {}
        here0 = (t.x, t.y, t.z)

        def woke(c) -> bool:                               # moving: anim set and off where it stood (idle anims don't count)
            return c.anim not in (None, -1) and math.dist((c.x, c.y, c.z), here0) > UPPER_MOVED_M

        if (t.anim not in (None, -1) and t.anim not in M.STAGGER) or math.hypot(t.x - safe[0], t.z - safe[2]) < UPPER_COME_R:
            self.log(f"   {tag}: 이미 오는 중이거나 안전 자리 가까움 — 안전 자리에서 받음")
            return "here"
        if how.get("wait") and self._wait_at_safe(ptr, safe, float(how["wait"])):
            self.log(f"   {tag}: 안전 자리에서 기다리니 옴")
            return "here"

        def met(sn) -> bool:
            c = self.mv.find(sn, ptr)
            return c is None or c.hp <= 0 or woke(c) or any(e.ptr != ptr for e in self._encounters(sn, ptr))

        def stop_in(sn) -> bool:
            c = self.mv.find(sn, ptr)
            return met(sn) or (c is not None and M.horiz(sn.player, c) < UPPER_CLOSE_R)

        goal = tuple(how["lure_at"]) if how.get("lure_at") else here0
        if self._sprint(goal, nb, stop_in) == "dead":
            return "died"
        s = self.mv.snap(200.0)
        if s is not None and not met(s):
            guard = getattr(self.mv.pad, "guard", lambda on: None)
            guard(True)
            t0 = time.time()
            while time.time() - t0 < float(how.get("notice", UPPER_NOTICE_S)):
                s = self.mv.snap(200.0)
                if s is None or met(s):
                    break
                time.sleep(0.1)
            guard(False)
        s = self.mv.snap(5.0)
        if s is not None and math.hypot(s.player.x - safe[0], s.player.z - safe[2]) <= UPPER_NEAR_SAFE_R:
            return "here"
        why = "조우" if s is not None and met(s) else "아직 아무도 안 움직임"
        back = self._sprint(safe, nb, lambda sn: math.hypot(sn.player.x - safe[0], sn.player.z - safe[2]) < 1.5)
        self.log(f"   {tag}: {why} — 달려서 안전 자리로 {back}")
        return "died" if back == "dead" else "here"

    def _before(self, step: dict, nb, tag: str) -> str:
        """A zone's 'before' step (구역 8, [MoKa] "안개벽 지나서, 사다리 타고 올라가서"). → 'ok' | 'dead' | 'fail' | walk result
          fog: walk to front, settle, fog_through toward beyond (known wall — A without the prompt check), as souls/asylum does
          ladder: walk to bottom, face `face`, A, stick up until top_y, keep pushing to step off (souls/asylum._climb)"""
        if "fog" in step:
            st = step["fog"]
            front, beyond = tuple(st["front"]), tuple(st["beyond"])
            s = self.mv.snap(5.0)
            if s is not None:
                here = (s.player.x, s.player.y, s.player.z)
                if math.dist(here, beyond) < math.dist(here, front):
                    self.log(f"   {tag}: 이미 안개벽 너머")
                    return "ok"
            r = self.f.walk_to(front, nb, f"{tag} 안개벽 앞")
            if r == "dead" or not self.f.alive():
                return "dead"
            self.f._settle(front, tol=0.5)
            ok = self.f.fog_through(beyond, known=True)
            self.log(f"   {tag}: 안개벽 {'통과' if ok else '못 지나감'}")
            return "ok" if ok else "fail"
        st = step["ladder"]
        bottom, face, top_y = tuple(st["bottom"]), tuple(st["face"]), float(st["top_y"])
        s = self.mv.snap(5.0)
        if s is not None and s.player.y >= top_y - 0.6:
            self.log(f"   {tag}: 이미 사다리 위")
            return "ok"
        if st.get("approach"):                             # [MoKa]: "계단에서 내려 와서, 옆으로 붙어서" — the recorded line, not a diagonal
            r = self.f.walk([tuple(q) for q in st["approach"]], nb, f"{tag} 사다리 아래", tol=0.4)
        else:
            r = self.f.walk_to(bottom, nb, f"{tag} 사다리 아래")
        if r == "dead" or not self.f.alive():
            return "dead"
        self.f._settle(bottom, tol=0.4)
        for attempt in range(LADDER_TRIES):
            s = self.mv.snap(5.0)
            if s is not None and s.cam_yaw is not None:
                self.mv.pad.move(*self.mv.stick_to(s, face[0], face[2], 0.35))
                time.sleep(0.25)
                self.mv.pad.move(0.0, 0.0)
                time.sleep(0.2)
            self.mv.pad.interact()
            time.sleep(0.8)
            s = self.mv.snap(5.0)
            y0 = s.player.y if s else bottom[1]
            t0, moved = time.time(), False
            while time.time() - t0 < LADDER_CLIMB_S:
                self.mv.pad.move(0.0, 1.0)                 # stick up = climb
                time.sleep(0.1)
                s = self.mv.snap(5.0)
                if s is None:
                    continue
                moved = moved or s.player.y > y0 + 0.4
                if s.player.y >= top_y - 0.3:
                    time.sleep(0.8)                        # keep pushing — step off the top
                    break
                if not moved and time.time() - t0 > 2.5:
                    break                                  # not on the ladder — face it again and A
            self.mv.pad.neutral()
            s = self.mv.snap(5.0)
            if s is not None and s.player.y >= top_y - 0.6:
                self.log(f"   {tag}: 사다리 올라감 (y {s.player.y:.1f})")
                return "ok"
            self.log(f"   {tag}: 사다리 안 올라감 ({attempt + 1}/{LADDER_TRIES}, y {None if s is None else round(s.player.y, 1)})")
            self.f._settle(bottom, tol=0.4)
        return "fail"

    def _wait_at_safe(self, ptr, safe, secs: float) -> bool:
        """Guard at the safe spot up to secs for the target (or anyone) to come within UPPER_COME_R of it. → it came"""
        guard = getattr(self.mv.pad, "guard", lambda on: None)
        guard(True)
        try:
            t0 = time.time()
            while time.time() - t0 < secs:
                s = self.mv.snap(200.0)
                if s is not None:
                    c = self.mv.find(s, ptr)
                    if c is None or c.hp <= 0 or math.hypot(c.x - safe[0], c.z - safe[2]) < UPPER_COME_R:
                        return True
                    if any(math.hypot(e.x - safe[0], e.z - safe[2]) < UPPER_COME_R for e in self._encounters(s, ptr)):
                        return True
                time.sleep(0.2)
            return False
        finally:
            guard(False)

    def _sprint(self, goal, nb, stop) -> str:
        """Run along the NavMesh path to goal (no guard) until stop(snapshot). → 'arrived' | 'stopped' | 'dead' | 'no_path' | …"""
        s = self.mv.snap(5.0)
        if s is None:
            return "no_snapshot"
        path = nb.find_path((s.player.x, s.player.y, s.player.z), tuple(goal))
        if not path:
            return "no_path"
        return self.mv.walk_path(nav.trim_path(path[1:], tuple(goal)), nb, "sprint", stop=stop)

    UPPER_SEGMENTS = {n: f"zone{n}" for n in range(1, len(UPPER["zones"]) + 1)}

    def upper_segment(self, n: int) -> str:
        """One safe-spot zone, then stop (same as burg_segment). Zone 1 rests at the Undead Burg bonfire first — every foe revives,
        HP·Estus full, so each try starts the same; later zones go on from where the character stands, without resting."""
        if not self.f.alive():
            self.f.wait_respawn()
        if n == 1:
            ok = self.f.rest_at(self.nms[MAP_B], SPOTS["burg-bonfire"])
            self.log(f"── 성벽 마을 휴식: {'됨' if ok else '안 됨'}")
            if not ok:
                return "휴식 실패"
        return self.upper_zone(n)

    def hunt_one(self, i: int) -> str:
        """From the Undead Burg bonfire, kill only BURG_TOWN #i and walk back to the bonfire — for testing single-enemy handling
        (user 2026-09-25: "Make it attack only that archer and come back to the bonfire" — #5 = crossbowman 255002)."""
        nb = self.nms[MAP_B]
        e = BURG_TOWN[i - 1]
        tag = f"#{i} {e['npc']}"
        # Rest at the Undead Burg bonfire first — HP·Estus refill and that enemy respawns, so every run has the same conditions (user: "rest first")
        ok = self.f.rest_at(nb, SPOTS["burg-bonfire"])
        self.log(f"── 성벽 마을 휴식: {'됨' if ok else '안 됨'}")
        r = self.f.walk_to(tuple(e["pos"]), nb, f"{tag} 이동")
        if r == "dead":
            return "died"
        c = self.f.find_at(e["npc"], e["pos"], 5.0) or self.f.find_at(e["npc"], e["pos"], 15.0)
        if c is None:
            self.log(f"   {tag}: 안 보임")
            res = "not_found"
        else:
            d = self.f.fight(c.ptr, nb, tag)
            res = d.result
            if res == "me_dead":
                return "died"
        back = self.f.walk_to(BURG_BONFIRE_SIDE, nb, "화톳불로")
        self.log(f"── 한 마리: {res}, 귀환 {back}")
        return f"{res} / 귀환 {back}"

    def to_merchant(self, stop: str | None = None, town: set | None = None) -> str:
        """stop: 'passage' = end at the Undead Burg entrance, 'town' = end after clearing `town` (BURG_TOWN numbers; None = all six,
        set() = none — later zones of a --seg run). Used by burg_segment."""
        return self._to_merchant(stop, town)

    def _to_merchant(self, stop: str | None, town: set | None) -> str:
        """To the merchant. Continues from the segment·point nearest the current position — passage (A) · Undead Burg (B) · storeroom (C).
        Previously it only looked at segment A, called it 'far', went back to the top of the stairs and got stuck (started inside Undead Burg, 2026-09-24)."""
        na, nb = self.nms[MAP_A], self.nms[MAP_B]
        top, route, R = _route()
        pb = [tuple(q) for q in R["b"]]
        pc = [tuple(q) for q in R["c"]]
        t0 = time.time()
        s = self.f.snap_settled(5.0)
        here = (s.player.x, s.player.y, s.player.z)
        seg, k, d = min(((name, j, math.dist(q, here)) for name, pts in (("A", route), ("B", pb), ("C", pc))
                         for j, q in enumerate(pts)), key=lambda t: t[2])
        self.log(f"   상인 길: 가장 가까운 곳 {seg}{k} ({d:.1f} m)")
        if d > 6.0:
            if seg == "A":
                r = self.f.walk_to(top, na, "꼭대기로")
                if r != "arrived":
                    return f"꼭대기까지 {r}"
                seg, k = "A", 0
            else:
                pts = pb if seg == "B" else pc
                r = self.f.walk_to(pts[k], nb, "길로")
                if r != "arrived":
                    return f"길까지 {r}"
        if seg == "A":
            r = self.f.walk(_with_entry_corner(route[k:]), na, "통로", tol=0.8)
            if r != "arrived":
                return f"통로 {r}"
            self.log(f"   경계 {time.time() - t0:.0f} s")
            if stop == "passage":
                return "통로 끝"
            seg, k = "B", 0
        if seg in ("B", "C"):
            self.f.home = pb[0]                            # in Undead Burg, retreat toward the entrance (this navmesh has no path to Firelink Shrine — no_path spinning)
        if seg == "B":
            # On entering Undead Burg, first clear the 6 in the fixed order (BURG_TOWN) — after that, only opportunistic fights while walking
            # (user 2026-09-25: "Code it to kill in the order I kill", "Make sure to keep the order")
            r = self.clear_burg_town(town)
            if r != "cleared" and not r.startswith("left"):
                return f"성벽 마을 순서 {r}"
            if stop == "town":
                return f"성벽 마을 {sorted(town) if town is not None else '전부'} {r}"
            # This is after roaming to the far end of town (#6) to kill the 6 — walking from the k (entrance) chosen on entry went straight toward the far entrance point
            # and hit a wall (2026-09-25, four runs in a row "Undead Burg stuck"). Re-find the nearest point from here and pathfind to it.
            s = self.f.snap_settled(5.0)
            if s is None:
                return "성벽 마을 위치 못 읽음"
            here = (s.player.x, s.player.y, s.player.z)
            k = min(range(len(pb)), key=lambda j: math.dist(pb[j], here))
            self.log(f"   마을 정리 뒤: 가장 가까운 B{k} ({math.dist(pb[k], here):.1f} m)")
            if math.dist(pb[k], here) > 3.0:
                r = self.f.walk_to(pb[k], nb, "길로")
                if r != "arrived":
                    return f"성벽 마을 길까지 {r}"
            r = self.f.walk(pb[k:], nb, "성벽 마을", tol=0.8, tight=R["small_bridge"])
            if r != "arrived":
                return f"성벽 마을 {r}"
            if not self._roll_boxes(R["roll"]["from"], R["roll"]["to"]):
                return "상자 못 지나감"
            seg, k = "C", 0
        rest = pc[k:]
        s = self.f.snap_settled(5.0)
        if k == 0 and s is not None and math.dist((s.player.x, s.player.y, s.player.z), tuple(R["roll"]["to"])) < 1.5:
            # At the box-rolling end spot (-30.2,-14.6,-76.6), three runs in a row (161024·zones·163921) walking made 0 m — boxes blocking the stairs
            # remained, and one roll went straight down (163921: 50 s stuck → through in one at 710). Roll once first
            self.mv.roll_toward(s, pc[0][0], pc[0][2])
            time.sleep(0.8)
        for extra in range(3):
            r = self.f.walk(rest, nb, "창고 방", tol=0.8)
            if r != "stuck" or extra == 2:
                break
            # A remaining box was blocking the stairs (2026-09-23 screenshot) — roll once more toward the next point to break it
            s = self.f.snap_settled(5.0)
            j = min(range(len(pc)), key=lambda i: math.dist(pc[i], (s.player.x, s.player.y, s.player.z)))
            nxt = pc[min(j + 1, len(pc) - 1)]
            self.mv.roll_toward(s, nxt[0], nxt[2])
            rest = pc[j:]
        s = self.f.snap_settled(5.0)
        d = math.dist((s.player.x, s.player.y, s.player.z), tuple(R["stand"])) if s else None
        res = "도착" if r == "arrived" and d is not None and d < 2.5 else f"창고 방 {r} (상인까지 {d if d is None else round(d, 1)} m)"
        self.log(f"── 상인: {res} — {time.time() - t0:.0f} s")
        return res

    def to_firelink(self) -> str:
        """Walk back to Firelink Shrine — the reverse of to_merchant. The Undead Burg (B) navmesh has no path to Firelink Shrine
        (no_path), so walk the recorded path backwards. Boxes were already broken on the way there, so don't roll again."""
        na, nb = self.nms[MAP_A], self.nms[MAP_B]
        top, route, R = _route()
        pb = list(reversed([tuple(q) for q in R["b"]]))
        pc = list(reversed([tuple(q) for q in R["c"]]))
        route_r = list(reversed(route))
        t0 = time.time()
        s = self.f.snap_settled(5.0)
        here = (s.player.x, s.player.y, s.player.z)
        pts = {"C": pc, "B": pb, "A": route_r}
        seg, k, d = min(((name, j, math.dist(q, here)) for name, ps in pts.items()
                         for j, q in enumerate(ps)), key=lambda t: t[2])
        self.log(f"   귀환 길: 가장 가까운 곳 {seg}{k} ({d:.1f} m)")
        self.f.home = FIRELINK["stand"] if seg == "A" else tuple(R["b"][0])
        if d > 6.0:                                     # starting away from the recorded path, e.g. at a bonfire — go to that point first
            r = self.f.walk_to(pts[seg][k], na if seg == "A" else nb, "귀환 길로")
            if r != "arrived":
                return f"귀환 길까지 {r}"
        if seg == "C":
            r = self.f.walk(pc[k:], nb, "창고 방(귀환)", tol=0.8)
            if r != "arrived":
                return f"창고 방 {r}"
            seg, k = "B", 0
        if seg == "B":
            self.f.home = tuple(R["b"][0])
            r = self.f.walk(pb[k:], nb, "성벽 마을(귀환)", tol=0.8, tight=R["small_bridge"])
            if r != "arrived":
                return f"성벽 마을 {r}"
            seg, k = "A", 0
        if seg == "A":
            self.f.home = FIRELINK["stand"]
            r = self.f.walk(route_r[k:], na, "통로(귀환)", tol=0.8)
            if r != "arrived":
                return f"통로 {r}"
        r = self.f.walk_to(tuple(FIRELINK["stand"]), na, "불의 제전으로")
        self.log(f"── 귀환: {r} — {time.time() - t0:.0f} s")
        return r

    def _roll_boxes(self, frm, to, tries: int = 3) -> bool:
        """Roll through the box pile, breaking it (user: "Rolling in and breaking them is better"). Stand within 0.3 m of the start point and roll."""
        def past(sn) -> bool:
            return sn.player.y < frm[1] - 0.5 or math.dist((sn.player.x, sn.player.z), (to[0], to[2])) < 1.5
        for _ in range(tries):
            s = self.f.snap_settled(5.0)
            if s is None or s.cam_yaw is None:
                return False
            if past(s):
                return True
            nav.goto(self.mv.tm, self.mv.pad, tuple(frm), tolerance=0.3, timeout=5, log=lambda *a: None)
            self.mv.pad.neutral()
            time.sleep(0.15)
            s = self.f.snap_settled(5.0)
            self.mv.roll_toward(s, to[0], to[2])
            s = self.f.snap_settled(5.0)
            if s and past(s):
                return True
        return False

    def light_burg_bonfire(self) -> str:
        """Light the Undead Burg bonfire and sit: first A = light (BONFIRE LIT), next A = sit.
        Success = sat and the last bonfire ID is no longer Firelink Shrine. B (stand up) is pressed **only while sitting** (otherwise it's a backstep)."""
        nb = self.nms[MAP_B]
        _, _, R = _route()
        self.f.home = tuple(R["b"][0])                     # retreat spot = Undead Burg entrance (inside this navmesh)
        r = self.f.walk_to(BURG_BONFIRE_SIDE, nb, "화톳불로")
        if r != "arrived":
            return f"화톳불까지 {r}"
        # Bloodstain next to the bonfire first (2026-09-24: died here, 740 souls) — we'll sit at this bonfire anyway, so it's fine if A goes into sitting
        b = self.f.pick_blood(nb, near=10.0, bonfire_ok=True)
        if b:
            self.log(f"   핏자국: {b}")
        s = self.mv.snap(15.0)
        if s and not self.f.safe(s):
            self.f.shake_off("화톳불 앞 적")               # with an enemy close, can't light or sit
        s = self.f.snap_settled(5.0)
        if s and s.cam_yaw is not None:                     # face the bonfire
            self.mv.pad.move(*self.mv.stick_to(s, BURG_BONFIRE[0], BURG_BONFIRE[2], 0.45))
            time.sleep(0.18)
            self.mv.pad.move(0.0, 0.0)
            time.sleep(0.5)
        tm = self.mv.tm
        before = tm.last_bonfire()
        sat = False
        for _ in range(3):
            self.mv.press(M.B.XUSB_GAMEPAD_A)
            t0 = time.time()
            while time.time() - t0 < 6.0 and not tm.sitting():
                time.sleep(0.25)
            if tm.sitting():
                sat = True
                break
        time.sleep(1.0)
        after = tm.last_bonfire()
        for _ in range(6):
            if not (tm.sitting() or tm.menu_open()):
                break
            self.mv.press(M.B.XUSB_GAMEPAD_B)
            time.sleep(1.0)
        ok = sat and after is not None and after != FIRELINK_ID
        self.log(f"── 성벽 마을 화톳불: 앉음 {sat}, 마지막 화톳불 {before} → {after} — {'귀환 지점 바뀜' if ok else '확인 못 함'}")
        return "lit" if ok else f"실패 (앉음 {sat}, {before}→{after})"

    # ── Missions ─────────────────────────────────────────────
    BURG_SEGMENTS = {1: "ramp", 2: "passage", 3: "town1", 4: "town2", 5: "merchant", 6: "bonfire"}

    def burg_segment(self, n: int) -> str:
        """One zone of burg_bonfire, then stop — [MoKa] 2026-10-01: "한 구역이 끝나면 중단하고, 피드백하고 다음 구역으로". Each zone goes on
        from where the character stands, without resting (killed foes stay dead): 1 ramp (rests at Firelink first) · 2 secret passage to the
        town entrance · 3 town #1–#3 · 4 town #4–#6 · 5 through town and the storeroom to the merchant · 6 light the Undead Burg bonfire."""
        name = self.BURG_SEGMENTS[n]
        if not self.f.alive():
            self.f.wait_respawn()
        if name == "ramp":
            if not self.start_fresh():
                return "휴식 실패"
            ok, r = self.pass_ramp()
            return f"경사로 {r}"
        if name == "passage":
            return self.to_merchant(stop="passage")
        if name == "town1":
            return self.to_merchant(stop="town", town={1, 2, 3})
        if name == "town2":
            return self.to_merchant(stop="town", town={4, 5, 6})
        if name == "merchant":
            r = self.to_merchant(town=set())
            return f"상인 {r}"
        return self.light_burg_bonfire()

    def burg_bonfire(self) -> str:
        if not self.f.alive():
            self.f.wait_respawn()
        if not self.start_fresh():
            return "휴식 실패"
        ok, r = self.pass_ramp()
        if not ok:
            return f"경사로 {r}"
        r = self.to_merchant()
        if r != "도착":
            return f"상인 {r}"
        return self.light_burg_bonfire()

    def burg_bonfire_round_trip(self) -> str:
        """Ramp → merchant → walk to the Undead Burg bonfire, then walk back to Firelink Shrine without resting (user 2026-09-25:
        "Don't rest at the bonfire, make it walk back"). Not sitting at the bonfire keeps the respawn point unchanged, so the next run also just starts by walking."""
        if not self.f.alive():
            self.f.wait_respawn()
        if not self.start_fresh():
            return "휴식 실패"
        ok, r = self.pass_ramp()
        if not ok:
            return f"경사로 {r}"
        r = self.to_merchant()
        if r != "도착":
            return f"상인 {r}"
        nb = self.nms[MAP_B]
        _, _, R = _route()
        self.f.home = tuple(R["b"][0])
        r = self.f.walk_to(BURG_BONFIRE_SIDE, nb, "화톳불로")
        if r != "arrived":
            return f"화톳불까지 {r}"
        self.log("── 성벽 마을 화톳불: 쉬지 않고 돌아간다")
        return self.to_firelink()
