"""수용소 진행용 도우미 — 적이 가까우면 먼저 잡고(방패 들고 다가가 R1), 없으면 경로를 걷는다. 안내창은 보는 즉시 끈다."""
import math, sys, time
sys.path.insert(0, r"D:\dev\chzzk-souls-chaos\bot")
sys.stdout.reconfigure(encoding="utf-8")
import control, env, nav, navmesh, patrol, quitout
import ladder_test as L

tm = env.make_telemetry({})
pad = control.Pad()
control.focus_game()
time.sleep(0.4)
nm = navmesh.Navmesh("m18_01_00_00")
FIGHT_R = 6.0


TRAIL: list = []            # 걸어온 자리 (1 m 간격) — 도망칠 곳


def snap(r=30.0):
    s = tm.snapshot(within=r)
    if s is not None and s.player.hp > 0:
        q = (s.player.x, s.player.y, s.player.z)
        if not TRAIL or math.dist(TRAIL[-1], q) >= 1.0:
            TRAIL.append(q)
            del TRAIL[:-200]
    return s


def retreat_point(p, back=8.0, avoid=None):
    """걸어온 길을 되짚어 back m 뒤 — 적들 쪽이 아닌 쪽."""
    here = (p.x, p.y, p.z)
    acc, prev = 0.0, here
    for q in reversed(TRAIL):
        acc += math.dist(prev, q); prev = q
        if acc >= back and (avoid is None or math.dist((q[0], q[2]), avoid) > 5.0):
            return q
    return TRAIL[0] if TRAIL else None


def flee(p, crowd, log=print):
    """사용자: "다수한테 둘러싸이면 도망, 다시 하나씩" — 걸어온 길로 8 m 달려 빠진다 (빠른 놈부터 떨어져 따라온다)."""
    gx = sum(x.x for x in crowd) / len(crowd); gz = sum(x.z for x in crowd) / len(crowd)
    q = retreat_point(p, 6.0, avoid=(gx, gz))
    if q is None:
        return False
    # 7 번째 죽음: 달려서 빠지면 방패가 내려가 등에 맞았다(세 번 연달아) → 방패 든 채 걸어서 물러난다
    log(f"   둘러싸임 {len(crowd)} — 방패 든 채 {math.dist((p.x, p.z), (q[0], q[2])):.1f} m 물러난다")
    pad.guard(True)
    nav.goto(tm, pad, q, tolerance=1.0, timeout=3.0, log=lambda *a: None, mode_fn=lambda _s: "guard")
    pad.neutral(); pad.guard(True)
    return True


def near_foe(s, r=FIGHT_R):
    fs = [c for c in s.hostile(r) if c.hp > 0 and abs(c.y - s.player.y) < 2.5]
    return min(fs, key=lambda c: c.dist) if fs else None


_seen: dict = {}


def aware(c) -> bool:
    """그놈이 나를 알아챘나 — 사용자: "적이 너를 인지하면 가드하는 거야". 움직이기 시작했거나(1 s 에 0.25 m 넘게),
    가만히 선 애니(-1)·자는 애니(9000번대)가 아니면 알아챈 것으로 본다."""
    now = time.time()
    pos = (c.x, c.y, c.z)
    old = _seen.get(c.ptr)
    moved = False
    if old is not None:
        if now - old[1] >= 1.0:
            moved = math.dist(pos, old[0]) > 0.25
            _seen[c.ptr] = (pos, now, moved)
        else:
            moved = old[2]
    else:
        _seen[c.ptr] = (pos, now, False)
    a = c.anim if c.anim is not None else -1
    return moved or (a != -1 and not 9000 <= a < 10000)


def alerted(sn, r=12.0) -> bool:
    return any(c.hp > 0 and aware(c) for c in sn.hostile(r))


def attacking(c) -> bool:
    return c.anim is not None and 3000 <= c.anim < 3600


def fight(ptr, limit=45.0, log=print, reach=1.9, gone_r=7.0):
    """기사(브로드소드 한손 + 탑의 카이트 실드, 물리 100% 막음) — 사용자: "가드 안 하고 다니네".
    방패를 들고 다가가고, 그놈이 휘두르는 동안(3000번대)은 막기만, 휘두르기가 끝난 순간(또는 가만히 있을 때) 방패 내리고 R1 한 번 →
    곧장 방패. 스태미나 30 아래면 막은 채 뒤로 빠져 회복. 휘두를 때마다 (그놈 애니, HP 전→후, 내 HP) 기록 — 이 적들의 틈을 배운다."""
    t0 = time.time(); rec = []; prev_anim = None; last_swing = 0.0
    idle_since: dict = {}
    last_sp = last_myhp = None
    last_flee = 0.0
    pad.guard(True)
    while time.time() - t0 < limit:
        s = snap(); p = s.player
        c = next((x for x in s.chars if x.ptr == ptr), None)
        if p.hp <= 0:
            log(f"   사망 {rec}"); return "dead"
        if c is None or c.hp <= 0:
            log(f"   처치 {time.time()-t0:.1f}s {rec}"); pad.neutral(); pad.guard(True); return "killed"
        if c.dist > gone_r or abs(c.y - p.y) > 2.5:
            return "gone"
        st = control.world_to_stick(c.x - p.x, c.z - p.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
        pad.guard(True)
        if 0 < p.hp < p.max_hp * 0.4 and tm.goods_count(201):
            # 싸우는 중 회복 — 방패 든 채 그놈 반대쪽으로 빠진 뒤, 그놈이 휘두르는 중이 아니면 에스트
            # (3 번째 죽음: 353 에서 안 마시고 연타를 막기만 하다 화살까지 맞아 0)
            if nav.ground_ahead(nm, p, p.x - c.x, p.z - c.z, reach=1.5):
                pad.move(-0.8 * st[0], -0.8 * st[1]); time.sleep(0.6); pad.move(0, 0)
            s3 = snap(); c3 = next((x for x in s3.chars if x.ptr == ptr), None)
            if c3 is None or not attacking(c3) or c3.dist > 2.5:
                pad.guard(False); pad.use_item(); time.sleep(0.2); pad.release_due(); time.sleep(2.4)
                log(f"   싸우는 중 에스트 {p.hp} → {snap(5).player.hp} (남음 {tm.goods_count(201)})")
                pad.guard(True)
            prev_anim = None
            continue
        crowd = [x for x in s.hostile(4.0) if x.hp > 0 and abs(x.y - p.y) < 2.5]
        if len(crowd) >= 2 and time.time() - last_flee > 6.0:
            # 5 번째 죽음: '무리 반대쪽으로 반 걸음' 은 뒤가 벽이면 안 움직였다 → 걸어온 길로 달려 빠지고, 먼저 따라온 놈과 싸운다
            last_flee = time.time()
            if flee(p, crowd, log):
                s = snap(); p = s.player
                near = [x for x in s.hostile(7.0) if x.hp > 0 and abs(x.y - p.y) < 2.5]
                if near:
                    ptr = min(near, key=lambda x: x.dist).ptr
                prev_anim = None; last_sp = last_myhp = None
                continue
        if p.sp < 20:
            # 스태미나 바닥 — 막은 채 뒤로 (그놈 반대쪽으로 천천히)
            pad.move(-0.5 * st[0], -0.5 * st[1]); time.sleep(0.25); pad.move(0, 0)
            prev_anim = c.anim
            continue
        if c.dist > reach:
            pad.move(0.5 * st[0], 0.5 * st[1]); time.sleep(0.15); pad.move(0, 0)
            prev_anim = c.anim
            continue
        if abs(math.degrees(patrol.rel_angle(p, c))) > 25:
            pad.move(0.35 * st[0], 0.35 * st[1]); time.sleep(0.07); pad.move(0, 0)
        blocked = last_sp is not None and p.sp <= last_sp - 6 and p.hp >= (last_myhp or p.hp)
        last_sp, last_myhp = p.sp, p.hp
        if attacking(c) and not (blocked and p.sp >= 20):
            prev_anim = c.anim
            idle_since[ptr] = time.time()
            time.sleep(0.03)                                # 휘두르는 중 — 막기만
            continue
        if blocked and p.sp >= 20:
            # 막았다(스태미나가 깎였는데 HP 는 그대로) = 그놈 한 방이 방패에 닿았다 → 곧장 한 번 친다.
            # 4 번째 죽음: 쉬지 않고 이어 휘두르는 할로우(3001→3003…)에게 '휘두르기가 끝난 틈' 만 기다리다 45 s 동안 막기만 했다
            hp0, my0, ea = c.hp, p.hp, c.anim
            pad.guard(False)
            pad.tap(control.B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06); time.sleep(0.1); pad.release_due()
            time.sleep(0.5)
            pad.guard(True)
            time.sleep(0.3)
            last_swing = time.time()
            s2 = snap(); c2 = next((x for x in s2.chars if x.ptr == ptr), None)
            rec.append(("막고", ea, hp0, None if c2 is None else c2.hp, my0, s2.player.hp))
            last_sp, last_myhp = s2.player.sp, s2.player.hp
            prev_anim = None
            continue
        # 사용자: "전투 시 주로 가드하고, 필요할 때만 공격" — 기본은 막기. 치는 건 그놈 휘두르기가 막 끝난 틈(스태미나 60 이상)뿐,
        # 그놈이 3 s 넘게 가만히 서 있으면 한 번 (끝없는 대치 방지)
        # 3 번째 죽음: 휘두르기 끝난 틈에 '스태미나 60' 을 요구했더니 막느라 늘 모자라 한 번도 못 쳤다 → 20 이면 친다
        just_ended = prev_anim is not None and 3000 <= prev_anim < 3600 and p.sp >= 20
        idle_long = time.time() - max(last_swing, idle_since.setdefault(ptr, time.time())) > 2.0
        prev_anim = c.anim
        if not (just_ended or idle_long):
            time.sleep(0.03)
            continue
        time.sleep(0.16 if abs(math.degrees(patrol.rel_angle(p, c))) > 25 else 0.0)   # 스틱 놓음이 먹게 (스틱+R1 = 발차기)
        hp0, my0, ea = c.hp, p.hp, c.anim
        pad.guard(False)
        pad.tap(control.B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06); time.sleep(0.1); pad.release_due()
        time.sleep(0.55)
        pad.guard(True)
        time.sleep(0.35)
        last_swing = time.time()
        s2 = snap(); c2 = next((x for x in s2.chars if x.ptr == ptr), None)
        rec.append(("끝남" if just_ended else "틈", ea, hp0, None if c2 is None else c2.hp, my0, s2.player.hp))
    pad.neutral(); pad.guard(True); return "timeout"


def drink_if(frac=0.5):
    s = snap(8); p = s.player
    # HP 가 실제로 깎였을 때만 (죽고 화톳불에서 깨어난 걸 모르고 가득 찬 채 두 번 마셨다)
    if 0 < p.hp < p.max_hp * frac and tm.goods_count(201) and near_foe(s, 4.0) is None:
        pad.guard(False); pad.use_item(); time.sleep(0.2); pad.release_due(); time.sleep(2.8)
        print("   에스트", p.hp, "→", snap(8).player.hp, "남음", tm.goods_count(201))


def shooter(s):
    """가까이 붙은 놈 없이 HP 가 줄 때 — 활 쏘는 놈(3~25 m, 같은 층 ±4 m, 알아챈 놈) 중 가장 가까운 놈."""
    fs = [c for c in s.hostile(25.0) if c.hp > 0 and 3.0 < c.dist and abs(c.y - s.player.y) < 4.0 and aware(c)]
    return min(fs, key=lambda c: c.dist) if fs else None


def go(target, tol=0.8, log=print):
    """경로를 한 점씩 걷는다. 매 점마다 가까운 적을 먼저 잡는다. → 'arrived' | 'dead' | 실패"""
    last_hp = None
    for attempt in range(12):
        s = snap(); p = s.player
        if p.hp <= 0:
            return "dead"
        if last_hp is not None and p.hp < last_hp and near_foe(s, 3.0) is None:
            # 사용자: "화살에 맞아서 피가 줄잖아" — 붙은 놈 없이 깎이면 쏘는 놈부터 잡으러 간다
            sh = shooter(s)
            if sh is not None:
                log(f"   화살? HP {last_hp} → {p.hp} — 쏘는 놈 {sh.npc_param} {sh.dist:.1f} m 부터")
                path = [tuple(q) for q in (nm.find_path((p.x, p.y, p.z), (sh.x, sh.y, sh.z)) or [])[1:]]
                nav.follow(tm, pad, path, terrain=nm, default_tol=1.2, mode_fn=lambda _s: "guard",
                           stop_fn=lambda sn: near_foe(sn, 2.5) is not None, log=lambda *a: None)
                f2 = near_foe(snap(), 7.0)
                if f2 is not None and fight(f2.ptr, log=log) == "dead":
                    return "dead"
        drink_if(0.55)
        last_hp = snap(5).player.hp
        f = near_foe(s)
        if f is not None:
            log(f"   적 {f.npc_param} {f.dist:.1f} m — 먼저 잡는다")
            if fight(f.ptr, log=log) == "dead":
                return "dead"
            drink_if()
            continue
        if math.dist((p.x, p.y, p.z), target) < tol:
            pad.neutral(); return "arrived"
        path = nav.trim_path([tuple(q) for q in (nm.find_path((p.x, p.y, p.z), target) or [])[1:]], target) + [target]
        # 알아챈 적이 12 m 안이면 방패 든 채 걷는다 (사용자: "가드 안 하고 다니네", "적이 너를 인지하면 가드")
        r = nav.follow(tm, pad, path, terrain=nm, default_tol=0.8,
                       mode_fn=lambda sn: "guard" if alerted(sn) else "walk",
                       stop_fn=lambda sn: near_foe(sn) is not None, log=lambda *a: None)
        if r == "dead":
            return "dead"
        if r not in ("arrived", "stopped"):
            log(f"   경로 {r} — 다시")
    s = snap(); p = s.player
    pad.neutral()
    return "arrived" if math.dist((p.x, p.y, p.z), target) < tol + 0.7 else "gave up"


def safe_end(log=print):
    """스크립트를 끝내기 전 — 알아챈 적이 5 m 안이면 메뉴로 나갔다 온다 (끝나면 가상 패드가 빠져 가드가 풀린다: 4 번째 죽음)."""
    s = snap(8)
    if s and s.player.hp > 0 and any(c.hp > 0 and c.dist < 5.0 and aware(c) for c in s.hostile(5.0)):
        pad.guard(True)
        q = quitout.quit_out(tm, pad, gap=quitout.MENU_GAP, settle=0.1, ready_wait=0.05)
        if q is not None:
            quitout.reload(pad); time.sleep(1.5)
        log(f"   끝내기 전 적이 붙어 있어 종료→재접속 ({q})")
    pad.neutral()


def dismiss():
    """안내·획득 창이 떠 있으면 곧장 A 로 끈다 (사용자: 안내는 보자마자 꺼)."""
    if tm.menu_open():
        L.press_a(pad); time.sleep(0.6)
