# C3 vs C4 class_weight 진단 — G2 I1-current RF (2026-10-31, [cloud])

## 무엇인가

- 질문: 같은 I1-current 입력·전처리·깊이 12·seed에서 `class_weight`만 바꾸면(C3 None / C4 balanced),
  희소 클래스 과예측과 주요 클래스 재현이 어떻게 달라지는가.
- **별도 진단 실험이다.**
  - 기존 C4는 사전에 정한 val 기준(정답 전체 macro F1)으로 선택된 모델이고, 그 기록은 그대로다.
  - C3를 최종 모델로 바꾸지 않는다.
- test/shift는 여러 번 본 후속 비교 데이터라 블라인드 검증이 아니다.
- seed 하나(20261031)짜리 제한된 실험이다.
- 게임 성능·판단의 질·실행 동작을 평가하지 않는다.
- I2(봇 기억)가 필요한지는 이 비교만으로 정하지 않는다.

## 참조 (복제하지 않음, 해시는 실행 시 스크립트가 대조)

| 자료 | 커밋 | SHA-256 |
|---|---|---|
| 추출본 `data/inventory/2026-10-31/g2_scene_extract.jsonl` | 6ccafc0 | `c0a31ceb8f8c733c0df043b076536c1d7045900ebec656a5ed44041527f3ea35` |
| manifest `…/g2_scene_manifest_scenes.jsonl` | 6ccafc0 | `3de0c325098b0358792b648aa1e1de5b079f591760ad94cfa3b39925e5eceec3` |
| 기준선 `experiments/g2_scene_baselines_2026_10_31/results.json` | ca6b7f05 | `37b91a0a119c9a6c57ef673a52e3da1ed2aad6b0037e776d24cb322257f9db2e` |
| RF `config.json` | 79742deb | `cb5c0d82a129dd9e904f9f41317282dd1d5dfc99f0637c85729a5ad2a7a1fa9e` |
| RF `selection.json` | 79742deb | `a31e68bb6ce2079771c47d08339787c64b9d28e7c58fa3a65c2f8432f15b1783` |
| RF `rf_i1current.py` (import해서 그대로 사용) | 79742deb | `461da1fa531be6db14a9c3b9b8cde91435e3dbaca3747e24cc650c0b6bf8347d` |
| RF `results.json` | 79742deb | `98f0f5ff7b993c58ef53aa2097bfb315b3ecc742dcca414fb17a24f87b523e32` |
| RF `predictions.jsonl` (**C4 예측의 출처**, variant=base) | 79742deb | `94880d62dc964a60f24924d2d38dfb5313f88c503a2450035714ab95a176a5cb` |
| RF `candidates.json` (C3 재현 대조용) | 79742deb | `fe8b7dc033dcd6875ea92ae874409e7d03accdfbe898800d038b72375833a083` |

RF 원본 디렉터리의 SHA256SUMS 12/12, 감사 SHA256SUMS 3/3이 실행 전에 통과했다.

## 비교 조건 (실행 전 고정: `diag_config.json` sha256 `c9161399…958a`, 스크립트 `c3_c4_diag.py` `e75583ab…da02`)

- 공통: 깊이 12, n_estimators 200, min_samples_leaf 3, random_state 20261031, gini, max_features sqrt, bootstrap, n_jobs 1
- 차이: `class_weight`뿐이다(RF `config.json`에서 읽어 확인).
- C3: train 전부(26실행 / 730)로 한 번 학습했다.
- C4: 기존 scene별 예측을 그대로 썼다(재학습하지 않음).
- 같은 특징·결측 처리·train 기반 범주 사전·분할·pending 제외를 쓴다. 기존 스크립트 함수를 수정 없이 import했다.
- 희소 클래스 정의: train 정답 수 5건 이하 → `block` 3, `face` 1, `lure` 1
- 이번 진단에서는 dirty train 실행을 뺀 재학습을 하지 않았다. shift_ref는 전체와 dirty 평가 실행(`20261019_232719`) 제외를 따로 낸다.

## 재현 확인

- C3의 train·val 지표가 `candidates.json`의 C3와 저장 정밀도에서 모두 일치했다.
  - 대조 항목: 정확도, macro F1, 클래스별 n·pred_n·P·R·F1
  - train 0.889 / 0.7465, val 0.6791 / 0.3953
- 환경도 같다: 같은 venv, pip freeze가 기존 `requirements-freeze.txt`와 동일. 그래서 C4는 재학습하지 않았다.

## 파일

| 파일 | 내용 |
|---|---|
| `diag_config.json` | 사전 고정한 설정 |
| `prerun_hashes.txt` | 설정·스크립트의 실행 전 해시 |
| `c3_c4_diag.py` | 실행 스크립트 (경로는 인자) |
| `diag_results.json` | 재현 확인, 희소 클래스, 평가셋별 C3·C4 지표 전부 (정확도, macro F1 두 종류와 labels 목록, 클래스별 P/R/F1·정답 수·예측 수·실행 수, 혼동행렬, 실행별 정확도와 단순 평균), 짝비교, 실행별 짝비교, 주요·희소 클래스 표, 예측에만 나온 클래스 |
| `paired_predictions.jsonl` | scene별 `run, scene_seq, split, y_true, y_pred_c3, y_pred_c4, c4_source` (평가셋 4개, 723줄) |
| `env_python.txt`, `env_pip_freeze.txt`, `commands.txt` | 환경과 재실행 명령. C3 모델 파일은 저장하지 않았으므로 명령으로 재학습한다 |
| `SHA256SUMS` | 해시 (자기 자신 제외) |

## 보존 상태

이 디렉터리와 압축 묶음은 저장소 밖 `/tmp/c34`에만 있다. **저장소 커밋이 아니므로 영구 보존이 아니다.** 저장소에 넣으려면 별도 승인이 필요하다.
