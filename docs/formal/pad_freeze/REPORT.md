# control.Pad freeze — 유한 범위 TLA+ 모델 안전성 검사 + 실제 코드 재현 (2026-10-27, 2차)

**분류**: 이 보고서는 두 가지로만 이루어져 있다. 하나는 유한 범위 TLA+ 모델의 안전성 검사(TLC), 다른 하나는 실제 Pad 코드로 순서를 고정해 재현한 결과다. 구현 전체를 정형 검증한 것은 **아니다**.
모델이 control.py와 같은지는 사람이 줄 단위로 대조한 것이고, 도구로 확인한 것이 아니다.
봇 코드 수정, 게임 실행, commit/push는 하지 않았다. 이 폴더는 커밋하지 않은 상태다.
패치 설계는 [PATCH_PLAN.md](PATCH_PLAN.md)에 있다.

## 0. 검사 대상과 실행 정보

| 항목 | 값 |
|---|---|
| spec | `PadFreeze.tla`, sha256 `65ff4892c950fc63f987a5d29d5eb6303e993b90474d307d6783d2cbb0f965c6`, 수정 시각 16:52:06 (배치 시작 16:52:22 전, 배치 중 수정 없음) |
| 실행기 | `run_tlc.py`, sha256 `fc0f32ff84d771e10116068b247a4b93a394e9bca4fae90cff61514c425e9364` |
| 도구 | TLC2 Version 2.19 of 08 August 2024 (rev 5a47802), tla2tools.jar v1.7.4 (sha256 `936a2620…e88`), OpenJDK Temurin 21.0.12.1+1 |
| 배치 명령 | `python docs/formal/pad_freeze/run_tlc.py <scratchpad>/tla/tla2tools.jar` |
| TLC 1회 명령 | `java -XX:+UseParallelGC -cp tla2tools.jar tlc2.TLC -deadlock -workers auto -metadir out/states_<n> -config cfg/<n>.cfg PadFreeze` |
| worker | `-workers auto` → 32 worker / 32 cores (로그 2행) |
| cfg 형식 | `CONSTANTS Variant, Script, MaxOps, UseNudge=TRUE, NGuard, NTap=TRUE, NHold` + `INVARIANT TypeOK` + `INVARIANT <성질 하나>` |
| 결과 | `out/results.tsv` (16:57:03에 이번 배치로 다시 씀, 200행), 로그는 `out/<n>.log` 200개, 표는 `out/tables.md` (`table.py`) |
| 실제 코드 재현 | `.venv/Scripts/python.exe docs/formal/pad_freeze/repro_new.py`, 출력은 `out/repro_new.txt` |

**처리 건수 (200회 모두 처리, 실행 오류 0)**:

| 종류 | 실행 | 정상 완료·성립 (HOLDS) | 반례로 종료 (VIOLATED) | 실행 오류 (ERROR / TYPE-ERROR) |
|---|---|---|---|---|
| 안전 성질 | 140 | 94 | 46 | 0 |
| 도달 탐침 (위반이 기대값) | 60 | 7 | 53 | 0 |
| 합계 | 200 | 101 | 99 | 0 |

200회가 모두 처리됐다는 것과 안전 성질이 모두 통과했다는 것은 **다른 이야기다**. 안전 성질 46건이 위반이고, 그 내역은 §4에 있다. 패치 후보 "minimal"에도 위반이 4건 남는다. S6 2건과 S5(hold) 2건으로, 둘 다 freeze와 무관한 평상시 결함 후보다(§5).

**시간 (TLC 내부 vs 전체 wall time)**:
- TLC가 로그에 남긴 `Finished in Ns`를 200회 합하면 **89 s**다. 초 단위 내림이라 근사치다. 이 값은 상태 탐색과 TLC 내부 처리 시간이다.
- 배치 전체 wall time은 첫 TLC 시작 16:52:22부터 마지막 종료 16:57:03까지 **약 281 s**다.
- 차이 약 190 s는 TLC 밖의 비용이다. 실행마다 JVM 시작과 spec 파싱이 있고(로그의 `Starting...`는 파싱 뒤에 찍힘), 상태 디렉터리 삭제와 Python 실행기도 시간을 쓴다. 한 번에 TLC 1개씩 순서대로 돌렸다.
- 가장 오래 걸린 실행은 TLC 내부 5 s다(`current … m4`, 약 238만 distinct).

**데드락 검사는 꺼져 있다**: 모든 실행에 `-deadlock`을 줬고, TLC에서 이 옵션은 교착(다음 행동이 없는 상태)을 **검사하지 않는다**는 뜻이다.
이유는 모델의 스크립트(h, e)가 끝나고 o·n이 호출 상한을 다 쓰면 더 할 행동이 없는 것이 정상 종료이기 때문이다. 이걸 교착으로 세면 모든 실행이 거짓 오류로 멈춘다.
그래서 이 보고서는 **안전성(불변식)만** 다룬다. 진행성(liveness), 예를 들어 "언젠가 unfreeze된다"나 "언젠가 B가 눌린다"는 검사하지 않았다.

**반례 표현**: 성질마다 따로 돌렸으니, 각 위반은 **그 성질의 반례**다. TLC는 너비 우선으로 탐색하지만 32 worker로 병렬 실행했고, 반례가 그 성질의 최단 반례인지는 따로 확인하지 않았다. 그래서 "최단 반례"라고 쓰지 않는다. `run_tlc.py` 설명 문자열(5행)에는 "shortest"라고 적혀 있지만, 위 해시를 유지하려고 고치지 않았다. 다음에 고칠 때 함께 바꾼다. 같은 성질을 다시 돌리면 다른 반례가 나올 수 있다. 실제로 1차와 2차 배치에서 같은 성질의 반례 순서가 달랐다.

## 1. 실제 Pad 코드 재현 (1단계) — 모델 반례와 구분

방법:
- 실제 `control.Pad`를 fake vgamepad(`tests/pad_fakes.py`) 위에서 돌린다.
- 비홀더는 오래 사는 이름 붙은 스레드(`Actor`, "guardkeep"/"nav")로 실행하고, 호출마다 `Event`로 끝날 때까지 기다려 순서를 고정한다.
- 시간은 `control.time`을 `Clock`(`time()`이 지정한 값에서 멈춤)으로 바꿔 넣어 조절하고, `sleep`은 실제 그대로다.
- 봇 코드는 고치지 않았고, 이 스크립트는 테스트 모음에 들어가지 않는다.

| 재현 | 모델 반례 (TLC) | 실제 코드 결과 | 비고 |
|---|---|---|---|
| **K1-pre** freeze 전 keep_guard | `block_quit_m3_S1_MenuClean`: oKeepGuard → hFreeze → hNeutral1 → LB | **재현됨**: freeze 전 LB 켜짐 → freeze 직후 꺼짐 → 홀더 neutral 뒤 LB 켜짐 → 메뉴 보고 2개 모두 LB. freeze 중 다른 스레드 호출 0회 | 경합이 필요 없는 결정적 순서 |
| **LB-orphan-a** freeze 중 만료·unkeep (메뉴 창 안) | `current_quit_m3_S6_NoOrphanLB(noguard)` 계열 | **재현됨**: unkeep 뒤 아무도 원하지 않는 LB가 메뉴 보고에 남음 | 홀더의 마지막 neutral이 지움 |
| **LB-orphan-b** 같은 순서, unfreeze 뒤까지 | (모델에도 이 순서로는 없음) | **재현 안 됨** | 아래 이유 1 |
| **LB-orphan-d** unfreeze 뒤 LB 고아 (TLC 순서) | `current_quit_m3_noguard_S6_post`: 메뉴 press 뒤 oKeepGuard → hNeutral2(LB) → TickGuard → oUnkeep(떼지 않음) → hUnfreeze | **재현됨**: unfreeze 직후 LB=True, unkeep 한 번 더 뒤에도 LB=True, gw/kept/fg 모두 False | 지난 보고의 "unfreeze 뒤에도 LB가 남는다"는 **이 순서**에서 성립 |
| **LB-orphan-c** freeze 중 keep_guard + guard(True) → unfreeze 뒤 LB 고아 | NGuard 포함 S6 계열 | **재현됨**: unfreeze·만료·unkeep 뒤 LB=True | guard(True)가 `_kept`를 지우는 평상시 결함(S6)과 같은 뿌리 |
| **스테일 sprint** 마지막 neutral과 unfreeze 사이 sprint(True) | `ownerNeutral_quit_m4_S4_ReSprint`: hNeutral2 → nSprintOn → hUnfreeze → nSprintOn(B 없음) | **재현됨** (unfreeze 때 0.0 s, 1.0 s 경과 둘 다): unfreeze 뒤 sprint(True) 1·2회 모두 B 꺼짐. 5 s 뒤 release_due 후에도 B 꺼짐, `_b_since` 남음 | |
| 스테일 sprint, nav.Mover 경유 (b): set('sprint')가 마지막 neutral과 unfreeze 사이 | 같은 반례 | **재현됨**: Mover.mode=sprint인데 B 꺼짐, `_b_since` 남음 | 실제 호출자 경로 |
| 스테일 sprint, nav.Mover 경유 (a): set('sprint')가 마지막 neutral 앞 | — | **재현 안 됨** | 아래 이유 2 |
| **S5f** freeze 중 버려진 tap(Y)의 예약 → unfreeze 뒤 hold(Y)를 뗌 | `current_quit_m3_hold_S5f_FrozenDueNoKill` | **재현됨** | 새 후보 (§5) |
| **S5 평상시** tap(Y) 예약 → hold(Y, True) → release_due | `minimal_quit_m3_hold_S5_StaleNoKill` | **재현됨** | freeze와 무관, API 수준 (§5) |

합계: 11개 중 9개 재현됨, 2개 재현 안 됨.

**재현 안 된 2개와 이유**:
1. **LB-orphan-b**: freeze 중 keep_guard → 홀더 첫 neutral(LB) → 만료 → 비홀더 unkeep → 메뉴 → **홀더 마지막 neutral** → unfreeze.
   마지막 neutral(watch.py:308)이 `force_guard`가 끝난 **뒤에** 실행된다. 그래서 control.py:423에서 장치를 reset하고 :425-426에서 LB를 다시 누르지 않는다. 고아 LB는 메뉴 창 안에서만 있다(a에서 재현).
   unfreeze 뒤까지 남으려면 keep_guard가 마지막 neutral **직전에** 들어와 그 neutral 때 `force_guard`가 아직 켜져 있어야 한다. 그 순서가 d이고, d는 재현됐다.
2. **스테일 sprint, Mover (a)**: Mover가 마지막 neutral **앞에서** sprint(True)를 부르면 그 neutral이 어린 hold를 보고 B를 실제로 누르고 예약한다(:427-431).
   unfreeze 뒤 Mover가 다시 맞추며 sprint(True)를 부르면 :613이 그 예약을 지운다. 그래서 B가 그대로 유지되어 정상 동작이다.
   스테일 상태는 sprint(True)가 마지막 neutral과 unfreeze **사이**에 들어올 때만 생긴다(b에서 재현). watch.py:308과 :309는 연달아 있는 두 줄이라 그 틈은 짧다. 실제 게임에서 얼마나 자주 겹치는지는 측정하지 않았다.

## 2. 성질의 정확한 식과 cfg 대응 (4단계)

식은 `PadFreeze.tla` 맨 아래 그대로다. 보조 정의는 다음과 같다.
- `Menu == Script = "quit" /\ pc["h"] \in {"pd","pu","n2"}`: quitout의 첫 neutral 뒤부터 마지막 neutral 전까지의 메뉴 입력 창
- `W(t) == pad.owner \in {None, t}`: t의 쓰기가 장치에 들어감

| 성질 | 식 | cfg (`cfg/<variant>_<script>_m<N>[_noguard][_hold]_<성질>.cfg`) |
|---|---|---|
| S1 `S1_MenuClean` | `Menu => pad.dev \subseteq g.hHeld` | quit, m3/m4, NGuard=TRUE, NHold=FALSE |
| S1b `S1b_MenuNoB` | `Menu => "B" \notin pad.dev` | 같음 |
| S2 `S2_NoOrphanA` | `"A" \in pad.dev => ("A" \in g.hHeld \/ pad.due["A"] # "no")` | tapper, m3/m4 |
| S3 `S3_Handoff` | `pc["h"] \in {"n1","tp","pd","pu","n2","uf"} => pad.owner = "h"` | quit, m3/m4 (UseNudge=TRUE) |
| S4 `S4_ReSprint` | `(pad.owner = None /\ g.wantB /\ g.syncB) => "B" \in pad.dev` | quit, m3/m4 |
| S4 `S4_ReGuard` | `(pad.owner = None /\ g.wantLB /\ g.syncLB) => "LB" \in pad.dev` | quit, m3/m4 |
| S5 `S5_StaleNoKill` (재작성) | `~g.kill`: kill은 release_due가 **자기 예약보다 나중에 눌린** 버튼(`g.newer`)을 장치에서 뗄 때 TRUE | quit·tapper, m3/m4 (NHold=FALSE), quit·tapper m3 (NHold=TRUE) |
| S5f `S5f_FrozenDueNoKill` | `~g.killFrozen`: 위 kill 중 그 예약이 freeze 중 `_NullPad`로 버려진 tap에서 온 경우 | quit·tapper, m3/m4, NHold=TRUE |
| S6 `S6_NoOrphanLB` (참고) | `"LB" \in pad.dev => (pad.gw \/ pad.kept \/ pad.fg)` | quit, m3/m4, NGuard=TRUE와 FALSE |
| S6 `S6_post` (참고) | `(pc["h"] = "done" /\ pad.owner = None) => S6_NoOrphanLB` | quit, m3/m4, NGuard=FALSE |

ghost 변수:
- `syncB`/`syncLB`: n의 마지막 sprint/guard 요청이 쓰기 가능한 상태에서 들어왔고, 그 뒤 epoch 증가(freeze, unfreeze, 누구의 neutral)가 없었음. nav.Mover가 epoch 변화를 보고 다시 맞추는 규칙(nav.py:62-68)을 접은 것이다.
- `newer`: 장치의 눌림이 그 버튼의 해제 예약보다 나중인 버튼.
- `frozenA`: A 예약이 쓰기 불가 tap에서 생김.

**호출 상한을 거는 방식**:
- o(guardkeep)와 n(결정 루프)의 호출은 스레드마다 `ops[t] < MaxOps`일 때만 가능하다. 아무것도 바꾸지 않는 호출도 1회로 센다(`Step`).
- h(quit-out)와 e(nudge)는 고정 스크립트라 상한이 없다.
- Tick(시간 경과)은 상한이 없다. 각 Tick은 단조롭게 움직이므로(fg TRUE→FALSE, bs young→old, due pending→ripe) 상태 공간은 유한하다.
- m3 = 스레드당 3회, m4 = 4회. 상한을 넣은 m3/m4 행동 집합 사이에는 포함 관계가 있다(m3에서 가능한 행동열은 m4에서도 가능). 그래서 m3에서 도달한 탐침은 m4에서도 도달한다. 탐침은 m3에서만 돌렸다.

**속성이 사실상 검사되지 않은 경우 확인 (도달 탐침)**: 탐침은 "그 성질에서 문제가 되는 경우에 도달할 수 있는가"를 묻는다. 위반이 나와야 정상이다(= 도달함). 표는 §4.2.
- 모든 변형에서 도달:
  - `R1_menuAfterBlockedCall`: 비홀더가 freeze 중에 호출한 뒤 메뉴 창에 도달
  - `R3`: nudge의 unfreeze가 quit-out 홀더 아래에서 대기
  - `R4`: quit-out 뒤 다시 한 sprint/guard 요청
  - `R2`: 홀더 tap의 예약이 익음
  - `R6`: quit-out 뒤 kept가 남음
  - `R5`: tapper와 hold 설정에서 newer 눌림의 예약이 익음

  → S1, S1b, S2, S3, S4, S5f, S6_post는 모든 변형에서 그 경우를 탐색했다.
- **패치 변형에서 성립한 탐침**은 패치가 그 전제 자체를 없앴다는 뜻이다:
  - `R1_menuWithYoungB`(block, both, minimal)
  - `R1_menuWithKeep`(minimal)
  - `R5_newerPressRipe` quit, NHold=FALSE(block, both, minimal)

  이 셋은 "검사 안 됨"이 아니라 "패치로 도달 불가"다. 단, 이것으로 S1/S1b가 성립한 이유는 "그 상태에 갈 수 없어서"이고, 여기에 기대고 있음을 밝혀 둔다.
- **사실상 검사되지 않은 것: `S5_StaleNoKill`, NHold=FALSE(모든 변형).**
  이 설정에서 `newer`가 생기는 경로는 홀더 h의 `press` 하나뿐이다. 그 동안 h가 freeze를 쥐고 있으므로 유일한 `release_due` 호출자 n은 쓰기 불가다. 그래서 `kill`은 **구조상 TRUE가 될 수 없다**.
  이 줄의 "성립"(quit/tapper × m3/m4 × 5 변형 = 20건)은 검사 결과로 세지 않는다. S5는 NHold=TRUE 실행으로 판정한다.
- `S4_ReGuard`가 모든 변형에서 성립한 이유는 `hold(LB, True)`가 언제나 실제로 누르기 때문이다(:539). 탐침 R4_reguard는 도달했다.

## 3. S5 재작성과 S6 분리 (5단계)

- **이전 S5**("quit-out 뒤 예약된 버튼은 눌려 있음")는 너무 강했다. 해가 없는 남은 예약도 위반으로 셌다. 판정에서 뺐다.
- **새 S5** = "오래된 예약이 나중에 눌린 입력을 떼지 않음". `hold`가 `_due`를 건드리지 않는다는 점을 모델에 넣었다(NHold). 실제 코드에서 tap과 hold가 겹치는 버튼은 Y다(control.py:551 `two_hand_toggle` tap, :630/:634 `two_hand_right` hold).
  - NHold=TRUE이면 **모든 변형에서 위반**한다. 반례는 freeze가 없다. `minimal_quit_m3_hold_S5`: nTap → TickDue → nHoldOn → nReleaseDue가 hold를 뗌. → **평상시 결함 후보**이고 freeze 패치 범위 밖이다. 실제 코드로도 재현했다(S5 평상시).
  - 지금 코드에서 실제로 일어나는지: `two_hand_right`는 결정 루프 안에서 sleep하며 막고 있고, `release_due`를 부르는 것도 결정 루프뿐이다. 그래서 실제 일어나는 경로는 찾지 못했다. API 수준 결함이다.
- **S5f** = 새 S5 중 freeze 때문에 생긴 부분.
  - current와 ownerNeutral에서 위반: 반례는 nudge freeze 중 n의 tap이 `_NullPad`로 버려지면서도 `_due[A]`를 남기고, unfreeze 뒤 n의 hold를 그 예약이 뗀다.
  - block, both, minimal에서는 m3/m4 모두 성립한다(비홀더 tap이 차단되어 예약이 생기지 않음).
  - 실제 코드로 재현했다(Y).
- **S6 분리**:
  - (i) **평상시 LB 고아**: NGuard=TRUE에서 **모든 변형 위반**이고, 반례에 freeze가 없다(`minimal_quit_m3_S6`: oKeepGuard → nGuardOn(kept=FALSE) → nGuardOff(:536-537 조기 return) → TickGuard). **별도 결함 후보**이고 이 패치로 고쳐지지 않는다.
  - (ii) **freeze 관련 LB 고아**: NGuard=FALSE로 n의 guard 호출을 빼고 검사했다. current만 위반하고(S6, S6_post 모두), block, ownerNeutral, both, minimal은 m3/m4에서 성립한다. 반례 `current_quit_m3_noguard_S6_post`(10 상태, unfreeze 뒤 LB 고아)는 실제 코드 LB-orphan-d로 재현됐다.

## 4. TLC 결과 표

셀은 판정과 distinct states다. 위반이면 반례 길이(초기 상태 포함 상태 수)도 적었다. 위반 행의 distinct는 반례를 찾고 멈출 때까지 센 값이다.

### 4.1 안전 성질 (140회)

| 실행 (성질 · 스크립트 · 호출 상한 · 설정) | current | block | ownerNeutral | both | minimal |
|---|---|---|---|---|---|
| S1_MenuClean · quit · m3 | **위반** 1,667 (trace 5) | **위반** 1,089 (trace 4) | 성립 316,881 | 성립 70,834 | 성립 53,785 |
| S1b_MenuNoB · quit · m3 | **위반** 1,369 (trace 4) | 성립 69,871 | 성립 316,881 | 성립 70,834 | 성립 53,785 |
| S3_Handoff · quit · m3 | 성립 637,758 | 성립 69,871 | 성립 316,881 | 성립 70,834 | 성립 53,785 |
| S4_ReSprint · quit · m3 | **위반** 3,384 (trace 6) | 성립 69,871 | **위반** 4,177 (trace 6) | 성립 70,834 | 성립 53,785 |
| S4_ReGuard · quit · m3 | 성립 637,758 | 성립 69,871 | 성립 316,881 | 성립 70,834 | 성립 53,785 |
| S5_StaleNoKill · quit · m3 ※ | 성립 637,758 | 성립 69,871 | 성립 316,881 | 성립 70,834 | 성립 53,785 |
| S6_NoOrphanLB · quit · m3 | **위반** 3,853 (trace 7) | **위반** 3,239 (trace 5) | **위반** 4,785 (trace 5) | **위반** 3,328 (trace 8) | **위반** 2,418 (trace 5) |
| S6_NoOrphanLB · quit · m3 · noguard | **위반** 3,018 (trace 6) | 성립 30,824 | 성립 140,905 | 성립 31,745 | 성립 24,920 |
| S6_post · quit · m3 · noguard | **위반** 13,422 (trace 10) | 성립 30,824 | 성립 140,905 | 성립 31,745 | 성립 24,920 |
| S2_NoOrphanA · tapper · m3 | **위반** 1,894 (trace 5) | 성립 98,527 | **위반** 3,224 (trace 5) | 성립 104,641 | 성립 72,757 |
| S5_StaleNoKill · tapper · m3 ※ | 성립 694,660 | 성립 98,527 | 성립 456,982 | 성립 104,641 | 성립 72,757 |
| S1_MenuClean · quit · m4 | **위반** 1,364 (trace 6) | **위반** 1,624 (trace 4) | 성립 1,182,771 | 성립 247,331 | 성립 198,807 |
| S1b_MenuNoB · quit · m4 | **위반** 1,426 (trace 4) | 성립 239,045 | 성립 1,182,771 | 성립 247,331 | 성립 198,807 |
| S3_Handoff · quit · m4 | 성립 2,382,891 | 성립 239,045 | 성립 1,182,771 | 성립 247,331 | 성립 198,807 |
| S4_ReSprint · quit · m4 | **위반** 4,364 (trace 6) | 성립 239,045 | **위반** 2,772 (trace 9) | 성립 247,331 | 성립 198,807 |
| S4_ReGuard · quit · m4 | 성립 2,382,891 | 성립 239,045 | 성립 1,182,771 | 성립 247,331 | 성립 198,807 |
| S5_StaleNoKill · quit · m4 ※ | 성립 2,382,891 | 성립 239,045 | 성립 1,182,771 | 성립 247,331 | 성립 198,807 |
| S6_NoOrphanLB · quit · m4 | **위반** 3,621 (trace 6) | **위반** 3,200 (trace 8) | **위반** 4,102 (trace 5) | **위반** 3,530 (trace 5) | **위반** 3,514 (trace 5) |
| S6_NoOrphanLB · quit · m4 · noguard | **위반** 3,458 (trace 6) | 성립 85,783 | 성립 395,779 | 성립 89,213 | 성립 73,069 |
| S6_post · quit · m4 · noguard | **위반** 21,048 (trace 11) | 성립 85,783 | 성립 395,779 | 성립 89,213 | 성립 73,069 |
| S2_NoOrphanA · tapper · m4 | **위반** 2,652 (trace 6) | 성립 306,163 | **위반** 3,083 (trace 6) | 성립 330,137 | 성립 241,897 |
| S5_StaleNoKill · tapper · m4 ※ | 성립 2,478,509 | 성립 306,163 | 성립 1,617,135 | 성립 330,137 | 성립 241,897 |
| S5_StaleNoKill · quit · m3 · hold | **위반** 7,222 (trace 5) | **위반** 4,570 (trace 5) | **위반** 9,556 (trace 6) | **위반** 5,249 (trace 6) | **위반** 3,592 (trace 6) |
| S5f_FrozenDueNoKill · quit · m3 · hold | **위반** 26,765 (trace 8) | 성립 82,565 | **위반** 25,021 (trace 11) | 성립 85,640 | 성립 65,126 |
| S5f_FrozenDueNoKill · quit · m4 · hold | **위반** 37,361 (trace 8) | 성립 309,958 | **위반** 22,012 (trace 8) | 성립 329,710 | 성립 261,469 |
| S5_StaleNoKill · tapper · m3 · hold | **위반** 8,196 (trace 6) | **위반** 4,701 (trace 5) | **위반** 10,358 (trace 8) | **위반** 4,026 (trace 10) | **위반** 3,683 (trace 5) |
| S5f_FrozenDueNoKill · tapper · m3 · hold | **위반** 50,365 (trace 8) | 성립 119,928 | **위반** 33,566 (trace 8) | 성립 128,781 | 성립 91,814 |
| S5f_FrozenDueNoKill · tapper · m4 · hold | **위반** 37,426 (trace 8) | 성립 420,365 | **위반** 22,201 (trace 8) | 성립 458,131 | 성립 342,705 |

※ NHold=FALSE의 S5는 구조상 위반이 나올 수 없다(§2). 검사 결과로 세지 않는다.

### 4.2 도달 탐침 (60회, 위반 = 도달함 = 기대값)

| 실행 | current | block | ownerNeutral | both | minimal |
|---|---|---|---|---|---|
| R1_menuAfterBlockedCall · quit · m3 | 도달 | 도달 | 도달 | 도달 | 도달 |
| R1_menuWithKeep · quit · m3 | 도달 | 도달 | 도달 | 도달 | **도달 불가** 53,785 (패치가 제거) |
| R1_menuWithYoungB · quit · m3 | 도달 | **도달 불가** 69,871 | 도달 | **도달 불가** 70,834 | **도달 불가** 53,785 |
| R3_nudgeUnfreezeLate · quit · m3 | 도달 | 도달 | 도달 | 도달 | 도달 |
| R4_resprintAfterQuit · quit · m3 | 도달 | 도달 | 도달 | 도달 | 도달 |
| R4_reguardAfterQuit · quit · m3 | 도달 | 도달 | 도달 | 도달 | 도달 |
| R5_newerPressRipe · quit · m3 | 도달 | **도달 불가** 69,871 | 도달 | **도달 불가** 70,834 | **도달 불가** 53,785 |
| R6_afterQuitWithKeep · quit · m3 · noguard | 도달 | 도달 | 도달 | 도달 | 도달 |
| R2_ripeAWhileFrozen · tapper · m3 | 도달 | 도달 | 도달 | 도달 | 도달 |
| R5_newerPressRipe · tapper · m3 | 도달 | 도달 | 도달 | 도달 | 도달 |
| R5_newerPressRipe · quit · m3 · hold | 도달 | 도달 | 도달 | 도달 | 도달 |
| R5_newerPressRipe · tapper · m3 · hold | 도달 | 도달 | 도달 | 도달 | 도달 |

(각 셀의 distinct·trace 길이는 `out/tables.md`에 있다.)

### 4.3 성질별 반례 (이번 배치 로그, `python trace.py out/<n>.log`, 바뀐 필드만)

```
current_quit_m3_S1_MenuClean      hFreeze → eFreeze(거절) → oKeepGuard(fg, kept; 장치 그대로) → hNeutral1: dev={LB}
block_quit_m3_S1_MenuClean        oKeepGuard(dev={LB}) → hFreeze(dev={}) → hNeutral1: dev={LB}        ← K1-pre, 경합 없음
current_quit_m3_S1b_MenuNoB       hFreeze → nSprintOn(bs=young) → hNeutral1: dev={B}, due.B=pending     ← K2
ownerNeutral_quit_m4_S4_ReSprint  … hNeutral2 → nSprintOn(bs=young, 장치 그대로) → hUnfreeze → nSprintOn: B 없음
current_tapper_m3_S2_NoOrphanA    hFreeze → hTap(A) → TickDue → nReleaseDue: due.A=no, A는 장치에 남음 ← K3
current_quit_m3_noguard_S6_post   … hPressDown → oKeepGuard → hPressUp → hNeutral2(dev={LB}) → TickGuard → oUnkeep(kept=F, 안 뗌) → hUnfreeze
current_quit_m3_hold_S5f          eFreeze → eNeutral → nTap(due.A, frozenA) → eUnfreeze → nHoldOn(dev={A}) → TickDue → nReleaseDue: A 뗌
minimal_quit_m3_S6_NoOrphanLB     oKeepGuard → nGuardOn(kept=F) → nGuardOff(조기 return) → TickGuard       ← freeze 없음
minimal_quit_m3_hold_S5           oKeepGuard → nTap → TickDue → nHoldOn → nReleaseDue: A 뗌                ← freeze 없음
```

### 4.4 변형 비교 요약 (이 모델, m3/m4 범위)

| 변형 | S1 | S1b | S2 | S3 | S4 sprint | S5f | S6 (noguard) | 평상시 S5/S6 |
|---|---|---|---|---|---|---|---|---|
| current | 위반 | 위반 | 위반 | 성립 | 위반 | 위반 | 위반 | 위반 |
| block | **위반** (freeze 전 keep) | 성립 | 성립 | 성립 | 성립 | 성립 | 성립 | 위반 |
| ownerNeutral | 성립 | 성립 | 위반 | 성립 | 위반 | 위반 | 성립 | 위반 |
| both | 성립 | 성립 | 성립 | 성립 | 성립 | 성립 | 성립 | 위반 |
| minimal | 성립 | 성립 | 성립 | 성립 | 성립 | 성립 | 성립 | 위반 |

## 5. 결함 후보 정리 (P 번호는 아직 없음, MoKa 결정 대기)

| 후보 | freeze 관련 | 모델 | 실제 코드 | minimal 패치로 |
|---|---|---|---|---|
| K1 (P-91) — freeze 중 또는 **freeze 전** keep_guard → 홀더 neutral이 LB | 예 | 위반 | 재현 (기존 K1, K1-pre) | 해결 (모델) |
| K2 (P-92) | 예 | 위반 | 재현 (기존 K2) | 해결 (모델) |
| K3 (P-92 참고, API 수준) | 예 | 위반 | 재현 (기존 K3) | 해결 (모델) |
| 스테일 sprint | 예 | 위반 | 재현 (직접 호출, Mover b) | 해결 (모델) |
| freeze 관련 LB 고아 (메뉴 창 / unfreeze 뒤) | 예 | 위반 | 재현 (a, d, c) | 해결 (모델, noguard) |
| S5f freeze 중 버려진 tap 예약 | 예 | 위반 | 재현 (Y) | 해결 (모델) |
| 평상시 LB 고아 (S6) | 아니오 | 위반 | (c와 같은 뿌리) | **남음** |
| 평상시 오래된 예약 (S5, Y tap/hold) | 아니오 | 위반 | 재현 (API 수준) | **남음** |

"해결 (모델)"은 이 모델과 범위 안에서 그 성질이 성립했다는 뜻이다. 패치 코드는 아직 없고 검사하지 않았다.

## 6. 제외한 가정

1. 스틱, `move`/`look`/`kick`, R1 `release_stick`(:460-461), `_note_stick`, `release_all`(F8 테스트로 따로 봄), `reconnect`/`close`, `force_guard` 속성 대입(guardkeep.stop).
2. 시간은 비결정 Tick으로 바꿨다. `due[B]` 숙성과 `bs` 노화를 서로 독립으로 둔 과대근사다. 위반 반례는 §1에서 실제 코드로 따로 확인했다.
3. 버튼 3개(LB, B, A). A는 "tap과 hold/press를 같이 쓰는 버튼"(실제로는 Y, 메뉴 A)을 대표한다.
4. Pad.epoch는 변수로 두지 않았다. nav.Mover의 다시 맞춤만 ghost(`sync*`)로 접었다. epoch를 보지 않는 다른 호출자(duel, reflex)는 모델에 없다.
5. quitout의 화면 대기·재시도와 Escape 스레드의 쿨다운.
6. Python GIL·메모리 모델. lock 밖 읽기는 :484 하나뿐이다.
7. tapper 스크립트(K3)는 현재 호출자가 없는 API 수준 시나리오다.
8. o·n 호출 상한 3/4, 스레드 4개 고정, 데드락·진행성 검사 없음(§0).

## 7. 다음 배치 최적화안 (제안만, 적용 안 함)

지금 방식은 성질 하나당 TLC 1회다. 같은 (variant, script, MaxOps, NGuard, NHold)의 상태 공간을 성질 수만큼 다시 탐색한다. 예: `ownerNeutral quit m3`의 316,881 상태를 7번. wall time의 약 2/3는 JVM 시작과 파싱이다.

1. **묶음 검사**: 같은 탐색 조건의 성질(+ 탐침이 아닌 것)을 cfg 하나에 `INVARIANT S1 S1b S3 S4 …`로 함께 넣고 1회 돌린다. 모두 성립하면 그 묶음은 끝난다.
2. **위반 성질만 분리 실행**: TLC는 첫 위반에서 멈추므로, 묶음에서 위반이 나오면 그 성질을 빼고 묶음을 다시 돌린다. 위반한 성질은 단독 cfg로 돌려 그 성질의 반례를 받는다. 위반 성질이 k개면 묶음 실행은 최대 k+1회다.
   - 대안: `-continue` 옵션으로 위반 뒤에도 계속 탐색하는 방법도 있다. 다만 반례 출력이 섞이므로 위 방식을 우선한다.
3. **탐침은 별도 묶음**: 기대값이 반대(위반 = 도달)라서 성질 묶음과 섞지 않는다. 같은 방식으로 "도달 불가"인 탐침만 단독으로 확인한다.
4. 예상 효과(추정, 측정 안 함): 이번 배치의 탐색 조건은 약 50개다. 성립 위주인 패치 변형은 조건당 1~2회로 줄고, current는 위반이 많아 이득이 작다. 실행 수는 200회에서 대략 100회 아래로 줄 것으로 본다. 판정 근거는 이번 결과와 같은 방식(성질별 판정, 성질별 반례)을 유지한다.
