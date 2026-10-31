# 표적 휘청 기억 특징 명세 (B에만 추가, 열 6개)

정의는 코드와 **train 자료만으로** 정했다. 평가 split의 특징 분포는 보지 않았다.
평가 split에서 확인한 것은 다음 세 가지뿐이다:
- 행렬이 같은지(A와 B의 공유 열)
- 결측 표시가 일관되는지
- 조건 칸 수가 보존된 감사 결과와 같은지

## 출처 필드와 갱신 순서

- **쓰는 곳**: `souls/duel.py` `prep_reflex`(RULES의 4번째 항목)만이 아래 필드를 쓴다.
  ```python
  if T.a in M.STAGGER:
      if F.__dict__.get("_stag_ptr") != F.ptr:
          F._stag_ptr, F._stag_t = F.ptr, T.now
      T.stag_age = T.now - F._stag_t
  else:
      F._stag_ptr, T.stag_age = None, None      # _stag_t는 그대로 남는다
  ```
  - 이 블록은 93dce7b(P-80, 2026-10-13)에서 처음 들어왔다.
  - manifest에 있는 P-80 이후 실행 커밋 18개 모두에서 문자열이 같다. RULES에서 `prep_reflex`의 위치(4번째)와 `scenes._plain`, `now = T.now`도 같다.
  - 미커밋 변경이 있는 실행(2a97b616, 30ddc29c, 137086b3 계열)은 코드로 확인할 수 없다.
- **캡처 시점**: `SCENE_TAP.tick(F, T)`가 `for rule in RULES` 앞에서 불린다. 그래서 scene의 `fight._stag_*`는 **이 틱의 갱신 전 값**이다. 즉 같은 Fight에서 가장 최근에 `prep_reflex`까지 도달한 이전 틱이 남긴 상태다.
- **Fight 수명**: `Fight`는 `duel()` 호출마다 새로 만든다. 따라서 그 싸움에서 `prep_reflex`가 한 번도 돌지 않았으면 키 자체가 없다.
- **시각 규약**:
  - `T.now = time.time()`(`_sense`)
  - `scenes._plain`은 1e9보다 큰 float를 `{"_t": v − T.now}`로 저장한다. 이때 T.now는 이 틱의 값이다.
  - 경과 초 = −`_t`

## 기본 특징 3개

| 특징 | 뜻 | 값 | 결측 (NaN + `__missing`=1) |
|---|---|---|---|
| `smem_active` | 최근 `prep_reflex`가 진행 중인 휘청을 기억했는가 | `_stag_ptr`가 None이 아니면 1.0, 키가 있고 None이면 0.0 | `_stag_ptr` 키가 없을 때 = **기록 안 됨** (93dce7b 이전 코드이거나, 이 싸움에서 아직 prep_reflex가 돌지 않음) |
| `smem_is_target` | 기억된 휘청 개체가 현재 표적인가 | `_stag_ptr == tick.ptr`이면 1.0, 다른 개체면 0.0 | 진행 중인 기억이 없을 때 (키 없음 또는 None) |
| `smem_target_since_s` | 현재 표적의 휘청 연속 구간이 시작된 뒤 경과한 초 | −`_stag_t._t`. `_stag_ptr == tick.ptr`이고 `_stag_t`가 `{"_t"}` 타이머일 때만 | 그 밖의 모든 경우 |

**코드로 막아 둔 것**
- `_stag_ptr`가 None인데 남아 있는 `_stag_t`(train 23건)는 쓰지 않는다.
- 다른 개체의 `_stag_t`도 쓰지 않는다.
- 포인터는 같은지 비교하는 데만 쓰고, 입력값으로 넣지 않는다.
- 절대 시각, 좌표, 식별자는 입력이 아니다.

**인코딩**
- A의 61열 뒤에 `[smem_active, smem_active__missing, smem_is_target, smem_is_target__missing, smem_target_since_s, smem_target_since_s__missing]`를 붙인다. **추가 열은 6개, B는 모두 67열이다.**
- 학습해서 정하는 통계(스케일링, 범주 사전)는 없다. 값 열의 NaN은 I1 인코더처럼 NaN으로 두고, 결측 표시 열이 0과 결측을 구분한다.

## train에서 본 상태 (730 scenes)

| 상태 | scene | 그중 현재 표적 휘청 | 비고 |
|---|---|---|---|
| 키 없음 | 601 | 250 | 592건은 93dce7b 이전 실행이고, 9건은 이후 실행의 싸움 첫 틱들이다 |
| None | 86 | 36 | 36건은 직전 prep_reflex 이후에 휘청이 시작된 경우 (기억은 이번 틱의 prep_reflex에서 생김). 23건은 남은 `_stag_t`가 있지만 쓰지 않는다 |
| 표적 | 43 | 40 | 3건은 기억은 휘청인데 현재 애니는 휘청이 아니다 (한 틱 지연) |
| 다른 개체 | 0 | – | train에는 없어서 `smem_is_target`의 비결측 값은 모두 1.0이다 |

- `smem_target_since_s`(43건): 최소 0.024, 중앙 0.858, 최대 2.557초. 음수는 0건이다.
- 키가 있는 train 실행은 26개 중 6개(129 scene)다: 20261013_003435, 003654, 005647, 010935, 171039_altar, 175209_clear-ramp.
- 상태별 정답 규칙: 표적 43건 중 stagger_punish가 28건이다. 나머지 분포는 `prep_report.json` `train.rule_by_state`에 있다.

## 커밋 메타데이터로 본 기록 범위 (특징값이 아니라 실행 커밋의 93dce7b 포함 여부)

| split | P-80 이후 커밋 scene | 이전 커밋 scene |
|---|---|---|
| train | 138 (6실행) | 592 |
| val | 0 | 134 |
| test | 68 (011929 하나) | 165 |
| shift_zone | 292 | 0 |
| shift_ref | 64 | 0 |

## 해석상 주의 (명세의 일부)

- `smem_active`의 결측은 대부분 **코드 버전 표시**와 같다. 버전에 따라 규칙 자체도 달라졌으므로, B와 A의 차이에는 기억 정보와 버전 표지가 섞여 있다.
- val에서는 B의 추가 열이 모두 결측이다. 그래도 학습된 숲이 달라지므로 val 예측이 바뀔 수 있다.
- 기록되는 연속 구간의 시작은 게임 안 휘청 시작이 아니라, 처음 그 휘청을 본 `prep_reflex` 시각이다. 두 `prep_reflex` 사이에 휘청이 끝났다가 다시 시작되면 한 구간으로 보인다.
- **기존 I2-memory와의 차이** (코드 확인, `i1_i2_compare.py` @ff72b45)
  - I2의 `mem_since_stag_s`는 `_stag_ptr`와 상관없이 `_stag_t`를 썼다. 그래서 None 상태에서 남아 있던 타이머(train 23건)도 값으로 들어갔다.
  - I2의 `mem_stag_is_target`은 None과 다른 개체를 모두 0으로 두었다.
  - 이번 B는 둘을 구분하므로, I2의 휘청 필드 두 개와 같은 입력이 아니다.

## 넣지 않은 것

- reflex.\* 전부, care.\*, res.\*
- `_aprev` 등 직전 애니
- 다른 fight 타이머와 카운터
- style·flags·무기 이름·nm/맵·ground·arena
- 표적이 아닌 적의 기억 요약
- run, scene_seq, commit, split, 싸움 식별자 (감사용 메타데이터로만 씀)
- rule, out, 미래 관측·피격·결과, ctl 연결
