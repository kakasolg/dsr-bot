"""때릴 때마다 적 HP 가 얼마나 깎이는지 기록한다 — 무기 비교를 체감이 아니라 숫자로.

  python dmglog.py [초]

사용자가 직접 조작하는 동안 옆에서 보기만 한다. 적 HP 가 줄면 그 순간의 거리·적 종류와 함께 적는다.
(실측 기록: 해골에게 할버드 2방 / 강화 클럽 3방 — 이 도구로 피해량까지 확정한다)
"""
import sys, time, json, math
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
import env

def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 600
    tm = env.make_telemetry({})
    hp, rows = {}, []
    t0 = time.time()
    print(f"기록 시작 ({secs:.0f}초). 때리세요.", flush=True)
    while time.time() - t0 < secs:
        s = tm.snapshot(within=25.0)
        if s and s.player.hp > 0:
            for c in s.chars:
                if c.max_hp <= 0 or c.dist > 25:
                    continue
                prev = hp.get(c.ptr)
                if prev is not None and 0 < prev - c.hp < prev:
                    d = prev - c.hp
                    model = tm.model(c.ptr) if hasattr(tm, "model") else "?"
                    rows.append({"t": round(time.time()-t0,1), "dmg": d, "dist": round(c.dist,2),
                                 "npc": c.npc_param, "model": model, "hp": f"{c.hp}/{c.max_hp}"})
                    print(f"  {d:4} 피해  {c.dist:4.2f}m  {model} npc{c.npc_param}  남은 {c.hp}/{c.max_hp}", flush=True)
                hp[c.ptr] = c.hp
        time.sleep(0.05)
    if rows:
        Path("data").mkdir(exist_ok=True)
        Path("data/dmglog.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        ds = sorted(r["dmg"] for r in rows)
        print(f"\n타격 {len(rows)}회  피해 {ds[0]}~{ds[-1]} 중앙 {ds[len(ds)//2]}  → data/dmglog.json")

if __name__ == "__main__":
    main()
