# B0 — 경과 시간 수치만 지운 B (준비만, 2026-10-31, [cloud])

**상태: 준비 단계.**
- 학습, 예측, scene_replay, 게임 실행은 하지 않았다.
- 저장소 밖(`/tmp/stagmem_b0/prep`)에만 있다. 원격 보존이 아니다.
- 기존 `/tmp/stagmem`, `/tmp/stagmem_m`, `/tmp/spaudit_consts`와 통합 묶음은 읽기만 했다.

## 질문

> 기억 상태와 유효 여부를 유지했을 때, 경과 시간의 실제 수치가 가드 규칙 재현에 추가로 도움이 되는가?

- 결과 해석에 넣지 않을 것: 인과, 순수한 버전 효과 분리, 게임 성능, 공격 성능, 유의성.

## 정의

**B0** = B와 같은 67열, 같은 열 순서. 바뀌는 곳은 `smem_target_since_s`(열 번호 65) 하나다.
- 이 열의 **유효한 값만 0.0**으로 바꾼다. NaN은 그대로 둔다.
- `__missing` 열 6개를 포함한 나머지 66열은 B와 같다.
- train과 평가 split 4개에 같은 변환을 적용한다.
- 0.0은 대체 상수일 뿐, 관측된 경과 시간이 아니다. train의 유효 값은 0.024~2.557초다.
- 다른 상수를 써도 같은 모델이 나오는지는 **확인하지 않았고 주장하지 않는다.**

**재사용과 새 학습**
- A·M·B는 저장된 예측(`/tmp/stagmem_m/run/predictions_M.jsonl`)을 재사용한다.
- 새로 학습하는 것은 B0뿐이다.
- 데이터, split, 인코더, 모델 설정(max_features=None), seed 20261031은 기존과 같다.

## 준비 검사 (prepare, 모두 통과)

**참조 해시** (9개 모두 일치)
- A/B: config, 스크립트, prep_report, results, predictions
- M: config, results, predictions
- 분기 감사: rows

**행렬**
- 5 split 모두에서 열 65를 뺀 66열이 B와 같다. NaN 위치까지 같다.
- 열 65의 NaN 위치가 B와 같다.
- 유효 값 개수가 B와 같다:

| split | 유효 값 (B / B0) |
|---|---|
| train | 43 / 43 |
| val | 0 / 0 |
| test | 32 / 32 |
| shift_zone | 85 / 85 |
| shift_ref | 29 / 29 |

- 유효 값은 모두 0.0이다.
- `smem_target_since_s__missing` = 1인 행이 정확히 NaN 위치와 같다.

**저장 예측**
- 723행이 평가 split과 정답에 모두 연결된다.
- 두 저장 파일(A/B 원본, M 파일)의 A·B 예측이 서로 같다.

**진단 집합 크기**: 가드 95 · 개선 35 · 핵심 24 · 경계 7 · A만 정답 6

**경계**
- prepare에서는 fit과 predict를 막았다.
- train은 승인 문자열이 없으면 **출력 폴더를 만들기 전에** 거부한다. 실제로 폴더가 생기지 않는 것을 확인했다.

## 평가 계획 (학습 승인 뒤)

**전체 평가를 먼저 보고한다.**
- split별 A·M·B0·B 지표: 정확도, macro F1 두 종류와 label 목록, 클래스별, 실행별 정확도와 단순 평균.
- 짝비교: B0–B, A–B0, M–B0를 split별·실행별로.

**진단 집합**
- 진단 집합별로 A·M·B0·B의 정답 수와 B0 예측 분포를 본다.
  - 대상: 가드 95, 개선 35, 핵심 조건 24, 시간 경계 7, A만 정답 6
- **개선 35와 A만 정답 6은 결과를 보고 고른 사후 진단 집합**이다. 결과 파일에는 `post_hoc: true`로 표시한다.
- 개선 35: 실행별로 B0가 유지한 수와 잃은 수를 센다. 212954 제외도 본다(핵심 24도 같음).
- 시간 경계 7, A만 정답 6: 장면별 예측을 표시한다.
- reflex·face_first: A 대비, B 대비로 잃은 장면 목록을 남긴다.

## 보존·문서 계획 (제안만 함, 실행하지 않음)

**기준**: GitHub `kakasolg/dsr-bot` 브랜치 `ccr-0daec3e4-ierxrw`, HEAD `3a0064f5c7f0d0f8e75a0700c139eda2a401c749` (원격도 같은 커밋인 것을 확인)

**제안 경로**: `experiments/g2_stagmem_followups_2026_10_31/`

| 하위 디렉터리 | 내용 | 원본 |
|---|---|---|
| `ab/prep/` | README.md, config.json, feature_spec.md, stagmem_compare.py, prep_report.json, prerun_hashes.txt, ref_hashes.txt, env_python.txt, env_pip_freeze.txt, commands.txt, SHA256SUMS | `/tmp/stagmem/prep` |
| `ab/run/` | results.json, predictions.jsonl, prep_report.json | `/tmp/stagmem/run` |
| `branch_audit/` | rows.json, consts.json, branch_classify.cmd.txt, branch_consts.cmd.txt, foes_/weapons_<commit>.py 22개 | 통합 묶음 `branch_audit/` |
| `m/prep/`, `m/run/` | config.json, stagmem_m.py, prep_report_M.json, README.md, commands.txt, env 파일, prerun_hashes.txt, SHA256SUMS / results_M.json, predictions_M.jsonl, prep_report_M.json | `/tmp/stagmem_m` |
| `b0/prep/` (`b0/run/`은 학습 승인 뒤) | 이 디렉터리 전체 | `/tmp/stagmem_b0` |
| 최상위 | `SUMMARY.md`(통합 요약), `CORRECTIONS.md`(아래 정정 설명, 새 파일), `SHA256SUMS` | – |

- `cond/results.json`은 이미 커밋된 3a0064f 파일과 같은 내용이므로 복제하지 않고 해시로만 참조한다.
- foes·weapons 사본은 git 객체에서 꺼낸 것이므로, 복제 대신 커밋 해시 목록으로 대체하는 방법도 있다.
- `.tar.gz` 묶음은 디렉터리 내용과 같으므로 커밋하지 않는다.
- 커밋할 때는 파일을 이름으로 지정해 stage한다.

**CORRECTIONS.md에 담을 정정 (기존 파일은 고치지 않는다)**

1. `g2_i1current_rf_2026_10_31/results.json`의 `tactic_aux`
   - P-80 이후 코드의 stagger_punish 정답 장면을 attack으로 셌다. 실제로는 대부분 휘청늦음 가드다.
   - 영향: test 20 · shift_zone 70 · shift_ref 5(shift_ref_no_dirty_duel 포함) · val 0. 예측 쪽은 95건 중 54건이 가드 장면.
   - 원본은 덮어쓰지 않고 설명만 별도 파일로 남긴다.
2. `g2_i1_vs_i2memory_c3_2026_10_31/README.md` 63행의 "원격 보존이 아니다"
   - ff72b45에서 원격에 푸시됐으므로 현재 상태와 다르다.
   - 정정 방법은 둘 중 하나로 고른다: (a) CORRECTIONS.md에만 기록, (b) 승인 시 그 한 줄만 고치는 별도 커밋.
   - **이번에는 수정하지 않았다.**
3. "stagger_punish 개선 = 공격 판단 재현"으로 읽힌 대화 보고 문장
   - 실제로는 휘청늦음 가드의 재현이다.

## 파일

| 파일 | 내용 |
|---|---|
| `config.json` | B0 정의, 참조 해시, 모델, 평가 계획 |
| `stagmem_b0.py` | prepare / train 두 단계 |
| `prep_report_B0.json` | 검사 결과, 진단 집합 목록 |
| `prerun_hashes.txt` | prepare 실행 전 config와 스크립트 해시 |
| `commands.txt` | 실행 명령 |
| `env_python.txt`, `env_pip_freeze.txt` | 환경 |
| `SHA256SUMS` | 해시 |
