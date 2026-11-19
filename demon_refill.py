"""Demon-only invincibility for MoKa's practice (M1118-02): refill the Asylum Demon's HP; the player is untouched."""
import os, sys, time
sys.path.insert(0, r"D:\dev\dsr-bot")
os.chdir(r"D:\dev\dsr-bot")
import env
from dsr_telemetry import OFF_HP
DEMON, BELOW, STOP = 223200, 0.5, "data/demon_refill.stop"
if os.path.exists(STOP):
    os.remove(STOP)
tm = env.make_telemetry({})
t0, n, seen = time.time(), 0, False
while time.time() - t0 < 3 * 3600 and not os.path.exists(STOP):
    s = tm.snapshot()
    c = None if s is None else next((x for x in s.chars if x.npc_param == DEMON), None)
    if c is not None:
        if not seen:
            print(f"{time.strftime('%H:%M:%S')} demon seen hp {c.hp}/{c.max_hp}", flush=True); seen = True
        if c.max_hp and 0 < c.hp < BELOW * c.max_hp:
            tm.pm.write_int(c.ptr + OFF_HP, c.max_hp); n += 1
            print(f"{time.strftime('%H:%M:%S')} refill {c.hp} -> {c.max_hp} (#{n})", flush=True)
    time.sleep(0.05)
print("end", n, "refills", flush=True)
