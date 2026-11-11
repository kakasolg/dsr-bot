# G4 수집·분할 계약 v1 (동결 2026-10-31, MoKa 승인: 묶음 2 · 기준 세이브 새로 만들기 · 워프 후 휴식) · [win]

이 파일을 바꾸면 v2로 올리고, v1로 모은 데이터와 조용히 합치지 않는다. 확인 불가 항목은 그대로 둔다.

## A. 고정 조건

| 항목 | 제안 값 | 근거 / 출처 |
|---|---|---|
| 수집 커밋 C | `6ccafc0f636c0976ea4289251ae5896afe2a7bee` (work HEAD = origin, 안 1) | CODE_DIFF.md 권장안. `game.save`·ctl `complete` 기록이 있는 유일한 커밋 |
| dirty | 포함 기준: settings `code.dirty_files` ⊆ {`.claude/launch.json`} (MoKa 변경, 코드 아님). 그 밖의 추적 파일이 바뀌면 제외. `experiments/g4_2026_10_31/`는 추적 안 됨이라 dirty 판정에 안 들어감(runinfo.code() 확인) | git status, 묶음 1 |
| 판단 함수 sha1 + RULES | rule_stagger_punish 742cafdfa4fb · _stagger_late 3e9d1be57093 · _other_swinging ddf6e30b509e · prep_reflex ed2af2bd47b4 · RULES bc4c029d4fe7 — **G2 값과 같음** | `ast.get_source_segment` sha1, C의 blob과 작업 트리 둘 다 같음 |
| scenes.py / foes.py / weapons.py sha256 (git blob) | 065f4717f2e1… (G2와 같음) / 01153c4e7f00… (G2 T1·T2와 다름: 255041 windup) / 7c6b506304b5… (다름: Claymore 타이밍) | `git show C:<path>` |
| 해시 기준 주의 | `core.autocrlf=true` → 작업 트리 파일은 CRLF라 sha256이 다르다(scenes f410919c…, foes ecd680c9…, duel 681f03c4…; weapons만 LF라 같음). **파일 해시는 git blob 기준으로 기록**한다 | 직접 계산 |
| Python·vgamepad·게임 | 봇 `.venv`: Python 3.12.10, vgamepad 0.1.0, pymem 1.14.0, numpy 2.5.3 (`collection_contract.json`). 모든 명령은 `.venv\Scripts\python.exe`. 게임: Offline, App ver 1.03.1, Regulation 1.04 (타이틀 화면), exe sha256 a45aaa36dd2f6cc1… BOT_GAME=dsr | 조회 |
| 무기·grip·style | Claymore 한손: weapon id **301005**(+5, G2 10-13 18:39 이후 burg-altar·10-19~10-30 실행 기록) grip 1, `--style guard`(기본) | settings `game` |
| 플래그 | 허용: `--radar --ctl-scenes --note`. burg-upper는 `--seg 1-8`. 금지: `--ctl-spans`(타이밍 확인 불가 항목 추가), `--ctl-frames`, `--basic`, `--no-rest`, `--no-lure`, `--attack-audit`, 게임 메모리 쓰기(무적·투명·워프) | G2 P-80 이후 burg 실행 argv |
| 명령줄 | U: `.venv\Scripts\python.exe run.py burg-upper --seg 1-8 --radar --ctl-scenes --note "g4-U<n>-<YYYYMMDD> save:<12>"` / A: `.venv\Scripts\python.exe run.py burg-altar --radar --ctl-scenes --note "g4-A<n>-<YYYYMMDD> save:<12>"` (burg-altar 기본 dists 5,8,12,15 · fb_target hollow) | |
| 기준 세이브 | `backup-20261031-153428-g4-base`, sl2 sha256 `c52cd462eed4aac62ccb944edb48ae0dc3f4fe30b3d28dea444ace6b6102fe6d`. 만든 법: 이어하기(1012964 근처) → `bonfire_warp(1012962)` + `farm.rest(SPOTS["burg-bonfire"])` (준비 단계에서만 메모리 쓰기 1회, 수집 실행에는 안 씀) → `savepoint.py save g4-base` (1차 ESC 3번 실패, 2차 성공). 기준값: 화톳불 1012962, 위치 (2.45, −10.02, −61.05), HP 793/793, estus 10 (id 205), 소울 1021, 인간성 0, 무기 301005 한손, 퀵슬롯 [205, 292, −1, −1, −1], 캐릭터 Asylum Test. 레벨·반지·방어구·화염병 개수 등은 확인 불가 | `run.py status`, savepoint.json |
| 시작 상태 확인 | restore 출력 `sl2 되돌림 (<기준 sha 앞 8>)` 일치, `저장 자리와 ≤ 3 m`. settings `game`: last_bonfire = 기준값, pos 1 m 안, weapon [301005] grip 1, hp 최대 = 기준값, estus = 기준값, souls·humanity·knives·quick_items = 기준값 | settings `game` 블록 |
| 해시 주의 | settings `game.save.sha256`은 **이어하기 뒤 게임이 다시 쓴 라이브 파일** 해시다. 10-31 r7 실행: 복원한 백업 829d5ae2 → settings에는 4488f13f. 그러므로 "save.sha256 = 기준 백업 sha" 조건은 쓸 수 없다. 대신 restore 로그의 복사 직후 해시로 확인하고, settings 값은 기록만 한다 | 10-31 r7 settings + savepoint.py 코드 |
| 종료 조건 | 봇 자체 종료(완료·사망·퀵 종료·low_hp)는 모두 포함. 사람 중단은 게임 충돌·소프트락(30 s 이상 진행 없음)·안전 문제만, 개입 기록표에 기록 | |
| 개입 기록 | `INTERVENTION_LOG_TEMPLATE.md` 형식, 식별자 `g4-<U|A><n>-<YYYYMMDD>` | |

## B. 실행 예산과 종료 규칙

| 항목 | 제안 |
|---|---|
| 총 실행 수 | **20 = burg-upper 10 + burg-altar 10** (대안: 12 = 6+6) |
| 순서 | U1 A1 U2 A2 … U10 A10 (교대 고정) |
| 시간 | G2 같은 명령 실행 4.6–9.4 분(로그 기준) + 복원 ~2 분 + 실행 후 절차 ~3 분 → 1회 약 15 분, 20회 약 5 시간. 2 세션(U1–A5 / U6–A10)으로 나눈다 |
| 예상 scene | G2 같은 명령 실행당 30–68 → 20회 약 600–1000 (추정) |
| 종료 규칙 | 목록을 다 돌면 끝. 결과를 보고 연장·교체하지 않는다 |
| 다시 돌리기 | 시작도 못 한 경우만, 새 순번(U11, A11…)으로 추가, 원래 행 유지 |
| 부족할 때 | 판단 보류로 보고, 추가 수집은 별도 승인 |

## C. 포함·제외 기준

- 포함: commit = C, dirty 기준(A 표 결정대로), 고정 플래그, scene schema `dsr-scene-input/0.2`, ctl end `complete True`, restore 해시 일치, 시작 상태 일치
- 제외: 위 위반, 싸움 중 사람 조작, 시작 불가
- 포함하는 것: 사망, 퀵 종료, low_hp, 가드 장면 0, scene 0(기여 0)

## D. 실행 단위 split (자료 보기 전 고정)

- 단위: 실행. 명령마다 순번으로 고정 배정:
  - train: 1, 2, 4, 5, 7, 9 → U·A 각 6 = 12 실행
  - val: 3, 8 → 4 실행
  - test: 6, 10 → 4 실행
- 제외된 실행 자리는 비운다(다른 실행으로 채우지 않는다). 다시 돌린 실행(U11…)은 원래 순번의 split을 물려받는다.
- 명령별 집계는 보조. split 이름에 "지역"을 쓰지 않는다.
- 최소 기준(운영상): val·test 각각에서 stagger_punish 가드 분기가 ≥ 2 실행에 나타나야 그 분기를 주 진단에 쓴다. 못 미치면 기술 보고만.

## E. 학습·평가 계약 (묶음 4 전에 확정)

| 항목 | 제안 |
|---|---|
| 기준선 | 다수결, lookup(G2 `baselines.py`·`config.json` 정의), A |
| 주 비교 | A vs B (B = A + 휘청 기억 6열, G2 정의 그대로) |
| 보조 대조군 | M, B0 — 넣을지 MoKa 결정 (권장: 넣음, seed 1개) |
| 모델·설정 | RF n_estimators 200, max_depth 12, min_samples_leaf 3, class_weight None, max_features None, n_jobs 1 (G2 고정값). **설정 탐색 없음** → val은 진단만 |
| seed | 20261101, 20261102, 20261103, 20261104, 20261105 — 평균·최소·최대 보고, 골라 쓰지 않음 |
| 학습 횟수 | A 5 + B 5 (+ M 1 + B0 1, seed 20261101) = 10 (또는 12) |
| 주 지표 | test 정확도의 B − A (seed별, 평균) + 실행별 짝비교(4 실행) |
| 보조 지표 | macro F1(G2 고정 label 집합 / 정답 전체), 클래스별, 실행별, 분기별(가드/공격/돌기) 재현율 |
| 해석 금지 | 게임 성능, 인과, 버전 분리, G2와 합산 |
| 모델 파일 | 저장 안 함, 예측만 저장 (G2와 같음) — 바꾸려면 MoKa 결정 |
| 분석 환경 | 봇 .venv에는 scikit-learn 없음. 별도 venv(예: `D:\dev\dsr-bot\experiments\g4_…\.venv`, Python 3.13 + scikit-learn 1.9.1 + numpy 2.5.4, cloud와 같은 버전) 설치는 묶음 4에서 승인 |
