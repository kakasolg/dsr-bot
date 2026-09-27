"""radar offline test — sender → UDP → server → /state, with a fake feed. No game.

  python radar_test.py
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import radar
import radar_server as S
from telemetry import Chr, Snapshot


def free_port(kind) -> int:
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


def state(http):
    with urllib.request.urlopen(f"http://127.0.0.1:{http}/state", timeout=2) as r:
        return json.loads(r.read())


udp, http = free_port(socket.SOCK_DGRAM), free_port(socket.SOCK_STREAM)
st = S.State()
threading.Thread(target=S.udp_loop, args=(st, udp), daemon=True).start()
srv = ThreadingHTTPServer(("127.0.0.1", http), S.make_handler(st))
threading.Thread(target=srv.serve_forever, daemon=True).start()
time.sleep(0.2)

print("서버")
check("데이터 없으면 snap None", state(http)["snap"] is None)
with urllib.request.urlopen(f"http://127.0.0.1:{http}/", timeout=2) as r:
    check("페이지 제공", b"DSR" in r.read())


class FakeFeed:
    def __init__(self):
        self.listeners = []


p = Chr(ptr=1, npc_param=0, team=1, hp=500, max_hp=600, x=1.0, y=0.0, z=2.0, heading=0.5)
e = Chr(ptr=2, npc_param=225000, team=6, hp=100, max_hp=200, x=5.0, y=0.0, z=2.0, dist=4.0, anim=3004, name="망자")
snap = Snapshot(t=time.time(), player=p, chars=[e], cam_yaw=1.0)

print("보내기")
feed = FakeFeed()
r = radar.Radar(port=udp).attach(feed)
check("피드 구독", feed.listeners == [r.snapshot])
feed.listeners[0](snap)
r.say("교전: 망자 (4.0 m)")
time.sleep(0.3)
s = state(http)
check("스냅샷 도착", s["snap"] and s["snap"]["player"]["hp"] == 500 and s["snap"]["chars"][0]["anim"] == 3004)
check("판단 한 줄 도착", s["says"] and s["says"][-1]["line"] == "교전: 망자 (4.0 m)")
r.snapshot(snap)
before = r._last
r.snapshot(snap)
check("RATE_HZ 제한 (바로 다음 프레임은 버림)", r._last == before)

print("안전")
r.snapshot(None)
dead = radar.Radar(port=free_port(socket.SOCK_DGRAM))
dead.say("서버 없음")
dead.snapshot(snap)
check("서버 없어도 예외 없음", True)


class NoFeed:
    def __init__(self):
        self.n = 0

    def snapshot(self, within=60.0):
        self.n += 1
        raise RuntimeError("읽기 실패")


nf = NoFeed()
radar.Radar(port=udp).attach(nf)
time.sleep(0.35)
check("피드 없으면 폴링 스레드, 읽기 실패해도 계속", nf.n >= 2)

srv.shutdown()
print("전부 통과" if not fails else f"실패 {fails}")
sys.exit(1 if fails else 0)
