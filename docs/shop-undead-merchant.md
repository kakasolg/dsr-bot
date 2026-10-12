# 망자 상인(성벽 마을) 상점 메뉴 기록

2026-10-12 [win], [MoKa] "상인 한테 가서 화염병, 투척나이프 구매하는데, A누를 때 마다 스크린샷 찍어서 확인 하면서 테스트 하면 어떨까?"
버튼 하나 → 기다림 → 스크린샷 (`pad_step.py`). 스크린샷: `data/shop/20261012/NN_<버튼>_<무엇>.jpg` (960 px로 줄임).
[cloud]의 `shop` 구매 루틴과 NPC 상호작용 모듈의 근거 기록.

## 결과

| | 전 | 후 | 메모리 |
|---|---|---|---|
| 소울 | 4042 | 2742 | `tm.souls()` |
| 투척 나이프 (Throwing Knife) | 0 | **30** (−300) | goods **290** — 확인 |
| 화염병 (Firebomb) | 47 | **67** (−1000) | goods **292** — 확인 (상점 "Held 47" = 메모리 47) |

세이브 백업: `backup-20261012-034844-merchant-bought-knife30-firebomb67` (상인 앞에서 불러와짐, 귀환 지점 불의 제전).

## 상인

- NPC **251001**, (−38.02, −19.80, −66.50), 상자 사이에 앉아 있음 (`places.py`의 "상인" (−39.17, −19.8, −67.81)과 1.5 m 차이)
- **말 걸기 표시는 바라봐야 뜸**: 1.2 m까지 가도 몸이 딴 데를 보면 안 뜸 (02). 1.7 m에서 몸을 상인 쪽 0°로 돌리니 `E:Talk` (03).
  표시는 마지막 입력 장치 기준 — 키보드 E로 보여도 패드 **A**로 됨.
- 가는 길: 불의 제전 → `run.py burg-bonfire --seg 1-5 --no-lure` (경사로 → 비밀 통로 → 마을 #1~#6 → 상인), 367 s, 사망 0 (`20261012_033810_burg-bonfire`).
  성벽 마을 화톳불 쪽에서는 마을 정리 순서가 안 맞아 2번 사망 (#6 방패병과 다른 적이 같이 붙음) — 아래 '남은 것'.

## 순서 (스크린샷 번호)

| # | 누름 | 기다림 | 화면 | `menu_open` |
|---|---|---|---|---|
| 03 | — | — | `E:Talk` 표시 (바라봄, 1.7 m) | False |
| 04 | A | 1.5 s | 인사 대사 ("Still keeping your marbles all together?") | **True** (대사 중에도) |
| 05 | — | +2 s | 메뉴: **Purchase Item** (선택됨) / Talk / Leave | True |
| 06 | A | 1.2 s | 구매 목록 — 1행 Repair Powder 500 · 2행 **Throwing Knife 10** · 3행 **Firebomb 50** · 4행 Lloyd's Talisman 500 (가격 + Held) | True |
| 07 | DOWN | 0.6 s | 커서 2행 Throwing Knife | True |
| 08 | A | 0.8 s | 수량 창 "Purchase for 10 souls?" 수량 **01**, **기본 선택 CANCEL** | True |
| 09 | RIGHT | 0.5 s | 선택이 **OK로** (LEFT/RIGHT = OK↔CANCEL, 수량은 그대로) | True |
| 10 | UP | 0.5 s | 수량 02, "20 souls" — **UP = +1** | True |
| 11 | UP ×28 | 0.25 s 간격 | 수량 30, "300 souls", OK 선택 그대로 | True |
| 12 | A | 1.0 s | 구매됨: 목록으로 돌아옴, Held 30, 소울 3742 | True |
| 13 | DOWN | 0.5 s | 커서 3행 Firebomb | True |
| 14 | A | 0.8 s | 수량 창 (다시 CANCEL 기본) | True |
| 15 | UP ×19 | 0.25 s 간격 | 수량 20 | True |
| 16 | RIGHT | 0.5 s | OK 선택, "1000 souls" | True |
| 17 | A | 1.0 s | 구매됨: Held 67, 소울 2742 | True |
| 18 | B | 0.8 s | 메뉴로 (Purchase Item / Talk / Leave) | True |
| 19 | B | 1.5 s | 대화 끝 대사 ("Ah, thank you, very much.") → 게임으로 | True → 곧 False |

## 루틴에 넣을 것

- 확인은 **화면보다 메모리로**: 구매 A 뒤 `goods_count(id)`가 수량만큼 늘고 `souls()`가 가격 × 수량만큼 줄면 성공. 둘 다 그대로면 실패 (CANCEL에 있었거나 입력이 씹힘).
- 수량 창 기본값이 **CANCEL** — OK로 옮기지 않고 A를 누르면 아무것도 안 삼. RIGHT 한 번으로 OK (위 09). 수량을 먼저 맞춘 뒤 옮겨도 됨 (15 → 16).
- 수량은 UP 한 번에 +1 (10 → 11은 0.25 s 간격 28번 그대로 들어감). DOWN, 최댓값, 소울이 모자랄 때는 안 해 봄.
- 목록 순서·가격은 이 상인 고정 (DSR 망자 상인 남): 나이프 2행, 화염병 3행 — 첫 행에서 DOWN 1번 / 2번.
- 대사가 나오는 동안에도 `menu_open`이 True — "메뉴가 열렸다"만으론 목록인지 대사인지 모름. 인사 뒤 메뉴가 뜨기까지 ~2 s 기다림.
- 나갈 때: B (목록 → 메뉴) → B (메뉴 → 대사 → 게임). 'Leave' 행을 안 골라도 됨.

## 남은 것

- 소울 모자랄 때·최대 수량 (DOWN으로 넘어가는지)
- 성벽 마을 화톳불 → 상인 길 (지금은 불의 제전에서 오는 순서만 안전)
- 활 (다른 상인 탭?) — 이 목록 화면의 위쪽 아이콘 줄(소모품 · 무기 · 열쇠 · …)은 안 넘겨 봄

## [cloud] 요청: `shop` 구매 루틴 (2026-10-12 [win] → [cloud], MoKa 승인)

목표: 봇이 사람 손 없이 **불의 제전 → 상인 → 구매**까지. 길은 이미 됨 (`burg-bonfire --seg 1-5`), 빠진 건 상인 앞부터.

1. `souls/shop.py` (NPC 상호작용 모듈의 첫 사례 — ROADMAP "NPC interaction"):
   - `buy(items)` — `items` = `[(goods_id, 개수), …]`, 예: `[(290, 30), (292, 20)]`. 행 번호·가격은 이 상인 표로 (290 → 2행 10, 292 → 3행 50; 1행 수리 분말 280 500, 4행 로이드 부적 500)
   - 다가가기: NPC **251001**을 스냅숏에서 찾아 1.7 m까지, 몸을 0° (±12°)로 (`Moves.face`) — 바라보지 않으면 말 걸기가 안 뜸
   - A → **~2 s** 기다림 (인사 대사; 그동안도 `menu_open` True) → A (Purchase Item) → 목록
   - 품목마다: 목록 맨 위에서 DOWN ×(행−1) → A → UP ×(개수−1) (0.25 s 간격) → **RIGHT** (기본 CANCEL → OK) → A
     (주의: 한 품목을 산 뒤 커서는 그 행에 남음 — 06 → 12 → 13. 다음 품목은 지금 행에서의 차이만큼)
   - 확인은 **메모리로**: `goods_count(id)`가 개수만큼 늘고 `souls()`가 가격×개수만큼 줄었나. 아니면 그 품목 한 번 다시, 두 번째도 아니면 멈춤 ('shop_fail')
   - 소울 모자라면 살 수 있는 만큼으로 줄임 (화면에서 안 해 봄 — 모자랄 때 동작은 미확인)
   - 나가기: B → B, `menu_open` False 될 때까지 (최대 5 s)
   - 이벤트 `shop`: 품목, 개수, 소울 전후, 결과
2. `run.py merchant-buy` (또는 `burg-bonfire --seg 1-5` 끝에 `--buy 290:30,292:20`): 상인 도착 뒤 `shop.buy`
3. 오프라인 테스트: 버튼 순서 (가짜 패드) · 확인 실패 시 재시도 1번 · CANCEL 기본값 처리 · 커서가 남는 것
4. [win] 게임 확인: 세이브 `backup-20261012-034844-merchant-bought-knife30-firebomb67` (상인 앞, 소울 2742)에서
   `savepoint.py restore` → 루틴만 3번 → 그다음 불의 제전부터 끝까지 1번. 버튼마다 `pad_step.py`처럼 스크린샷을 남길지는 [cloud]가 정함

## [cloud] 구현 (2026-10-12) — `souls/shop.py`

- `Shop(mv, nm, log, events, shoot=None, walk_to=None).buy([(goods, 개수), …])` — 위 순서 그대로. 행·가격 표 `shop.UNDEAD_MERCHANT`
  (280 → 1행 500, 290 → 2행 10, 292 → 3행 50; 4행 로이드 부적은 id 기록 없음이라 빠짐).
- 다가가기: NPC 251001이 4 m보다 멀면 `Field.walk_to`, 그다음 짧은 걸음으로 1.7 m 안, `Moves.aim`(걷지 않고 짧은 탭으로 돌기)으로 12° 안.
  말 걸기 A 뒤 1.5 s 안에 `menu_open`이 안 켜지면 다시 조준해 한 번 더, 그래도 안 되면 `no_talk`.
- 품목마다: 지금 커서 행에서 차이만큼 DOWN/UP → A → UP ×(개수−1) 0.25 s 간격 → RIGHT → A → 메모리 확인 (1.5 s 동안).
  개수·소울 둘 다 그대로면: B B로 나가고 다시 말 걸어(커서 1행) 그 품목 한 번 더, 두 번째도 그대로면 `shop_fail`로 멈춤.
  소울이 모자라면 살 수 있는 만큼(0이면 `no_souls`, 버튼 안 누름). 이벤트 `shop` (개수·소울 전후, tries, result).
- 실행: `python run.py merchant-buy --buy 290:30,292:20` (상인 앞에서) ·
  `python run.py burg-bonfire --seg 1-5 --no-lure --buy 290:30,292:20` (5 상인 도착 뒤; `--seg 1-6`이면 산 뒤 6으로).
  `--shop-shots`: 단계마다 스크린샷 `data/shop/<날짜>/<nn>_bot_<단계>.jpg` (pad_step.py와 같은 960 px JPEG) — 첫 게임 확인 때 켜는 걸 권함.
- 오프라인: `tests/shop_test.py` — 가짜 상인(인사 2 s, 목록, CANCEL 기본, 커서 유지, 입력 씹힘)에서 기록 그대로 사면
  4042 → 2742 소울·나이프 30·화염병 67, 버튼 순서가 위 표와 같음; RIGHT가 씹히면 다시 말 걸어 두 번째에 삼; 두 번 다 씹히면 `shop_fail`;
  소울 300 → 화염병 6개; 목록에 없는 id → `not_sold`; 말 걸기 안 됨 → `no_talk`.
- 미확인 (게임): 목록 UP(위로) 이동 (지금 표 순서로는 안 씀), 최대 수량, 소울 모자랄 때 화면, 대사 중 A를 누르면 넘어가는지.


## [win] 게임 확인 1 (`dc4c0a0`, 2026-10-12): shop_fail — 인사가 여러 줄, 대사 중 A = 다음 줄

`20261012_041218_merchant-buy`, 상인 앞 세이브, `--buy 290:30,292:20 --shop-shots`. 다가가기·바라보기는 됨 (1.88 m, 0°).
루틴 스크린샷 `data/shop/20261012/20~27_bot_*.jpg`:

| 루틴 단계 | 실제 화면 |
|---|---|
| 20 after-greeting (A 뒤 GREET_S 2 s) | 인사 대사 아직 ("Still keeping your marbles all together?") |
| 21 purchase-item (A) | A가 **다음 대사로 넘김** — "Then, go ahead, don't be a nitwit." |
| 22 to-290 (DOWN) | "Never hurts to splurge when your days are numbered!" |
| 23 select-290 (A) | "Nee hee hee hee hee!" |
| 24 qty-30 (UP ×29) | 이제야 처음 메뉴 (Purchase Item / Talk / Leave) |
| 25 ok (RIGHT) | 처음 메뉴 그대로 |
| 26 buy-290 (A) | 이 A로 **구매 목록**이 열림 (커서 1행) |
| 27 close-shop | 처음 메뉴 |

→ 개수·소울 그대로 → 나갔다 다시 말 걸기 → 두 번째도 그대로 → `shop_fail`. 처음 기록(04 → 05)은 인사 한 줄 + 3.5 s 기다림이라 우연히 맞았음.
대사 중에도 `menu_open` True라 메모리로는 구분 못 함. 제안: 고정 시간 대신 **화면 확인 뒤 다음 입력** — `quitout._is_screen`처럼
처음 메뉴(왼쪽 패널 · 주황 선택 막대), 구매 목록("Purchase" 제목), 수량 창(가운데 상자) 기준 이미지. 대사가 남아 있으면 A로 넘기되
처음 메뉴가 보일 때까지만.
