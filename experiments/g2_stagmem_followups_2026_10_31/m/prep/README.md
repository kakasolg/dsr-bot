# 기록 여부 대조군 M — 준비만 (2026-10-31, [cloud])

**상태: 준비 단계.**
- 학습, 예측, scene_replay, 게임 실행은 하지 않았다.
- 저장소 밖(`/tmp/stagmem_m/prep`)과 그 압축 묶음에만 있다. 원격 보존이 아니다.
- `/tmp/stagmem`과 감사 산출물(`/tmp/spaudit_consts`)은 읽기만 했다. 해시는 그대로다.

## 1. 정정 요약 (기존 결과 파일은 덮어쓰지 않음)

**유지할 것**
- rule 라벨 재현 지표(정확도, macro F1, 클래스별)는 그대로다.
- 대상: 기준선 · I1 RF(79742de) · C3–C4(798e2ac) · I1–I2(ff72b45) · 휘청 기억 A/B(`/tmp/stagmem/run`).

**명시할 것**
- B가 stagger_punish를 새로 맞힌 35장면은 **모두 휘청늦음 가드 분기**다. 방패를 들고 정면을 유지하는 분기이고, 실제 반격이 아니다.
- 실행별로는 4실행: 011929 20 · 061331 9 · 060542 5 · 183926 1.
- 평가 split의 stagger_punish 101장면 구성:
  - 가드 95
  - 실제 공격 1 (shift_zone 190105, A·B 모두 오답)
  - P-80 이전 코드 5 (가드 분기가 없는 코드)
- 근거: 분기 감사 (`/tmp/spaudit_consts/rows.json`, sha256 `46ef3608…cd29`).

**tactic_map(`stagger_punish` → attack)의 영향 범위**
- 이 매핑을 쓰는 곳은 **I1 RF 실험(79742de)뿐**이다.
  - `config.json`의 `tactic_map`
  - `rf_i1current.py`의 `tactic()`
  - `results.json`의 `variants.{base,no_dirty_duel_train}.eval.*.tactic_aux` (acc · macro F1 · per_class · confusion)
- 정답 쪽 영향:
  - test: 20장면, shift_zone: 70장면, shift_ref: 5장면이 실제로는 guard인데 attack으로 셈해졌다.
  - shift_ref_no_dirty_duel도 shift_ref와 같은 실행(212954)이 들어 있어 영향을 받는다.
  - val에는 가드 분기 정답이 0이라 정답 쪽은 영향이 없다.
- 예측 쪽 영향:
  - 예측된 stagger_punish도 attack으로 셈했다. base 기준 예측 stagger_punish 95건 중 54건이 가드 분기 정답 장면에 놓여 있다.
  - 정답 장면이 아닌 곳에서 예측된 stagger_punish가 어느 분기였을지는 알 수 없다.
- 영향을 받지 않는 것:
  - 기준선, C3–C4, I1–I2, 휘청 기억 A/B, 조건별 감사, reflex 감사는 tactic을 계산하지 않았다.
  - `g2_i1current_rf_2026_10_31/audit/metric_consistency.md` 49행의 "val guard 전술 합계 17"은 val에 가드 분기 정답이 없으므로 그대로다.
- 대화 보고 중 "tactic 보조 지표"를 인용한 부분과 "stagger_punish 개선 = 공격 판단 재현"으로 읽힌 부분은 정정 대상이다.

## 2. 후속 비교 설계

| 조건 | 열 | 학습 |
|---|---|---|
| A | 기존 현재 관측 61열 | **재사용** (`/tmp/stagmem/run/predictions.jsonl` `y_pred_A`) |
| M | A 61열 + `rec_stag_ptr_key`, `rec_stag_t_key` = 63열 | **새로 학습** (승인 뒤) |
| B | A + 휘청 기억 6열 = 67열 | **재사용** (`y_pred_B`) |

**M에 넣는 것과 넣지 않는 것**
- M에 넣는 것은 키가 있는지(0/1)뿐이다.
- 넣지 않는 것: 포인터 값, None 여부, 표적 일치, 경과 시간, B의 `__missing` 열.
- 두 키는 항상 같이 나타나지 않는다. train에서 (ptr 키, t 키)는 다음과 같다:

| (ptr 키, t 키) | train scene |
|---|---|
| (0, 0) | 601 |
| (1, 0) | 63 |
| (1, 1) | 66 |
| (0, 1) | 0 |

그래서 열 두 개를 둔다.

**M의 성격 (명시)**
- M은 **원본 필드 기록 여부 대조군**이다. 순수한 코드 버전 대조군이 아니다.
  - `_stag_ptr` 키는 93dce7b 이후 코드에서, 그 싸움에서 `prep_reflex`가 한 번이라도 돌면 생긴다.
  - 그래서 키가 없다는 것은 "옛 코드"이거나 "싸움 첫 틱들"이다.
- `_stag_t` 키는 그 싸움에서 휘청 연속 구간이 한 번 시작되어야 생긴다. 이것은 **기억 내용**이기도 하다.
- 따라서 M과 B의 차이를 "기억 내용만의 효과"로, A와 M의 차이를 "버전만의 효과"로 읽을 수 없다.

## 3. 비교 가능성 확인 (prepare에서 수행, 모두 통과)

**참조 해시**
- `/tmp/stagmem`의 config, 스크립트, prep_report, results, predictions와 감사 rows가 기록값과 같다.

**학습 경로**
- M은 `stagmem_compare.setup`을 그대로 불러 같은 데이터, 같은 해시 검사, 같은 I1 인코더(train만 fit), 같은 행 순서를 쓴다.
- 모델 설정도 같다: max_features=None, seed 20261031, n_jobs 1.

**행렬과 연결**
- 5 split 모두에서 M의 앞 61열이 A와 같고, 저장된 B의 앞 61열과도 같다.
- M의 추가 열은 0/1이고 NaN이 없다.
- 저장 예측 723행이 평가 split과 정답에 모두 연결된다.
- 저장 예측으로 다시 계산한 A·B 지표(acc, macro F1 두 종류, 실행별 평균)가 저장된 results와 8/8 같다.

**재사용의 한계**
- A를 다시 학습해서 같은 예측이 나오는지는 확인하지 않았다(학습 금지).
- 같은 seed, n_jobs 1, 같은 venv라는 전제에 기댄다. 이 venv에서 앞서 I1을 다시 학습했을 때 보존된 C3 예측과 0건 차이로 같았다(sqrt 설정).

## 4. 평가 계획 (`config.json` `evaluation`, 학습 승인 뒤)

**split별 지표**
- 대상: val · test · shift_zone · shift_ref, 그리고 A(저장) · M · B(저장) 각각.
- 지표: 정확도, macro F1 두 종류와 label 목록, 클래스별 지표, 실행별 정확도와 단순 평균.
- 짝비교: A–M, M–B, A–B를 split별·실행별로.

**기록 있음/없음별 결과**
- 기준은 장면별 `_stag_ptr` 키 존재다. (ptr, t) 상태별로도 나눈다.

| split | 기록 있음 (scene / 실행) | 기록 없음 (scene / 실행) |
|---|---|---|
| val | 0 / 0 | 134 / 5 |
| test | 67 / 1 | 166 / 7 |
| shift_zone | 269 / 8 | 23 / 8 |
| shift_ref | 63 / 8 | 1 / 1 |

shift 쪽의 "기록 없음"은 각 싸움의 첫 틱들이다.

**감사 집합에서 M의 위치**
- 대상 집합: 가드 95 · 개선 35 · 핵심 조건 24 · 실제 공격 1.
- A·M·B 각각의 정답 수를 보고한다.
- 개선 35장면에서는 M이 B처럼 맞혔는지, A처럼 틀렸는지를 센다.
- 핵심 조건 24장면과 개선 35장면은 212954 제외로도 따로 본다.

**시간 경계 장면 7개** (경과 + startup + 0.1과 stagger_s의 차이가 0.05초 이내)
- 장면별로 따로 표시한다.
- 목록: 011929 3143·3294 · 060542 2291·2293 · 061331 2303 · 183926 7655 · 185234 2916

**주장하지 않을 것**
- 평가 split의 실제 공격은 1장면뿐이다. 공격 성능 개선은 주장하지 않는다.
- 유의성, 인과, 게임 성능, 기억 내용과 버전의 분리도 주장하지 않는다.

## 파일

| 파일 | 내용 |
|---|---|
| `config.json` | 설계, 참조 해시, 모델, 평가 계획 |
| `stagmem_m.py` | `prepare`(fit·predict 차단) / `train`(`--approved TRAINING-APPROVED-M` 필요, M만 학습) |
| `prep_report_M.json` | 검사 결과, 감사 집합 장면 목록, 기록 여부 수 |
| `prerun_hashes.txt` | prepare 실행 전 config와 스크립트 해시 |
| `commands.txt` | 실행 명령 |
| `env_python.txt`, `env_pip_freeze.txt` | 환경 |
| `SHA256SUMS` | 해시 |
