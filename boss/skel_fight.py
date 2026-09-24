"""묘지 해골 실전 — 실측 타이밍으로: 3005 는 막고, 나머지는 닿기 0.33 s 전에 반대쪽으로 구르고, 콤보가 끝난 틈에 약공 1대.
한 번에 한 마리 — 둘이 4 m 안이면 입구 쪽으로 백스텝. HP 35% 아래면 화톳불로 달려 끝.
  python boss/skel_fight.py [초]"""
import sys, time, json, math, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import control, env, nav, navmesh, farm, patrol, merchantrun as mr
tm = env.make_telemetry({}); pad = control.Pad(); pad.reconnect(); control.focus_game()
n = navmesh.Navmesh(mr.MAP_A)
LIMIT = float(sys.argv[1]) if len(sys.argv) > 1 else 150
SPOT = (-42.4, -59.6, 119.1)
EXIT = (-44.0, -56.5, 113.7)
# 사용자: "해골이 나타나면 많이 후퇴" — 입구에서 화톳불 쪽 길을 따라 물러나며 줄을 세운다 (빠른 놈이 혼자 먼저 온다)
BACK = [(-44.0, -56.5, 113.7), (-47.2, -55.5, 91.0), (-44.0, -56.0, 89.0), (-40.1, -54.7, 79.3), (-41.4, -56.2, 71.4)]
HIT = {3000: [0.75], 3001: [0.63], 3002: [0.80], 3003: [1.48], 3004: [1.20], 3005: [0.50, 0.88], 3008: [1.88, 3.20]}
DUR_AFTER = 0.35          # 마지막 타격 뒤 이만큼 지나면 틈
LEAD = 0.33
EV = []
T0 = time.time()
def ev(*a):
    EV.append([round(time.time() - T0, 2)] + list(a)); print(f"  [{time.time()-T0:6.2f}]", *a, flush=True)
def stick(dx, dz, s):
    return control.world_to_stick(dx, dz, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
def roll(dx, dz, s):
    st = stick(dx, dz, s); pad.guard(False); pad.move(st[0], st[1])
    pad.tap(control.B.XUSB_GAMEPAD_B, 0.06); time.sleep(0.08); pad.release_due(); time.sleep(0.25); pad.move(0, 0); time.sleep(0.35)
def r1():
    pad.move(0, 0); time.sleep(0.16); pad.guard(False)
    pad.tap(control.B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06); time.sleep(0.1); pad.release_due(); time.sleep(0.7)
def face(s, c):
    p = s.player
    if abs(math.degrees(patrol.rel_angle(p, c))) > 25:
        st = stick(c.x - p.x, c.z - p.z, s); pad.move(0.45 * st[0], 0.45 * st[1]); time.sleep(0.15); pad.move(0, 0)
def skels(s, r):
    return [c for c in s.hostile(r) if c.hp > 0 and c.npc_param // 1000 in (290, 291) and abs(c.y - s.player.y) < 6]

def fight():
    start = {}; done = set(); kills = 0; last_hp = None; hp_seen = {}
    bi = -1; backing = False; seen = False
    while time.time() - T0 < LIMIT:
        s = tm.snapshot(within=20)
        if s is None: time.sleep(0.02); continue
        p = s.player
        if p.hp <= 0: ev("사망"); return "dead"
        if last_hp is not None and p.hp < last_hp:
            near = sorted(skels(s, 5), key=lambda c: c.dist)
            ev("맞음", last_hp - p.hp, [(c.anim, round(time.time() - start.get(c.ptr, (0, time.time()))[1], 2), round(c.dist, 1)) for c in near[:2]])
        last_hp = p.hp
        for ptr, h in list(hp_seen.items()):
            c = next((x for x in s.chars if x.ptr == ptr), None)
            if c is not None and c.hp <= 0 and ptr not in done:
                done.add(ptr); kills += 1; ev("처치", kills, "소울", tm.souls())
        if p.hp < p.max_hp * 0.35:
            ev("HP 낮음 — 후퇴", p.hp); return "retreat"
        ss = skels(s, 14)
        for c in ss:
            hp_seen[c.ptr] = c.hp
            a = c.anim if c.anim is not None else -1
            if start.get(c.ptr, (None,))[0] != a:
                start[c.ptr] = (a, time.time())
        # ⓪ 처음 보이면 / 둘째가 7 m 안이면 → 다음 후퇴점까지 달려서 물러난다
        n7 = [c for c in ss if c.dist < 7.0]
        if ((ss and not seen) or len(n7) >= 2) and not backing and bi < len(BACK) - 1:
            seen = True; backing = True; bi += 1; ev("후퇴", bi, "해골", len(ss), "7m안", len(n7))
        if backing:
            q = BACK[bi]
            if math.hypot(q[0] - p.x, q[2] - p.z) < 1.2:
                backing = False; pad.sprint(False); pad.move(0, 0)
            else:
                st = stick(q[0] - p.x, q[2] - p.z, s); pad.guard(False); pad.sprint(p.sp > 25); pad.move(st[0], st[1]); time.sleep(0.05)
                continue
        pad.sprint(False)
        # ① 피하기 / 막기 (둘 이상 붙어 있으면 구르지 않고 막는다)
        acted = False
        for c in sorted(ss, key=lambda c: c.dist):
            a, t = start[c.ptr]; age = time.time() - t
            if a not in HIT or c.dist > 4.5:
                continue
            for i, h in enumerate(HIT[a]):
                key = (c.ptr, round(t, 2), i)
                if key in done or not (h - LEAD - 0.05 <= age <= h - 0.08):
                    continue
                done.add(key)
                if a == 3005 or p.sp < 20 or h - age < 0.2 or len([x for x in ss if x.dist < 4.5]) >= 2:
                    pad.move(0, 0); pad.guard(True); ev("막기", a, round(age, 2), round(c.dist, 1), "sp", p.sp)
                else:
                    ux, uz = p.x - c.x, p.z - c.z; m = math.hypot(ux, uz) or 1
                    ex, ez = EXIT[0] - p.x, EXIT[2] - p.z; me = math.hypot(ex, ez) or 1
                    roll(ux / m + 0.6 * ex / me, uz / m + 0.6 * ez / me, s)
                    ev("구름", a, round(age, 2), round(c.dist, 1), "sp", p.sp)
                acted = True; break
            if acted: break
        if acted: continue
        winding = [c for c in ss if c.dist < 4.5 and start[c.ptr][0] in HIT and time.time() - start[c.ptr][1] < HIT[start[c.ptr][0]][-1] + 0.1]
        if winding:
            pad.guard(True); pad.move(0, 0); time.sleep(0.02); continue
        close = [c for c in ss if c.dist < 4.0]
        # ② 둘이 붙으면 입구 쪽으로 물러난다
        if len(close) >= 2:
            st = stick(EXIT[0] - p.x, EXIT[2] - p.z, s); pad.guard(True); pad.move(st[0], st[1]); time.sleep(0.08); continue
        if not ss:
            pad.guard(True); pad.move(0, 0); time.sleep(0.05); continue
        c = min(ss, key=lambda c: c.dist)
        a, t = start[c.ptr]; age = time.time() - t
        opening = (a in HIT and age >= HIT[a][-1] + DUR_AFTER and a in (3002, 3003, 3004, 3008)) or a in (-1, 9910, 9311, 9312)
        # ③ 틈이면 1대
        if c.dist < 2.3 and opening and p.sp >= 35:
            hp0 = c.hp; face(s, c); r1()
            c2 = next((x for x in tm.snapshot(within=20).chars if x.ptr == c.ptr), None)
            ev("약공", a, round(age, 2), "해골", hp0, "→", None if c2 is None else c2.hp)
            pad.guard(True); continue
        # ④ 가드 든 채 2 m 까지
        if c.dist > 2.0:
            st = stick(c.x - p.x, c.z - p.z, s); pad.guard(True); pad.move(0.6 * st[0], 0.6 * st[1])
        else:
            pad.guard(True); pad.move(0, 0)
        time.sleep(0.03)
    return "timeout"

r = None
try:
    s = tm.snapshot(within=5); here = (s.player.x, s.player.y, s.player.z)
    p = n.find_path(here, SPOT) or [SPOT]
    print("가기", nav.follow(tm, pad, [tuple(q) for q in p[1:]] + [SPOT], terrain=None, mode_fn=lambda _s: "walk", default_tol=1.0, log=lambda *a: None))
    r = fight(); print("결과", r, flush=True)
finally:
    pad.neutral()
    json.dump(EV, open(ROOT / f"data/trace/skel_fight_{time.strftime('%H%M%S')}.json", "w", encoding="utf-8"), ensure_ascii=False)
    if r != "dead":
        s = tm.snapshot(within=5); bf = tuple(mr.BONFIRE["stand"])
        p = n.find_path((s.player.x, s.player.y, s.player.z), bf) or [bf]
        print("복귀", nav.follow(tm, pad, [tuple(q) for q in p[1:]] + [bf], terrain=None, mode_fn=lambda _s: "sprint", default_tol=1.5, log=lambda *a: None))
        farm.rest(tm, pad, n, mr.BONFIRE)
    print("소울", tm.souls())
