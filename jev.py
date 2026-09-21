"""
Jev (TypeSafe AI System One) 연동 — 텍스트를 만들지 않고 **타입이 정해진 판단**(choice/score/noul)을
확률·신뢰도와 함께 돌려주는 모델. 지연 ~0.1 s, 입력 토큰 10억 개당 $42.  https://docs.typesafe.ai

우리 골격에서 끼우는 자리 (둘 다 결정론 규칙과 A/B 비교해 이겨야 채택):
  B. 구간 정책  decide_move(): 적이 보이거나 웨이포인트에 닿을 때 → 이동 모드 choice + 후퇴 noul + 위협 score
  A. 복기 랭킹  rank_proposals(): 규칙이 만든 플레이북 수정 후보들 중 "이 죽음을 막았을" 것을 고름

규율:
  · 이벤트 트리거만 (틱마다 호출 안 함). 하루 호출 상한 (JEV_DAILY_CAP).
  · 신뢰도 게이트: confidence < JEV_MIN_CONF 이면 결정론 규칙을 따른다 (confidence-gated routing).
  · 실패·타임아웃·상한 초과 → 즉시 규칙 폴백. 호출 입력/출력은 에피소드 로그에 남긴다.
  · 출력은 우리가 준 선택지 안에서만 나오므로 플레이북 범위를 벗어날 수 없다.

.env: TYPESAFE_API_KEY=...   (console.typesafe.ai 에서 발급)
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

API = "https://api.typesafe.ai/v1/systemone"
MODEL = os.environ.get("JEV_MODEL", "jev-latest")
MIN_CONF = float(os.environ.get("JEV_MIN_CONF", "0.6"))
DAILY_CAP = int(os.environ.get("JEV_DAILY_CAP", "3000"))
TIMEOUT = float(os.environ.get("JEV_TIMEOUT", "2.0"))
LOG = Path(__file__).resolve().parent / "data" / "jev.jsonl"

_calls_today = 0
_day = time.strftime("%Y%m%d")


def available() -> bool:
    return bool(os.environ.get("TYPESAFE_API_KEY"))


def ask(state, questions: dict, tag: str = "") -> dict | None:
    """POST /v1/systemone. 실패·상한·키 없음 → None (호출자는 규칙으로 폴백)."""
    global _calls_today, _day
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        return None
    today = time.strftime("%Y%m%d")
    if today != _day:
        _day, _calls_today = today, 0
    if _calls_today >= DAILY_CAP:
        return None
    body = json.dumps({"state": state, "model": MODEL, "questions": questions}).encode("utf-8")
    req = urllib.request.Request(API, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            out = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        _log({"t": time.time(), "tag": tag, "error": str(e)[:200]})
        return None
    _calls_today += 1
    _log({"t": time.time(), "tag": tag, "ms": round((time.time() - t0) * 1000), "state": state, "questions": questions,
          "answers": out.get("answers"), "model": out.get("model")})
    return out.get("answers")


def _log(row: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── B. 구간 정책 ──
MOVE_CRITERIA = {
    "sprint": "Run at full speed with no guard. Fastest, drains stamina, exposed to hits.",
    "guardjump": "Advance with the shield raised and jump every second. Medium speed, protected by guard and jump invulnerability frames.",
    "walk": "Walk slowly to recover stamina. Slowest, exposed.",
}
THREAT_LEVELS = [
    "No danger: no hostile within 20 m",
    "Minor: weak hostiles far away or few",
    "Dangerous: strong or several hostiles closing in",
    "Lethal: the character will likely die within seconds without retreating",
]


def decide_move(snapshot, pb, names: dict | None = None) -> dict | None:
    """스냅샷 → {mode, retreat, threat, confidence...}. None 이면 규칙 폴백."""
    p = snapshot.player
    hostiles = snapshot.hostile(20.0)
    state = {
        "context": "Elden Ring. An autonomous character patrols a fixed route in Limgrave. Goal: survive and keep moving. "
                   "It cannot attack; it can only move, guard (shield), jump, dodge, drink a healing flask, and retreat to the previous waypoint.",
        "player": {"hp_pct": round(p.hp / max(1, p.max_hp), 2), "stamina_pct": round(p.sp / max(1, p.max_sp), 2) if p.max_sp else None,
                   "current_move_mode": getattr(pb, "mode_near_enemy", "guardjump")},
        "hostiles": [{"type": (names or {}).get(c.npc_param, "") or str(c.npc_param), "distance_m": round(c.dist, 1),
                      "hp_pct": round(c.hp / max(1, c.max_hp), 2)} for c in hostiles[:6]],
        "playbook": {"retreat_hp_pct": pb.retreat_hp_pct, "avoid_types": [(names or {}).get(t, str(t)) for t in pb.avoid_types]},
    }
    questions = {
        "move_mode": {"type": "choice", "instructions": "Which movement mode should the character use right now?", "criteria": MOVE_CRITERIA},
        "retreat": {"type": "noul", "instructions": "The character should retreat to the previous waypoint right now instead of advancing."},
        "threat": {"type": "score", "instructions": "How dangerous is the current situation?", "criteria": THREAT_LEVELS},
    }
    a = ask(state, questions, tag="move")
    if not a:
        return None
    mv, rt, th = a.get("move_mode", {}), a.get("retreat", {}), a.get("threat", {})
    return {
        "mode": mv.get("choice"), "mode_conf": mv.get("confidence", 0.0), "mode_probs": mv.get("probabilities"),
        "retreat": rt.get("noul", 0.0),
        "threat": th.get("score"), "threat_conf": th.get("confidence", 0.0),
        "confident": (mv.get("confidence", 0.0) >= MIN_CONF),
    }


# ── A. 복기 랭킹 ──
def rank_proposals(diag: dict, pb, candidates: list[dict]) -> dict | None:
    """규칙이 만든 후보들(각각 {key, op, value, why}) 중 이 죽음을 막았을 가능성이 가장 높은 것을 고른다.
    후보가 없으면 None. Jev 실패 시 None (호출자가 첫 후보를 쓰면 규칙과 동일)."""
    if not candidates:
        return None
    crit = {f"c{i}": c["why"] for i, c in enumerate(candidates)}
    crit["none"] = "None of these changes would have prevented this death; keep the playbook as is."
    state = {
        "context": "Post-mortem of an autonomous Elden Ring character that died while patrolling. "
                   "We may change exactly one playbook parameter. Pick the change most likely to prevent this kind of death.",
        "diagnosis": diag,
        "playbook": {k: v for k, v in vars(pb).items() if k not in ("rejected", "note", "change")},
    }
    questions = {
        "best_change": {"type": "choice", "instructions": "Which single change is most likely to prevent this death next time?", "criteria": crit},
        "avoidable": {"type": "noul", "instructions": "This death was avoidable by changing movement or retreat behaviour."},
    }
    a = ask(state, questions, tag="postmortem")
    if not a:
        return None
    ch = a.get("best_change", {})
    pick = ch.get("choice")
    if not pick or pick == "none" or ch.get("confidence", 0.0) < MIN_CONF:
        return {"proposal": None, "confidence": ch.get("confidence"), "avoidable": a.get("avoidable", {}).get("noul")}
    return {"proposal": candidates[int(pick[1:])], "confidence": ch.get("confidence"), "probs": ch.get("probabilities"),
            "avoidable": a.get("avoidable", {}).get("noul")}


# ── 순찰 루프 연결 (그림자/실전) ──
import threading


class Shadow:
    """순찰 틱(20 Hz)을 막지 않도록 Jev 호출을 스레드에서 돌린다.
    호출 트리거: 적 수가 바뀜 · 피해를 입음 · 적이 있는 채로 ASK_EVERY 초 경과.  적이 없으면 안 묻는다.
    mode='shadow' 이면 결과를 기록만 하고, 'live' 이면 confident 한 결과를 Guard 가 따른다."""
    ASK_EVERY = 3.0

    def __init__(self, pb, names: dict | None, mode: str = "shadow", log=print):
        self.pb, self.names, self.mode, self.log = pb, names or {}, mode, log
        self.latest: dict | None = None      # 마지막 응답 (+ 그때의 규칙 모드)
        self.fresh = False                   # on_tick 이 아직 기록 안 한 새 응답
        self.busy = False
        self.last_ask = 0.0
        self.last_hostiles = -1
        self.calls = 0

    def maybe_ask(self, s, rule_mode: str, damaged: bool) -> None:
        n = len(s.hostile(20.0))
        now = time.time()
        due = (n != self.last_hostiles) or damaged or (n > 0 and now - self.last_ask > self.ASK_EVERY)
        self.last_hostiles = n
        if not due or self.busy or n == 0 and not damaged:
            return
        self.busy, self.last_ask = True, now
        threading.Thread(target=self._run, args=(s, rule_mode), daemon=True).start()

    def _run(self, s, rule_mode: str) -> None:
        try:
            d = decide_move(s, self.pb, self.names)
            if d:
                d["rule_mode"] = rule_mode
                d["t"] = round(time.time(), 3)
                self.latest, self.fresh = d, True
                self.calls += 1
                if d["mode"] != rule_mode or d["retreat"] >= 0.5:
                    self.log(f"  jev[{self.mode}]: mode={d['mode']}({d['mode_conf']:.2f}) rule={rule_mode} "
                             f"retreat={d['retreat']:.2f} threat={d['threat']}")
        finally:
            self.busy = False

    def take(self) -> dict | None:
        """새 응답이 있으면 한 번만 돌려준다 (에피소드 행에 기록용)."""
        if not self.fresh:
            return None
        self.fresh = False
        return self.latest

    def override(self) -> tuple[str | None, bool]:
        """live 모드에서 Guard 가 따를 (이동 모드, 후퇴) — 최근 ASK_EVERY×2 초 안의 confident 응답만."""
        d = self.latest
        if self.mode != "live" or not d or time.time() - d["t"] > self.ASK_EVERY * 2:
            return None, False
        return (d["mode"] if d["confident"] else None), d["retreat"] >= 0.7
