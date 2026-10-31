# 정정: I1 RF `tactic_aux`의 stagger_punish = attack 해석 (2026-10-31, [cloud])

## 대상

- `experiments/g2_i1current_rf_2026_10_31/config.json` `tactic_map` — `"stagger_punish": "attack"`
- `experiments/g2_i1current_rf_2026_10_31/rf_i1current.py` `tactic()`
- `experiments/g2_i1current_rf_2026_10_31/results.json`의 `variants.{base,no_dirty_duel_train}.eval.{val,test,shift_zone,shift_ref,shift_ref_no_dirty_duel}.tactic_aux`

**이 파일들은 고치지 않는다.** 이 문서가 해석을 정정한다. rule 라벨 지표(acc, macro F1, per_class)는 그대로 유효하다.

## 무엇이 틀렸나

- `rule_stagger_punish`(souls/duel.py)는 같은 라벨로 세 가지 분기를 남긴다.
  - **휘청늦음 가드**: 방패를 들고 정면을 유지 → guard
  - **휘청반격**: 실제 공격 → attack
  - **휘청돌기**: 몸만 돌림
- 휘청늦음 분기는 93dce7b(P-80)에서 생겼다. 그 이후 코드에서는 stagger_punish 정답이 대부분 이 분기다. 그런데 `tactic_map`은 라벨 하나를 attack으로 일괄 매핑했다.

## 정답 쪽 영향 (분기 감사 rows.json 기준, 정답이 stagger_punish인 장면)

| 평가셋 | 휘청늦음 가드 | 실제 공격 | P-80 이전 코드 |
|---|---|---|---|
| val | 0 | 0 | 2 |
| test | 20 | 0 | 3 |
| shift_zone | 70 | 1 | 0 |
| shift_ref | 5 | 0 | 0 |
| shift_ref_no_dirty_duel | 5 | 0 | 0 |

- 위 휘청늦음 가드 장면은 `tactic_aux`에서 정답 attack으로 셈해졌다. 실제로는 guard다.
- base와 no_dirty_duel_train 두 변형 모두 같은 정답을 쓰므로 영향 범위가 같다.
- **P-80 이전 코드 5장면**은 가드 분기가 없는 코드다. 그래도 실제 공격인지 돌기만 했는지는 감사에서 나누지 않았다. 그래서 attack 매핑이 맞는지도 **확인되지 않았다.**

## 예측 쪽 영향 (예측이 stagger_punish인 장면)

| 변형 | 평가셋 | 정답도 stagger_punish | 정답이 다른 클래스 |
|---|---|---|---|
| base | val | 2 (P-80 이전) | 9 |
| base | test | 2 (P-80 이전) | 6 |
| base | shift_zone | 55 (가드 54, 공격 1) | 18 |
| base | shift_ref | 0 | 3 |
| no_dirty_duel_train | val | 2 (P-80 이전) | 11 |
| no_dirty_duel_train | test | 2 (P-80 이전) | 6 |
| no_dirty_duel_train | shift_zone | 54 (가드 54) | 21 |
| no_dirty_duel_train | shift_ref | 0 | 2 |

**예측 라벨만으로는 분기를 확정할 수 없다.**
- 정답이 다른 클래스인 장면(base 36, no_dirty_duel_train 40)에서 예측된 stagger_punish가 실제 봇이었다면 어느 분기를 탔을지는 알 수 없다.
- 이를 알려면 그 장면에서 `_stagger_late`와 공격 조건을 계산해야 한다. 그런데 정답 규칙이 따로 있으므로 봇은 그 분기에 도달하지 않았다.
- 장면 상태에서 분기 조건을 계산할 수는 있다. 하지만 그것은 "봇이 이 규칙을 택했다면"이라는 가정 계산이며, 이번에는 하지 않았다.

## 바른 읽기

- `tactic_aux`의 attack·guard 클래스 지표는 test, shift_zone, shift_ref(no_dirty 포함)에서 **분기를 반영하지 않은 값**이다. 전술 판단의 질을 나타내는 지표로 쓰지 않는다.
- val의 `tactic_aux`도 P-80 이전 stagger_punish 2장면과, 정답이 다른 장면에서 예측된 stagger_punish의 분기가 확인되지 않은 상태다.
- `audit/metric_consistency.md` 49행 "val guard 전술 합계 17"(reflex 16 + late_windup_block 1)은 정답 쪽 guard 합계다. val에는 가드 분기 정답이 없으므로 그대로 맞다.
- 다시 계산하려면 라벨이 아니라 장면별 분기로 전술을 매겨야 한다(예: `rows.json`의 branch). 이번에는 재계산하지 않았다.

## 근거

- 분기 감사: `branch_audit/rows.json` (sha256 `46ef3608…cd29`)
  - 실행 당시 커밋 11개의 판단 코드가 같다는 것을 확인했다.
  - 상수는 커밋별 `foes.py`·`weapons.py`에서 읽었다.
  - 감사 명령 원문은 `branch_audit/branch_*.cmd.txt`에 있다(세션 기록에서 복원).
- 계산 명령: `provenance/tactic_impact.cmd.txt`(세션 기록에서 복원)
