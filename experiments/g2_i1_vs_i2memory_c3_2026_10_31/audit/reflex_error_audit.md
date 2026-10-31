# reflex 오류 감사 — I1-current vs I2-memory (고정 C3) (2026-10-31, [cloud])

새로 작성한 감사 기록이다. 상위 디렉터리의 원본 10개(설정·스크립트·결과·예측·README)는 고치지 않았다.
새 학습·예측·모델 호출은 하지 않았다. 저장된 예측(`../predictions.jsonl`)과 scene 입력(추출본 @6ccafc0)을 연결해 집계만 했다.

- 코드: `audit_reflex.py`
- 결과: `reflex_error_audit.json`
- 장면 목록: `reflex_error_scenes.jsonl` (참조, 정답, 기존 예측, 분석 필드만 담음)

## 0. 연결 검사

- 예측 723행이 (run, scene_seq)로 1:1 연결된다.
- 중복 0, 미연결 0, split 불일치 0, y_true 불일치 0, pending 0.

## 1. reflex.age 의미 정정

**코드** (`souls/reflex.py:84-87` `attack_age`)
- `self._anim[ptr]`가 `ATTACK`(`souls/moves.py:24`, `range(3000, 3500)`)에 있고, `ptr`가 `self._start`에 있을 때만 `time.time() − _start[ptr]`를 돌려준다. 그 밖에는 None이다.
- 즉 age None의 조건은 **반사가 마지막으로 기억한 표적 애니가 공격이 아니거나, 공격 시작 기록이 없는 경우**다.
- 이 조건으로 train 730건을 대조하면 위반 0건이다.

**설명의 변천**

| 출처 | 설명 | 판정 |
|---|---|---|
| 추출 검증 보고, 코드 docstring "(None if not attacking)" | age None = 표적이 공격 중이 아님 | **틀림.** 현재 표적 애니(`tick.a`)와 무관하다 |
| I2 실험 보고 | age None = 반사 기억에 공격 시작 시각이 없음 | **불완전** |

train의 age None 302건을 나누면:
- 반사가 기억한 애니가 공격이 아님 + 시작 기록 있음: **229건**
- 반사가 기억한 애니가 공격이 아님 + 시작 기록 없음: 73건

**캡처 시점**
- scene 캡처(`scenes.capture`)는 규칙을 부르기 전에 일어난다.
- 반사의 `update()`는 4번째 규칙 `prep_reflex`(`souls/duel.py:1005-1010`) 안에서 불린다.
- 따라서 캡처된 `age`·`anim`·`prefer`는 **이번 틱에 갱신되기 전 값**(직전 갱신 기준)이다. 규칙이 실제로 쓰는 `T.age`는 갱신 뒤의 값이라 캡처값과 다를 수 있다.

**재집계**
- "현재 `tick.a`가 3000~3499인데 age None"인 train은 같은 정의로 **50건**이다(기존 보고와 일치).
- 반대로 age가 있는데 현재 애니가 공격이 아닌 경우는 223건이다.

**I2 구현의 실제 처리**
- `mem_reflex_age_s = age`이고, None이면 NaN과 `mem_reflex_age_s__missing=1`로 둔다.
- **"공격 아님"으로 바꾸는 처리는 없다.** `i2_config.json`의 설명도 "반사 기억에 공격 시작이 없거나, 반사가 마지막으로 본 애니가 공격이 아님"으로 되어 있어 코드와 맞다.
- 잘못된 설명은 과거 보고 문장에만 있었다. 의미 정정만으로 기존 결과가 무효가 되지는 않는다.

**reflex 경과 시간 특징 두 개**

| 특징 | 계산 | 기준 시각 |
|---|---|---|
| `mem_reflex_age_s` | `attack_age`의 반환값 = 캡처 호출 시점의 `time.time()` − `_start[표적]` | 캡처 호출 시점 |
| `mem_reflex_target_since_start_s` | −`reflex.start[표적]._t` (`_t` = `_start` − `T.now`, `scenes._plain`) | `T.now` |

두 값의 기준 시각 차이는 캡처 호출 지연만큼이다. 두 번째 특징은 age가 None이어도 시작 기록만 있으면 값이 있다.

## 2. y_true = reflex 장면의 네 그룹

| 평가셋 | n / 실행 | 둘 다 정답 | I1만 정답 (손실) | I2만 정답 | 둘 다 오답 |
|---|---|---|---|---|---|
| val | 16 / 4 | 5 | 3 → I2: after_swing 2, backstab_swing 1 | 1 (I1: after_swing) | 7 |
| test | 18 / 5 | 2 | 9 → I2: after_swing 5, backstab_swing 2, attack 1, stagger_punish 1 | 0 | 7 |
| shift_zone | 12 / 7 | 0 | 2 → I2: after_swing 1, stagger_punish 1 | 0 | 10 |
| shift_ref | 14 / 1 | 0 | **9 → I2: stagger_punish 9** (모두 212954) | 0 | 5 (I1: attack 5 → I2: after_swing 3, stagger_punish 2) |

- 손실 장면 23건의 대체 규칙: stagger_punish 11, after_swing 8, backstab_swing 3, attack 1.
- 실행별 손실: 212954에 9건, test 025301에 5건, test 011929에 2건, val 024340에 2건, 나머지는 실행당 1건.

## 3. 기존 입력과의 대조 (관측된 연관, 원인 아님)

- **손실 장면의 공통점**
  - 현재 표적 애니가 대부분 3500대(휘청)다: shift_ref 9/9, test 7/9.
  - 반사가 기억한 표적 애니가 공격이 아니다(age 결측): shift_ref 9/9, test 6/9.
  - 휘청·휘두름 기억(`_stag_t`, `_swing_end_t`)이 있다: shift_ref 9/9.
  - 우선 대상(prefer)은 모두 표적이다.
- **train의 stagger_punish 45건 모습**
  - 표적 애니 3500대 44 + 9600 1 (공격 애니 0)
  - 반사 기억 애니가 공격이 아님 44, age 결측 44
  - 손실 장면의 기억 상태와 같은 형태다.
- **I1 입력의 현재 세계 관측과 대조**
  - 손실 장면에서는 **표적이 아닌 다른 적이 2.5 m 안에서 공격 애니 중**인 경우가 많다: shift_ref 9/9, test 8/9(1명 6 + 2명 2).
  - train에서 그 상황은 reflex 23/43, stagger_punish 0/45다.
  - I1에는 "4 m 안 다른 적의 공격 수"와 "2.5 m 안 적대 수"가 들어 있다. 2.5 m 기준의 다른 적 공격 수는 입력에 없다.
- **코드상 가능한 설명 (가설)**
  - `rule_reflex`(13번째)는 표적만이 아니라 2.5 m 안 **어떤 적**의 공격에도 반응한다(`reflex.threats`).
  - `stagger_punish`(17번째)는 그보다 뒤에 있다.
  - 그래서 표적이 휘청 중이어도 다른 적이 휘두르면 reflex가 먼저 걸린다.
  - 그런데 I2의 reflex 기억 특징은 모두 **표적 기준**이다. 다른 적이 일으킨 반사 상황에서도 "표적 휘청 + age 결측" 패턴이 train의 stagger_punish와 같아 보일 수 있다.
  - 이 설명은 코드와 분포가 맞는다는 데까지만 확인됐고, 모델이 실제로 그렇게 판단했는지는 확인하지 않았다.
- **I2만 맞힌 reflex는 val의 1건뿐이다**: 다른 적이 2.5~4 m 안에서 공격 중이었다.

## 4. shift_ref 20261019_212954_parish-group1

- **메타**: 커밋 `f36afcd6…`, 미커밋 변경 없음, 품질 플래그 없음, 스타일 guard, 무기 클레이모어(301000), scene 34개
- **분포**
  - 정답: reflex 14 · face_first 12 · stagger_punish 5 · edge 1 · after_swing 1 · hit_first 1
  - I1 예측: attack 9 · face_first 12 · reflex 11 · after_swing 1 · hit_first 1
  - I2 예측: **stagger_punish 25** · after_swing 4 · face_first 4 · hit_first 1
- **전이 (정답 | I1 | I2)**
  - reflex|reflex|stagger_punish 9
  - face_first|face_first|stagger_punish 8
  - stagger_punish|attack|stagger_punish 4
  - reflex|attack|after_swing 3
  - reflex|attack|stagger_punish 2
  - face_first 유지 4
  - 나머지 4건
- **기억 상태**: reflex·face_first·stagger_punish 정답 장면 모두 다음 상태가 같다.
  - 표적 애니 3500, 직전 애니 3500
  - 반사 기억 애니가 공격이 아님(age 결측)
  - 시작 기록 있음, prefer = 표적
  - 휘청 기억 있음 (휘청 뒤 경과 중앙: reflex 0.89 s, face_first 0.79 s, stagger_punish 1.27 s)
- **다른 적**: 이 실행의 reflex·face_first 손실 장면은 모두 2.5 m 안에 다른 공격 중인 적이 있다.
- **같은 규칙의 다른 평가 실행**
  - reflex 손실(I1 정답 → I2 오답)은 212954 9건 외에 test 025301 5, 011929 2, 005843 1, 033444 1, val 145345 1, 024340 2, shift_zone 060542 1, 061331 1이다.
  - face_first 손실은 212954 8건 외에 val 223957 3, test 025301 2, val 053935 1이다.
  - **한 실행에 몰려 있지만, 여러 실행에 걸친 현상이기도 하다.**

## 5. RF 비교의 해석상 한계

- 설정은 `max_features="sqrt"`다(`i2_config.json` model.common).
- 분할마다 고려하는 후보 특성 수는 I1 61열에서 7개, I2 174열에서 13개로 달라진다.
- 비중도 바뀐다. 추가된 113열 중 다수가 결측 표시이고, 원래 61열 각각이 후보로 뽑힐 확률이 낮아진다.
- 따라서 이번 결과는 **"고정된 RF 학습 절차에 기억 필드 묶음을 추가한 효과"**이고, "기억 정보 자체의 효과만 독립적으로 분리한 결과"가 아니다.
- 이를 나눠 확인하는 학습은 하지 않았다.

## 6. 정리

**확인된 사실**
- 예측과 입력의 연결은 정상이다.
- age None의 정확한 조건과 캡처 시점(규칙 전, 반사 갱신 전)을 확인했다.
- I2 구현은 None을 결측으로 두었다.
- reflex 손실 23건의 대체 규칙과 실행 분포를 확인했다(212954에 9건).
- 손실 장면의 기억 상태가 train의 stagger_punish와 같은 형태이고, 다른 적이 2.5 m 안에서 공격 중인 경우가 대부분이다.

**코드상 가능한 설명**
- reflex는 다른 적의 공격으로도 걸리는데 I2의 기억 특징은 표적만 기술한다.
- max_features 희석.

**확인하지 못한 원인**
- 모델 내부에서 어떤 분할이 이런 예측을 만들었는지
- 열 수 증가 효과와 기억 정보 효과의 분리
- seed 변동

**수정 후보 (실행하지 않음)**
- reflex 기억 특징을 "2.5 m 안 다른 적의 공격 상태"처럼 반사 규칙이 실제로 보는 대상 기준으로 요약하기
- 열 수를 같게 맞춘 비교로 희석 효과를 분리하기
