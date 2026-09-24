"""배틀 액스 강공(R2) 실측 — 경사로 망자를 나이프로 끌어와 평지에서 강공만 쓴다.

  python axe_heavy_test.py [--targets 1,3] [--reach 1.8]

재는 것 (한 번 휘두를 때마다 한 줄, data/runs/<시각>_axe-heavy.jsonl 의 "heavy" 사건):
  피해 · 그놈 애니 흐름(휘청 3500대? 넘어짐 9900대?) · 내 애니 흐름과 R2 부터 -1 로 돌아올 때까지 시간 · 스태미나 소모 · 거리 · 받은 피해
시작은 불의 제전에서 쉬고(적 부활). 지금 자리가 경사로 아래면 다크사인으로 올라간다 (소울 확인 후).
"""
from __future__ import annotations

import argparse
import math
import sys
import time

sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env
import navmesh
from run import Log
from souls import missions, moves as M, weapons
from souls.field import Field
from souls.watch import Escape


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default="1,3")
    ap.add_argument("--reach", type=float, default=1.8, help="이 안이면 R2")
    ap.add_argument("--max", type=int, default=4, help="한 놈당 강공 횟수 상한")
    a = ap.parse_args()
    targets = [int(x) for x in a.targets.split(",")]

    log = Log("axe-heavy")
    tm = env.make_telemetry({})
    control.focus_game()
    pad = control.Pad()
    nm = navmesh.Navmesh(missions.MAP_A)
    mv = M.Moves(tm, pad)
    w = weapons.of(tm.right_weapon())
    log(f"무기 {w.name}  소울 {tm.souls()}  나이프 {tm.goods_count(M.ITEM_KNIFE)}")
    esc = Escape(pad, [nm], log=log, events=log.event).start()
    fld = Field(mv, w, esc, bonfires=[missions.FIRELINK], log=log, events=log.event)
    try:
        s = mv.snap(5.0)
        if math.dist((s.player.x, s.player.y, s.player.z), tuple(missions.FIRELINK["stand"])) > 15.0:
            log(f"   불의 제전으로 다크사인 (소울 {tm.souls()})")
            mv.darksign(missions.FIRELINK["stand"])
        if not fld.rest_at(nm, missions.FIRELINK):
            log("휴식 실패 — 중단")
            return
        for ti in targets:
            e = dict(missions.RAMP[ti - 1], label=ti)
            c = fld.find_at(e["npc"], e["pos"], 3.0) or fld.find_at(e["npc"], e["pos"], 12.0) or fld.find_at(e["npc"], e["pos"], 30.0)
            if c is None:
                log(f"#{ti}: 없음")
                continue
            lr = fld.lure(c.ptr, e["pos"], nm, f"#{ti}", arena=missions.RAMP_ARENA)
            log(f"#{ti} 끌어오기: {lr}")
            ptr, t0, n, taken0 = c.ptr, time.time(), 0, None
            e_sel = mv.estus_id()
            if e_sel is not None:
                mv.select_item(e_sel)
            while time.time() - t0 < 60.0 and n < a.max:
                if esc.escaping:
                    time.sleep(0.2)
                    continue
                s = mv.snap(40.0)
                c = mv.find(s, ptr)
                if s is None:
                    continue
                if c is None or c.hp <= 0:
                    log(f"#{ti}: 죽음 — 강공 {n}번")
                    break
                if taken0 is None:
                    taken0 = s.player.hp
                if fld.reflex.tick(s):            # 휘두르기 시작하면 정면·방패
                    time.sleep(0.02)
                    continue
                h = M.horiz(s.player, c)
                if h > a.reach + 0.3:
                    # 길(내비메시)로만 붙는다 — 스틱 직진으로 22 m 위 턱의 6번을 향하다 낭떠러지로 떨어져 죽었다 (2026-09-24)
                    path = nm.find_path((s.player.x, s.player.y, s.player.z), (c.x, c.y, c.z))
                    if not path:
                        log(f"#{ti}: 그놈까지 길 없음 — 기다림")
                        mv.pad.guard(True)
                        time.sleep(0.3)
                        continue
                    mv.walk_path(path[1:], nm, "walk", stop=lambda sn: (lambda cc: cc is None or M.horiz(sn.player, cc) <= a.reach)(mv.find(sn, ptr)))
                    mv.pad.move(0.0, 0.0)
                    continue
                mv.pad.move(0.0, 0.0)
                if not mv.face(s, c, deg=15.0):
                    time.sleep(0.05)
                    continue
                if (c.anim or -1) in M.ATTACK:    # 휘두르는 중엔 맞바꾸지 않는다 — 틈에서만
                    mv.pad.guard(True)
                    time.sleep(0.03)
                    continue
                sp0, t1 = s.player.sp, time.time()
                hit = mv.heavy(s, c)
                n += 1
                s2 = mv.snap(10.0)
                sp1 = s2.player.sp if s2 else None
                # 내 애니가 R2 뒤 -1 로 돌아온 시각 = 동작 길이
                back = next((t for t, an in hit.my_anims[1:] if an in (-1, None)), None)
                row = {"target": ti, "n": n, "dist": round(h, 2), "dmg": hit.dmg, "dead": hit.dead, "taken": hit.taken,
                       "sp": [sp0, sp1], "secs": round(time.time() - t1, 2), "anim_len": back,
                       "my_anims": hit.my_anims[:6], "e_anims": hit.e_anims[:6]}
                log(f"   #{ti} 강공 {n}: {h:.2f} m → 피해 {hit.dmg}{' 죽음' if hit.dead else ''}, 내 피해 {hit.taken}, SP {sp0}→{sp1}, "
                    f"동작 {back} s, 내 애니 {hit.my_anims[:4]}, 그놈 애니 {hit.e_anims[:4]}")
                log.event("heavy", **row)
                if hit.dead:
                    break
            fld.heal(0.7)
        log("══ 끝")
    finally:
        esc.stop()
        pad.neutral()


if __name__ == "__main__":
    main()
