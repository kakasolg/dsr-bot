"""
클라우드 판단 모델 프로브 — 로컬 Qwen3-4B 가 탈락한 같은 12 상황(score_judge.SCENARIOS)을 Vercel AI Gateway 로 잰다.

  .venv-llm\\Scripts\\python.exe cloud_judge_probe.py          (키: 상위 폴더 .env 의 AI_GATEWAY_API_KEY — Jev 와 같은 키)

  .venv-llm\\Scripts\\python.exe cloud_judge_probe.py <모델> ...   (모델만 골라서)

모델: google/gemini-3.5-flash-lite (VersionSandbox 에서 승급 대상으로 쓴 것), google/gemma-4-26b-a4b-it (클라우드 Gemma),
      typesafe-ai/jev (choice 확률을 돌려주는 판단 모델).
      실행해 보니 3.5·3.1 Flash-Lite 는 게이트웨이 무료 등급에서 403 — 무료로 열리는 google/gemini-2.5-flash-lite 로 대신 잰다.
      Gemma 26B 는 분당 5회 한도(429) — 기다렸다 재시도한다.

── 사전 등록 (2026-09-22, 실행 전) ──────────────────────────────
 (1) 그리디(온도 0) 답이 기대 답과 10개 중 8개 이상 일치 — 로컬과 같은 선
 (2) 신뢰도가 모호한 상황(s06·s09)에서 더 낮다
       Gemini·Gemma: 그리디와 온도 1 샘플 3개의 일치 수 (VersionSandbox: 그리디 대비 불일치가 신호였다, 패스끼리 일치는 아니었다)
       Jev: 돌려주는 choice 확률의 1·2등 차
 (3) 그리디 한 번의 지연 p50 < 1000 ms — 로컬(300 ms)보다 느슨한 것은 이 자리가 반사가 아니라 교전 단위 판단이라서
 판정: 셋 다 통과한 모델만 "교전 단위 전술 제안"(톰슨 샘플링의 상황별 보조) 후보. (1) 미달이면 쓰지 않는다.
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
for line in (ROOT.parent / ".env").read_text(encoding="utf-8").splitlines():   # dotenv 없이 (이 venv 엔 없다)
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import jev             # noqa: E402
import score_judge as sj  # noqa: E402

GW = "https://ai-gateway.vercel.sh/v1/chat/completions"
KEY = os.environ["AI_GATEWAY_API_KEY"]
MODELS = ["google/gemini-2.5-flash-lite", "google/gemma-4-26b-a4b-it", "typesafe-ai/jev"]
SAMPLES = 3
LOG = ROOT / "data" / "cloud_judge_probe.jsonl"


def chat(model: str, state: dict, temperature: float) -> tuple[str | None, float, dict]:
    user = sj.prompt(state).split("<|im_start|>user\n")[1].split("<|im_end|>")[0]
    body = {"model": model, "temperature": temperature, "max_tokens": 60,
            "messages": [{"role": "system", "content": sj.SYSTEM.replace("Answer with exactly one line: Tactic: <name>", "Reply with the JSON object only.")},
                         {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "t", "strict": True, "schema": {
                "type": "object", "properties": {"tactic": {"type": "string", "enum": list(sj.TACTICS)}},
                "required": ["tactic"], "additionalProperties": False}}}}
    req = urllib.request.Request(GW, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    for attempt in range(6):
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                out = json.loads(r.read().decode())
            break
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:200]
            if e.code == 429 and attempt < 5:          # 분당 한도 — 지연에는 넣지 않고 기다렸다 다시
                time.sleep(13.0)
                continue
            return None, (time.perf_counter() - t0) * 1000, {"error": f"{e.code} {msg}"}
        except Exception as e:  # noqa: BLE001
            return None, (time.perf_counter() - t0) * 1000, {"error": str(e)[:200]}
    ms = (time.perf_counter() - t0) * 1000
    c = out["choices"][0]["message"].get("content") or ""
    try:
        pick = json.loads(c[c.find("{"): c.rfind("}") + 1])["tactic"]
    except Exception:  # noqa: BLE001
        pick = None
    return pick, ms, {"usage": out.get("usage"), "raw": c[:80]}


def chat_direct(model: str, state: dict, temperature: float) -> tuple[str | None, float, dict]:
    """Gemini API 직접 (게이트웨이 무료 등급에서 3.x 가 403 이라). 모델 이름은 "gemini-direct:<모델>" — 봇이 쓰는 것과 같은 호출(tactic_llm)."""
    import tactic_llm
    return tactic_llm.gemini_choice(model.split(":", 1)[1], tactic_llm.system_text(), tactic_llm.user_text(state),
                                    list(sj.TACTICS), temperature=temperature)


def jev_pick(state: dict) -> tuple[str | None, float, dict]:
    q = {"tactic": {"type": "choice", "instructions": "Which tactic should the bot use in this situation?", "criteria": sj.TACTICS}}
    t0 = time.perf_counter()
    a = jev.ask({"context": sj.SYSTEM.split(" Answer with")[0], **state}, q, tag="tactic-probe")
    ms = (time.perf_counter() - t0) * 1000
    if not a or "tactic" not in a:
        return None, ms, {"error": "no answer"}
    return a["tactic"].get("choice"), ms, {"confidence": a["tactic"].get("confidence"), "probs": a["tactic"].get("probabilities")}


def main() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    summary = {}
    for model in (sys.argv[1:] or MODELS):
        print(f"\n═══ {model}")
        hits, n_exp, lat, conf_hit, conf_amb, rows, errors = 0, 0, [], [], [], [], 0
        for label, state, expect in sj.SCENARIOS:
            if model == "typesafe-ai/jev":
                pick, ms, extra = jev_pick(state)
                probs = sorted((extra.get("probs") or {}).values(), reverse=True)
                conf = (probs[0] - probs[1]) if len(probs) >= 2 else (probs[0] if probs else None)
                conf_txt = f"확률차 {conf:.2f}" if conf is not None else "확률 없음"
            else:
                call = chat_direct if model.startswith("gemini-direct:") else chat
                pick, ms, extra = call(model, state, 0.0)
                samples = [call(model, state, 1.0)[0] for _ in range(SAMPLES)]
                conf = sum(s == pick for s in samples) if pick else None
                conf_txt = f"샘플 일치 {conf}/{SAMPLES} {samples}"
            if extra.get("error"):
                errors += 1                          # 응답이 없으면 지연·일치 어디에도 넣지 않는다 (에러 응답 시간을 지연으로 재면 안 된다)
            else:
                lat.append(ms)
            ok = None if expect is None else (pick in expect)
            if expect is not None:
                n_exp += 1
                hits += bool(ok)
                if ok and conf is not None:
                    conf_hit.append(conf)
            elif conf is not None:
                conf_amb.append(conf)
            mark = "·" if ok is None else ("O" if ok else "X")
            print(f"  {label:<28} 기대 {'/'.join(sorted(expect)) if expect else '(모호)':<18} 답 {str(pick):<12} {ms:6.0f} ms  {conf_txt}  {mark}"
                  + (f"  {extra['error']}" if extra.get("error") else ""), flush=True)
            rows.append({"model": model, "scenario": label, "pick": pick, "expect": sorted(expect) if expect else None, "ms": round(ms),
                         "conf": conf, **{k: v for k, v in extra.items() if k in ("usage", "probs", "error")}})
        with LOG.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({"t": time.time(), **r}, ensure_ascii=False) + "\n")
        p50 = st.median(lat) if lat else float("nan")
        c1 = hits >= 8
        c2 = bool(conf_hit and conf_amb) and st.mean(conf_amb) < st.mean(conf_hit)
        c3 = p50 < 1000
        summary[model] = (hits, n_exp, c1, c2, c3, p50, errors)
        print(f"  → 일치 {hits}/{n_exp}  신뢰도 평균: 일치 {st.mean(conf_hit) if conf_hit else float('nan'):.2f} / 모호 {st.mean(conf_amb) if conf_amb else float('nan'):.2f}"
              f"  그리디 지연 p50 {p50:.0f} ms")
    print("\n═══ 판정 (사전 등록)")
    for m, (hits, n_exp, c1, c2, c3, p50, errors) in summary.items():
        if errors:
            print(f"  {m:<32} 측정 불완전 — 에러 {errors}/12 (판정 안 함)")
            continue
        print(f"  {m:<32} (1) {hits}/{n_exp} {'통과' if c1 else '미달'}  (2) {'통과' if c2 else '미달'}  (3) p50 {p50:.0f} ms {'통과' if c3 else '미달'}"
              f"  → {'후보' if c1 and c2 and c3 else '쓰지 않음'}")


if __name__ == "__main__":
    main()
