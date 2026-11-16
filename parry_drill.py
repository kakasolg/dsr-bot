"""Parry drill (MoKa M1115-03): "캐릭터를 무적으로 놓고, 석궁병 그냥 처치 하고 나머지는 무제한 패링으로 잡아봐."

  python parry_drill.py [--radius 16] [--limit 300] [--at x,y,z]   --at: walk there first (NavMesh), then pick foes

Offline drill only — it turns on ChrDbg PlayerNoDead (a game-memory write; CLAUDE.md: offline use only, MoKa asked for it).
 1. Foes = hostiles within --radius of the start, same floor (|dy| ≤ 2 m), alive; plus any that later come within 6 m.
 2. Crossbowmen (255002 · 255042, souls/foes.py) → the bot's normal fight (Field.fight), "그냥 처치".
 3. Everyone else → parry only: stand ~1.8 m in front, face them, and when an attack anim's first hit window (game file TAE,
    type 1) is LEAD_S away, press L2 (Pad.parry). If the foe goes into 2100 (parried), R1 at once (riposte).
    No other attack, no roll, no Estus — unlimited tries (no death).
 4. Ends when no foe is left, --limit s, or Ctrl+C. PlayerNoDead is turned back off only when no awake foe is within 8 m.
Every decision and every 20 ms tick → data/runs/<log>.parry.jsonl. Not a bot command; nothing imports this.

── 패링 시각 (MoKa 시범 11-15, M1115-01, 23번 중 12번 성공) ──────────────────────
 · 패링 애니 485102는 L2 뒤 0~17 ms에 시작. 성공은 적 판정이 닿을 때 패링 애니가 0.02~0.19 s 째 (실패 0.007 · 0.449).
 · 그래서 적 판정 시작까지 LEAD_S(0.12 s) 남았을 때 누름 → 닿을 때 패링 애니 ≈ 0.10~0.12 s (구간 한가운데).
 · 파일 판정보다 실제가 이른 공격: c2560 3000 두 번 모두 0.14 s 이름 → OFFSET로 그만큼 일찍 누름 [2번 관찰].
 · 못 푼 것: c2550 3004 (적 at 1.8~2.0 s에 패링됨, 파일 0.37 s), c2560 3005 (판정 안 0.12 s에 맞음 2번).
"""
from __future__ import annotations

import json
import math
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

import andre_route

CROSSBOW = {255002, 255042}
PARRIED = {2100, 2101, 2102}
LEAD_S = 0.12          # 판정 시작 전 이만큼 남았을 때 L2 (위 블록)
MIN_LEFT_S = 0.03      # 이보다 덜 남았으면 늦음 — 누르지 않음 (실패 0.007 · −0.011)
OFFSET: dict = {}      # (model, anim) → s; 비워 둠 — c2560 3000의 '0.14 s 이름'은 아래 SECTION(a02 23000 0.733 s)으로 설명됨
# ── 같은 메모리 애니 번호, 다른 TAE 섹션 (11-15 드릴 1차 + MoKa 시범) ──────────────────────
#  · 255041의 3004 = a01 13004 (판정 2.03 s): 드릴 1차에 at 2.083에서 −261, MoKa 성공 2번은 at 1.78·1.98 (a00 3004는 0.37 s).
#  · 256002의 3000 = a02 23000 (0.733 s): MoKa 성공 2번 모두 a00 창(0.867)보다 0.14 s 앞 = 23000과 맞음; 3005 = 23005 (0.533 s)
#    → MoKa가 3005 at 0.53에 누르고 두 번 맞은 것과 맞음.
#  · 256000은 a00과 맞음 (MoKa 3003 ×2 · 3004 ×1 ±0.012 s). NpcParam에 섹션 값은 없음 (variation 같음) — 관찰로만 정한 표.
SECTION = {255041: 1, 256002: 2}
NO_PARRY = {("c2550", 3009)}   # 드릴 1차: 판정 0.117 s 전에 눌러 패링 애니 중 −50; MoKa도 1번 실패 (가드 부담 100 — 방패 치기류로 봄, 미확인)
# ── 먼 거리 패링 (드릴 4차 11-15, 가설) ──────────────────────
#  · 3003 실패 3번이 모두 d 2.31·2.83·2.87 m: 판정 창 안에 패링 애니가 돌고 있었는데도 맞음 (at 0.9 · 1.067에 피격).
#  · 성공 9번은 전부 d ≤ 1.91 m, MoKa 성공도 0.85~1.21 m. 거리 때문인지 3003(돌진)만의 문제인지는 아직 모름.
MAX_PARRY_M = 2.2      # 이보다 멀면 L2 안 누르고 그 공격 동안 뒤로 빠짐
RIPOSTE_M = 1.1        # 앞잡이 R1 전에 이 거리까지 붙음 (0.5 s 한도)
STAND_M = 1.8          # 기다리는 거리 (시범 성공 0.8~1.2 m, 붙으면 리포스트도 잡힘)
FAR_M = 2.6
NEAR_M = 1.0
JOIN_M = 6.0
TICK_LOG_S = 0.02
MAX_FAILS = 20         # [MoKa M1115-04] 20번 실패하면 멈춤 → 세이브 복원, 원인 고치고 다시
JUDGE_S = 0.6          # L2 뒤 이 안에 적이 2100이 안 되면 실패
REPRESS_S = 0.8        # 이 안엔 L2를 다시 안 누름 (anim 시작 키가 반올림 경계에서 바뀌어 같은 공격에 두 번 눌림)


def model_of(npc: int) -> str:
    return f"c{str(npc)[:4]}"


def load_windows(models) -> dict:
    """{(model, anim): [(start, end), …]} from the game files (TAE type 1 = AttackBehavior), as in the 11-15 analysis."""
    import player_tae_extract as P
    import tae_extract as TE
    from navmesh import GAME_DIR
    from soulstruct.containers import Binder
    P._patch()
    out = {}
    for m in models:
        for f in sorted((GAME_DIR / "chr").glob(f"{m}*.anibnd.dcx")):
            for ent in Binder.from_path(f).entries:
                if not ent.name.lower().endswith(".tae"):
                    continue
                sec = P.section_of(ent.name)
                t = TE.read_tae(bytes(ent.data))
                for aid, a in t["animations"].items():
                    full = aid if not sec else sec * 10000 + aid
                    h = sorted((e["start"], e["end"]) for e in a["events"] if e["type"] == 1)
                    if h:
                        out.setdefault((m, full), h)
    return out


def windows_for(win: dict, npc: int, anim: int):
    """The hit windows the foe really plays: its SECTION's copy (a01 = +10000, a02 = +20000) when the file has one, else a00."""
    m, sec = model_of(npc), SECTION.get(npc, 0)
    if anim < 10000 and sec and (m, sec * 10000 + anim) in win:
        return win[(m, sec * 10000 + anim)]
    return win.get((m, anim))


def parry_due(windows, at: float, offset: float = 0.0, done=()) -> int | None:
    """Index of the hit window to parry now, or None. Pure (tests/parry_drill_test.py)."""
    if at is None:
        return None
    for i, (w0, _) in enumerate(windows):
        if i in done:
            continue
        left = w0 + offset - at
        if MIN_LEFT_S <= left <= LEAD_S:
            return i
    return None


class Drill(andre_route.Route):
    def __init__(self, radius: float, limit: float, at=None):
        super().__init__()
        self.radius, self.limit, self.at = radius, limit, at
        self.plog = open(str(self.log.path).replace(".jsonl", ".parry.jsonl"), "a", encoding="utf-8")
        self.t0 = time.time()
        self.stats = {"parry": 0, "parried": 0, "fail": 0, "riposte": 0, "hit_taken": 0, "unknown_attack": 0}
        self.pending = None    # (ptr, t_press, anim, at) — the last L2 not judged yet

    def rec(self, kind, **kw):
        d = {"t": round(time.time() - self.t0, 3), "kind": kind, **kw}
        self.plog.write(json.dumps(d) + "\n"); self.plog.flush()
        if kind != "tick":
            self.say(f"  [{d['t']:6.2f}] {kind} {kw}")

    def foes(self, s, ids):
        return [c for c in s.chars if c.ptr in ids and c.hp > 0] if s else []

    def go(self):
        tm = self.tm
        nodead0 = tm.get_dbg(tm.DBG_PLAYER_NO_DEAD)
        tm.set_dbg(tm.DBG_PLAYER_NO_DEAD, True)
        result = "?"
        try:
            if self.at:
                # MoKa 11-15 (M1115-10) "석궁병은 아예 처리도 않하네": 교회로 가기 전에 광장 석궁병부터 (5차는 교회 18 m만 골라 빠짐)
                s0 = self.mv.snap(30.0)
                for c in [c for c in (s0.hostile(30.0) if s0 else []) if c.npc_param in CROSSBOW and c.hp > 0]:
                    self.rec("crossbow_fight", npc=c.npc_param, d=round(c.dist, 1), hp=c.hp)
                    r = self.f.fight(c.ptr, self.nm, f"석궁 {c.npc_param}", desperate=True, limit=25.0)
                    self.rec("crossbow_done", r=r)
                # MoKa가 기사(c2560)를 패링으로 잡은 교회 안 자리 (observe 172208 · 173325: 플레이어 (6.6~11.1, 28.47, 92.2~102.8))
                r = self.walk([self.at], f"연습 자리 {self.at}", ignore={c.npc_param for c in self.mv.snap(60.0).chars})
                self.rec("walk_to_spot", at=self.at, r=r)
            s = self.state("start")
            p = s.player
            ids = {c.ptr for c in s.hostile(self.radius) if c.hp > 0 and abs(c.y - p.y) <= 2.0 and c.npc_param != 100000}
            start = [(c.npc_param, round(c.dist, 1)) for c in s.chars if c.ptr in ids]
            self.rec("targets", foes=start, nodead_before=nodead0)
            self.win = load_windows({model_of(c.npc_param) for c in s.chars if c.ptr in ids} | {"c2550", "c2560"})
            self.rec("windows", n=len(self.win))
            result = self.loop(ids)
        except KeyboardInterrupt:
            result = "ctrl-c"
        finally:
            self.pad.guard(False); self.pad.neutral()
            s = self.mv.snap(10.0)
            awake = [c for c in s.hostile(8.0) if c.hp > 0] if s else []
            if not awake:
                tm.set_dbg(tm.DBG_PLAYER_NO_DEAD, bool(nodead0))
            self.rec("end", result=result, stats=self.stats, nodead_now=tm.get_dbg(tm.DBG_PLAYER_NO_DEAD),
                     awake_8m=[(c.npc_param, round(c.dist, 1)) for c in awake])
            print(f"RESULT parry drill: {result} {self.stats} · log {self.log.path}")
            self.plog.close()
            try:
                self.esc.stop()
            except Exception:
                pass
            self.pad.close()
            self.lock.release()

    def loop(self, ids):
        mv, pad, tm = self.mv, self.pad, self.tm
        t_end = time.time() + self.limit
        done = {}             # (ptr, anim start key) → set(window index) already parried
        last_log = 0.0
        last_anim = {}
        while time.time() < t_end:
            s = mv.snap(self.radius + 4)
            if not s:
                time.sleep(0.02); continue
            p = s.player
            for c in s.hostile(JOIN_M):
                if c.hp > 0 and c.ptr not in ids and abs(c.y - p.y) <= 2.0 and c.npc_param != 100000:
                    ids.add(c.ptr); self.rec("join", npc=c.npc_param, d=round(c.dist, 1))
            live = self.foes(s, ids)
            if not live:
                return "all down"
            bows = [c for c in live if c.npc_param in CROSSBOW]
            if bows:
                c = min(bows, key=lambda c: c.dist)
                self.rec("crossbow_fight", npc=c.npc_param, d=round(c.dist, 1), hp=c.hp)
                r = self.f.fight(c.ptr, self.nm, f"석궁 {c.npc_param}", desperate=True, limit=8.0)
                self.rec("crossbow_done", r=getattr(r, "result", str(r)), dealt=getattr(r, "dealt", None))
                continue
            k = min(live, key=lambda c: c.dist)
            m, a = model_of(k.npc_param), k.anim
            at = tm.anim_time(k.ptr)
            now = time.time()
            if p.hp < getattr(self, "_hp_prev", p.hp):
                self.stats["hit_taken"] += 1
                self.rec("hit_taken", hp=p.hp, lost=self._hp_prev - p.hp, by=k.npc_param, anim=a,
                         at=None if at is None else round(at, 3), my=p.anim)
            self._hp_prev = p.hp
            if last_anim.get(k.ptr) != a:
                last_anim[k.ptr] = a
                self.rec("anim", npc=k.npc_param, anim=a, at=None if at is None else round(at, 3), d=round(k.dist, 2),
                         khp=k.hp, hp=p.hp, my=p.anim)
            if now - last_log >= TICK_LOG_S:
                last_log = now
                self.rec("tick", npc=k.npc_param, anim=a, at=None if at is None else round(at, 3), d=round(k.dist, 2),
                         khp=k.hp, hp=p.hp, sp=p.sp, my=p.anim)
            if self.pending and a not in PARRIED and now - self.pending[1] > JUDGE_S:
                self.stats["fail"] += 1
                self.rec("parry_fail", n=self.stats["fail"], anim=self.pending[2], at=self.pending[3], hp=p.hp)
                self.pending = None
                if self.stats["fail"] >= MAX_FAILS:
                    return f"{MAX_FAILS} fails"
            # 패링당함 → 바로 R1 (리포스트)
            if a in PARRIED:
                if self.pending:
                    self.rec("parry_ok", anim=self.pending[2], at=self.pending[3], after=round(now - self.pending[1], 3))
                    self.pending = None
                self.stats["parried"] += 1
                hp0, khp0 = p.hp, k.hp
                # 드릴 5차: 패링 성공 d 2.12 → R1이 d 1.63에서 나가 일반 공격(2000), 0 피해. 성공한 앞잡이는 d 0.85~1.09.
                t_close = time.time()
                while k.dist > RIPOSTE_M and time.time() - t_close < 0.5:
                    s_c = mv.snap(8.0); k_c = mv.find(s_c, k.ptr)
                    if not s_c or k_c is None:
                        break
                    k = k_c
                    pad.move(*mv.stick_to(s_c, k.x, k.z, 1.0))
                    time.sleep(0.01)
                pad.move(0.0, 0.0)
                pad.attack()
                self.rec("riposte_press", npc=k.npc_param, d=round(k.dist, 2), at=None if at is None else round(at, 3))
                t1 = time.time(); my_anims = []
                while time.time() - t1 < 3.0:
                    pad.release_due()
                    s2 = mv.snap(8.0); k2 = mv.find(s2, k.ptr)
                    if s2 and (not my_anims or my_anims[-1] != s2.player.anim):
                        my_anims.append(s2.player.anim)
                    if k2 is None or k2.hp < khp0:      # 드릴 1차: 2100이 끝난 뒤에야 HP가 깎임 (dealt 0으로 잘못 적음)
                        break
                    time.sleep(0.01)
                s2 = mv.snap(8.0); k2 = mv.find(s2, k.ptr)
                dealt = khp0 - (k2.hp if k2 else 0)
                if dealt > 0:
                    self.stats["riposte"] += 1
                self.rec("riposte_done", dealt=dealt, my_anims=my_anims[:6], khp=None if not k2 else k2.hp)
                continue
            wins = windows_for(self.win, k.npc_param, a)
            if (m, a) in NO_PARRY and wins and at is not None and at < wins[-1][1] + 0.05:
                key = (k.ptr, a, round(now - at, 1))
                if key not in done:
                    done[key] = set()
                    self.rec("no_parry_step_back", npc=k.npc_param, anim=a, at=round(at, 3), d=round(k.dist, 2))
                pad.move(*mv.stick_to(s, 2 * p.x - k.x, 2 * p.z - k.z, 1.0))
                time.sleep(0.01)
                continue
            if wins is None and 3000 <= a % 10000 < 4000:
                key = (k.ptr, a, round(now - (at or 0), 1))
                if key not in done:
                    done[key] = set(); self.stats["unknown_attack"] += 1
                    self.rec("no_window", npc=k.npc_param, anim=a)
            if wins and k.dist > MAX_PARRY_M and at is not None and any(at < w1 + 0.05 for _, w1 in wins):
                key = (k.ptr, a, round(now - at, 1))
                if key not in done:
                    done[key] = set()
                    self.rec("too_far_skip", npc=k.npc_param, anim=a, at=round(at, 3), d=round(k.dist, 2))
                # 드릴 5차: 넘기고 서 있다가 3003에 −245 → 그 공격 동안 뒤로 빠짐
                pad.move(*mv.stick_to(s, 2 * p.x - k.x, 2 * p.z - k.z, 1.0))
                time.sleep(0.01)
                continue
            if wins:
                key = (k.ptr, a, round(now - (at or 0), 1))
                i = parry_due(wins, at, OFFSET.get((m, a), 0.0), done.get(key, ()))
                if i is not None and now - getattr(self, "_last_parry", 0.0) < REPRESS_S:
                    i = None             # 드릴 3차 12.00 / 12.08 s: 같은 3005에 두 번 → 두 번째가 패링 애니를 다시 시작, −119
                if i is not None:
                    pad.move(0.0, 0.0)
                    pad.parry()
                    self._last_parry = now
                    self.pending = (k.ptr, now, a, round(at, 3))
                    done.setdefault(key, set()).add(i)
                    self.stats["parry"] += 1
                    self.rec("parry", npc=k.npc_param, anim=a, at=round(at, 3), win=wins[i], off=OFFSET.get((m, a), 0.0),
                             d=round(k.dist, 2), hp=p.hp)
                    continue
                if any(at is not None and at < w1 + 0.1 for _, w1 in wins):
                    mv.face(s, k, 15.0)
                    time.sleep(0.003)
                    continue
            # 공격 중 아님 → 거리 맞추고 바라봄
            if k.dist > FAR_M:
                pad.move(*mv.stick_to(s, k.x, k.z, 0.7))
            elif k.dist < NEAR_M:
                pad.move(*mv.stick_to(s, 2 * p.x - k.x, 2 * p.z - k.z, 0.4))
            else:
                mv.face(s, k, 15.0)
            time.sleep(0.005)
        return "limit"


if __name__ == "__main__":
    args = sys.argv[1:]
    r = float(args[args.index("--radius") + 1]) if "--radius" in args else 16.0
    lim = float(args[args.index("--limit") + 1]) if "--limit" in args else 300.0
    at = tuple(float(v) for v in args[args.index("--at") + 1].split(",")) if "--at" in args else None
    Drill(r, lim, at).go()
