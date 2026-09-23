"""
적마다 정해 둔 공략으로 경사로 무리를 하나씩 치운다 — 먼저 "모를 때 폭탄" 을 시험한다.

  python hunt.py [시도 수] [--throw 10] [--targets 1,2,3]

사용자: "몹의 위치가 고정이고 패턴도 일정하다 — 제대로 접근하면 해결 가능", "네가 감독하고 3.8 Flash 로 이미지 판독시켜 성공 확률을 올려봐".
적 지도(enemy_map.py, 화톳불 휴식 직후 스폰 자리)의 순서대로:
  1) 경로를 천천히 걸어 그 적 스폰에서 --throw m 떨어진 경로점에 선다 (적 25 m 안부터는 creep)
  2) 카메라 정렬, 메모리로 '준비' 확인 (스폰에서 1 m 안, 최근 4 s 몸 15° 미만 돎), 3.8 Flash 판독은 **기록만** (믿을지는 결과와 비교해 정한다)
  3) 파이어밤 칸 확인 → 락온(R3) → 던지기(X) → 4 s 동안 그 적 HP 로 결과: 처치 / 명중 / 빗나감
  4) 잡았으면 다음 적, 살아서 알아챘으면 화톳불로 돌아가 초기화하고 다음 시도
결과: data/hunt.jsonl (던질 때마다 한 줄)
"""
from __future__ import annotations

import json
import math
import sys
import threading
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import control
import merchantrun as mr
import nav
import patrol
import tactic_llm
import vision_probe as vp

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "hunt.jsonl"
MAP = json.loads((ROOT / "data" / "enemy-map.json").read_text(encoding="utf-8"))["enemies"]
ITEM_BOMB = 292
JUDGE_MODEL = "gemini-3.8-flash"


class Hunter(vp.Probe):
    def find(self, spawn, s=None, r=3.0):
        """스폰 자리 근처(r m)의 살아 있는 적 — 포인터는 휴식마다 바뀌어서 위치로 찾는다."""
        s = s or self.tm.snapshot(within=40.0)
        if not s:
            return None, None
        c = min((c for c in s.hostile(250.0) if c.hp > 0), key=lambda c: math.dist((c.x, c.y, c.z), spawn), default=None)   # 화톳불에서도 지도 적을 잡도록 넓게
        return (c, s) if c is not None and math.dist((c.x, c.y, c.z), spawn) < r else (None, s)

    def judge(self, b64, dist) -> dict:
        pick, ms, extra = tactic_llm.gemini_choice(JUDGE_MODEL, "You judge enemy awareness in a game screenshot.",
                                                   vp.PROMPT.format(d=dist), vp.STATES, timeout=30.0, retry_429=1, image_jpeg_b64=b64)
        return {"state": pick, "ms": round(ms), **({"error": extra["error"][:100]} if extra.get("error") else {})}

    def select_bomb(self) -> bool:
        t0 = time.time()
        while self.tm.selected_item() != ITEM_BOMB and time.time() - t0 < 3.0:
            self.pad.item_next()
            t1 = time.time()
            while time.time() - t1 < 0.35:
                self.pad.release_due()
                time.sleep(0.01)
        return self.tm.selected_item() == ITEM_BOMB

    def throw_at(self, ptr, locked_already: bool = False, release_if_alive: bool = True) -> dict:
        """락온 → 던지기 → 4 s 동안 대상 HP·애니. 락온은 대상이 살아 있을 때만 풀어 준다 (죽으면 게임이 푼다)."""
        s0 = self.tm.snapshot(within=40.0)
        c0 = next((c for c in s0.hostile(40.0) if c.ptr == ptr), None) if s0 else None
        hp0 = c0.hp if c0 else None
        if not locked_already:
            self.pad.lock_on()
            t = time.time()
            while time.time() - t < 0.35:
                self.pad.release_due()
                time.sleep(0.01)
        shots = [("락온", self._shot())]           # 락온 표시가 대상에 있나 — 두 번 빗나가서 확인한다
        # 락온하면 카메라가 그 대상에 고정된다 → 카메라 정면에 가장 가까운 적 = 락온 대상. 노린 놈이 아니면 풀고 안 던진다.
        # (실측: 2번(255010)을 노렸는데 옆의 3번이 다가와 화면 가운데에 가까워서 그놈이 잡혔다 — 폭탄은 엉뚱한 놈에게)
        sl = self.tm.snapshot(within=20.0)
        if sl and sl.cam_yaw is not None:
            cand = [c for c in sl.hostile(20.0) if c.hp > 0]
            locked = min(cand, key=lambda c: abs(vp.rel_to_camera(sl, c)), default=None)
            if locked is not None and locked.ptr != ptr:
                self.pad.lock_on()      # 풀기
                time.sleep(0.1)
                self.pad.release_due()
                return {"hp0": hp0, "hp_after": hp0, "result": "락온 대상 다름", "locked_npc": locked.npc_param,
                        "locked_dist": round(locked.dist, 1), "anims_after": [], "shots": []}
        self.pad.use_item()
        t_throw = time.time()
        anims, hp_min = [], hp0
        want = [1.5, 2.0, 2.5]
        # 누르고 ~1.2 s 뒤에 손을 떠나고 10 m 를 날아간다 — 2.2 s 로 끊었더니 떨어지기 전에 '빗나감' 으로 판정했다 (락온은 걸려 있었다)
        while time.time() - t_throw < 4.0:
            if want and time.time() - t_throw >= want[0]:
                shots.append((f"+{want.pop(0)}s", self._shot()))
            self.pad.release_due()
            s = self.tm.snapshot(within=40.0)
            c = next((c for c in s.hostile(40.0) if c.ptr == ptr), None) if s else None
            if c is not None:
                hp_min = min(hp_min, c.hp) if hp_min is not None else c.hp
                if not anims or anims[-1] != c.anim:
                    anims.append(c.anim)
            else:
                hp_min = 0 if hp_min is not None else None   # 목록에서 빠졌다 = 죽음
            time.sleep(0.05)
        alive = hp_min is not None and hp_min > 0
        if alive and release_if_alive:
            self.pad.lock_on()          # 풀기
            time.sleep(0.1)
            self.pad.release_due()
        res = "처치" if not alive else ("명중" if hp0 is not None and hp_min < hp0 else "빗나감")
        tag = time.strftime("%H%M%S")
        names = []
        for label, im in shots:
            if im is not None:
                nm_ = f"throw_{tag}_{label.replace('+', 'p')}.jpg"
                im.save(vp.IMG_DIR / nm_, quality=80)
                names.append(nm_)
        return {"hp0": hp0, "hp_after": hp_min, "result": res, "anims_after": anims[:10], "shots": names}

    def _shot(self):
        from PIL import ImageGrab
        rc = vp.window_rect()
        if not rc:
            return None
        img = ImageGrab.grab(bbox=rc, all_screens=True)
        return img.resize((800, round(img.size[1] * 800 / img.size[0])))

    def standpoint(self, path, spawn, dist):
        """경로를 따라가다 처음으로 스폰까지 dist m 안에 드는 점 (그 앞 점과 사이를 보간)."""
        for i in range(1, len(path)):
            if math.dist(path[i], spawn) <= dist:
                a, b = path[i - 1], path[i]
                da, db = math.dist(a, spawn), math.dist(b, spawn)
                f = 0.0 if da <= db else min(1.0, (da - dist) / max(1e-6, da - db))
                return i, tuple(a[k] + (b[k] - a[k]) * f for k in range(3))
        return None, None

    def hunt(self, k: int, targets: list[int], dist: float) -> None:
        print(f"── 시도 {k}: 화톳불 휴식 (적 초기화)", flush=True)
        if not self.run.rest():
            self.pad.reconnect()          # 가상 패드를 게임이 놓칠 때가 있다 (휴식 실패 — 안내가 키보드 E 로 바뀜)
            control.focus_game()
            if not self.run.rest():
                print("   휴식 실패 — 중단", flush=True)
                return
        nm = self.run.nm[mr.MAP_A]
        self.run.cur_nm = nm
        self.hist.clear()
        self.last_kill_pos = None
        # 쉰 직후 = 전부 스폰 자리. 포인터를 잡아 두면 스폰을 떠나도 따라갈 수 있다 (3번은 1번이 죽으면 자리를 뜬다)
        s0 = self.tm.snapshot(within=200.0)
        self.ptr_of = {}
        for i, e in enumerate(MAP, 1):
            c0, _ = self.find(tuple(e["pos"]), s0, r=1.5)
            if c0 is not None:
                self.ptr_of[i] = c0.ptr
        for ti in targets:
            e = MAP[ti - 1]
            spawn = tuple(e["pos"])
            s = self.tm.snapshot(within=1.0)
            path = nm.find_path((s.player.x, s.player.y, s.player.z), mr.BOUND_A)
            idx, stand = self.standpoint(path, spawn, dist)
            if stand is None:
                print(f"   #{ti}: 경로에서 {dist} m 안에 드는 점 없음 — 건너뜀", flush=True)
                continue
            near = {"v": False}

            def on_tick(sn, _d=None):
                self.note(sn)
                near["v"] = any(c.hp > 0 and not patrol.dormant(c) for c in sn.hostile(25.0))
            plan = self.plans.get(ti, "sneak")
            tptr = self.ptr_of.get(ti)
            left = {"v": False}

            def mode_fn(_s):
                if plan in ("bait", "melee") and tptr is not None:
                    tc = next((x for x in _s.chars if x.ptr == tptr), None)
                    if tc is not None and math.dist((tc.x, tc.y, tc.z), spawn) > 1.0:
                        left["v"] = True
                        return "retreat"                    # 알아채고 스폰을 떠났다 → 멈춰서 맞이한다
                return "creep" if near["v"] else "walk"
            for q in path[1:idx] + [stand]:
                r = nav.goto(self.tm, self.pad, q, tolerance=0.8 if q == stand else 1.5, timeout=20, log=lambda *a: None,
                             on_tick=on_tick, mode_fn=mode_fn, terrain=nm)
                if r == "dead":
                    print("   사망", flush=True)
                    return
                if left["v"]:
                    break
            self.pad.neutral()
            time.sleep(0.3)
            if plan == "bait":
                if not self.bait(k, ti, e, tptr):
                    return
                continue
            if plan == "melee":
                # 알아채고 스폰을 떠났으면 앞 적을 잡은 평평한 자리로 물러나 거기서 맞이한다 (사용자: 원하는 지형까지 끌고 가기).
                # 경사로 한가운데서 3번과 싸우다 2.2 m 아래 놈에게 강공이 헛돌고 325 맞았다.
                if not self.melee(k, ti, e, tptr, nm, pull_to=self.last_kill_pos if left["v"] else None):
                    return
                continue
            c, s = self.find(spawn)
            if c is None:
                print(f"   #{ti} {e['npc']}: 스폰 자리에 없음 (이미 움직였거나 죽음)", flush=True)
                self._record(k, ti, e, None, None, {}, {"result": "스폰에 없음"})
                return
            self.align(c.ptr)
            c, s = self.find(spawn)
            if c is None:
                print(f"   #{ti}: 정렬 중에 움직였다 — 알아챔", flush=True)
                self._record(k, ti, e, None, None, {}, {"result": "정렬 중 움직임"})
                return
            trk = self.tracking(c.ptr, time.time())
            mem_state = "준비" if (trk["turned_deg"] or 0) < 15 else "경계"
            img, b64, full = vp.capture_crop(self.tm, c)
            name = f"hunt_{time.strftime('%H%M%S')}_{k}_{ti}_{c.dist:.0f}m.jpg"
            if img is not None:
                img.save(vp.IMG_DIR / name, quality=85)
                full.save(vp.IMG_DIR / name.replace(".jpg", "_full.jpg"), quality=80)
            # 판독은 기록용이라 던진 뒤에 받는다 — 먼저 기다리면 2~4 s 를 적 앞에 서 있게 된다
            jd: dict = {}
            jt = threading.Thread(target=lambda: jd.update(self.judge(b64, c.dist)), daemon=True) if b64 else None
            if jt:
                jt.start()
            if not self.select_bomb():
                print("   파이어밤 칸을 못 고름 — 중단", flush=True)
                return
            c2, _ = self.find(spawn)
            if c2 is None:
                print(f"   #{ti}: 폭탄 고르는 동안 움직였다 — 알아챔", flush=True)
                self._record(k, ti, e, c, trk, jd, {"result": "판독 중 움직임", "mem_state": mem_state}, name)
                return
            res = self.throw_at(c2.ptr)
            res["mem_state"] = mem_state
            if jt:
                jt.join(30)
            self._record(k, ti, e, c2, trk, jd, res, name)
            print(f"   #{ti} {e['npc']} {c2.dist:.1f} m 보는 각 {vp.facing_player(c2, s.player):.0f}° 몸 {trk['turned_deg']}° 돎 → 메모리 {mem_state}, "
                  f"3.8 {jd.get('state')}({jd.get('ms')} ms) | 폭탄 {res['result']} (HP {res['hp0']}→{res['hp_after']}) 애니 {res['anims_after'][:5]}  [{name}]",
                  flush=True)
            if res["result"] != "처치":
                print("   못 잡음 — 화톳불로", flush=True)
                return
            sk = self.tm.snapshot(within=1.0)
            if sk:
                self.last_kill_pos = (sk.player.x, sk.player.y, sk.player.z)
            if self.observe_s > 0:
                self.observe(k, ti)
        print("   목표 전부 처치", flush=True)

    observe_s = 0.0
    plans: dict = {}

    def approach_speed(self, ptr) -> float:
        h = [x for x in self.hist.get(ptr, []) if time.time() - x[0] <= 0.6]
        if len(h) < 3 or h[-1][0] - h[0][0] < 0.2:
            return 0.0
        return (h[0][3] - h[-1][3]) / (h[-1][0] - h[0][0])

    def lock_verified(self, ptr) -> bool:
        """정렬 → 락온 → 카메라 정면에 가장 가까운 적이 그놈인지. 아니면 풀고 False."""
        self.align(ptr)
        self.pad.lock_on()
        t = time.time()
        while time.time() - t < 0.35:
            self.pad.release_due()
            time.sleep(0.01)
        sl = self.tm.snapshot(within=20.0)
        if sl and sl.cam_yaw is not None:
            cand = [c for c in sl.hostile(20.0) if c.hp > 0]
            locked = min(cand, key=lambda c: abs(vp.rel_to_camera(sl, c)), default=None)
            if locked is not None and locked.ptr == ptr:
                return True
        self.pad.lock_on()
        time.sleep(0.1)
        self.pad.release_due()
        return False

    last_kill_pos = None

    def melee(self, k: int, ti: int, e: dict, ptr, nm, pull_to=None) -> bool:
        """정면 돌파 — 사용자: "폭탄이 없으면 근접으로 정면 돌파, 캐릭터가 강해서 강공이 먹히면 한 방에 끝난다".
        같은 높이(높이차 0.8 m 미만)로 2 m 안이면 막고 → R2 강공 (적이 휘두르는 중엔 방패, 끝나면 스틱을 그놈 쪽으로 + R2).
        pull_to 가 있으면 먼저 그 평평한 자리로 물러나 기다린다. 다가가다 2 s 진전이 없으면(낙차·다른 층) 밀지 않고 기다리고,
        10 s 를 기다려도 안 오면 다시 다가간다. 내 HP 40 % 아래면 포기. 30 s 안에 못 끝내면 포기."""
        if ptr is None:
            print(f"   #{ti}: 포인터 없음", flush=True)
            return False
        t0 = time.time()
        swings, locked, hits = 0, False, []
        hp_start = None
        why = None
        last_anim, att_start, waits = None, 0.0, 0
        mode, wait_since, prog_pos, prog_t = "approach", 0.0, None, time.time()
        if pull_to is not None:
            print(f"      알아챘다 — 평평한 자리 {tuple(round(v, 1) for v in pull_to)} 로 물러나 맞이한다", flush=True)
            nav.goto(self.tm, self.pad, pull_to, tolerance=1.0, timeout=8, log=lambda *a: None, terrain=nm,
                     on_tick=lambda sn, _d=None: self.note(sn), mode_fn=lambda _s: "sprint")
            mode, wait_since = "wait", time.time()
        while time.time() - t0 < 30.0:
            s = self.tm.snapshot(within=30.0)
            if not s:
                time.sleep(0.05)
                continue
            self.note(s)
            p = s.player
            hp_start = hp_start or p.hp
            if p.hp <= 0:
                why = "사망"
                break
            if p.hp < p.max_hp * 0.4:
                why = f"내 HP {p.hp}"
                break
            c = next((x for x in s.chars if x.ptr == ptr), None)
            if c is None or c.hp <= 0:
                why = "처치"
                break
            if c.anim != last_anim:              # 공격 애니로 **바뀐** 순간 (번호는 끝나도 남는다 — reflex.ATTACK_WINDOW)
                if 3000 <= (c.anim or 0) < 3600:
                    att_start = time.time()
                last_anim = c.anim
            enemy_swinging = 3000 <= (c.anim or 0) < 3600 and time.time() - att_start < 1.3
            if time.time() - getattr(self, "_mdbg", 0) > 2.0:
                self._mdbg = time.time()
                print(f"      근접 +{time.time() - t0:4.1f}s: 거리 {c.dist:.1f} m (높이차 {c.y - p.y:+.1f}), 나 ({p.x:.1f},{p.y:.1f},{p.z:.1f}), "
                      f"적 ({c.x:.1f},{c.y:.1f},{c.z:.1f}) 애니 {c.anim}", flush=True)
            same_level = abs(c.y - p.y) < 0.8
            if c.dist > 2.0 or not same_level:
                if mode == "wait":
                    self.pad.move(0.0, 0.0)     # 방패 들고 제자리 — 오게 둔다
                    self.pad.guard(True)
                    if time.time() - wait_since > 10.0:
                        mode, prog_pos, prog_t = "approach", None, time.time()
                        self.pad.guard(False)
                    time.sleep(0.03)
                    continue
                if prog_pos is None or math.dist((p.x, p.z), prog_pos) > 0.5:
                    prog_pos, prog_t = (p.x, p.z), time.time()
                elif time.time() - prog_t > 2.0:
                    print(f"      2 s 진전 없음 (거리 {c.dist:.1f} m, 높이차 {c.y - p.y:+.1f}) — 밀지 않고 기다린다", flush=True)
                    mode, wait_since = "wait", time.time()
                    continue
                path = nm.find_path((p.x, p.y, p.z), (c.x, c.y, c.z))
                q = path[1] if path and len(path) > 1 else (c.x, c.y, c.z)
                d_now = c.dist
                nav.goto(self.tm, self.pad, q, tolerance=1.8 if len(path or []) <= 2 else 1.0, timeout=1.2, log=lambda *a: None,
                         on_tick=lambda sn, _d=None: self.note(sn), terrain=nm,
                         mode_fn=lambda _s: "creep" if d_now < 4.0 else "walk")
                continue
            # 막고 → 한 대 (사용자 원칙): 적이 휘두르는 중(공격 애니 시작 뒤 1.3 s)이면 방패만 든다. 그 사이에 R2 를 누르면
            # 우리 공격이 나가기 전에 맞아서 끊긴다 — 첫 근접에서 강공 4번 중 3번이 0 피해, 그동안 421 맞았다 (적 애니 3003·3006 중에 휘두름).
            if enemy_swinging:
                self.pad.move(0.0, 0.0)
                self.pad.guard(True)
                waits += 1
                time.sleep(0.03)
                continue
            self.pad.guard(False)
            self.pad.neutral()
            # 락온 없이 겨눈다 — 붙은 적에게 정렬·락온 확인은 너무 느렸다 (1번이 2.4 s 만에 0.9 m 로 붙어 치는 동안 락온 확인 중 90 맞음).
            # 공격을 누르는 순간의 스틱 방향으로 몸이 틀어진다.
            if s.cam_yaw is None:
                time.sleep(0.05)
                continue
            st_ = control.world_to_stick(c.x - p.x, c.z - p.z, s.cam_yaw, nav.YAW_OFFSET, nav.FLIP_X)
            hp_before = c.hp
            self.pad.heavy(stick=st_)
            swings += 1
            t1 = time.time()
            hp_min = hp_before
            while time.time() - t1 < 1.3:
                s2 = self.tm.snapshot(within=10.0)
                c2 = next((x for x in s2.chars if x.ptr == ptr), None) if s2 else None
                hp_min = 0 if c2 is None else min(hp_min, c2.hp)
                self.pad.release_due()
                time.sleep(0.03)
            hits.append(hp_before - hp_min)
            if hp_min <= 0:
                why = "처치"
                break
            if swings >= 4:
                why = "4번 쳐도 안 죽음"
                break
        if why == "처치":
            sk = self.tm.snapshot(within=1.0)
            if sk:
                self.last_kill_pos = (sk.player.x, sk.player.y, sk.player.z)   # 다음 적을 끌어올 평평한 자리
        self.pad.guard(False)
        self.pad.neutral()
        s = self.tm.snapshot(within=5.0)
        res = {"plan": "melee", "result": why or "시간 초과", "swings": swings, "dmg_per_swing": hits, "guard_ticks": waits,
               "my_hp_lost": (hp_start - s.player.hp) if (s and hp_start) else None}
        self._record(k, ti, e, None, None, {}, res)
        print(f"   #{ti} {e['npc']} 근접: {res['result']} — 강공 {swings}번, 피해 {hits}, 내가 잃은 HP {res['my_hp_lost']}", flush=True)
        if why != "처치":
            if locked:
                self.pad.lock_on()
                time.sleep(0.1)
                self.pad.release_due()
            return False
        return True

    def bait(self, k: int, ti: int, e: dict, ptr) -> bool:
        """알아채고 오게 둔다 — 폭탄을 고르고, 스폰을 떠난 그놈에 **먼저** 정렬·락온(확인)해 둔 채 방패를 들고 기다리다,
        초속 1 m 넘게 달려들며 4.5~8 m 에 들면(공격 단계) 던진다. 누르고 ~1.2 s 뒤에 손을 떠나므로 초속 3 m 로 오는 놈은
        7 m 쯤에서 눌러야 3~4 m 에서 맞는다 (처음엔 3~6 m 에서 눌러 1.2~1.4 m 에서 던졌고 빗나갔다).
        3 m 안까지 붙으면 폭탄은 포기 (기록만). 15 s 안에 안 오면 포기."""
        if ptr is None:
            print(f"   #{ti}: 포인터 없음", flush=True)
            return False
        if not self.select_bomb():
            print("   파이어밤 칸을 못 고름", flush=True)
            return False
        locked = self.lock_verified(ptr) or self.lock_verified(ptr)
        if not locked:
            print(f"   #{ti}: 락온이 그놈에 안 걸림 (두 번)", flush=True)
            self._record(k, ti, e, None, None, {}, {"result": "락온 실패", "plan": "bait"})
            return False
        self.pad.guard(True)
        t0 = time.time()
        why, c = None, None
        while time.time() - t0 < 15.0:
            s = self.tm.snapshot(within=30.0)
            if not s:
                time.sleep(0.05)
                continue
            self.note(s)
            if s.player.hp <= 0:
                why = "사망"
                break
            c = next((x for x in s.chars if x.ptr == ptr), None)
            if c is None or c.hp <= 0:
                why = "사라짐"
                break
            v = self.approach_speed(ptr)
            if 4.5 <= c.dist <= 8.0 and v >= 1.0:
                why = f"달려듦 {v:.1f} m/s"
                break
            if c.dist < 3.0:
                why = "붙음"
                break
            time.sleep(0.03)
        self.pad.guard(False)
        if why == "붙음":
            self.pad.lock_on()          # 락온 풀기 (살아 있다)
            time.sleep(0.1)
            self.pad.release_due()
        if why is None or c is None or why in ("사망", "사라짐", "붙음"):
            print(f"   #{ti} {e['npc']} 미끼: {why or '15 s 안에 안 옴'} — 화톳불로", flush=True)
            self._record(k, ti, e, c, None, {}, {"result": f"미끼 실패: {why or '안 옴'}", "plan": "bait"})
            return False
        c2 = next((x for x in (self.tm.snapshot(within=30.0) or s).chars if x.ptr == ptr), c)
        res = self.throw_at(ptr, locked_already=True, release_if_alive=False)
        res.update({"plan": "bait", "trigger": why})
        self._record(k, ti, e, c2, None, {}, res)
        print(f"   #{ti} {e['npc']} 미끼: {why}, {c2.dist:.1f} m 에서 던짐 → 폭탄 {res['result']} (HP {res['hp0']}→{res['hp_after']})"
              f"{' 락온 ' + str(res.get('locked_npc')) if res['result'] == '락온 대상 다름' else ''}", flush=True)
        # 달려오는 놈은 손을 떠날 때 자리를 겨누니 떨어질 무렵엔 앞으로 와 있다 — 가장자리만 맞으면(75→57) 한 방 더.
        # 락온·폭탄 칸은 그대로라 곧바로 던질 수 있다. 3 m 안이면 폭탄은 접는다 (막고 한 대 몫).
        n_more = 0
        while res["result"] == "명중" and n_more < 2:
            s3 = self.tm.snapshot(within=30.0)
            c3 = next((x for x in s3.chars if x.ptr == ptr), None) if s3 else None
            if c3 is None or c3.hp <= 0:
                res["result"] = "처치"
                break
            if c3.dist < 3.0:
                break
            n_more += 1
            res = self.throw_at(ptr, locked_already=True, release_if_alive=False)
            res.update({"plan": "bait", "trigger": f"한 방 더 #{n_more}"})
            self._record(k, ti, e, c3, None, {}, res)
            print(f"      한 방 더 ({c3.dist:.1f} m) → {res['result']} (HP {res['hp0']}→{res['hp_after']})", flush=True)
        if res["result"] != "처치" and res.get("hp_after"):
            self.pad.lock_on()          # 살아 있으면 락온 풀기
            time.sleep(0.1)
            self.pad.release_due()
        if res["result"] == "처치":
            sk = self.tm.snapshot(within=1.0)
            if sk:
                self.last_kill_pos = (sk.player.x, sk.player.y, sk.player.z)
        if res["result"] != "처치":
            print("   못 잡음 — 화톳불로", flush=True)
            return False
        return True

    def observe(self, k: int, after: int) -> None:
        """처치 직후 제자리에서 방패를 들고 observe_s 초 동안 나머지 지도 적의 움직임을 본다 (1 s 마다 한 줄)."""
        self.pad.guard(True)
        t0 = time.time()
        rows = []
        while time.time() - t0 < self.observe_s:
            s = self.tm.snapshot(within=60.0)
            if s:
                self.note(s)
                line = []
                for i, ptr in self.ptr_of.items():
                    c = next((x for x in s.chars if x.ptr == ptr), None)
                    if c is None or c.hp <= 0:
                        continue
                    moved = math.dist((c.x, c.y, c.z), tuple(MAP[i - 1]["pos"]))
                    fp = vp.facing_player(c, s.player)
                    line.append(f"#{i} {c.dist:4.1f}m 스폰서 {moved:4.1f}m 보는각 {'-' if fp is None else round(fp)}° 애니 {c.anim}")
                    rows.append({"t": round(time.time() - t0, 1), "id": i, "dist": round(c.dist, 1), "moved": round(moved, 1),
                                 "facing": None if fp is None else round(fp), "anim": c.anim, "pos": [round(c.x, 1), round(c.y, 1), round(c.z, 1)]})
                print(f"     +{time.time() - t0:4.1f}s  " + " | ".join(line), flush=True)
            time.sleep(1.0)
        self.pad.guard(False)
        with (ROOT / "data" / "hunt-observe.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "trial": k, "after": after, "rows": rows}, ensure_ascii=False) + "\n")

    def _record(self, k, ti, e, c, trk, jd, res, img=None) -> None:
        with OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "trial": k, "target": ti, "npc": e["npc"], "spawn": e["pos"],
                                "dist": None if c is None else round(c.dist, 1), **(trk or {}), "judge": jd, **res, "img": img},
                               ensure_ascii=False) + "\n")


def main() -> None:
    args = sys.argv[1:]
    dist = 10.0
    targets = [1]
    if "--throw" in args:
        dist = float(args[args.index("--throw") + 1])
        del args[args.index("--throw"):args.index("--throw") + 2]
    if "--targets" in args:
        targets = [int(x) for x in args[args.index("--targets") + 1].split(",")]
        del args[args.index("--targets"):args.index("--targets") + 2]
    obs = 0.0
    if "--observe" in args:
        obs = float(args[args.index("--observe") + 1])
        del args[args.index("--observe"):args.index("--observe") + 2]
    plans = {}
    if "--plan" in args:                  # 예: --plan 1:sneak,3:bait  (적마다 공략)
        for kv in args[args.index("--plan") + 1].split(","):
            i, v = kv.split(":")
            plans[int(i)] = v
        del args[args.index("--plan"):args.index("--plan") + 2]
    n = int(args[0]) if args else 1
    h = Hunter()
    h.observe_s = obs
    h.plans = plans
    for k in range(1, n + 1):
        h.hunt(k, targets, dist)
    h.pad.neutral()
    h.run.rest()


if __name__ == "__main__":
    main()
