"""Radar sender — pushes what the bot sees and says to radar_server.py over local UDP. Never blocks or breaks the bot.

  from radar import Radar
  r = Radar()               # 127.0.0.1:47800 (RADAR_PORT)
  r.attach(tm)              # follows the feed's frames (at most RATE_HZ per second)
  r.follow(mv)              # + what layer 4 is doing: target (mv.cam_target), path (mv.show_path), held spot (mv.show_spot),
                            #   prop just swung at (mv.show_smash)
  r.say("retreat: 2 foes closing")  # one decision line (run.py's Log does this for every log line)

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


class Radar:
    def __init__(self, host: str = "127.0.0.1", port: int = PORT):
        self.addr = (host, port)
        self.mv = None
        self.player = None           # (x, y, z) of the last frame sent — where to look for pickups
        self.picked: set[int] = set()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self._last = 0.0

    def _send(self, msg: dict) -> None:
        try:
            self.sock.sendto(json.dumps(msg, ensure_ascii=False, default=str).encode("utf-8"), self.addr)
        except Exception:
            pass

    def snapshot(self, s) -> None:
        now = time.time()
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

    def watch_items(self, tm) -> None:
        treasures = load_treasures()
        if not treasures:
            return

        def loop():
            n = 0
            while True:
                if n % 30 == 0 and self.picked:     # the server may have restarted — resend what is known now and then
                    self._send({"type": "picked", "flags": sorted(self.picked)})
                self.check_items(tm, treasures)
                n += 1
                time.sleep(ITEM_CHECK_S)

        threading.Thread(target=loop, daemon=True, name="radar-items").start()

    def attach(self, tm) -> "Radar":
        """Follow what the bot reads. With feed.Feed (the default telemetry) subscribe to its frames like blackbox.py;
        otherwise poll tm.snapshot on a daemon thread. The bot's own reads are untouched. Also watches item pickups."""
        if hasattr(tm, "event_flag"):
            self.watch_items(tm)
        if hasattr(tm, "listeners"):
            tm.listeners.append(self.snapshot)
            return self

        def poll():
            while True:
                try:
                    self.snapshot(tm.snapshot(within=POLL_WITHIN))
                except Exception:
                    pass
                time.sleep(1.0 / RATE_HZ)

        threading.Thread(target=poll, daemon=True, name="radar").start()
        return self
