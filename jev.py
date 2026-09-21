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

백엔드 (JEV_BACKEND):
  typesafe  Jev API. 둘 중 하나:
              · .env: AI_GATEWAY_API_KEY=...   Vercel AI Gateway 경유 (https://ai-gateway.vercel.sh/typesafe/v1/systemone, model typesafe-ai/jev)
                — TypeSafe 와 같은 요청/응답 모양, 입력 100만 토큰당 $0.042, 출력 무료. early access 없이 바로 됨.
              · .env: TYPESAFE_API_KEY=...     TypeSafe 직접 (console.typesafe.ai, early access)
  local     로컬 LLM 의 OpenAI 호환 서버 (LM Studio `lms server start` / Ollama / llama-server) + JSON 스키마 강제 출력.
            .env: LOCAL_LLM_URL=http://127.0.0.1:1234/v1  LOCAL_LLM_MODEL=qwen/qwen3-4b
            (localhost 라고 쓰지 말 것 — Windows 에서 ::1 먼저 시도하다 실패해 요청마다 2 s 가 붙는다. 실측 2.1 s → 0.1 s)
            같은 질문(choice/score/noul)을 JSON 스키마로 바꿔 묻고 같은 모양의 답을 돌려준다.
            choice 의 확률은 모델이 적는 값이 아니라 **선택 토큰의 logprob** 에서 뽑는다 (LM Studio/llama-server 가 top_logprobs 지원).
            그래서 Jev 의 probabilities/confidence 와 같은 의미로 게이트를 건다. logprobs 가 없는 서버(Ollama)면 모델이 적은 값으로 폴백.
            temperature 0 이라 같은 상태엔 같은 답 → A/B 재현 가능. 비용 0. 게임과 GPU 를 나눠 쓰므로 프레임 드랍은 실측할 것.
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

TYPESAFE_API = "https://api.typesafe.ai/v1/systemone"
GATEWAY_API = "https://ai-gateway.vercel.sh/typesafe/v1/systemone"


def _typesafe_route() -> tuple[str, str, str] | None:
    """(URL, 모델, 키) — TYPESAFE_API_KEY 가 있으면 직접, 아니면 AI_GATEWAY_API_KEY 로 Vercel 게이트웨이. 둘 다 없으면 None."""
    if os.environ.get("TYPESAFE_API_KEY"):
        return TYPESAFE_API, os.environ.get("JEV_MODEL", "jev-latest"), os.environ["TYPESAFE_API_KEY"]
    if os.environ.get("AI_GATEWAY_API_KEY"):
        return GATEWAY_API, os.environ.get("JEV_MODEL", "typesafe-ai/jev"), os.environ["AI_GATEWAY_API_KEY"]
    return None
BACKEND = os.environ.get("JEV_BACKEND", "").lower()          # "" → 키 있으면 typesafe, 아니면 local
LOCAL_URL = os.environ.get("LOCAL_LLM_URL", "http://127.0.0.1:1234/v1").rstrip("/")
LOCAL_MODEL = os.environ.get("LOCAL_LLM_MODEL", "")
MIN_CONF = float(os.environ.get("JEV_MIN_CONF", "0.6"))
DAILY_CAP = int(os.environ.get("JEV_DAILY_CAP", "3000"))
TIMEOUT = float(os.environ.get("JEV_TIMEOUT", "2.0"))
LOG = Path(__file__).resolve().parent / "data" / "jev.jsonl"

_calls_today = 0
_day = time.strftime("%Y%m%d")


def backend() -> str:
    if BACKEND in ("typesafe", "local"):
        return BACKEND
    return "typesafe" if _typesafe_route() else "local"


def describe() -> str:
    if backend() == "local":
        return f"local {LOCAL_URL} {LOCAL_MODEL}"
    r = _typesafe_route()
    return f"typesafe {r[0]} {r[1]}" if r else "typesafe (키 없음)"


def available() -> bool:
    if backend() == "typesafe":
        return _typesafe_route() is not None
    try:
        with urllib.request.urlopen(f"{LOCAL_URL}/models", timeout=2.0) as r:
            return r.status == 200
    except Exception:
        return False


def ask(state, questions: dict, tag: str = "") -> dict | None:
    """질문 → 답. 실패·상한·키 없음 → None (호출자는 규칙으로 폴백)."""
    global _calls_today, _day
    if backend() == "local":
        return _ask_local(state, questions, tag)
    route = _typesafe_route()
    if not route:
        return None
    api, model, key = route
    today = time.strftime("%Y%m%d")
    if today != _day:
        _day, _calls_today = today, 0
    if _calls_today >= DAILY_CAP:
        return None
    body = json.dumps({"state": state, "model": model, "questions": questions}).encode("utf-8")
    req = urllib.request.Request(api, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            out = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        _log({"t": time.time(), "tag": tag, "error": str(e)[:200]})
        return None
    _calls_today += 1
    _log({"t": time.time(), "tag": tag, "backend": "typesafe", "ms": round((time.time() - t0) * 1000), "state": state, "questions": questions,
          "answers": out.get("answers"), "model": out.get("model"), "usage": out.get("usage"),
          "cost": ((out.get("provider_metadata") or {}).get("gateway") or {}).get("cost")})
    return out.get("answers")


def _schema_for(questions: dict) -> tuple[dict, str]:
    """choice/score/noul 질문 묶음 → (JSON 스키마, 질문 설명 텍스트)."""
    props, lines = {}, []
    for name, q in questions.items():          # choice 가 먼저 오도록 두 번 돈다 (생성 순서 = 프로퍼티 순서)
        if q["type"] == "choice":
            props[name] = {"type": "string", "enum": list(q["criteria"].keys())}
    for name, q in questions.items():
        t = q["type"]
        if t == "choice":
            opts = list(q["criteria"].keys())
            props[f"{name}_confidence"] = {"type": "number", "minimum": 0, "maximum": 1}
            lines.append(f"- {name} (choose one): {q['instructions']}\n" + "\n".join(f"    {k}: {v}" for k, v in q["criteria"].items())
                         + f"\n  {name}_confidence: how sure you are, 0..1")
        elif t == "score":
            levels = q["criteria"]
            props[name] = {"type": "integer", "minimum": 0, "maximum": len(levels) - 1}
            lines.append(f"- {name} (integer 0..{len(levels)-1}): {q['instructions']}\n" + "\n".join(f"    {i}: {v}" for i, v in enumerate(levels)))
        elif t == "noul":
            props[name] = {"type": "number", "minimum": 0, "maximum": 1}
            lines.append(f"- {name} (probability 0..1 that this is true): {q['instructions']}")
    props["reason"] = {"type": "string", "maxLength": 120}
    schema = {"type": "object", "properties": props, "required": list(props.keys()), "additionalProperties": False}
    return schema, "\n".join(lines)


def _ask_local(state, questions: dict, tag: str) -> dict | None:
    """OpenAI 호환 /chat/completions + response_format json_schema. 답을 Jev 와 같은 모양으로 맞춘다."""
    global _calls_today, _day
    today = time.strftime("%Y%m%d")
    if today != _day:
        _day, _calls_today = today, 0
    if _calls_today >= DAILY_CAP:
        return None
    schema, qtext = _schema_for(questions)
    body = {
        "model": LOCAL_MODEL or "default",
        "temperature": 0,
        "max_tokens": 200,
        "messages": [
            {"role": "system", "content": "You are a decision module for a game bot. Answer ONLY with the JSON object requested. Be decisive; keep 'reason' under 20 words."
                                          + (" /no_think" if "qwen3" in LOCAL_MODEL.lower() else "")},   # Qwen3 소프트 스위치 (Ollama 는 chat_template_kwargs 를 무시)
            {"role": "user", "content": f"STATE:\n{json.dumps(state, ensure_ascii=False)}\n\nQUESTIONS:\n{qtext}"},
        ],
        "response_format": {"type": "json_schema", "json_schema": {"name": "decision", "strict": True, "schema": schema}},
        "chat_template_kwargs": {"enable_thinking": False},   # Qwen3/Gemma4 류 thinking 모델: 생각 토큰이 예산을 다 먹지 않게
        "logprobs": True, "top_logprobs": 8,                  # choice 확률 분포용 (미지원 서버는 무시)
    }
    req = urllib.request.Request(f"{LOCAL_URL}/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer lm-studio"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=max(TIMEOUT, 8.0)) as r:
            out = json.loads(r.read().decode("utf-8"))
        msg = out["choices"][0]["message"]
        content = msg.get("content") or ""
        if "{" not in content:
            raise ValueError("empty content" + (" (thinking model — reasoning ate the token budget; use a non-thinking model)"
                                                if msg.get("reasoning_content") else ""))
        content = content[content.find("{"): content.rfind("}") + 1]   # 일부 모델이 앞뒤에 텍스트를 붙임
        raw = json.loads(content)
    except Exception as e:  # URLError/HTTPError/KeyError/JSONDecodeError/timeout
        _log({"t": time.time(), "tag": tag, "backend": "local", "error": str(e)[:200]})
        return None
    lp = (out["choices"][0].get("logprobs") or {}).get("content") or []
    answers = {}
    for name, q in questions.items():
        if name not in raw:
            continue
        if q["type"] == "choice":
            probs = _choice_probs(lp, name, list(q["criteria"].keys()))
            if probs and max(probs.values()) >= 0.999:
                probs = None   # LM Studio 는 샘플링 뒤 분포(1.0/0.0)를 돌려줘 정보가 없다 → 모델이 적은 값으로
            if probs:
                conf = probs[raw[name]] if raw[name] in probs else max(probs.values())
            else:   # logprobs 없는 서버 → 모델이 적은 값
                conf = float(raw.get(f"{name}_confidence", 0.0))
                probs = {raw[name]: conf}
            answers[name] = {"choice": raw[name], "confidence": round(conf, 3), "probabilities": probs}
        elif q["type"] == "score":
            answers[name] = {"score": int(raw[name]), "confidence": 1.0}
        else:
            answers[name] = {"noul": float(raw[name])}
    answers["_reason"] = raw.get("reason", "")
    _calls_today += 1
    _log({"t": time.time(), "tag": tag, "backend": "local", "model": out.get("model"), "ms": round((time.time() - t0) * 1000),
          "state": state, "answers": answers})
    return answers


def _choice_probs(lp: list, name: str, options: list[str]) -> dict | None:
    """logprobs 토큰열에서 `"name": "` 바로 다음 토큰의 top_logprobs 를 옵션별로 모아 정규화한다.
    옵션의 첫 토큰이 겹치면(예: guard/guardjump) 접두 일치로 합산 — 우리 옵션들은 첫 글자부터 다르다."""
    text = ""
    for i, tok in enumerate(lp):
        text += tok.get("token", "")
        stripped = text.rstrip()
        if stripped.endswith(f'"{name}": "') or stripped.endswith(f'"{name}":"'):
            if i + 1 >= len(lp):
                return None
            mass = {o: 0.0 for o in options}
            for cand in lp[i + 1].get("top_logprobs") or []:
                t = cand.get("token", "").strip().strip('"')
                for o in options:
                    if t and (o.startswith(t) or t.startswith(o)):
                        mass[o] += math.exp(cand["logprob"])
                        break
            total = sum(mass.values())
            return {o: round(v / total, 3) for o, v in mass.items()} if total > 0 else None
    return None


def _log(row: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── B. 구간 정책 ──
MOVE_CRITERIA = {
    "sprint": "Run at full speed (6 m/s), shield down. Best for covering ground when nothing is close; drains stamina; every hit lands.",
    "guardjump": "Advance with the shield up and jump every second (4 m/s). Blocks most melee hits and jumps through sweeps; costs stamina on each block.",
    "walk": "Walk (2.5 m/s) with the shield down. Slowest and unprotected; its only benefit is that stamina regenerates fast. Never a safe option near enemies.",
}
CONTEXT = ("Elden Ring. An autonomous character patrols a fixed route in Limgrave. Goal: survive as long as possible while continuing the route. "
           "It cannot attack. It can: move, hold the shield up, jump, dodge-roll when hit, drink a healing flask (heals ~40%, takes 1.5 s, unsafe with an enemy within 8 m), "
           "and retreat to the previous waypoint (only useful against enemies that are slower than the character or stop chasing; flying enemies such as bats and hawks are faster and keep biting). "
           "Being hit at low HP is how it dies; it dies in seconds when surrounded.")
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
        "context": CONTEXT,
        "player": {"hp_pct": round(p.hp / max(1, p.max_hp), 2), "stamina_pct": round(p.sp / max(1, p.max_sp), 2) if p.max_sp else None},
        "hostiles": [{"type": (names or {}).get(c.npc_param, "") or str(c.npc_param), "distance_m": round(c.dist, 1),
                      "hp_pct": round(c.hp / max(1, c.max_hp), 2)} for c in hostiles[:6]],
        "playbook": {"retreat_hp_pct": pb.retreat_hp_pct, "avoid_types": [(names or {}).get(t, str(t)) for t in pb.avoid_types]},
    }
    questions = {
        "move_mode": {"type": "choice", "instructions": "Which movement mode should the character use right now?", "criteria": MOVE_CRITERIA},
        "retreat": {"type": "noul", "instructions": "The character should turn back to the previous waypoint right now (to break contact and drink the flask) instead of advancing."},
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
        "reason": a.get("_reason", ""),
    }


# ── A. 복기 랭킹 ──
def rank_proposals(diag: dict, pb, candidates: list[dict]) -> dict | None:
    """규칙이 만든 후보들(각각 {key, op, value, why}) 중 이 죽음을 막았을 가능성이 가장 높은 것을 고른다.
    후보가 없으면 None. Jev 실패 시 None (호출자가 첫 후보를 쓰면 규칙과 동일)."""
    if not candidates:
        return None
    # 라벨은 첫 토큰이 서로 다른 한 글자 (c0/c1… 은 첫 토큰 "c" 가 같아 logprob 분포가 뭉개진다)
    labels = [chr(ord("A") + i) for i in range(len(candidates))]
    crit = {lab: c["why"] for lab, c in zip(labels, candidates)}
    crit["NONE"] = "None of these changes would have prevented this death; keep the playbook as is."
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
    if not pick or pick == "NONE" or ch.get("confidence", 0.0) < MIN_CONF:
        # 게이트 미달 — 채택은 안 하지만 뭘 골랐을지는 남긴다 (그림자 비교용)
        would = candidates[labels.index(pick)] if pick and pick != "NONE" else None
        return {"proposal": None, "would_pick": would, "confidence": ch.get("confidence"), "probs": ch.get("probabilities"),
                "avoidable": a.get("avoidable", {}).get("noul")}
    return {"proposal": candidates[labels.index(pick)], "confidence": ch.get("confidence"), "probs": ch.get("probabilities"),
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
                             f"retreat={d['retreat']:.2f} threat={d['threat']} {d.get('reason', '')}")
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
