"""불의 제전 화톳불 → 망자 상인 달리기, 여러 판. 싸우지 않고 **막무가내로 달린다** (사용자: "자꾸 하다 보면 뭐가 생긴다").

  python merchantrun.py [판 수]

한 판: 화톳불 휴식(HP·적 초기화) → 구역 경계까지 질주(m10_02 내비메시) → 상인까지 질주(m10_01) → 성공 판정
→ 화톳불로 질주 복귀(귀로는 적이 경계 상태라 따로 센다). 죽으면 화톳불에서 부활을 기다려 다음 판.

판마다 남긴다: 맞은 곳(피해·위치·시각), 죽은 곳, 떨어진 곳(2 s 안에 4 m), 걸린 시간.
쌓이면 "어디서 맞고 어디서 죽는지" 가 보인다 — 거기가 다음에 배울 곳이다.
결과: data/merchantrun.jsonl (한 판에 한 줄)

구역 경계는 사람이 걸어서 기록한 통과점 (data/routes/firelink-merchant-run.json) — 내비메시는 구역 안에서만 길을 찾는다.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import env
import farm
import nav
import navmesh
import patrol
import playbook as pbm
import quitout
import reflex

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "merchantrun.jsonl"
GLOG = ROOT / "data" / "merchantrun.log"      # 전투 판단 기록 (왜 못 잡는지 보려고)
ROUTE = json.loads((ROOT / "data" / "routes" / "firelink-merchant-run.json").read_text(encoding="utf-8"))
MAP_A, MAP_B = "m10_02_00_00", "m10_01_00_00"
BOUND_A = tuple(ROUTE["segments"][0]["points"][-1])     # 경계 직전 (불의 제전 쪽)
BOUND_B = tuple(ROUTE["segments"][1]["points"][0])      # 경계 직후 (성벽 마을 쪽)
MERCHANT = tuple(farm.SPOTS["undead-merchant"]["pos"])
BONFIRE = farm.SPOTS["firelink-bonfire"]
ARRIVE = 3.0
LEG_TIMEOUT = 180.0
ITEM_DARKSIGN = 117
ABORT_HP = 0.35        # 에스트가 없다 — 이 아래면 다크사인으로 돌아가 쉬고 다시 (다크사인이 곧 회복)
STALL_S = 25.0         # 이만큼 목표에 1.5 m 도 못 다가가면 "판단이 안 되는 상황" — 다크사인
TACTICS_F = ROOT / "data" / "merchant-tactics.json"
# 전술: 실패하면 다크사인으로 돌아가 **다른 전술**로 다시 한다 (사용자: "해결도 안 하고 멈추면 시간 낭비, 전술을 새로 짜서 다시")
TACTICS = {
    "fight":       {"desc": "폭탄 + 근접 (지금까지의 전투)", "pb": {}},
    "bomb_stop":   {"desc": "4~9.5 m 까지 다가가 멈춰 서서 폭탄, 4 m 안으로 오면 근접", "pb": {}},
    "bomb_sprint": {"desc": "달리다 사거리에 들면 폭탄만, 근접 안 함", "pb": {"attack_range": 0.0, "melee_proactive": False}},
    "sprint":      {"desc": "싸우지 않고 달린다", "pb": {}},
}
PB_DIR = ROOT / "data" / "playbook-merchant"
# 막무가내 질주는 경사로의 할로우 둘에게 길이 막혀 0.8 m 안에서 13대 맞고 죽었다 (1판 실측).
# 그래서 길을 막는 놈은 치우고 지나간다: 멀리서 파이어밤(할로우 HP 75 = 한 방, 9.4 m 까지 실측), 붙으면 막고 한 대.
# 할로우는 느려서 먼저 쳐도 된다(melee_proactive). 도망은 끈다(사용자: "도망친 게 실패").
PB_DEFAULTS = {"use_bombs": True, "bomb_min_dist": 4.0, "bomb_max_dist": 9.0, "bombs_per_episode": 8,
               "bomb_min_enemies": 1, "melee_proactive": True, "crowd_threshold": 5, "attack_range": 1.0,
               "hold_range": 1.6, "lock_range": 9.0, "mode_open": "sprint", "mode_near_enemy": "guard", "retreat_hp_pct": 0.0,
               "flask_hp_pct": 0.5}


class Runner:
    def __init__(self):
        self.tm = env.make_telemetry({})
        control.focus_game()
        self.pad = control.Pad()
        self.nm = {MAP_A: navmesh.Navmesh(MAP_A), MAP_B: navmesh.Navmesh(MAP_B)}
        pbm.set_dir(PB_DIR)
        if not (PB_DIR / "current.json").exists():
            base = pbm.Playbook()
            for k, v in PB_DEFAULTS.items():
                setattr(base, k, v)
            base.note = "상인 달리기: 길 막는 할로우는 폭탄·막고한대로 치우고 지나간다"
            pbm.save(base)
        self.pb = pbm.load_current()
        self.guard = None
        self.rfx = None
        self.tactic = "fight"
        pa = self.nm[MAP_A].find_path(tuple(BONFIRE["stand"]), BOUND_A)
        pbp = self.nm[MAP_B].find_path(BOUND_B, MERCHANT)

        def plen(pth):
            return sum(math.dist(pth[k], pth[k + 1]) for k in range(len(pth) - 1)) if pth else 150.0
        self.len_a, self.len_b = plen(pa), plen(pbp)

    def snap(self, r=20.0):
        return self.tm.snapshot(within=r)

    def leg(self, map_id: str, goal: tuple, st: dict, tag: str) -> str:
        """한 구간 질주 → 'ok' | 'dead' | 'stuck'"""
        s = self.snap(1.0)
        if not s or s.player.hp <= 0:
            return "dead"
        nm = self.nm[map_id]
        path = nm.find_path((s.player.x, s.player.y, s.player.z), goal)
        if not path:
            st["notes"].append(f"{tag}: 경로 없음 @({s.player.x:.1f},{s.player.y:.1f},{s.player.z:.1f})")
            return "stuck"
        t0, fails = time.time(), 0
        st["best_d"], st["best_t"] = None, time.time()

        def on_tick(sn, _d=None):
            p = sn.player
            here = (p.x, p.y, p.z)
            dg = math.dist(here, goal)
            if st["best_d"] is None or dg < st["best_d"] - 1.5:
                st["best_d"], st["best_t"] = dg, time.time()
            prog = st["leg_base"] + max(0.0, st["leg_len"] - dg)
            st["progress"] = max(st["progress"], prog / st["route_len"])
            if st["abort"] is None and p.hp > 0:
                if p.hp < p.max_hp * ABORT_HP:
                    st["abort"] = f"HP {p.hp}"
                elif time.time() - st["best_t"] > STALL_S:
                    st["abort"] = f"{STALL_S:.0f} s 동안 진전 없음 (남은 {dg:.0f} m)"
                elif st["fall"] is not None:
                    st["abort"] = f"추락 {st['fall']['drop']} m"
            if st["last_hp"] is not None and p.hp < st["last_hp"]:
                near = min(sn.hostile(12.0), key=lambda c: c.dist, default=None)
                st["hits"].append({"leg": tag, "dmg": st["last_hp"] - p.hp, "hp": p.hp,
                                   "pos": [round(p.x, 1), round(p.y, 1), round(p.z, 1)],
                                   "t": round(time.time() - st["t0"], 1),
                                   "by": near.npc_param if near else None, "dist": round(near.dist, 1) if near else None})
            st["last_hp"] = p.hp
            for c in sn.chars:                  # 처치·준 피해 — HP 가 줄면 준 피해, 0 이 되면 처치 (죽은 적은 팀 표시가 바뀌어 목록 방식은 0 으로 셌다)
                if c.max_hp <= 0 or c.dist > 25 or c.team != 6 and c.hp > 0:
                    continue
                prev = st["ehp"].get(c.ptr)
                if prev is not None and c.hp < prev:
                    st["dealt"] += prev - c.hp
                    if c.hp <= 0 < prev:
                        st["kills"] += 1
                st["ehp"][c.ptr] = c.hp
            if self.guard is not None:
                a = self.guard.tick(sn)
                if a in ("bomb",):
                    st["bombs"] += 1
                if a in ("attack", "counter", "combo"):
                    st["swings"] += 1
            if p.hp > 0:
                st["last_pos"] = [round(p.x, 1), round(p.y, 1), round(p.z, 1)]
            ys = st["ys"]
            ys.append((time.time(), p.y, p.x, p.z))
            while ys and time.time() - ys[0][0] > 2.0:
                ys.pop(0)
            top = max(ys, key=lambda v: v[1])
            if top[1] - p.y > 4.0 and st["fall"] is None:
                st["fall"] = {"leg": tag, "from": [round(top[2], 1), round(top[1], 1), round(top[3], 1)],
                              "drop": round(top[1] - p.y, 1),
                              "mode": self.guard.mode if self.guard else None,
                              "engaged": bool(self.guard and self.guard.engage is not None)}

        # 경로점을 못 가면 **지금 자리에서 다시 길을 찾는다**. 예전엔 다음 경로점으로 넘어갔는데, 싸우다 경로에서 밀려난 뒤엔
        # 원래 경로점들이 의미가 없어서 줄줄이 실패했다 (실측: 경사로 아래·위 두 층이 겹치는 곳에서 '막힘 4회').
        best, replans = None, 0
        while True:
            if time.time() - t0 > LEG_TIMEOUT:
                return "stuck"
            failed = False
            for q in path[1:]:
                if time.time() - t0 > LEG_TIMEOUT:
                    return "stuck"
                def mode_fn(_s):
                    if st["abort"]:
                        return "retreat"              # 포기 신호 → goto 가 곧바로 돌아온다
                    if self.guard and self.guard.mode == "retreat":
                        return "hold"                 # Guard 의 후퇴는 끔 — 그 자리에서 계속 싸운다
                    return self.mode(_s)
                r = nav.goto(self.tm, self.pad, q, tolerance=1.5, timeout=20, log=lambda *a: None,
                             on_tick=on_tick, mode_fn=mode_fn, terrain=nm,
                             engage_fn=lambda _s: self.guard.engage_pos() if self.guard else None)
                if st["abort"]:
                    return "abort"
                if r == "dead":
                    return "dead"
                if r in ("timeout", "unreachable", "lost", "stuck"):
                    failed = True
                    break
            s = self.snap(1.0)
            if not s or s.player.hp <= 0:
                return "dead"
            here = (s.player.x, s.player.y, s.player.z)
            d = math.dist(here, goal)
            if not failed or d < 6.0:
                break
            if best is None or d < best - 2.0:
                best, replans = d, 0                 # 가까워지고 있으면 다시 센다
            else:
                replans += 1
                if replans >= 4:
                    st["notes"].append(f"{tag}: 다시 찾아도 못 감 {replans}회 @({here[0]:.1f},{here[1]:.1f},{here[2]:.1f}) 남은 {d:.0f} m")
                    return "stuck"
            path = nm.find_path(here, goal)
            if not path:
                st["notes"].append(f"{tag}: 경로 없음 @({here[0]:.1f},{here[1]:.1f},{here[2]:.1f})")
                return "stuck"
        s = self.snap(1.0)
        if not s or s.player.hp <= 0:
            return "dead"
        return "ok" if math.dist((s.player.x, s.player.y, s.player.z), goal) < 6.0 else "stuck"

    def mode(self, s) -> str:
        """전술별 이동. 적이 없으면 질주."""
        g = self.guard
        if g is None or self.tactic == "sprint":
            return "sprint"
        near = sorted((c for c in s.hostile(15.0) if c.hp > 0 and not patrol.dormant(c) and abs(c.y - s.player.y) < 4),
                      key=lambda c: c.dist)
        if not near and g.engage is None:
            return "sprint"
        gm = g.mode if g.mode != "retreat" else "hold"
        d = near[0].dist if near else 99.0
        bombs_left = g.bombs_thrown < getattr(g.pb, "bombs_per_episode", 0)
        if self.tactic == "bomb_stop" and bombs_left:
            if d < 4.0:
                return gm                     # 붙었다 — 근접
            if d <= 9.5:
                return "hold"                 # 폭탄 사거리 — 서서 던진다 (가드 든 채)
            return "creep"                    # 사거리 밖 — 천천히 다가간다
        if self.tactic == "bomb_sprint":
            if g.bomb_step in (1, 2) and 4.0 <= d <= 9.5:
                return "hold"                 # 폭탄을 들고 사거리 안 — 잠깐 서서 던진다
            return "sprint"
        return gm

    def wait_respawn(self, timeout=40.0) -> bool:
        t = time.time()
        while time.time() - t < timeout:
            try:
                s = self.tm.snapshot(within=1.0)
            except Exception:
                s = None
            if s and s.player.hp > 0 and s.player.hp == s.player.max_hp:
                time.sleep(2.0)
                return True
            time.sleep(0.5)
            try:
                self.tm = env.make_telemetry({})
            except Exception:
                pass
        return False

    def _dead_count(self) -> int:
        s = self.tm.snapshot(within=400.0)
        return sum(1 for c in (s.chars if s else []) if c.max_hp > 0 and c.hp <= 0 and c.team == 6)

    def rest(self) -> bool:
        for attempt in range(2):
            if farm.rest(self.tm, self.pad, self.nm[MAP_A], BONFIRE):
                return True
            self.pad.reconnect()
            control.focus_game()
        return False

    def darksign(self, tries: int = 3) -> bool:
        """다크사인으로 화톳불 복귀. 칸(117)·확인창 글자·YES 칸을 **확인한 뒤에만** 누른다 (기본값이 YES)."""
        for _ in range(tries):
            self.pad.guard(False)
            self.pad.neutral()
            quitout.close_menu(self.tm, self.pad)
            t0 = time.time()
            while self.tm.selected_item() != ITEM_DARKSIGN and time.time() - t0 < 3.0:
                self.pad.item_next()
                t1 = time.time()
                while time.time() - t1 < 0.35:
                    self.pad.release_due()
                    time.sleep(0.01)
            if self.tm.selected_item() != ITEM_DARKSIGN:
                continue
            quitout._press(self.pad, quitout.B.XUSB_GAMEPAD_X, 0.0)
            ok = quitout._wait(lambda: quitout._is_screen("darksign_q") is True
                               and quitout._is_screen("darksign_yes") is True, 1.5)
            if not ok:
                quitout._press(self.pad, quitout.B.XUSB_GAMEPAD_B, 0.4)   # 창이 아니면 닫고 다시 (맞아서 끊겼을 수도)
                continue
            quitout._press(self.pad, quitout.B.XUSB_GAMEPAD_A, 0.0)
            t2 = time.time()
            while time.time() - t2 < 15.0:
                try:
                    s = self.tm.snapshot(within=1.0)
                except Exception:
                    s = None
                if s and s.player.hp > 0 and math.dist((s.player.x, s.player.y, s.player.z), tuple(BONFIRE["stand"])) < 8.0:
                    time.sleep(1.5)
                    return True
                time.sleep(0.2)
                try:
                    self.tm = env.make_telemetry({})
                except Exception:
                    pass
        return False

    def pick_tactic(self) -> str:
        """안 해 본 전술 먼저, 그다음엔 성공·진행도가 가장 좋은 전술 (20 % 는 다른 것도 시험)."""
        import random
        stats = json.loads(TACTICS_F.read_text(encoding="utf-8")) if TACTICS_F.exists() else {}
        untried = [k for k in TACTICS if stats.get(k, {}).get("n", 0) == 0]
        if untried:
            return untried[0]
        if random.random() < 0.2:
            return random.choice(list(TACTICS))
        return max(TACTICS, key=lambda k: (stats[k]["succ"] / stats[k]["n"]) * 2 + stats[k]["prog"] / stats[k]["n"])

    def record_tactic(self, name: str, success: bool, progress: float) -> None:
        stats = json.loads(TACTICS_F.read_text(encoding="utf-8")) if TACTICS_F.exists() else {}
        s = stats.setdefault(name, {"n": 0, "succ": 0, "prog": 0.0})
        s["n"] += 1
        s["succ"] += int(success)
        s["prog"] = round(s["prog"] + progress, 3)
        TACTICS_F.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")

    def episode(self, i: int) -> dict:
        import dataclasses
        self.tactic = self.pick_tactic()
        pb = dataclasses.replace(self.pb, **TACTICS[self.tactic]["pb"])
        st = {"ep": i, "t0": time.time(), "hits": [], "fall": None, "notes": [], "last_hp": None, "last_pos": None, "ys": [],
              "bombs": 0, "kills": 0, "dealt": 0, "swings": 0, "ehp": {}, "abort": None, "progress": 0.0,
              "route_len": self.len_a + self.len_b, "leg_base": 0.0, "leg_len": self.len_a,
              "best_d": None, "best_t": time.time()}
        if not self.rest():
            return {"ep": i, "error": "rest_failed"}
        st["t0"] = time.time()
        st["last_hp"] = None
        self.rfx = reflex.Reflex(self.tm, self.pad)
        self.rfx.start()
        glog = GLOG.open("a", encoding="utf-8")
        glog.write(f"\n=== {i}판 [{self.tactic}] {time.strftime('%H:%M:%S')} ===\n")
        t_ep = time.time()

        def gl(*a):
            glog.write(f"{time.time() - t_ep:6.1f} {' '.join(str(x) for x in a)}\n")
            glog.flush()
        self.guard = patrol.Guard(self.pad, pb, log=gl, item_fn=getattr(self.tm, "selected_item", None), reflex=self.rfx)
        self.guard.has_estus = any(patrol.is_estus(x) for x in self.tm.quick_items())
        out = self.leg(MAP_A, BOUND_A, st, "out-A")
        if out == "ok":
            nav.goto(self.tm, self.pad, BOUND_B, tolerance=1.2, timeout=8, log=lambda *a: None, mode_fn=lambda _s: "sprint")
            st["leg_base"], st["leg_len"] = self.len_a, self.len_b
            out = self.leg(MAP_B, MERCHANT, st, "out-B")
        s = self.snap(1.0)
        alive = bool(s and s.player.hp > 0)
        reached = alive and math.dist((s.player.x, s.player.y, s.player.z), MERCHANT) < ARRIVE + 3
        if reached:
            st["progress"] = 1.0
        t_out = round(time.time() - st["t0"], 1)
        hp_out = s.player.hp if alive else 0
        self.rfx.stop()
        self.rfx.join(1.0)
        self.guard, self.rfx = None, None
        # 돌아가기: 죽었으면 부활을 기다리고, 살아 있으면(도착했든 포기했든) 다크사인
        if not alive or out == "dead":
            st["death_at"] = st["last_pos"]
            self.wait_respawn()
            back = "respawn"
        else:
            back = "darksign" if self.darksign() else "darksign_failed"
        glog.write(f"  결과: {'도착' if reached else out} {st['abort'] or ''}  진행 {st['progress']:.0%}  복귀 {back}\n")
        glog.close()
        self.record_tactic(self.tactic, reached, st["progress"])
        return {"ep": i, "tactic": self.tactic, "success": reached, "outbound": out, "abort": st["abort"],
                "progress": round(st["progress"], 3), "back": back,
                "bombs": st["bombs"], "kills": st["kills"], "dealt": st["dealt"], "swings": st["swings"],
                "seconds": t_out, "hp_left": hp_out, "hp_lost": sum(h["dmg"] for h in st["hits"]),
                "hits": st["hits"], "fall": st["fall"], "death_at": st.get("death_at"), "notes": st["notes"], "t": time.time()}


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    run = Runner()
    wins = 0
    print(f"상인 달리기 {n}판 — 경계 {BOUND_A}→{BOUND_B}, 상인 {MERCHANT}", flush=True)
    for i in range(1, n + 1):
        r = run.episode(i)
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        if r.get("error"):
            print(f"── {i}: {r['error']} — 중단", flush=True)
            break
        wins += bool(r["success"])
        print(f"── {i}/{n} [{r['tactic']}]: {'✔ 도착' if r['success'] else '✖ ' + str(r['outbound'])}"
              f"{' (' + r['abort'] + ')' if r['abort'] else ''}  진행 {r['progress']:.0%}  {r['seconds']}s  "
              f"잃은HP {r['hp_lost']}  폭탄 {r['bombs']}  휘두름 {r['swings']}  처치 {r['kills']}  "
              f"{'사망 ' + str(r['death_at']) + '  ' if r['death_at'] else ''}복귀 {r['back']}  누적 {wins}/{i} ({wins / i:.0%})",
              flush=True)
        for note in r["notes"]:
            print(f"     · {note}", flush=True)


if __name__ == "__main__":
    main()
