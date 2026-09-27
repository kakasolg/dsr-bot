"""Radar server — receives radar.py's UDP packets and serves the radar page. Local only (127.0.0.1).

  python radar_server.py              → open http://127.0.0.1:47801 in a browser (second monitor or OBS browser source)
  python radar_server.py --demo       fake world (no game, no bot) — to see or develop the page on any OS
  python run.py burg-bonfire --radar  the bot sends; start this server first or later, either order works

Endpoints: /  (radar.html)   /state  (latest snapshot + last decision lines + breakable props near the player, JSON)
Props come from data/gamefiles/*.json (msb_extract.py) — every extracted map is loaded; the ones near the player are sent.
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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PAGE = Path(__file__).parent / "radar.html"
GAMEFILES = Path(__file__).parent / "data" / "gamefiles"
PROP_R, PROP_DY = 40.0, 6.0     # props sent: within this (horizontal) of the player, and this height
STRONG_MIN_ATTACK = 50         # same as msb_extract.py
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


class State:
    def __init__(self, props: list | None = None):
        self.props = props if props is not None else load_props()
        self.lock = threading.Lock()
        self.snap: dict | None = None
        self.says: collections.deque = collections.deque(maxlen=SAY_KEEP)
        self.t_recv = 0.0

    def put(self, msg: dict) -> None:
        with self.lock:
            self.t_recv = time.time()
            if msg.get("type") == "snap":
                self.snap = msg
            elif msg.get("type") == "say":
                self.says.append({"t": msg.get("t"), "line": msg.get("line", "")})

    def get(self) -> dict:
        with self.lock:
            snap = self.snap
            out = {"snap": snap, "says": list(self.says), "age": round(time.time() - self.t_recv, 2) if self.t_recv else None}
        p = (snap or {}).get("player") or {}
        if p.get("x") is not None:
            out["props"] = [o for o in self.props if abs(o[0] - p["x"]) < PROP_R and abs(o[2] - p["z"]) < PROP_R
                            and abs(o[1] - p["y"]) < PROP_DY and math.hypot(o[0] - p["x"], o[2] - p["z"]) < PROP_R]
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
    foes = [dict(ptr=100 + i, name=f"망자 #{i + 1}", npc=225000, ang=rng.uniform(0, 6.28), rad=rng.uniform(6, 25),
                 spd=rng.uniform(-0.3, 0.3), hp=200) for i in range(6)]
    lines = ["이동: 경사로 아래 → 대기 지점", "끌어오기: 망자 #3 에 나이프", "교전: 망자 #3 (4.2 m)",
             "공격 모션 3004 → 구르기", "후퇴: 적 2명 접근", "휘청 → 약공 2연타"]
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
            mv.show_path = ("경사로 아래로", [(px + 1.5 * i, 0.0, pz + 3 * math.sin(i / 3)) for i in range(12)])
            if t % 8 > 5:
                mv.show_smash = ("o1130_d2", (6.0, 0.0, 1.0), time.time())
        elif phase == 1:
            mv.show_path, mv.cam_target = None, chars[0].ptr
        else:
            mv.cam_target, mv.show_path = None, None
            mv.show_spot = ("대기 지점", (px - 4.0, 0.0, pz + 2.0), time.time())
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
    a = ap.parse_args()
    demo_props = [[6.0, 0.0, 1.0, False, "o1130_d2"], [7.0, 0.0, -1.5, False, "o1132_d3"], [-3.0, 0.0, 6.0, True, "o1230_d4"],
                  [2.0, 0.0, -7.0, False, "o1154_d5"]]
    state = State(props=demo_props if a.demo else None)
    if not a.demo:
        print(f"부서지는 물건 {len(state.props)}개 (data/gamefiles)")
    threading.Thread(target=udp_loop, args=(state, a.udp), daemon=True).start()
    if a.demo:
        threading.Thread(target=demo_loop, args=(a.udp,), daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", a.http), make_handler(state))
    print(f"레이더: http://127.0.0.1:{a.http}  (UDP {a.udp}{', 데모' if a.demo else ''})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
