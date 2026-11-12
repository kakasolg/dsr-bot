# HP · 기력(SP) · 에스트 판단 위치 목록 (read-only inventory, 2026-11-12)

(cloud 11-12: [cloud]가 §8-b-1을 직접 확인 — `duel._low_hp_line`은 `low_hp <= 0`이면 0을 그대로 돌려줌 (duel.py:521). 이 목록의 결론이 맞음. 본문: `docs/hp-stamina-2026-11-12.md`.)

Repo `dsr-bot` @ `039092c`. 코드는 하나도 안 바꿈. 값은 코드에서 그대로 복사. "출처" 열은 **코드 주석이 말하는 것만** 적음:
`[meas]` = 주석에 런 id·측정이 적힘 · `[MoKa]` = MoKa 인용/ledger id · `[wiki]` · `출처 없음` = 주석에 근거 없음.
이 목록은 정적 읽기만 거쳤고 (파서·런타임 검증 없음), 어느 줄이 실제 런에서 몇 번 발동했는지는 보지 않았다.

`souls/duel.py` RULES 순서 (위에서 아래, 처음 맞는 규칙이 이 틱을 가짐; 번호 = 위치):
1 shot · 2 separate · 3 wall_bounce · 4 finish_first · 5 prep_reflex · 6 guard_counter · 7 footing · 8 swing_backstep · 9 jump_drill ·
10 jump_dodge · 11 jump_save · 12 after_swing · 13 face_first · 14 early_kick · 15 late_windup_block · 16 prep_linger · 17 hit_first ·
18 backstab_swing · 19 reflex · 20 lure · 21 edge · **22 estus** · 23 stagger_punish · 24 evade · 25 block · 26 downed · 27 prep_backstab_chance ·
28 wait_far · 29 approach · 30 finish · **31 stamina** · 32 prep_face · 33 backstab · 34 attack.
RULES 앞에서 매 틱 `_sense` (duel.py:822)가 끝 조건 (low_hp · losing · crowd …)을 먼저 본다 — 여기서 끝나면 RULES는 안 돈다.

---

## 1. souls/duel.py (층 3, 한 놈과 싸움)

| file:line | 함수 / 규칙 (RULES 위치) | 판단 | 조건 | 상수 = 값 | 출처 (주석) |
|---|---|---|---|---|---|
| duel.py:876 | `_sense` 끝 조건 (RULES 전) | 싸움 끝 `low_hp` → Field.recover (물러남·에스트) | `p.hp < max_hp × _low_hp_line(s, F.low_hp)` **단** 그놈 HP ≤ FINISH_KEEP_HP이고 내 HP ≥ 12 % 이면 안 끝냄 | `low_hp` = Field가 넘김: `RETREAT_HP` 0.5 (desperate면 0.0) · `FINISH_KEEP_HP = 40` · 하드코딩 `0.12` | FINISH_KEEP_HP: "after dark sign the shield soldier went 10 → 85" [meas, 런 id 없음]; 0.12: 주석 "(down to 12 %)" 근거 없음 |
| duel.py:518–527 | `_low_hp_line` | 둘러싸이면 후퇴선 올림 | 같은 높이 CROWD_R 안 살아 있는 적 ≥ 2 → `max(low_hp, CROWD_LOW_HP)` | `CROWD_R = 4.0` · `CROWD_LOW_HP = 0.45` | "two shield soldiers took 262 → 22 → dead in one exchange (P-8)" [meas] |
| duel.py:881–883 | `_sense` | 싸움 끝 `losing` → recover | low_hp > 0 · 이 싸움에서 잃은 HP ≥ max_hp × LOSING_TAKEN · 준 피해 < 그놈 max_hp × LOSING_DEALT · 그놈 HP > FINISH_KEEP_HP | `LOSING_TAKEN = 0.35` · `LOSING_DEALT = 0.5` | [MoKa] 2026-10-01 "전술적인 문제와 후퇴를 더 많이 할 필요"; 09-30a~10-01b 집계 (4779/9824, low_hp 7번 2347) [meas] |
| duel.py:1133–1166 | `rule_shot` (1) | 싸움 끝 `shot` → Field가 사선 밖으로 | 한 틱 사이 HP 감소 ≥ SHOT_HP, SHOT_NEAR_R 안 근접 휘두름 없음, SHOT_FAR_R 밖 투척병 있음 (SHOT_HOLD_R 안 붙은 근접 적이 있으면 첫 번은 버팀) | `SHOT_HP = 40` · `SHOT_NEAR_R = 6.0` · `SHOT_NEAR_S = 1.5` · `SHOT_FAR_R = 5.0` · `SHOT_HOLD_R = 2.5` · `SHOT_AGAIN_S = 10.0` | 10-11 영상 리뷰 10-03e 52–58 s −113×2 [meas]; SHOT_HP 값 자체는 출처 없음 |
| duel.py:1242–1251 | `rule_finish_first` (4) | 약공 1번 (반사보다 먼저) | 그놈 HP ≤ FINISH_HP · 안 휘두름 · 닿는 거리 · 내 SP ≥ FINISH_SP | `FINISH_HP, FINISH_SP = 25, 15` | "measured 34–41" (약공 한 대) [meas]; FINISH_SP 15 출처 없음 |
| duel.py:1283 → reflex.py:236 | `prep_reflex` (5) / `rule_reflex` (19) → `Reflex.tick` | 막기 vs 막지 않고 마주보기 | SP < GUARD_SP → 방패 안 듦 (`step_away`) | `reflex.GUARD_SP = 25` | "blocked at SP 12~22, guard broke, pushed off, fatal fall, 2026-09-24" [meas] |
| duel.py:1826 → reflex.py:152–193 | `rule_guard_counter` (6) → `Reflex.guard_counter` | 방패에 맞은 틱에 약공 1번 | 내 애니 …140 · 닿는 거리 안 휘두르는/휘청 놈 · SP ≥ GUARD_COUNTER_SP | `GUARD_COUNTER_SP = 1` · `GUARD_COUNTER_STEP = 0.3` | [MoKa] 11-08 "첫 번째 방패 부딪혔을때 반응해서 약공 들어갔으면 되는데" (M1108-02), "방패, 약공은 모든 공격에세 기본으로" (M1108-01); 225520 구역 4 SP 29·32·45 < 55 [meas]; "친 뒤 막을 기력이 모자라는 위험은 MoKa가 받아들임" |
| duel.py:1617–1680 | `rule_swing_backstep` (8) — COMBO_ONLY만 | 백스텝 콤보 안 함 | SP < SWING_BS_SP | `SWING_BS_SP = 50` | "142619: 기력 27–45에서 누름" [meas] |
| duel.py:1494–1530 | `rule_jump_drill` (9) — jump_r2 계획만 | 점프 공격 안 함 | SP < JUMP_SP | `JUMP_SP = 65` | "224853: 303600 점프 한 번에 기력 48 → −17 (≈65, 배틀 액스)" [meas] |
| duel.py:1564–1592 | `rule_jump_dodge` (10) — jump_r2 계획만 | 백스텝 안 함 | SP < JUMP_DODGE_SP | `JUMP_DODGE_SP = JUMP_SP + 20` (= 85) | "224853: 기력 43에 백스텝 → 헛친 틈 2.6 m에 기력 21이라 점프 못 함" [meas] |
| duel.py:1595–1614 | `rule_jump_save` (11) — jump_r2 계획만 | **방패 내리고 마주보고 기력 모음** (다른 공격 안 함) | SP < JUMP_DODGE_SP (85) · 그놈 안 휘두름 · (드릴 밖이면) JUMP_SAVE_CROWD_R 안 다른 놈 없음 | `JUMP_DODGE_SP` 85 · `JUMP_SAVE_CROWD_R = 6.0` | [MoKa] 11-03 "기력 아껴 봐" (M1103-13), 224853 #5 백스텝 ≈20 · 막기 ≈20 · 점프 ≈65 [meas] |
| duel.py:1703–1825 (sp 1764) | `rule_after_swing` (12) | 그놈 휘두름 끝 → 바로 약공/발차기 | … SP ≥ `weapon.sp_min` (아니면 why="sp", 안 침) | `weapon.sp_min` (§9) · `AFTER_SWING_S = 0.6` | [MoKa] 10-06 "끝나면 무조건 공격" — sp 조건은 출처 없음 |
| duel.py:430–435, 1847 | `rule_early_kick` (14) / `_early_kick_candidate` | 빠른 발차기 후보 (지금 'shadow'=기록만) | SP ≥ `weapon.sp_min` | `weapon.sp_min` | 출처 없음 |
| duel.py:1901–1925 | `rule_hit_first` (17) | 먼저 약공 (방패병 제외) | 닿는 거리 · SP ≥ `weapon.sp_min` · 그놈 서 있음 또는 INTERRUPT_S 안 시작 · 옆 휘두름 없음 | `weapon.sp_min` · `INTERRUPT_S = 0.35` | 사용자 인용 "if you'd swung even once…"; sp 조건 출처 없음 |
| duel.py:1960–1964 | `_sleeper_heavy` (hit_first 안) | 자는 적 첫 타 강공 | 그놈 HP ≤ SLEEPER_HEAVY_HP · 내 SP ≥ SLEEPER_HEAVY_SP | `SLEEPER_HEAVY_HP = 75` · `SLEEPER_HEAVY_SP = 60` | [MoKa] 10-03 P-39, 배틀 액스 강공 69/75/85 [meas]; "heavy costs 50 (+20 on a ground hit)" [meas, weapons.py] |
| duel.py:1936–1944 | `_third` (2연타 뒤) | 3타째 약공 | 그놈 HP ≤ FINISH_HP · 닿는 거리 · 내 SP > 0 | `FINISH_HP` 25 · `THIRD_REACH_SLACK = 0.0` | 10-03a/e [meas] |
| **duel.py:2048–2064** | **`rule_estus` (22)** | **싸우는 중 에스트** (Care.take) / 가까우면 백스텝 | `care.wants(s)` (= 에스트 > 0 · HP < max_hp × FIGHT_HEAL 0.6, field.py:2820) · 마지막 시도 뒤 CARE_RETRY · `opening()`: 그놈 쓰러짐 또는 (안 휘두름 · OPEN_R 이상) **그리고** `_others_quiet` (다른 놈 OTHERS_R 밖, OTHERS_ATTACK_R 안 휘두름 없음). 열림 아님 + 그놈 안 휘두름 + h < OPEN_R + 뒤 바닥 2.2 m → 백스텝 (2 s 간격) | `OPEN_R = 3.0` · `OTHERS_R, OTHERS_ATTACK_R = 5.0, 8.0` · `CARE_RETRY = 3.0` · `field.FIGHT_HEAL = 0.6` | 독스트링 "user: drink if safe" (M0000-05, en_record); OPEN_R·OTHERS_R·CARE_RETRY 값 출처 없음 |
| duel.py:2082–2108 | `rule_stagger_punish` (23) | 휘청에 약공 콤보 / 방패병엔 강공 | SP ≥ `weapon.sp_min`; 강공은 SP ≥ HEAVY_SP · heavy_punish 무기 · 락온 | `HEAVY_SP = 100` · `weapon.sp_min` | 사용자 2026-09-25 "guard·heavy·guard", "one heavy while guarding costs 90" [meas] |
| duel.py:2112–2133 | `rule_evade` (24) — backstep 스타일 | 헛친 뒤 들어가 약공 | SP ≥ `weapon.sp_min` | `weapon.sp_min` | 출처 없음 |
| duel.py:2136–2162 | `rule_block` (25) | 방패 듦 | 그놈 휘두름 · h < NEAR · shield 스타일 — **SP 조건 없음** | `NEAR = 4.0` | 2026-09-25 rush "8 s+ 0 attacks, 676 taken" [meas] |
| duel.py:2198–2217 | `rule_wait_far` (28) | 기다리기 끝 → `low_hp` (→ recover) | 기다리는 동안 잃은 HP > WAIT_HURT_HP (절대값) | `WAIT_HURT_HP = 120.0` | "490→242 waiting 11 s, user 2026-09-25" [meas] |
| duel.py:2279 | `_entry_try` (rule_wait_far/approach 안, COMBO_ONLY만) | 진입 콤보 | SP ≥ `weapon.sp_min` | `weapon.sp_min` | 출처 없음 |
| duel.py:2328–2337 | `rule_finish` (30) | 한 대에 죽으면 약공 1번 | 그놈 HP ≤ FINISH_HP · SP ≥ FINISH_SP | `FINISH_HP, FINISH_SP = 25, 15` | "guard broke while a shield soldier held out 4 s at HP 10" [meas] |
| **duel.py:2340–2348** | **`rule_stamina` (31)** | **방패 내리고 마주보기 (기력 회복)** | SP < `weapon.sp_min` | `weapon.sp_min` | 독스트링 "recovery −80 %, wiki" [wiki] |
| duel.py:2440–2454 | `_slam` (rule_attack 34 안) | 벽 강공 | SP ≥ WALL_HEAVY_SP · `_heavy_ok` (HEAVY_CLEAR_R 안 다른 놈 없음, 양손이거나 1:1 방패병) | `WALL_HEAVY_SP = 60` · `HEAVY_CLEAR_R = 3.5` · `ALONE_R = 6.0` | "Battle Axe heavy −50, −20 more if it hits the ground" [meas]; [MoKa] 10-01 "3.5 m 안에 적이 있으면 양잡은 좋지 않음. 1:1 확실한 상황에서 양잡" |
| duel.py:2466–2483 | `_shield_combo` | 양손 전환 → 강공 → 약공 | `_slam` 조건 (WALL_HEAVY_SP) 안에서만 | 위와 같음 | [MoKa] 2026-09-30 |
| duel.py:2767–2790 | `rule_attack` (34) | 기본 공격 (발차기 / 강공 / 약공 n=combo) | 자체 SP 조건 없음 — rule_stamina (31)가 SP < sp_min을 먼저 막음. 2타째는 `sp_second = weapon.sp_min` | `weapon.sp_min` | — |
| duel.py:2669–2672 | `_drill_setup` 등 (드릴만) | 드릴 중단 | 이 싸움에서 잃은 HP > max_hp × DRILL_HURT | `DRILL_HURT = 0.3` | 출처 없음 |

## 2. souls/field.py (층 4, 걷기·싸움 사이·회복)

| file:line | 함수 | 판단 | 조건 | 상수 = 값 | 출처 (주석) |
|---|---|---|---|---|---|
| field.py:468–478 | `Field.safe` | 에스트 마셔도 되나 (걷기·싸움 사이) | 깨어 있는 적 SAFE_R 안 없음 · SAFE_ATTACK_R 안 휘두름 없음 · RANGED_R 안 깨어 움직이는 투척병 없음 | `SAFE_R = 6.0` · `SAFE_ATTACK_R = 8.0` · `RANGED_R = 25.0` | "a firebomb hollow on the ledge above hit us mid-drink … died (2026-09-24)" [meas]; SAFE_R 6은 출처 없음 (M1109-71 held: 6 m 모자람 기록, 안 바꿈) |
| field.py:480–498 | `Field.desperate` | safe가 아니어도 마심 | HP < max_hp × DESPERATE_HP · 투척병 DESPERATE_R 밖 · 근접 적 LAST_SIP_R 밖 · SAFE_R 안 휘두르는 근접 적 없음 | `DESPERATE_HP = 0.3` · `DESPERATE_R = 4.0` · `LAST_SIP_R = 3.5` | [MoKa] 11-01 "가)+나) 고치기" (M1101-08, 214607 석궁 HP 116) · [MoKa] 11-08 "30% 이하이면 에스트 마시고 뭔가 해야 하는데 않했음" (M1108-07, P-139, 221120 HP 79 · 3.8 m). "3.8 m에서 한 모금이 닿기 전에 끝나는지는 게임에서 안 잼" |
| field.py:501–520 | `Field.heal(frac=0.7, sips=3)` | 에스트 최대 sips모금, HP ≥ frac 되면 멈춤 | 매 모금 `safe` 아니면 `desperate` 볼 것 (둘 다 아니면 안 마심), 에스트 > 0 | 인자 frac/sips (부르는 곳마다 다름 ↓) | — |
| field.py:208, 2820–2821 | `Care.wants` (duel care) | 싸움 중 마시고 싶나 | 에스트 > 0 · HP < max_hp × FIGHT_HEAL | `FIGHT_HEAL = 0.6` | [MoKa] 2026-09-28 "열심히 에스트 마시면서 플레이하는 것이 최선" (M0928-03); "Bandit Bot e 실행: 최저 HP 10 %까지 떨어지고도 에스트 5개가 남음 → 0.5 / 0.6 에서 올림" [meas, 런 id 없음] |
| field.py:209, 2108–2111 | `Field._walk` | 걷다가 멈추고 마심 `heal(0.7)` | HP < max_hp × WALK_HEAL · `walk_heal` 켜짐 · safe · 에스트 > 0 | `WALK_HEAL = 0.7` | M0928-03 (위와 같은 주석) |
| field.py:974 | `Field._fight_once` | duel 후퇴선 | desperate → 0.0 (끝까지), 아니면 RETREAT_HP | `RETREAT_HP = 0.5` | "was 0.25 — MoKa 2026-10-01: retreat more; low_hp fights took 335 each" [MoKa + meas] |
| field.py:995–996 | `Field._fight_once` | 처치 뒤 마심 `heal(0.7)` (기본 3모금) | duel 결과 killed | 0.7 하드코딩 | 파일 머리 "killed → estus if HP below 70 % (only when safe)" — 출처 없음 |
| field.py:759–818 | `Field.recover` | 지는 싸움 뒤: 붙은 놈 있으면 빈틈으로 구르기/약공 (BREAK_HITS) → safe 아니면 물러남 → `heal(0.9, sips=4)` → 계속할 가치? | `low` = HP < 0.6 × max 또는 why가 "losing"; 반환 = HP ≥ 0.6 × max | 하드코딩 `0.6` (low · 반환) · `heal(0.9, 4)` · `CHASER_ROLL_R = 1.8` · `escape_.BREAK_HITS` | 독스트링 "if safe, estus up to 90 %" 출처 없음; 'losing' 10-01 [meas]; [MoKa] 2026-10-01 · 10-10 "주변에 적이 애워싸면…" |
| field.py:1683–1686, 1833–1836, 1905–1911, 2002–2005, 2398–2401, 2425 | `clear` · `_clear_old` · `_walk_chaser` · `careful_walk_to` | recover가 False면 다음 싸움 `desperate` (low_hp 0 = 끝까지); False + 에스트 0 → `no_estus` (careful_walk_to는 "dead") | recover 결과 · `estus_left() <= 0` | — | "repeating 'low → can't retreat → can't drink' every 0.1 s … died, 2026-09-24" [meas]; 10-06 구역 5 [meas] |
| field.py:1343–1346 (1271) | `Field._emergency` | 나이프 대신 화염병 써도 됨 | HP < 0.35 × max · 에스트 0 | 하드코딩 `0.35` | 사용자 "bombs are better than dying" (값 출처 없음) |
| field.py:1392–1440 | `Field._hold_at` (자리 지키기) | 조용하면 방패 내림; 붙은 놈 + SP 부족 → `low_stamina_threat` (방패 내림); 다가오면 SP 되면 방패 | SP ≥ HOLD_GUARD_SP × max_sp | `HOLD_GUARD_SP = 0.25` (비율) · `HOLD_CALM_R = 5.0` · `HOLD_GUARD_R = 3.0` | Patch C 2026-09-26 "shield was up the whole wait … stamina never refilled (R3 34/106)" [meas]; 0.25 값 출처 없음 |
| field.py:1525–1546 | `Field._defend_in_place` | 기력 부족 제자리 방어 중 HP 낮으면 recover | HP < 0.25 × max | 하드코딩 `0.25` | 출처 없음 |
| field.py:426–430 | `Field.estus_left` | 개수 (퀵 종료 중 0으로 읽힘 주의) | — | — | 2026-09-25 190651 [meas] |
| field.py:212–214 | (상수) | 둘러싸임 후퇴 꺼짐 | `CROWD_FALL_BACK = False` | — | [MoKa] 2026-09-28 "일단 끄고 테스트" (P-26) |

## 3. souls/taurus.py (타우로스 데몬)

| file:line | 함수 | 판단 | 조건 | 상수 = 값 | 출처 (주석) |
|---|---|---|---|---|---|
| taurus.py:247–251 | `Taurus.run` | 부르기 전 마심 `f.heal(PRE_HEAL, sips=min(2, spare))` | spare = 에스트 − 1 > 0 (하나는 남김) | `PRE_HEAL = 0.80` | [MoKa] 10-06 "에스트는 1개만 있으면" (M1006-15); "save point start is 680/742 = 0.92" [meas]; 0.80 자체는 출처 없음 |
| taurus.py:454–465 | `_punish` | 착지 뒤 약공 1번 | 보스 PUNISH_R 안 · SP ≥ HIT_SP | `HIT_SP = 40` · `PUNISH_R = 2.6` | YouTube guide [02:02]; HIT_SP 40 출처 없음 |
| taurus.py:526–540 | `_on_top` | 탑 위에서 마심 (safe 검사 없음, `drink(lambda: True)`) | HP < max × TOP_HEAL · 에스트 > 0 | `TOP_HEAL = 0.50` | "Estus on the top only (YouTube guide)"; 11-02 002807 HP 225/698 (32 %) 안 마시고 낙하 → 사망 [meas] |
| taurus.py:598 | `_fight_loop` `low` | 마실 선 | HP < max(max_hp × ESTUS_HP, 2 × TAURUS_HIT) · 에스트 > 0 | `ESTUS_HP = 0.40` · `TAURUS_HIT = 245` (→ 2×=490) | TAURUS_HIT: "one hit seen 233–242 (10-12 3003 −233, 11-02 3006 / 3005 −242)" [meas]; [MoKa] 11-02 "연속 2대 맞으면 죽잖아" (M1102-03), 051424 [meas]; ESTUS_HP 0.40 출처 없음 |
| taurus.py:603 | `_fight_loop` `one_left` | 한 대에 죽음 → 기력 상관없이 마실 창, 그동안 약공 안 함 | HP ≤ TAURUS_HIT · 에스트 > 0 | `TAURUS_HIT = 245` | [MoKa] 11-09 "한 대 남으면 마셔" (M1109-24), 073200 HP 3 · 기력 98 약공 → 사망 (P-147) [meas] |
| **taurus.py:604–624** | `_fight_loop` 마시기 | **마심 (+ 바로 두 번째)** | `window` = low · (SP < HIT_SP 또는 one_left) · 보스 애니 ∉ BOSS_ATTACK; 그리고 (자리 SIP_SPOT_R 안 또는 창이 SIP_SPOT_WAIT 넘게 열림). 두 번째: 첫 모금 ok · 에스트 남음 · drink의 ok(보스 BOSS_ATTACK 밖) | `HIT_SP = 40` · `BOSS_ATTACK` = 3000–3499 ∪ 4000–4006 ∪ 4100–4106 · `SIP_SPOT_R = 0.8` · `SIP_SPOT_WAIT = 4.0` | [MoKa] 11-09 M1109-11 "에스트를 마셔도 다리 사이에서 마셔야지", M1109-12 "에스트를 왜 마셔 … 시간 낭비", M1109-13 "스테미나가 다 떨어져가서 할게 없으면 에스트 마셔도 되겠지만…", M1109-20 "에스트를 두번 마셔봐" (072235 [meas]); BOSS_ATTACK: 065619 −244·−277·−244 + TAE c2250 [meas + parser]; SIP_SPOT_R/WAIT "unmeasured" |
| taurus.py:635–655 | `_fight_loop` 공격 | 약공×3 (`sp_second=0`, BOSS_MOVE에 끊음) | 자리 SPOT_R 안 · not one_left · 보스 ∉ BOSS_MOVE · (SP ≥ HIT_SP 또는 자리 SPOT_ATTACK_S 이상 · SP > 0) — **보스 BOSS_ATTACK 여부는 안 봄** | `SPOT_R = 0.45` · `HIT_SP = 40` · `SPOT_ATTACK_S = 0.5` · `BOSS_MOVE = {701}` | [MoKa] 11-09 "다리에 붙었으면 바로 공격하고 3대를 연속으로" (M1109-16), "0.5초 내에 공격" (M1109-17), "701엔 기다려", "끊고 다시 붙어"; 071032 기력 80 기다림 6 s [meas]; SPOT_R 0.45 출처 없음 |
| taurus.py:656–657 | `_fight_loop` | 칠 때·마실 때 말고는 가드 | `GUARD_CLOSE = True` | — | [MoKa] 11-08 "양잡 가드 하면서 다리 밑으로 들어가봐" (M1108-16, P-141) — MoKa 본인 "문제는 가드를 하면 스테미나가 차지 않는게 문제" |
| taurus.py:70 | (상수) | **안 쓰임** | — | `HIT_SP2 = 80` "two in a row only from here (two cost ~76)" | [MoKa] 11-03 M1103-22 "2대 때리고 …" — 11-09 HIT_SP로 바뀜 (주석 632–634) |

## 4. souls/missions.py (성벽 마을 위 burg-upper)

| file:line | 함수 | 판단 | 조건 | 상수 = 값 | 출처 (주석) |
|---|---|---|---|---|---|
| missions.py:789–804 | `_top_up` | 유인/안개벽 전에 마심, 적이 가까우면 화톳불 쪽으로 물러나 마심; 낮고 에스트 0 → False (`no_estus`) | HP < max × UPPER_HEAL_FRAC | `UPPER_HEAL_FRAC = 0.7` | [MoKa] 10-06 "hp가 많이 줄었으면, 에스트를 마셔야 하는 것이 우선" (M1006-06) |
| missions.py:806–829 | `_drink_back` | 안전 자리 오면 **safe 안 보고** 1모금, 그래도 낮으면 2번째 | 1모금: HP < UPPER_SIP_FRAC; 2모금: HP < UPPER_HEAL_FRAC; UPPER_SWING_R 안 휘두르는 놈 있으면 미룸 | `UPPER_SIP_FRAC = 0.7` · `UPPER_HEAL_FRAC = 0.7` · `UPPER_SWING_R = 2.5` | [MoKa] 10-06 "무조건 에스트부터 마시게 해" (M1006-07) + MoKa 승인 예외 두 개 (10-06g 713/742, 2.4 m 화염병 −109) [meas]; "[MoKa] 90 → 80 → 70 %" |
| missions.py:1073–1096 | `_sip_on_hit` | 큰 한 방 뒤 일어나자마자 그 자리에서 마심 (safe·휘두름 안 봄) | 유인 달리기 동안 잃은 HP ≥ max × frac (구역 json `sip_on_hit`) | `sip_on_hit = 0.3` (data/burg-upper-map.json:317, :331) · `SIP_GETUP_S = 3.0` | [MoKa] 11-02 "죽지 않으니 맞으면 바로 에스트 마시는게 더 나은 방법이야" (M1102-06, P-105); 022918 미뤘다 사망 [meas] |
| missions.py:1148–1153 | `_before` 사다리 | 사다리 전 마심 `f.heal(heal_first, 3)` | HP < max × heal_first | `heal_first = 0.9` (data/burg-upper-map.json:409, 구역 8) | [MoKa] 11-01 "가)+나) 고치기" (M1101-08); 214607 72 %로 올라가 사망 [meas] |
| missions.py:606–614 | 구역 8 `hold` | 석궁 hold: desperate=True 싸움, 사이사이 `f.heal(UPPER_HEAL_FRAC)` | 매 라운드 뒤 | `UPPER_HEAL_FRAC` 0.7 | [MoKa] 11-01 "녹화처럼 달려가 기다리기" (P-103) |
| missions.py:617–631, 651–658, 429–432 | `upper_zone` attack/일반 · `burg` | recover 실패 + 에스트 0 → `no_estus`; 실패면 다음 desperate | Field.recover 반환 | — | 10-06 구역 8 (P-47) [meas] |

## 5. souls/reflex.py · souls/guardkeep.py · souls/moves.py · souls/weapons.py

| file:line | 함수 | 판단 | 조건 | 상수 = 값 | 출처 (주석) |
|---|---|---|---|---|---|
| reflex.py:236–239 | `Reflex.tick` | 막지 않고 마주보기 (`step_away`) | SP < GUARD_SP (또는 evade 스타일) | `GUARD_SP = 25` | 2026-09-24 SP 12~22 가드 깨짐·낙사 [meas] |
| reflex.py:215–233 | `Reflex.tick` → `dodge` | 막을 수 없는 공격 → 백스텝/구르기 | **SP 조건 없음** | — | 2026-09-24, M1109-76 |
| reflex.py:152–193 | `Reflex.guard_counter` | 방패 맞음 → 약공 | SP ≥ GUARD_COUNTER_SP | `GUARD_COUNTER_SP = 1` | M1108-01/02 (§1) |
| guardkeep.py:70–71 | `GuardKeep` | 미리 든 방패 유지 끝 | SP < GUARD_SP | `reflex.GUARD_SP` 25 | (모듈 독스트링: 가드 깨짐 → 낭떠러지) |
| moves.py:367–386 | `Moves.light(n, sp_second=40)` | 2·3타째를 칠지 | 시작 시 SP ≥ sp_second면 min(3,n)번, 아니면 1번 | 기본 `sp_second = 40`; duel은 `weapon.sp_min`, taurus는 0, asylum/taurus _punish는 999 (= 1타만) | 출처 없음 |
| moves.py:727–749 | `Moves.drink(safe)` | 한 모금: 칸 고른 뒤 `safe(snap)` 다시 보고 마심, 2.2 s 기다림 | safe 콜백 | 2.2 s 하드코딩 | 출처 없음 (ledger M1108-07 check: "에스트 약 2.2 s") |
| weapons.py:20 | `Weapon.sp_min` 기본 | "below this stamina, don't attack — guard" | — | 40 | 출처 없음 |
| weapons.py:72 | BROADSWORD | 〃 | — | sp_min 40 (기본) | 출처 없음 |
| weapons.py:77 | ZWEIHANDER | 〃 | — | sp_min 60 | 출처 없음 (강공 120 [meas 09-23]) |
| weapons.py:99 | BATTLE_AXE (DEFAULT) | 〃 | — | sp_min 55 | 출처 없음 (약공 −25 [meas 09-28]; reflex 주석이 "2연타 콤보용 기준"이라 부름) |
| weapons.py:114 | CLAYMORE | 〃 | — | sp_min 60 | "first values from the wiki" [wiki]; 약공 −30 [meas 09-25] |
| weapons.py:131 | BANDITS_KNIFE | 〃 | — | sp_min 30 | 출처 없음 (약공 −14 [meas 09-28]) |

## 6. 기타 (task 목록 밖에서 찾은 것)

| file:line | 함수 | 판단 | 조건 | 상수 = 값 | 출처 |
|---|---|---|---|---|---|
| souls/watch.py:26–34, 104–110 | `Escape` 독스트링 · `_dps` | 독스트링은 "predicted HP 2.8 s ahead below 15 %"이면 퀵 종료라 하지만 **`_run`에 그 판단이 없음** — `_dps`·`QUIT_S = 2.8`은 아무도 안 부름 (`grep`). 지금 퀵 종료/워프는 낙사(기록만)와 `_crowd3`(적 수·거리, HP 안 봄)뿐 | — | `QUIT_S = 2.8` (안 쓰임) | [MoKa] 09-28 "둘러싸였을 때는 퀵 종료하면 안 되고 후퇴해야 해" (주석 136–140) |
| souls/asylum.py:49–50, 637–641 | 수용소 데몬 | 싸움 중 마심 | HP < max × DEMON_ESTUS_HP · 데몬 DEMON_ESTUS_R 밖 · 안 휘두름 | `DEMON_ESTUS_HP = 0.4` · `DEMON_ESTUS_R = 6.0` | 출처 없음 |
| souls/asylum.py:67, 238 | `ready` | 구간 시작 안 함 | HP < max × START_HP · 에스트 0 | `START_HP = 0.5` | "segment 2 and 3 left us at 152/616" [meas] |
| souls/asylum.py:644–647 | 데몬 약공 | 약공 1번 (`sp_second=999`) | **SP 조건 없음** | — | — |
| souls/altar.py:379–383 | ② 아래층 대기 | `heal(0.9, 3)` | HP < 0.9 · safe · 에스트 > 0 | 하드코딩 0.9 | 출처 없음 |
| souls/altar.py:462–468 | 헬카이트 엄폐 | `heal(0.9, 3)`, 근처 3 m 적 있으면 desperate | HP < 0.6 | 하드코딩 0.6 / 0.9 | 출처 없음 |
| souls/altar.py:507–510 | 출발 전 | `heal(0.9, 4)`; `walk_heal = False` (다리 위에서 안 멈춤) | HP < 0.9 | 하드코딩 0.9 | 10-13 chain3b 3번째 HP 41 % → 사망 [meas] |
| run.py:131, 521 · afterdeath.py:91–95 | `--level-up` 구역 사이 | 다음 구역 안 하고 `estus_low`로 화톳불 | 에스트 ≤ ESTUS_HOME | `ESTUS_HOME = 1` | [MoKa] 10-31 "에스트 하나 남았으면 그냥 돌아가" (M1031-02) |
| boss_ready.py:182–187 | `taurus` 확인 | 실행 막음 | 에스트 < 1 (못 읽으면 막음) | 1 | M1006-15 |
| souls/style.py:6, 28 | RUSH 스타일 | 반사·방패 끔, "survive on Estus" | — | — | 사용자 2026-09-25 "Don't defend either, just drink Estus" |

---

## 7. MoKa ledger 줄 (docs/moka_ledger.jsonl, HP · 기력 · 에스트 관련)

| id | 상태 | 인용 (원문) | ledger `where` |
|---|---|---|---|
| M0000-05 | built | "drink if safe" (en_record) | duel.rule_estus |
| M0928-03 | built | "열심히 에스트 마시면서 플레이하는 것이 최선" | field FIGHT_HEAL 0.6 · WALK_HEAL 0.7 |
| M1006-06 | built | "hp가 많이 줄었으면, 에스트를 마셔야 하는 것이 우선" | missions UPPER_HEAL_FRAC 0.7 |
| M1006-07 | built | "그 구간이 화염병 맞는 구간이라 안전 구역으로 오고, 무조건 에스트부터 마시게 해" | missions._drink_back · UPPER_SIP_FRAC 0.7 |
| M1006-15 | built | "에스트는 1개만 있으면" | boss_ready.taurus · taurus PRE_HEAL spare |
| M1031-02 | built | "에스트 하나 남았으면 그냥 돌아가" | run.py ESTUS_HOME 1 |
| M1101-08 | built | "가)+나) 고치기" | field.desperate DESPERATE_HP · 구역 8 heal_first 0.9 |
| M1102-01 | built | "나는 낙하 공격 한 번 하고 황금 송진 유효할때 계속 때려. 에스트 마시면서. 4-5번만 때리면 죽어 타우로스. …" | taurus PLUNGES 1 |
| M1102-03 | built | "연속 2대 맞으면 죽잖아" | taurus TAURUS_HIT 245 |
| M1102-06 | built | "죽지 않으니 맞으면 바로 에스트 마시는게 더 나은 방법이야" | missions._sip_on_hit 0.3 |
| M1103-13 | built | "기력 아껴 봐" (also: "방패 가드의 단점이 막으면 스테미나를 많이 사용해서 다음 공격이 어려워 지는데") | duel.rule_jump_save |
| M1103-22 | built | "2대 때리고 다시 가랑이에 붙어봐. 거리 조절도 되지만, 스테미나도 채워야해" | taurus HIT_SP2 80 (n=2) — **지금 코드와 다름** (§8-c) |
| M1108-01 | built | "방패, 약공은 모든 공격에세 기본으로 하게 수정해." | reflex.guard_counter |
| M1108-02 | built | "첫 번째 방패 부딪혔을때 반응해서 약공 들어갔으면 되는데" | reflex.GUARD_COUNTER_SP 1 |
| M1108-07 | built | "30% 이하이면 에스트 마시고 뭔가 해야 하는데 않했음" (topic "HP 30 % 이하 → 에스트 마시고 뭔가") | field.desperate LAST_SIP_R 3.5 (P-139); check (perplexity): partial — "HP 낮다고가 아니라 적 회복 틈·거리 벌린 뒤 마심" |
| M1108-16 | built | "타우로스 실행 하는데 양잡 가드 하면서 다리 밑으로 들어가봐." | taurus GUARD_CLOSE |
| M1108-19 | built | "않되도 않된게 아니라 다른 팩터가 영향을 줘서 않되는 경우가 다반사야. …" | moka_ledger.py --cases (HP · 기력 · 거리) |
| M1109-10 | built | "다리사이로 붙으라니깐 왜 멀리 떨어져. …" | taurus 낮은 HP 물러남 없앰 |
| M1109-11 | built | "에스트를 마셔도 다리 사이에서 마셔야지" | taurus SIP_SPOT_R 0.8 · SIP_SPOT_WAIT 4.0 |
| M1109-12 | built | "여기서 가장 이해 않가는게, 에스트를 왜 마셔, 다리 사이에서 몇대 때리면 죽는데, 에스트 마시면서 시간 낭비 하잖아." | taurus "기력 ≥ HIT_SP2면 약공×2" — **stale** (§8-c) |
| M1109-13 | built | "만약에 스테미나가 다 떨어져가서 할게 없으면 에스트 마셔도 되겠지만, 다른 케이스는 스테미니가 더 중요한 상황이야." | taurus 마시는 조건 "기력 < HIT_SP2(80)" — **stale** (§8-c) |
| M1109-14 | principle | "다크소울 자체가 다른 회사들의 게임과 다른 점 혹은 특징이 이 스테미나 관리야. 그래서 어쩔때는 공격은 스테미나 관리, 방어는 hp 관리 라고 봐도 되." | taurus 에스트 조건만 |
| M1109-15 | noted | "cloud에게 hp, stamina 관리 하는 것에 대해 연구 하라고 그래. 이게 않되면, 뒤로 가면 갈수록 문제가 커져." | 이 목록이 그 요청의 일부 |
| M1109-16 | built | "다리에 붙었으면 바로 공격하고 3대를 연속으로 때려봐." | taurus HIT_SP 40 → 약공×3 |
| M1109-17 | built | "다리에 붙으면 0.5초 내에 공격 들어가봐." | taurus SPOT_ATTACK_S 0.5 (SP > 0) |
| M1109-20 | built | "그리고 에스트를 두번 마셔봐." | taurus 두 번째 모금 |
| M1109-24 | built | "한 대 남으면 마셔" | taurus one_left (HP ≤ 245) |
| M1109-71 | held | "… 이게 아주 유명한 에스트 캐치라는 기술이야. 캐릭터가 에스트 마시려고 뒤로 물러나서 마시기 동작이 들어가면, 빠르게 공격이 들어 가는 거고 …" | field.safe SAFE_R 6 — "기록만 두자", SAFE_R 안 바꿈 |
| M1110-19 | noted | "에스트 마시면, 둘이 동시에 달려 들고" | 연습장 punish_estus만 |
| M1111-03 | built | "…실제 전투시에는 스테미나가 줄고 그 사이에 때릴수 있는 타격 횟수가 빠져서 아쉽네." | weapon_probe (측정, 봇 판단 아님) |
| M1111-04 | noted | "츠바이헨더는 사기급 무기 인데 스테미나 사용을 고려해서 end 스탯을 2번 때릴수 있을 정도로 보통 업그레이드를 해. …" | 지구력별 최대 기력 미측정 |
| M1111-12 | noted | "… 나는 무기 안든 오른쪽 쪽으로 돌면서 때리거나, 스테미나를 채우면서 계속 공격하는 거야." | 봇에 안 넣음 (데몬 c2300) |

(M1109-51·53·75·76·79 · M1111-07 등 연습장/시뮬 줄에도 기력·HP가 나오지만 봇 판단 코드가 아님 — 뺌.)

---

## 8. Overlaps and contradictions

### a. 같은 것을 다른 문턱으로 정하는 곳 — "에스트를 언제 마시나" (HP 비율)
| 곳 | HP 선 | 안전 검사 |
|---|---|---|
| field.Care.wants (duel 안) | < 0.6 (FIGHT_HEAL) | duel.opening: 그놈 ≥ 3.0 m (OPEN_R) · 다른 놈 5 m 밖 · 8 m 안 휘두름 없음 |
| field._walk | < 0.7 (WALK_HEAL) | Field.safe: 6 m (SAFE_R) · 8 m 휘두름 · 25 m 투척병 |
| field._fight_once 처치 뒤 | heal(0.7) | safe / desperate |
| field.recover | heal(0.9, 4) | safe / desperate |
| field.desperate | < 0.3 (DESPERATE_HP) | 근접 3.5 m (LAST_SIP_R) · 투척 4.0 m |
| missions._top_up / hold | < 0.7 (UPPER_HEAL_FRAC) | safe / desperate (+ 물러남) |
| missions._drink_back | < 0.7 (UPPER_SIP_FRAC) / 0.7 | **safe 안 봄**, 2.5 m 휘두름만 |
| missions._sip_on_hit | 한 방에 ≥ 0.3 × max 잃음 | **아무것도 안 봄** |
| missions 사다리 heal_first | < 0.9 | safe / desperate |
| taurus PRE_HEAL / TOP_HEAL | 0.80 / < 0.50 | heal(safe) / **안 봄** |
| taurus 근접 low | < max(0.40, 490 HP) | 보스 BOSS_ATTACK 밖 · 자리 0.8 m |
| asylum 데몬 | < 0.4 | 데몬 6 m 밖 |
| altar | 0.9 (0.6에서 시작) | safe / 3 m |

- 싸움 안(opening, 3 m)이 싸움 밖(safe, 6 m)보다 느슨하다: 같은 놈이 4 m에서 서 있으면 duel은 마시고 Field.heal은 안 마심. M1109-71 (held)은 6 m도 모자란다고 기록함 → OPEN_R 3.0은 그 기록과 더 크게 어긋남 (기록만, MoKa가 고치지 말라 함 — "collect-then-improve").
- 타우로스 `low`는 `max(max_hp × 0.40, 2 × 245)` — max_hp가 1225 미만이면 언제나 490이 이김. 주석의 save point (max 742)에선 실제 선이 **66 %**이고 `ESTUS_HP = 0.40`은 효과가 없음. ESTUS_HP는 출처 없음, 490은 M1102-03 근거.

### b. 한 규칙 때문에 다른 규칙이 닿지 않는 곳
1. **`CROWD_LOW_HP = 0.45`는 지금 한 번도 안 올림.** `_low_hp_line`은 `max(low_hp, 0.45)`인데 duel을 부르는 곳은 `Field._fight_once`(field.py:974) 하나뿐이고 low_hp는 0.5 (RETREAT_HP) 또는 0.0 (desperate; 0이면 함수가 바로 0 반환). duel 기본값 0.25로 부르는 곳 없음 (grep). 그래서 "둘이면 45 %에서 후퇴" (P-8)는 죽은 줄. field.py:213 · 232 주석 "HP 45 % 후퇴(recover)만"도 지금 값 (50 %)과 다름.
2. **`rule_estus` (22)는 그 앞 공격 규칙에 자주 밀림.** HP < 0.6이어도 `rule_after_swing` (12, 휘두름 끝 0.6 s 안 · 닿는 거리+1.2 m · SP ≥ sp_min), `rule_hit_first` (17, 방패병 아님 · 닿는 거리 · 서 있음 · SP ≥ sp_min), `rule_guard_counter` (6, SP ≥ 1)가 먼저 틱을 가짐. rule_estus의 "가까우면 백스텝" 갈래는 `h < OPEN_R (3.0)` · 안 휘두름일 때인데, 그 중 h ≤ reach (1.6–1.8 m) · SP ≥ sp_min인 비방패병 경우는 hit_first가 먼저 침. 결과: 백스텝→마시기 갈래는 방패병, reach~3 m 사이, 또는 SP < sp_min일 때만 사실상 열림. (정적 읽기 결론 — 런에서 센 것 아님.)
3. **rule_estus가 일할 HP 띠가 좁음.** `_sense`가 RULES 전에 HP < 0.5에서 `low_hp`로 끝내므로 (desperate 아닌 싸움) duel 안 에스트는 0.5–0.6 사이에서만 열림. 그 밑은 recover → retreat → heal(0.9) (Field.safe 6 m 또는 desperate 0.3 선)로 넘어감.
4. `rule_attack` (34)은 자체 SP 검사가 없지만 `rule_stamina` (31)가 SP < sp_min이면 먼저 CONT → 공격은 sp_min 밑에서 못 나감. 반대로 `rule_block` (25, SP 검사 없음)은 rule_stamina보다 위라 SP가 0이어도 2.5–4.0 m 휘두름엔 방패를 든다 (reflex는 2.5 m 안에서 SP < 25면 안 듦). 즉 "SP 25 밑에선 막지 않음" (GUARD_SP, 09-24 낙사 근거)은 2.5 m 안에서만 지켜지고 2.5–4 m에선 rule_block이 깸.
5. `HIT_SP2 = 80` (taurus.py:70)은 어디서도 안 읽힘 (grep) — 남은 상수.
6. watch.Escape 독스트링·`_dps`·`QUIT_S`: "예측 HP 15 % 퀵 종료"는 코드에 없음 (위 §6). 독스트링을 믿고 "HP가 위험하면 Escape가 뺀다"고 보면 틀림.

### c. ledger `where`와 지금 코드가 다른 곳
- M1103-22 ("2대 때리고 …", `HIT_SP2 80 (n=2)`), M1109-12 ("기력 ≥ HIT_SP2면 약공×2"), M1109-13 ("기력 < HIT_SP2(80)"), M1109-14 ("기력 < HIT_SP2일 때만"): 코드는 M1109-16/17 뒤 **HIT_SP 40 · 약공×3 · SPOT_ATTACK_S 0.5 s 뒤 SP > 0이면 침**, 마시는 창도 `SP < HIT_SP (40)`. ledger 줄 4개가 옛 값을 가리킴.

### d. MoKa 원칙과 견주어 본 것 (판단은 MoKa 몫 — 사실만)
- **M1109-14 "공격은 스테미나 관리, 방어는 hp 관리"** / **M1109-13 "스테미나가 다 떨어져가서 할게 없으면 에스트 …"**: 기력을 보고 에스트를 정하는 곳은 **타우로스 `_fight_loop` 하나뿐**. 일반 싸움 (duel `Care.wants` · rule_estus), 걷기 (WALK_HEAL), Field.heal/desperate, missions의 모든 마시기는 **HP와 적 거리만** 보고 기력은 안 봄. 그래서 일반 싸움에선 기력이 넉넉해도 HP < 0.6 + 틈이면 마시고 (rule_estus), 기력이 바닥이어도 HP ≥ 0.6이면 안 마시고 rule_stamina (31)로 방패 내리고 서 있음. 일반화는 안 만들어짐 (M1109-15 noted).
- **방어 쪽 "hp 관리"**: 방어 판단 (rule_block · reflex · guardkeep)은 HP를 안 보고 SP(25)·거리·애니만 봄; HP를 보는 방어 판단은 후퇴선 (`_sense` 0.5 · losing · WAIT_HURT_HP 120)뿐.
- **공격 쪽 "스테미나 관리"**: 공격 문턱이 규칙마다 다름 — sp_min (무기별 30–60), FINISH_SP 15, GUARD_COUNTER_SP 1, HEAVY_SP 100, WALL/SLEEPER_HEAVY_SP 60, SWING_BS_SP 50, JUMP_SP 65 / 85, 타우로스 HIT_SP 40 또는 SP > 0, `light()` 2타째 기본 40. sp_min 값들은 대부분 출처 없음 (클레이모어만 [wiki]); 주석에 남은 측정은 한 번 휘두를 때 드는 기력 (−14 · −25 · −30)뿐. GUARD_COUNTER_SP 1은 MoKa가 위험을 받아들인 예외.
- **타우로스 "시간 낭비 말고, 마시면 다리 사이에서"** (M1109-11/12): 마시는 창은 HP < 490 (max 742에서 66 %) 이고 SP < 40일 때 — 붙어서 약공×3 뒤 기력이 40 밑으로 떨어지는 매 사슬 뒤에 HP가 490 밑이면 마심 (+ 두 번째 모금, M1109-20). 즉 "기력이 다 떨어져 할 게 없을 때"의 "다 떨어짐"이 40 (약공 한 대 ≈38)으로 정해져 있음 — 이 값은 출처 없음. `TOP_HEAL` 탑 위 마시기는 safe 검사 없이 마심 (보스 손이 안 닿는다는 주석 근거). 공격 쪽은 보스 BOSS_ATTACK 중에도 SPOT_ATTACK_S 뒤 SP > 0이면 약공×3을 시작할 수 있음 (BOSS_MOVE 701만 막음) — 정적 읽기 사실, 런에서 일어났는지는 안 봄.
- **M1108-07 "30% 이하이면 에스트 마시고 뭔가"**: `DESPERATE_HP 0.3`은 Field.heal 안에서만 (recover·걷기·처치 뒤). duel 안에선 desperate 싸움 (low_hp 0)이어도 `Care.wants` 0.6 + `opening()`만 보고 `desperate()`의 3.5 m 규칙을 쓰지 않음 — 두 길의 "가까운 적" 기준이 3.0 m (OPEN_R, 그놈만 · 다른 놈은 5 m) 대 3.5 m (LAST_SIP_R, 모든 근접 적)로 다름. perplexity check (ledger)는 "HP 낮다고가 아니라 적 회복 틈·거리 벌린 뒤 마심"으로 partial.
- **M0928-03 "열심히 에스트" ↔ M1109-12 "에스트 마시면서 시간 낭비"**: ledger가 M1109-13으로 정리 (타우로스 한정). 일반 싸움 규칙은 M0928-03 쪽 (0.6 / 0.7 / 0.9)으로 남아 있음.
- **M1102-06 / M1006-07 (safe 안 보고 마심) ↔ M1109-71 (에스트 캐치, held)**: missions `_sip_on_hit`·`_drink_back`, taurus `_on_top`은 MoKa 지시로 거리 검사 없이 마심; M1109-71은 마시는 2.2 s 동안 7 m 다가오는 적을 기록. 두 지시는 다른 구간 (불붙은 통·화염병 구간 대 해골 묘지)이라 충돌인지는 MoKa 판단.
- 하드코딩 비율 (출처 없음): recover 0.6/0.9, 처치 뒤 0.7, _defend_in_place 0.25, _emergency 0.35, duel 0.12, altar 0.9/0.6.
