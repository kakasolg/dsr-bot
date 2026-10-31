# 지표 정합성 감사 — I1-current RF vs G2 기준선 (2026-10-31, [cloud])

이 문서는 새로 작성한 감사 기록이다. 상위 디렉터리의 원본 산출물(`results.json`, `comparison.json` 등)과
기준선 보존본(`experiments/g2_scene_baselines_2026_10_31/`, 커밋 ca6b7f05)은 **고치지 않았다**.
새 학습·예측·기준선 재실행은 하지 않았다. 기존 파일에서 다시 집계만 했다.

## 사용한 파일과 방법

- 추출본 `g2_scene_extract.jsonl` @6ccafc0 (sha256 `c0a31ceb…3ea35`) — 정답 `rule`과 분할
- 기준선 결과 `results.json` @ca6b7f05 (sha256 `37b91a0a…db2e`) — 변형 A, lookup·majority
- RF 결과 `../results.json` (sha256 `98f0f5ff…3e32`), RF 예측 `../predictions.jsonl` (sha256 `94880d62…a5cb`, variant base)
- 집계 코드 `audit_metrics.py` (이 폴더), 결과 `metric_consistency.json`
  - 실행: `python audit_metrics.py <extract> <baseline results.json> <rf results.json> <rf predictions.jsonl> metric_consistency.json`
  - 표준 라이브러리만 사용
- 용어 구분
  - **정답 클래스**: 그 평가셋의 y_true에 1번 이상 나온 클래스
  - **합집합**: 정답 또는 예측에 나온 클래스

## 결과 1 — 평가 표본과 정답은 같다

평가셋 4개(val, test, shift_zone, shift_ref) 모두에서 다음이 성립한다.
- RF 예측 파일의 (run, scene_seq, y_true)가 추출본과 1:1로 같다.
- 기준선과 RF의 클래스별 정답 수(support)가 추출본과 같다.
- 기준선과 RF의 실행별 scene 수가 같다.

기준선은 scene별 예측을 저장하지 않았다. 그래서 기준선 쪽은 "실행별 scene 수와 클래스별 support가 같다"까지만 확인할 수 있고,
(run, scene_seq) 단위 대조는 **확인 불가**다.

## 결과 2 — 클래스 수 차이의 원인: 보고문에서 합집합을 정답 클래스 수로 적음

| 평가셋 | 정답 클래스 (추출본) | 기준선 `per_class` 키 수 (합집합) | 기준선 예측에만 나온 클래스 | RF `per_class` 키 수 (합집합) | RF 예측에만 나온 클래스 |
|---|---|---|---|---|---|
| val | 18 | 18 | 없음 | 19 | face |
| test | 17 | 17 | 없음 | 18 | finish |
| shift_zone | **14** | **15** | estus | 16 | estus, lure |
| shift_ref | **8** | **10** | backstab, backstab_swing | 12 | attack, block, estus, lure |

- 기준선 `results.json`의 `n_true_classes` 필드는 shift_zone 14, shift_ref 8로 **맞게 저장되어 있다.**
  기준선의 "정답 전체 macro F1"도 정답 클래스(n≥1)만으로 계산되어 있다.
- "shift_zone 15개 / shift_ref 10개"는 기준선 결과를 보고할 때 `per_class` 표의 행 수, 즉 **합집합**을 정답 클래스 수로 잘못 적은 것이다.
  - 이 잘못된 값은 기준선 보존 README(@ca6b7f05) 76행 "shift_ref는 정답 클래스가 10개"에도 들어가 있다.
  - 확인된 값은 **정답 클래스 8개** (after_swing, reflex, face_first, hit_first, stagger_punish, late_windup_block, approach, edge)다.
  - 기준선 README는 고치지 않았다.
- RF 보고(이번 실험)의 정답 클래스 수 18 / 17 / 14 / 8은 맞다.

## 결과 3 — "val reflex 17개"

- 추출본 기준 val의 reflex 정답은 **16개**(4실행)이다. 기준선 결과와 RF 결과 모두 16이다.
- 17은 val의 **guard 전술 합계**와 같다: reflex 16 + late_windup_block 1 (block·downed 0).
  이전 분할표의 guard 열(17/4)을 reflex로 옮겨 적었을 가능성이 높다.
  어느 보고 문장에서 생겼는지는 기록으로 확정하지 못했다(**추정**).

## 결과 4 — 주요 클래스 집합은 같은 것을 썼다

- RF `results.json`의 `baseline_set_classes`가 기준선 `primary_classes`와 평가셋별로 같다.
  - val 4개, test 7개, shift_zone 6개, shift_ref 1개
- RF 예측에서 같은 집합으로 macro F1을 **새로 다시 집계**한 값이 보고값과 같다.

| 평가셋 | 기준선 집합 macro F1 | 정답 전체 macro F1 |
|---|---|---|
| val | 0.6562 | 0.4182 |
| test | 0.5694 | 0.5025 |
| shift_zone | 0.5805 | 0.5036 |
| shift_ref | 0.0 | 0.2809 |

macro F1에 실제로 들어간 labels는 기준선 집합 또는 정답 클래스이고, 예측에만 나온 클래스는 포함되지 않았다(`metric_consistency.json`의 `labels_primary`, `labels_true`).

## 비교 결론에 미치는 영향

- 수치(정확도·macro F1)는 바뀌지 않는다. 잘못된 것은 보고 문장 속 클래스 수뿐이다.
- 기준선 대비 개선 결론(test·shift_zone에서 정확도와 같은 클래스 집합 macro F1 상승)은 같은 표본·같은 클래스 집합 위에서 계산된 것으로 확인됐다.
- shift_ref 해석 정정: 정답 클래스는 8개다. 그중 1차 기준(정답 10개 이상, 실행 3개 이상)을 통과한 클래스가 1개라는 점은 그대로다.

## 미확인

- 기준선의 scene 단위 예측 (저장되지 않음)
- "17"이 생긴 정확한 보고 위치
- 이번 감사는 기존 파일 사이의 정합성만 봤다. 기준선·RF를 다시 돌렸을 때 같은 값이 나오는지는 확인하지 않았다.
