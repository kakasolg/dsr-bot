"""발차기 실전 시험 — 가까운 할로우에게 다가가 발차기를 넣고, 적이 어떻게 반응하는지 애니로 기록한다.

  python kicktest.py [발차기 횟수] [--rest]

알고 싶은 것 (사용자: "방패 든 적의 가드를 깨서 도망치거나 틈을 만들 때 유리"):
  · 발차기 뒤 적의 애니가 무엇으로 바뀌나 — 비틀거림(가드 깨짐)인가, 그냥 막았나
  · 비틀거리면 바로 약공을 넣었을 때 피해가 평소보다 큰가 (가드 깨진 상대)
  · 차는 동안 내가 맞나

안전: 반사 스레드가 적 공격 시작 즉시 가드. HP 55% 아래면 중단하고 물러난다. 결과는 data/kicktest.json.
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
OUT = ROOT / "data" / "kicktest.json"
KICK_DIST = 1.5          # 이 안에서 찬다 (발차기 사거리는 짧다)
STOP_HP = 0.55


def face_stick(s, tgt):
    return control.world_to_stick(tgt.x - s.player.x, tgt.z - s.player.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)


def watch_enemy(tm, ptr, sec: float) -> tuple[list, int | None]:
    """sec 동안 그 적의 애니 전환을 5 ms 간격으로 기록 → (전환 목록, 마지막 HP)."""
    mapd = tm.q(ptr + 0x68)
    st = tm.q(mapd + 0x48) if mapd else None
    addr = st + 0x80 if st else None
    seq, last, t0 = [], None, time.perf_counter()
    while time.perf_counter() - t0 < sec:
        a = tm.i32(addr) if addr else None
        if a != last:
            seq.append((round((time.perf_counter() - t0) * 1000), a))
            last = a
        time.sleep(0.005)
    c = tm.read_chr(ptr)
    return seq, (c.hp if c else None)


def watch_both(tm, ptr, sec: float) -> tuple[list, int | None, list]:
    """적 애니 전환 + 내 애니(중복 제거) 를 같이 본다 → (적 전환, 적 HP, 내 애니 목록)."""
    def addr_of(p):
        mapd = tm.q(p + 0x68)
        st = tm.q(mapd + 0x48) if mapd else None
        return st + 0x80 if st else None
    ea, ma = addr_of(ptr), addr_of(tm.player_ptr())
    seq, last, mine, t0 = [], None, [], time.perf_counter()
    while time.perf_counter() - t0 < sec:
        a = tm.i32(ea) if ea else None
        if a != last:
            seq.append((round((time.perf_counter() - t0) * 1000), a)); last = a
        m = tm.i32(ma) if ma else None
        if m is not None and (not mine or mine[-1] != m):
            mine.append(m)
        time.sleep(0.005)
    c = tm.read_chr(ptr)
    return seq, (c.hp if c else None), mine


def main() -> None:
    n_kicks = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 5
    tm = env.make_telemetry({})
    control.focus_game()
    pad = control.Pad()
    if "--rest" in sys.argv:
        import farm
        s = tm.snapshot(within=1.0)
        nm0 = navmesh.Navmesh(navwalk.locate(tm, s.player)[0])
        print("화톳불 휴식 (적 부활) ...", farm.rest(tm, pad, nm0, farm.SPOTS["firelink-bonfire"]), flush=True)
    s = tm.snapshot(within=80.0)
    # 할로우(c25xx)만 — 묘지 해골(c29xx)은 이 시험의 대상이 아니다 (패링·2:1)
    foes = sorted((c for c in s.hostile(80.0) if c.hp > 0 and abs(c.y - s.player.y) < 15
                   and tm.model(c.ptr).startswith("c25")), key=lambda c: c.dist)
    if not foes:
        print("근처에 적 없음"); return
    tgt = foes[0]
    print(f"대상: npc {tgt.npc_param} ({tm.model(tgt.ptr)}) HP {tgt.hp}  {tgt.dist:.1f} m  @({tgt.x:.1f},{tgt.y:.1f},{tgt.z:.1f})", flush=True)

    rfx = reflex.Reflex(tm, pad)
    rfx.start()
    nm = navmesh.Navmesh(navwalk.locate(tm, s.player)[0])
    path = nm.find_path((s.player.x, s.player.y, s.player.z), (tgt.x, tgt.y, tgt.z))
    # 대상 6 m 앞까지는 경로로, 그 뒤는 가드 올리고 걸어서 붙는다
    for q in (path or [])[1:]:
        cur = tm.read_chr(tgt.ptr)
        if cur is None or cur.hp <= 0:
            break
        me = tm.snapshot(within=1.0).player
        if math.dist((me.x, me.z), (cur.x, cur.z)) < 6.0:
            break
        if nav.goto(tm, pad, q, tolerance=1.5, timeout=20, log=lambda *a: None, terrain=nm,
                    mode_fn=lambda _s: "walk") == "dead":
            print("사망"); return

    rows = []
    locked = False
    kicks = 0
    t_end = time.time() + 120
    while kicks < n_kicks and time.time() < t_end:
        s = tm.snapshot(within=10.0)
        if not s or s.player.hp <= 0:
            print("사망"); break
        cur = next((c for c in s.chars if c.ptr == tgt.ptr), None)
        if cur is None or cur.hp <= 0:
            print("대상 처치됨"); break
        rfx.update(s)
        me = s.player
        if me.hp / me.max_hp < STOP_HP:
            print(f"HP {me.hp} — 중단"); break
        if not locked and cur.dist < 8.0:
            pad.lock_on(); locked = True
        pad.guard(True)
        sx, sy = face_stick(s, cur)
        if cur.dist > KICK_DIST:
            pad.move(sx * 0.5, sy * 0.5)            # 가드 든 채 걸어서 붙는다
            pad.release_due(); time.sleep(0.02)
            continue
        pad.move(0.0, 0.0)
        enemy_attacking = (cur.anim or 0) in patrol.ENEMY_ATTACK_ANIMS or rfx.threat
        if enemy_attacking or me.sp < me.max_sp * 0.5 or patrol.player_locked(me.anim):
            pad.release_due(); time.sleep(0.02)     # 적이 휘두르는 중·스태미나 부족 — 막으면서 기다린다
            continue
        # ── 발차기 ──
        hp_e0, hp_me0, anim_e0 = cur.hp, me.hp, cur.anim
        # 가드(L1)를 **정말로** 내린 뒤 찬다. 실측: 반사 스레드의 force_guard 로 L1 이 눌린 채 스틱+RB 를 넣었더니
        # 발차기(333100)가 아니라 약공(333000)이 나갔다 — 가드 든 채 스틱+RB 는 그냥 약공이다.
        pad.force_guard = False
        pad.guard(False)
        time.sleep(0.08)
        if pad.guard_held():
            continue
        pad.kick(sx, sy)
        time.sleep(0.07); pad.release_due()
        pad.move(0.0, 0.0)
        seq, hp_e1, my_anims = watch_both(tm, cur.ptr, 1.0)
        me1 = tm.snapshot(within=1.0).player
        kicked = patrol.MY_KICK_ANIM in my_anims
        # 비틀거림(적 애니가 공격·대기가 아닌 걸로 바뀜)이면 바로 약공 — 가드 깨진 상대에게 들어가는지
        stagger = [a for _, a in seq if a is not None and not (3000 <= a < 3500) and a not in (-1, anim_e0)]
        follow = None
        if stagger:
            hp_before = tm.read_chr(cur.ptr).hp if tm.read_chr(cur.ptr) else None
            pad.attack(); time.sleep(0.07); pad.release_due()
            seq2, hp_after = watch_enemy(tm, cur.ptr, 0.9)
            follow = {"dmg": (hp_before - hp_after) if (hp_before is not None and hp_after is not None) else None,
                      "enemy_anims": seq2}
        kicks += 1
        row = {"kick": kicks, "kicked": kicked, "enemy": cur.npc_param, "dist": round(cur.dist, 2), "enemy_anim_before": anim_e0,
               "enemy_anims_after": seq, "enemy_dmg": (hp_e0 - hp_e1) if hp_e1 is not None else None,
               "my_dmg": hp_me0 - me1.hp, "my_anims": my_anims, "stagger": stagger[:4], "follow_r1": follow}
        rows.append(row)
        print(f"  발차기 {kicks} ({'발차기 나감' if kicked else '발차기 아님 ' + str(my_anims[:3])}): 적 애니 {seq[:6]}  적 피해 {row['enemy_dmg']}  내 피해 {row['my_dmg']}"
              f"  비틀 {stagger[:3]}  후속 약공 {follow and follow['dmg']}", flush=True)
        pad.guard(True)
        t_g = time.time()
        while time.time() - t_g < 1.0:                # 찬 뒤엔 가드 올리고 잠깐 본다
            pad.release_due(); time.sleep(0.02)

    rfx.stop(); rfx.join(1.0)
    pad.guard(False); pad.neutral()
    if locked:
        pad.lock_on()
    # 끝나면 적 사이에 세워 두지 않는다 — 화톳불로 싸우며 돌아간다 (실측: 끝난 뒤 서 있다가 323 맞음)
    import gc, subprocess
    pad.pad = None; gc.collect(); time.sleep(1.5)   # 가상 패드는 하나만 — 돌아가는 프로세스가 새로 꽂는다
    subprocess.run([sys.executable, str(ROOT / "navwalk.py"), "to", "-54.06", "-59.95", "58.07", "--run", "--fight"],
                   cwd=ROOT, capture_output=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"target": tgt.npc_param, "rows": rows, "reflex": rfx.report()}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"저장: {OUT}  발차기 {len(rows)}회")


if __name__ == "__main__":
    main()
