# G2 scene 기준선 2종 — 보존본 (2026-10-31, [cloud])

## 목적과 적용 범위

선별 저장된 G2 scene(`--ctl-scenes`의 scene 레코드)에서, 그 결정 순간의 관측 일부만으로
**과거 봇이 고른 규칙(`selected_rule`)을 재현하는 기준선** 두 가지를 계산한 기록이다.

- 기준선 1: train의 최빈 규칙을 항상 답함
- 기준선 2: (표적 애니 범주 × 표적 거리 구간 × 4 m 안 적대 개체 수) 조회표

**게임 성능을 측정하거나 개선을 입증한 결과가 아니다.**
- 정답이 과거 규칙의 출력이므로, 높은 일치율은 "그 버전의 규칙과 같은 것을 골랐다"는 뜻일 뿐이다.
- scene은 비유지형 규칙(공격·뒤잡기·에스트 등)은 매번, 유지형 규칙은 자세가 바뀔 때만 저장된다
  (`scenes.py` `keep`). 그래서 결과는 "저장된 장면의 분포" 안에서만 유효하다.

봇은 이 디렉터리를 import하지 않는다. 계산은 Cloud 세션에서 한 번 했고, 여기 파일은 그 산출물의 바이트 그대로의 사본이다.

## 사용 데이터 (복제하지 않고 참조만)

모두 작업 브랜치 `claude/dsr-bot-project-review-r3hh9f`의 커밋 `6ccafc0f636c0976ea4289251ae5896afe2a7bee`에 있다.

| 파일 | SHA-256 |
|---|---|
| `data/inventory/2026-10-31/g2_scene_extract.jsonl` (입력·라벨, 1,475줄) | `c0a31ceb8f8c733c0df043b076536c1d7045900ebec656a5ed44041527f3ea35` |
| `data/inventory/2026-10-31/g2_scene_manifest_scenes.jsonl` (scene별 분할) | `3de0c325098b0358792b648aa1e1de5b079f591760ad94cfa3b39925e5eceec3` |
| `data/inventory/2026-10-31/g2_scene_manifest_runs.json` (실행별 메타·플래그) | `f9d8be52f3d474e0852155010b8dbe0381a82fe63092f9b4bf2a9a1f68399b3c` |
| `data/inventory/2026-10-31/g2_scene_manifest.tsv` (압축 manifest) | `ab637fcb2b6ff0a613cce8f899a239ca1b9a35194f39925d95cc03c0e62c8dbe` |
| `data/inventory/2026-10-31/g2_scene_extract_check.json` (추출 검증) | `93cff1eea2ab4379ba652925a8821fc5bc2abcf108dcc16f901ce0cb81d1300d` |

계산에 실제로 읽은 파일은 앞의 `g2_scene_extract.jsonl` 하나다. 분할 값은 그 파일의 `split` 필드이고, 이 필드는 manifest와 1,475건 모두 같다(추출 때 확인).
원본 ctl·영상·세이브·diff는 Windows PC의 `data/runs/`에만 있으며 여기에 복제하지 않았다.

## 분할

| split | 실행 | scene | 사용 |
|---|---|---|---|
| train | 26 | 730 | 기준선 만들기 (변형 A) |
| val | 5 | 134 | 평가 |
| test | 7 | 233 | 평가 |
| shift_zone | 8 | 292 | 평가 (burg-altar 전체 — 구역·날짜·버전·무기가 함께 바뀜) |
| shift_ref | 8 | 64 | 평가, 참고치만 (parish, 10-19·10-27) |
| pending | 1 | 22 | **학습·평가 모두 제외** (`20261012_215634_burg-upper`, ctl `end` 레코드 없음) |
| 합계 | 55 | 1,475 | |

범위 조건: 실행 날짜 ≥ 20261011, scene 스키마 `dsr-scene-input/0.2`, 실행의 기준 커밋이 `4f99502`·`8a2c96a`·`d256d69`를 포함.

## 변형과 dirty_duel_py 처리

미커밋 diff가 `souls/duel.py`를 바꾼 실행이 2개 있다(`g2_scene_extract_check.json`의 `dirty_diff_touches`).

- **A_base**: train 26실행 전부로 만든다.
- **B_no_dirty_duel**: train에서 `20261012_075054_burg-upper`(scene 18개)를 빼고 25실행 / 712로 다시 만든다.
- 평가 변형 **shift_ref_no_dirty_duel**: shift_ref에서 `20261019_232719_parish-group1`(scene 3개)을 뺀다.
  A·B 모두에 대해 계산했다.

## 계산 전에 고정한 설정 (`config.json`)

- **애니 범주** (`tick.a`)
  - idle(−1 또는 null), attack 3000~3499, stagger 3500~3599, hit_stun 2000~2099
  - downed 9900~9999, guard_broken 9600, dormant 9000~9099, falling 1500/1550/121500, other
  - 근거: `souls/moves.py` 상수
- **거리 구간** (`tick.h`, m): <1.0 · 1.0~1.6 · 1.6~2.5 · 2.5~4.0 · 4.0~6.0 · ≥6.0
- **4 m 안 적 수**: `snap.chars` 중 팀 {6,7,24,25,27,33}, HP>0, 플레이어와의 수평 거리 4.0 m 미만인 개체 수(표적 포함) → 0 / 1 / 2 / 3+
- **조회표**: 칸 키는 (애니, 거리, 적 수). train 1건 이상이면 칸으로 인정한다.
- **동률 처리**: 칸 안에서 동률이면 train 전체 빈도가 높은 규칙, 그다음 규칙 이름 오름차순. 최빈값 기준선의 동률은 이름 오름차순.
- **미관측 칸 fallback**: (애니, 거리, 적 수) → (애니, 거리) → (애니) → train 최빈 규칙. 어느 단계를 썼는지 평가셋별로 집계한다.
- **macro F1**
  - 1차: 그 평가셋에서 정답 scene 10개 이상이고 실행 3개 이상인 클래스
  - 참고: 그 평가셋에 정답으로 한 번이라도 나온 모든 클래스
  - 한 번도 예측하지 않은 클래스의 precision은 0, P+R=0이면 F1=0

## 결과를 읽을 때 주의 (결과 파일은 고치지 않았다)

- **평가셋마다 1차 macro F1의 클래스 집합이 다르다.** val 4개, test 7개, shift_zone 6개, shift_ref 1개다
  (`results.json`의 `primary_classes`). 점수를 평가셋 사이에서 단순 비교할 수 없다.
- **shift_ref는 정답 클래스가 10개인데, 1차 기준을 통과한 것은 1개(after_swing)뿐이다.**
  그래서 shift_ref의 1차 macro F1(A 조회표 0.553, B 0.833)은 사실상 after_swing 하나의 F1이다. 참고치로만 읽는다.
- B에서 train 실행 하나(18 scene)를 빼자 shift_ref 조회표 정확도가 0.406에서 0.562로 바뀌었다.
  조회표 칸 몇 개의 최다 규칙이 바뀐 결과이며, 이 기준선이 작은 학습 변화에 민감하다는 뜻이다.
- 게임 성능 향상을 측정하거나 입증한 결과가 아니다.

## 재실행 방법

`baselines.py`는 표준 라이브러리만 쓴다(json, math, collections, sys, hashlib).
입력 경로가 **`/tmp/inv3/data/inventory/2026-10-31/g2_scene_extract.jsonl`로 고정**되어 있고, `config.json`과 결과 `results.json`은 **현재 디렉터리** 기준이다.
보존본을 덮어쓰지 않도록 다른 폴더에서 돌린다.

```bash
# 저장소 루트에서
git fetch origin claude/dsr-bot-project-review-r3hh9f        # 6ccafc0 포함
mkdir -p /tmp/inv3 && git archive 6ccafc0 data/inventory/2026-10-31 | tar -x -C /tmp/inv3
sha256sum /tmp/inv3/data/inventory/2026-10-31/g2_scene_extract.jsonl   # c0a31ceb… 이어야 함
mkdir -p /tmp/rerun && cp experiments/g2_scene_baselines_2026_10_31/{config.json,baselines.py} /tmp/rerun/
cd /tmp/rerun && python3 baselines.py && sha256sum results.json    # 보존본 37b91a0a… 와 비교
```

이 재실행은 아직 해 보지 않았다. 바이트 단위로 같은 `results.json`이 나오는지는 확인되지 않았다.

## 실행 환경 — 확인된 것과 못 한 것

- 계산 장소: Claude Code Cloud 세션(Linux 컨테이너), 2026-10-31. 명령은 `/tmp/bb/baseline`에서 `python3 baselines.py`.
- **당시 기록하지 않은 것**: `python3`가 가리킨 실제 인터프리터 경로와 버전, OS·라이브러리 버전.
  보존 시점에 같은 세션에서 `python3`는 `/home/user/dsr-bot/.venv/bin/python3`(Python 3.12.3)로 풀렸지만, 계산 당시에도 같았는지는 기록이 없다.
- 외부 의존성은 없다(코드로 확인).

## 파일

| 파일 | 용도 | 출처 |
|---|---|---|
| `config.json` | 계산 전에 고정한 설정 | `/tmp/bb/baseline/` 바이트 그대로 |
| `baselines.py` | 기준선 계산 스크립트 (수정하지 않음, 입력 경로 고정) | 같음 |
| `results.json` | 결과 전부: 변형 A/B, 평가셋 val/test/shift_zone/shift_ref/shift_ref_no_dirty_duel, 기준선별 정확도·클래스별 P/R/F1·정답 수·실행 수·예측 수, macro F1(1차/참고)과 1차 클래스 집합, 혼동행렬, 실행별 정확도, 조회표 fallback 단계별 수와 비율, 조회표 전체 칸, train 규칙 빈도 | 같음 |
| `hashes_before.txt` | 계산 직전 config·입력 2개의 해시 3줄 + 계산 직후 `baselines.py`·`results.json` 해시 2줄 (이름과 달리 뒤 2줄은 계산 뒤에 덧붙인 것). 경로는 당시 `/tmp` 기준 | 같음 |
| `README.md` | 이 설명 | 보존 때 새로 작성 |
| `SHA256SUMS` | 위 파일들의 SHA-256 (자기 자신 제외) | 보존 때 새로 작성 |

## 보존되지 않은 것

- **scene별 정답·예측·fallback 단계 목록**: 계산 때 파일로 쓰지 않았다(`results.json`에는 집계만 있음).
  만들려면 재계산이 필요하므로 이번에는 만들지 않았다.
- 실행 명령의 터미널 출력, 환경 정보: 기록하지 않았다.

## 한계와 아직 하지 않은 일

- 조회표는 규칙의 내부 타이머(휘두름 끝, 휘청 시각, SP 등)를 보지 못한다.
  after_swing이 다른 규칙을 흡수하고(재현율 높고 정밀도 낮음), reflex·stagger_punish·stamina·attack은 test에서 한 번도 맞히지 못했다.
- 평가셋의 실행 수가 5~8개뿐이고 실행 사이 편차가 크다. 실행 단위 bootstrap 같은 구간은 계산하지 않았다.
- shift_zone은 구역·날짜·버전·무기가 함께 바뀌어 원인을 나눌 수 없다.
- 하지 않은 것: 입력 세트 I1/I2 모델 학습·비교, scene별 예측 저장, 재실행 검증, 게임 실행.
