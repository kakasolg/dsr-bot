"""radar warp offline test — every refusal of radar_warp.Warper, the one allowed path (lock held during the warp, released
after), the game-state field of /state, and radar_server's POST /warp origin guard. Fake game, no memory writes.

  python tests/radar_warp_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import http.client
import json
import socket
import sys
import threading
import time
from http.server import ThreadingHTTPServer

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import radar_server as S
import radar_warp as W
from telemetry import Chr, Snapshot

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


class Lock:
    def __init__(self, free=True):
        self.free, self.held, self.released = free, False, 0

    def acquire(self):
        self.held = self.free
        return self.free

    def release(self):
        self.held = False
        self.released += 1


class Game:
    def __init__(self, hp=500, in_world=True, menu=False, warp_ok=True, char="Knight bot"):
        self.hp, self.in_world, self.menu, self.warp_ok, self.char = hp, in_world, menu, warp_ok, char
        self.warps = []
        self.lock_held_during_warp = None

    def snapshot(self, within=60.0):
        if not self.in_world:
            return None
        return Snapshot(t=time.time(), player=Chr(ptr=1, npc_param=0, team=1, hp=self.hp, max_hp=500, x=0.0, y=0.0, z=0.0), chars=[])

    def menu_open(self):
        return self.menu

    def char_name(self):
        return self.char

    def bonfire_warp(self, bid, log=print):
        self.lock_held_during_warp = lock.held
        self.warps.append(bid)
        log("   화톳불 워프 끝")
        return self.warp_ok


OFF = {"offline": True, "why": ["Steam set offline"]}
LIT = {"Knight bot": {1012962: "2026-09-25"}}          # per character (bonfires.load(char))
NAMES = {1012962: "Undead Burg"}
lock = Lock()
says: list[str] = []


def warper(steam=OFF, game=None, lk=None, enabled=True, connect=None):
    global lock
    lock = lk or Lock()
    g = game or Game()
    w = W.Warper(says.append, enabled=enabled, steam_check=lambda: steam, connect=connect or (lambda: g), lock=lambda: lock,
                 lit=lambda char: LIT.get(char, {}), names=lambda: NAMES, run_async=False)
    return w, g


W.LOCK_TRIES, W.LOCK_GAP = 2, 0.0

print("거절")
cases = [
    ("replay·demo 에서는 끔", dict(enabled=False), 1012962, "replay"),
    ("불 안 붙인 화톳불", {}, 1022960, "not a lit bonfire"),
    ("잘못된 id", {}, "abc", "bad bonfire id"),
    ("Steam 오프라인 확인 안 됨 (None)", dict(steam={"offline": None, "why": ["Steam not running"]}), 1012962, "Steam not confirmed offline"),
    ("Steam 온라인", dict(steam={"offline": False, "why": ["Steam set ONLINE"]}), 1012962, "Steam not confirmed offline"),
    ("봇 실행 중 (bot.lock)", dict(lk=Lock(free=False)), 1012962, "a bot is running"),
    ("게임 없음", dict(connect=lambda: None), 1012962, "game not found"),
    ("타이틀·로딩", dict(game=Game(in_world=False)), 1012962, "not in the world"),
    ("사망", dict(game=Game(hp=0)), 1012962, "dead"),
    ("메뉴 열림", dict(game=Game(menu=True)), 1012962, "menu"),
    ("다른 캐릭터(새 캐릭터)는 이 화톳불을 안 붙임", dict(game=Game(char="NewGuy")), 1012962, "not a lit bonfire of 'NewGuy'"),
    ("캐릭터 이름 못 읽음", dict(game=Game(char=None)), 1012962, "not a lit bonfire of None"),
]
for name, kw, bid, want in cases:
    w, g = warper(**kw)
    ok, msg = w.request(bid)
    check(f"{name} → '{msg}'", not ok and want in msg and g.warps == [] and not lock.held and not w.busy
          and w.last.startswith("refused"))
w, g = warper()
w.busy = True
check("다른 워프 중이면 거절", w.request(1012962) == (False, "a warp is already running") and g.warps == [])

print("허용")
says.clear()
w, g = warper()
ok, msg = w.request(1012962)
check(f"워프 → '{msg}'", ok and g.warps == [1012962])
check("워프하는 동안 bot.lock 쥠, 끝나면 놓음", g.lock_held_during_warp is True and not lock.held and lock.released == 1)
check("결과를 Decisions 줄로", says[0].startswith("warp → 1012962 Undead Burg: requested") and says[-1].endswith("arrived")
      and "warp: 화톳불 워프 끝" in says)
check("상태: 끝남", w.status() == {"busy": False, "last": "arrived at Undead Burg", "enabled": True})
w, g = warper(game=Game(warp_ok=False))
w.request(1012962)
check("워프 실패도 기록하고 lock 놓음", "failed" in w.last and not lock.held and not w.busy)
check("화톳불 목록은 캐릭터별", warper()[0].bonfires("Knight bot") == [{"id": 1012962, "name": "Undead Burg"}]
      and warper()[0].bonfires("NewGuy") == [] and warper()[0].bonfires(None) == [])


print("/state 게임 상태")
st = S.State(props=[], items=[], enemies={})
check("보내는 쪽 없음 → none", st.get()["game"] == {"game": "none"})
st.put({"type": "status", "t": time.time(), "game": "title", "menu": None, "away": 4.0})
check("status 패킷 → title", st.get()["game"] == {"game": "title", "menu": None, "away": 4.0, "char": None})
st.t_status -= 5
check("2 s 넘게 끊기면 다시 none", st.get()["game"] == {"game": "none"})
check("steam·warp 없으면 키 없음", "steam" not in st.get() and "warp" not in st.get())


print("POST /warp 출처 확인")


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


port = free_port()
st.warp, _ = warper()
st.steam = OFF
srv = ThreadingHTTPServer(("127.0.0.1", port), S.make_handler(st))
threading.Thread(target=srv.serve_forever, daemon=True).start()


def post(body, headers):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    c.putrequest("POST", "/warp", skip_host=True)
    for k, v in headers.items():
        c.putheader(k, v)
    data = json.dumps(body).encode()
    c.putheader("Content-Length", str(len(data)))
    c.endheaders(data)
    r = c.getresponse()
    return r.status, r.read()


good = {"Host": f"127.0.0.1:{port}", "X-Radar": "1", "Content-Type": "application/json"}
check("X-Radar 없으면 403", post({"id": 1012962}, {**good, "X-Radar": ""})[0] == 403)
check("다른 Host (DNS rebinding) 403", post({"id": 1012962}, {**good, "Host": f"evil.example:{port}"})[0] == 403)
check("다른 Origin 403", post({"id": 1012962}, {**good, "Origin": "http://evil.example"})[0] == 403)
code, body = post({"id": 1022960}, good)
check(f"거절은 409 + 이유 ({json.loads(body)['msg']})", code == 409 and not json.loads(body)["ok"])
code, body = post({"id": 1012962}, {**good, "Origin": f"http://127.0.0.1:{port}"})
check("같은 출처 → 200, 워프", code == 200 and json.loads(body)["ok"])
c = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
c.request("GET", "/state")
s = json.loads(c.getresponse().read())
check("/state 에 steam·warp", s["steam"]["offline"] is True and s["warp"]["last"] == "arrived at Undead Burg")
c.request("GET", "/bonfires")
check("/bonfires — 보내는 쪽이 없으면(캐릭터 모름) 빈 목록", json.loads(c.getresponse().read()) == [])
st.put({"type": "status", "t": time.time(), "game": "world", "menu": False, "away": None, "char": "Knight bot"})
c.request("GET", "/bonfires")
check("/bonfires — 지금 캐릭터의 목록", json.loads(c.getresponse().read()) == [{"id": 1012962, "name": "Undead Burg"}])
st.put({"type": "status", "t": time.time(), "game": "world", "menu": False, "away": None, "char": "NewGuy"})
c.request("GET", "/bonfires")
check("/bonfires — 새 캐릭터는 빈 목록", json.loads(c.getresponse().read()) == [])
srv.shutdown()

print("실패 0" if not fails else f"실패 {fails}")
sys.exit(1 if fails else 0)
