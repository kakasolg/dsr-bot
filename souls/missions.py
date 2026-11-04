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
from types import SimpleNamespace as NS

import nav

from . import moves as M
from .field import Field, plain_nm

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
# 구역 끝 드롭 줍기(Missions._loot)를 하지 않는 구역 — 구역 8: 탑 위 좁은 턱(P-47)·석궁병 둘이 남는 구역이고 바로 앞이
# 타우로스 안개벽이라, 드롭 때문에 턱 위를 걸어 다니거나 보스 쪽으로 가지 않는다 (게임 확인 없이 정한 제외)
LOOT_SKIP_ZONES = {8}
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
# ── 던지기 (run.py --throw, [MoKa] 2026-10-12 "투척 아이템 구매했으니 … 소머리데몬 가는 길에 적들에게 사용") ─────────────
#  임시값 — 첫 시험용. 나이프: 달려가 깨우기 전에 Field.lure(안전 자리에서 / 길 따라 10 m 안까지 가서 락온 투척).
#  화염병: 안전 자리로 깨어 오는 적이 둘 이상이고 가장 가까운 놈이 FB_MIN_R~FB_MAX_R → 그놈에게 (범위 피해),
#  구역 시작 때 턱 위 화염병 망자(UPPER_IGNORE 자리)가 FB_LEDGE_R 안 → 그놈에게. 각각 FB_MAX_THROWS개까지
FB_MIN_R, FB_MAX_R = 4.0, 10.0
FB_LEDGE_R = 12.0
FB_MAX_THROWS = 2
UPPER_MOVED_M = 0.5      # a target counts as awake once it has an anim and is this far off where it stood
UPPER_WALK_M = 1.0       # running in: any foe on our level this far off where we first saw it is walking (anim reads −1 while walking, P-127)
UPPER_CLOSE_R = 3.0      # running in: stop this close even if it hasn't woken…
UPPER_NOTICE_S = 2.0     # …and stand guarding this long for it to notice, then run back anyway
SPRINT_BACK_M = 1.5      # _sprint(through): this much farther from the goal than the closest it got → stop and re-plan (P-113)
SPRINT_REPLANS = 3
SIP_GETUP_S = 3.0        # _sip_on_hit: wait at most this long to get up (my anim in HIT_STUN) before drinking
BARREL_FOE_R = 4.0     # _barrel: a live foe this close ends the guard-wait (try 12: the barrel soldier came down to 1.7 m)
UPPER_FOLLOW_R = 8.0   # _pull_to_safe: not at its spawn → the same type this close to me is the one that followed
UPPER_COME_R = 8.0      # a target already this close to the safe spot (or already moving) isn't run at — wait for it there
UPPER_NEAR_SAFE_R = 4.0  # within this of the safe spot, don't turn our back to run there — fight (10-06d died 2–3 m from it)
UPPER_TRIES = 4          # same target until dead, at most this many lure + fight rounds (a round may go to a foe that came along)
UPPER_ENCOUNTER_R = 10.0 # running in: any awake, moving foe on our level this close → turn back to the safe spot
UPPER_LURE_CROWD_R = 4.0 # a target with another live foe this close (same level) is lured with a knife, not by running in (below)
UPPER_LURE_CROWD_DY = 2.0
# ── 나이프는 송진 문 앞 병사들부터 ([MoKa] 11-02) ─────────────────────────────
#  "투척나이프를 황금송진 있는 문 앞에 병사들 있는데 부터 사용 해야함" — 구역 4 (문 (20.2, −5.7, −104.2) 2–5 m 안의 254010·254012·254011)부터.
#  11-02 try 15: 구역 1·2에서 락온이 안 걸려 0/5 던지고, 구역 2에선 그 사이 턱 화염병에 −666 → 사망 (P-117)
UPPER_KNIFE_FROM = 4
UPPER_HEAL_FRAC = 0.7    # before each lure: below this share of max HP, Estus first
LADDER_TRIES = 3         # zone 8 ladder: face + A + climb attempts
LADDER_TOP_SLACK_M = 1.5  # already up when y ≥ top_y − this: zone 8 tower floor 23.7 vs top_y 24.5 (11-01 230106 track), bottom 16.0 (P-108)
LADDER_BUSY_S = 4.5      # wait at most this for a roll / stagger / Estus to end before facing + A (235045: Estus 3.2 s, stun 2017 4 s)
LADDER_FREE_S = 0.15     # not busy this long in a row before facing + A
LADDER_FACE_DEG = 35.0   # body already this close to the ladder → no turn, A at once (A taken at 15–20° off, 10-31)
LADDER_TURN_S = 1.0      # turn toward the ladder at most this long before A (001740: 93° and 180° off after a stun)
LADDER_GRAB_S = 1.2      # after A, the mount anim (7010) must show within this — else no climb input
ROUTE_NEAR_M = 6.0       # _to_merchant: the nearest route point is walked to straight only this close …
ROUTE_DY_M = 1.5         # … and on our level — P-57: a ramp fight ending on the top platform (−20,−39.3,14.4) was 4.2 m from A0
                         # (the stair top, 3.3 m higher, reached around the east side); the straight walk ran into the ledge — a 1.5–2.6 s
                         # stall and a turn-around, in 4 of 15 seg 1-2 runs, and the same spot as the ramp-ledge falls (P-49 / P-58)


def off_route(here, q) -> bool:
    """Route point q can't be walked to in a straight line from here: too far, or on another level → path-find to it first."""
    return math.dist(here, q) > ROUTE_NEAR_M or abs(q[1] - here[1]) > ROUTE_DY_M
LADDER_CLIMB_S = 15.0    # …give one climb this long (souls/asylum CLIMB_S)
ROLL_M = 2.6             # a 'roll' before-step: floor this far ahead for each roll (design-floor-check §3-B 'roll'; track max 2.5 m)
ROLL_FOE_R = 10.0        # … foes this close are kept at a distance when the planned way has no floor
UPPER_SIP_FRAC = 0.7     # back at the safe spot: drink only below this share (10-06g spent one on 713/742; [MoKa] 90 → 80 → 70 %)
UPPER_SWING_R = 2.5      # …and not while a foe this close is mid-swing (10-06g: interrupted by a firebomb from 2.4 m)
CHEST_FOE_R = 8.0        # zone 'after' chest: an awake foe this close → don't go
CHEST_DOOR_TRIES = 2     # …A on the door (only while its state flag reads shut)
CHEST_DOOR_S = 2.5       # …wait for it to swing / the Master Key message (11-01: flag True 2.5 s after A)
CHEST_REACH_M = 0.75     # …the lid opened on A from 0.77 m, not from 2.4 m (item-pickup.md 11-01); 192523: 0.84 m, same side, faced → A ×3 nothing
CHEST_NUDGES = 10
CHEST_NUDGE_STICK = 0.7  # 11-01 183919: stick 0.3 only turned the body — 8 pulses, position unchanged at 1.34 m
CHEST_NUDGE_S = 0.2
CHEST_WINDOW_S = 2.0       # wait this long for the item window list before the closing A
CHEST_PRESSES = 3        # A (lid) → A (take); a third only if the flag still reads shut
CHEST_PRESS_S = 3.0
CHEST_TAP_S = 0.15       # …hold A this long, then release it ourselves (Pad.interact holds 0.1 s)
CHEST_ROUNDS = 2         # 11-01 fresh-save runs 183919·192523·234903: same spot/heading as the 214607 success, A ×3 nothing → guard off, face, again


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


def crowd_near(s, t, ptr) -> list:
    """
    ── 붙어 선 적은 몸으로 안 끌어옴 ([MoKa] 2026-10-12 "적이 다수가 있는데, 거기에 가서 불리한 싸움을 하는 이유는?") ──
     · 10-12 align2 구역 4: 254010 · 254012 · 254011이 1.9–3.4 m 붙어 섬 → 몸으로 달려가 셋 다 깨움 → 1:2 사망 (P-78)
     · 목표에서 UPPER_LURE_CROWD_R 안, 같은 층(UPPER_LURE_CROWD_DY)에 살아 있는 다른 적 → 나이프 유인 (Field.lure, --throw 없이도)
    """
    if s is None or not hasattr(s, "hostile"):
        return []
    return [o for o in s.hostile(60.0) if o.ptr != ptr and o.hp > 0 and abs(o.y - t.y) < UPPER_LURE_CROWD_DY
            and math.hypot(o.x - t.x, o.z - t.z) < UPPER_LURE_CROWD_R]


class Missions:
    def __init__(self, fld: Field, nms: dict, log=print, lure: bool = True):
        self.f, self.nms, self.log = fld, nms, log
        self.lure = lure                                  # False = --no-lure (every mission that clears the ramp, not just clear-ramp)
        self.throw = False                                # run.py --throw: knives / firebombs on the way to the Taurus (burg-upper)
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
                if ok and getattr(self.f, "loot", None) is not None:
                    self.f.loot.reset("warp")
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
        self._loot(self.nms[MAP_A], "경사로", back=RAMP_ARENA)   # the arena: pass_ramp's survivor check and the next walk start there
        return r

    def firelink_humanity(self) -> dict | None:
        """불의 제전 화톳불 옆 인간성 ×3 시체(loot.TREASURES) — 쉬고(레벨업) 난 뒤 경사로 전에 ([MoKa] 11-01 "먼저 레벨업 하고,
        humanity 아이템 확보 하는 것도 점검"). 이미 주웠으면(ItemFlag) 걷지 않는다. Off (--no-loot) → None."""
        lt = getattr(self.f, "loot", None)
        if lt is None or not lt.on or not self.f.alive():
            return None
        from . import loot as loot_
        r = self.f.pick_treasure(self.nms[MAP_A], loot_.TREASURES["firelink-humanity"])
        self.log(f"── 인간성 시체: {r['result']}")
        return r

    def _loot(self, nm, tag: str, back=None) -> None:
        """Pick up enemy drops here, after this stop's own fights (Field.loot, souls/loot.py — one book per run, baseline at run
        start / rest / respawn / warp / quit-out). Off (--no-loot) → nothing at all. back=None: the next step's walk finds its
        way from wherever the pickups ended (walk / careful_walk_to / to_merchant re-find the nearest path point)."""
        lt = getattr(self.f, "loot", None)
        if lt is None or not lt.on or not self.f.alive():
            return
        r = lt.collect(nm, tag, back=back)
        self.log(f"── {tag} 드롭: {r}")

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
        self._loot(nb, "성벽 마을")
        return "cleared"

    def upper_zone(self, n: int) -> str:
        """Zone n of the Burg bonfire → fog wall stretch (UPPER): walk carefully to the zone's safe spot (a marked fall-back spot
        and the fight tether while the zone runs), then for each foe in MoKa's kill order go wake it and fight it back there."""
        nb = self.nms[MAP_B]
        z = UPPER["zones"][n - 1]
        safe = tuple(z["safe"])
        self.zone_n = n
        # home = where recover() backs off to drink. Not the safe spot (10-06d: already there, foe on us → never drank) and not
        # the run's default (Firelink — another NavMesh, no path) → the Undead Burg bonfire
        home0, self.f.home = self.f.home, BURG_BONFIRE_SIDE
        # 10-06b 구역 2: 255001이 깨우러 가는 걸음 중간에 따라붙어, 걷기의 '따라온 놈' 싸움이 안전 자리 13 m 앞(턱 화염병 9 m)에서 바로 시작 → 사망.
        # 걷기는 따라온 놈을 싸우기 전에 찍어 둔 자리(ZONE_REACH 15 m 안)로 가드 든 채 물러나므로, 이 구역 동안 안전 자리를 거기 넣는다
        # [MoKa]: "적이 붙으면 그 다음에 안전 구역으로 가야 하는데, 그냥 있으면 화염폭탄에 맞아서 죽지" → 싸움 도중에도 벗어나면 끊고 돌아옴 (Field.fight tether)
        zones0, tether0 = getattr(self.f, "extra_zones", ()), getattr(self.f, "tether", None)
        no_safe = bool(z.get("no_safe"))                  # 구역 3 — [MoKa] "적이 하나씩 만나니깐 그냥 공격 … 안전 구역 자체가 필요 없어"
        self.f.extra_zones, self.f.tether = ((), None) if no_safe else ((safe,), safe)
        w0 = getattr(getattr(self.f, "esc", None), "warps", 0)
        try:
            past = self._past_before(z)
            if past:
                # 11-01 231119 (P-108): 탑 위에서 --seg 8 시작 → fog 단계가 3D 거리로 '안개벽 앞'이라 보고 걸어가다 사다리 꼭대기에서 9 m 낙하.
                #  사다리 꼭대기 높이면 안개벽·사다리는 이미 지난 것 — before 단계(에스트 채우기 포함)를 통째로 건너뜀
                self.log(f"   구역{n}: 이미 사다리 꼭대기 높이 (y {past:.1f}) — 안개벽·사다리 단계 건너뜀")
            elif z.get("before") and not self._top_up(nb, f"구역{n}"):   # fog wall · ladder ahead — no fighting there, drink first
                return "no_estus"
            landed = None
            for step in ([] if past else z.get("before", [])):
                self._landed = None
                r = self._before(step, nb, f"구역{n}")
                if r == "dead":
                    return "died"
                if r != "ok":
                    return f"{next(iter(step))} {r}"
                if step.get("roll", {}).get("safe_after") and self._landed is not None:
                    landed = self._landed
            if landed is not None and not no_safe:
                # P-47: the ladder top is the narrow ledge — the safe spot / tether is where the rolls landed, not back there
                safe = landed
                self.f.extra_zones, self.f.tether = (safe,), safe
                self.log(f"   구역{n}: 구른 자리 ({safe[0]:.1f},{safe[1]:.1f},{safe[2]:.1f})를 안전 자리로")
                r = "arrived"
            elif no_safe:
                r = "arrived"
            elif z.get("run_to_safe"):
                r = self._sprint(safe, nb, None, through=z.get("run_to_safe") == "through")
                r = "dead" if r == "dead" else ("arrived" if r in ("arrived", "stopped") else r)
            else:
                r = self.f.careful_walk_to(safe, nb, f"구역{n} 안전 자리")
            if r == "dead":
                return "died"
            if self._warped(w0, f"구역{n} 안전 자리"):
                return "warped"
            if r != "arrived":
                self.log(f"   구역{n} 안전 자리까지 {r} — 지금 자리에서 이어감")
            self._firebomb_ledge(f"구역{n}")
            # 11-01 183919 ([MoKa] "처음에 문 안열고 들어가려다 못여니깐 … 병사들 해치우고 그다음에 문 연거야"): 255000 유인 길이
            # 닫힌 문 1011310을 지나 문 앞 (19.9,−103.7)에서 7 s 막힘 → 문이 있는 'after' 단계는 적보다 먼저 문만 연다
            for step in z.get("after", []):
                st = step.get("chest") or {}
                if st.get("door_first") and self.mv.tm.event_flag(int(st["door_flag"])) is not True:
                    r = self._open_door(st, nb, f"구역{n}")
                    if r == "dead":
                        return "died"
                    if self.f.careful_walk_to(safe, nb, f"구역{n} 안전 자리") == "dead":
                        return "died"
            left = []
            for i, k in enumerate(z["kills"], 1):
                if not self.f.alive():
                    return "died"
                if self._warped(w0, f"구역{n}"):
                    return "warped"
                npc, pos, how = k[0], k[1], (k[2] if len(k) > 2 else {})
                r = self._pull_to_safe(npc, tuple(pos), safe, nb, f"구역{n}-{i} {npc}", how)
                if r in ("died", "no_estus"):
                    return r
                if self._warped(w0, f"구역{n}-{i}"):
                    return "warped"
                if r not in ("killed", "gone"):
                    left.append(f"#{i} {npc} {r}")
            if n not in LOOT_SKIP_ZONES:                   # still inside the zone: a pickup fight keeps its home · tether
                self._loot(nb, f"구역{n}")
            # 11-02 P-105: 상자 단계(구역 5)가 생긴 뒤 구역 6 255001이 계단 위에서 화염병 4번 — 예전(10-11~13, 6/6 피해 0)처럼 구역 6을
            #  먼저 하고 상자는 그 뒤에 (take_in). 문은 위 door_first 그대로 구역 5에서 연다
            chests = [st["chest"] for zz in UPPER["zones"] for st in zz.get("after", [])
                      if "chest" in st and int(st["chest"].get("take_in", zz["n"])) == n]
            for st in chests:
                if self._chest(st, nb, f"구역{n}") == "dead":
                    return "died"
        finally:
            self.f.home = home0
            self.f.extra_zones, self.f.tether = zones0, tether0
        if left:                                       # 10-06 구역 8: 석궁 둘이 살아 있는데 'cleared' (P-47)
            self.log(f"── 구역{n}: 끝 — 남은 적 {', '.join(left)}")
            return "left " + " ".join(s.split()[0] for s in left)
        self.log(f"── 구역{n}: 끝")
        return "cleared"

    def _warped(self, w0: int, tag: str) -> bool:
        """
        ── 워프 뒤엔 구역을 이어 가지 않음 (P-126) ─────────────────────
         · 11-04 015007: 3놈 몰림 → 화톳불 워프는 됐는데, 못 잡은 놈을 '죽음'으로 지우고 38 m 걸어 같은 무리로 돌아가 사망.
           워프는 적을 원위치로 안 돌림 — 깨어 있는 채 그 자리에 남음
         · [MoKa] 11-04 "리셋하고 다시 하는 거지" → 'warped'를 돌려주면 afterdeath.run_zones가 화톳불 휴식 (구역 1)부터 다시
        """
        w = getattr(getattr(self.f, "esc", None), "warps", 0)
        if w == w0:
            return False
        self.log(f"   {tag}: 화톳불로 워프됨 — 이 구역 그만, 쉬어서 적 리셋 뒤 처음부터")
        return True

    def _zone_foe(self, npc: int, pos):
        """The zone's foe of type npc: near its spawn, else the same type next to me; never one on the firebomb ledge."""
        c = self.f.find_at(npc, pos, 8.0) or self.f.find_at(npc, pos, 20.0)
        if c is None:
            # 11-02 try 12: 구역 6 통 병사가 계단 위 스폰(y 0.9)에서 안전 자리(y −9.1)까지 내려와 붙었는데 스폰 3 m 높이 안만 찾아
            #  '안 보임 — 이미 잡았거나 죽음' → 구역 7로 넘어가 HP 326으로 싸우다 사망. 스폰에 없으면 내 옆도 봄
            s = self.mv.snap(10.0)
            if s is not None:
                c = self.f.find_at(npc, (s.player.x, s.player.y, s.player.z), UPPER_FOLLOW_R)
        if c is not None and any(math.dist((c.x, c.y, c.z), q) < UPPER_IGNORE_R for q in UPPER_IGNORE):
            c = None
        return c

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
        c = self._zone_foe(npc, pos)
        if c is None:
            self.log(f"   {tag}: 안 보임 — 이미 잡았거나 죽음")
            return "gone"
        ptr = c.ptr
        res = None
        if (how or {}).get("hold"):
            # ── 구역 8 석궁: 녹화처럼 달려가 기다리기 (MoKa 11-01 "녹화처럼 달려가 기다리기") ──────────────
            #  녹화 151317: 꼭대기에서 동쪽 F9#8까지 11 m 달림 → 석궁 둘이 따라와 근접에서 처치. 구르기 2번 + 붙기(P-47)는
            #  사거리 6–9 m에서 끝나 붙는 중에 맞았고, low_hp 후퇴는 탁 트인 탑 위에서 계속 맞음(12런 중 사망 4, P-103).
            #  → 안전 자리(F9#8)에서 가드 들고 기다림, 오면 물러나지 않고(desperate) 싸움, 사이사이 에스트(Field.desperate 포함).
            #  기다려도 안 오면 그때 붙음.
            if not self._wait_at_safe(ptr, safe, float(how["hold"])):
                self.log(f"   {tag}: {how['hold']} s 기다려도 안 옴 — 붙음")
            for k in range(UPPER_TRIES):
                if not self.f.alive():
                    return "died"
                t = self.mv.find(self.mv.snap(200.0), ptr)
                if t is None or t.hp <= 0:
                    return "killed"
                foe = self._first_foe(ptr)
                res = self.f.fight(foe, nb, tag if foe == ptr else f"{tag}: 같이 온 놈", desperate=True)
                if res.result == "me_dead":
                    return "died"
                self.f.heal(UPPER_HEAL_FRAC)
            t = self.mv.find(self.mv.snap(200.0), ptr)
            return "killed" if t is None or t.hp <= 0 else res.result
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
            if not self.f.alive():                         # P-68: _top_up's back-off toward the bonfire can end in death
                return "died"
            t = self.mv.find(self.mv.snap(200.0), ptr)
            if t is None or t.hp <= 0:
                self.log(f"   {tag}: 죽음")
                return "killed"
            if self._lure(t, ptr, safe, nb, tag, how or {}) == "died":
                return "died"
            self._drink_back(tag)
            self._firebomb_group(tag)
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

    def _chest(self, st: dict, nb, tag: str) -> str:
        """Zone 'after' step: open a door by its state flag, walk to a treasure chest, take what's in it, put `item` in a quick slot.
        → 'taken' | 'already' | 'dead' | why it stopped

        ── 구역 5 문 → 宝箱01 황금송진 ([MoKa] 11-01 "문열고 황금 송진 잡는 것도 … 루틴에 적용해줘") ──────────────
         문 1011310은 상태 플래그(61010510) False일 때만 A — 열린 문에 A면 다시 닫힘. 11-01 180933 뒤엔 잠긴 문이라 A에 "Used Master Key".
         상자는 2.4 m에선 A가 안 먹고 ~0.8 m 앞에서 A(뚜껑) → A(꺼내기, 송진 0→3, 플래그 51010460 True) → A(창 닫기) (docs/item-pickup.md).
         같은 날 스크래치 스크립트는 문에서 먼 자리에서 '문 A'를 눌러 바닥의 화염병을 주웠다 — 그래서 문 앞에 선 뒤에만 누른다."""
        tm = self.mv.tm
        item, flag = int(st["item"]), int(st["flag"])
        if tm.event_flag(flag) is True:
            self.log(f"   {tag} 상자: 이미 열었음 (플래그 {flag}) — {item} {tm.goods_count(item)}개")
            return "already"
        s = self.mv.snap(15.0)
        awake = [c for c in s.hostile(CHEST_FOE_R + 2.0) if c.hp > 0 and (c.anim or -1) != -1
                 and M.horiz(s.player, c) < CHEST_FOE_R] if s is not None else []
        if awake:
            self.log(f"   {tag} 상자: {awake[0].npc_param} {M.horiz(s.player, awake[0]):.1f} m — 안 감")
            return "foe"
        r = self._open_door(st, nb, tag)
        if r != "open":
            return r
        box = tuple(st["chest"])
        r = self.f.walk_to(tuple(st["stand"]), nb, f"{tag} 상자 앞")
        if r == "dead" or not self.f.alive():
            return "dead"
        last, stuck = None, 0
        for _ in range(CHEST_NUDGES):                      # NavMesh ends 1.5 m off the chest; the lid needs ~0.8 m
            s = self.mv.snap(5.0)
            d = M.horiz(s.player, NS(x=box[0], z=box[2])) if s is not None else None
            if d is None or d <= CHEST_REACH_M:
                break
            stuck = stuck + 1 if last is not None and last - d < 0.03 else 0
            if stuck >= 2:                                 # against the chest's collision — A from here
                break
            last = d
            self.mv.pad.move(*self.mv.stick_to(s, box[0], box[2], CHEST_NUDGE_STICK))
            time.sleep(CHEST_NUDGE_S)
            self.mv.pad.move(0.0, 0.0)
            time.sleep(0.25)
        s = self.mv.snap(5.0)
        if s is not None:
            self.log(f"   {tag} 상자: 밀기 뒤 상자까지 {M.horiz(s.player, NS(x=box[0], z=box[2])):.2f} m")
        n0 = tm.goods_count(item) or 0
        for rnd in range(CHEST_ROUNDS):
            # 11-01 234903: 잘 된 214607과 같은 자리·방향인데 A 세 번에 아무 일 없음 — 그때 화면을 못 봄.
            #  가드 유지(LB)를 풀고 다시 돌아서 누르고, 누를 때마다 안내창 값·화면을 남겨 다음에 원인을 본다
            self.mv.pad.unkeep()
            self.mv.pad.neutral()
            self._face_pulses(box)
            for k in range(CHEST_PRESSES):
                self._chest_look(tag, f"{rnd + 1}-{k + 1}")
                self._press_a()
                time.sleep(CHEST_PRESS_S)
                if tm.event_flag(flag) is True:
                    break
            if tm.event_flag(flag) is True:
                break
            self.log(f"   {tag} 상자: {rnd + 1}회차 A {CHEST_PRESSES}번 — 플래그 그대로")
        got = tm.event_flag(flag) is True
        if got:
            import drops
            # 11-01 214607: 플래그가 True가 된 직후엔 창 목록이 아직 비어 있어 A를 안 눌렀고, 'Gold Pine Resin 3' 창을 띄운 채 구역 6 싸움으로 감
            t_end = time.time() + CHEST_WINDOW_S
            while not drops.itemget_nodes(tm) and time.time() < t_end:
                time.sleep(0.1)
            self._press_a()                                # close the item window (pressed even if the list never read)
            time.sleep(1.0)
        n1 = tm.goods_count(item) or 0
        quick = None
        if got and st.get("quick"):
            import steam_state
            quick = (tm.equip_quick_item(item) if steam_state.check().get("offline") is True else "Steam 오프라인 아님")
        s = self.mv.snap(5.0)
        d = M.horiz(s.player, NS(x=box[0], z=box[2])) if s is not None else None
        self.log(f"   {tag} 상자: {'꺼냄' if got else '못 꺼냄'} — {item} {n0}→{n1}, 플래그 {flag} = {tm.event_flag(flag)}, "
                 f"상자까지 {d if d is None else round(d, 2)} m, 퀵슬롯 {quick}")
        self.f.events("chest", tag=tag, item=item, before=n0, after=n1, flag=tm.event_flag(flag), quick=quick)
        return "taken" if got else "not taken"

    def _press_a(self) -> None:
        """A tap released here — tap only schedules the release and no fight loop runs release_due at a door or chest.
        11-02 002536: A 1 opened the lid, the A stayed down, A 2·3 'Pillage' never got a fresh press (P-110)."""
        self.mv.pad.interact()
        time.sleep(CHEST_TAP_S)
        self.mv.pad.release_due()

    def _chest_look(self, tag: str, k: str) -> None:
        """Before an A at the chest: log the bottom prompt box reading and keep a screenshot in data/runs (best effort)."""
        try:
            import screen_prompt
            import shot
            px = screen_prompt.prompt_px()
            path = Path(__file__).resolve().parent.parent / "data" / "runs" / f"chest_{time.strftime('%Y%m%d_%H%M%S')}_{k}.png"
            shot.shot(path)
            self.log(f"   {tag} 상자: A {k} 전 안내창 {px} ({'있음' if px >= 850 else '없음'}) · {path.name}")
        except Exception as e:                               # no window / no display — the press goes ahead anyway
            self.log(f"   {tag} 상자: A {k} 전 화면 못 봄 ({e})")

    def _open_door(self, st: dict, nb, tag: str) -> str:
        """A on st's door only while its state flag reads shut (A on an open door shuts it). → 'open' | 'dead' | 'door shut'"""
        tm = self.mv.tm
        door, front, dflag = tuple(st["door"]), tuple(st["door_front"]), int(st["door_flag"])
        for k in range(CHEST_DOOR_TRIES):
            if tm.event_flag(dflag) is True:
                break
            r = self.f.walk_to(front, nb, f"{tag} 문 앞")
            if r == "dead" or not self.f.alive():
                return "dead"
            self.f._settle(front, tol=0.4)
            self._face_pulses(door)
            self._press_a()
            time.sleep(CHEST_DOOR_S)
            self.log(f"   {tag} 문: A ({k + 1}/{CHEST_DOOR_TRIES}) → 플래그 {dflag} = {tm.event_flag(dflag)}")
        return "open" if tm.event_flag(dflag) is True else "door shut"

    def _face_pulses(self, t, n: int = 4) -> None:
        """Turn toward t with short weak stick pulses (barely moves) — doors and chests take A only when faced."""
        for _ in range(n):
            s = self.mv.snap(5.0)
            if s is None or s.cam_yaw is None:
                return
            self.mv.pad.move(*self.mv.stick_to(s, t[0], t[2], 0.3))
            time.sleep(0.12)
            self.mv.pad.move(0.0, 0.0)
            time.sleep(0.25)

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

    def _has(self, item: int) -> bool:
        """Held and in a quick slot (the bot can only pick quick-slot items)."""
        quick = getattr(self.mv.tm, "quick_items", None)
        return (self.mv.tm.goods_count(item) or 0) > 0 and (not callable(quick) or item in (quick() or []))

    def _firebomb(self, ptr, tag: str, why: str) -> dict:
        r = self.mv.throw_firebomb(ptr)
        self.log(f"   {tag}: 화염병 ({why}) — {r.get('dist')} m, 락온 {r.get('locked')} → 피해 {r.get('hit')}"
                 f"{' | ' + r['why'] if r.get('why') else ''}")
        self.f.events("throw", item="firebomb", why=why, **{k: r.get(k) for k in ("dist", "locked", "hit", "woke", "knives")})
        return r

    def _firebomb_group(self, tag: str) -> None:
        """At the safe spot: two or more awake foes coming and the nearest FB_MIN_R–FB_MAX_R away → firebomb the nearest."""
        if not getattr(self, "throw", False):
            return
        for _ in range(FB_MAX_THROWS):
            if not self._has(M.ITEM_FIREBOMB):
                return
            s = self.mv.snap(FB_MAX_R + 4.0)
            if s is None:
                return
            p = s.player
            come = sorted((c for c in s.hostile(FB_MAX_R + 1.0) if c.hp > 0 and c.anim not in (None, -1)
                           and not 9000 <= (c.anim or 0) < 9100 and abs(c.y - p.y) < 2.5 and M.horiz(p, c) <= FB_MAX_R),
                          key=lambda c: M.horiz(p, c))
            if len(come) < 2 or M.horiz(p, come[0]) < FB_MIN_R:
                return
            r = self._firebomb(come[0].ptr, tag, f"{len(come)}명 다가옴, 가장 가까운 {come[0].npc_param} {M.horiz(p, come[0]):.1f} m")
            if not r.get("ok"):
                return

    def _firebomb_ledge(self, tag: str) -> None:
        """Zone start: a ledge firebomb hollow (UPPER_IGNORE spots — out of reach) within FB_LEDGE_R → firebombs at it."""
        if not getattr(self, "throw", False):
            return
        for _ in range(FB_MAX_THROWS):
            if not self._has(M.ITEM_FIREBOMB):
                return
            s = self.mv.snap(FB_LEDGE_R + 6.0)
            if s is None:
                return
            p = s.player
            led = [c for c in s.hostile(FB_LEDGE_R + 6.0) if c.hp > 0 and M.horiz(p, c) <= FB_LEDGE_R
                   and any(math.dist((c.x, c.y, c.z), q) < UPPER_IGNORE_R for q in UPPER_IGNORE)]
            if not led:
                return
            c = min(led, key=lambda c: M.horiz(p, c))
            r = self._firebomb(c.ptr, tag, f"턱 위 {c.npc_param} {M.horiz(p, c):.1f} m, 높이 {c.y - p.y:+.1f}")
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

        def target(sn):
            # P-75: not in sn ≠ gone — a walk's snapshot reads 30 m (nav.goto) and zone 2-2's 254011 stood 30.5 m out, so the
            # run in "met" it on its first tick and never left the safe spot; ask a wide snapshot before calling it dead
            c = self.mv.find(sn, ptr)
            return c if c is not None else self.mv.find(self.mv.snap(200.0), ptr)

        seen: dict = {}

        def walking(sn) -> bool:
            # P-127: 걷는 적은 애니가 −1로 읽힘 — 023349 구역 2: 255001 (−1,−95)→(−7,−93) 5 s 동안 전부 −1, 254011 둘도 −1인 채 다가옴
            #  → 애니만 보던 met()가 못 봐서 1–2 m까지 달려 들어감. 처음 본 자리에서 UPPER_WALK_M 넘게 옮긴 놈 = 움직이는 중
            p = sn.player
            for c in getattr(sn, "hostile", lambda r: [])(UPPER_ENCOUNTER_R):
                if c.hp <= 0 or abs(c.y - p.y) >= 2.5:
                    continue
                x0 = seen.setdefault(c.ptr, (c.x, c.z))
                if math.hypot(c.x - x0[0], c.z - x0[1]) > UPPER_WALK_M:
                    return True
            return False

        def met(sn) -> bool:
            c = target(sn)
            return c is None or c.hp <= 0 or woke(c) or any(e.ptr != ptr for e in self._encounters(sn, ptr)) or walking(sn)

        def stop_in(sn) -> bool:
            c = target(sn)
            return met(sn) or (c is not None and M.horiz(sn.player, c) < UPPER_CLOSE_R)

        crowd = crowd_near(self.mv.snap(200.0), t, ptr)
        failed = getattr(self, "knife_failed", set())
        knife_zone = getattr(self, "zone_n", UPPER_KNIFE_FROM) >= UPPER_KNIFE_FROM
        if (getattr(self, "throw", False) or crowd) and knife_zone and ptr not in failed and not how.get("lure_at")                 and self._has(M.ITEM_KNIFE):
            if crowd and not getattr(self, "throw", False):
                self.log(f"   {tag}: 옆에 {len(crowd)}명 붙어 있음 ({', '.join(f'{o.npc_param} {math.hypot(o.x - t.x, o.z - t.z):.1f} m' for o in crowd)}) — 몸 대신 나이프로")
            lr = self.f.lure(ptr, here0, nb, tag, arena=safe)     # from the safe spot, or up to 10 m along the path, locked on
            self.log(f"   {tag}: 나이프 유인 → {lr}")
            if not self.f.alive():
                return "died"
            if lr in ("lured", "awake", "dead", "interrupted"):
                s = self.mv.snap(5.0)
                if s is not None and math.hypot(s.player.x - safe[0], s.player.z - safe[2]) > UPPER_NEAR_SAFE_R:
                    back = self._sprint(safe, nb, lambda sn: math.hypot(sn.player.x - safe[0], sn.player.z - safe[2]) < 1.5)
                    self.log(f"   {tag}: 나이프 뒤 안전 자리로 {back}")
                    if back == "dead":
                        return "died"
                return "here"
            # no_knife / no_path / no_spot / too_far / no_reaction / no_lock → the body run below, and no knife at this one again
            #  (P-117: 구역 2-1에서 같은 놈에게 두 번 서서 시도하는 사이 화염병 −222 · −111)
            self.knife_failed = failed | {ptr}
        goal = tuple(how["lure_at"]) if how.get("lure_at") else here0
        s = self.mv.snap(5.0)
        hp0 = s.player.hp if s is not None else None
        if self._sprint(goal, nb, stop_in) == "dead":
            return "died"
        if how.get("sip_on_hit") and hp0 is not None and self._sip_on_hit(hp0, float(how["sip_on_hit"]), tag) == "dead":
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

    def _barrel(self, st: dict, nb, tag: str) -> str:
        """
        ── 구역 6 계단 불타는 통 (P-105, 11-02 024657 화면 캡처) ─────────────────────────────────────
         · −336(애니 2026 넘어짐)은 병사가 계단 위에서 굴린 불붙은 통 — 11-01~02 구역 6 9번 모두 같은 계단에서 맞음.
           계단은 난간과 벽 사이로 좁아 옆으로 비킬 데가 없음
         · [MoKa] 11-02 "계단이 꺽이는 지점에서 5m 정도 올라 가면 굴리는데 그게 몇 m인지 몰라" — 꺾이는 곳 (39.1, −5.0, −114.6)에서
           4.9 m인 (43.3, −2.6) = 010036이 멈춘 뒤 ~1 s에 맞은 자리. 022918은 41.4까지 아무 일 없고 43.7을 지나 ~1 s 뒤 46.5에서 맞음
         · trigger까지 걸어가 통을 부르고, 기다리지 않고 back(모퉁이 뒤 안전 자리)으로 달려 wait 초 가드 들고 기다린 뒤 원래 순서로
         · [MoKa] "일단 피해본다, 맞으면 바로 마신다" — 이 사이 sip_on_hit 넘게 잃으면 일어나자마자 한 모금 (_sip_on_hit)
        """
        trig, back, wait = tuple(st["trigger"]), tuple(st["back"]), float(st.get("wait", 6.0))
        s = self.mv.snap(5.0)
        hp0 = s.player.hp if s is not None else None
        sip = float(st["sip_on_hit"]) if st.get("sip_on_hit") else None
        r = self.f.walk_to(trig, nb, f"{tag} 통 부르기")
        if r == "dead" or not self.f.alive():
            return "dead"
        drank = None
        if sip and hp0 is not None:                        # hit on the way up — drink there, not after the 20 m run back
            drank = self._sip_on_hit(hp0, sip, tag)
            if drank == "dead":
                return "dead"
        # 11-02 try 12: 마신 뒤 또 맞아도(−237) 한 번 마셨다고 건너뜀 → 326으로 구역 7 → 사망. 마신 뒤 HP를 새 기준으로 다시 봄
        base = hp0
        if drank == "drank":
            s = self.mv.snap(5.0)
            base = s.player.hp if s is not None else None
        r = self._sprint(back, nb, None, through=True)
        if r == "dead" or not self.f.alive():
            return "dead"
        if sip and base is not None and self._sip_on_hit(base, sip, tag) == "dead":
            return "dead"
        guard = getattr(self.mv.pad, "guard", lambda on: None)
        guard(True)
        try:
            t0 = time.time()
            while time.time() - t0 < wait:
                if not self.f.alive():
                    return "dead"
                # 11-02 try 12: 통 굴린 병사(255001)가 내려와 기다리는 중에 1.7 m에서 −237 → 오면 기다림 끝, kills 순서가 싸움
                s = self.mv.snap(10.0)
                near = [c for c in (s.chars if s is not None else ()) if c.hp > 0 and M.horiz(s.player, c) < BARREL_FOE_R]
                if near:
                    self.log(f"   {tag}: 기다리는 중 {near[0].npc_param} {M.horiz(s.player, near[0]):.1f} m — 기다림 끝")
                    break
                time.sleep(0.2)
        finally:
            guard(False)
        s = self.mv.snap(5.0)
        self.log(f"   {tag}: 통 부르고 물러나 {wait:.0f} s 기다림 — HP {hp0} → {s.player.hp if s is not None else None}")
        return "ok"

    def _sip_on_hit(self, hp0: int, frac: float, tag: str) -> str | None:
        """
        ── 큰 한 방 맞으면 그 자리에서 바로 에스트 (P-105, [MoKa] 11-02 "죽지 않으니 맞으면 바로 에스트 마시는게 더 나은 방법이야") ──
         · 구역 6 계단: 병사가 굴린 불붙은 통 −336 (11-01~02 9번 모두). 피하기(계단을 올라갔다 내려오기)는 영상 없이 시점을 못 맞춰
           부작용만 난다고 MoKa가 봄 → 맞고, 넘어진 데서 일어나자마자 한 모금
         · 유인 달리기 동안 max HP × frac 넘게 잃었을 때만. 휘두르는 적이 있어도 미루지 않음(_drink_back의 UPPER_SWING_R 예외와 다름) —
           022918은 미뤘다가 255001 3004 −237 → 사망
        → 'dead' | 'drank' | None (no big hit / no Estus)"""
        s = self.mv.snap(15.0)
        if s is None or hp0 - s.player.hp < s.player.max_hp * frac:
            return None
        t0 = time.time()
        while s is not None and (s.player.anim or -1) in M.HIT_STUN and time.time() - t0 < SIP_GETUP_S:
            time.sleep(0.05)
            s = self.mv.snap(15.0)
        if not self.f.alive():
            return "dead"
        if self.f.estus_left() <= 0:
            self.log(f"   {tag}: 큰 피격 (HP {hp0} → {s.player.hp if s else '?'}) — 에스트 없음")
            return None
        r = self.mv.drink(lambda _s: True)
        self.log(f"   {tag}: 큰 피격 (HP {hp0} → {r.get('hp', [None])[0]}) — 그 자리에서 에스트: {r}")
        self.f.events("estus", **r)
        return "drank" if self.f.alive() else "dead"

    def _past_before(self, z: dict) -> float | None:
        """The zone's before steps end with a ladder and we already stand at its top height → our y, else None."""
        ladders = [st["ladder"] for st in z.get("before", []) if "ladder" in st]
        if not ladders:
            return None
        s = self.mv.snap(5.0)
        if s is None or s.player.y < float(ladders[-1]["top_y"]) - LADDER_TOP_SLACK_M:
            return None
        return s.player.y

    def _before(self, step: dict, nb, tag: str) -> str:
        """A zone's 'before' step (구역 8, [MoKa] "안개벽 지나서, 사다리 타고 올라가서"). → 'ok' | 'dead' | 'fail' | walk result
          fog: walk to front, settle, fog_through toward beyond (known wall — A without the prompt check), as souls/asylum does
          ladder: walk to bottom, face `face`, A, stick up until top_y, keep pushing to step off (souls/asylum._climb)
          roll: roll n times toward `toward`, each only with floor ROLL_M ahead; 'safe_after' → where we land is the zone's
                safe spot / tether from here on (P-47, [MoKa] 10-06: "구르기를 2번 해서 석궁병하고 간격을 벌려야 해")"""
        if "roll" in step:
            return self._roll_away(step["roll"], nb, tag)
        if "barrel" in step:
            return self._barrel(step["barrel"], nb, tag)
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
            if not ok:
                # ── 보스를 이미 잡았으면 안개벽이 없음 (10-13 클레이모어 구역 1–8 둘째 런) ──
                #  타우로스를 잡은 캐릭터: A 두 번에 1.1 · 1.6 m만 움직이고(스틱 0.3 s씩) 'fog fail' — 벽이 없으면 그냥 걸어가면 됨.
                #  벽이 있으면 걷기가 막혀 그대로 실패
                r = self.f.walk_to(beyond, nb, f"{tag} 안개벽 자리 걸어서")
                ok = r == "arrived"
                if ok:
                    self.log(f"   {tag}: 안개벽 없음 (보스 처치 뒤?) — 걸어서 지나감")
            self.log(f"   {tag}: 안개벽 {'통과' if ok else '못 지나감'}")
            return "ok" if ok else "fail"
        st = step["ladder"]
        bottom, face, top_y = tuple(st["bottom"]), tuple(st["face"]), float(st["top_y"])
        s = self.mv.snap(5.0)
        if s is not None and s.player.y >= top_y - 0.6:
            self.log(f"   {tag}: 이미 사다리 위")
            return "ok"
        hp, mx = (getattr(s.player, "hp", None), getattr(s.player, "max_hp", None)) if s is not None else (None, None)
        if st.get("heal_first") and hp is not None and mx and hp < mx * float(st["heal_first"]):
            # ── 사다리 위는 석궁병 둘 사거리라 못 마심 (MoKa 11-01 "가)+나) 고치기") ──────────────
            #  214607: 72 %로 올라가 −162 · −162 · −81 → HP 116에서 '근처에 적 — 안 마심' 3번 → 사망 (P-103과 같은 꼴)
            self.log(f"   {tag}: 사다리 전 HP {hp}/{mx} — 에스트 먼저")
            self.f.heal(float(st["heal_first"]), sips=3)
        if st.get("approach"):                             # [MoKa]: "계단에서 내려 와서, 옆으로 붙어서" — the recorded line, not a diagonal
            r = self.f.walk([tuple(q) for q in st["approach"]], nb, f"{tag} 사다리 아래", tol=0.4)
        else:
            r = self.f.walk_to(bottom, nb, f"{tag} 사다리 아래")
        if r == "dead" or not self.f.alive():
            return "dead"
        self.f._settle(bottom, tol=0.4)
        for attempt in range(LADDER_TRIES):
            s = self._ladder_ready()
            # ── 이미 사다리를 보고 있으면 돌기 0.45 s를 건너뜀 (20261101_001326) ──────────────────
            #  구르기 뒤 몸이 사다리에서 15~20° (헤딩 −105°) — 돌기 스틱에도 헤딩은 그대로였고, 그 0.45 s 사이 3002에 맞음
            #  (710 끝 53.6 → A 54.62, 피격 54.51). 같은 헤딩에서 A는 바로 먹힘 (000637 54.6 → 7010 54.72).
            # ── 볼 때까지 돌기 (20261101_001740) ─────────────────────────────────────────────────
            #  경직 뒤 몸이 93°·180° 돌아가 있었는데 스틱 0.35 × 0.25 s로는 거의 안 돌아 A 두 번이 안 먹음 (64.72, 70.91).
            #  moves.face처럼 0.55로, 매번 새 스냅숏으로 LADDER_FACE_DEG 안에 들 때까지 (최대 LADDER_TURN_S) 돈 뒤 A.
            t_turn = time.time()
            turned = False
            while (s is not None and not self._ladder_dead(s) and s.cam_yaw is not None
                   and getattr(s.player, "heading", None) is not None
                   and abs(math.degrees(M.rel_angle(s.player, NS(x=face[0], z=face[2])))) > LADDER_FACE_DEG
                   and time.time() - t_turn < LADDER_TURN_S):
                self.mv.pad.move(*self.mv.stick_to(s, face[0], face[2], 0.55))
                turned = True
                time.sleep(0.05)
                s = self.mv.snap(5.0)
            if self._ladder_dead(s, tag):                  # 20261101_002546: HP 0 after the entry check, then A ×3 on the corpse
                self.mv.pad.neutral()
                return "dead"
            if turned:
                self.mv.pad.move(0.0, 0.0)
                time.sleep(0.1)
            self.mv.pad.interact()
            s = self._ladder_grabbed()
            if s is None:
                # ── A가 안 먹으면 스틱 위를 누르지 않는다 (10-31 225341 · 230111) ──────────────
                #  구르기(애니 710)가 1.5 s 이어지는 동안 누른 A는 무시됐고, 사다리에 안 붙은 채 '스틱 위'는 카메라 앞
                #  (보스 쪽)으로 달리기가 돼 7 m 끌려가 맞았다. 붙었는지(애니 7000대) 보고 아니면 다시 사다리를 본다.
                self.log(f"   {tag}: 사다리 안 잡힘 ({attempt + 1}/{LADDER_TRIES}) — 오르기 입력 안 함")
                self.mv.pad.neutral()                      # A 떼기 — 10-31 235045: 눌린 채 남아 다음 A 두 번이 새 입력이 안 됨
                if self._ladder_dead(self.mv.snap(5.0), tag):
                    return "dead"
                self.f._settle(bottom, tol=0.4)
                continue
            y0 = s.player.y
            t0, moved, died = time.time(), False, False
            while time.time() - t0 < LADDER_CLIMB_S:
                self.mv.pad.move(0.0, 1.0)                 # stick up = climb
                time.sleep(0.1)
                s = self.mv.snap(5.0)
                if s is None:
                    continue
                if self._ladder_dead(s, tag):
                    died = True
                    break
                moved = moved or s.player.y > y0 + 0.4
                if s.player.y >= top_y - 0.3:
                    time.sleep(0.8)                        # keep pushing — step off the top
                    break
                if not moved and time.time() - t0 > 2.5:
                    break                                  # not on the ladder — face it again and A
            self.mv.pad.neutral()
            if died:
                return "dead"
            s = self.mv.snap(5.0)
            if s is not None and s.player.y >= top_y - 0.6:
                self.log(f"   {tag}: 사다리 올라감 (y {s.player.y:.1f})")
                return "ok"
            self.log(f"   {tag}: 사다리 안 올라감 ({attempt + 1}/{LADDER_TRIES}, y {None if s is None else round(s.player.y, 1)})")
            if self._ladder_dead(s, tag):
                return "dead"
            self.f._settle(bottom, tol=0.4)
        return "fail"

    def _ladder_dead(self, s, tag: str | None = None) -> bool:
        """
        ── 사다리 루틴의 사망 판정 (20261101_002546) ─────────────────────────────
         · 이미 읽은 스냅숏의 HP 0 = 사망. alive()로 다시 확인하지 않는다 — DS1에서 HP 0은 되돌아오지 않고,
           Field.alive도 읽기 한 번의 HP로 판정한다. 살아 있는 경로에 읽기를 더하지 않으려고 손에 든 스냅숏을 쓴다.
         · 스냅숏 없음 = 읽기 실패이지 사망 증거가 아니다 → 입구와 같은 정책(Field.alive: 다시 읽고 그래도 없으면 False).
         · 판정 시점은 '읽은 순간'이다 — 실제 사망과 그 읽기 사이의 입력은 막지 못한다.
         tag: log the verdict under it (None = no log: the turn loop's per-read check)."""
        if s is None:
            dead = not self.f.alive()
            if dead and tag:
                self.log(f"   {tag}: 사다리 — 스냅숏 없음, alive() 거짓 → 'dead' (읽기 실패, HP 0은 못 봄)")
            return dead
        hp = getattr(s.player, "hp", None)
        if hp is not None and hp <= 0:
            if tag:
                self.log(f"   {tag}: 사다리 — 스냅숏 HP 0 → 중단")
            return True
        return False

    def _ladder_ready(self):
        """Wait until a roll (700s), a hit stagger or Estus is over — A pressed in one is dropped. Free means free for
        LADDER_FREE_S in a row: 20261101_000027 710 ended at 55.58, −1 for 0.05 s, then a hit stun (2017) at 55.63 — A at 56.06
        went in the stun. → a fresh snapshot or None."""
        t0 = time.time()
        s = self.mv.snap(5.0)
        free_t = None
        while s is not None and time.time() - t0 < LADDER_BUSY_S:
            a = getattr(s.player, "anim", None)
            a = -1 if a is None else a
            if 700 <= a < 800 or a in M.HIT_STUN or 7585 <= a <= 7587:   # 7585–7587 Estus (235045: A in 7587 dropped)
                free_t = None
            else:
                free_t = free_t or time.time()
                if time.time() - free_t >= LADDER_FREE_S:
                    break
            time.sleep(0.05)
            s = self.mv.snap(5.0)
        return s

    def _ladder_grabbed(self):
        """After A: the ladder anims (7000s) or the body going up within LADDER_GRAB_S → that snapshot, else None."""
        t0 = time.time()
        s0 = self.mv.snap(5.0)
        y0 = s0.player.y if s0 is not None else None
        while time.time() - t0 < LADDER_GRAB_S:
            self.mv.pad.release_due()                      # the A tap is released here (tap only schedules it)
            time.sleep(0.05)
            s = self.mv.snap(5.0)
            if s is None:
                continue
            if 7000 <= (getattr(s.player, "anim", None) or -1) < 7100 or (y0 is not None and s.player.y > y0 + 0.3):
                return s
        return None

    def _roll_away(self, st: dict, nb, tag: str) -> str:
        """
        ── 사다리 꼭대기에서 구르기 두 번 (P-47, [MoKa] 2026-10-06) ─────────────────────────────
         "구역 8 석궁병을 바로 공격하려고 하면 위치가 불리하니, 구르기를 2번 해서 석궁병하고 간격을 벌려야 해."
         꼭대기 (50.8,24.7,−116.6)는 NavMesh 가장자리까지 0.2~0.5 m인 좁은 턱 — 10-06 사망 실행은 거기를 안전 자리로 두고 2.4 m 앞
         석궁병 3004에 −228·−228, 턱에서 다섯 번 미끄러짐. 녹화에서 MoKa는 동쪽으로 달려 F9#8 (61.95,23.7,−116.93)에서 받음 —
         동쪽 2~3 m부터 바닥이 넓어짐(가장자리 3~6 m). 그쪽(`toward`)으로 바닥이 ROLL_M 있으면 그쪽으로, 없으면 바닥 있는 방향 중
         ROLL_FOE_R 안 적에게서 가장 먼 쪽으로 구름. 둘 다 없으면 구르지 않음. → 'ok' | 'dead'; self._landed = 마지막 자리
        """
        import ground
        n, toward = int(st.get("n", 2)), tuple(st["toward"])
        g = ground.for_map(plain_nm(nb)) if nb is not None else None   # --ground may already hand us a Ground
        self._landed = None
        for i in range(n):
            s = self.mv.snap(15.0)
            if s is None:
                break
            p = s.player
            d = self._roll_dir(g, s, toward)
            if d is None:
                self.log(f"   {tag}: 구를 쪽에 바닥 없음 — 구르지 않음 ({i}/{n})")
                break
            self.log(f"   {tag}: 구르기 {i + 1}/{n} → {math.degrees(math.atan2(d[0], d[1])):+.0f}° "
                     f"({'F9 쪽' if d[2] else '적에게서 먼 쪽'})")
            self.mv.roll_toward(s, p.x + d[0] * 3.0, p.z + d[1] * 3.0)
            if not self.f.alive():
                return "dead"
        s = self.mv.snap(15.0)
        if s is not None:
            self._landed = (s.player.x, s.player.y, s.player.z)
        return "ok"

    @staticmethod
    def _roll_dir(g, s, toward):
        """(dx, dz, toward?) for one roll: toward `toward` when that has floor ROLL_M ahead, else of 12 directions with floor the one
        that lands farthest from awake foes within ROLL_FOE_R (ties: nearer the planned way). None = no floor anywhere."""
        p = s.player
        P = type("P", (), {})()
        P.gx, P.gy, P.gz = p.x, p.y, p.z                       # m10_01: local = NavMesh coords (as find_path is given here)
        ok = (lambda dx, dz: True) if g is None else (lambda dx, dz: nav.can_move(g, P, dx, dz, ROLL_M))
        tx, tz = toward[0] - p.x, toward[2] - p.z
        n = math.hypot(tx, tz)
        if n > 0.5 and ok(tx / n, tz / n):
            return tx / n, tz / n, True
        foes = [c for c in s.hostile(ROLL_FOE_R) if c.hp > 0 and abs(c.y - p.y) < 3.0]
        best = None
        for k in range(12):
            a = k * math.pi / 6
            dx, dz = math.sin(a), math.cos(a)
            if not ok(dx, dz):
                continue
            qx, qz = p.x + dx * ROLL_M, p.z + dz * ROLL_M
            far = min((math.hypot(c.x - qx, c.z - qz) for c in foes), default=ROLL_FOE_R)
            score = far + (0.5 * (dx * tx + dz * tz) / n if n > 0.5 else 0.0)
            if best is None or score > best[0]:
                best = (score, dx, dz)
        return None if best is None else (best[1], best[2], False)

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

    def _sprint(self, goal, nb, stop, through: bool = False) -> str:
        """Run along the NavMesh path to goal (no guard) until stop(snapshot), or until a foe is hitting / swinging at us
        (reflex.threat_now — the same check Field's walks stop on) → 'threat', and the caller fights from where it stands.
        through: don't stop for threats (bolts from range) — only stop / arrival / death end it.
        → 'arrived' | 'stopped' | 'threat' | 'dead' | 'no_path' | …"""
        # P-67: 돌아가는 달리기가 적 셋에게 막혀 12 s 맞기만 함 — 멈춤 조건이 '도착'뿐이었다. 걷기와 같은 피격 검사를 거친다
        # ── through 달리기가 거꾸로 감 (P-113, 11-02 020649 · 11-01 230106) ─────────────────────────────
        #  사다리 꼭대기에서 맞은 뒤 달리기가 구르기(900→1790)로 턱 아래로 떨어져 경로점을 놓침 → 길 따라가기가 놓친 점으로
        #  되돌아가 석궁병 쪽으로 3 m 걸어감, 피격에 안 멈추니 싸움 없이 −557. 목표에서 SPRINT_BACK_M 넘게 멀어지면 멈추고
        #  지금 자리에서 길을 다시 찾음 (최대 SPRINT_REPLANS번)
        for _ in range(SPRINT_REPLANS + 1 if through else 1):
            s = self.mv.snap(5.0)
            if s is None:
                return "no_snapshot"
            path = nb.find_path((s.player.x, s.player.y, s.player.z), tuple(goal))
            if not path:
                return "no_path"
            why = []
            best = [math.hypot(s.player.x - goal[0], s.player.z - goal[2])]

            def stop2(sn) -> bool:
                if stop is not None and stop(sn):
                    return True
                if not through and self.f.reflex.threat_now(sn):
                    why.append("threat")
                    return True
                if through:
                    d = math.hypot(sn.player.x - goal[0], sn.player.z - goal[2])
                    best[0] = min(best[0], d)
                    if d > best[0] + SPRINT_BACK_M:
                        why.append("back")
                        return True
                return False
            r = self.mv.walk_path(nav.trim_path(path[1:], tuple(goal)), nb, "sprint", stop=stop2)
            if not (r == "stopped" and why == ["back"]):
                break
            self.log(f"   달리기: 목표에서 {SPRINT_BACK_M} m 넘게 멀어짐 — 지금 자리에서 길 다시 찾음")
        return "threat" if r == "stopped" and why and why[0] == "threat" else r

    UPPER_SEGMENTS = {n: f"zone{n}" for n in range(1, len(UPPER["zones"]) + 1)}

    def to_altar_bridge(self) -> str:
        """
        ── 구역 7 끝 → 타우로스 다리 → 헬카이트 다리 입구 (전체 연결, [MoKa] 2026-10-13 "진행해줘") ──────────────────
         · 타우로스를 이미 잡은 캐릭터: 구역 8의 안개벽(탑 문)만 지나고, 사다리로 탑에 오르지 않고 다리를 서쪽으로 건넘 —
           NavMesh 길 (49.4,16.3,−117.1) → (14.2,15.8,−118.3) → (−3.3,16.8,−112.5) → 계단 → 다리 입구 (−21.3,9.47,−101.77), 약 75 m.
           다리 입구까지 걷기는 altar.run()이 함 (① 4 m 밖이면 walk_to)
         · 탑 위 석궁병 둘(구역 8 kills)은 안 잡음 — 다리를 건널 때 쏘는지는 첫 런에서 봄
        → 'ok' | 'dead' | 'fail' | walk result"""
        fog = next(st for st in UPPER["zones"][7].get("before", []) if "fog" in st)
        return self._before(fog, self.nms[MAP_B], "구역8 안개벽")

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
            self._loot(nb, tag)
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
        if seg == "A" and d <= ROUTE_NEAR_M and off_route(here, route[k]):
            # close but another level (P-57): path-find to that point, then go on from it
            self.log(f"   상인 길: A{k}가 높이 {route[k][1] - here[1]:+.1f} m — 곧장 말고 길 찾아 감")
            r = self.f.walk_to(route[k], na, "꼭대기로" if k == 0 else "길로")
            if r != "arrived":
                return f"{'꼭대기' if k == 0 else '길'}까지 {r}"
        elif d > ROUTE_NEAR_M:
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
        if sat:
            import levelup
            levelup.maybe(tm, self.mv.press, log=self.log)  # run.py --level-up ([MoKa] 10-31 "모은 소울로 업그레이드")
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
