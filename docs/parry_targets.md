# 패링 되는 몹 (웹 자료 요약, 게임 검증 아님)

출처: Perplexity 2026-11-15 (MoKa 요청 M1115-09). 근거는 darksouls.wikidot "List of Parriable Enemies"와 darksouls.fandom의
공격 표. 게임 파일로는 아직 확인 안 함 (flag 73 "패링 가능"은 c2540 · c2550 · 플레이어 TAE 어디에도 없음). 봇이 실제로 패링한 것은
아래 "봇 기록"뿐.

## 지금 경로 몹 (Burg · Parish) — [cloud] 표에 붙일 요약
모델 이름은 게임 파일에 없음(`chr_models.json`에 이름 칸 없음). 아래 이름은 NPC 번호 · 장소 · 생김새로 맞춘 **추정**.

| 모델 (NPC) | 추정 이름 | 위키 | 봇 드릴 11-15 (성공/판정) | 쓸 만한가 |
|---|---|---|---|---|
| c2540 (254010 · 254000) | Burg 망자 (검 · 도끼 · 화염병) | 근접형 가능, 화염병 · 활 불가 | 시험 안 함 | 근접 공격만 후보. 3000/3001 연타가 많아 패링 뒤 다른 적 위험 |
| c2550 (255001 · 255041) | 망자 병사 (방패 + 검/창) | 근접 가능 | 3003 3/3 · 3005 1/2 · 3004 0/1 (섹션 버그) · 3009 0/1 | 3003 · 3005 · 3004(a01) 후보, **3009는 제외** (가드 부담 100, MoKa도 실패) |
| c2550 (255002 · 255042) | 석궁 병사 | 석궁 불가 | 근접 안 옴 — 그냥 잡음 | 아님 |
| c2560 (256000 · 256002) | 교구 교회 기사 (Balder Knight로 추정) | 검 · 레이피어형 가능 | 3000 4/5 · 3005 2/4 · 3003 1/4 · 3001 0/1 | 가장 쉬움 (MoKa "칼든 기사 계열이 패링이 가장 쉬워"). 3003은 2.2 m 안에서만 |
| c2570 (257002, HP 744) | Berenike Knight로 추정 | 일부 공격만 패링, **앞잡이 불가** | 시험 안 함 | 아님 (패링해도 앞잡이가 안 들어감) |

- 같은 메모리 애니 번호라도 NPC마다 TAE 섹션이 다름: 255041 → a01, 256002 → a02, 나머지는 a00 (관찰로 정한 표, `parry_drill.SECTION`).
- 타이밍: 적 판정(TAE type 1) 시작이 패링 애니(485102)의 0.02~0.19 s 안에 들어오게 L2를 누름. 판정 시작 0.03~0.12 s 전에 누르는 셈.
- 패링 실패의 대가: 검병 약 −120, 기사 약 −250 (드릴의 피격). 방패로 막다 실패하면 기력만 잃는 것과 다름.

## 보스
- **Gwyn만 패링 가능** (검 공격과 점프 검 공격. 발차기와 잡기는 불가).
- 나머지 보스는 모두 불가: Asylum · Taurus · Bell Gargoyles · Capra · Moonlight Butterfly · Gaping Dragon · Quelaag · Stray ·
  Iron Golem · Ornstein & Smough · Priscilla · Gwyndolin · Sif · Pinwheel · Nito · Seath · Four Kings · Ceaseless ·
  Firesage · Centipede · Bed of Chaos · DLC 보스 전부.

## 큰 몹
- **가능:** Black Knight (모든 무기), Silver Knight (근접만), 블라이트타운 몽둥이 거인 (Infested Barbarian 몽둥이형), Butcher (잡기는 불가).
- **패링은 되지만 앞잡이는 안 됨:** Berenike Knight (교회 위층의 큰 기사).
  - 메이스형: 기본 · 가로 휘두르기 · 강공격은 가능, 방패 치기는 불가.
  - 대검형: 가로 베기 · 두 번 베기는 가능, 강공격 · 방패 치기는 불가.
- **불가:** 센의 요새 거인, Anor Londo 센티널, 다크루트 Stone Knight, Titanite Demon, 일반 Taurus · Capra Demon, Bat Wing Demon,
  일반 Gargoyle, Bounding Demon, Crystal Golem, 큰 해골 · Bonewheel, Fang Boar.
  - Fang Boar의 돌진은 패링 동작으로 튕겨 낼 수 있지만 앞잡이는 안 됨.

## 보통 몹 (근접 공격만 해당. 활 · 석궁 · 마법 · 잡기는 불가)
- **가능:** 할로우 (검 · 횃불), Undead Soldier, Balder Knight (검 · 레이피어. 석궁형은 불가), 도둑 · 암살자, 해골 (검), Serpent Soldier,
  Painting Guardian, Darkwraith, Crystal Soldier (근접).
- **사람형 NPC:** 쓰는 무기 공격을 따름. Havel, Kirk, Mildred, Leeroy 등은 가능. Andre는 가능하지만 드롭킥은 불가.

## 봇 기록 (11-15 드릴, parry_drill.py)
- c2550 (Undead Soldier 검병 255041): 3003 · 3005 성공. 3009는 불가로 둠 (봇과 MoKa 모두 실패).
- c2560 (교회 기사 256000 · 256002): 3000 · 3003 · 3005 성공.
  - 2.2 m보다 먼 거리의 3003은 3번 모두 실패 (가설: 거리).
- 257002 (교회 안, HP 744): 아직 시도 안 함. c2570 = Berenike Knight라면 위 표대로 앞잡이 불가 (모델 대조 필요).
