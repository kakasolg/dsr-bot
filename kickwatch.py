"""사람이 차는 걸 옆에서 본다 — 패드를 만들지 않는다 (사용자 조작에 끼어들지 않게).

  python kickwatch.py [초]

내 애니가 발차기(333100)로 바뀌는 순간마다: 3 m 안 가장 가까운 적의 애니 전환·HP 를 1.5 s 기록하고,
내 애니·HP 도 같이 남긴다. 봇이 따라 할 "통하는 발차기"의 모양(거리·적 상태·적 반응)을 숫자로 얻는다.
결과: data/kickwatch.json (한 번 찰 때마다 저장)
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import env
import patrol

OUT = Path(__file__).resolve().parent / "data" / "kickwatch.json"


def anim_addr(tm, p):
    mapd = tm.q(p + 0x68)
    st = tm.q(mapd + 0x48) if mapd else None
    return st + 0x80 if st else None


def main() -> None:
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 1800
    tm = env.make_telemetry({})
    rows = []
    t_end = time.time() + secs
    last_me = None
    print(f"관찰 시작 ({secs:.0f}s). 차 보세요.", flush=True)
    while time.time() < t_end:
        pp = tm.player_ptr()
        ma = anim_addr(tm, pp) if pp else None
        a = tm.i32(ma) if ma else None
        if a == patrol.MY_KICK_ANIM and last_me != patrol.MY_KICK_ANIM:
            s = tm.snapshot(within=6.0)
            me = s.player
            foes = sorted((c for c in s.hostile(6.0) if c.hp > 0), key=lambda c: c.dist)
            tgt = foes[0] if foes else None
            ea = anim_addr(tm, tgt.ptr) if tgt else None
            hp0, my_hp0 = (tgt.hp if tgt else None), me.hp
            off = None
            if tgt and me.heading is not None:
                off = round(math.degrees((math.atan2(tgt.x - me.x, tgt.z - me.z) - (me.heading + math.pi) + math.pi)
                                         % (2 * math.pi) - math.pi))
            seq, mine, last_e, t0 = [], [], None, time.perf_counter()
            while time.perf_counter() - t0 < 1.5:
                e = tm.i32(ea) if ea else None
                if e != last_e:
                    seq.append((round((time.perf_counter() - t0) * 1000), e)); last_e = e
                m = tm.i32(ma)
                if m is not None and (not mine or mine[-1][1] != m):
                    mine.append((round((time.perf_counter() - t0) * 1000), m))
                time.sleep(0.005)
            c1 = tm.read_chr(tgt.ptr) if tgt else None
            me1 = tm.snapshot(within=1.0).player
            row = {"t": round(time.time(), 1), "enemy": tgt.npc_param if tgt else None,
                   "model": tm.model(tgt.ptr) if tgt else None, "dist": round(tgt.dist, 2) if tgt else None,
                   "angle": off, "enemy_anim_before": tgt.anim if tgt else None, "enemy_anims": seq,
                   "enemy_dmg": (hp0 - c1.hp) if (tgt and c1) else None, "my_anims": mine,
                   "my_dmg": my_hp0 - me1.hp, "others_within_4m": [(c.npc_param, round(c.dist, 1)) for c in foes[1:] if c.dist < 4]}
            rows.append(row)
            OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  발차기 {len(rows)}: 적 {row['model']} {row['dist']} m ({row['angle']}°) 전 {row['enemy_anim_before']} → {seq[:5]}"
                  f"  적 피해 {row['enemy_dmg']}  내 피해 {row['my_dmg']}  내 애니 {[m for _, m in mine][:4]}", flush=True)
            a = tm.i32(ma)
        last_me = a
        time.sleep(0.005)


if __name__ == "__main__":
    main()
