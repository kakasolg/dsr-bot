# 휘청 기억 후속 진단 묶음 (2026-10-31, [cloud])

조건 A / M / B0 / B와 stagger_punish 분기 감사, 최종 보고를 보존한다.
- 결론: `FINAL_REPORT.md`
- tactic_aux 해석 정정: `CORRECTIONS_tactic_aux.md`

**이 디렉터리의 성격**
- 모델 파일은 없다. 모든 모델은 메모리에서만 학습했다.
- 원시 데이터는 복제하지 않았다. 아래 해시로 참조한다.
- 이 디렉터리의 실험 파일은 임시 디렉터리 원본을 바이트 그대로 옮긴 것이다(v2 묶음 `7edac16b…e92f`에서 복사). 옮기면서 내용을 고치지 않았다.
- 이 README, `branch_audit/SOURCE.md`, 최상위 `SHA256SUMS`만 저장소용으로 새로 썼다.
- 게임 성능, 인과, 유의성, 실제 공격 성능, 버전 효과 분리는 주장하지 않는다.

## 조건

| 조건 | 열 수 | 디렉터리 | 내용 |
|---|---|---|---|
| A | 61 | `ab/` | I1-current 현재 관측 |
| B | 67 | `ab/` | A + 표적 휘청 기억 6열 |
| M | 63 | `m/` | A + `_stag_ptr`·`_stag_t` 키 존재 여부 (원본 필드 기록 여부 대조군) |
| B0 | 67 | `b0/` | B의 `smem_target_since_s` 유효 값을 0.0으로 바꾼 **재학습** 비교 |

- 공통 설정: RandomForest, max_features=None, seed 20261031.
- 분기 감사: `branch_audit/`

## 임시 경로와 저장소 경로 대응

스크립트, `commands.txt`, `*.cmd.txt`에는 실행 당시의 절대 경로가 그대로 남아 있다. 아래 표로 읽는다.

| 실행 당시 경로 | 저장소에서 |
|---|---|
| `/tmp/stagmem/prep/` | `ab/prep/` |
| `/tmp/stagmem/run/` | `ab/run/` (`prep_report.json` 사본은 `ab/prep/`의 것과 같아서 제외) |
| `/tmp/stagmem/cond/results.json` | `experiments/g2_i1_vs_i2memory_c3_2026_10_31/audit/conditional_reflex/results.json` @3a0064f (sha256 `25b21b98…231a`) |
| `/tmp/stagmem_m/prep/`, `/run/` | `m/prep/`, `m/run/` |
| `/tmp/stagmem_b0/prep/`, `/run/` | `b0/prep/`, `b0/run/` |
| `/tmp/spaudit_consts/rows.json`, `consts.json` | `branch_audit/` (foes·weapons 사본은 `branch_audit/SOURCE.md`의 git 객체로 대체) |
| `/tmp/inv3/data/inventory/2026-10-31/` | `git archive 6ccafc0 data/inventory/2026-10-31` (추출본 `c0a31ceb…3ea35`, manifest `3de0c325…ceec3`) |
| `/tmp/rfexp/ref/baseline_results.json` | `experiments/g2_scene_baselines_2026_10_31/results.json` @ca6b7f05 (`37b91a0a…db2e`) |
| `/home/user/dsr-bot/experiments/g2_i1current_rf_2026_10_31` | 같은 경로 @79742deb (config `cb5c0d82…`, 스크립트 `461da1fa…`) |
| `/tmp/rfexp/venv` | 보존하지 않음. `experiments/g2_i1current_rf_2026_10_31/requirements-freeze.txt`로 venv를 다시 만든다 |

## 재실행에 필요한 것 (이 저장소 경로에서 실행해 본 적은 없음)

- **환경**: Python 3.13.18 venv, `pip install --only-binary=:all: -r experiments/g2_i1current_rf_2026_10_31/requirements-freeze.txt`
  - 결과: scikit-learn 1.9.1, numpy 2.5.4, scipy 1.18.1 …
  - 각 `prep/env_pip_freeze.txt`와 같다.
- **입력**: 위 표의 데이터, 기준선 결과, RF 디렉터리.
- **실행 순서**:
  1. `ab` prepare → `ab` train
  2. `m` prepare → `m` train (A·B 저장 예측 필요)
  3. `b0` prepare → `b0` train (A·M·B 저장 예측 필요)
  - 명령은 각 `prep/commands.txt`에 있다.
  - 각 train은 승인 문자열(`TRAINING-APPROVED`, `-M`, `-B0`)이 필요하다.
- **기록된 것은 `/tmp` 경로에서 한 번씩 실행한 결과뿐이다.**
  - 이 저장소 경로로 옮겨 다시 실행하거나, 다시 실행해서 같은 예측이 나오는지 확인한 적은 없다.
  - 경로를 바꿔 실행하면 스크립트의 참조 해시 검사는 통과하겠지만, 이것도 확인하지 않았다.
- `branch_audit/*.cmd.txt`와 `provenance/*.cmd.txt`는 세션 기록에서 복원한 표준 입력 명령 원문이다. 이 경로에서 다시 실행하지 않았다.

## 체크섬

| 파일 | 범위 | 상태 |
|---|---|---|
| 최상위 `SHA256SUMS` | 이 디렉터리의 모든 파일 (자기 자신 제외) | 저장소 기준 체크섬 |
| `ab/prep/SHA256SUMS`, `m/prep/SHA256SUMS`, `b0/prep/SHA256SUMS` | 각 prep 디렉터리의 파일 | 준비 당시 그대로이고, 이 위치에서도 그대로 통과한다 |

- `run/` 디렉터리에는 하위 체크섬이 없다. 최상위 `SHA256SUMS`가 덮는다.
- 실행 당시 해시는 각 config와 prep_report의 `refs`에 있다. results/predictions 해시도 원본 `/tmp` 파일과 같다.

## 참고

- `FINAL_REPORT.md`에는 "이 묶음의 `REPO_PLAN.md`"라는 표현이 있다. `REPO_PLAN.md`는 v2 묶음에만 있고, 그 계획을 실행한 것이 이 디렉터리와 이 커밋이다.
- 이 커밋에서 I1–I2 README에 보존 상태 정정을 덧붙였다(`g2_i1_vs_i2memory_c3_2026_10_31/README.md`).
- tactic_aux 원본 파일(`g2_i1current_rf_2026_10_31`)은 고치지 않았다.
