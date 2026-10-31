# I1-current vs I2-memory — 고정 C3 RF 입력 비교 (2026-10-31, [cloud])

## 질문과 범위

- 질문: 같은 RF 설정(C3: 깊이 12, class_weight None, seed 20261031)·같은 전처리 원칙·같은 train에서,
  봇 내부 기억(fight / reflex / care의 허용 필드)을 더하면 과거 `selected_rule` 재현이 I1-current보다 얼마나 나아지는가.
- **I2-memory는 포괄적 I2가 아니다.** 과거 결과(`res`)는 두 조건 모두 뺐다.
- C3는 이번 입력 비교용 고정 설정이다. I1-current 실험에서 사전에 선택된 모델은 여전히 C4다.
- 아래 어느 것도 뜻하지 않는다.
  - 게임 판단이 더 좋다
  - 기억 갱신 구조를 갖췄다
  - 특정 필드가 인과적 효과를 냈다
  - full decision replay를 구현했다
- test/shift는 여러 번 본 후속 비교다. seed 하나, 평가 실행 수가 적고, 선별 저장된 장면 분포다.

## 참조 (복제하지 않음, 스크립트가 해시 대조)

| 자료 | 커밋 | SHA-256 |
|---|---|---|
| 추출본 | 6ccafc0 | `c0a31ceb8f8c733c0df043b076536c1d7045900ebec656a5ed44041527f3ea35` |
| manifest | 6ccafc0 | `3de0c325098b0358792b648aa1e1de5b079f591760ad94cfa3b39925e5eceec3` |
| 기준선 results | ca6b7f05 | `37b91a0a119c9a6c57ef673a52e3da1ed2aad6b0037e776d24cb322257f9db2e` |
| RF config / 스크립트 | 79742deb | `cb5c0d82…a1fa9e` / `461da1fa…347d` |
| C3–C4 `paired_predictions.jsonl` (I1 재현 대조) | 798e2ac4 | `SHA256SUMS` 참조 (같은 커밋의 디렉터리) |

## 고정한 것 (학습 전: `i2_config.json` sha256 `507d70ab…f6202`, 스크립트 `i1_i2_compare.py` `0e7be902…bb50`)

- I1-current: 기존 `rf_i1current.features`와 `Encoder`를 수정 없이 import했다(열 61개).
- I2-memory: I1 열(값이 같음) + 기억 필드 허용 목록
  - 수치 48개 + 각각의 `__missing` 열 + 범주 1개(`_aprev` 애니)
  - 열은 모두 174개, 추가된 열 113개
- 필드별 원본 경로·변환식·단위·결측 처리는 `i2_config.json`의 `inputs`에 있다.
- 타이머 규칙
  - fight 값 `0.0`은 초기값("설정된 적 없음") → NaN + missing 표시
  - `{"_t": r}`는 결정 시각 기준 상대 초(`scenes._plain`) → 경과 = −r 초
- 제외한 것과 이유도 `inputs.excluded`에 있다.
  - 포인터 값, 좌표, `*_from` 키, `--footing` 전용 `_foot*`, raw dict
  - `reflex.anim`(`_aprev`와 겹침), `res`
- 실제 자료로 다시 확인한 것
  - `reflex.age`가 None인 것은 반사 기억에 공격 시작이 없다는 뜻이다. train에서 현재 `tick.a`가 공격인데 age가 None인 경우가 50건 있다.
  - `_aprev`, `lock_n`, `_swing_*`, `_stag_*` 키는 코드 버전에 따라 없을 수 있다 → missing 처리
- 범주 사전은 train만으로 만들었다. 평가에서 처음 보는 키나 범주는 새 열로 추가하지 않고 `__unknown__`으로 처리했다.

## 재현 확인

- 일반화한 범주 인코더가 원래 I1 인코더와 같은 열·같은 행렬을 만든다(`encoder_generic_equals_original_I1` = true).
- I1-current를 이 파이프라인에서 다시 학습한 예측이, 보존된 C3 예측과 평가 scene 전부에서 일치한다(불일치 0).
- 환경: 같은 venv, pip freeze가 기존 `requirements-freeze.txt`와 같다.

## 파일

| 파일 | 내용 |
|---|---|
| `i2_config.json`, `prerun_hashes.txt` | 사전 고정 설정·특징 명세와 실행 전 해시 |
| `i1_i2_compare.py` | 실행 스크립트 (경로는 인자) |
| `results.json` | I1·I2-memory의 train 지표, 평가셋별 지표 전부(정확도, macro F1 두 종류와 labels, 클래스별, 혼동행렬, 실행별과 단순 평균), 짝비교, 실행별 짝비교, 주요·희소 클래스, I1 재현 대조, 추가 열 목록, I2 특징 중요도 상위 30개(참고용) |
| `predictions.jsonl` | scene별 `run, scene_seq, split, y_true, y_pred_i1, y_pred_i2_memory` (723줄) |
| `env_python.txt`, `env_pip_freeze.txt`, `commands.txt` | 환경과 재실행 명령. 모델은 저장하지 않았다 |
| `SHA256SUMS` | 해시 (자기 자신 제외) |

## 보존 상태

이 디렉터리와 압축 묶음은 저장소 밖(`/tmp/i2m`)에만 있고, **원격 보존이 아니다.** 커밋·푸시는 별도 승인 대상이다.

> 정정 (2026-10-31): 위 문장은 푸시 이전 상태를 설명한 것이다. 이 디렉터리는 이후 커밋 `ff72b45b3422270a4b8c9cd28eb18e2e791b9fa2`로 브랜치 `ccr-0daec3e4-ierxrw`에 푸시되어 원격에 보존되었다. 이 정정으로 바뀐 파일은 이 README와 `SHA256SUMS`의 README 항목뿐이다.
