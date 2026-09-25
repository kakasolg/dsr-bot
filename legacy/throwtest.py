"""투척 실전 시험 — 할로우에게 9 m 까지만 다가가 서서, 투척 나이프와 파이어밤을 번갈아 던지며 명중·피해를 잰다.

  python throwtest.py [던질 횟수] [--rest] [--item knife|bomb|both]

왜: 발차기는 붙어야 하고 타이밍이 어렵다 (사용자). 멀리서 던지면 2:1 로 둘러싸일 일이 없다
(발차기 시험에서 옆·뒤의 두 번째 할로우에게 14대 맞고 사망 — 전부 90~147° 방향).

  · 칸 선택은 메모리로 확인 (에스트 205 / 나이프 290 / 폭탄 292). 눈 감고 누르지 않는다.
  · 락온한 대상이 3.5~9 m 이고 **돌진 중이 아닐 때만** 던진다 (던지는 동작 중엔 못 막는다).
  · 3 m 안으로 붙으면 던지기를 멈추고 가드 — 적 공격이 끝난 직후에만 한 대 (막고 → 한 대).
  · 끝나면 에스트로 칸을 돌리고 화톳불로 돌아간다 (적 사이에 세워 두지 않는다).
결과: data/throwtest.json
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env
import nav
import navmesh
import navwalk
import patrol
import reflex

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "throwtest.json"
ITEM_KNIFE = 290
STAND_DIST = 9.0
THROW_MIN, THROW_MAX = 3.5, 9.5
CLOSE = 3.0
STOP_HP = 0.5
BONFIRE = (-54.06, -59.95, 58.07)


def select(tm, pad, item: int, timeout: float = 3.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        cur = tm.selected_item()
        if cur == item or (item == 0 and patrol.is_estus(cur)):
            return True
        pad.item_next()
        t = time.time()
        while time.time() - t < 0.35:
            pad.release_due(); time.sleep(0.01)
    return False


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 6
    mode = sys.argv[sys.argv.index("--item") + 1] if "--item" in sys.argv else "both"
    plan = {"knife": [ITEM_KNIFE] * n, "bomb": [patrol.ITEM_BOMB] * n}.get(mode) or \
        [ITEM_KNIFE if i % 2 == 0 else patrol.ITEM_BOMB for i in range(n)]
    tm = env.make_telemetry({})
    control.focus_game()
    pad = control.Pad()
    if "--rest" in sys.argv:
        import farm
        s = tm.snapshot(within=1.0)
        nm0 = navmesh.Navmesh(navwalk.locate(tm, s.player)[0])
        print("화톳불 휴식 ...", farm.rest(tm, pad, nm0, farm.SPOTS["firelink-bonfire"]), flush=True)
    s = tm.snapshot(within=80.0)
    foes = sorted((c for c in s.hostile(80.0) if c.hp > 0 and abs(c.y - s.player.y) < 15
                   and tm.model(c.ptr).startswith("c25")), key=lambda c: c.dist)
    if not foes:
        print("근처에 할로우 없음"); return
    tgt = foes[0]
    print(f"대상: npc {tgt.npc_param} ({tm.model(tgt.ptr)}) HP {tgt.hp}  {tgt.dist:.1f} m", flush=True)
    t_log = 0.0

    rfx = reflex.Reflex(tm, pad)
    rfx.start()
    nm = navmesh.Navmesh(navwalk.locate(tm, s.player)[0])
    path = nm.find_path((s.player.x, s.player.y, s.player.z), (tgt.x, tgt.y, tgt.z)) or []
    for q in path[1:]:
        cur = tm.read_chr(tgt.ptr)
        me = tm.snapshot(within=1.0).player
        if cur is None or cur.hp <= 0 or math.dist((me.x, me.z), (cur.x, cur.z)) < STAND_DIST:
            break
        if nav.goto(tm, pad, q, tolerance=1.5, timeout=20, log=lambda *a: None, terrain=nm,
                    mode_fn=lambda _s: "walk") == "dead":
            print("사망"); break
    pad.neutral()

    rows, locked, i = [], False, 0
    last_throw, last_attack = 0.0, 0.0
    prev_attacking = False
    dist_hist: list[tuple[float, float]] = []
    t_end = time.time() + 150
    while i < len(plan) and time.time() < t_end:
        s = tm.snapshot(within=40.0)
        if not s or s.player.hp <= 0:
            print("사망"); break
        me = s.player
        rfx.update(s)
        rc = tm.read_chr(tgt.ptr)             # 스냅샷 반경과 상관없이 직접 읽는다
        dead = rc is None or rc.hp <= 0       # (예전엔 반경 밖이면 '처치'로 오판해서 한 번도 안 던지고 끝냄)
        cur = next((c for c in s.chars if c.ptr == tgt.ptr), None)
        if not dead and cur is None:
            cur = rc
            cur.dist = math.dist((rc.x, rc.y, rc.z), (me.x, me.y, me.z))
        if dead:
            alive = sorted((c for c in s.hostile(15.0) if c.hp > 0 and not patrol.dormant(c)), key=lambda c: c.dist)
            if not alive:
                print("대상 처치 — 근처 적 없음"); break
            tgt, cur, locked = alive[0], alive[0], False
            dist_hist.clear()
            print(f"  다음 대상: npc {tgt.npc_param} {tgt.dist:.1f} m", flush=True)
            pad.lock_on(); time.sleep(0.1); pad.release_due()
        if me.hp / me.max_hp < STOP_HP:
            print(f"HP {me.hp} — 중단"); break
        now = time.time()
        dist_hist.append((now, cur.dist)); dist_hist[:] = [h for h in dist_hist if now - h[0] < 0.6]
        v = (dist_hist[0][1] - dist_hist[-1][1]) / max(0.05, dist_hist[-1][0] - dist_hist[0][0]) if len(dist_hist) > 2 else 0.0
        ttc = (cur.dist - 1.5) / v if v > 0.3 else 99.0
        if not locked and cur.dist < 15:
            pad.lock_on(); locked = True
        near = min((c.dist for c in s.hostile(6.0) if not patrol.dormant(c)), default=99)
        attacking = (cur.anim or 0) in patrol.ENEMY_ATTACK_ANIMS or rfx.threat
        if near < CLOSE:
            # 붙었다 — 막고 → 한 대 (적 공격이 막 끝났을 때만)
            pad.guard(True)
            if prev_attacking and not attacking and now - last_attack > 1.0 and me.sp > me.max_sp * 0.3:
                pad.attack(); last_attack = now
            prev_attacking = attacking
            pad.release_due(); time.sleep(0.02)
            continue
        prev_attacking = attacking
        pad.guard(True)
        want = plan[i]
        if cur.dist > THROW_MAX and near > 6.0:
            sx, sy = control.world_to_stick(cur.x - me.x, cur.z - me.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
            pad.move(sx * 0.5, sy * 0.5)       # 사거리 밖 — 가드 든 채 걸어서 다가간다
            pad.release_due(); time.sleep(0.02)
            continue
        pad.move(0.0, 0.0)
        if now - t_log > 3.0:
            t_log = now
            print(f"    대기: 대상 {cur.dist:.1f} m, 다가오는 속도 {v:.1f} m/s, 높이차 {cur.y - me.y:+.1f}", flush=True)
        if not (THROW_MIN <= cur.dist <= THROW_MAX and ttc > patrol.THROW_TIME and not rfx.threat
                and now - last_throw > 2.0 and abs(cur.y - me.y) < 3.0):
            pad.release_due(); time.sleep(0.02)
            continue
        if not select(tm, pad, want):
            print(f"  칸 선택 실패 ({want})"); break
        hp0, my0, d0 = cur.hp, me.hp, cur.dist
        pad.force_guard = False
        pad.guard(False)
        time.sleep(0.05)
        pad.use_item()
        last_throw = time.time()
        t = time.time()
        dmg_at = None
        while time.time() - t < 2.0:                         # 날아가는 시간까지 본다
            pad.release_due()
            c1 = tm.read_chr(cur.ptr)
            if c1 and c1.hp < hp0 and dmg_at is None:
                dmg_at = round(time.time() - t, 2)
            time.sleep(0.01)
        c1 = tm.read_chr(cur.ptr)
        me1 = tm.snapshot(within=1.0).player
        i += 1
        row = {"n": i, "item": "knife" if want == ITEM_KNIFE else "bomb", "dist": round(d0, 2),
               "enemy": cur.npc_param, "enemy_dmg": hp0 - (c1.hp if c1 else 0), "hit_after_s": dmg_at,
               "enemy_hp_left": c1.hp if c1 else None, "my_dmg": my0 - me1.hp, "ttc": round(ttc, 1)}
        rows.append(row)
        print(f"  {i}: {row['item']:5} {row['dist']:.1f} m → 적 피해 {row['enemy_dmg']} ({dmg_at}s)  "
              f"남은 HP {row['enemy_hp_left']}  내 피해 {row['my_dmg']}", flush=True)

    select(tm, pad, 0)                                          # 반드시 에스트로
    rfx.stop(); rfx.join(1.0)
    pad.guard(False); pad.neutral()
    if locked:
        pad.lock_on(); time.sleep(0.1); pad.release_due()
    OUT.write_text(json.dumps({"rows": rows, "reflex": rfx.report()}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {OUT}  {len(rows)}회  선택 칸 {tm.selected_item()}", flush=True)
    import gc, subprocess
    pad.pad = None; gc.collect(); time.sleep(1.5)
    subprocess.run([sys.executable, str(ROOT / "navwalk.py"), "to", *map(str, BONFIRE), "--run", "--fight"],
                   cwd=ROOT, capture_output=True)
    s = env.make_telemetry({}).snapshot(within=1.0)
    print(f"복귀: hp {s.player.hp}  ({s.player.x:.1f},{s.player.z:.1f})", flush=True)


if __name__ == "__main__":
    main()
