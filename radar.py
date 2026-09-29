"""Radar sender — pushes what the bot sees and says to radar_server.py over local UDP. Never blocks or breaks the bot.

  from radar import Radar
  r = Radar()               # 127.0.0.1:47800 (RADAR_PORT)
  r.attach(tm)              # follows the feed's frames (at most RATE_HZ per second)
  r.follow(mv)              # + what layer 4 is doing: target (mv.cam_target), path (mv.show_path), held spot (mv.show_spot),
                            #   prop just swung at (mv.show_smash)
  r.say("retreat: 2 foes closing")  # one decision line (run.py's Log does this for every log line)

  python radar.py watch      read-only watch — no bot: the radar follows the game while a person plays by hand
                             (same as `python run.py watch --radar`). Sends no pad input, writes no game memory.

Game state: attach() also starts a thread that sends a small "status" packet every STATUS_S, even when there is no player
(title screen, loading) — so the radar can tell "at the title" from "nobody is sending": game off / title (or loading) /
world / dead, plus whether the in-game menu is open.

Pickups: attach() also starts a thread that, once a second, reads the pickup event flags (tm.event_flag) of the treasures
in data/gamefiles/*.json within ITEM_R of the player and sends the ones already taken, so the radar hides them.

Fire-and-forget: UDP to localhost, nothing waits for an answer, every error is swallowed. With no server
running the packets are simply dropped. Only reads — nothing here touches the game or the pad.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time

PORT = int(os.environ.get("RADAR_PORT", "47800"))
RATE_HZ = 10.0
POLL_WITHIN = 40.0     # radius for the fallback poll (no feed)
MAX_PATH = 200          # path points sent (evenly thinned)
SPOT_FRESH = 2.0       # s — a held spot older than this is no longer shown
SMASH_FRESH = 10.0     # s — a prop swung at stays highlighted this long
ITEM_CHECK_S = 1.0     # s between pickup-flag reads
ITEM_R = 40.0          # m — only treasures this close to the player are checked
GAMEFILES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "gamefiles")
MAX_CHARS = 40          # nearest first; keeps one packet well under the UDP size limit
STATUS_S = 0.5         # s between game-state packets
SEEN_S = 1.0           # s — a player seen this recently counts as "in the world"
RECONNECT_S = 5.0      # watch: s between checks that the game is still there
NOTE_EVERY = 10        # status packets between lit-bonfire notes (≈ 5 s)
REATTACH_S = 30.0      # watch: no player this long while the game runs → attach again (pointers may move after the title)


def _r(v, n=2):
    return None if v is None else round(float(v), n)


def chr_dict(c) -> dict:
    return {"ptr": c.ptr, "name": c.name, "npc": c.npc_param, "team": c.team,
            "hp": c.hp, "max_hp": c.max_hp, "sp": c.sp, "max_sp": c.max_sp,
            "x": _r(c.x), "y": _r(c.y), "z": _r(c.z), "dist": _r(c.dist),
            "heading": _r(c.heading, 3), "anim": c.anim}


def snapshot_dict(s) -> dict:
    return {"t": s.t, "player": chr_dict(s.player), "chars": [chr_dict(c) for c in s.chars[:MAX_CHARS]],
            "cam_yaw": _r(s.cam_yaw, 3), "flask_hp": s.flask_hp, "max_flask_hp": s.max_flask_hp}


def _pts(path) -> list:
    step = max(1, -(-len(path) // MAX_PATH))
    pts = list(path[::step])
    if pts and pts[-1] is not path[-1]:
        pts.append(path[-1])
    return [[_r(q[0]), _r(q[1]), _r(q[2])] for q in pts]


def intent_dict(mv) -> dict:
    """Layer 4's intent as set on Moves — read only. Missing attributes (fakes, old code) just leave fields out."""
    out = {}
    t = getattr(mv, "cam_target", None)
    if t is not None:
        out["target"] = t
    p = getattr(mv, "show_path", None)
    if p:
        out["path_tag"], out["path"] = p[0], _pts(p[1])
    sp = getattr(mv, "show_spot", None)
    if sp and time.time() - sp[2] < SPOT_FRESH:
        out["spot_tag"], out["spot"] = sp[0], [_r(v) for v in sp[1]]
    sm = getattr(mv, "show_smash", None)
    if sm and time.time() - sm[2] < SMASH_FRESH:
        out["smash"] = sm[0]
    return out


def load_treasures(folder: str = GAMEFILES) -> list[tuple]:
    """[(x, y, z, flags)] for every extracted treasure that has pickup flags."""
    import glob
    out = []
    for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                ts = json.load(f).get("treasures") or []
        except (OSError, ValueError):
            continue
        out += [(*t["pos"], tuple(t["flags"])) for t in ts if t.get("flags")]
    return out


def game_alive(tm) -> bool:
    """Is the game process behind tm still running. Telemetry without a process handle (fakes) counts as running."""
    if tm is None:
        return False
    pm = getattr(tm, "pm", None)
    if pm is None:
        return True
    try:
        import ctypes
        code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(pm.process_handle, ctypes.byref(code)):
            return False
        return code.value == 259            # STILL_ACTIVE
    except Exception:
        return True


def status_dict(alive: bool, seen: float, hp, menu, now: float, char: str | None = None) -> dict:
    """Game state for the radar: off / title (title screen or loading — memory can't tell them apart yet) / world / dead.
    away = s since the player was last seen (None if never, since this sender started)."""
    if not alive:
        game = "off"
    elif seen and now - seen < SEEN_S:
        game = "dead" if not hp or hp <= 0 else "world"
    else:
        game = "title"
    return {"type": "status", "t": now, "game": game, "menu": menu if game in ("world", "dead") else None,
            "away": round(now - seen, 1) if seen and game == "title" else None,
            "char": char if game in ("world", "dead") else None}


class Radar:
    def __init__(self, host: str = "127.0.0.1", port: int = PORT):
        self.addr = (host, port)
        self.mv = None
        self.player = None           # (x, y, z) of the last frame sent — where to look for pickups
        self.picked: set[int] = set()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self._last = 0.0
        self.tm = None
        self._seen = 0.0             # when a player was last in a frame
        self._hp = None
        self._attached = 0.0
        self._started = False
        self._n_status = 0

    def _send(self, msg: dict) -> None:
        try:
            self.sock.sendto(json.dumps(msg, ensure_ascii=False, default=str).encode("utf-8"), self.addr)
        except Exception:
            pass

    def snapshot(self, s) -> None:
        now = time.time()
        if s is not None:
            try:
                self._seen, self._hp = now, s.player.hp
            except Exception:
                pass
        if s is None or now - self._last < 1.0 / RATE_HZ:
            return
        self._last = now
        try:
            self.player = (s.player.x, s.player.y, s.player.z)
            msg = {"type": "snap", **snapshot_dict(s)}
            if self.mv is not None:
                msg.update(intent_dict(self.mv))
            self._send(msg)
        except Exception:
            pass

    def say(self, line: str) -> None:
        self._send({"type": "say", "t": time.time(), "line": str(line)[:300]})

    def follow(self, mv) -> "Radar":
        self.mv = mv
        return self

    def check_items(self, tm, treasures: list[tuple]) -> tuple[list[int], list[int]]:
        """Read the pickup flags of treasures near the player — picked ones too, since loading an older save turns a flag
        back off (ROADMAP P-9: a restored item stayed hidden). Send what changed. → (newly on, newly off)."""
        if self.player is None:
            return [], []
        px, py, pz = self.player
        on, off = [], []
        for x, y, z, flags in treasures:
            if abs(x - px) > ITEM_R or abs(z - pz) > ITEM_R:
                continue
            for fl in flags:
                try:
                    v = tm.event_flag(fl)
                except Exception:
                    continue
                if v is None:
                    continue                    # unreadable (loading screen) — keep what we knew
                if v and fl not in self.picked:
                    self.picked.add(fl)
                    on.append(fl)
                elif not v and fl in self.picked:
                    self.picked.discard(fl)
                    off.append(fl)
        if on:
            self._send({"type": "picked", "flags": on})
        if off:
            self._send({"type": "unpicked", "flags": off})
        return on, off

    def status(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        tm = self.tm
        alive = game_alive(tm)
        menu = char = None
        if alive and self._seen and now - self._seen < SEEN_S and hasattr(tm, "menu_open"):
            try:
                menu = tm.menu_open()
                char = tm.char_name() if hasattr(tm, "char_name") else None
            except Exception:
                pass
            self._n_status += 1
            if char and self._n_status % NOTE_EVERY == 0 and hasattr(tm, "last_bonfire"):
                try:                                    # rested at a bonfire while a person plays → it's lit for this character
                    import bonfires
                    bonfires.note_id(char, tm.last_bonfire(), log=lambda m: self.say(m.strip()))
                except Exception:
                    pass
        msg = status_dict(alive, self._seen, self._hp, menu, now, char)
        self._send(msg)
        return msg

    def _threads(self) -> None:
        treasures = load_treasures()

        def items():
            n = 0
            while True:
                tm = self.tm
                if treasures and tm is not None and hasattr(tm, "event_flag"):
                    if n % 30 == 0 and self.picked:     # the server may have restarted — resend what is known now and then
                        self._send({"type": "picked", "flags": sorted(self.picked)})
                    self.check_items(tm, treasures)
                    n += 1
                time.sleep(ITEM_CHECK_S)

        def poll():                                     # telemetry without a feed: read it ourselves
            while True:
                tm = self.tm
                if tm is not None and not hasattr(tm, "listeners"):
                    try:
                        self.snapshot(tm.snapshot(within=POLL_WITHIN))
                    except Exception:
                        pass
                time.sleep(1.0 / RATE_HZ)

        def status():
            while True:
                try:
                    self.status()
                except Exception:
                    pass
                time.sleep(STATUS_S)

        for fn, name in ((items, "radar-items"), (poll, "radar"), (status, "radar-status")):
            threading.Thread(target=fn, daemon=True, name=name).start()

    def attach(self, tm) -> "Radar":
        """Follow what the bot reads. With feed.Feed (the default telemetry) subscribe to its frames like blackbox.py;
        otherwise poll tm.snapshot on a daemon thread. The bot's own reads are untouched. Also watches item pickups and
        sends the game state. Can be called again with new telemetry (watch reconnects); tm None = game not found yet."""
        self.tm, self._attached = tm, time.time()
        if not self._started:
            self._started = True
            self._threads()
        if tm is not None and hasattr(tm, "listeners"):
            tm.listeners.append(self.snapshot)
        return self

    def reconnect(self, connect, now: float | None = None) -> bool:
        """watch only: if the game went away, or no player for REATTACH_S while it runs, drop the telemetry and connect
        again. → True if it attached new telemetry."""
        now = time.time() if now is None else now
        tm = self.tm
        lost = not game_alive(tm)
        stuck = not lost and now - max(self._seen, self._attached) > REATTACH_S
        if not (lost or stuck):
            return False
        if tm is not None and hasattr(tm, "stop"):
            try:
                tm.stop()                               # feed thread — env.make_telemetry then builds a new one
            except Exception:
                pass
        new = connect()
        if new is not None:
            self.attach(new)
            return True
        if lost:
            self.tm = None
        else:
            self._attached = now                        # try again in REATTACH_S, not every check
        return False



def connect_game():
    """DSR telemetry, or None if the game isn't running (yet)."""
    os.environ["BOT_GAME"] = "dsr"             # env reads this on import; the radar is DSR only
    try:
        import env
        return env.make_telemetry({})
    except Exception:
        return None


def watch(tm=None, forever: bool = True, connect=connect_game) -> Radar:
    """Read-only watch: the radar follows the game while a person plays (no bot running, so nothing else sends
    snapshots and the page would freeze on the last bot frame). Only telemetry reads — no control.Pad, no memory writes.
    Survives the title screen and a game restart (connects again). Don't run it next to a bot started with --radar:
    both would send snapshots."""
    r = Radar().attach(tm if tm is not None else connect())
    line = "radar watch: read-only"
    print(f"{line} — python radar_server.py -> http://127.0.0.1:47801  (Ctrl+C to stop)"
          + ("" if r.tm is not None else "  [game not found — waiting]"), flush=True)
    r.say(line)
    while forever:
        time.sleep(RECONNECT_S)
        if r.reconnect(connect):
            print(f"radar watch: game attached again ({time.strftime('%H:%M:%S')})", flush=True)
    return r

if __name__ == "__main__":
    import sys
    if sys.argv[1:] != ["watch"]:
        sys.exit("usage: python radar.py watch")
    try:
        watch()
    except KeyboardInterrupt:
        pass
