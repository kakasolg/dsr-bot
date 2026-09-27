"""Radar server — receives radar.py's UDP packets and serves the radar page. Local only (127.0.0.1).

  python radar_server.py              → open http://127.0.0.1:47801 in a browser (second monitor or OBS browser source)
  python radar_server.py --demo       fake world (no game, no bot) — to see or develop the page on any OS
  python run.py burg-bonfire --radar  the bot sends; start this server first or later, either order works

Endpoints: /  (radar.html)   /state  (latest snapshot + last decision lines + breakable props near the player, JSON)
Props and items come from data/gamefiles/*.json (msb_extract.py) — every extracted map is loaded; the ones near the
player are sent. Items already picked up (pickup flags radar.py reports) are left out.
Standard library only.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import random
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import radar
import translate

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PAGE = Path(__file__).parent / "radar.html"
GAMEFILES = Path(__file__).parent / "data" / "gamefiles"
PROP_R, PROP_DY = 40.0, 1.0     # props sent: within this (horizontal) of the player, and this height (±1 m: same floor only — user 2026-09-27, lower floors showed up)
STRONG_MIN_ATTACK = 50         # same as msb_extract.py
ITEM_DY = 5.0                  # items: ±5 m — a ledge or stairs above still matters (user 2026-09-27; props stay ±1 m)
HTTP_PORT = radar.PORT + 1
SAY_KEEP = 12


def load_props(folder: Path = GAMEFILES) -> list[list]:
    """[x, y, z, strong, name] for every breakable prop of every extracted map."""
    out = []
    for path in sorted(folder.glob("*.json")):
        try:
            objs = json.loads(path.read_text(encoding="utf-8"))["objects"]
        except (OSError, ValueError, KeyError):
            continue
        for o in objs:
            if o.get("breakable") is True:
                x, y, z = o["pos"]
                out.append([x, y, z, (o.get("min_attack") or 0) >= STRONG_MIN_ATTACK, o["name"]])
    return out


ITEM_KINDS = ("soul", "humanity", "titanite", "other")


def load_items(folder: Path = GAMEFILES) -> list[list]:
    """[x, y, z, kind, label, flags] for every extracted treasure (msb_extract.py treasures)."""
    out = []
    for path in sorted(folder.glob("*.json")):
        try:
            ts = json.loads(path.read_text(encoding="utf-8")).get("treasures") or []
        except (OSError, ValueError):
            continue
        for t in ts:
            if t.get("kind"):
                x, y, z = t["pos"]
                out.append([x, y, z, t["kind"], t.get("label") or "", list(t.get("flags") or [])])
    return out


class State:
    def __init__(self, props: list | None = None, english: bool = True, items: list | None = None):
        self.english = english                 # translate the bot's Korean log lines / tags for display (translate.py)
        self.props = props if props is not None else load_props()
        self.items = items if items is not None else load_items()
        self.picked: set[int] = set()        # pickup flags radar.py found set
        self.lock = threading.Lock()
        self.snap: dict | None = None
        self.says: collections.deque = collections.deque(maxlen=SAY_KEEP)
        self.t_recv = 0.0

    def put(self, msg: dict) -> None:
        with self.lock:
            self.t_recv = time.time()
            if msg.get("type") == "snap":
                self.snap = msg
            elif msg.get("type") == "picked":
                self.picked.update(int(f) for f in msg.get("flags") or [])
            elif msg.get("type") == "say":
                self.says.append({"t": msg.get("t"), "line": msg.get("line", "")})

    def get(self) -> dict:
        with self.lock:
            snap, says, picked = self.snap, list(self.says), set(self.picked)
            age = round(time.time() - self.t_recv, 2) if self.t_recv else None
        if self.english:
            says = [{**x, "line": translate.line(x.get("line"))} for x in says]
            if snap:
                snap = {**snap, **{k: translate.line(snap[k]) for k in ("path_tag", "spot_tag") if snap.get(k)}}
        out = {"snap": snap, "says": says, "age": age}
        p = (snap or {}).get("player") or {}
        if p.get("x") is not None:
            out["props"] = [o for o in self.props if abs(o[0] - p["x"]) < PROP_R and abs(o[2] - p["z"]) < PROP_R
                            and abs(o[1] - p["y"]) < PROP_DY and math.hypot(o[0] - p["x"], o[2] - p["z"]) < PROP_R]
            # items: [x, y, z, kind, label] not yet picked up (any of its flags set = taken)
            out["items"] = [o[:5] for o in self.items if math.hypot(o[0] - p["x"], o[2] - p["z"]) < PROP_R
                            and abs(o[1] - p["y"]) < ITEM_DY and not (set(o[5]) & picked)]
        return out


def udp_loop(state: State, port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", port))
    while True:
        data, _ = sock.recvfrom(65535)
        try:
            state.put(json.loads(data.decode("utf-8")))
        except Exception:
            pass


def make_handler(state: State):
    class H(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.split("?")[0] == "/state":
                self._send(200, json.dumps(state.get(), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            elif self.path.split("?")[0] in ("/", "/radar.html"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain")

        def log_message(self, *a):
            pass

    return H


# ── Demo: a fake world so the page can be seen without the game ───────────────
class _C:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def demo_loop(port: int) -> None:
    r = radar.Radar(port=port)
    rng = random.Random(1)
    foes = [dict(ptr=100 + i, name=f"Hollow #{i + 1}", npc=225000, ang=rng.uniform(0, 6.28), rad=rng.uniform(6, 25),
                 spd=rng.uniform(-0.3, 0.3), hp=200) for i in range(6)]
    lines = ["walk: ramp bottom -> waiting spot", "lure: knife at Hollow #3", "fight: Hollow #3 (4.2 m)",
             "attack anim 3004 -> roll", "retreat: 2 foes closing", "stagger -> light x2"]
    mv = _C(cam_target=None, show_path=None, show_spot=None, show_smash=None)
    r.follow(mv)
    t0, k = time.time(), 0
    while True:
        t = time.time() - t0
        px, pz = 5 * math.sin(t / 9), 5 * math.cos(t / 11)
        chars = []
        for f in foes:
            f["ang"] += f["spd"] * 0.1
            x, z = px + f["rad"] * math.cos(f["ang"]), pz + f["rad"] * math.sin(f["ang"])
            hp = max(0, f["hp"] - int(t * 3) % 260) if f["ptr"] == 103 else f["hp"]
            chars.append(_C(ptr=f["ptr"], name=f["name"], npc_param=f["npc"], team=6, hp=hp, max_hp=200, sp=0, max_sp=0,
                            x=x, y=0.0, z=z, dist=math.hypot(x - px, z - pz), heading=math.atan2(px - x, pz - z) + math.pi,
                            anim=3004 if f["rad"] < 9 else 7000))
        chars.sort(key=lambda c: c.dist)
        phase = int(t / 8) % 3                     # cycle: walk a path → fight the nearest → hold a spot
        if phase == 0:
            mv.cam_target, mv.show_spot = None, None
            mv.show_path = ("down the ramp", [(px + 1.5 * i, 0.0, pz + 3 * math.sin(i / 3)) for i in range(12)])
            if t % 8 > 5:
                mv.show_smash = ("o1130_d2", (6.0, 0.0, 1.0), time.time())
        elif phase == 1:
            mv.show_path, mv.cam_target = None, chars[0].ptr
        else:
            mv.cam_target, mv.show_path = None, None
            mv.show_spot = ("waiting spot", (px - 4.0, 0.0, pz + 2.0), time.time())
        player = _C(ptr=1, name="", npc_param=0, team=1, hp=int(420 + 150 * math.sin(t / 5)), max_hp=600, sp=90, max_sp=120,
                    x=px, y=0.0, z=pz, dist=0.0, heading=t / 4 % (2 * math.pi), anim=None)
        r.snapshot(_C(t=time.time(), player=player, chars=chars, cam_yaw=t / 6 % (2 * math.pi), flask_hp=3, max_flask_hp=5))
        if int(t / 2.5) != k:
            k = int(t / 2.5)
            r.say(lines[k % len(lines)])
        time.sleep(0.1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--demo", action="store_true", help="fake world, no game needed")
    ap.add_argument("--udp", type=int, default=radar.PORT)
    ap.add_argument("--http", type=int, default=HTTP_PORT)
    ap.add_argument("--korean", action="store_true", help="show the bot's log lines untranslated (default: English)")
    a = ap.parse_args()
    demo_props = [[6.0, 0.0, 1.0, False, "o1130_d2"], [7.0, 0.0, -1.5, False, "o1132_d3"], [-3.0, 0.0, 6.0, True, "o1230_d4"],
                  [2.0, 0.0, -7.0, False, "o1154_d5"]]
    demo_items = [[3.0, 0.0, 5.0, "soul", "Soul of a Lost Undead", [1]], [-6.0, 0.0, -2.0, "humanity", "Humanity", [2]],
                  [8.0, 0.0, 6.0, "titanite", "Titanite Shard x2", [3]], [-2.0, 0.0, -9.0, "other", "Firebomb x3", [4]]]
    state = State(props=demo_props if a.demo else None, english=not a.korean, items=demo_items if a.demo else None)
    if not a.demo:
        print(f"breakable props: {len(state.props)}, items: {len(state.items)} (data/gamefiles)")
    threading.Thread(target=udp_loop, args=(state, a.udp), daemon=True).start()
    if a.demo:
        threading.Thread(target=demo_loop, args=(a.udp,), daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", a.http), make_handler(state))
    print(f"radar: http://127.0.0.1:{a.http}  (UDP {a.udp}{', demo' if a.demo else ''})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
