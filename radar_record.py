"""Radar recording and replay — every message radar_server.py receives, saved per session and played back with a timeline.

  python radar_server.py                        records to data/radar/<YYYYmmdd_HHMMSS>.jsonl (--no-record to skip)
  python radar_server.py --replay FILE          replays it on the same page: play / pause / seek / speed / frame step
  python radar_server.py --replay data/observe/20260926_160200.jsonl   an observe_record.py recording (human demo) too

File: one JSON message per line, as radar.py sent it, plus "rt" = seconds since the session started.
Replay feeds the messages into the same State the live server uses, so the page and the overlay can't tell the difference
(except the "replay" block in /state that drives the timeline). Seeking rebuilds the state from the start up to that time.
Standard library only.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

RADAR_DIR = Path(__file__).resolve().parent / "data" / "radar"
FRAME_S = 0.1          # one step of the frame buttons (the radar sends 10 frames/s)


class Recorder:
    def __init__(self, folder: Path = RADAR_DIR):
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / f"{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        self.f = self.path.open("x", encoding="utf-8")
        self.t0 = time.time()
        self.lock = threading.Lock()
        self.n = 0

    def write(self, msg: dict) -> None:
        line = json.dumps({"rt": round(time.time() - self.t0, 3), **msg}, ensure_ascii=False, default=str)
        with self.lock:
            self.f.write(line + "\n")
            self.n += 1
            if self.n % 50 == 0:
                self.f.flush()

    def close(self) -> None:
        with self.lock:
            self.f.close()


# ── observe_record.py (human demo) → radar messages ─────────────────────────
def _observe_to_radar(rec: dict, t0_ms: float) -> dict | None:
    """One observe_record line → a radar message (same shapes radar.py sends), or None."""
    k, rt = rec.get("k"), (rec.get("ms", 0.0) - t0_ms) / 1000.0
    if k == "w":
        p = rec.get("p") or {}
        pos = p.get("pos") or [None, None, None]

        def chr_(e, team):
            ep = e.get("pos") or [None, None, None]
            return {"ptr": e.get("ptr") or e.get("handle"), "name": "", "npc": e.get("npc"), "team": team,
                    "hp": e.get("hp_raw"), "max_hp": e.get("max_hp_raw"), "sp": None, "max_sp": None,
                    "x": ep[0], "y": ep[1], "z": ep[2], "dist": e.get("d"), "heading": e.get("hd"), "anim": e.get("anim")}

        chars = []
        for e in rec.get("e") or []:
            if e.get("vt") == "player" or e.get("npc") == 0:
                continue                                   # other players / phantoms — not foes
            chars.append(chr_(e, 6))
        lock = (rec.get("lock") or {}).get("resolved")
        return {"rt": rt, "type": "snap", "t": rt,
                "player": {"ptr": p.get("handle"), "name": "", "npc": 0, "team": 1, "hp": p.get("hp_raw"),
                           "max_hp": p.get("max_hp_raw"), "sp": p.get("sp"), "max_sp": p.get("max_sp"),
                           "x": pos[0], "y": pos[1], "z": pos[2], "dist": 0.0, "heading": p.get("hd"), "anim": p.get("anim")},
                "chars": sorted(chars, key=lambda c: c["dist"] if c["dist"] is not None else 999),
                "cam_yaw": rec.get("cam_yaw"), "flask_hp": None, "max_flask_hp": None,
                **({"target": lock} if lock is not None else {})}
    if k == "pad":                                          # observe's "rt" is the right trigger — ours is "rtr" ("rt" = time)
        return {"rt": rt, "type": "pad", "i": rec.get("i"), "btn": rec.get("btn"), "lt": rec.get("lt"), "rtr": rec.get("rt"),
                "lx": rec.get("lx"), "ly": rec.get("ly"), "rx": rec.get("rx"), "ry": rec.get("ry")}
    if k == "marker":
        return {"rt": rt, "type": "say", "t": rt, "line": f"F9 marker #{rec.get('n', '')}".strip()}
    return None


def load(path: str | Path) -> list[dict]:
    """Messages of a radar recording or an observe_record.py recording, sorted by time."""
    msgs, t0_ms, observe = [], 0.0, False
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("k") == "hdr":
                observe = True
                continue
            if observe:
                if not msgs and "ms" in rec and t0_ms == 0.0:
                    t0_ms = rec["ms"]
                m = _observe_to_radar(rec, t0_ms)
                if m:
                    msgs.append(m)
            elif "rt" in rec:
                msgs.append(rec)
    msgs.sort(key=lambda m: m["rt"])
    return msgs


class Replay:
    """Feeds recorded messages into a State at the recorded pace (× speed), with seek / step."""

    def __init__(self, state, msgs: list[dict], name: str = ""):
        self.state, self.msgs, self.name = state, msgs, name
        self.t0 = msgs[0]["rt"] if msgs else 0.0
        self.t1 = msgs[-1]["rt"] if msgs else 0.0
        self.t = self.t0
        self.i = 0
        self.playing, self.speed = True, 1.0
        self.lock = threading.Lock()
        self.markers = [m["rt"] for m in msgs if m.get("type") == "say" and str(m.get("line", "")).startswith("F9 marker")]

    def status(self) -> dict:
        with self.lock:
            return {"name": self.name, "t": round(self.t - self.t0, 2), "len": round(self.t1 - self.t0, 2),
                    "playing": self.playing, "speed": self.speed, "markers": [round(x - self.t0, 2) for x in self.markers]}

    def _feed_until(self, t: float) -> None:
        while self.i < len(self.msgs) and self.msgs[self.i]["rt"] <= t:
            m = dict(self.msgs[self.i])
            m.pop("rt", None)
            self.state.put(m)
            self.i += 1

    def seek(self, t_rel: float) -> None:
        with self.lock:
            t = min(max(self.t0 + t_rel, self.t0), self.t1)
            self.state.reset()
            self.i = 0
            self._feed_until(t)
            self.t = t

    def command(self, cmd: str, v: float | None = None) -> None:
        with self.lock:
            if cmd == "play":
                self.playing = True
                if self.t >= self.t1:
                    self.playing = False
            elif cmd == "pause":
                self.playing = False
            elif cmd == "speed" and v:
                self.speed = max(0.1, min(8.0, float(v)))
        if cmd == "seek" and v is not None:
            self.seek(float(v))
        elif cmd == "step" and v is not None:
            with self.lock:
                self.playing = False
                now = self.t - self.t0
            self.seek(now + float(v) * FRAME_S)

    def loop(self) -> None:
        last = time.time()
        while True:
            time.sleep(0.02)
            now = time.time()
            dt, last = now - last, now
            with self.lock:
                if not self.playing:
                    continue
                self.t = min(self.t + dt * self.speed, self.t1)
                self._feed_until(self.t)
                if self.t >= self.t1:
                    self.playing = False

    def start(self) -> "Replay":
        self.seek(0.0)
        threading.Thread(target=self.loop, daemon=True, name="replay").start()
        return self

