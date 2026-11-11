"""Offline check of humanity_probe.py — fake telemetry and world, the real control.Pad on tests/pad_fakes, fake clock. No game.

  python experiments/item_pickup_2026_11_01/humanity_probe_test.py

Checked: import alone loads no game / pad module · already picked · flag unreadable (None, exception) · normal pickup (one A,
none after the flag, no close A by default) · separate ui record (close approved / sent / confirmed; confirmed stays None) ·
--close-a keeps result "got" · count mismatch and unread count kept as such · one pickup A only (PICK_TRIES 1) · A that opens
something without the flag → no second A · stuck walk · bot lock / pad lock held → no device, no input · exception and Ctrl+C
mid-walk → device left neutral, pad closed, lock released, end record written · Probe built directly with no clock (the 11-01
close-attempt TypeError) and with an injected clock.
Not checked: anything about the real game (pickup distance, the window, the flag and count reads themselves).
"""
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace as NS

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FAILED: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        FAILED.append(name)


# ── import alone: no game / pad module (fresh interpreter) ─────────────────
r = subprocess.run([sys.executable, "-c",
                    "import sys; sys.path.insert(0, sys.argv[1]); import humanity_probe; "
                    "print(sorted(m for m in ('dsr_telemetry', 'env', 'navmesh', 'control', 'vgamepad', 'pymem', 'botlock') if m in sys.modules))",
                    str(HERE)], capture_output=True, text=True, timeout=60)
check("import alone: no dsr_telemetry / env / navmesh / control / vgamepad / pymem / botlock", r.stdout.strip() == "[]")

sys.path[:0] = [str(HERE), str(ROOT), str(ROOT / "tests")]
os.environ.setdefault("BOT_GAME", "dsr")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import control  # noqa: E402
import pad_fakes  # noqa: E402
import humanity_probe as HP  # noqa: E402

A = "XUSB_GAMEPAD_A"


class Lock:
    def __init__(self, ok=True):
        self.ok, self.held, self.released = ok, False, False

    def acquire(self):
        self.held = self.ok
        return self.ok

    def release(self):
        self.released = True


def scene(flag0=False, flag_err=False, pickable=True, goods_add=3, goods_none=False, menu_after_A=None, frozen=False,
          raise_at=None, lock_ok=True, pad_held=False, close_a=False):
    """One execute() on a fake world. The player walks by the device's left stick (0.3 m per read per unit); an A reported while
    within HP.STOP_M of the corpse turns the flag on (pickable) and adds goods_add. raise_at = (n, exc): the n-th stick call raises
    (a snapshot failure is a recorded unread, not an exception). → (result, records, rec, world, lock)"""
    clock = {"t": 1000.0}
    real = (time.time, time.sleep)
    time.time, time.sleep = (lambda: clock["t"]), (lambda s: clock.__setitem__("t", clock["t"] + s))
    vg = pad_fakes.install(Path(tempfile.mkdtemp(prefix="humprobe_")))
    n_dev = len(vg.devices)
    w = {"x": HP.BONFIRE[0], "y": HP.BONFIRE[1], "z": HP.BONFIRE[2], "flag": flag0, "goods": 0, "menu": False,
         "reads": 0, "seen": 0, "made_tm": False}
    recs: list[dict] = []
    lock = Lock(lock_ok)

    def world_step():
        dev = vg.devices[-1] if len(vg.devices) > n_dev else None
        if dev is None:
            return
        rep = dev.sent
        for x in rep[w["seen"]:]:
            if A in x["buttons"]:
                d = math.hypot(w["x"] - HP.CORPSE[0], w["z"] - HP.CORPSE[2])
                if pickable and d <= HP.STOP_M and not w["flag"]:
                    w["flag"] = True
                    w["goods"] += goods_add
                if menu_after_A is not None:
                    w["menu"] = menu_after_A
        w["seen"] = len(rep)
        st = rep[-1] if rep else None
        if st and not frozen:
            w["x"] += 0.3 * st["lx"]
            w["z"] += 0.3 * st["ly"]

    def snap():
        w["reads"] += 1
        world_step()
        return NS(player=NS(x=w["x"], y=w["y"], z=w["z"], heading=0.0, anim=-1, hp=400), cam_yaw=0.0)

    def flag(fid):
        world_step()
        if flag_err:
            raise RuntimeError("read failed")
        return None if flag0 is None else w["flag"]

    tm = NS(event_flag=flag, goods_count=lambda i: None if goods_none else w["goods"], humanity=lambda: 0,
            menu_open=lambda: w["menu"])

    def make_tm():
        w["made_tm"] = True
        return tm

    def stick(s, x, z):
        w["sticks"] = w.get("sticks", 0) + 1
        if raise_at is not None and w["sticks"] == raise_at[0]:
            raise raise_at[1]
        dx, dz = x - s.player.x, z - s.player.z
        L = math.hypot(dx, dz) or 1.0
        return dx / L, dz / L

    try:
        res = HP.execute(recs.append, recs, lambda: lock, lambda: pad_held, make_tm, control.Pad, control.PadBusy,
                         lambda t, p: (snap, stick, lambda a, b: [(-43.0, -59.0, 53.4)]), close_a=close_a)
    finally:
        time.time, time.sleep = real
    rec = vg.devices[-1] if len(vg.devices) > n_dev else None
    return res, recs, rec, w, lock


def a_count(rec):
    """Distinct A presses the device saw (A going down)."""
    n, prev = 0, False
    for x in rec.sent:
        on = A in x["buttons"]
        n += on and not prev
        prev = on
    return n


def inputs(recs, what):
    return [r for r in recs if r.get("k") == "input" and r.get("what") == what]


def end(recs):
    return [r for r in recs if r.get("k") == "end"]


def stick_or_a(rec):
    return [x for x in rec.sent if A in x["buttons"] or abs(x["lx"]) > 1e-9 or abs(x["ly"]) > 1e-9]


# ── already picked ──────────────────────────────────────────────────────────
res, recs, rec, w, lock = scene(flag0=True)
check("flag True at the start → 'already', no A and no stick", res == "already" and not stick_or_a(rec))
check("already: lock released, end record", lock.released and end(recs) and end(recs)[-1]["result"] == "already")

# ── flag unreadable ─────────────────────────────────────────────────────────
res, recs, rec, w, lock = scene(flag0=None)
st = recs[0] if recs else {}
check("flag None → 'unknown_flag', no input, kept as unread (not False)",
      res == "unknown_flag" and not stick_or_a(rec) and st.get("flag") == {"v": None, "unread": True})
res, recs, rec, w, lock = scene(flag_err=True)
check("flag read raises → 'unknown_flag', error text kept", res == "unknown_flag" and "err" in recs[0]["flag"] and not stick_or_a(rec))

# ── normal pickup ───────────────────────────────────────────────────────────
res, recs, rec, w, lock = scene()
j = end(recs)[-1]["judge"]
check("normal: walks, one A, flag on → 'got'", res == "got" and a_count(rec) == 1 and w["flag"])
check("normal: no A after the flag read True, no close A by default",
      len(inputs(recs, "A")) == 1 and not [r for r in inputs(recs, "A") if r["step"] == "close"])
check("normal: judge — flag False → True with a time, goods 0 → 3 'match'",
      j["flag_before"] == {"v": False} and j["flag_after"] == {"v": True} and j["flag_on_at"] is not None
      and j["goods"]["delta"] == 3 and j["goods"]["vs_lot"] == "match")
check("normal: asks for a look at the window (no guess)", any(r.get("k") == "ask" for r in recs))
check("normal: every input has a time", all("t" in r for r in recs if r.get("k") == "input" and r["what"] != "cleanup"))
check("normal: device left with nothing held, pad closed", rec.is_neutral() and rec.removed)
ui = [r for r in recs if r.get("k") == "ui"]
check("normal: separate ui record — close not approved / not sent / not confirmed, window unknown",
      len(ui) == 1 and ui[0]["close_approved"] is False and ui[0]["close_sent_t"] is None
      and ui[0]["close_confirmed"] is None and ui[0]["window_shown"] is None)
res, recs, rec, w, lock = scene(close_a=True)
ui = [r for r in recs if r.get("k") == "ui"]
check("--close-a: result is still the pickup 'got'; second A as its own 'close' step, then reads",
      res == "got" and a_count(rec) == 2 and [r["step"] for r in inputs(recs, "A")] == ["pick1", "close"]
      and any(r.get("step") == "after_close" for r in recs))
check("--close-a: ui record — approved, sent with a time, confirmed still None (no memory value shows the window)",
      len(ui) == 1 and ui[0]["close_approved"] is True and ui[0]["close_sent_t"] is not None and ui[0]["close_confirmed"] is None)

# ── count does not match / unread ─────────────────────────────────────────────
res, recs, rec, w, lock = scene(goods_add=0)
j = end(recs)[-1]["judge"]
check("flag on, goods unchanged → 'got' with goods 'mismatch' (flag and count apart)", res == "got" and j["goods"]["vs_lot"] == "mismatch")
res, recs, rec, w, lock = scene(goods_none=True)
j = end(recs)[-1]["judge"]
check("goods unreadable → kept unread, no delta / verdict (not 0)",
      j["goods"]["before"] == {"v": None, "unread": True} and j["goods"]["delta"] is None and j["goods"]["vs_lot"] is None)

# ── retry cap / unclear window ──────────────────────────────────────────────
check("PICK_TRIES is 1 (no retry A while the window can't be seen)", HP.PICK_TRIES == 1)
res, recs, rec, w, lock = scene(pickable=False)
check("A never takes, menu_open False → 'not_got' after one A, no second A, asks for a look",
      res == "not_got" and a_count(rec) == 1 and any(r.get("k") == "ask" for r in recs))
res, recs, rec, w, lock = scene(pickable=False, menu_after_A=True)
check("A opens something, flag unchanged → 'window_unclear', no second A", res == "window_unclear" and a_count(rec) == 1)

# ── walk bounds ─────────────────────────────────────────────────────────────
res, recs, rec, w, lock = scene(frozen=True)
check("player doesn't move → 'stuck', no A", res == "stuck" and a_count(rec) == 0 and rec.is_neutral())

# ── locks ───────────────────────────────────────────────────────────────────
res, recs, rec, w, lock = scene(lock_ok=False)
check("bot lock held → 'bot_lock_held', no telemetry, no pad device", res == "bot_lock_held" and rec is None and not w["made_tm"])
res, recs, rec, w, lock = scene(pad_held=True)
check("pad lock held → 'pad_lock_held', no pad device, bot lock released", res == "pad_lock_held" and rec is None and lock.released)

# ── exception / Ctrl+C mid-walk ─────────────────────────────────────────────
res, recs, rec, w, lock = scene(raise_at=(6, RuntimeError("boom")))
check("exception mid-walk → 'exception:RuntimeError', stick was held before it", res == "exception:RuntimeError" and stick_or_a(rec))
check("exception: device neutral, pad closed, lock released, end record",
      rec.is_neutral() and rec.removed and lock.released and end(recs)[-1]["result"] == res)
res, recs, rec, w, lock = scene(raise_at=(6, KeyboardInterrupt()))
check("Ctrl+C mid-walk → 'user_stop', device neutral, pad closed, lock released",
      res == "user_stop" and rec.is_neutral() and rec.removed and lock.released and end(recs)[-1]["result"] == "user_stop")

# ── Probe built directly (as the 11-01 close attempt did) ──────────────────
tm0 = NS(event_flag=lambda f: True, goods_count=lambda i: 4, humanity=lambda: 0, menu_open=lambda: False)
snap0 = lambda: NS(player=NS(x=HP.CORPSE[0], y=HP.CORPSE[1], z=HP.CORPSE[2], heading=0.0, anim=-1, hp=400))
out: list[dict] = []
try:
    p = HP.Probe(tm0, snap0, None, None, None, out.append)
    st = p.state("x")
    check("direct Probe(), no clock given → builds (t0 from time.time), state t small and ≥ 0",
          isinstance(p.t0, float) and 0 <= st["t"] < 5)
except Exception as e:  # noqa: BLE001
    check(f"direct Probe(), no clock given → builds ({type(e).__name__}: {e})", False)
clk = {"t": 500.0}
real_sleep = time.sleep
time.sleep = lambda s: (_ for _ in ()).throw(AssertionError("real sleep used"))
try:
    p = HP.Probe(tm0, snap0, None, None, None, out.append, now=lambda: clk["t"],
                 sleep=lambda s: clk.__setitem__("t", clk["t"] + s))
    p.sleep(3.5)
    st = p.state("y")
    check("direct Probe(now=, sleep=) → injected clock used (t0 500, t 3.5), real sleep untouched",
          p.t0 == 500.0 and st["t"] == 3.5)
finally:
    time.sleep = real_sleep

if __name__ == "__main__":
    if FAILED:
        print(f"{len(FAILED)} failed")
        sys.exit(1)
    print("all ok")
