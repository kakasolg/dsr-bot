"""수용소 데몬(223200) — 안개 통과 → 발코니 끝에서 데몬이 바로 아래 오면 떨어지며 RB(낙하 공격) → 등 뒤에서 약공 2번, 도약(3008)·망치(3006) 피해 구르기.
데몬 애니·내 HP 는 0.05 s 로, 화면은 1 s 로 기록한다 (사용자: "1초마다 스크린샷 찍어서 분석").

첫 판 분석(boss_223135): 3008 = 뛰어올라 내려찍기(192 × 3), 3006 = 앞으로 망치(169 × 2) — 방패로 못 막았다. 3003/3005/3013 은 막았고(스태미나 91→39),
약공 한 번 38. 낙하 피해 189 (낙하 공격이 빗나가 12 m 를 그냥 떨어졌다). 에스트를 3.4 m 앞에서 마시다 곧장 3008 에 맞았다."""
import json, math, sys, threading, time
sys.path.insert(0, r"D:\dev\chzzk-souls-chaos\bot")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent)); sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import ah
from ah import tm, pad, L, nav, control
import env, patrol
from PIL import ImageGrab
import vision_probe as vp

DEMON = 223200
# 두 판(boss_232120, boss_233426) 실측: 애니 시작 → 내가 맞은 때(s), 애니 길이(s). 7.8 m 에서도 맞았다 (망치가 길다).
HIT_AT = {3000: 1.77, 3002: 1.26, 3003: 1.6, 3005: 1.46, 3006: 1.72, 3008: 4.05, 3010: 2.63, 3011: 1.15,
          3012: 1.8, 3013: 1.9, 3021: 1.2}
DUR = {3000: 5.5, 3002: 3.0, 3003: 2.0, 3005: 4.0, 3006: 4.6, 3008: 6.9, 3010: 6.4, 3011: 2.25, 3012: 5.1, 3013: 5.1, 3021: 2.05}
ROLL_LEAD = 0.33          # 구르기 무적이 누른 뒤 ~0.1 s 부터 ~0.37 s — 닿기 0.33 s 전에 누른다 (1.28 에 굴렀다 1.79 에 맞음)
REACH = 8.2               # 이 안이면 피한다
TAG = time.strftime("%H%M%S")
FINE: list = []          # (t, 내 hp, sp, 내 anim, 데몬 hp, 데몬 anim, 거리, 데몬 y-내 y, 정면각, 반지름 R, 모드, 내 x, z, 데몬 x, z)
SHOTS: list = []
EVENTS: list = []
_stop = [False]
STATE = {"R": None, "mode": "start"}
T0 = time.time()


def demon(s):
    return next((c for c in s.chars if c.npc_param == DEMON), None)


def behind_angle(d, p):
    """데몬 정면 기준 내가 몇 도 옆에 있나 (0 = 정면, 180 = 등 뒤)."""
    return abs(math.degrees(patrol.rel_angle(d, p)))


def ev(*a):
    t = round(time.time() - T0, 2)
    EVENTS.append((t,) + a)
    print(f"   [{t:6.2f}]", *a, flush=True)


def recorder():
    tm2 = env.make_telemetry({})
    last_shot = 0.0; k = 0
    while not _stop[0]:
        s = tm2.snapshot(within=40)
        if s:
            d = demon(s)
            p = s.player
            FINE.append((round(time.time() - T0, 2), p.hp, p.sp, p.anim,
                         None if d is None else d.hp, None if d is None else d.anim,
                         None if d is None else round(d.dist, 2), None if d is None else round(d.y - p.y, 2),
                         None if (d is None or d.heading is None) else round(behind_angle(d, p)),
                         STATE["R"], STATE["mode"], round(p.x, 2), round(p.z, 2),
                         None if d is None else round(d.x, 2), None if d is None else round(d.z, 2),
                         None if d is None else d.heading))
        if time.time() - last_shot >= 1.0:
            last_shot = time.time()
            name = f"boss_{TAG}_{k:03d}.jpg"
            try:
                ImageGrab.grab(bbox=vp.window_rect()).convert("RGB").resize((960, 540)).save(vp.IMG_DIR / name, quality=80)
                SHOTS.append((round(time.time() - T0, 1), name))
            except Exception:
                pass
            k += 1
        time.sleep(0.05)


def roll(dx, dz):
    s = ah.snap(40)
    st = control.world_to_stick(dx, dz, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
    pad.guard(False)
    pad.move(st[0], st[1])
    pad.tap(control.B.XUSB_GAMEPAD_B, 0.06); time.sleep(0.08); pad.release_due()
    time.sleep(0.25)
    pad.move(0, 0)
    time.sleep(0.45)


def r1(n=1):
    for _ in range(n):
        pad.guard(False)
        pad.tap(control.B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06); time.sleep(0.1); pad.release_due()
        time.sleep(0.6)


def plunge():
    """안개를 지나 발코니 끝에서 데몬이 바로 아래(착지점 1.8 m 안)·땅(높이차 < -10)·도약 중 아님일 때 걸어 나가 떨어지며 RB."""
    for _ in range(6):                                   # 안개(+z) 쪽을 보고 안내가 뜰 때까지
        if L.prompt_px() >= L.PROMPT_ON:
            break
        s = ah.snap(8)
        st = control.world_to_stick(0.0, 1.0, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
        pad.move(0.5 * st[0], 0.5 * st[1]); time.sleep(0.15); pad.move(0, 0); time.sleep(0.45)
    L.press_a(pad); time.sleep(3.5)
    s = ah.snap(40); p = s.player
    ev("안개 통과", (round(p.x, 1), round(p.y, 1), round(p.z, 1)))
    # 8 번째 죽음: 여기서 가장자리 '밖' 점으로 걸어가 그대로 떨어졌고(낙하 피해 193), 기다리는 루프가 떨어진 걸 몰라 30 s 맞기만 했다.
    # 안개를 나오면 이미 가장자리 앞(z -32.6) — 걷지 않고 제자리에서 데몬 쪽을 본다
    # 9 번째 죽음: 가장자리에서 기다리면 데몬이 8.5 s 뒤 도약(3023)으로 발코니까지 쳐서(214) 떨어뜨린다 → 기다리지 않는다.
    # 떨어지는 동안에도 스틱을 데몬 쪽으로 밀어야 공중에서 2~3 m 더 나간다 (첫 판은 놓아서 3.8 m 빗나감)
    # 사용자: "데몬이 널 쳐다보게 만들고 낙하 공격". 기록: 안개를 나올 때 데몬은 이미 5.6 m 앞에서 나를 보고(정면각 0°) 3020→3021 로 서 있고,
    # 그대로 두면 ~7 s 뒤 도약(3023)으로 발코니를 친다 → 나를 보고 서 있는 게 확인되면 곧장, 3023 이 시작되면 그 즉시 뛴다
    t_w = time.time()
    while time.time() - t_w < 4.0:
        s = ah.snap(40); d = demon(s)
        if s is None or d is None:
            time.sleep(0.05); continue
        ang = behind_angle(d, s.player) if d.heading is not None else 180
        if d.anim == 3023 or (ang < 25 and d.anim in (3020, 3021, -1)):
            ev("데몬이 나를 봄", "정면각", round(ang), "애니", d.anim, "기다림", round(time.time() - t_w, 2)); break
        time.sleep(0.05)
    s = ah.snap(40); d = demon(s)
    ev("곧장 뛰어내림", "데몬", (round(d.x, 1), round(d.y, 1), round(d.z, 1)), "애니", d.anim)
    y0 = s.player.y; hp0 = d.hp; pressed = False; t1 = time.time(); tp = None; last_rb = 0.0
    pad.sprint(True)
    while time.time() - t1 < 6.0:
        s = ah.snap(40)
        if s is None:
            time.sleep(0.03); continue
        d = demon(s)
        if d is not None and s.cam_yaw is not None:
            st = control.world_to_stick(d.x - s.player.x, d.z - s.player.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
            pad.move(st[0], st[1])
        # 10 번째 판: 떨어지기 직전(1550, y 그대로)에 RB 를 눌러 씹혔다 — 낙하 공격 애니가 한 번도 없었다.
        # 실제로 떨어지는 중(1500 또는 1 m 넘게 내려감)에 0.15 s 마다 RB
        falling = s.player.anim == 1500 or s.player.y < y0 - 1.0
        if falling and s.player.y > y0 - 11.0 and time.time() - last_rb > 0.15:
            pad.sprint(False)
            pad.tap(control.B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06); time.sleep(0.07); pad.release_due()
            last_rb = time.time()
            if not pressed:
                ev("떨어지는 중 → RB", round(s.player.y, 1), s.player.anim)
            pressed = True; tp = time.time()
            continue
        if pressed and time.time() - tp > 1.5 and s.player.y < y0 - 10:
            break
        time.sleep(0.02)
    pad.sprint(False)
    pad.neutral()
    s = ah.snap(40); d = demon(s)
    ev("낙하 공격", "데몬 HP", hp0, "→", d.hp, "내 HP", s.player.hp)


def face_to(s, d, tol=30):
    p = s.player
    if abs(math.degrees(patrol.rel_angle(p, d))) > tol:
        st = control.world_to_stick(d.x - p.x, d.z - p.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
        pad.move(0.45 * st[0], 0.45 * st[1]); time.sleep(0.15); pad.move(0, 0)
        return True
    return False


def backstep():
    """사용자: "후진은 백스텝으로" — 스틱 놓고 B 톡 (등을 안 보인다)."""
    pad.move(0, 0); time.sleep(0.16)
    pad.guard(False)
    pad.tap(control.B.XUSB_GAMEPAD_B, 0.06); time.sleep(0.08); pad.release_due()
    time.sleep(0.6)


# 보스방 바닥 x -8..14, z -32..-6. 기둥 줄 x -4..-3, 9..10. 벽·구석 말고 가운데 자리만 (구석에 몰려 3000 을 다섯 번 맞았다)
SPOTS = [(0.5, 197.8, -28.0), (6.5, 197.8, -28.0), (3.5, 197.8, -23.5), (0.5, 197.8, -19.0), (6.5, 197.8, -19.0),
         (3.5, 197.8, -14.5), (0.5, 197.8, -10.0), (6.5, 197.8, -10.0)]


def attack_anim(a):
    return a is not None and 3000 <= a < 3100 and a not in (3020, 3022)


def spot_away(p, d, min_d=5.5):
    """데몬에게서 min_d 넘게 떨어진 가운데 자리 중 나에게 가깝고 데몬을 가로지르지 않는 곳."""
    best = None
    for q in SPOTS:
        dq = math.hypot(q[0] - d.x, q[2] - d.z)
        mq = math.hypot(q[0] - p.x, q[2] - p.z)
        if dq < min_d:
            continue
        if mq > 1.0:
            cos = ((q[0] - p.x) * (d.x - p.x) + (q[2] - p.z) * (d.z - p.z)) / (mq * max(0.1, math.hypot(d.x - p.x, d.z - p.z)))
            if cos > 0.3:
                continue
        sc = mq - 0.3 * dq
        if best is None or sc < best[0]:
            best = (sc, q)
    return None if best is None else best[1]


def quarter_spot(p, d, r=3.5):
    """사용자: "데몬 주위를 1/4 바퀴 돌고 한 대씩". 데몬 중심 반지름 r 에서 지금 각 ±90° 자리 — 방(x -7..13, z -31..-7) 안쪽, 가운데에 가까운 쪽."""
    a = math.atan2(p.x - d.x, p.z - d.z)
    best = None
    for sgn in (1, -1):
        b = a + sgn * math.pi / 2
        q = (d.x + r * math.sin(b), 197.8, d.z + r * math.cos(b))
        inside = -7 <= q[0] <= 13 and -31 <= q[2] <= -7
        sc = (0 if inside else 100) + math.hypot(q[0] - 3.5, q[2] + 19)
        if best is None or sc < best[0]:
            best = (sc, q)
    return best[1]


def side_roll(p, d):
    """데몬 방향에 수직으로 — 방 가운데(x 3.5, z -19) 쪽 옆으로."""
    dx, dz = d.x - p.x, d.z - p.z
    a, b = (-dz, dx), (dz, -dx)
    cx, cz = 3.5 - p.x, -19.0 - p.z
    return a if a[0] * cx + a[1] * cz >= b[0] * cx + b[1] * cz else b


ORBIT_R = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0


def orbit_stick(p, d, s, sgn, r):
    """데몬 둘레를 반지름 r 로 돈다 — 접선 방향 + 반지름 보정."""
    ux, uz = (p.x - d.x), (p.z - d.z)
    m = math.hypot(ux, uz) or 1.0
    ux, uz = ux / m, uz / m
    tx, tz = -uz * sgn, ux * sgn
    k = max(-1.0, min(1.0, (r - m) / 2.0))          # 멀면 안으로, 가까우면 밖으로
    vx, vz = tx + k * ux, tz + k * uz
    return control.world_to_stick(vx, vz, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)


# 사용자 임무: "데몬과 어느 정도 거리를 유지했을 때 가장 좋았는지 분석 — 그 데이터를 모으는 것". 한 판 안에서 반지름을 45 s 마다 바꾼다
RADII = [6.5]
SEG = 45.0


def far_spot(d):
    return max(SPOTS, key=lambda q: math.hypot(q[0] - d.x, q[2] - d.z))


def ang_at(d, x, z):
    """데몬 정면에서 (x, z) 가 몇 도 옆인가 (0 정면, 180 등 뒤)."""
    class _P: pass
    q = _P(); q.x, q.z = x, z
    return behind_angle(d, q) if d.heading is not None else 90.0


def toward_back_sgn(p, d, sgn):
    """두 방향 중 데몬 등 쪽(각이 커지는 쪽)으로 도는 방향. 방 밖이면 반대."""
    ux, uz = p.x - d.x, p.z - d.z
    m = math.hypot(ux, uz) or 1.0
    best = None
    for g in (1, -1):
        tx, tz = -uz / m * g, ux / m * g
        nx, nz = p.x + 1.0 * tx, p.z + 1.0 * tz
        inside = -7 <= nx <= 13 and -31 <= nz <= -7
        sc = ang_at(d, nx, nz) - (0 if inside else 1000)
        if best is None or sc > best[0]:
            best = (sc, g)
    return best[1]


def fight(limit=520):
    """사용자 전술: ① 가드 든 채 적절한 거리(R)로 90° 돈다 ② 때리러 들어갈 땐 구르기 → 약공 ③ 에스트는 멀리 빨리 도망가서
    ④ 데몬 공격은 닿기 0.33 s 전 구른다 (멈추지 않는다)."""
    t0 = time.time(); last_a = None; a_t = time.time(); rolled_for = None; hit_for = None
    last_myhp = None; sgn = 1; ang_acc = 0.0; last_ang = None; wall_t = 0.0
    fleeing = False; flee_t = 0.0; spot = None
    r0 = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 0
    while time.time() - t0 < limit:
        s = ah.snap(40)
        if s is None:
            time.sleep(0.1); continue
        p = s.player; d = demon(s)
        if p.hp <= 0:
            ev("사망"); return "dead"
        if d is None or d.hp <= 0:
            ev("처치"); return "killed"
        R = RADII[(int((time.time() - t0) / SEG) + r0) % len(RADII)]
        if STATE["R"] != R:
            ev("반지름", R)
        STATE["R"] = R
        if d.anim != last_a:
            last_a, a_t = d.anim, time.time()
        age = time.time() - a_t
        dx, dz = d.x - p.x, d.z - p.z
        dist = math.hypot(dx, dz)
        atk = attack_anim(d.anim)
        hit_at = HIT_AT.get(d.anim, 1.77) if atk else None
        key = (d.anim, round(a_t, 1))
        if last_myhp is not None and p.hp < last_myhp - 20:
            ev("맞음", last_myhp, "→", p.hp, "데몬", d.anim, "age", round(age, 2), "거리", round(dist, 1), "R", R, "모드", STATE["mode"])
        last_myhp = p.hp
        stunned = p.anim not in (-1, None) and 2000 <= p.anim < 2100
        ang = math.atan2(p.x - d.x, p.z - d.z)
        if last_ang is not None:
            ang_acc += abs((ang - last_ang + math.pi) % (2 * math.pi) - math.pi)
        last_ang = ang
        # 사용자: "점프해서 엉덩방아는 전체 범위 공격 — 거리를 유지". 3008 시작되면 닿는 때(4.05 s)까지 밖으로 뛴다
        if d.anim == 3008 and age < 4.4 and dist < 8.0 and not stunned:
            if STATE["mode"] != "slam-run":
                ev("3008 엉덩방아 → 밖으로 뜀", "거리", round(dist, 1), "HP", p.hp)
            STATE["mode"] = "slam-run"
            st = control.world_to_stick(-dx, -dz, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
            if not (-7 <= p.x - dx / max(dist, 0.1) * 1.5 <= 13 and -31 <= p.z - dz / max(dist, 0.1) * 1.5 <= -7):
                st = orbit_stick(p, d, s, sgn, 9.0)
            pad.guard(False); pad.sprint(p.sp > 10); pad.move(st[0], st[1]); time.sleep(0.06)
            continue
        # ④ 피하기
        if False and atk and d.anim != 3008 and rolled_for != key and hit_at - ROLL_LEAD - 0.04 <= age <= hit_at - 0.1 and dist < REACH and p.sp >= 20 and not stunned:
            rolled_for = key
            pad.sprint(False)
            rx, rz = (-dx, -dz) if d.anim in (3006, 3012) else side_roll(p, d)
            STATE["mode"] = "dodge"
            ev(f"{d.anim} 피함", "age", round(age, 2), "거리", round(dist, 1), "sp", p.sp, "HP", p.hp, "R", R)
            roll(rx, rz)
            continue
        if False and d.anim == 3003 and rolled_for != ("2nd", round(a_t, 1)) and 1.62 <= age <= 1.8 and dist < REACH and p.sp >= 20:
            rolled_for = ("2nd", round(a_t, 1))
            STATE["mode"] = "dodge"
            ev("3003→3013 이어치기 피함", "거리", round(dist, 1), "HP", p.hp)
            roll(*side_roll(p, d))
            continue
        after = atk and age >= hit_at + 0.25
        left = DUR.get(d.anim, 4.5) - age if atk else 0
        window = after and left > 1.2 and d.anim != 3003
        winding = atk and not after
        # ③ 에스트 — 25% 깎이면 멀리 빨리 도망가서 마신다
        if not fleeing and p.hp < p.max_hp * 0.5 and tm.goods_count(201) and not stunned:
            fleeing = True; flee_t = time.time(); spot = far_spot(d)
            ev("에스트 하러 도망", "HP", p.hp, "거리", round(dist, 1), "→", spot[::2])
        if fleeing:
            near_spot = math.hypot(spot[0] - p.x, spot[2] - p.z) < 1.2
            if (dist >= 10.0 or near_spot or time.time() - flee_t > 3.5) and not (winding and dist < REACH):
                pad.sprint(False); pad.guard(False); pad.move(0, 0); time.sleep(0.35)
                STATE["mode"] = "drink"
                n0 = tm.goods_count(201)
                pad.use_item(); time.sleep(0.2); pad.release_due(); time.sleep(0.6)
                if tm.goods_count(201) == n0:   # 첫 누름이 씹히면 한 번 더
                    pad.use_item(); time.sleep(0.2); pad.release_due(); time.sleep(0.6)
                time.sleep(1.5)
                ev("에스트", p.hp, "→", ah.snap(5).player.hp, "남음", tm.goods_count(201), "거리", round(dist, 1))
                fleeing = False
                continue
            if not stunned:
                STATE["mode"] = "flee"
                if near_spot:
                    spot = far_spot(d)
                st = control.world_to_stick(spot[0] - p.x, spot[2] - p.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
                pad.guard(False); pad.sprint(p.sp > 15); pad.move(st[0], st[1]); time.sleep(0.06)
            continue
        # ② 90° 돌았으면(또는 헛친 틈) 구르며 들어가 약공
        back = ang_at(d, p.x, p.z)
        if ang_acc >= math.pi / 2 and not (winding and dist < REACH) and p.sp >= 40 and not stunned:
            if dist > 2.3:
                STATE["mode"] = "in-run"
                st = control.world_to_stick(dx, dz, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
                pad.guard(False); pad.sprint(False); pad.move(st[0], st[1]); time.sleep(0.06)
                continue
            hit_for = key
            STATE["mode"] = "in-roll"
            d_in = dist; hp0 = d.hp
            pass
            s2 = ah.snap(40); d2 = demon(s2)
            if d2 is not None:
                pad.move(0, 0); face_to(s2, d2, 25); time.sleep(0.12)
            STATE["mode"] = "attack"
            n = 1
            r1(n)
            d3 = demon(ah.snap(40))
            ev(f"구르고 약공 {n}", "데몬", hp0, "→", None if d3 is None else d3.hp, "들어간 거리", round(d_in, 1), "R", R,
               "틈" if window else "90°", "각", round(back))
            ang_acc = 0.0
            # 치고 나면 꼬리 쪽 옆으로 굴러 빠진다
            s4 = ah.snap(40); d4 = demon(s4)
            if False:
                g = toward_back_sgn(s4.player, d4, sgn)
                ux, uz = s4.player.x - d4.x, s4.player.z - d4.z
                STATE["mode"] = "out-roll"
                roll(-uz * g + 0.7 * ux, ux * g + 0.7 * uz)
            continue
        # ① 가드 든 채 반지름 R 로 돈다. 방 밖으로 나가면 방향을 바꾼다
        STATE["mode"] = "orbit"
        sgn = -1
        st = orbit_stick(p, d, s, sgn, R)
        pad.guard(winding and dist < REACH and p.sp < 20); pad.sprint(False); pad.move(st[0], st[1]); time.sleep(0.06)
    pad.neutral()
    return "timeout"


def behind_spot(d, r=2.6):
    """데몬 엉덩이 쪽 점 — 각이 가장 큰(등 뒤) 점, 방 안."""
    best = None
    for k in range(24):
        a = k * math.pi / 12
        x, z = d.x + r * math.sin(a), d.z + r * math.cos(a)
        if not (-7 <= x <= 13 and -31 <= z <= -7):
            continue
        sc = ang_at(d, x, z)
        if best is None or sc > best[0]:
            best = (sc, x, z)
    return best


def butt_fight(limit=520):
    """고수 플레이(사용자가 본 것): 양손, 가드·구르기 없음. 엉덩이 쪽으로 돌아 1대, 점프(3008)면 밖으로 뛴다."""
    t0 = time.time(); last_a = None; a_t = time.time(); last_myhp = None; last_hit = 0.0
    fleeing = False; flee_t = 0.0; spot = None
    while time.time() - t0 < limit:
        s = ah.snap(40)
        if s is None:
            time.sleep(0.1); continue
        p = s.player; d = demon(s)
        if p.hp <= 0:
            ev("사망"); return "dead"
        if d is None or d.hp <= 0:
            ev("처치"); return "killed"
        if d.anim != last_a:
            last_a, a_t = d.anim, time.time()
        age = time.time() - a_t
        dx, dz = d.x - p.x, d.z - p.z
        dist = math.hypot(dx, dz)
        back = ang_at(d, p.x, p.z)
        if last_myhp is not None and p.hp < last_myhp - 20:
            ev("맞음", last_myhp, "→", p.hp, "데몬", d.anim, "age", round(age, 2), "거리", round(dist, 1), "각", round(back), "모드", STATE["mode"])
        last_myhp = p.hp
        stunned = p.anim not in (-1, None) and 2000 <= p.anim < 2100
        if d.anim == 3008 and age < 4.4 and dist < 8.5 and not stunned:
            if STATE["mode"] != "slam-run":
                ev("3008 점프 → 밖으로 뜀", "거리", round(dist, 1))
            STATE["mode"] = "slam-run"
            st = control.world_to_stick(-dx, -dz, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
            if not (-7 <= p.x - dx / max(dist, 0.1) * 1.5 <= 13 and -31 <= p.z - dz / max(dist, 0.1) * 1.5 <= -7):
                st = orbit_stick(p, d, s, -1, 9.0)
            pad.sprint(p.sp > 10); pad.move(st[0], st[1]); time.sleep(0.06)
            continue
        if not fleeing and p.hp < p.max_hp * 0.5 and tm.goods_count(201) and not stunned:
            fleeing = True; flee_t = time.time(); spot = far_spot(d)
            ev("에스트 하러 도망", "HP", p.hp)
        if fleeing:
            if dist >= 10.0 or time.time() - flee_t > 3.5 or math.hypot(spot[0] - p.x, spot[2] - p.z) < 1.2:
                pad.sprint(False); pad.move(0, 0); time.sleep(0.35)
                STATE["mode"] = "drink"; n0 = tm.goods_count(201)
                pad.use_item(); time.sleep(0.2); pad.release_due(); time.sleep(0.6)
                if tm.goods_count(201) == n0:
                    pad.use_item(); time.sleep(0.2); pad.release_due(); time.sleep(0.6)
                time.sleep(1.5)
                ev("에스트", p.hp, "→", ah.snap(5).player.hp, "남음", tm.goods_count(201))
                fleeing = False
            else:
                STATE["mode"] = "flee"
                st = control.world_to_stick(spot[0] - p.x, spot[2] - p.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
                pad.sprint(p.sp > 15); pad.move(st[0], st[1]); time.sleep(0.06)
            continue
        # 엉덩이 쪽에 붙었으면 1대
        if back >= 120 and dist <= 3.2 and p.sp >= 30 and not stunned and time.time() - last_hit > 1.0:
            STATE["mode"] = "attack"; hp0 = d.hp
            pad.sprint(False); pad.move(0, 0); time.sleep(0.05)
            face_to(s, d, 25); time.sleep(0.12)
            r1(1)
            d3 = demon(ah.snap(40)); last_hit = time.time()
            ev("엉덩이 1대", hp0, "→", None if d3 is None else d3.hp, "각", round(back), "거리", round(dist, 1), "sp", p.sp)
            continue
        # 엉덩이 쪽으로 돈다 (가드·구르기 없음). 멀면 달린다
        STATE["mode"] = "circle"
        # 앞쪽이면 몸을 뚫고 가지 말고 반지름 3.8 m 로 돌아 등 쪽으로, 등 쪽(100° 이상)이면 엉덩이에 붙는다
        if back < 100:
            STATE["mode"] = "circle-out"
            st = orbit_stick(p, d, s, toward_back_sgn(p, d, -1), 3.8)
            tx, tz = 5.0, 0.0
        else:
            b = behind_spot(d)
            tx, tz = (b[1] - p.x, b[2] - p.z) if b else (dx, dz)
            st = control.world_to_stick(tx, tz, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
        pad.guard(False); pad.sprint(math.hypot(tx, tz) > 4 and p.sp > 40); pad.move(st[0], st[1]); time.sleep(0.06)
    pad.neutral()
    return "timeout"


def run():
    th = threading.Thread(target=recorder, daemon=True); th.start()
    try:
        s = ah.snap(8)
        if s.player.hp < s.player.max_hp * 0.9 and tm.goods_count(201):
            pad.use_item(); time.sleep(0.2); pad.release_due(); time.sleep(2.4)
        pad.tap(control.B.XUSB_GAMEPAD_Y, 0.08); time.sleep(0.15); pad.release_due(); time.sleep(1.0)   # 양손
        ev("양손 잡기")
        plunge()
        s2 = ah.snap(40); d2 = demon(s2)
        if d2 is not None:
            face_to(s2, d2, 25); time.sleep(0.12)
        hp0 = None if d2 is None else d2.hp
        r1(1)
        d3 = demon(ah.snap(40)); ev("낙공 뒤 1대", hp0, "→", None if d3 is None else d3.hp)
        r = butt_fight()
        print("보스전", r, flush=True)
    finally:
        _stop[0] = True; th.join(2)
        out = {"events": EVENTS, "shots": SHOTS, "fine": FINE}
        json.dump(out, open(f"D:/dev/chzzk-souls-chaos/bot/data/trace/boss_{TAG}.json", "w", encoding="utf-8"), ensure_ascii=False)
        print("기록", f"boss_{TAG}.json", "세밀", len(FINE), "스크린샷", len(SHOTS), flush=True)
        pad.neutral(); pad.guard(True)


if __name__ == "__main__":
    run()
