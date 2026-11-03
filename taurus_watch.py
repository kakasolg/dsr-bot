"""Read-only recorder while MoKa fights Taurus by hand — no pad input, no game-memory writes.

  python taurus_watch.py [minutes]        (default 10; Ctrl+C stops)

MoKa 11-03: "나는 보스가 몽둥이를 들어 올리는 타이밍에 들어가는데, 봇은 애니로 그것을 판정 해야 하는 거 아니야?"
To find which anim that is and where MoKa stands, it writes data/runs/<stamp>_taurus-watch.jsonl:
  · every ~0.1 s a "tw" row: boss anim / HP / position, our position / anim / HP, horizontal distance h and angle off its facing
  · (boss attacks are read back from the "tw" rows: 11-03 a second AttackLog thread on the same reader wrote nothing)
  · a "boss_hit" event whenever the boss HP drops (our hit): boss anim then, h, angle
Run it alongside an OBS recording (obs_rec.py) so the numbers can be lined up with the clip (clip.py <stamp>_taurus-watch <t>).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import env
from souls import moves as M
from souls import taurus as T

ROOT = Path(__file__).resolve().parent


def main() -> int:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = ROOT / "data" / "runs" / f"{stamp}_taurus-watch.jsonl"
    txt = (ROOT / "data" / "runs" / f"{stamp}_taurus-watch.log").open("a", encoding="utf-8")
    out = path.open("a", encoding="utf-8")
    t0 = time.time()

    def log(msg: str) -> None:
        line = f"[{time.time() - t0:7.1f}] {msg}"
        print(line, flush=True)
        txt.write(line + "\n")
        txt.flush()

    def event(_ev: str, **kw) -> None:
        out.write(json.dumps({"t": round(time.time() - t0, 2), "ev": _ev, **kw}, ensure_ascii=False, default=str) + "\n")
        out.flush()

    tm = env.make_telemetry({})
    log(f"taurus-watch: read only, {minutes:.0f} min → {path.name}")
    boss_hp, end = None, t0 + minutes * 60
    try:
        while time.time() < end:
            s = tm.snapshot(within=40.0)
            b = T.Taurus.boss(s) if s is not None and s.player is not None else None
            if b is None:
                time.sleep(0.1)
                continue
            p = s.player
            h, ang = M.horiz(p, b), round(T.ang_off(b, p))
            event("tw", anim=b.anim, bhp=b.hp, b=[round(b.x, 2), round(b.y, 2), round(b.z, 2)],
                  me=[round(p.x, 2), round(p.y, 2), round(p.z, 2)], me_anim=p.anim, hp=p.hp, h=round(h, 2), ang=ang)
            if boss_hp is not None and b.hp is not None and b.hp < boss_hp:
                log(f"   보스 −{boss_hp - b.hp} (HP {b.hp}): 보스 애니 {b.anim}, {h:.2f} m, 정면에서 {ang:+d}°, 나 {T.my_kind(p.anim)}")
                event("boss_hit", dmg=boss_hp - b.hp, bhp=b.hp, anim=b.anim, h=round(h, 2), ang=ang, me_anim=p.anim)
            boss_hp = b.hp
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    log("taurus-watch: end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
