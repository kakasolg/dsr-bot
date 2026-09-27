"""Radar sender — pushes what the bot sees and says to radar_server.py over local UDP. Never blocks or breaks the bot.

  from radar import Radar
  r = Radar()               # 127.0.0.1:47800 (RADAR_PORT)
  r.attach(tm)              # follows the feed's frames (at most RATE_HZ per second)
  r.say("후퇴: 적 2명 접근")  # one decision line (run.py's Log does this for every log line)

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


class Radar:
    def __init__(self, host: str = "127.0.0.1", port: int = PORT):
        self.addr = (host, port)
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
            self._send({"type": "snap", **snapshot_dict(s)})
        except Exception:
            pass

    def say(self, line: str) -> None:
        self._send({"type": "say", "t": time.time(), "line": str(line)[:300]})

    def attach(self, tm) -> "Radar":
        """Follow what the bot reads. With feed.Feed (the default telemetry) subscribe to its frames like blackbox.py;
        otherwise poll tm.snapshot on a daemon thread. The bot's own reads are untouched."""
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
