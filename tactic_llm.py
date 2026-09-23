"""
교전 단위 전술 제안 — 상황이 바뀔 때마다 Gemini 에게 정해진 전술 중 하나를 묻는다. 게임을 모른다 (상태 dict 는 호출자가 만든다).

쓰는 자리: 톰슨 샘플링(bandit.py)의 팔 하나. 게이트형 판단기로 쓰지 않는 이유는 README "클라우드 판단 모델" 절 —
정확도는 8/10(3.5 Flash-Lite)까지 나오지만 틀린 답을 가려낼 신뢰도 신호가 어느 모델에도 없었다. 그래서 믿을지 말지를
모델에게 묻지 않고, 이 팔 전체의 성적(성공·진행도)을 고정 전술들과 나란히 재서 정한다.

프롬프트: 봇은 BOT_SYSTEM·BOT_DESC (폭탄 전술을 뺀 뒤의 선택지), 12 상황 프로브는 score_judge 의 넷짜리 그대로.
키: GEMINI_API_KEY (상위 폴더 .env). 호출은 스레드 — 봇 루프를 막지 않는다 (p50 750 ms).
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import score_judge as sj

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODEL = os.environ.get("TACTIC_LLM_MODEL", "gemini-3.5-flash-lite")
LOG = Path(__file__).resolve().parent / "data" / "tactic_llm.jsonl"
_NO_THINKING_CFG: set[str] = set()   # 'minimal' 생각 설정을 거절한 모델 (3.8 Flash — "Thinking level MINIMAL is not supported")


def gemini_choice(model: str, system: str, user: str, options: list[str], temperature: float = 0.0,
                  timeout: float = 30.0, retry_429: int = 5, image_jpeg_b64: str | None = None) -> tuple[str | None, float, dict]:
    """Gemini API 직접 호출 → (선택지, ms, 부가 정보). 답은 JSON 스키마 enum 으로 options 안에서만 나온다.
    생각은 최소 — 3.x 는 thinkingLevel, 2.x 는 thinkingBudget. 한도는 생각 토큰을 포함하므로 넉넉히 (256 이면 3.8 Flash 가 잘렸다).
    3.8 Flash 는 'minimal' 을 안 받아(400) 기본 생각으로 다시 보낸다 — 텍스트 프로브의 3.8 숫자도 사실 기본 생각이었다.
    image_jpeg_b64 가 있으면 이미지를 앞에 붙인다 (적 단계 판정용 스크린샷)."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None, 0.0, {"error": "GEMINI_API_KEY 없음 — 상위 폴더 .env 에 GEMINI_API_KEY=... 한 줄을 넣는다"}
    thinking = None if model in _NO_THINKING_CFG else ({"thinkingLevel": "minimal"} if model.startswith("gemini-3") else {"thinkingBudget": 0})
    parts =([{"inline_data": {"mime_type": "image/jpeg", "data": image_jpeg_b64}}] if image_jpeg_b64 else []) + [{"text": user}]
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 4096, "responseMimeType": "application/json",
                                 "responseSchema": {"type": "OBJECT", "properties": {"tactic": {"type": "STRING", "enum": list(options)}},
                                                    "required": ["tactic"]},
                                 **({"thinkingConfig": thinking} if thinking else {})}}
    t0 = time.perf_counter()
    for attempt in range(retry_429 + 2):     # +1 은 생각 설정 거절(400) 뒤 다시 보내는 몫 — 예전엔 429 몫을 같이 써서 retry_429=0 이면 못 보냈다
        req = urllib.request.Request(GEMINI_API.format(model=model), data=json.dumps(body).encode(), method="POST",
                                     headers={"x-goog-api-key": key, "Content-Type": "application/json"})
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read().decode())
            break
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:300]
            if e.code == 429 and attempt < retry_429:
                time.sleep(13.0)
                continue
            if e.code == 400 and "thinking" in msg.lower() and "thinkingConfig" in body["generationConfig"]:
                body["generationConfig"].pop("thinkingConfig")      # 이 모델이 그 생각 설정을 안 받으면 기본값으로
                _NO_THINKING_CFG.add(model)                         # 다음부턴 처음부터 빼고 보낸다
                continue
            return None, (time.perf_counter() - t0) * 1000, {"error": f"{e.code} {msg}"}
        except Exception as e:  # noqa: BLE001 — 네트워크·타임아웃 전부 "답 없음"
            return None, (time.perf_counter() - t0) * 1000, {"error": str(e)[:200]}
    else:
        return None, (time.perf_counter() - t0) * 1000, {"error": "429 재시도 초과"}
    ms = (time.perf_counter() - t0) * 1000
    parts = ((out.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    try:
        pick = json.loads(text[text.find("{"): text.rfind("}") + 1])["tactic"]
    except Exception:  # noqa: BLE001
        pick = None
    return (pick if pick in options else None), ms, {"usage": out.get("usageMetadata"), "raw": text[:80]}


# 봇의 gemini 팔이 쓰는 설명 — 폭탄 전술(bomb_stop·bomb_sprint)을 뺀 뒤의 선택지와 원칙 (사용자: 경계 중인 적은 폭탄을 피한다,
# 둘 이상 붙으면 빈 곳으로, 낭떠러지 옆에서 싸우면 죽는다). 12 상황 프로브(cloud_judge_probe)는 score_judge 의 넷짜리를 그대로 쓴다.
BOT_DESC = {
    "fight": "Stand and fight: block, then hit back. A firebomb is thrown only while an enemy is still unaware or is charging in, never while it is on guard.",
    "sprint": "Do not fight at all; sprint past everything.",
}
BOT_SYSTEM = ("You pick the tactic for a Dark Souls Remastered bot running from the Firelink Shrine bonfire to the Undead Merchant. "
              "Hollows are slow, but an alert hollow dodges a thrown firebomb. Principles from the player: enemies that block the path are "
              "cleared, not fled from; when two or more are on top of the bot it escapes to open ground and fights them one at a time; "
              "fighting next to a drop is how the bot dies; standing still under ranged fire from above is bad. Reply with the JSON object only.")


def user_text(state: dict, desc: dict | None = None) -> str:
    """desc 가 없으면 프로브와 같은 넷짜리 (score_judge), 있으면 그 선택지만."""
    if desc is None:
        return sj.prompt(state).split("<|im_start|>user\n")[1].split("<|im_end|>")[0]
    tactics = "\n".join(f"- {k}: {v}" for k, v in desc.items())
    return f"STATE:\n{json.dumps(state, ensure_ascii=False)}\n\nTACTICS:\n{tactics}"


def system_text(bot: bool = False) -> str:
    return BOT_SYSTEM if bot else sj.SYSTEM.replace("Answer with exactly one line: Tactic: <name>", "Reply with the JSON object only.")


class Tactician:
    """상황이 바뀔 때만 묻고(최소 간격 min_gap), 답은 스레드가 채운다. take() 로 새 답을 한 번 가져간다.
    물어보는 동안·실패하면 지금 전술을 그대로 둔다 (호출자가 기본 전술을 정한다)."""

    def __init__(self, options: list[str], model: str = MODEL, min_gap: float = 2.0, log=print, tag: str = ""):
        self.options, self.model, self.min_gap, self.log, self.tag = list(options), model, min_gap, log, tag
        self.busy = False
        self.last_ask = 0.0
        self.last_sig = None
        self._fresh: str | None = None
        self.calls: list[dict] = []          # 이번 판의 호출 기록 (결과 행에 붙인다)

    def maybe_ask(self, sig, state: dict) -> bool:
        """sig = 상황 요약 (바뀌었을 때만 묻는다). 적이 없는 상황은 호출자가 걸러서 부르지 않는다."""
        now = time.time()
        if sig == self.last_sig or self.busy or now - self.last_ask < self.min_gap:
            return False
        self.last_sig, self.last_ask, self.busy = sig, now, True
        threading.Thread(target=self._run, args=(state, sig), daemon=True).start()
        return True

    def _run(self, state: dict, sig) -> None:
        try:
            pick, ms, extra = gemini_choice(self.model, system_text(bot=True), user_text(state, {k: BOT_DESC[k] for k in self.options}),
                                           self.options, timeout=5.0, retry_429=0)
            row = {"t": round(time.time(), 2), "tag": self.tag, "model": self.model, "sig": list(sig) if isinstance(sig, tuple) else sig,
                   "pick": pick, "ms": round(ms), "state": state, **({"error": extra["error"]} if extra.get("error") else {}),
                   "usage": extra.get("usage")}
            self.calls.append({k: row[k] for k in ("t", "pick", "ms") if k in row} | ({"error": row["error"][:80]} if "error" in row else {}))
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if pick:
                self._fresh = pick
            self.log(f"  gemini: {pick} ({ms:.0f} ms, 적 {len(state.get('enemies', []))}){'  ' + extra['error'][:60] if extra.get('error') else ''}")
        finally:
            self.busy = False

    def take(self) -> str | None:
        p, self._fresh = self._fresh, None
        return p
