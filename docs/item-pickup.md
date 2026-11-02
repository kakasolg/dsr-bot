# 아이템 획득 진단 (Firelink 초기 아이템, 2026-11-01~)

목표: 대략적인 위치 자료만으로 봇이 아이템을 찾아 줍는지 본다. 목표 5개를 하나씩, 결과를 이미 획득 / 이번에 획득 / 실패 /
확인 불가로 나눠 적는다. 아이템 사용·장비 변경·레벨업 없음, 실패 뒤 자동 코드 수정 없음 (MoKa 11-01).

| # | 목표 | 상태 |
|---|---|---|
| 1 | 우물 가장자리 인간성 3 (flag 51020000, item 500) | **획득 1회 + 닫기 A 1회 성공 사례** (아래) |
| 2 | 화염병 6 | 미시도 |
| 3 | 이름 없는 영혼 (첫째) | 미시도 · 이름 확인 필요 (Firelink 자료에는 Soul of a Lost Undead id 400만 있음) |
| 4 | 이름 없는 영혼 (둘째) | 미시도 · 3과 같음 |
| 5 | 귀환의 뼛조각 6 | 미시도 · NavMesh 경로 없음 (내려가야 함) |

## 1. 인간성 3 — 2026-11-01 실행 1회

**획득 및 닫기 A가 1회 성공한 사례.** 반복 재현은 하지 않았다.

- 시작: 기준 세이브 `backup-20260929-080235-asylum-test-full-bot-run-firelink` (sl2 `e2da9f35…55710`)로 복원, 화톳불 1022960
  (-47.4, -59.82, 53.29), 인간성 0, menu_open False. 복원 전 세이브는 `backup-20261101-042428-before-restore-…` (sl2 `97542d86…`).
- 실행 `20261101_042509_humanity` (`experiments/item_pickup_2026_11_01/humanity_probe.py`, `--close-a` 없이):
  - 이동 입력 38개, 줍기 A 1개. 마지막 위치 (-38.98, -58.86, 53.71), 시체까지 0.476 m, 화톳불까지 8.484 m.
  - 획득 확인 (메모리, 1회): event_flag(51020000) False → True (A 뒤 0.38 s, 기록 t 5.042 s) · goods_count(500) 1 → 4 (차이 3 =
    ItemLot 수량, 일치) · humanity() 0 → 0 (소지품 인간성은 인간성 수치가 아님).
  - 시작 전 goods_count가 이미 1이었다 → 0은 "없음"의 증거가 아니고, 개수는 차이로만 본다.
- 창 (MoKa 눈 확인, 메모리 근거 아님):
  - 획득 창이 떠 있었다 (05:08 "떠 있음"). 그동안 menu_open()은 처음부터 끝까지 False.
  - 닫기 A는 MoKa 요청("너가 닫아봐")으로 따로 1회 보냄 (`….close.jsonl`). 첫 시도는 Probe 직접 생성 버그(`now` 없음 → TypeError)로
    입력 없이 끝났고, 두 번째 시도에서 A 1회 (t 2.71 s). 닫기 전후 flag True · goods 4 · menu_open False 그대로.
  - 05:10 "사라졌어" → 닫기 A 1회 뒤 창이 사라짐.

### 이 사례에서 확인된 것 / 안 된 것

- 확인 (메모리 읽기, 1회): 이 위치·이 세이브에서 A 1회로 flag와 개수가 바뀜.
- 확인 (MoKa 눈, 1회): 창이 떴고, A 1회로 닫힘.
- **menu_open()은 이 창을 구분하지 못한다** (창이 떠 있는 동안 False). "menu_open False = 창 없음"으로 쓰면 안 된다.
  다른 메모리 값으로 창을 볼 수 있는지는 찾아보지 않았다 — 없다는 뜻이 아니다.
- 창 표시·닫힘 판정은 지금 MoKa 확인뿐이다. 코드는 `close_confirmed`를 None으로 남긴다.
- 미검증: 다른 4개 목표 · 같은 목표 반복 · 줍기 거리 한계 · 창 자동 판정 · 창을 닫지 않은 채 이동/전투했을 때의 영향 · 봇 본편 경로
  (`souls/altar.py` `_claymore`의 획득 분기는 게임에서 실행된 기록이 없음, 로그에는 "이미 주움"만).

### 11-01 이후 코드 정리 (오프라인만)

- `humanity_probe.py`: Probe 직접 생성 시 `self.now()` 사용 (TypeError 수정) · `PICK_TRIES` 2 → 1 (두 번째 A는 "menu_open
  False = 창 없음" 전제였음) · 결과는 획득만 ("got", `--close-a`여도 같음), 창은 별도 `ui` 기록 (window_shown · close_approved ·
  close_sent_t · close_confirmed = None) · 못 주웠을 때도 화면 확인 요청.
- 기존 획득 경로와 같은 모양: `souls/altar.py` `_claymore` (walk_to → A → event_flag → 닫기 A). 그쪽은 menu_open을 안 쓰고, 닫기 A를
  조건 없이 1회 보낸다 — 이번 사례(닫기 A 1회로 사라짐)와 모순은 없지만 1회 근거다. 그쪽 코드는 이번에 고치지 않았다.
- 참고 (수정 안 함): `radar_warp.py:107`의 워프 전제 "게임 메뉴를 먼저 닫아라"는 menu_open을 보므로 획득 창은 못 본다.
- 검사: `python experiments/item_pickup_2026_11_01/humanity_probe_test.py` 27/27 (가짜 세계 · 실제 control.Pad + pad_fakes · 가짜
  시계; 게임 관련 사항은 검사 안 됨).

### 기록 위치 (`experiments/item_pickup_2026_11_01/runs/`, 미추적)

| 파일 | 내용 |
|---|---|
| `preflight_20261101_042335.txt` | 기준 세이브 해시, HEAD 6ccafc0, dirty 20개, diff sha `6c2820b2…` |
| `restore_20261101.txt` · `start_state_20261101.txt` | 복원 기록 · 시작 상태 |
| `20261101_042509_humanity.jsonl` | 원본 실행 기록 (sha256 `4d5a57e9…3385f`, 수정 안 함) |
| `20261101_042509_humanity.observation.jsonl` | MoKa 관찰 2줄 (창 떠 있음 / 닫기 A 뒤 사라짐) — 원본과 별도 |
| `20261101_042509_humanity.close.jsonl` | 닫기 A 기록 (첫 시도 exception·입력 없음, 두 번째 A 1회) |

## 2. 적 드롭 표 — 오프라인 추출 (2026-11-01, 게임 관측 없음)

MoKa 11-01: "현재 경로에서 만나는 적과 드롭 표를 연결하고, 이후 실제 드롭 탐지 관측에 쓸 적절한 후보를 고르는 것" — 사망 전 드롭
예측·자율 획득이 아니다. 근거 등급은 전부 "file"(게임 파일에 그렇게 적혀 있음)이다.

- 도구: `drop_tables.py <mapID> … [--tracks "<glob>"]` → `data/gamefiles/<mapID>-drops.json`. `msb_extract.py`는 고치지 않았다.
  - 입력: 그 맵 JSON(`enemies[].npc_param_id`, `entity_id`, `pos`)과 GameParam의 NpcParam·ItemLotParam.
  - 파서: 기존 의존성 soulstruct 2.3.2 (GPL-3.0-or-later). 새로 설치한 것도, 모드 코드에서 복사한 것도 없다.
  - 아이템 이름: `msb_extract.load_item_names`
  - 출력의 `source`에 입력 3개(맵 JSON, GameParam, item.msgbnd)의 sha256을 남긴다.
  - `--tracks`: 지난 실행의 `*.track.jsonl`에서 실시간 스냅숏에 그 NpcParam이 잡힌 실행 수(`seen_runs`) — "경로에서 만났다"의 근거.
- 연결: 배치 개체 → NpcParam → `itemLotId_1..6` → lot 행과 그 뒤에 이어지는 행(lot+1 …) → 칸마다 종류·ID·수량·points·운·칸 플래그
  → 행의 `ItemFlag`·누적 필드.
- 해석하지 않고 원값으로 남김 (`drop_tables.py` 머리 주석):
  - `weight_share` = 행 안의 points 비율. **확률이 아니다** (운·누적·묶음 처리 미확인).
  - 묶음은 "다음 번호 행이 있으면 이어 읽음"(외부 서술)으로 따라가되, lot 단위 분류는 `chain_unresolved`로 둔다.
  - 이어진 행의 `ItemFlag` −2 = 뜻 미확인 (`unresolved`).
  - flag 0도 `unresolved`, flag −1 = 플래그 없음.
  - `humanityLotId`·`dropType` = 원값만 남김 (출처끼리 설명이 엇갈림).
  - 보스·대화·이벤트 보상(emevd)은 나오지 않는다.
- 이 도구가 따로 구분하는 상태: `missing_row`, `unresolved_id`(lot 0), `npc_row_missing`, `no_lot_ids(all -1)`, `unknown_category` → `unsupported`,
  `chain_cap`, `chain_stops_at_other_base`. 읽기 오류는 그대로 예외로 올린다. 어느 것도 "드롭 없음"으로 바꾸지 않는다.
- **50,000,000 + lot 규칙은 쓰지 않는다.** 플래그는 행에서 읽는다.
  - 적 lot 25100100의 플래그는 51010960이다 (+lot 규칙이었다면 75100100).
  - NPC lot 6370 → 11607020.

### 검증 (오프라인)

- `python tests/drop_tables_test.py`, `python -m pytest -k drop_tables`: 통과.
  - 가짜 파라미터로 확인한 경우: 없는 lot 행, 빈 칸만 있는 lot, lot 둘, 묶음, 다른 적의 첫 lot에서 멈춤, flag −2·0, 누적, 모르는 종류,
    NpcParam 행 없음, 전부 −1, 묶음 상한, 읽기 오류가 예외로 올라감.
- 독립 바이트 파서 대조 (DSR 설치본이 있을 때만): PARAM 행 표, NpcParam +0x2C·+0x44(soulsmodding 오프셋), ItemLotParam 0x94 필드 순서.
  - Burg·Firelink 적의 NpcParam 81행과 ItemLotParam 130행이 soulstruct 값과 같았다. 압축 해제는 둘 다 soulstruct Binder.
- Firelink 보물 49/49: 이 도구가 같은 lot에서 읽은 플래그 = `msb_extract.py` 결과 (宝死体00 1020000 → 51020000 포함).
- 외부 표 대조 (HotPocketRemix `items_setup.py`, 커밋 f7cabbd 2018-08-08, 라이선스 없음 → 저장소에 복사하지 않고 비교만):
  - 적·NPC 첫 lot 행 63개 중 57개가 아이템·points·플래그 일치. 예: 25401200 88/10/2와 뒤따르는 묶음 01–03, 25100100 → 51010960.
  - 다른 6개:
    - NPC lot 6070·6080 (3건): 그쪽에 플래그 표기가 없음
    - 누적 lot 23000100·34600000: 그쪽이 단순화
    - 25700100: 그쪽은 Titanite Shard만 적음 — 우리 묶음 행 25700105
  - 누적 플래그 9164/7(23000100)은 그쪽 `CumulFlag(9164, 7, …)`와 같다.
- 전체 `python -m pytest`: 129 통과, 1 실패 `ground_test.py` (P-97, 이 변경과 무관).

### 경로의 적 (seen_runs = burg-* 기록 126개 중, 첫 lot 행)

| NpcParam (모델) | 위치 | seen | lot · 분류 | 첫 행 (points) | 행 플래그 |
|---|---|---|---|---|---|
| 254002 (c2540, 화염병 망자) | Firelink 경사로 꼭대기 (entity 1020161) | 57 | 25400200 · chain_unresolved (4행) | 빈 칸 88 · Firebomb ×1 10 · ×2 2 | −1, −2, −2, −2 |
| 254012 (c2540, 화염병 망자) | Burg 5곳 (첫 마당, 상층 4) | 67 | 25401200 · chain_unresolved | 같음 | 같음 |
| 254000 / 254001 / 255010 | Firelink 경사로 | 57–59 | 25400000 / 25400100 / 25501000 | 빈 칸 97 · 무기·방패 2/1 | −1, −2 … |
| 120100 (c1201) | Firelink 경사로 꼭대기 | 57 | 12010000 · weighted_one_row | 빈 칸 95 · Humanity 5 | −1 |
| 255002 (c2550, 석궁) | Burg 상층 1·4·8 | 77 | 25500200 · chain_unresolved (5행) | 빈 칸 98 · Light Crossbow 2 | −1, −2 … |
| 225000 (c2250, 타우로스) | Burg 탑 | 1 | 22500000 · weighted_one_row | 빈 칸 95 · Demon's Greataxe 5 | −1 |
| 251001 (c2510, 상인) | Burg 상인 자리 | 18 | 25100100 · table_single_outcome | Uchigatana 100 | 51010960 |

### 관측 후보 (제안, 미승인)

- **반복 가능한 일반 드롭 후보: 254002 Firelink 경사로 꼭대기 화염병 망자 (entity 1020161).**
  - 지금 세이브(Firelink 기준)에서 가장 가깝다. 봇이 이미 싸워 본 경사로 구간이다 (57개 실행에서 봄).
  - 첫 행에 빈 칸(points 88)이 있어, 같은 적을 여러 번 쓰러뜨리면 드롭 있음과 드롭 없음 처치를 둘 다 얻을 수 있다 — 대조군이 생긴다.
  - 행 플래그가 −1이다 → "받았음" 플래그로 구분할 수 없다. 획득 확인은 `goods_count(292)` 차이와 MoKa 눈이다.
    292(화염병)를 메모리로 읽어 본 적은 없다.
  - Burg의 254012도 같은 표다.
- **고정·일회성으로 읽히는 후보: 경로 안에 쓸 만한 것이 없다.**
  - `table_single_outcome`이면서 플래그가 있는 적은 251001(상인, 처치하면 상점을 잃음)과 264000(c2640, Blacksmith Hammer, seen 0)이다.
    둘 다 NPC를 처치해야 하고 되돌릴 수 없다 → 권하지 않는다 (MoKa 결정 사항).
  - 349101·349102(c3491, Humanity 100)는 경로 기록에 없다 (seen 0).
  - "확정"인지는 게임에서 확인하지 않았다.
- 플래그가 켜져 있다는 것은 "받았다"는 추정일 뿐이고, 지금 바닥이나 시체에 드롭이 있다는 뜻이 아니다. 둘은 다른 관측이다.

### 다음 관측 계획 (제안만 — 게임 관측은 미승인)

목표: 한 처치에서 **살아 있음 / 사망 후 미획득 / 획득 후** 세 상태를 메모리로 구분하는 값을 찾는 것. 값 하나가 바뀌는 것만으로는 성공이 아니다.

1. 정답 표시 (처치마다):
   - MoKa 눈: 시체에 빛이 있는가 없는가, 줍기를 했는가.
   - 이미 읽는 값: `goods_count(292)`, 소울, 그 적의 HP, `menu_open`.
   - 줍기는 빛이 보일 때만, A 1회.
2. 범위를 정한 읽기 (광범위 덤프 아님):
   - 그 적 ChrIns의 시작부터 0x400 바이트 (포인터는 기존 chr 목록에서, `field._liveness`의 세대 확인으로 재사용 여부 검사).
   - 대조군: 같은 범위를 살아 있는 다른 적 1개와 플레이어 ChrIns에서 같은 시각에 읽는다.
   - WorldChrMan 목록의 해당 칸 존재 여부와 포인터.
   - 시점: 마지막 공격 직전, 사망 +1·+3·+6 s, 줍기 직후 +1 s.
   - 기록량: 처치 1회에 1 KB × 3개체 × 5시점 ≈ 15 KB.
3. 후보 값의 조건 (전부 만족해야 함):
   - 드롭 있음 처치와 드롭 없음 처치에서 같은 시점에 값이 다르다.
   - 대조 적·플레이어에서는 같은 식으로 변하지 않는다.
   - START 메뉴를 한 번 열고 닫을 때와 획득 창이 떠 있을 때 변하지 않는다 (UI 혼동 배제).
   - 사망 +1·+3·+6 s에 같은 상태로 유지된다 (일반 시간 변화 배제).
   - 줍기 뒤에 바뀐다.
4. 판정 기준: 드롭 있음 처치 2회와 드롭 없음 처치 2회 이상이 모인 뒤에만 "후보"라고 부른다. 처치 수 상한은 승인 때 정한다
   (드롭 있음 2회가 몇 번 만에 나올지는 points만으로 알 수 없다).
5. 범위 밖: 0x400 안에서 아무것도 안 나오면, 다른 영역은 근거(소스·구조)를 먼저 찾고 나서 다시 승인을 받는다.
   세이브 복원 여부와 화톳불 휴식으로 다시 생성하는 방법도 승인 때 정한다.

## 현재 상태 (2026-11-01)

- dev `radar_server`: 진단 전에 중지했고 **다시 시작하지 않았다** (11-01 확인: radar 프로세스 0개).
- 게임 세이브: 진단 뒤 상태 그대로 (인간성 3 획득, 창 닫힘). 다시 복원하지 않았다.
- G4 수집: 계속 보류 (`D:/dev/g4-preserve-20261101/`, 계약 v2는 초안·미동결).

## 적 드롭 — 사망 후 탐지·루팅 결과와 상태 관리 (2026-11-01 오후)

관측 상세는 저장소 밖 `D:/dev/item-pickup-survey-20261101/itemget/RESULT-chest01-20261101.md` (chest01·02, dropsig01, 패드 루팅,
loop10 10회). 여기에는 봇 쪽 결론과 정정만 적는다.

- 사망 후 탐지 (메모리 읽기, loop10 10개 + dropsig01 1개): 모양 스캔으로 죽고 1.3–4.9 s 안에 전부 찾음, 기록 +0x68 → 떨군 적 11/11.
- 죽기 전 신호: 적 객체 앞 0x1800 바이트에서 아이템·lot 값 0건 (11개). 그 범위 밖은 안 봄.
- 루팅 (loop10, 스크래치 `testloop.py`의 ViGEm 패드 — 봇 본편 코드 아님): 주울 수 있던 8개 모두 획득 목록에 들어감(목록 근거, 가방
  화면은 안 봄). 이 중 1개(r03 Shortsword)는 창 닫기 A가 주운 것. 기록이 남아 이미 주운 드롭으로 1번 헛걸음, 다른 드롭이 먼저 주워짐 1번.
- 상태 관리: `drops.py` (`DropBook`) + `tests/drops_test.py` (오프라인 21개 검사). 이동·입력·창 처리 연결은 아직 안 함.
  "주웠음"은 획득 목록의 새 항목으로만 판정. 기록 자체에서 주웠음을 나타내는 필드는 못 찾음 (dropwatch01: 기록 0x60 바이트 그대로,
  원소 1개짜리 목록 head/tail만 0이 됨 1회, 정적 루트 없음).

### 정정 (2026-11-01)

- 시체 보물: 위 1번(宝死体00 인간성 3, flag 51020000)은 **오전에 획득을 확인했다** — 근거는 플래그 False→True와 goods_count(500)
  1→4, 창은 MoKa 눈. 오후의 **획득 목록 신호(ItemGetMenuMan +0x8)는 상자 3개와 적 드롭에서만 봤고 시체 보물에서는 기록하지 않았다.**
  채팅에서 "시체 위 보물은 줍지 않았다"고 한 것은 틀림 — 맞는 말은 "宝死体09는 안 주웠고, 宝死体00은 목록 신호 없이 플래그·개수로 확인".
- 宝箱01 Morning Star + Talisman: **표시 라벨 문제가 아니라 추출 누락.** ItemLot 1020180에는 Morning Star(802000)뿐이고, Talisman
  (1360000)은 다음 행 1020181(같은 플래그 51020180)에 있다. `msb_extract.treasure_items`는 MSB에 적힌 lot 행만 읽어서 1020181을 놓친다.
  게임은 두 행을 같이 줬다 (상자 1개 1회 관측). 이어지는 행을 같이 주는 규칙이 모든 보물에 맞는지는 확인 안 함 — 추출기는 아직 안 고침.
- m10_02_00_00 = **불의 제전(Firelink Shrine)** 쪽 맵 (missions.MAP_A, 경사로 포함; m10_01_00_00 = 불사자 마을). 보물 49개(소울 8,
  인간성 1)는 불의 제전 맵 기준이다. 채팅에서 "불사자 마을 위쪽에 49개"라고 한 것은 틀림.
- 위 "현재 상태"의 radar_server 중지는 오전 기록. 오후 실험 동안 dev radar_server와 radar watch를 다시 켰고 지금도 켜져 있다.

### 봇 흐름 연결 (2026-11-01, 오프라인만)

- `run.py clear-ramp --drops` → `Missions.clear_ramp`: 처치 전 `_drop_book()`(기준 스캔 + 적 HP) → `Field.clear` (기존 그대로) →
  살아 있으면 `Field.pick_drops(nm, book, back=RAMP_ARENA)`. `--drops` 없으면 전과 같음 (기본 꺼짐).
- `Field.pick_drops`: 가까운 묶음부터 — 주변 적 확인(`_foes_by`, 핏자국과 같은 15 m; 적이 있으면 싸우지 않고 멈춤) → `walk_to`로 드롭
  1.8 m 앞까지 (오는 적이 있으면 멈춤) → `_creep_to` 펄스 0.4×0.15 s로 0.95 m 안 → `_press_for_window` A 1회, 창 목록 변화 →
  없으면 한 펄스 더 + A 1회 → `_close_window` 닫기 A (목록이 늘면 그것도 주운 것으로 기록, 최대 3번) → `DropBook.visited` →
  다시 스캔 → 다음 묶음. 끝나면 `back`으로 `walk_to`.
- 검사: `tests/pick_drops_test.py` (가짜 세계: 1 m 안에서만 A가 주움, 주운 기록 남음, r03처럼 닫기 A가 옆 것을 주움) 12개 통과,
  `tests/drops_test.py` 21개 통과, 전체 pytest 131 통과 / 1 실패(ground_test, P-97 — 이번 변경과 무관). duel golden 변화 없음.
- 게임에서 실행한 적 없음. 펄스 세기·멈출 거리·창 대기 시간은 loop10 스크래치 값을 옮긴 것이고 `walk_to` 뒤 1.8 m 지점 정지는 검증 안 됨.

### 게임 검증 1회 — run 20261101_134754_clear-ramp (`--drops`, MoKa 승인)

- 시작 상태: loop10 뒤 캐릭터가 불사자 마을 쪽 (-40.5, -19.8, -72.4)에 있었고 HP·소울·인간성(31)이 바뀌어 있었다(봇 실행 기록 없음 —
  사람 플레이로 추정, 확인 안 함). MoKa "워프 후 진행" → 레이더 워프 불의 제전 → `clear-ramp --drops --radar`.
- 기준 스캔: 0 records (워프·휴식 뒤 이전 기록이 메모리에 없었다 — 이 1회 관측).
- 전투: 6처치 cleared, 위험 판정 깨끗 (최저 HP 59%, 큰 피격 2번 −204, 254001×2). hotspots: 걷기 문제 없음. track_report: 멈춤 1번
  2.0 s (-28.6, -49.0, 28.9) #6 던질 자리로; `드롭` 걷기 NOT REACHED (plan 4.2 m / walked 8.4 m) — 그 뒤 펄스로 다가가 주웠다.
  blind_report는 clear-ramp 실행을 표에 넣지 않는다.
- 드롭: 1개 (방어구|523000 Hollow Warrior Waistcloth). 방문 1번, 창 목록 = 그 아이템 ×1 → `taken` 1, unexpected 0. 끝난 뒤 목록 비어
  있음(읽기 전용으로 확인) = 창 닫힘. `드롭 뒤 제자리로: arrived`.
- 이 1회에서 본 것: 기준 → 처치 → 후보 1 → 접근 → A → 목록 대조 → 닫기 → 복귀가 봇 본편 경로로 끝까지 돌았다.
- 이 1회로 확인 안 된 것: 겹친 드롭·이미 주운 기록 거르기(드롭이 1개뿐이었고 기준 0), 시체 밀림·멈춘 거리(로그에 안 남김 — 기록 추가
  필요), 적이 가까울 때 멈춤, 주운 아이템이 가방에 있는지(화면 안 봄).

### 레이더 드롭 표시 (2026-11-01, MoKa "표시 만들기")

- 봇 실행 중 `Field.pick_drops`가 `mv.show_drops`에 DropBook 상태(위치·아이템 코드·상태·지금 가는 묶음)를 둔다(보는 용도만) →
  `radar.intent_dict`가 스냅샷 패킷에 `drops`로 보냄(마지막 갱신 뒤 30 s까지) → `radar_server`가 `*-drops.json`에서 이름을 붙임
  (`drop_names`) → `radar.html` 범례 (DropBook 상태 = 판정 근거):
  - 채운 원 = `pending`: **미획득 후보 / 획득 확인 없음.** 땅에 있다는 증거가 아니다 (주운 뒤에도 기록이 남는다).
  - 빈 원 = `taken`: 획득 창 목록에 그 아이템이 새로 생겼고, 그 자리 후보 중 그 아이템이 이것 하나뿐이었다.
  - × = `failed` (방문 3번 다 씀) 또는 `gone` (다시 스캔해도 기록 없음, 또는 바닥 없음·25 m 밖·높이차 6 m 넘음).
  - 바깥 고리 = 지금 가는 묶음. Doing 칸 "Drops: unconfirmed · picked (window) · gave up / gone · going to …".
  (11-01 처음 쓴 "채운 원 = 아직 땅에 있음"은 틀린 설명 — MoKa 정정.)
- 확인: `tests/radar_test.py` 드롭 4개 검사 통과, `--demo`(가짜 드롭 3개, 포트 47810/47811)를 브라우저로 열어 그림·Doing 줄을 봄.
  실제 봇 실행에서 드롭이 레이더에 뜨는 것은 아직 안 봄. `radar.py watch`(봇 없이 감시)는 드롭을 보내지 않는다 (스캔 1.5 s).
- 기존 문제 (이번 변경과 무관): 페이지 첫 로드 때 캔버스 크기 0이면 `draw`가 음수 반지름으로 한 번 오류를 낸다.

### 두 번째 시도 — run 20261101_140618_clear-ramp (`--drops`, MoKa "이 상태로 한번 더 트라이")

- 워프 없이 경사로 아래 평지에서 시작 (clear-ramp가 불의 제전 화톳불로 걸어가 휴식). 기준 스캔 0 records — 바로 전 목록 조회 때 메모리에
  있던 Hollow Warrior Waistcloth 기록(-23.9, -49.6, 16.2)이 휴식 뒤 사라짐 (휴식·워프 뒤 기록 0: 2회째 관측).
- 전투 cleared, 위험 판정 깨끗 (최저 HP 97%, 큰 피격 0). hotspots 걷기 문제 없음, track_report 멈춤 0.
- 드롭 0개 → `pick_drops` 방문 0, 줍기 없음, `드롭 뒤 제자리로: arrived`. 이 실행은 드롭 줍기 판정 보류 (상황이 안 나옴).

### 세 번 더 — runs 20261101_141004 · 141237 · 141458 (`clear-ramp --drops`, MoKa "3번 더")

| run | 처치 | 위험 판정 | 기준 | 드롭 | 방문 | 창 목록 → 판정 |
|---|---|---|---|---|---|---|
| 141004 | 7 | 깨끗 (최저 84%) | 0 | Firebomb ×1 (goods 292) | 1 | 같은 아이템 ×1 → taken |
| 141237 | 6 | 깨끗 (최저 84%) | 0 | Titanite Shard ×1 (goods 1000) | 1 | 같은 아이템 ×1 → taken |
| 141458 | 7 | 깨끗 (최저 100%) | 0 | Hollow Warrior Waistcloth ×1 (armor 523000) | 1 | 같은 아이템 ×1 → taken |

- 세 번 모두 끝난 뒤 `드롭 뒤 제자리로: arrived`, unexpected 0. hotspots 걷기 문제 없음, track_report 멈춤 0 (141458).
- 봇 본편 경로 누적 (`--drops` 5회): 드롭 4개 / 4개 줍기 판정 (창 목록 근거), 각 방문 1번. 모두 한 실행에 드롭 1개 — 겹친 드롭·이미 주운
  기록 거르기(기준 0이라 상황 없음)·적 근처 멈춤은 게임에서 아직 안 나옴. 가방 화면·시체 밀림 거리는 안 봄(로그에 없음).

## 성과 기록 (MoKa 지정 문구, 2026-11-01)

**clear-ramp에서 단일 적 드롭 자동 수집을 본편으로 4회 확인.** (`clear-ramp --drops` 5회: 134754 · 141004 · 141237 · 141458 =
드롭 1개 → 방문 1번 → 획득 창 목록 일치, 140618 = 드롭 없음.) 전체 아이템 수집·예외 처리(겹친 드롭, 잔존 기록 거르기, 적 근처
멈춤, 접근 실패)는 게임에서 검증되지 않았다 — 오프라인 가짜 세계 검사만. 고정 보물·상자·다른 지역은 범위 밖.

- 실행 기록 보존 (`sample.py`, 원본 `data/runs/` 그대로 — sha256 비교 일치):
  | 본편 실행 (원본 `data/runs/<id>.log`) | 보존 | 드롭 |
  |---|---|---|
  | 20261101_134754_clear-ramp | `data/samples/20261101_134754_clear-ramp_drops-run1of5-got1.*` | Hollow Warrior Waistcloth |
  | 20261101_140618_clear-ramp | `…_140618_clear-ramp_drops-run2of5-nodrop.*` | 없음 |
  | 20261101_141004_clear-ramp | `…_141004_clear-ramp_drops-run3of5-got1.*` | Firebomb |
  | 20261101_141237_clear-ramp | `…_141237_clear-ramp_drops-run4of5-got1.*` | Titanite Shard |
  | 20261101_141458_clear-ramp | `…_141458_clear-ramp_drops-run5of5-got1.*` | Hollow Warrior Waistcloth |
  각각 .txt(로그) · .track.jsonl · .settings.json · .jsonl(이벤트). `.diff`·`.hits.jsonl`은 sample.py 규칙대로 data/runs에만.
  `data/runs/<id>.stdout.txt`는 Claude가 run.py 표준 출력을 따로 저장한 사본(원본 로그 아님).
- 실험 코드 loop10과 구분: 스크래치 `testloop.py`가 `run.py clear-ramp`(본편, `--drops` 없음)를 부르고 줍기는 **실험 코드**의 패드가 함
  — 20261101_121152 · 121423 · 121653 · 122008 · 122237 · 122501 · 122717 · 122931 · 123216 · 123432 (+ 그 전 113532 · 115413).
  이 실행들은 sample.py로 보존하지 않았다(이번 요청 범위 밖, data/runs에 원본 있음). 이 실행들의 줍기 결과는 본편 성과에 넣지 않는다.

## 정정 (2026-11-01 저녁, MoKa)

- 인간성의 발견력 증가는 **10에서 상한**. "20 이상이면 발견 확률이 많이 오른다"는 틀림 (채팅·RESULT 파일·Claude 메모리에 있던 이유를
  정정; 이 문서에는 그 문장이 없었다). 세이브의 인간성(31)은 바꾸지 않았다.
- 레이더 채운 원 = "미획득 후보 / 획득 확인 없음" (위 레이더 절 범례 고침).

## DropBook 기준 정책 (정리)

- 기준 = 처치 전 메모리에 있던 기록 전부를 뺀다. **주운 뒤 남은 기록뿐 아니라 실제로 땅에 남은 드롭도 빠질 수 있다.**
- `pass_ramp` 재시도에서 첫 회에 못 주운 드롭이 빠지는 것: **현재 의도된 제한** (버그로 고치지 않음). 근거 — 첫 회 `pick_drops`가 이미
  시도함, 재시도는 퀵 종료(P-25) 뒤에만, 휴식·워프 뒤 기록이 사라진 관측 3회. 퀵 종료 뒤 드롭이 땅에 남는지는 확인 안 함 — 남는다면
  그때 개선 대상(첫 회 DropBook을 재시도에 넘기는 방식)으로 다시 본다.

## 일반 진행에 연결 — 공통 드롭 줍기 루틴 (2026-11-01 밤, 오프라인만)

MoKa: "아이템 수집을 clear-ramp 전용 옵션이 아니라, 일반 진행 중 자동으로 수행하는 공통 루틴으로 연결해줘." 최소 코드·문서
수정과 오프라인 검사만 승인됨 — **게임에서는 이 연결을 한 번도 돌리지 않았다.** 본편 확인은 여전히 위의 clear-ramp 단일 드롭 4회뿐이다.

**구조.** `souls/loot.py` `Loot`를 `Field.loot`으로 하나 둔다. DropBook은 실행 하나에 하나다.
- 기준은 `run.py` 시작 때(처치 전) 잡고, 이때 다시 잡는다: `Field.rest_at` 휴식 · `Field.wait_respawn` 부활(죽어 있었을 때만) ·
  `passage_drill` 워프 · 퀵 종료(`esc.gen`가 바뀌면 다음 collect가 기준을 새로 잡고 아무것도 줍지 않음).
- 미션은 자기 싸움이 끝난 멈춤 지점에서 `Missions._loot(nm, tag, back)` → `Loot.collect`를 부른다.
  - collect 안에서 기존 `Field.pick_drops`가 걸어가서 줍는다.
  - 드롭 근처에 적이 있으면 `Field._chaser`로 판단한다(걷기의 "따라온 놈"과 같은 판단).
    우리에게 오는 적이면 `Field.fight(wait_far=True, limit=COMING_LIMIT)`로 싸우고 다시 확인한다(최대 `LOOT_FIGHTS`=2).
    오지 않는 적(잠든 적, 멀리 있는 적)은 깨우지 않고 그 드롭을 보류한다(`DropBook.held`). 2번 보류되면 포기한다(`MAX_HOLDS`).
  - 접근 중 걷기(`walk_to` done)나 마지막 스틱 펄스(`_creep_to` stop) 중에 적이 오면 A 전에 멈추고 같은 판단으로 돌아간다.
  - 끝나면 `back`이 있는 곳(경사로 = RAMP_ARENA, 검증된 그대로)만 그 자리로 간다.
    나머지는 제자리에서 다음 단계가 자기 길을 다시 계산한다(`careful_walk_to` · `walk_to` · `to_merchant`의 nearest point 재탐색).
- 재진입 막음: collect 안에서 다시 collect를 부르면 바로 `busy`.
- 화톳불 6 m 안 드롭(A가 앉기 = 적 부활)과 살아 있는 비적대 캐릭터 3 m 안 드롭(A가 말 걸기)은 후보가 아니다.

**켜고 끄기.** `run.py` `LOOT_CMDS`의 명령에서는 기본으로 켠다. `--no-loot`로 끄면 collect가 아무것도 안 한다(스캔·걷기·입력 없음, 예전 동작).
`--drops`는 남겨 두지만 효과가 없다(기본값이 됨). `Missions.drops`와 `_drop_book`은 없앴다.

**실제 연결한 호출 경로**

| 멈춤 지점 | 부르는 명령 | back |
|---|---|---|
| `Missions.clear_ramp` 끝 (pass_ramp · burg_segment 1 · burg_bonfire · burg_loop) | clear-ramp, burg-bonfire, burg-loop | RAMP_ARENA |
| `Missions.clear_burg_town` 끝 (to_merchant의 town 단계) | clear-burg-town, merchant, burg-bonfire (--seg 3·4) | 없음 → to_merchant가 nearest point 재탐색 |
| `Missions.upper_zone(n)` 끝, n ≠ 8 | burg-upper, burg-altar (구역 1–7), pick-blood (구역 1) | 없음 → 다음 구역 `careful_walk_to(safe)` |
| `Missions.hunt_one` 싸움 뒤 | hunt-one | 없음 → 원래대로 화톳불로 걸어감 |

**연결하지 않은 경로**
- 긴 걷기 도중 "따라온 놈" 싸움(passage · merchant 걷기 · to_firelink): 그 드롭은 다음 멈춤 지점에서 25 m 안이면 줍는다.
- 구역 8(`LOOT_SKIP_ZONES`): 탑 위 좁은 턱(P-47)이고 바로 앞이 타우로스 안개벽이다.
- 그 밖: `to_altar_bridge` · altar · taurus(보스) · asylum · parish · firebomb-probe · light-burg · quit-test · passage-drill.

**지원 대상.**
- 지원: 적이 죽은 뒤 생긴 드롭 기록.
- 미지원(찾지도 표시하지도 않음, `loot.NOT_SUPPORTED`):
  - 고정 보물(시체 위·땅): 보상 추출 연쇄 lot 누락, 봇 흐름에서 획득 확인 안 해 봄
  - 보물 상자: 여는 입력·확인 단계 없음
- 미믹 · 숨은 보물 · 잠긴 문 · 이벤트 전제 대상은 고정 보물·상자를 다루지 않으므로 지금은 해당 없음.
- 아이템을 버리거나 소모품을 쓰는 단계는 없다.

**기준 정책 변화.**
- 책이 실행 하나에 하나라 같은 실행 안의 pass_ramp 재시도는 첫 회에 못 주운 드롭을 계속 후보로 본다(이전 제한 해소, 오프라인만).
- 기준을 다시 잡는 사건(휴식 · 부활 · 워프 · 퀵 종료) 앞의 드롭은 빠진다.
- 옛 기록 오인 방지는 그대로다: 기준 제외 + (주소 · 아이템 · 개수 · 주인) 식별 + 기준과 같은 바이트면 1회만.

**오프라인 검사** `tests/loot_test.py` (가짜 월드, 25개 확인):
- 적 먼저 처리, 전투 뒤 재개
- 접근 걷기 중 · 펄스 중 적 → A 전에 중단
- 잠든 적 → 보류, 2회 뒤 포기, 그 뒤로 멈추지 않음
- 같은 실행 다음 멈춤에서 보류 드롭 회수
- 싸움 실패 → 보류
- r03 겹침 3개 · 남은 기록 재방문 없음
- 휴식 · 부활 · 살아 있을 때 wait_respawn · 퀵 종료 초기화
- 끔
- 재진입
- 화톳불 · NPC 제외
- hunt_one · clear_ramp · clear_burg_town · upper_zone(7) 호출 순서와 결과 유지

`pick_drops_test` 12와 `drops_test` 21도 그대로 통과한다. 게임 검증이 아니다.

### 공통 루틴 게임 확인 (2026-11-01 밤, MoKa "G1·G2 승인" · "지금 위치에서 바로 진행" · "보스 있는데 까지 쭉" · "죽어도 거기서 끝내")

| run | 명령 | 드롭 줍기 결과 | 끝 |
|---|---|---|---|
| `20261101_150628_clear-ramp` (G1) | `clear-ramp --radar` (`--drops` 없이, 기본 켬) | 경사로: 방문 1, 획득 1 (Cracked Round Shield 0x157430, 획득 창 증거), 경사로 싸움 자리로 돌아감 arrived | cleared |
| `20261101_151142_burg-bonfire` | `burg-bonfire --seg 2-6` (불의 제전 경사로에서 휴식 없이) | 성벽 마을 끝 3번 불림 (town1 · town2 · merchant) — 3번 다 방문 0 | lit, 성벽 마을 화톳불로 귀환 지점 바뀜 |
| `20261101_151756_burg-upper` (G2 확대) | `burg-upper --seg 1-8` | 구역 1 끝 방문 0 | 구역 2 낙하 사망(P-98), 부활 직후 봇 멈춤 |

- 확인된 것:
  - 기본 켬 상태에서 경사로 단일 드롭 줍기가 예전과 같게 돈다(본편 5회째).
  - 성벽 마을 끝과 구역 1 끝에서 collect가 불리고, 방문 0이면 결과를 바꾸지 않고 다음 단계로 이어진다.
  - 휴식(rest_at)·부활 뒤 기준을 다시 잡는다(로그 "드롭 기준 (rest)" · "(respawn)").
- 확인 안 된 것:
  - 마을 #1–6과 구역 1에서 드롭 기록이 생겼는지. 방문 0이 "드롭 없음"인지 "후보에서 빠짐(gone)"인지 로그로 가를 수 없다
    (gone 이유를 찍지 않음).
  - 경사로 밖에서 실제로 줍기, 줍는 중 싸움, 보류, 구역 2–7 끝.
- 새로 본 빈틈: `light_burg_bonfire`의 앉기는 `Field.rest_at`을 거치지 않아 드롭 기준을 다시 잡지 않는다(이 run은 거기서 끝나 영향 없음).
- 길에 있던 Soul of a Lost Undead 등은 고정 보물이라 지원 대상이 아니다(줍지 않음이 의도된 동작).

**다음 테스트 (MoKa 11-01 지정, 미승인 — 코드 없음)**: 세이브를 복원한 뒤 주변 고정 보물도 줍는다. MoKa가 물은 레벨업은 이미
`run.py --level-up STAT`(levelup.py, 쉴 때마다)로 있다. 게임 기록은 10-31 로그 1건(SL 7→8, VIT 15→16)뿐이다. 인간성이 있으면
화톳불 메뉴 순서가 달라질 위험이 있다. 그 전에 정할 것: 고정 보물 코드 범위(플래그로 미획득 판단 · 접근 · A · 획득 창 확인 ·
연쇄 lot), 복원할 세이브, 올릴 능력치.

### 복원 세이브로 다시 (2026-11-01 밤, MoKa "불의 제사장 세이브로 복원하고 원래 테스트 다시")
- 복원: `savepoint.py restore backup-20260929-080235-…-firelink` (e2da9f35). 복원 전 상태는 `backup-20261101-152837-before-restore-…`(100484d9)에
  백업함. 복원 뒤 값: HP 616/616, 에스트 3, 소울 2280, 인간성 0 — 기억해 둔 기준값과 같음.
- `152901_clear-ramp`: 투척 나이프가 없어 시작 검사에서 멈춤(게임 입력 없음). → `152928_clear-ramp --no-lure`: cleared,
  줍기 방문 0(최저 HP 28%).
- `153157_burg-bonfire --seg 2-6 --no-lure`: town1 끝 줍기에서 드롭 1개를 **보류** — 250000 둘이 13·15 m에 있고 오지 않음.
  걷기·입력 없이 다음 단계로 감(보류 경로가 게임에서 처음 돎). town2 #4에서 사망(P-99) → MoKa 지시대로 끝냄. G2(burg-upper)는 못 감.
- 레벨업(`--level-up`)은 넣지 않았다 — 올릴 능력치가 정해지지 않음.

### 복원 세이브 + VIT (2026-11-01 밤, MoKa "VIT" · "죽은 자국도 가능하면 회수")
| run | 드롭 줍기 | 레벨업 | 끝 |
|---|---|---|---|
| `153642_clear-ramp --no-lure --level-up VIT` | 방문 0 | 불의 제전 휴식: SL 4 → 7 (VIT 12 → 15; 다음 run 첫 줄 기준, 레벨업 줄은 이 로그에 없음) | cleared |
| `153940_burg-bonfire --seg 2-6` | town1 끝 **보류** 1 (근처 적이 오지 않음), town2 · merchant 방문 0 | 성벽 마을 화톳불: SL 7 → 8, VIT 15 → 16, 소울 1193 → 418 | lit |
| `154533_burg-upper --seg 1-8` | **구역 1 끝: 방문 1, 획득 1 (Hollow Soldier Armor 0x100756e8, 획득 창 증거)** · 구역 2–4 방문 0 | 쉴 소울 모자람 | 구역 5 사망(P-100), 핏자국 1258 소울은 정책상 무시 |

- 경사로 밖에서 처음으로 공통 루틴이 실제로 주웠다(구역 1 끝, 한 번). 보류도 두 번째로 일어났다. 줍는 중 싸움은 아직 한 번도 없음.

## 2026-11-01 저녁: 구역 5 문 → 보물 상자 宝箱01 황금송진 (MoKa "열고, 황금송진 확보 해봐", 한 번, 봇 흐름 밖)
- 스크래치 스크립트(가상 패드 + nav.goto, 봇 명령 아님)로 손으로 시킨 일. MoKa가 주변 적을 먼저 정리함.
- 문 1011310 (20.22, -5.72, -104.2): 1.0 m 앞에서 화면 "Ⓐ: Open" (닫힘·안 잠김, 플래그 11010140 False 그대로) → A 1번에 열림.
  첫 시도는 게임 창이 앞에 없어(Perplexity) 패드 입력이 안 먹음 — 게임 창을 앞으로 가져온 뒤 됨.
- 상자 宝箱01 (o0110_0001, id 1011671, (31.34, -7.45, -111.07), lot 1010460, 플래그 51010460):
  - 2.4 m에서 A → 아무 일 없음. 같은 쪽에서 0.77 m까지 붙어 상자를 보고 A → 뚜껑 열림, 화면 "Ⓐ: Pillage treasure chest" (개수·플래그 그대로).
  - 두 번째 A → Gold Pine Resin(311) 0 → 3, 플래그 51010460 False → True, 아이템 창 [(0x40000137, 3)]. 세 번째 A로 창 닫힘(창 목록 비어짐).
  - 그래서 상자 = A 두 번(열기 → 꺼내기) + 창 닫기 A, 앞면에서 ~1 m 안. 봇 흐름에는 아직 없음 (loot.NOT_SUPPORTED "chest" 그대로).

## 2026-11-01 저녁: 문 열림/닫힘 = ObjAct 상태 플래그 (MoKa "문이 더 중요해")
- 성벽 마을 문마다 MSB ObjAct에 플래그 둘: `obj_act_entity_id`(11010xxx, "한 번 열었음" 기록 — 닫아도 True로 남음)와
  `obj_act_flag`(61010xxx, **지금 상태** — True 열림 / False 닫힘).
- 구역 5 문 1011310 (61010510): 닫힘 "Ⓐ: Open" False → A → True, 바깥 0.8 m에 "Ⓐ: Close"(안쪽 0.9 m에선 안내 없음) → A → False
  ("Ⓐ: Open") → A → True. MoKa도 손으로 열고 닫아 봄 — 닫히는 문.
- 화톳불 근처 문 1011312 (61010512): 1.07 m에서 "Ⓐ: Open" + False → A → True. 안쪽 宝死体24 Wooden Shield(-10.9, -13.3, -73.55)
  A 한 번: 플래그 51010130 False → True, 창 [(1401000, 1)], 창 닫기 A 1번.
- 11-01 저녁 스캔(성벽 마을 문 11개): 61010510·61010518 True, 나머지 False.
- 봇 반영(souls/field.py DOOR_FLAGS 둘째 값, Field.door_open): 막힌 문이 True(열림)면 A 안 누름(누르면 닫힘), False·못 읽음이면 A 1번.
  오프라인 tests/field_fog_test.py만 — 봇 흐름에서 문 앞에 막힌 일은 아직 없음. 적이 문을 닫을 때(10-06j) 61…이 False가 되는지 미측정.
- 같은 날 실수: computer-use open_application으로 게임 창을 앞으로 가져오려다 게임 exe 5개가 더 떠 "Failed to initialize Steam"
  창이 남. 여분 프로세스 종료, 원래 게임만 남김. 게임 창 포커스는 MoKa에게 부탁.
