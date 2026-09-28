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
import radar_record
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
AI_MATCH_R = 80.0              # m — a live foe is matched to the nearest extracted spawn of its kind within this
NO_LEASH = 1000                # MaxRetreatDistance at or above this = never gives up (9999 in the data)


def load_enemies(folder: Path = GAMEFILES) -> dict[int, list]:
    """{npc param id: [(spawn x, y, z, sight m, sight width deg, hearing m, leash m | None), ...]} from the extracted
    enemies' NpcThinkParam (msb_extract.py). Evidence grade "file" — metres assumed, not yet checked in play."""
    out: dict[int, list] = {}
    for path in sorted(folder.glob("*.json")):
        try:
            es = json.loads(path.read_text(encoding="utf-8")).get("enemies") or []
        except (OSError, ValueError):
            continue
        for e in es:
            t = e.get("think") or {}
            if e.get("kind") != "enemy" or not t.get("SightDistance"):
                continue
            leash = t.get("MaxRetreatDistance")
            out.setdefault(e["npc_param_id"], []).append(
                (*e["pos"], t["SightDistance"], t.get("SightRangeWidth") or 120, t.get("HearingDistance") or 0,
                 leash if leash and leash < NO_LEASH else None))
    return out


def match_ai(chars: list[dict], enemies: dict[int, list]) -> dict[str, list]:
    """{ptr: [sight, width, hearing, leash, spawn x, spawn z]} for live foes, by kind + nearest spawn."""
    out = {}
    for c in chars:
        cands = enemies.get(c.get("npc"))
        if not cands or c.get("x") is None:
            continue
        d, e = min((math.hypot(e[0] - c["x"], e[2] - c["z"]), e) for e in cands)
        if d <= AI_MATCH_R:
            out[str(c["ptr"])] = [e[3], e[4], e[5], e[6], e[0], e[2]]
    return out


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
    def __init__(self, props: list | None = None, english: bool = True, items: list | None = None,
                 enemies: dict | None = None):
        self.english = english                 # translate the bot's Korean log lines / tags for display (translate.py)
        self.props = props if props is not None else load_props()
        self.items = items if items is not None else load_items()
        self.enemies = enemies if enemies is not None else load_enemies()
        self.lock = threading.Lock()
        self.recorder = None                  # radar_record.Recorder — every message received is also saved
        self.replay = None                    # radar_record.Replay — when playing a recording back
        self.mesh = None                      # radar_mesh.MeshView — NavMesh faces near the player (Windows, game files)
        self.reset()

    def reset(self) -> None:
        """Forget everything received (a replay seeks by resetting and feeding again)."""
        with self.lock:
            self.picked: set[int] = set()     # pickup flags radar.py found set
            self.snap: dict | None = None
            self.says: collections.deque = collections.deque(maxlen=SAY_KEEP)
            self.pads: dict[int, dict] = {}   # XInput slot → last pad state (radar_pad.py, or a replayed recording)
            self.t_recv = 0.0

    def put(self, msg: dict) -> None:
        if self.recorder is not None:
            self.recorder.write(msg)
        with self.lock:
            self.t_recv = time.time()
            if msg.get("type") == "snap":
                self.snap = msg
            elif msg.get("type") == "picked":
                self.picked.update(int(f) for f in msg.get("flags") or [])
            elif msg.get("type") == "unpicked":            # flag off again (older save loaded) — show the item again
                self.picked.difference_update(int(f) for f in msg.get("flags") or [])
            elif msg.get("type") == "pad":
                self.pads[int(msg.get("i") or 0)] = {k: msg.get(k) for k in ("btn", "lt", "rtr", "lx", "ly", "rx", "ry")}
            elif msg.get("type") == "say":
                self.says.append({"t": msg.get("t"), "line": msg.get("line", "")})

    def get(self) -> dict:
        with self.lock:
            snap, says, picked, pads = self.snap, list(self.says), set(self.picked), dict(self.pads)
            age = round(time.time() - self.t_recv, 2) if self.t_recv else None
        if self.english:
            says = [{**x, "line": translate.line(x.get("line"))} for x in says]
            if snap:
                snap = {**snap, **{k: translate.line(snap[k]) for k in ("path_tag", "spot_tag") if snap.get(k)}}
        out = {"snap": snap, "says": says, "age": age, "pads": {str(k): v for k, v in pads.items()}}
        if self.replay is not None:
            out["replay"] = self.replay.status()
        p = (snap or {}).get("player") or {}
        if p.get("x") is not None:
            out["props"] = [o for o in self.props if abs(o[0] - p["x"]) < PROP_R and abs(o[2] - p["z"]) < PROP_R
                            and abs(o[1] - p["y"]) < PROP_DY and math.hypot(o[0] - p["x"], o[2] - p["z"]) < PROP_R]
            out["ai"] = match_ai(snap.get("chars") or [], self.enemies)
            # items: [x, y, z, kind, label] not yet picked up (any of its flags set = taken)
            out["items"] = [o[:5] for o in self.items if math.hypot(o[0] - p["x"], o[2] - p["z"]) < PROP_R
                            and abs(o[1] - p["y"]) < ITEM_DY and not (set(o[5]) & picked)]
            if self.mesh is not None:
                out["mesh"] = self.mesh.near(p["x"], p["y"], p["z"])
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
            if self.path.split("?")[0] == "/replay" and state.replay is not None:
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                v = q.get("v", [None])[0]
                state.replay.command(q.get("cmd", [""])[0], float(v) if v not in (None, "") else None)
                self._send(200, json.dumps(state.replay.status()).encode("utf-8"), "application/json")
            elif self.path.split("?")[0] == "/state":
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
    ap.add_argument("--replay", metavar="FILE", help="play back a radar recording (data/radar/*.jsonl) or an observe_record.py file")
    ap.add_argument("--no-record", action="store_true", help="don't save this session to data/radar/")
    ap.add_argument("--no-pad", action="store_true", help="don't read the controller (XInput)")
    ap.add_argument("--maps", default="m10_02_00_00,m10_01_00_00", help="NavMesh maps to draw (read from the game install)")
    ap.add_argument("--no-mesh", action="store_true", help="don't draw the NavMesh")
    a = ap.parse_args()
    demo_props = [[6.0, 0.0, 1.0, False, "o1130_d2"], [7.0, 0.0, -1.5, False, "o1132_d3"], [-3.0, 0.0, 6.0, True, "o1230_d4"],
                  [2.0, 0.0, -7.0, False, "o1154_d5"]]
    demo_items = [[3.0, 0.0, 5.0, "soul", "Soul of a Lost Undead", [1]], [-6.0, 0.0, -2.0, "humanity", "Humanity", [2]],
                  [8.0, 0.0, 6.0, "titanite", "Titanite Shard x2", [3]], [-2.0, 0.0, -9.0, "other", "Firebomb x3", [4]]]
    demo_enemies = {225000: [(10.0 * math.cos(k), 0.0, 10.0 * math.sin(k), 30, 120, 10, 20) for k in range(6)]}
    state = State(props=demo_props if a.demo else None, english=not a.korean, items=demo_items if a.demo else None,
                  enemies=demo_enemies if a.demo else None)
    if not a.demo:
        print(f"breakable props: {len(state.props)}, items: {len(state.items)} (data/gamefiles)")
    if not a.no_mesh:
        import radar_mesh
        if a.demo:      # an L-shaped floor around the demo world, a step up in one corner
            state.mesh = radar_mesh.MeshView([radar_mesh.rect_mesh([(-14, -4, 6, 4, 0.0), (6, -4, 14, 4, 0.0), (6, 4, 14, 16, 0.0),
                                                                    (6, -16, 14, -4, 0.0), (-14, -16, -6, -4, 1.5)])])
        else:
            state.mesh = radar_mesh.load(a.maps.split(","))
            print(f"navmesh: {'drawn (' + a.maps + ')' if state.mesh else 'not found (game install / soulstruct) — radar without floor'}")
    if a.replay:
        msgs = radar_record.load(a.replay)
        state.replay = radar_record.Replay(state, msgs, Path(a.replay).name).start()
        print(f"replay: {a.replay} — {len(msgs)} messages, {state.replay.status()['len']:.0f} s")
    else:
        threading.Thread(target=udp_loop, args=(state, a.udp), daemon=True).start()
        if not a.no_record and not a.demo:
            state.recorder = radar_record.Recorder()
            print(f"recording: {state.recorder.path}")
        if not a.no_pad:
            import radar_pad
            if radar_pad.start(state.put, demo=a.demo):
                print("controller: reading XInput" if not a.demo else "controller: demo input")
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
