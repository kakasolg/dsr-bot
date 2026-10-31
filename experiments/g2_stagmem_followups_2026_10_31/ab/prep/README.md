# I1-current와 I1 + 표적 휘청 기억 비교 — 준비만 (2026-10-31, [cloud])

**상태: 준비 단계.**
- 학습, 예측, 기존 모델 호출은 하지 않았다.
- 이 디렉터리는 저장소 밖(`/tmp/stagmem/prep`)과 그 압축 묶음에만 있다. **원격 보존이 아니다.**
- 커밋과 푸시는 별도 승인 대상이다.

## 질문과 성격

> 표적 휘청 기억만 더해도, 전체 I2-memory에서 본 stagger_punish 개선과 reflex·face_first 손실이 다시 나타나는가?

- 앞서 본 결과에서 출발한 **후속 진단**이다.
- 블라인드 평가가 아니고, 개별 특징의 인과 검정도 아니다.
- 게임 성능에 대해서는 아무것도 말하지 않는다.

## A와 B (차이는 6열뿐)

- **A = I1-current**: 커밋된 `rf_i1current.features` / `Encoder`(@79742deb, 해시 대조)를 수정 없이 쓴다. train으로만 fit하며 61열이다.
- **B = A의 61열(같은 값, 같은 순서) + 휘청 기억 6열** = 67열. 명세는 `feature_spec.md`와 `config.json` `memory_features`에 있다.
  - `smem_active` (+ `__missing`): 진행 중인 휘청 기억이 있는가. 키가 없으면 결측(기록 안 됨)이다.
  - `smem_is_target` (+ `__missing`): 기억된 휘청 개체가 현재 표적인가.
  - `smem_target_since_s` (+ `__missing`): 현재 표적일 때만 휘청 연속 구간의 경과 초. 그 밖에는 결측이다.

## 모델 (A·B 같음)

`RandomForestClassifier(n_estimators=200, max_depth=12, min_samples_leaf=3, class_weight=None, random_state=20261031, criterion="gini", max_features=None, bootstrap=True, n_jobs=1)`

**max_features=None은 이번에 새로 정한 진단 설정이다.**
- 기존 C3 설정(`"sqrt"`)이 아니다.
- A와 B 둘 다 이 설정으로 새로 학습해야 한다. 보존된 C3 예측은 A를 대신할 수 없다.
- 과거 C3·C4 결과를 대체하지 않는다.
- 모든 특징을 고려해도 기억의 순수한 정보 가치가 분리되거나 인과가 성립하지는 않는다. bootstrap과 동점 처리의 무작위성은 남는다.
- 구현상 문제는 없다. sklearn 1.9.1은 `None`을 받고, I1에 이미 있는 NaN 열 처리도 그대로다.

## 고정한 것

- split: manifest @6ccafc0 그대로다. pending 22건은 제외한다.
- 목표: `rule`.
- 학습: train만 쓴다. val로 고르는 단계가 없다. seed 1개, dirty 재학습 없음, 추가 ablation 없음.

## 평가 계획 (학습 승인 뒤, `config.json` `evaluation`)

평가셋 4개를 각각 따로 본다: val · test · shift_zone · shift_ref.

**전체 지표**
- 정확도
- macro F1 두 종류, 각각의 label 목록
  - 보존된 primary 집합(기준선 lookup primary_classes)
  - 그 split의 모든 정답 클래스
- 클래스별 P/R/F1, 정답 수, 예측 수, 실행 수
- 실행별 정확도와 그 단순 평균

**진단 클래스와 짝비교**
- 진단 클래스: stagger_punish, reflex, face_first, after_swing
- scene 짝비교: 둘 다 정답 / A만 / B만 / 둘 다 오답 (실행별 포함)

**핵심 조건 칸**: 표적 휘청 + 표적이 아닌 살아 있는 적대 개체가 2.5 m 안에서 공격 애니
- 정의는 `conditional_reflex_audit.py` @3a0064f와 같다.
- 준비 단계에서 평가셋별 칸 수가 보존된 감사 결과와 같은지 확인했다.
- stagger_punish·reflex·face_first의 정답 수와 재현율을 보고한다. 범위는 전체와 212954 제외 두 가지다.
- scene 수와 실행 수를 함께 쓰고, 표본이 0이면 null로 둔다.

**해석 규칙**
- stagger_punish가 좋아지고 reflex나 face_first가 나빠지면: "작은 기억 묶음이 같은 방향의 맞교환을 재현했다"
- 한쪽 방향만 나타나면: 관측된 것만 보고하고, I2 전체 결과를 이 특징 탓으로 돌리지 않는다.
- 변화가 작으면: "이 구성에서는 재현되지 않았다". 기억이 무관하다고 결론 내지 않는다.
- 유의성, 인과, 게임 성능 개선은 주장하지 않는다.

## 미리 알아 둘 한계 (준비 중 확인)

- **기록 범위**: 휘청 기억은 93dce7b(P-80) 이후 코드에서만 기록된다.
  - train은 26실행 중 6실행, 129 scene만 키가 있다. 그중 표적 기억이 있는 경우는 43건이다.
  - 커밋 메타데이터로 보면 val은 0 scene, test는 68 scene(011929)만 이후 코드다. shift_zone과 shift_ref는 전부 이후 코드다.
- **결측 = 버전 표지**: `smem_active`의 결측은 대부분 코드 버전 표지와 같다. B와 A의 차이에는 기억 정보와 버전 정보가 섞인다.
- **기존 I2와 다른 정의**: I2-memory의 휘청 필드는 이번 정의와 다르다.
  - I2는 None 상태에서 남아 있던 `_stag_t`(train 23건)를 경과 시간으로 썼다.
  - I2는 None과 다른 개체를 모두 0으로 두었다.
  - 따라서 이 실험은 I2의 부분집합을 그대로 떼어 낸 것이 아니다.

## 파일

| 파일 | 내용 |
|---|---|
| `config.json` | 고정 설정 (질문, 참조 해시, 특징 명세, 모델, 평가 계획, 해석 규칙) |
| `feature_spec.md` | 필드, 갱신 순서, 시각 규약, 변환식, 결측 처리, train 상태표 |
| `stagmem_compare.py` | `prepare` / `train` 두 단계. prepare는 fit·predict를 막아 둔 채 행렬과 검사만 만든다. train은 `--approved TRAINING-APPROVED`가 있어야 돌고, prep_report와 config·스크립트 해시가 맞아야 한다 |
| `prep_report.json` | prepare 실행 결과: 열 목록, 공유 열 동일성(5 split 모두 true), 결측 일관성, 조건 칸 수 대조, train 상태 분포 |
| `prerun_hashes.txt` | prepare 실행 전 config와 스크립트 해시 |
| `ref_hashes.txt` | 참조 파일 전체 SHA-256 (커밋별) |
| `env_python.txt`, `env_pip_freeze.txt` | 환경 (pip freeze는 @79742deb requirements-freeze와 같음) |
| `commands.txt` | 준비와 학습 명령 (학습은 실행하지 않음) |
| `SHA256SUMS` | 이 디렉터리 파일 해시 (자기 자신 제외) |
