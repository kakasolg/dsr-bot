"""Planned path vs actual track, written by every bot run — no radar server needed (ROADMAP 1-e / 0-b).

  t = track.Track(path).attach(tm).follow(mv)   # run.py does this: data/runs/<stamp>_<name>.track.jsonl

Same message format as the radar (radar.py "snap" lines, radar_record "rt" key), thinned to RATE_HZ, and the planned
path only when it changes — so track_report.py reads these files and radar recordings (data/radar/*.jsonl) alike.
Read-only: it never touches the pad or the game.
"""
from __future__ import annotations

import json
import threading
import time

import radar

RATE_HZ = 2.0


class Track:
    def __init__(self, path, rate_hz: float = RATE_HZ):
        self.f = open(path, "a", encoding="utf-8")
        self.rate = rate_hz
        self.mv = None
        self.t0 = time.time()
        self._last = 0.0
        self._path_key = None
        self._lock = threading.Lock()

    def follow(self, mv) -> "Track":
        self.mv = mv
        return self

    def write(self, msg: dict) -> None:
        line = json.dumps({"rt": round(time.time() - self.t0, 2), **msg}, ensure_ascii=False, default=str)
        with self._lock:
            self.f.write(line + "\n")
            self.f.flush()

    def say(self, line: str) -> None:
        try:
            self.write({"type": "say", "line": str(line)[:300]})
        except Exception:
            pass

    def snapshot(self, s) -> None:
        now = time.time()
        if s is None or now - self._last < 1.0 / self.rate:
            return
        self._last = now
        try:
            msg = {"type": "snap", "player": radar.chr_dict(s.player),
                   "chars": [radar.chr_dict(c) for c in s.hostile(12.0)]}
            if self.mv is not None:
                intent = radar.intent_dict(self.mv)
                key = (intent.get("path_tag"), json.dumps(intent.get("path")))
                if key == self._path_key:
                    intent.pop("path", None)            # unchanged — the report keeps the last one it saw
                else:
                    self._path_key = key
                    if "path" not in intent:
                        intent["path"] = None           # walking ended
                msg.update(intent)
            self.write(msg)
        except Exception:
            pass

    def attach(self, tm) -> "Track":
        if hasattr(tm, "listeners"):
            tm.listeners.append(self.snapshot)
            return self

        def poll():
            while True:
                try:
                    self.snapshot(tm.snapshot(within=radar.POLL_WITHIN))
                except Exception:
                    pass
                time.sleep(1.0 / self.rate)

        threading.Thread(target=poll, daemon=True, name="track").start()
        return self
