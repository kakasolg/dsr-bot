# Laya 섀도 모드 — 구조 분석 · 경계 · 평가 계획

2026-10-01 [win]. 목표: 로컬 판단 모델 [Laya](https://github.com/NandhaKishorM/laya)가 싸움 상태를 보고 **이미 구현된 전술 후보** 중 하나를 고르게 하되,
**기록만** 하고 패드·규칙에는 절대 반영하지 않는다. 미세조정·실제 반영은 범위 밖.

## 1. 지금 구조 (코드로 확인한 것)

| 무엇 | 어디 | 메모 |
|---|---|---|
| 게임 상태 읽기 | `dsr_telemetry.py` `Telemetry.snapshot()` → `Snapshot(player, chars)` | 메모리 읽기 전용. `env.make_telemetry` |
| 상태 정규화 (싸움) | `souls/duel.py` `_sense(F)` → `Tick(s, p, c, h, dy, a, now)` | 목표 따라가기·끼어든 적·원거리 우선, **끝 조건**(`low_hp`·`losing`·`crowd`·`stalemate`…)도 여기 |
| 싸움 판단 | `souls/duel.py` `RULES` (25개, 위에서 먼저 걸리는 순서) · `duel()` 루프 | 규칙 함수가 **판단과 실행을 한 번에** 함 (`F.mv.*` 호출 = 패드 입력). `prep_*`는 계산만 |
| 끝난 뒤 판단 | `souls/field.py` `Field.fight` → `recover`·`fall_back`·`back_to_wall` | 후퇴·에스트는 `DuelResult.result`로 Field가 결정 |
| 안전 규칙 | 규칙 안의 조건들: `_other_swinging`(옆 적 휘두르면 공격 안 함), `opening`(에스트 틈), `low_hp` 0이면 후퇴 없음(`desperate`), `BACKSTAB`/`HEAVY`(`--basic`), `_heavy_ok`, `T.room`(뒤 공간), `nav.ground_ahead`(낭떠러지) | 별도 '안전 계층' 모듈은 없음 — 조건이 규칙마다 흩어져 있음 |
| 반사 | `souls/reflex.py` `Reflex.tick` | 2.5 m 안 휘두름 → 막기/백스텝. 패드 입력 |
| 실제 입력 | `control.py` `Pad` (vgamepad, ViGEm 가상 360 패드) ← `souls/moves.py` `Moves` | 그 밖에 `camera.CamFollow`·`watch.Escape` 스레드도 패드를 씀 |
| 기록 | 로그 `data/runs/<시각>_<이름>.jsonl` + `.txt`, `track.Track`(2 Hz, `tm.listeners`, 읽기 전용), `blackbox.py`, 싸움 상태 줄(`Fight.note`, 1 s마다) | 상태 줄 = 거리·높이·적 애니·HP·SP·각도 + 그 1 s 동안 한 행동 횟수. 샘플 로그 70개에 3,120줄 |
| 오프라인 테스트 | `tests/duel_golden_test.py` — 47,000여 상황의 duel 결정 전부를 스냅샷과 비교 | 가짜 `Moves`가 모든 패드·이동 호출을 trace로 남김 → **판단이 바뀌었는지 정확히 알 수 있음** |

예전 실험: `experiments/jev.py` (Jev API·로컬 LLM, choice/score/noul 같은 모양, 엘든링 순찰용, 지금 봇은 안 씀).

## 2. Laya 패키지 (PyPI 0.3.23 휠을 받아 소스로 확인)

- `laya.load(repo, device=, revision=)` → `Agent`; `agent.predict(state, questions)` → `{"answers": {qid: {"choice", "probabilities", "confidence"}}, "usage": {...}}`
- 의존성(휠 메타데이터): `torch>=2.0`, `transformers>=4.48`, `safetensors`, `huggingface_hub`, `numpy`. **이 PC의 봇 venv에는 torch·transformers·laya 없음**
- 체크포인트: `convaiinnovations/laya` 루트(영어). 검토된 커밋 `PINNED_REVISIONS["convaiinnovations/laya"] = 55cf4c4e…` 로 고정해서 받음. 크기·파라미터 수(문서상 ModernBERT-large 421M, ~1.5 GB)는 **받기 전엔 미확인**
- 네트워크: 첫 `snapshot_download`만. 그 뒤는 `HF_HUB_OFFLINE=1`로 캐시만 씀. 핵심 경로(agent)에 다른 네트워크 호출 없음(소스 grep)
- `Router`는 언어별 체크포인트를 고르는 것뿐 — DSR 전투를 배운 모델이 아님. 이 작업은 Router를 안 쓰고 체크포인트를 직접 지정
- 영상의 0.12 s(M4 Pro)·Jev 0.56 s는 **이 프로젝트에서 잰 값이 아님**. 목표치로 쓰지 않음

## 3. 끼우는 경계 (가장 좁게)

```
snapshot → _sense(정규화) → RULES (기존 안전 조건 + 실행) ──→ 패드          ← 그대로
                                   │ 규칙이 동작한 틱마다 (실행 뒤)
                                   ▼
                 advisor.observe(F, T, 규칙 이름)   ← 읽기만, 예외 삼킴, put_nowait (꽉 차면 버림)
                                   ▼
             숫자 dict (관측값 + 허용 후보 + 규칙이 한 전술)
                                   ▼   stdin JSON 한 줄
             laya_worker.py (별도 프로세스, WSL Ubuntu venv)  → Laya 예측 → data/runs/<시각>.laya.jsonl
```

- `duel()`에 `advisor=None` 인자 하나, 루프에 `if advisor is not None:` 두 곳. `Field.fight`가 `self.advisor`를 넘김. `run.py --laya-shadow`일 때만 만듦. 기본값은 None → **골든 테스트 47,000여 상황이 그대로여야 함**
- 돌려받는 길이 없음: 워커는 파일에만 쓰고, 봇 쪽은 워커 출력을 읽지 않음. advisor는 `F.mv`·패드를 건드리지 않음 (테스트로 확인)
- 별도 프로세스인 이유: torch가 봇 프로세스에 들어오면 GIL·메모리·크래시가 판단 루프(초당 21~25 틱)를 흔들 수 있음. 워커가 죽거나 느리면 큐가 넘쳐 버려질 뿐
- 별도 venv인 이유: 봇 venv·`requirements-lock.txt`·CI를 안 바꿈

## 4. Laya 입력/출력

**상태** (관측값만, 이미 봇이 읽는 것. 적의 의도·다음 공격 예측은 넣지 않음):
`my_hp_pct`, `my_stamina_pct`, `stamina_for_attack`, `target_kind`(망자/방패병/원거리…, `foes.py`), `target_state`(idle/swinging/staggered/guard_broken/downed/asleep — 애니 번호 범위), `target_swing_age_s`, `target_hp_pct`, `target_one_hit`, `distance_m`, `height_diff_m`, `weapon_reach_m`, `in_reach`, `facing_error_deg`, `target_facing_me_deg`, `others_within_4_5m`, `other_swinging_near`, `estus_wanted`, `estus_opening`, `taken_this_fight_pct`, 봇 자신의 설정 `fighting_style`·`let_it_come`(wait_far)

**후보** (이미 있는 규칙 묶음 → 전술 이름), 기존 조건으로 **먼저 거른 것만** 질문에 넣음:

| 전술 | 규칙 | 허용 조건 (기존 규칙의 조건에서) |
|---|---|---|
| attack | finish_first · hit_first · stagger_punish · finish · attack · early_kick | 닿는 거리+0.3 안, 높이 1 m 안, SP ≥ 무기 sp_min (한 방이면 15), 옆 적이 안 휘두름 (한 방이면 무관) |
| guard | reflex · block · late_windup_block · downed · (arena 없는) edge | 방패 스타일 |
| evade | reflex (백스텝 스타일) | `style.evade` |
| approach | approach | 닿는 거리 밖 |
| hold_position | wait_far · stamina | 늘 |
| heal | estus | `care.wants` (에스트 남음 + HP 기준) |
| reposition | lure · edge | arena·NavMesh 있음 |
| retreat | (끝 조건 `low_hp`·`losing`·`crowd`) | `low_hp > 0` (끝까지 싸우기 모드가 아님) |
| backstab | backstab · backstab_swing | `T.room` (`BACKSTAB` 켜짐 + 뒤 공간 + 1:1) — `--basic`이면 늘 빠짐 |

방향 돌기(`face_first`·`face`)·떼어놓기·백스텝 스타일 대기는 비교에서 뺌(전술이 아니라 준비 동작 또는 드묾).
**판단 보류** = confidence < `min_conf`(기본 0.5)이면 abstain.

**출력 행**: 규칙 이름·규칙 전술·허용 후보·Laya 선택·확률·confidence·상태(ok/abstain/invalid/error)·시간(봇 쪽 상태 만들기, 큐, 워커 준비, 추론, 합계).

## 5. 오프라인 평가 (게임 없음)

데이터 셋 둘 + 나중에 하나:
1. **golden** — `duel_golden_test`의 상황을 advisor를 붙여 돌려 (상태, 규칙 전술)을 정확히 얻음. 격자 상황이라 실제 분포와 다름
2. **logs** — `data/samples/*.txt`의 싸움 상태 줄. 실제 분포지만 관측값 일부만(옆 적·에스트 없음), 라벨은 그 1 s에 가장 많이 한 전술(둘 이상 섞이면 `mixed`로 따로 셈)
3. (게임 확인 허락 뒤) **shadow** — `--laya-shadow` 실행의 `.laya.jsonl`

나누기: 같은 장면의 거의 같은 프레임이 양쪽에 안 가게 **묶음 단위**로 dev/test (golden: 적 종류·애니·거리 묶음, logs: 실행 파일 단위, shadow: 실행 단위). 같은 (상태, 후보, 라벨)은 하나로 줄임.
지금은 학습을 안 하므로 dev는 임계값(min_conf) 고르기·실패 사례 보기에만 쓰고 숫자는 test로 보고.

측정: 규칙과 일치율(비교 가능한 것만) · 다수 클래스 기준선 · 혼동표 · **금지 후보 제안율**(허용 밖·잘못된 출력) · **규칙 행동이 마스크 밖인 비율**(마스크가 너무 좁은지) · 판단 보류율과 보류 임계값별 일치율/범위 · 라벨별 사례 수·실패 사례 · 시간 p50/p95 (상태 준비·추론·합계).
일치율 하나로 성공을 말하지 않음 — 규칙 자체가 정답이 아니고(P-29·P-30처럼 규칙이 틀린 장면이 있음), 일치율이 높아도 '규칙 흉내'일 뿐.

## 6. 설치·다운로드 — WSL Ubuntu ([MoKa] 2026-10-01 제안, 승인 전 — 아직 안 함)

WSL Ubuntu(WSL2, Python 3.12.3, RTX 5080·드라이버 610.88이 WSL 안에서 보임, 여유 830 GB)에 둠. 봇 venv·`requirements-lock.txt`·CI는 그대로.
봇은 `wsl -e sh -c 'exec "$HOME/laya-venv/bin/python" "$@"' sh /mnt/d/dev/dsr-bot/laya_worker.py --out /mnt/d/…`로 워커를 띄움 (`laya_shadow.worker_cmd`).

```
wsl -e bash -lc 'python3 -m venv ~/laya-venv && ~/laya-venv/bin/pip install -U pip'
wsl -e bash -lc '~/laya-venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cu128'
wsl -e bash -lc '~/laya-venv/bin/pip install laya==0.3.23'
wsl -e bash -lc 'cd /mnt/d/dev/dsr-bot && ~/laya-venv/bin/python laya_worker.py --download'     ← 체크포인트, 이때만 네트워크
```
추정(받기 전이라 미확인): torch CUDA 휠 ~3 GB(설치 후 ~5~6 GB, nvidia 라이브러리 포함), transformers 등 ~0.3 GB, 체크포인트 ~1.5~1.7 GB. 시간: 회선에 따라 10~20분. 학습 없음.

WSL에서 달라지는 점 (재 본 것):
- 전달: 가짜 백엔드 워커를 WSL 기본 python3로 띄워 200건 — 버림 0, 봇 쪽 offer 최악 1.09 ms, 큐+전송 p50 0.24 ms·p95 0.57 ms. 단 **Windows와 WSL은 시계가 둘**이라 `queue_ms`·`total_ms`는 근사(`clock_cross`). `infer_ms`는 워커 안 시계라 정확
- `wsl.exe` 시작 ~70 ms (실행 시작 때 한 번)
- 워커 우선순위: Windows 쪽 `BELOW_NORMAL`은 `wsl.exe`에만 걸리고 WSL VM 안 계산엔 안 걸림 — 게임 프레임에 영향이 있는지는 게임 실행으로만 앎 (허락 뒤)
- 오프라인 평가 점수 매기기도 WSL에서: `wsl -e bash -lc 'cd /mnt/d/dev/dsr-bot && ~/laya-venv/bin/python laya_eval.py score data/laya/cases_golden.jsonl --device cuda'` (`laya_eval`·`laya_shadow`는 표준 라이브러리만 import)

## 8. 지금까지 결과 (2026-10-01, 모델 없이)

- 바뀐 동작 없음: `python tests/duel_golden_test.py` 40,320 상황 그대로. `tests/laya_shadow_test.py`: 골든 10,080 상황을 advisor 3가지(정상 기록·보내기 실패·특징 계산 실패)로 돌려 trace(모든 Moves·패드 호출·로그·결과)가 advisor 없을 때와 같음, 그동안 `F.mv`를 만지면 실패하는 가짜로 바꿔 둠 → 접근 0. 느린 워커(0.3 s)에 60건: offer 최악 0.08 ms, 새것만 남기고 버림. 모델·워커 없음: 오류 한 줄 기록, 싸움 쪽 영향 없음. 전체 pytest 52 통과
- 마스크 점검 (golden 58,432 틱 → 서로 다른 11,620, test 묶음 8,126): 처음엔 규칙 행동의 21.7 %가 마스크 밖 → 원인은 마스크(백스텝 스타일의 반사는 막기가 아니라 백스텝, arena 없는 `rule_edge`는 제자리 막기) → 고친 뒤 1.6 %, 남은 건 둘: (1) golden의 가짜 반사는 안 터져서 옆 적이 휘두를 때 `rule_attack` (게임에선 반사가 먼저) (2) **`rule_finish`가 닿는 거리 밖(2.2~4.0 m)에서 침** — 뒤잡기 기회면 `rule_approach`를 건너뛰기 때문 → ROADMAP P-31. logs 0.3 %
- 일치율 상한: golden은 같은 상태·후보에 규칙 전술이 둘 이상인 사례가 75 % — 가짜 반사 켜짐/꺼짐·`back`처럼 상태에 안 보이는 격자 축 때문. 그래서 golden 일치율은 '규칙 흉내' 정도로만 읽어야 함. logs는 0.4 %지만 1 s 안에 전술이 섞인 줄이 56 %라 비교에서 빠짐
- 기준선 (test): 가짜 백엔드 'guard가 후보에 있으면 guard, 없으면 첫 후보' golden 49.6 % · logs 38.9 %, 늘 같은 답(다수 클래스) golden 28.1 % · logs 38.9 %, 후보 중 무작위 golden 23.8 % · logs 20.8 % — Laya 숫자는 이 셋과 같이 봐야 함 (마스크만으로 이미 절반 가까이 맞힘)
## 9. 실제 Laya 결과 (2026-10-01, [MoKa] 설치 승인 뒤)

**환경**: WSL2 Ubuntu (커널 6.6.114.1), Python 3.12.3, `~/laya-venv` 6.9 GB — torch 2.11.0+cu128 · transformers 5.18.0 · laya 0.3.23. RTX 5080 16 GB(드라이버 610.88), CPU i9-13900K(WSL vCPU 32). 게임은 안 켬.
**체크포인트**: `convaiinnovations/laya` 루트(영어), 커밋 `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`, `model.safetensors` 804 MB, ModernBERT 28층·hidden 1024, **421.3 M 파라미터**. 로드 1.9 s(캐시, 오프라인), 첫 다운로드 포함 31.7 s.
로드 때 경고: "체크포인트의 choice 11개 이상 온도 값이 잘못됨 → 0.5로 대체, 해당 confidence는 보정 안 됨" — 우리 후보는 많아야 9개라 해당 없음으로 봄(추정).

**결과 (test 묶음, CUDA)** — 금지·잘못된 제안 **0**, 상태 잘림 0 (상태 토큰 p50 golden 206·logs 94):
| | golden test (8,126) | logs test (1,016 비교 가능) |
|---|---|---|
| 보류율 (`confidence` < 0.5) | **99.9 %** | **99.9 %** |
| 보류 없이 답했을 때 규칙과 일치 | 45.9 % | 38.4 % |
| 늘 같은 답 / 후보 중 무작위 | 28.1 % / 23.8 % | 38.9 % / 20.8 % |
| 단순 규칙 'guard 우선' (가짜 백엔드) | 49.6 % | 38.9 % |
| `top_p` ≥ 0.4로 거르면 (범위 · 일치) | 29.9 % · 52.3 % | 40.0 % · 40.1 % |

라벨별 (golden test, 보류 무시): guard 1,920/2,284 · evade 1,045/1,848 · attack 438/655 · hold_position 328/1,360 · **approach 0/1,537** · backstab 0/332 · heal 0/40 · reposition 0/70. logs: hold_position 238/254 · attack 146/148 · **guard 0/395** · approach 0/136.
→ Laya는 후보 9개 중 4~5개만 답하고, **approach는 6,958번 후보에 있었지만 한 번도 안 고름**. 일치율은 '늘 같은 답'(logs)·'guard 우선'(golden) 기준선과 같거나 낮음.

**실패 원인 점검** (dev·무작위 표본):
- `confidence`는 선택지 확률이 아니라 Laya의 보정값(중앙 0.05). 선택지 확률은 `answer_confidence`(= `top_p`, 예: 후보 4개 중 0.40) — 둘 다 기록하게 고침. 하지만 `top_p`로 걸러도 logs 일치율은 안 오름 → 확률이 판단 품질을 가르지 못함
- **후보 순서에 민감**: 같은 상태·후보를 순서만 뒤집으면 200건 중 86건(43 %)의 답이 바뀜. 정방향에선 첫 후보를 82 % 고름
- 상태는 읽음: 상태를 "정보 없음"으로 바꾸면 100건 중 76건의 답이 바뀜
- 상태를 영어 문장으로 줘 봄 (dev 300건씩): golden 40.7 → 48.7 %, logs 41.3 → 26.3 % — 엇갈림, dict 유지

**지연시간** (단일 요청, 배치 없음):
| | p50 | p95 | 최대 | n |
|---|---|---|---|---|
| CUDA 추론 (채점, golden test) | 19.8 ms | 21.6 ms | 25.3 ms | 8,126 |
| CUDA 추론 (채점, logs test) | 18.9 ms | 20.7 ms | 56.1 ms | 2,287 |
| CUDA 실제 경로 (Windows `WorkerChannel` → WSL 워커, 5 Hz 300건, 버림 0) — 요청→답 | 23.7 ms | 44.0 ms | 402 ms | 300 |
| CPU 추론 (logs 500건) | 321~333 ms | 393~396 ms | 618 ms | 500 |
| 봇 쪽 상태 준비 · offer | 0.01 ms · 최악 0.30 ms | | | |
실제 경로 측정은 CPU 채점이 같이 돌던 때라 p95가 넓을 수 있음, 최대 402 ms는 첫 요청. 게임이 GPU를 쓰는 중의 값은 아님 — 게임 실행에서만 앎.

**판단**: 경로(섀도·격리·지연)는 쓸 만함 — CUDA p95 ~22~44 ms는 싸움 틱(~45 ms)과 비슷한 크기. **모델 판단은 이대로는 쓸 수 없음**: 보류 99.9 %, 기준선 수준 일치, approach를 전혀 안 고름, 후보 순서에 따라 답이 43 % 바뀜. 영상의 0.12 s와는 다른 환경이고 이 숫자로 비교하지 않음.
다음 단계 후보 (결정은 [MoKa]): (a) 여기서 멈추고 경로만 남김 (b) 질문을 전술 하나 고르기 대신 noul 여러 개("지금 막아야 하나?")로 나눠 순서 민감도를 없애고 다시 평가 — 미세조정 없음 (c) 미세조정 — 이번 범위 밖. 게임 섀도 실행(`--laya-shadow`)은 (b)든 무엇이든 정한 뒤, 허락받고

## 7. 다음 단계로 넘어가기 전 기준 (제안)

- 골든 테스트 그대로 · 섀도 켠 게임 실행에서 판단 공백(`blind_report.py`)·틱 수가 끈 실행과 차이 없음
- 금지 후보 제안 0 · 잘못된 출력 0
- 추론 p95가 싸움 틱 간격(~45 ms)과 견줄 만한지 — 아니면 '틱마다 조언'은 불가, '이벤트마다'만 가능
- 일치율은 다수 클래스 기준선보다 뚜렷이 높고, 불일치 사례를 [MoKa]가 봤을 때 Laya 쪽이 나은 장면이 있는지 (규칙이 틀린 P-기록 장면 위주)
