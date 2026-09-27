"""radar offline test — sender → UDP → server → /state, with a fake feed. No game.

  python radar_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

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
check("판단 한 줄 도착 (영어로 번역)", s["says"] and s["says"][-1]["line"] == "fight: Hollow (4.0 m)")
r.snapshot(snap)
before = r._last
r.snapshot(snap)
check("RATE_HZ 제한 (바로 다음 프레임은 버림)", r._last == before)

print("목표·경로·지킬 자리")
mv = type("Mv", (), {})()
mv.cam_target, mv.show_path, mv.show_spot = 2, ("경사로", [(float(i), 0.0, 0.0) for i in range(500)]), ("대기", (3.0, 0.0, 4.0), time.time())
r.follow(mv)
r._last = 0
r.snapshot(snap)
time.sleep(0.3)
s = state(http)["snap"]
check("목표 ptr", s.get("target") == 2)
check("경로: 줄여서 보내고 끝점은 유지", s.get("path_tag") == "ramp" and len(s["path"]) <= radar.MAX_PATH + 1 and s["path"][-1] == [499.0, 0.0, 0.0])
check("지킬 자리", s.get("spot") == [3.0, 0.0, 4.0] and s.get("spot_tag") == "대기")
mv.show_spot = ("대기", (3.0, 0.0, 4.0), time.time() - 10)
mv.cam_target, mv.show_path = None, None
check("오래된 자리·빈 목표·빈 경로는 안 보냄", radar.intent_dict(mv) == {})
check("속성 없는 mv 도 괜찮음", radar.intent_dict(object()) == {})

mv.show_smash = ("o1130_12", (1.0, 0.0, 1.0), time.time())
check("부숨 시도한 물건 이름", radar.intent_dict(mv).get("smash") == "o1130_12")
mv.show_smash = ("o1130_12", (1.0, 0.0, 1.0), time.time() - 60)
check("오래된 부숨은 안 보냄", "smash" not in radar.intent_dict(mv))

print("부서지는 물건 (서버)")
ps = S.State(props=[[1.0, 0.0, 2.0, False, "near"], [100.0, 0.0, 0.0, False, "far"], [1.0, -20.0, 2.0, False, "below"]])
check("스냅샷 없으면 props 없음", "props" not in ps.get())
ps.put({"type": "snap", "player": {"x": 0.0, "y": 0.0, "z": 0.0}, "chars": []})
check("플레이어 근처·같은 높이만", [o[4] for o in ps.get()["props"]] == ["near"])
allp = S.load_props()
check(f"data/gamefiles 에서 읽음 ({len(allp)}개, 강공 {sum(1 for o in allp if o[3])})", len(allp) >= 400 and any(o[4] == "o1130_12" for o in allp))

print("아이템 (소울·인간성·쐐기석)")
it = S.State(props=[], items=[[1.0, 0.0, 2.0, "soul", "Soul of a Lost Undead", [11]], [2.0, 0.0, 1.0, "humanity", "Humanity", [12, 13]],
                              [90.0, 0.0, 0.0, "titanite", "far", [14]], [1.0, 30.0, 1.0, "soul", "high above", [15]]])
it.put({"type": "snap", "player": {"x": 0.0, "y": 0.0, "z": 0.0}, "chars": []})
check("근처·높이 안의 것만", [o[4] for o in it.get()["items"]] == ["Soul of a Lost Undead", "Humanity"])
it.put({"type": "picked", "flags": [13]})
check("주운 것(플래그 하나라도)은 뺌", [o[4] for o in it.get()["items"]] == ["Soul of a Lost Undead"])


class FlagTm:
    def __init__(self, on):
        self.on, self.reads = set(on), []

    def event_flag(self, f):
        self.reads.append(f)
        return f in self.on


rr = radar.Radar(port=udp)
tr = [(1.0, 0.0, 2.0, (11,)), (2.0, 0.0, 1.0, (12, 13)), (90.0, 0.0, 0.0, (14,))]
ftm = FlagTm({13})
check("플레이어 위치 모르면 안 읽음", rr.check_items(ftm, tr) == ([], []) and ftm.reads == [])
rr.player = (0.0, 0.0, 0.0)
check("근처 것만 읽고 켜진 플래그 보냄", rr.check_items(ftm, tr) == ([13], []) and 14 not in ftm.reads)
check("바뀐 것 없으면 안 보냄", rr.check_items(ftm, tr) == ([], []))
ftm.on = set()
check("세이브를 되돌려 플래그가 꺼지면 unpicked (P-9)", rr.check_items(ftm, tr) == ([], [13]) and 13 not in rr.picked)
ftm.on = {13}
ftm.event_flag = lambda f: None
check("못 읽으면(로딩) 아는 것 유지", rr.check_items(ftm, tr) == ([], []))
del ftm.event_flag
rr.check_items(ftm, tr)
time.sleep(0.3)
st.put({"type": "snap", "player": {"x": 0.0, "y": 0.0, "z": 0.0}, "chars": []})
check("서버가 picked 받음", 13 in st.picked)
it.put({"type": "unpicked", "flags": [13]})
check("서버가 unpicked 받으면 다시 보임", [o[4] for o in it.get()["items"]] == ["Soul of a Lost Undead", "Humanity"])
check(f"data/gamefiles 에서 읽음 (아이템 {len(S.load_items())}, 플래그 있는 것 {len(radar.load_treasures())})", True)

print("field.walk 가 경로를 걸고 푼다 (돌아가기 중첩 포함)")
from souls import field as F


class W:
    def __init__(self):
        self.mv = type("Mv", (), {"show_path": None})()
        self.seen = []

    def _walk(self, path, nm, tag, *a):
        self.seen.append(self.mv.show_path[0])
        if tag == "밖":
            F.Field.walk(self, [(9, 0, 9)], nm, "돌아서")
            self.seen.append(self.mv.show_path[0])
        return "arrived"


w = W()
F.Field.walk(w, [(0, 0, 0), (1, 0, 1)], None, "밖")
check("안쪽 경로 → 끝나면 바깥 경로로 복귀 → 끝나면 비움", w.seen == ["밖", "돌아서", "밖"] and w.mv.show_path is None)

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
