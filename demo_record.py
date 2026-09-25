"""사용자 시범 기록 — 입력 없이 메모리만 읽어 (1) 나이프 던진 자리 (2) 백스텝→공격 조합을 남긴다.
사용자 2026-09-24: "지금부터 내가 나이프 던지는 위치를 기억하고, 내가 백스텝 후 공격도 저장해줘."

  python demo_record.py

출력: data/demo/<시각>.jsonl + 화면 한 줄씩 (Ctrl+C 로 끝)
  knife:  내 위치·heading, 그때 가장 가까운 적(npc·위치·거리·높이차), 1.8 s 안 그 적 HP 감소(맞음)·이동(깸)
  combo:  백스텝(690)/구르기 뒤 1.5 s 안에 공격 애니 → 간격 s, 그때 적 거리·적 애니(휘두르는 중?), 적 HP 감소, 내 HP 감소
  anims:  내 애니 흐름은 모두 남긴다 (나중에 어떤 번호가 뭔지 맞추기 위해)
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import env
from souls import moves as M

ITEM_KNIFE = 290
BACKSTEP = 690
ATTACK_MY = range(300000, 310000)      # 내 공격 애니 (303xxx 한손·304xxx 양손 실측)
OUT = Path(__file__).resolve().parent / "data" / "demo"


def nearest(s, r: float = 40.0):
    hs = [c for c in s.hostile(r) if c.hp > 0]
    return min(hs, key=lambda c: c.dist, default=None)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    f = path.open("a", encoding="utf-8")
    tm = env.make_telemetry({})
    print(f"기록: {path}  (입력 없음, Ctrl+C 로 끝)", flush=True)

    def emit(row: dict) -> None:
        row["t"] = round(time.time(), 2)
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()

    knives = tm.goods_count(ITEM_KNIFE) or 0
    last_knife_check = 0.0
    my_anim, anim_t = None, 0.0
    step = None                 # 진행 중인 백스텝/구르기: {"t", "anim", "e": 적 스냅, "hp0"}
    pending = []                # 결과를 기다리는 사건: {"kind", "until", "row", "ptr", "ehp0", "epos0", "hp0"}
    while True:
        s = tm.snapshot(within=40.0)
        now = time.time()
        if s is None:
            time.sleep(0.1)
            continue
        p = s.player
        # 내 애니 흐름
        if p.anim != my_anim:
            emit({"ev": "anim", "anim": p.anim, "prev": my_anim, "held": round(now - anim_t, 2)})
            if p.anim == BACKSTEP or (700 <= (p.anim or -1) < 800):      # 백스텝 / 구르기(추정 7xx) 시작
                e = nearest(s)
                step = {"t": now, "anim": p.anim, "hp0": p.hp,
                        "e": None if e is None else {"ptr": e.ptr, "npc": e.npc_param, "dist": round(e.dist, 2), "eanim": e.anim, "ehp": e.hp}}
            elif (p.anim or -1) in ATTACK_MY and step is not None and now - step["t"] <= 1.5:
                e = nearest(s)
                row = {"ev": "combo", "first": "backstep" if step["anim"] == BACKSTEP else f"roll{step['anim']}", "gap_s": round(now - step["t"], 2),
                       "attack_anim": p.anim, "at_step": step["e"],
                       "at_attack": None if e is None else {"npc": e.npc_param, "dist": round(e.dist, 2), "eanim": e.anim, "swinging": (e.anim or -1) in M.ATTACK}}
                pending.append({"kind": "combo", "until": now + 1.5, "row": row, "ptr": None if e is None else e.ptr,
                                "ehp0": None if e is None else e.hp, "epos0": None, "hp0": p.hp, "min_hp": p.hp, "min_ehp": None if e is None else e.hp})
                step = None
            my_anim, anim_t = p.anim, now
        # 나이프
        if now - last_knife_check > 0.15:
            last_knife_check = now
            n = tm.goods_count(ITEM_KNIFE)
            if n is not None and n < knives:
                e = nearest(s)
                row = {"ev": "knife", "pos": [round(p.x, 2), round(p.y, 2), round(p.z, 2)], "heading": None if p.heading is None else round(p.heading, 3),
                       "locked": tm.lock_target() not in (None, -1),
                       "target": None if e is None else {"npc": e.npc_param, "pos": [round(e.x, 2), round(e.y, 2), round(e.z, 2)],
                                                          "dist": round(e.dist, 2), "dy": round(e.y - p.y, 2), "eanim": e.anim}}
                pending.append({"kind": "knife", "until": now + 1.8, "row": row, "ptr": None if e is None else e.ptr,
                                "ehp0": None if e is None else e.hp, "epos0": None if e is None else (e.x, e.y, e.z),
                                "hp0": p.hp, "min_hp": p.hp, "min_ehp": None if e is None else e.hp, "moved": False})
                print(f"나이프 @ ({p.x:.1f},{p.y:.1f},{p.z:.1f}) → {None if e is None else f'{e.npc_param} {e.dist:.1f} m 높이 {e.y - p.y:+.1f}'}", flush=True)
            if n is not None:
                knives = n
        # 결과 대기
        for pe in list(pending):
            if pe["ptr"] is not None:
                c = M.Moves.find(s, pe["ptr"])
                if c is not None:
                    pe["min_ehp"] = min(pe["min_ehp"], c.hp) if pe["min_ehp"] is not None else c.hp
                    if pe["epos0"] is not None and math.dist((c.x, c.y, c.z), pe["epos0"]) > 0.8:
                        pe["moved"] = True
                elif pe["min_ehp"] is not None:
                    pe["min_ehp"] = 0
            pe["min_hp"] = min(pe["min_hp"], p.hp)
            if now >= pe["until"]:
                pending.remove(pe)
                row = pe["row"]
                row["hit"] = None if pe["ehp0"] is None else pe["ehp0"] - pe["min_ehp"]
                row["taken"] = pe["hp0"] - pe["min_hp"]
                if pe["kind"] == "knife":
                    row["woke"] = pe.get("moved", False)
                    print(f"   → 피해 {row['hit']}, {'움직임' if row['woke'] else '반응 없음'}", flush=True)
                else:
                    print(f"조합 {row['first']} → 공격 {row['attack_anim']} ({row['gap_s']} s 뒤), 적 {row['at_attack']}, 피해 {row['hit']}, 내 피해 {row['taken']}", flush=True)
                emit(row)
        time.sleep(0.03)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("끝", flush=True)
