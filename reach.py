"""무기 유효 사거리 실측 — 무기를 바꾸면 반드시 다시 잰다.

  python reach.py [휘두를 횟수]

일부러 사거리를 넓게(PROBE_RANGE) 잡고 교전시켜, **휘두른 순간의 거리**와 **피해가 들어갔는지**를 짝지어 기록한다.
맞은 거리의 최댓값이 곧 유효 사거리. 빗나간 거리와 겹치는 구간이 있으면 그게 아슬아슬한 경계다.

플레이북의 attack_range 는 이 값보다 0.2~0.3 m 짧게 잡는 게 안전하다 (적도 움직이므로).
실측 기록: 도끼 1.8 m 기준으로 쓰다가 할버드로 바꾸면서 다시 재야 했다.

── 이 측정의 한계 ───────────────────────────
프롬 게임은 **벽을 통과해서 때리거나 맞는 일이 있다** (사용자 경험). 즉 "그 거리에서 맞았다"가
"그 거리면 언제나 닿는다"를 뜻하지 않는다. 각도·지형·적의 이동에 따라 같은 거리에서도 빗나간다.
그러니 여기서 나온 최댓값을 그대로 쓰지 말고, 맞은 거리의 **중앙값 근처**를 기준으로 잡는 편이 안전하다.
"""
from __future__ import annotations

import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import json
import math
from pathlib import Path

import control
import env
import nav
import navmesh
import patrol
import playbook

SPOTS = json.loads((Path(__file__).parent / "data" / "spots.json").read_text(encoding="utf-8"))
PROBE_RANGE = 4.2     # 이 안이면 일단 휘두른다 (실제 사거리보다 넉넉히)
APPROACH = 7.0        # 적이 이보다 멀면 다가간다
HIT_WINDOW = 1.2      # 휘두르고 이 안에 적 HP 가 줄면 그 스윙이 맞은 것


def main():
    swings_wanted = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    tm = env.make_telemetry({})
    s = tm.snapshot(within=30.0)
    if not s:
        print("텔레메트리 없음"); return
    pb = playbook.Playbook()
    pb.attack_range, pb.hold_range, pb.lock_range = PROBE_RANGE, PROBE_RANGE + 0.6, 10.0
    pb.attack_cooldown, pb.crowd_threshold = 1.6, 99   # 다수라고 도망가지 말 것 (측정 중)
    control.focus_game()
    pad = control.Pad()
    guard = patrol.Guard(pad, pb, log=lambda *a: None)
    print(f"측정 시작 — {PROBE_RANGE} m 안이면 휘두른다. 목표 {swings_wanted}회. hp {s.player.hp}/{s.player.max_hp}")

    rec = []          # (거리, 맞았나, 피해)
    state = {"pend": None}   # (시각, 거리, 적ptr, 적hp)
    t0 = time.time()

    def tick(sn, _dist=None):
        """**nav.goto 안에서** 돌아야 한다. 밖에서만 돌리면 goto 가 블로킹하는 동안 Guard 가 멈춰
        6 초에 한 번꼴로만 휘두른다 (실측: 240 초에 스윙 1회)."""
        pend = state["pend"]
        cur = guard.engage
        if pend:
            if cur is not None and cur.ptr == pend[2] and cur.hp < pend[3]:
                rec.append((pend[1], True, pend[3] - cur.hp))
                print(f"  맞음  {pend[1]:.2f} m  피해 {pend[3]-cur.hp}")
                state["pend"] = None
            elif time.time() - pend[0] > HIT_WINDOW:
                rec.append((pend[1], False, 0))
                print(f"  빗나감 {pend[1]:.2f} m")
                state["pend"] = None
        a = guard.tick(sn)
        if a in ("attack", "counter", "combo") and guard.engage is not None and state["pend"] is None:
            state["pend"] = (time.time(), guard.engage.dist, guard.engage.ptr, guard.engage.hp)

    bonfire, spot = SPOTS.get("firelink-bonfire"), SPOTS.get("burg-approach")
    nm = navmesh.Navmesh(spot["map"]) if spot else None

    def walk_to(xyz, mode="sprint", timeout=30):
        cur = tm.snapshot(within=1.0)
        for wp in nm.find_path((cur.player.x, cur.player.y, cur.player.z), xyz)[1:]:
            if nav.goto(tm, pad, wp, tolerance=2.0, timeout=timeout, log=lambda *a: None,
                        mode_fn=lambda _s: mode, on_tick=tick,
                        engage_fn=lambda _s: guard.engage_pos()) == "dead":
                return False
        pad.neutral()
        return True

    def respawn() -> bool:
        """화톳불로 돌아가 쉬고(적 리스폰·HP 회복) 시험장으로 복귀."""
        if not (bonfire and spot and nm):
            return False
        print("  … 적 소진 — 화톳불에서 쉬고 돌아온다")
        if not walk_to(tuple(bonfire["stand"])):
            return False
        for _ in range(4):
            tm.safe_warp(*bonfire["stand"], bonfire["heading"], hold_s=3.0)
            time.sleep(0.8)
            pad.interact()
            for _ in range(16):            # 앉는 데 2.5 s (anim2 -1 → 7710 → 7711)
                time.sleep(0.25)
                if tm.sitting():
                    break
            if tm.sitting():
                break
        if not tm.sitting():
            return False
        time.sleep(1.0)
        import vgamepad
        for _ in range(6):                 # 일어나기
            if not tm.sitting():
                break
            pad.tap(vgamepad.XUSB_BUTTON.XUSB_GAMEPAD_B, 0.1)
            time.sleep(1.0)
        guard.engage, guard.ignore = None, {}
        return walk_to(tuple(spot["pos"]), mode="walk")

    try:
        while len(rec) < swings_wanted and time.time() - t0 < 900:
            s = tm.snapshot(within=30.0)
            if not s or s.player.hp <= 0:
                print("사망 — 중단"); break
            if s.player.hp < s.player.max_hp * 0.4:
                print("HP 40 % 미만 — 중단"); break
            # 다가갈 때는 높이차를 따지지 않는다 — 비탈 위 적은 멀리서 보면 +2 m 여도 붙으면 같은 높이가 된다
            # (Guard 의 교전 판정은 자체 기준 2 m 를 쓴다)
            host = [c for c in s.hostile(30.0) if c.hp > 0 and abs(c.y - s.player.y) < 6.0]
            if guard.engage is not None and guard.engage.hp > 0:
                tgt = (guard.engage.x, guard.engage.y, guard.engage.z)
            elif host:
                tgt = (host[0].x, host[0].y, host[0].z)
            else:
                # 적을 다 잡았다 → 화톳불에서 쉬어 리스폰시키고 돌아온다 (표본을 모으려면 반복해야 한다)
                if not respawn():
                    print("리스폰 순환 실패 — 중단"); break
                continue
            nav.goto(tm, pad, tgt, tolerance=PROBE_RANGE - 0.6, timeout=8, log=lambda *a: None,
                     on_tick=tick, mode_fn=lambda _s: guard.mode,
                     engage_fn=lambda _s: guard.engage_pos())
    finally:
        pad.guard(False)
        pad.neutral()

    if not rec:
        print("표본 없음"); return
    hit = sorted(d for d, ok, _ in rec if ok)
    miss = sorted(d for d, ok, _ in rec if not ok)
    print(f"\n스윙 {len(rec)}회 — 맞음 {len(hit)}, 빗나감 {len(miss)}")
    if hit:
        print(f"  맞은 거리 : {hit[0]:.2f} ~ {hit[-1]:.2f} m  (중앙 {hit[len(hit)//2]:.2f})")
    if miss:
        print(f"  빗나간 거리: {miss[0]:.2f} ~ {miss[-1]:.2f} m  (중앙 {miss[len(miss)//2]:.2f})")
    if hit:
        edge = hit[-1]
        safe = max(1.2, round(edge - 0.25, 1))
        print(f"  → 유효 사거리 ≈ {edge:.2f} m,  플레이북 attack_range 권장 {safe}")
        if miss and min(miss) < edge:
            print(f"     (주의: {min(miss):.2f} m 에서도 빗나간 기록이 있다 — 각도·적 이동 탓, 경계가 흐리다)")


def direct(n_swings: int = 28):
    """Guard 없이 직접 거리를 맞춰 가며 휘두른다 — 순수 측정용.

    Guard 를 쓰면 HP 가 낮을 때 후퇴하고 성배병을 마시느라 스윙이 거의 안 나온다 (실측: 10 분에 4 회).
    여기서는 목표 거리 목록을 돌며 그 거리에 서서 한 대씩 휘두르고, 휘두른 순간의 실제 거리와
    적 HP 변화를 짝지어 기록한다. 맞는 동안에도 가드를 들고 버틴다."""
    import vgamepad
    tm = env.make_telemetry({})
    control.focus_game()
    pad = control.Pad()
    B = vgamepad.XUSB_BUTTON
    targets = [3.6, 3.2, 2.8, 2.4, 2.0, 1.6, 1.2]
    state_lock = {"ptr": None, "on": False}
    rec = []
    t0 = time.time()
    try:
        while len(rec) < n_swings and time.time() - t0 < 600:
            s = tm.snapshot(within=30.0)
            if not s or s.player.hp <= 0:
                print("사망 — 중단"); break
            p = s.player
            live = [c for c in s.hostile(30.0) if c.hp > 0 and abs(c.y - p.y) < 3.0]
            if not live:
                print("주변에 살아 있는 적 없음 — 중단"); break
            if p.hp < p.max_hp * 0.45:
                pad.guard(False)
                pad.tap(B.XUSB_GAMEPAD_X, 0.1)   # 성배병
                time.sleep(2.5)
                continue
            tgt = live[0]
            # 락온을 반드시 건다. 락온이 없으면 공격이 **캐릭터가 마지막으로 향한 방향**으로 나가서,
            # 적이 옆으로 돌면 붙어 있어도 허공을 친다 (실측: 락온 없이 8스윙 0명중, 0.85 m 에서도 빗나감).
            if state_lock["ptr"] != tgt.ptr:
                if state_lock["on"]:
                    pad.lock_on(); time.sleep(0.15)
                pad.lock_on(); time.sleep(0.25)
                state_lock.update(ptr=tgt.ptr, on=True)
            want = targets[len(rec) % len(targets)]
            # 그 거리에 설 지점 = 적에서 우리 쪽으로 want m
            ux, uz = p.x - tgt.x, p.z - tgt.z
            n = math.hypot(ux, uz) or 1.0
            stand = (tgt.x + ux / n * want, tgt.y, tgt.z + uz / n * want)
            pad.guard(True)
            nav.goto(tm, pad, stand, tolerance=0.35, timeout=6, log=lambda *a: None,
                     mode_fn=lambda _s: "creep")
            s2 = tm.snapshot(within=30.0)
            cur = next((c for c in s2.hostile(30.0) if c.ptr == tgt.ptr), None)
            if cur is None or cur.hp <= 0:
                continue
            d0, hp0 = cur.dist, cur.hp
            pad.tap(B.XUSB_GAMEPAD_RIGHT_SHOULDER, 0.06)
            hit, dmg = False, 0
            for _ in range(int(HIT_WINDOW / 0.1)):
                time.sleep(0.1)
                s3 = tm.snapshot(within=30.0)
                c3 = next((c for c in s3.hostile(30.0) if c.ptr == tgt.ptr), None)
                if c3 is not None and c3.hp < hp0:
                    hit, dmg = True, hp0 - c3.hp
                    break
            rec.append((d0, hit, dmg))
            print(f"  목표 {want:.1f} m → 실제 {d0:.2f} m  {'맞음 피해 ' + str(dmg) if hit else '빗나감'}")
    finally:
        if state_lock["on"]:
            pad.lock_on()
        pad.guard(False)
        pad.neutral()
    report(rec)


def report(rec):
    if not rec:
        print("표본 없음"); return
    hit = sorted(d for d, ok, _ in rec if ok)
    miss = sorted(d for d, ok, _ in rec if not ok)
    print(f"\n스윙 {len(rec)}회 — 맞음 {len(hit)}, 빗나감 {len(miss)}")
    if hit:
        print(f"  맞은 거리 : {hit[0]:.2f} ~ {hit[-1]:.2f} m  (중앙 {hit[len(hit)//2]:.2f})")
    if miss:
        print(f"  빗나간 거리: {miss[0]:.2f} ~ {miss[-1]:.2f} m  (중앙 {miss[len(miss)//2]:.2f})")
    # 거리 구간별 명중률
    import collections
    bucket = collections.defaultdict(lambda: [0, 0])
    for d, ok, _ in rec:
        b = bucket[round(d * 2) / 2]
        b[0] += 1
        b[1] += 1 if ok else 0
    print("  거리별 명중률:")
    for d in sorted(bucket):
        n, k = bucket[d]
        print(f"    {d:.1f} m : {k}/{n}")
    if hit:
        good = [d for d in sorted(bucket) if bucket[d][1] / bucket[d][0] >= 0.5]
        if good:
            print(f"  → 절반 이상 맞는 최대 거리 {max(good):.1f} m,  플레이북 attack_range 권장 {max(1.2, max(good)-0.2):.1f}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "direct":
        direct(int(sys.argv[2]) if len(sys.argv) > 2 else 28)
    else:
        main()
