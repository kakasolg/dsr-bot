# 일관성 조사 — 문제를 조건으로 막을 것인가, 원칙으로 풀 것인가 (2026-10-11, [win])

## 0. 질문 (MoKa 10-11)

- "봇이 캐릭터를 조정할 때 우선순위가 없으면 결국 조건에 따라 진행하고, 앞으로 문제가 생기면 원인을 못 찾는다."
- "궁극적으로 다크소울이 문제가 아니라, 봇이 뭔가를 조작하고 문제를 해결할 때 **일관성**이 있냐는 것. 일관성 때문에 실패하더라도
  일관성이 있으면 문제 해결이 쉬운데, 당장의 문제를 **특정 조건**을 주어서 해결하면, 그 조건이 사라지면 그다음부터 문제 해결이 어려워진다."
- "이건 인간의 인지적 평가이고, 로봇 공학이나 자율 주행은 다른 해법이 있을 수 있으니 더 좋은 방법을 찾자."
- 같은 날: "공격 대상과 캐릭터 정렬, 카메라 방향 일치도 우선순위가 높은 작업."

이 문서는 **조사와 제안**이다 — 정해진 것만 ROADMAP으로 옮긴다. 1절 지금 봇(코드 `451630c`), 2절 바깥 사례, 3절 제안, 4절 물을 것.

---

## 1. 지금 봇 — 조건이 얼마나 쌓였나, 누가 패드를 쥐나

**조건으로 막은 흔적 (세어 본 것)**
- 코드 안 문제 번호 표시: `P-n` 80곳, 서로 다른 문제 25개 — 문제 하나를 고칠 때마다 그 자리에 조건을 덧붙인 흔적.
- 숫자 문턱값(모듈 상수): duel 83 · field 71 · nav 26 · missions 22 · moves 14 · pull 13 · escape 12 · reflex 7 = **248개**.
- 켜고 끄는 스위치(`X = True/False`): duel 5 · field 5 · nav 2. 거기에 `run.py` 옵션(`--ground`·`--pull`·`--footing`…).
- 구역별 처리: `missions.py`에 구역 번호 분기 11곳 (구역 8 사다리, 구역 1 휴식 …).
- 좋은 점: 적 ID 숫자를 코드에 직접 박은 비교는 0 — 적 반응은 `foes.py` 데이터로 빠져 있음.

**누가 패드를 쥐나**
- 진짜 우선순위 장치는 하나(`Pad.freeze`, 비상 탈출). 나머지는 **호출 순서**(missions → field → duel → moves)와 `duel.RULES`의 줄 순서(28개, 첫 일치).
- 카메라는 따로 도는 스레드(`CamFollow`)가 플래그(`cam_busy`·`escaping`·락온)를 보고 비킴.
- 틈: ① 카메라 목표는 싸움·끌기 동안만 정해짐 — 물러나기·사선 밖으로·몸으로 끌기·걷기에선 주인 없음 (P-65)
  ② 싸움 안에서 목표를 바꿔도(`원거리부터`, 끼어든 적: `duel.py:682/745`) 카메라 목표는 그대로 → 몸은 새 목표, 카메라는 옛 목표
  ③ 몸 허용 각 30/35/45°(`QUIET_FACE_DEG`·`FACE_FIRST_DEG`·`AFTER_SWING_DEG`) 대 카메라 10°(`DEADBAND`) — 따로 놂
  ④ 반사(`rule_reflex`)는 RULES 13번째, 몇몇 걷기(`retreat`·`fall_back`·`notice_pull`·`_sprint` …)엔 반사가 안 돎
  ⑤ 기록은 **이긴 규칙만** (`dec.rule`) — 같은 틱에 걸리고 싶었다가 순서에 밀린 규칙, 카메라와 몸이 다른 대상을 본 순간은 안 남음.

→ MoKa의 평가와 맞다: 한 층 안(싸움 규칙)은 순서가 있지만, 문제를 고칠 때마다 **조건을 그 자리에 덧붙여 왔고**,
층 사이·입력 장치 사이엔 정해진 원칙이 없어 "왜 그랬나"를 되짚기 어렵다.

---

## 2. 바깥에서는 어떻게 푸나

### 2-A. "특수 조건이 쌓이는 문제" — 자율 주행·로봇·ML 시스템

- **규칙 폭증과 긴 꼬리(long tail)**: 손으로 쓴 규칙 계획기는 흔한 상황에선 잘하지만 드문 상황에선 무너짐 — 규칙 기반·학습 기반 둘 다
  드문 상황 벤치마크를 안전하게 못 넘김 ([interPlan, Hallgarten 2024](https://arxiv.org/html/2404.07569v2)).
  Tesla는 FSD v12에서 상황별로 "무엇을 하라"를 적은 C++ 코드 30만 줄 이상을 신경망 하나로 바꿨다고 밝힘
  ([release notes 보도](https://www.notateslaapp.com/news/1842/first-look-at-teslas-fsd-beta-v12-1-video), 회사 발표 수치).
- **얽힘(CACE: Changing Anything Changes Everything)**: Google의 ML 시스템 기술 부채 논문 — 서로 얽힌 부분은 하나를 바꾸면 전부가 바뀜,
  임시방편 연결 코드·죽은 실험 경로가 유지 비용이 됨 ([Sculley 2015, NeurIPS](https://proceedings.neurips.cc/paper/2015/file/86df7dcfd896fcaf2674f757a2463eba-Paper.pdf)).
  → 우리 248개 문턱값·25개 문제 고침이 서로 얽힌 상태와 같은 모양.
- **Rulebooks (nuTonomy/Aptiv·Motional, Censi 2019)**: 조건을 덧붙이는 대신 **규칙 전부를 "위반 정도를 재는 척도"로 만들고 우선순위로 줄 세움**.
  후보 행동마다 각 규칙을 얼마나 어기는지 재서, 위 규칙부터 덜 어기는 것을 고름. 행동을 바꾸려면 **규칙의 순서·척도를 고치고**,
  어떤 고침이 앞서 정한 제약을 깨지 않는지도 따짐 → "왜 이걸 골랐나" = "어느 규칙을 덜 어겨서"로 늘 같은 방식의 답
  ([논문](https://arxiv.org/pdf/1902.09355.pdf), [Motional](https://motional.com/news/liability-ethics-and-culture-aware-behavior-specification-using-rulebooks)).
  한계: 상황마다 다른 rulebook을 고르는 법은 원 논문에 없음 — 후속 연구가 "상황 인식 rulebook"을 냄 ([2409.06607](https://arxiv.org/pdf/2409.06607)).
- **RSS (Mobileye, 2017)**: 상황별 고침 대신 **모든 상황에 같은 몇 개의 일반 규칙**(안전 거리, 끼어들기, 우선권…)을 수식으로 — 화이트박스·검증 가능,
  구현 방식과 무관하게 정의 ([논문](https://arxiv.org/pdf/1708.06374v6), [Mobileye](https://www.mobileye.com/responsibility-sensitive-safety/)).
- **Simplex 구조 (런타임 안전 보장)**: 잘하지만 보장 못 하는 "주 제어기" + 작고 검증된 "안전 제어기" + 바꿔 주는 "결정 모듈" 셋으로 나눔.
  주 제어기가 곧 위험한 걸 하려 하면 안전 쪽으로, 안전해지면 되돌림 → 고침이 주 제어기 안의 조건으로 흩어지지 않고 경계가 한 곳
  ([Simplex 경로 추종](https://arxiv.org/pdf/2503.10559), [Black-Box Simplex](https://www3.cs.stonybrook.edu/%7Estoller/papers/rv2022.pdf)).
- **SOTIF (ISO 21448)**: 실패를 "알려진/모르는 × 안전/위험" 네 칸으로 나누고, **모르던 위험을 알려진 시나리오로 옮겨** 시나리오 모음에 쌓고 반복 검증.
  위험을 일으키는 **촉발 조건**을 명시적으로 기록 ([Ansys 요약](https://www.ansys.com/simulation-topics/what-is-sotif), [NHTSA ESV 논문](https://www-esv.nhtsa.dot.gov/Proceedings/26/26ESV-000258.pdf)).
  → 우리 `duel_expect_test`·`golden`·`scene_replay`가 이 방향의 시작.

### 2-B. "여러 행동이 같은 입력 장치를 원할 때" — 중재

- **고르기(arbitration) vs 섞기(fusion)**: 하나를 고르거나(승자 독식·우선순위) 가중 합으로 섞음 ([Brown cs148](https://cs.brown.edu/courses/cs148/lectures/cs148_4_decisionarchitectures.pdf), [Pirjanian 1999](https://robotics.usc.edu/publications/319), [DAMN](https://u.cs.biu.ac.il/~galk/teach/current/intsys/readings/DAMN_AAAI.pdf)).
- **포섭 구조(Brooks)**의 알려진 약점 = 우리 지금 모양: 위층이 아래층을 눌러 덮어쓰는 지점이 흩어져, **층이 늘수록 "왜 그랬나"를 여러 층에 걸쳐 추적**해야 함
  ([Wikipedia](https://en.wikipedia.org/wiki/Subsumption_architecture)).
- **행동 트리**: 우선순위 선택(첫 성공이 이김)을 트리 하나에 — 포섭 구조·결정 트리를 일반화, Halo 2 AI의 핵심 ([Colledanchise & Ögren](https://arxiv.org/pdf/1709.00084), [Halo 강의](https://web.cs.wpi.edu/~rich/courses/imgd4000-d10/lectures/halo3.pdf)).
  엔진 디버거가 도는 가지를 보여 주고, CryEngine은 **틱마다 실행 경로를 로그로** 남김 ([Unreal](https://dev.epicgames.com/documentation/en-us/unreal-engine/ai-debugging-in-unreal-engine), [CryEngine](https://cryengine.com/docs/static/engines/cryengine-5/categories/23756813/pages/23310620)).
- **입력 장치마다 주인 하나**: ros2_control은 명령 인터페이스를 한 컨트롤러만 차지(둘째는 "Resource conflict" 거절) ([#343](https://github.com/ros-controls/ros2_control/issues/343));
  동시 행동 트리는 행동마다 쓰는 자원을 선언하고 충돌을 우선순위로 ([2110.11813](https://arxiv.org/pdf/2110.11813)); twist_mux는 우선순위 + 입력마다 timeout + 잠금 ([twist_mux](https://mirror.umd.edu/roswiki/twist_mux.html)).
- **시선은 우선순위 있는 별도 채널**: Unreal AI focus — 길 따라가기는 낮은 우선순위(Move), 게임 로직의 적은 높은 우선순위(Gameplay)
  ([포럼 예](https://answers.unrealengine.com/questions/384761/index.html), [Epic](https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/AIModule/AAIController)).
- **소울 게임 학습 환경**: SoulsGym(DS3) 항상 락온, DSLE(DSR 보스 22종, 2026-08) 락온을 환경이 일정 간격 자동 — "카메라 유지는 낮은 층의 관리 일", 행동에 카메라 없음
  ([SoulsGym](https://soulsgym.readthedocs.io/en/dev/envs/soulsenv.html), [DSLE](https://arxiv.org/html/2608.09902v1)). 둘 다 1:1 보스전이라 그대로는 못 씀.
- **Arbitration graph (KIT)**: 행동마다 "명령 / 쓸 수 있나 / 계속해도 되나"를 스스로 밝히고, 중재자가 우선순위·비용으로 정렬, **검증기 통과한 첫 것**,
  다 실패하면 단계적 대체 ([2411.10170](https://arxiv.org/html/2411.10170v3)). 효용 AI 관행: **이긴 것만이 아니라 후보 전부와 점수·이유를 기록** ([IAUS](https://github.com/ProjectBorealis/IAUS/wiki)).

---

## 3. 제안 (결정 아님)

바깥 사례의 공통점: **(1) 결정하는 방식은 하나, 모든 상황에 같게 (2) 고칠 땐 조건을 덧붙이지 않고 원칙(순서·척도)을 고침
(3) 고른 이유와 진 쪽까지 늘 같은 형식으로 기록 (4) 실패는 시나리오로 모아 반복 검증.**

**원칙 1 — 결정 방식 하나: 후보 → 척도 → 순서**
- 매 틱 같은 절차: 할 수 있는 행동 후보를 모으고 → 몇 개의 **일반 척도**(맞을 위험, 떨어질 위험, 정렬 오차, 준 피해 기대, 스태미나…)로 재고 →
  **우선순위 표 하나**(rulebook처럼)로 고름. 걷기·싸움·물러나기·끌기가 다 같은 절차를 탐.
- 새 문제는 "이 상황이면 X" 분기 대신 **척도나 순서를 고침**. 어쩔 수 없이 조건을 넣으면 4번 장부에 올림.

**원칙 2 — 입력 장치마다 주인 하나, 시선은 하나의 focus에서**
- 채널: 이동(왼스틱) · 시선(오른스틱·락온) · 행동(공격·가드·구르기·에스트) · 비상(freeze). 틱마다 채널별 주인을 정하고 기록.
- 몸 방향과 카메라는 같은 `focus`(대상 하나 + 정한 주인)를 봄. 목표가 바뀌면 focus가 바뀜 → 1절 틈 ①② 해결. 허용 각은 표 하나.

**원칙 3 — 안전은 작은 별도 층 (Simplex)**
- 떨어짐·비상 탈출·반사(막기) 같은 "절대 지킬 것"은 작은 안전 층 하나에 모으고, 주 결정이 그걸 어기려 할 때만 넘겨받음.
  지금 흩어진 발밑 확인(`rule_edge`·`rule_footing`·`ground_ahead`·`safe_back`, P-63)과 반사가 이 층 후보.

**원칙 4 — 기록과 조건 장부**
- 매 틱: 후보 · 척도 값 · 이긴 것 · **밀린 것과 이유** · 채널 주인 · focus. 고리 버퍼에 두고 피격·낙하·멈칫 때 앞 몇 초를 덤프.
- 조건 장부: 특정 조건(구역·적·좌표·스위치)마다 이유가 된 문제(P-n), 시나리오 테스트, **다시 볼 날**을 적음 — 조건이 사라지거나 바뀌면 장부에서 찾음.
  지금 `P-n` 표시 80곳·스위치 12개·구역 분기 11곳이 첫 장부감.

**원칙 5 — 실패는 시나리오로 (SOTIF)**
- 새 실패는 먼저 "알려진 시나리오"로 `tests/expect`·`scene_replay`에 넣고, 고친 뒤 **전체 시나리오**로 다시 돌림 — 이미 하는 일을 규칙으로.

**단계 (v1.0 / v2.0에 맞춤)**
- **v1.0 (지금 구조, 재는 것부터)**: ① 정렬 지표를 싸움 밖까지 (몸·카메라·focus 각, 채널 주인) ② `dec.rule`에 밀린 규칙(`also`) ③ 조건 장부 초안
  ④ 시선 채널만 먼저 focus로 (`cam_target`을 바뀐 목표·물러나기·끌기에도, P-65).
- **v2.0 (한 틱 루프)**: 원칙 1~3을 틱 루프의 중심으로 — 리뷰 문서 2절 ①의 "읽기 → 상태 → 행동 하나 → 입력"에 후보·척도·순서·채널을 넣음.
  248개 문턱값은 척도의 매개변수로 모으고(설정 객체), 조건 장부로 정리.

---

## 4. MoKa에게 물을 것

1. 방향: "결정 방식 하나(후보 → 척도 → 순서) + 안전 층 + 조건 장부"로 가는 게 MoKa가 말한 일관성과 맞나
2. 우선순위의 맨 위 몇 개 (예: 떨어지지 않기 > 맞지 않기 > 정렬 > 피해 주기 > 빠르기)
3. 싸움 중 락온 기본을 시험해 볼지 (소울 학습 환경 두 곳의 방식, 뒤잡기·여러 적·물러나기 때는 풂)
4. v1.0에서 ①~④부터 할지, 아니면 v2.0 한 틱 루프로 바로 갈지
