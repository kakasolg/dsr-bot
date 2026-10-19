"""Animation play-time field hunt (docs/rea.md round 3) — read-only, the bot never imports this.

  python experiments/anim_time_scan.py check            step 1-a: is DS1 Overhaul's struct path valid in our game build?
  python experiments/anim_time_scan.py record [secs]    step 1-b: log the anim controls of the player at ~60 Hz (jsonl)
  python experiments/anim_time_scan.py drill [--restart] record while the pad acts (--restart: chained backsteps / light attacks)
  python experiments/anim_time_scan.py foe [secs=90]     hollow A's 3000 (PlayerNoDead on, walk to 3.5 m, whiff to wake, record)

Path (Overhaul OverhaulDLL/include/PlayerInsStruct.h, offsets only):
  ChrIns +0x68 → ChrCtrl:  +0x10 ChrIns (back pointer)  +0x18 ChrCtrl_AnimationQueue  +0x20 AnimationMediator
                           +0x28 havokChara (= our pos data)  +0x48 ActionCtrl (= our anim object, +0x80 anim ID)
  ChrCtrl_AnimationQueue:  +0x0 array_length (u32)  +0x8 arry → entries of 0x78 bytes, entry +0x8 → anim control (0xC0 bytes)
Vtables come from the dump's MSVC RTTI (docs/rea.md "원장"), stored module-relative.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dsr_telemetry  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

VT = {  # RVA from RTTI in the 10-16 dump
    0x132C258: "PlayerCtrl", 0x132BEA8: "EnemyCtrl", 0x132AAB0: "ChrCtrl", 0x132D318: "ActionCtrl",
    0x13460D0: "FrpgDefaultAnimationControl", 0x1412728: "hkaDefaultAnimationControl", 0x1412698: "hkaAnimationControl",
    0x13251F0: "PlayerIns", 0x1322E68: "EnemyIns",
}
ENTRY = 0x78
CTRL = 0xC0


def vt_name(tm, p) -> str:
    v = tm.q(p) if p else None
    if v is None:
        return "unreadable"
    return VT.get(v - tm.base, hex(v - tm.base))


def controls(tm, ctrl) -> list[tuple[int, int]]:
    """(entry address, anim control address) for each entry of the anim queue."""
    q = tm.q(ctrl + 0x18)
    n = tm.i32(q) if q else None
    arr = tm.q(q + 0x8) if q else None
    if not (q and arr and n and 0 < n <= 32):
        return []
    out = []
    for i in range(n):
        e = arr + i * ENTRY
        out.append((e, tm.q(e + 0x8) or 0))
    return out


def check(tm) -> None:
    ptrs = [tm.player_ptr()] + [p for p in tm.chr_ptrs() if p != tm.player_ptr()][:3]
    for p in ptrs:
        if not p:
            continue
        c = tm.read_chr(p)
        ctrl = tm.q(p + 0x68)
        mapd_pos, mapd_anim = tm.q(ctrl + 0x28), tm.q(ctrl + 0x48)
        print(f"== {vt_name(tm, p)} {tm.model(p)} hp={getattr(c, 'hp', None)} anim={getattr(c, 'anim', None)}")
        print(f"   ChrCtrl {hex(ctrl)} vt={vt_name(tm, ctrl)}  +0x10==ChrIns: {tm.q(ctrl + 0x10) == p}  "
              f"+0x48 vt={vt_name(tm, mapd_anim)}  +0x80 anim={tm.i32(mapd_anim + 0x80)}  +0x28 pos x={tm.f32(mapd_pos + 0x10)}")
        q = tm.q(ctrl + 0x18)
        print(f"   AnimationQueue {hex(q or 0)} len={tm.i32(q) if q else None}  mediator {hex(tm.q(ctrl + 0x20) or 0)}")
        for i, (e, a) in enumerate(controls(tm, ctrl)):
            print(f"   [{i}] entry {hex(e)} ctrl {hex(a)} vt={vt_name(tm, a)}  "
                  f"+0x10={tm.f32(a + 0x10) if a else None}  +0x14={tm.f32(a + 0x14) if a else None}  info={hex(tm.q(e + 0x20) or 0)}")


def record(tm, secs: float) -> None:
    p = tm.player_ptr()
    ctrl = tm.q(p + 0x68)
    out = Path(__file__).resolve().parent.parent / "data" / "samples" / time.strftime("%Y%m%d_%H%M%S_anim-time-scan.jsonl")
    t0 = time.perf_counter()
    n = 0
    with out.open("w", encoding="utf-8") as f:
        while time.perf_counter() - t0 < secs:
            row = {"t": round(time.perf_counter() - t0, 4), "anim": tm.i32(tm.q(ctrl + 0x48) + 0x80), "ctrls": []}
            for e, a in controls(tm, ctrl):
                raw = tm.pm.read_bytes(a, CTRL) if a else b""
                fl = [round(x, 4) for x in __import__("struct").unpack(f"<{len(raw) // 4}f", raw)] if raw else []
                row["ctrls"].append({"a": a, "vt": vt_name(tm, a), "info": tm.q(e + 0x20) or 0, "f": fl})
            f.write(json.dumps(row) + "\n")
            n += 1
            time.sleep(1 / 60)
    print(f"{n} rows → {out}")


def drill(tm, restart: bool = False) -> None:
    """record() in a thread while the pad does: stand · backstep · stand · light attack · stand · backstep ×2 (same-ID restart)
    · stand. Stops the inputs when a hostile comes within 8 m."""
    import threading
    import control
    pad = control.Pad()
    th = threading.Thread(target=record, args=(tm, 16.0), daemon=True)
    th.start()
    marks = []

    def near() -> bool:
        s = tm.snapshot(10)
        return bool(s and s.hostile(8))

    def do(name, fn, wait):
        if near():
            marks.append((name, "skipped: hostile < 8 m"))
            return
        marks.append((name, round(time.perf_counter(), 3)))
        fn()
        time.sleep(wait)

    t0 = time.perf_counter()    # ≈ record()'s t0 (the pad is connected before the recorder starts)
    time.sleep(2)
    if restart:     # same-ID restart: backstep, then backstep presses every 0.15 s from 0.4 s to 1.6 s (buffered → fires at the cancel)
        do("backstep", pad.dodge, 0.4)
        for k in range(9):
            do(f"backstep+{k}", pad.dodge, 0.075)
        time.sleep(3.0)
        do("light", pad.attack, 0.5)
        for k in range(8):
            do(f"light+{k}", pad.attack, 0.15)
        time.sleep(3.0)
    else:
        do("backstep", pad.dodge, 2.5)
        do("light", pad.attack, 2.5)
        do("backstep", pad.dodge, 0.45)
        do("backstep2", pad.dodge, 3.0)
    pad.release_all()
    th.join()
    print("marks (s from start):", [(n, round(v - t0, 2) if isinstance(v, float) else v) for n, v in marks])


def _heading_to(px, pz, tx, tz) -> float:
    """+0x4 heading that faces (tx, tz): world yaw = heading + π, direction (sin yaw, cos yaw) in x-z (dsr_telemetry.face)."""
    import math
    return math.atan2(tx - px, tz - pz) - math.pi


def foe(tm, secs: float, refill: tuple[int, int] = (500, 793), npc: int = 254010) -> None:
    """Hollow A's 3000: PlayerNoDead on (game-memory write, offline only; restored at the end), walk to 3.5 m of A
    (NavMesh path + Moves.walk_path), whiff light attacks facing away from A until A wakes (B-11), then record A's anim controls at ~60 Hz for `secs`.
    First half: stand. Second half: backstep 0.3 s into each 3000 (out of reach → B-11 saw A repeat 3000 with one ID)."""
    import math
    import control
    import env

    feed = env.make_telemetry({})
    pad = control.Pad()
    nodead = tm.get_dbg(tm.DBG_PLAYER_NO_DEAD)
    tm.set_dbg(tm.DBG_PLAYER_NO_DEAD, True)
    out = Path(__file__).resolve().parent.parent / "data" / "samples" / time.strftime("%Y%m%d_%H%M%S_anim-time-foe.jsonl")
    try:
        s = tm.snapshot(40)
        a = next((c for c in s.hostile(40) if c.npc_param == npc), None)
        if not a:
            print(f"no {npc} within 40 m")
            return
        aptr = a.ptr
        d = math.hypot(s.player.x - a.x, s.player.z - a.z) or 1.0
        goal = (a.x + 3.5 * (s.player.x - a.x) / d, a.y, a.z + 3.5 * (s.player.z - a.z) / d)
        import navmesh
        from souls import moves as M
        nm = navmesh.Navmesh("m10_01_00_00")
        path = nm.find_path((s.player.x, s.player.y, s.player.z), goal)
        mv = M.Moves(feed, pad)
        r = mv.walk_path(path, nm, stop=lambda sn: (lambda cc: cc is not None and M.horiz(sn.player, cc) <= 3.5)(mv.find(sn, aptr)))
        pad.move(0.0, 0.0)
        s = tm.snapshot(40)
        a = tm.read_chr(aptr)
        print(f"goto {r}: player ({s.player.x:.2f}, {s.player.y:.2f}, {s.player.z:.2f}), A {math.hypot(s.player.x - a.x, s.player.z - a.z):.2f} m")
        x0, z0 = a.x, a.z
        for k in range(6):
            s = tm.snapshot(40)
            a = tm.read_chr(aptr)
            if a.anim not in (-1, None) or math.hypot(a.x - x0, a.z - z0) > 0.5:
                print(f"A awake after {k} whiffs (anim {a.anim}, moved {math.hypot(a.x - x0, a.z - z0):.2f} m)")
                break
            # 10-19: facing A, the first whiff killed it (75 → 0, as B-8) — swing facing away from A
            tm.face(pad, _heading_to(s.player.x, s.player.z, a.x, a.z) + math.pi)
            pad.attack()
            time.sleep(1.6)
        else:
            print("A did not wake after 6 whiffs")
        ctrl = tm.q(aptr + 0x68)
        t0 = time.perf_counter()
        n, last_bs = 0, -9.0
        with out.open("w", encoding="utf-8") as f:
            f.write(json.dumps({"head": {"npc": npc, "secs": secs, "refill": refill, "half": "stand / backstep 0.3 s into 3000"}}) + "\n")
            while (t := time.perf_counter() - t0) < secs:
                s = tm.snapshot(40)
                a = tm.read_chr(aptr)
                row = {"t": round(t, 4), "hp": s.player.hp, "p": [round(s.player.x, 2), round(s.player.y, 2), round(s.player.z, 2)],
                       "a": [round(a.x, 2), round(a.y, 2), round(a.z, 2)] if a else None, "aanim": a.anim if a else None,
                       "ahp": a.hp if a else None, "ctrls": []}
                for i, (e, c) in enumerate(controls(tm, ctrl)):
                    w = tm.f32(c + 0x14) if c else None
                    if w:
                        row["ctrls"].append({"i": i, "c": c, "t": round(tm.f32(c + 0x10), 4), "w": round(w, 3), "info": tm.q(e + 0x20) or 0})
                if refill and s.player.hp < refill[0]:
                    tm.set_hp(refill[1])
                    row["refill"] = refill[1]
                if t > secs / 2 and a and a.anim == 3000 and t - last_bs > 1.5:
                    act = [c for c in row["ctrls"] if c["w"] > 0.5]
                    if act and 0.3 <= act[0]["t"] <= 0.4:
                        pad.dodge()
                        row["backstep"] = True
                        last_bs = t
                f.write(json.dumps(row) + "\n")
                n += 1
                time.sleep(1 / 60)
        print(f"{n} rows → {out}")
    finally:
        pad.release_all()
        tm.set_dbg(tm.DBG_PLAYER_NO_DEAD, bool(nodead))


def main() -> None:
    tm = dsr_telemetry.DSRTelemetry()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        check(tm)
    elif cmd == "record":
        record(tm, float(sys.argv[2]) if len(sys.argv) > 2 else 20.0)
    elif cmd == "drill":
        drill(tm, restart="--restart" in sys.argv)
    elif cmd == "foe":
        foe(tm, float(sys.argv[2]) if len(sys.argv) > 2 else 90.0)


if __name__ == "__main__":
    main()
