"""Bonfire warp from the radar page — radar_server.py's POST /warp. The one radar feature that writes game memory.

Uses dsr_telemetry.bonfire_warp (the game's own bonfire-menu warp: loading screen, souls kept). Refused unless all hold:
  · not a replay / demo            · no other warp running
  · the bonfire is in the lit list (bonfires.load — the same rule bonfire_warp itself applies)
  · Steam is confirmed offline (steam_state.check() is True — unknown counts as no; CLAUDE.md: memory writes offline only)
  · no bot is running (botlock.BotLock — held for the whole warp, so a bot can't start in the middle either)
  · the game is running, the player is in the world, alive, and the in-game menu is closed
Every refusal says why. The page asks for confirmation first; the server only accepts POST from its own origin
(radar_server.py checks Host / Origin and a custom header a foreign web page can't send without a CORS preflight).
"""
from __future__ import annotations

import threading
import time

import bonfires
import steam_state

LOCK_TRIES, LOCK_GAP = 10, 0.2    # watchdog.py grabs the lock for an instant now and then (same retry as run.py)


def connect_game():
    """Direct telemetry (not the feed — only a few reads, then the warp). None if the game isn't running."""
    try:
        import dsr_telemetry
        return dsr_telemetry.DSRTelemetry({})
    except Exception:
        return None


def _lock():
    from botlock import BotLock
    return BotLock()


class Warper:
    def __init__(self, say, enabled: bool = True, steam_check=steam_state.check, connect=connect_game, lock=_lock,
                 lit=bonfires.load, names=bonfires.names, run_async: bool = True):
        self.say = say                           # one line to the radar's Decisions list (and the recording)
        self.enabled = enabled                   # False for --replay / --demo
        self.steam_check, self.connect, self.lock, self.lit, self.names = steam_check, connect, lock, lit, names
        self.run_async = run_async
        self.busy = False
        self.last = ""
        self._mx = threading.Lock()

    def bonfires(self) -> list[dict]:
        nm = self.names()
        return [{"id": b, "name": nm.get(b, "") or str(b)} for b in sorted(self.lit())]

    def status(self) -> dict:
        return {"busy": self.busy, "last": self.last, "enabled": self.enabled}

    def request(self, bid) -> tuple[bool, str]:
        """→ (started, message). Checks everything, then warps on a thread (the loading screen takes up to ~40 s)."""
        with self._mx:
            if self.busy:
                return False, "a warp is already running"
            self.busy = True
        try:
            ok, msg, lock, tm = self._check(bid)
        except Exception as e:
            ok, msg, lock, tm = False, f"check failed: {type(e).__name__}", None, None
        if not ok:
            self._done(lock)
            self.last = f"refused: {msg}"
            return False, msg
        bid = int(bid)
        name = self.names().get(bid, "") or str(bid)
        self.last = f"warping to {name}"
        self.say(f"warp → {bid} {name}: requested from the radar page")
        if self.run_async:
            threading.Thread(target=self._warp, args=(tm, bid, name, lock), daemon=True, name="radar-warp").start()
        else:
            self._warp(tm, bid, name, lock)
        return True, f"warping to {name}"

    def _check(self, bid):
        """→ (ok, reason, lock held or None, telemetry or None). Cheapest checks first; the lock is taken last-but-one."""
        if not self.enabled:
            return False, "warp is off here (replay / demo)", None, None
        try:
            bid = int(bid)
        except (TypeError, ValueError):
            return False, "bad bonfire id", None, None
        if bid not in self.lit():
            return False, f"{bid} is not a lit bonfire (bonfires.py)", None, None
        st = self.steam_check()
        if st.get("offline") is not True:
            return False, "Steam not confirmed offline — " + ", ".join(st.get("why") or []), None, None
        lock = self.lock()
        for _ in range(LOCK_TRIES):
            if lock.acquire():
                break
            time.sleep(LOCK_GAP)
        else:
            return False, "a bot is running (data/bot.lock held)", None, None
        try:
            tm = self.connect()
            if tm is None:
                return False, "game not found", lock, None
            s = tm.snapshot(within=1.0)
            if s is None or s.player is None:
                return False, "not in the world (title / loading)", lock, None
            if not s.player.hp or s.player.hp <= 0:
                return False, "the player is dead", lock, None
            if tm.menu_open():
                return False, "close the in-game menu first", lock, None
        except Exception as e:
            return False, f"game read failed: {type(e).__name__}", lock, None
        return True, "", lock, tm

    def _warp(self, tm, bid: int, name: str, lock) -> None:
        try:
            ok = tm.bonfire_warp(bid, log=lambda m: self.say("warp: " + str(m).strip()))
            self.last = f"arrived at {name}" if ok else f"warp to {name} failed (see Decisions)"
            self.say(f"warp → {bid} {name}: {'arrived' if ok else 'FAILED'}")
        except Exception as e:
            self.last = f"warp to {name} failed: {type(e).__name__}"
            self.say(f"warp → {bid} {name}: error {type(e).__name__}: {e}")
        finally:
            try:
                tm.pm.close_process()
            except Exception:
                pass
            self._done(lock)

    def _done(self, lock) -> None:
        if lock is not None:
            try:
                lock.release()
            except Exception:
                pass
        self.busy = False
