# G2 scene 규칙 분류 — I1-current RandomForest (2026-10-31, [cloud])

## 목적과 범위

선별 저장된 G2 scene의 **현재 세계 관측만(I1-current)**으로 과거 봇이 고른 규칙(`selected_rule`)을 재현하는 작은 분류기를 만들고,
보존된 기준선(`experiments/g2_scene_baselines_2026_10_31/`, 커밋 `ca6b7f05`)과 비교한 기록이다.

- **게임 성능 평가가 아니다.** 정답은 그 버전 규칙의 출력이고, 일치율은 "과거 규칙과 같은 것을 골랐다"는 뜻일 뿐이다.
- **블라인드 시험이 아니다.** 기준선의 test/shift 결과를 이미 본 뒤에 설계한 후속 비교다.
  다만 설정과 후보 선택은 train/val만으로 했고, test/shift 결과를 보고 바꾼 설정은 없다.
- 결과는 "선별 저장된 장면의 분포" 안에서만 유효하다.

## 참조 (복제하지 않음)

| 자료 | 위치 | SHA-256 |
|---|---|---|
| 추출본 | `data/inventory/2026-10-31/g2_scene_extract.jsonl` @6ccafc0 | `c0a31ceb8f8c733c0df043b076536c1d7045900ebec656a5ed44041527f3ea35` |
| manifest | `data/inventory/2026-10-31/g2_scene_manifest_scenes.jsonl` @6ccafc0 | `3de0c325098b0358792b648aa1e1de5b079f591760ad94cfa3b39925e5eceec3` |
| 기준선 결과 | `experiments/g2_scene_baselines_2026_10_31/results.json` @ca6b7f05d9f184c56d7fce97dab94b833e451fc9 | `37b91a0a119c9a6c57ef673a52e3da1ed2aad6b0037e776d24cb322257f9db2e` |

스크립트는 추출본·manifest·기준선의 해시를 `config.json`의 값과 대조하고, 다르면 멈춘다.

## 분할

| split | 실행 / scene | 사용 |
|---|---|---|
| train | 26 / 730 | 학습 |
| val | 5 / 134 | 후보 선택 |
| test | 7 / 233 | 평가 |
| shift_zone | 8 / 292 | 평가 |
| shift_ref | 8 / 64 | 평가 (참고) |
| shift_ref_no_dirty_duel | 7 / 61 | 평가 (`20261019_232719` 제외) |
| pending | 1 / 22 | 학습·평가 모두 제외 |

민감도 분석: 선택된 설정 그대로 train에서 `20261012_075054_burg-upper`(미커밋 diff가 duel.py를 바꾼 실행)를 빼고 한 번 더 학습했다(25 / 712).

## 입력 (I1-current) — 정의는 `config.json` `features`

**수치 24개** (단위는 m, deg, HP/SP)
- 내 HP·최대·비율, SP·최대·비율
- 표적 HP·최대·비율, SP·최대·비율
- 표적 수평 거리 `tick.h`, 높이차 `tick.dy`
- 내 시선 기준 표적의 각도(절댓값·부호), 표적 시선 기준 내 각도(절댓값)
  - 봇의 `souls/moves.py` `rel_angle` 규약을 그대로 사용. 봇도 적에게 같은 규약을 쓴다(`duel.py:112,1581,1685`).
- 2.5 / 4 / 8 / 25 m 안의 적대 개체 수
- 표적 외 가장 가까운 적과 두 번째 적의 수평 거리
- 4 m 안에서 공격 애니(3000~3499) 중인 다른 적 수
- 결측 가능 필드 6개는 NaN 그대로 두고 `__missing` 표시 열을 따로 둔다(0과 구분).

**범주 4개** (one-hot)
- 내 애니 ID, 표적 애니 ID, 표적 애니 범주(기준선과 같은 정의), 무기 ID
- train에서 5회 이상 나온 값만 열을 만든다. 그 밖의 train 값은 `__rare__`, train에 없던 값은 `__unknown__`.
- 열은 모두 61개다.

**제외**: fight·reflex·care(봇 기억), res(과거 결과), rule·out, 미래 정보, 연결·실행 정보, 식별자, 포인터 값, 버전·날짜·구역, 절대 좌표, `snap.t`, `cam_yaw`, `chars.dist`, `npc_param`, 적대가 아닌 팀(0·1·26).
표적 포인터는 개체를 찾는 데만 쓰고 입력에 넣지 않았다.

## 모델과 선택

- `RandomForestClassifier`: n_estimators 200, min_samples_leaf 3, random_state 20261031, gini, max_features sqrt, bootstrap, n_jobs 1
- 후보 4개: C1 깊이 6·가중치 없음 / C2 깊이 6·balanced / C3 깊이 12·가중치 없음 / C4 깊이 12·balanced
- 선택 기준: val에 정답으로 나온 18개 클래스 전체의 macro F1. 동률이면 얕은 모델, 그다음 후보 순서.

| 후보 | train 정확도 / macro F1 | val 정확도 / macro F1 (18클래스) |
|---|---|---|
| C1 | 0.748 / 0.525 | 0.582 / 0.308 |
| C2 | 0.588 / 0.630 | 0.485 / 0.378 |
| C3 | 0.889 / 0.747 | **0.679** / 0.395 |
| **C4 (선택)** | 0.738 / 0.743 | 0.560 / **0.418** |

- val에서 정답 n이 1~5인 클래스가 많아 선택이 불안정할 수 있다. 정확도만 보면 C3가 가장 높다.
- `footing`(val 3건)은 train에 없는 클래스다.

## 고정·실행 기록

- `config.json` sha256 `cb5c0d82…a1fa9e`: 학습 전에 작성
- `selection.json` sha256 `a31e68bb…1783`: test/shift 평가 전에 작성. `final` 단계는 config 해시가 selection과 같은지 확인한다.
- `rf_i1current.py` sha256 `461da1fa…347d`: select와 final 모두 이 버전으로 실행
  - config 고정 뒤 select 실행 **전에** 한 줄을 고쳤다: 기준선 클래스 집합을 찾는 키 처리를 단순화(`bl_sets.get(en)`).
  - 고친 곳은 비교용 키이며, 입력·후보·선택 기준과는 관계없다.
- 환경: Python 3.13.18 (`/usr/local/bin/python3`로 만든 venv), pip 26.2.2
  - scikit-learn 1.9.1, numpy 2.5.4, scipy 1.18.1, joblib 1.6.0, threadpoolctl 3.7.0, narwhals 2.28.0, cloudpickle 3.1.2
  - wheel만 사용, `pip check` 이상 없음
  - 상세는 `env.json`, `requirements-freeze.txt`
- **venv 자체는 보존되지 않는다.** `commands.txt`대로 다시 만든다.
- 모델 파일은 저장하지 않았다. `final`을 다시 돌리면 재학습한다. 같은 결과가 나오는지 재실행 검증은 하지 않았다.

## 파일

| 파일 | 용도 |
|---|---|
| `config.json` | 학습 전에 고정한 설정 (입력·전처리·후보·분할·지표·선택 기준·환경) |
| `rf_i1current.py` | 전처리·학습·평가 (`select` / `final`, 경로는 인자) |
| `candidates.json` | 후보별 train/val 결과, 인코더 사전, val에서 처음 본 범주 수 |
| `selection.json` | 선택 결과와 해시 |
| `results.json` | 최종 결과 전부: 변형 base / no_dirty_duel_train, 평가셋 5개, 클래스별 지표, macro F1(기준선 클래스 집합 / 정답 전체), 혼동행렬, 실행별 정확도와 단순 평균, 처음 본 범주 수, 전술 보조 지표, 특징 중요도(impurity — 참고용) |
| `comparison.json` | 보존된 기준선 A(최빈값·조회표)와의 비교, 재현율 0이던 4개 클래스 |
| `predictions.jsonl` | scene별 `run, scene_seq, split, variant, y_true, y_pred` (평가셋 4개 × 변형 2개) |
| `env.json`, `requirements-freeze.txt`, `install_choice.txt`, `commands.txt` | 환경과 재현 명령 |
| `SHA256SUMS` | 해시 (자기 자신 제외) |

## 결과 해석 시 주의

- macro F1의 클래스 집합이 평가셋마다 다르다. 같은 평가셋 안에서만 기준선과 비교한다.
- shift_ref
  - "기준선 클래스 집합" macro F1은 클래스 1개(after_swing)뿐이고, 이 모델은 거기서 0이다.
  - 정답 전체(8개 클래스) 기준이 참고치다.
- `class_weight=balanced` 때문에 train 1건뿐인 `lure`가 shift_zone에서 20번, shift_ref에서 10번 예측됐다.
  after_swing의 재현율도 기준선보다 낮다(test 0.44, shift_zone 0.16).
- 구간 추정(bootstrap 등)은 하지 않았다. 평가셋의 실행 수는 5~8개다.
- 특징 중요도는 인과적 근거가 아니다.
