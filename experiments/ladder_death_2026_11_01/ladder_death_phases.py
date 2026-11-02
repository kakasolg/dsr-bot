"""Read-only characterisation: which inputs does the CURRENT ladder routine send after the fake player dies in each phase?
Not a pass/fail test — it prints what happens. Real Field._settle is used; time is faked."""
import math, os, sys
from types import SimpleNamespace as NS
sys.path.insert(0, r"D:\dev\dsr-bot"); os.environ.setdefault("BOT_GAME", "dsr")
import time as _t
from souls import missions as MS, field as F
FOOT = (49.16, 15.97, -117.1); FACE = (50.5, 15.97, -117.1); TOP = 24.8
def run(phase):
    clock = {"t": 1000.0}; st = {"hp": 377, "x": FOOT[0], "y": FOOT[1], "anim": -1, "head": -math.pi/2,
                                 "turn_reads": 0, "climb_reads": 0, "settles": 0, "As": 0}
    log = []
    def die(why):
        if st["hp"] > 0:
            st["hp"], st["anim"] = 0, 6053; log.append(("DIED", why))
    def snap(r=5.0):
        return NS(player=NS(x=st["x"], y=st["y"], z=FOOT[2], anim=st["anim"], heading=st["head"], hp=st["hp"]), cam_yaw=0.0)
    def move(x, y):
        log.append(("move", round(x, 2), round(y, 2)))
        if (x or y) and abs(st["head"] + math.pi/2) > 0.1 and st["hp"] > 0 is not None:
            pass
        if phase == "turn" and (x or y) and abs(y) < 0.9:
            st["turn_reads"] += 1
            if st["turn_reads"] == 3: die("turn")
        if y > 0.9 and 7000 <= st["anim"] < 7100 and st["hp"] > 0:
            st["climb_reads"] += 1; st["y"] += 0.5
            if phase == "climb" and st["climb_reads"] == 2: die("climb")
    def interact():
        st["As"] += 1; log.append(("A",))
        if st["hp"] > 0 and not (phase == "retry" and st["As"] == 1):
            st["anim"] = 7010
    def settle_wrap(spot, tol=None, tries=10):
        st["settles"] += 1
        if phase == "entry" and st["settles"] == 1: die("entry settle"); st["x"] = FOOT[0] - 1.0
        if phase == "retry" and st["settles"] == 2: die("retry settle"); st["x"] = FOOT[0] - 1.0
        return F.Field._settle(fake_f, spot, tol=tol, tries=tries)
    mv = NS(snap=snap, stick_to=lambda s, x, z, sc=1.0: (sc, 0.0),
            pad=NS(move=move, interact=interact, neutral=lambda: log.append(("neutral",)), release_due=lambda: None))
    fake_f = NS(mv=mv)
    if phase == "turn": st["head"] = -math.pi/2 + math.radians(179)
    f = NS(walk_to=lambda *a, **k: "arrived", walk=lambda *a, **k: "arrived", alive=lambda: st["hp"] > 0, _settle=settle_wrap)
    m = MS.Missions.__new__(MS.Missions); m.log = lambda *a: None; m.f, m.mv = f, mv
    real = (_t.time, _t.sleep)
    _t.time, _t.sleep = (lambda: clock["t"]), (lambda s: clock.__setitem__("t", clock["t"] + s))
    try:
        r = m._before({"ladder": {"bottom": list(FOOT), "face": list(FACE), "top_y": TOP}}, None, "t")
    finally:
        _t.time, _t.sleep = real
    i = next(k for k, e in enumerate(log) if e[0] == "DIED") if any(e[0] == "DIED" for e in log) else len(log)
    after = log[i + 1:]
    moves = [e for e in after if e[0] == "move" and (e[1] or e[2])]
    print(f"{phase:6} result={r!r:7} died at {log[i] if i < len(log) else None}; after death: A x{sum(e[0]=='A' for e in after)}, "
          f"stick moves x{len(moves)} {sorted(set(moves))[:3]}, neutral x{sum(e[0]=='neutral' for e in after)}, "
          f"fake time after death ~{clock['t']-1000:.1f}s total")
for ph in ("entry", "turn", "climb", "retry"):
    run(ph)
