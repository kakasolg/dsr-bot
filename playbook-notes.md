# 플레이북 후보 — 게임 지식 (2026-09-21, 웹 조사)

봇이 "죽고 → 복기 → 고친다" 로 스스로 찾기엔 너무 느린 것들은 사람이 넣어 준다. 여기는 그 후보 목록이다.
각 항목: 규칙 → 출처 → 봇에서의 상태 (**있음** / **넣음(오늘)** / **후보** / **텔레메트리 필요** / **못 함**).
봇은 공격을 안 한다 (이동·가드·점프·구르기·성배병·후퇴·휴식만). 공격이 전제인 조언은 뺐다.

## A. 자원 (HP · 성배병 · 스태미나)

| 규칙 | 출처 | 봇 |
|---|---|---|
| 성배병은 축복에서 쉬면 전부 찬다. 쉬면 적도 되살아난다 | [Push Square](https://www.pushsquare.com/guides/elden-ring-how-to-replenish-flasks), [GameRant](https://gamerant.com/elden-ring-how-refill-flasks/) | **넣음** — 1병 남으면 축복으로 가서 앉는다 (`REST_FLASKS_LEFT`) |
| 적 무리를 처치하면 성배병 1회분이 돌아온다 (전투 밖 보충) | [PlayStation](https://www.playstation.com/en-us/games/elden-ring/how-to-survive-your-first-few-hours-in-elden-ring/) | **못 함** — 공격 안 함. 시청자가 소환한 몹을 다른 몹이 죽여도 우리 킬이 아님 |
| 스태미나는 가드를 올리고 있으면 훨씬 느리게 찬다 → 공격 사이엔 가드를 내려라 | [Fextralife Guarding](https://eldenring.wiki.fextralife.com/Guarding), [GameRant guard counter](https://gamerant.com/elden-ring-how-to-guard-counter/) | **후보** — 지금 guardjump 는 적이 20 m 안이면 계속 LB. "적이 8 m 밖이면 가드 내리고 걷기/달리기" 로 바꾸면 스태미나가 돈다 (`guard_release_dist` 파라미터) |
| 가드 중 스태미나가 바닥나면 가드가 깨지고 잠깐 경직 + 치명타에 노출 | [Fextralife Guarding](https://eldenring.wiki.fextralife.com/Guarding) | **있음(약함)** — `stamina_walk_pct` 25% 아래면 걷기. **후보**: 가드 상태에선 임계를 더 높게 (40%) — 25% 는 한 방 막으면 깨진다 |
| 무기로 막는 것(양손)은 방패보다 피해 감소·가드 보강이 낮다 → 큰 공격은 막지 말고 굴러라 | [Fextralife Shields](https://eldenring.wiki.fextralife.com/Shields) | **텔레메트리 필요** — 적 공격 애니메이션 ID 로 "큰 공격" 을 알아야 함 (다음 단계 항목) |
| HP 가 낮을 때 후퇴하면서 마셔라; 적 옆에서 마시면 맞는다 | 공통 조언 | **넣음** — HP 50% 미만이면 마시되 적이 4 m 안이면 먼저 후퇴 (`FLASK_SAFE_DIST`) |

## B. 이동 · 회피

| 규칙 | 출처 | 봇 |
|---|---|---|
| 거리를 벌릴 땐 구르기보다 **달리기** — 무적은 없지만 빠르고 스태미나가 훨씬 덜 든다 | [Fextralife Dodging](https://eldenring.wiki.fextralife.com/Dodging) | **있음** — 후퇴·군집 시 sprint. **후보**: 피격 직후 구르기(지금)를 "적이 2 마리 이상이면 구르기 대신 달리기" 로 |
| 구르기 무적 13 프레임(30 fps 기준, 경장·중장), 중량 초과면 12 | [Fextralife Dodging](https://eldenring.wiki.fextralife.com/Dodging) | **있음** — 피격 후 0.8 s 쿨다운 구르기. 선제 구르기는 텔레메트리 필요 |
| 점프는 하반신만 무적 — 옆으로 쓸거나 땅에서 솟는 공격에만 통하고, 내려찍기·잡기엔 안 통한다 | [Fextralife Dodging](https://eldenring.wiki.fextralife.com/Dodging) | **있음(맹목)** — guardjump 가 1.2 s 마다 점프. **후보**: 개·쥐·늑대(낮은 공격)엔 점프 유지, 병사·새(위에서)엔 점프 끄고 가드만 |
| 적에게서 등을 보이며 구르면 추격기에 맞는다 → 적 쪽으로 굴러라 | [Fextralife Dodging](https://eldenring.wiki.fextralife.com/Dodging) | **후보** — 지금은 진행 방향 유지 구르기. 가장 가까운 적 방향으로 스틱을 돌려 구르기 |
| 적은 꽤 멀리까지 쫓아온다 — 도망은 "원하는 지형까지 끌고 가기" 용도지 떼어내기 용도가 아니다 | [ER Reforged Combat](https://err.fandom.com/wiki/Combat_Mechanics), [GameRant](https://gamerant.com/elden-ring-leyndell-knight-dragon-chase-funny-video-clip/) | **실측 일치** — R0 "도망쳤는데도 죽음 → 회피 철회" 가 두 팔 모두에서 효과. 특히 새·박쥐는 도망이 무의미 (`avoid_types` 에 날개 달린 적을 넣지 않기) |
| 안 싸워도 된다 — 지나쳐 달리기 | [WeGotThisCovered](https://wegotthiscovered.com/gaming/how-to-stop-certain-enemies-from-attacking-you-in-elden-ring/) | **있음** — `sprint_segments`, `crowd_threshold` |

## C. 적 종류별

| 적 | 규칙 | 출처 | 봇 |
|---|---|---|---|
| 개 (Dog) | 혼자면 위험, 무리면 치명적. 끝까지 쫓아온다. 방패(가드)가 잘 먹는다 — 달려드는 공격을 막으면 튕긴다 | [Fextralife Dog](https://eldenring.wiki.fextralife.com/Dog) | **실측 일치** — 회피 철회(v9)가 맞았다. **후보**: 개는 `guardjump` 대신 `guard`(점프 없이 가드 유지) — 점프 중엔 가드가 풀린다 |
| 늑대 (Wolf) | 개와 같은 추격형, 무리 | [Fextralife Dog](https://eldenring.wiki.fextralife.com/Dog) | 개와 동일 취급 |
| 쥐 (Rat) | 낮은 공격, 무리. 위협은 낮지만 발을 묶는다 | 공통 | **후보**: 쥐만 있으면 sprint 로 무시하고 통과 (`ignore_types`) |
| 짐승 전반 (개·곰·쥐) | **짐승 퇴치 횃불**을 들면 덤비지 않는다. 새·큰곰은 예외 | [GamesRadar](https://www.gamesradar.com/it-turns-out-the-beast-repellent-torch-in-elden-ring-also-works-on-dogs/) | **후보(장비)** — 왼손에 횃불을 들면 가드는 못 하지만 개·쥐·늑대가 안 온다. 케일리드 고립 상인 1,200 룬. "하위 티어 = 잔챙이 떼" 설계와 맞물림 — 시청자 소환 잔챙이 대부분이 짐승 |
| 전투매 (Warhawk) · 큰박쥐 | 날아서 쫓아온다, 도망 불가. 위에서 내려오므로 점프 무적이 안 통한다 | [Fextralife Dodging](https://eldenring.wiki.fextralife.com/Dodging) 의 점프 설명 + 실측 | **실측 일치** — 회피 철회. **후보**: 날개 달린 적엔 점프 끄고 가드 유지 |
| 날아다니는 적 | 뼈 단검(투척)으로 놀라게 해서 끌어내릴 수 있다 | [WeGotThisCovered](https://wegotthiscovered.com/gaming/how-to-stop-certain-enemies-from-attacking-you-in-elden-ring/) | **못 함** — 공격 안 함 |

## D. 상태 · 절차 (오늘 넣은 것)

| 규칙 | 봇 |
|---|---|
| 왼손이 비면 **양손 잡기** 상태에서만 LB 가 가드 — 한손이면 주먹 | **넣음** — `ensure_two_hand`, ArmStyle 감시 |
| 길 위에 서 있지 않는다. 쉬는 건 축복에서 | **넣음** — 멈춤 감시 → 흔들기 → `stall` 종료, 후퇴 중 정지 제거, 런 종료 시 축복 복귀 |
| 성배병 1병이면 무조건 축복 | **넣음** — `rest_at_grace` (앉기 판정 반경 < 0.7 m, 정확한 지점 실측) |

## 우선순위 제안 (복기가 스스로 못 찾는 것부터)
1. **가드 내리기 규칙** (A-3): 적이 멀면 LB 를 놓아 스태미나를 돌린다 — 지금은 20 m 안에 적이 있는 내내 가드라 스태미나가 안 찬다. 파라미터 `guard_release_dist` (6~15 m) 로 학습 가능.
2. **적 종류별 이동 모드** (C): 짐승(개·늑대·쥐) = 가드 유지·점프 끄기, 날개(매·박쥐) = 가드 유지·점프 끄기, 병사 = guardjump. `mode_by_type` 딕셔너리 — 후보는 규칙 R6 "이 적에게 죽었으면 그 타입의 모드를 바꿔 본다".
3. **짐승 퇴치 횃불** (C-4): 장비 한 번 바꾸면 잔챙이 떼 문제의 절반이 사라진다. 가드를 잃는 대가 — A/B 로 재면 된다 (`--arm torch`).
4. **선제 구르기** (B-2, A-5): 적 애니메이션 ID 학습 — 텔레메트리에 `anim` 은 이미 있다. 사망 30 s 전 기록에서 "피격 직전 적 anim" 을 세면 공격 예고 ID 표가 나온다.
