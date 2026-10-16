# TAE verification — c2540 first

MoKa 2026-10-16: REA 추가 조사보다 TAE 실제 파일 검증 우선. judge 일치율만으로 레이아웃·필드 의미가 검증됐다고 하지 않는다.
c2540 애니메이션 2–3개 DSAnimStudio 대조는 **필수**. 결과는 세 단계로 나눠 적는다. 통과하면 c2540 하나로 AI Lua와 연결해 작은 전투 시뮬레이터 첫 수직 슬라이스.

**이름**: TAE 이벤트의 시간 = **공격 이벤트 활성 구간** (`active_start` · `active_end`, 그 공격 behavior가 실행되는 동안).
플레이어 HP가 줄어든 시각 = **적중 시각**. 둘은 따로 기록하고 섞지 않는다.

도구: `tae_extract.py` (파싱, `--rebuild`는 게임 없이 다시 계산) · `tae_verify.py` (sheet · blame · probe · timing).

## 상태

| 단계 | 뜻 | c2540 | 전체 |
|---|---|---|---|
| 1 파싱 성공 | 파일을 읽었고 개수 · judge 분자/분모가 나옴 | **통과** — 애니 170 (빌림 13), attack 27 · bullet 1 · common 28, 그 밖 2234; judge attack 27/27 · bullet 1/1 | **통과** — 66/66 모델, 실패 0; judge 1241/1245 |
| 2 독립 도구 대조 | DSAnimStudio에서 같은 애니의 id · 종류 · 시작/끝 · 숫자가 같음 | **type 1 통과** (재대조 10-16, 3000 · 3003 · 3010, 차이 0) — type 2 · 5는 대조 안 됨 | — |
| 3a 런타임 애니 id | 기록된 피격 순간 적의 애니에 TAE 공격 이벤트가 있나 | 224건 중 198 (0.884) — 아래 | 382건 중 309 (0.81) |
| 3b 런타임 타이밍 | 피격 시각 − 애니 시작 = 활성 구간 안인가 | **안 함 — [win] probe** | — |

1단계가 말하는 것: 32비트 리더가 66개를 끝까지 읽었고, type 1·2의 p[2]가 그 모델 BehaviorParam의 judge id와 맞는다.
말하지 않는 것: 시작/끝 시각이 맞는 필드인지, 애니 id가 게임이 쓰는 번호인지, type 이름이 뜻과 맞는지.
내부 신호 하나(증거는 아님): c2540의 활성 구간이 모두 30 fps 프레임 경계에 정확히 떨어짐 (예: 3000 = 프레임 26.0–31.0).

### 1단계 세부 (2026-10-16, `tae_extract.py --rebuild`)
- judge 불일치 4건: c2250 애니 3013 값 190 · c5260 애니 1750 값 321 · c5280 애니 3000 · 3001 bullet 값 121.
  [win] 첫 실행 커밋은 "레이아웃과 p[2]가 맞다"고 적었지만, 여기서는 1단계 통과로만 본다.
- 고친 것: 첫 판의 `attacks`는 type 5(common)의 p[2]도 judge로 넣었다 — type 5엔 judge가 없음 (c2540에서 0 · 1 · 5 · 16 같은 값이
  701 · 1500 · 7201 같은 애니와 묶였음). 이제 type 1·2만. 시각 키도 `active_start` · `active_end`로 바꿈.

### 3a 세부 (`tae_verify.py blame c2540`, data/samples의 `hit` 이벤트 224줄)
- 공격 이벤트 있는 애니: 198 — 254012/3008 ×57 (bullet, 화염병), 254010/3000 ×22, 254010/3003 ×16, 254010/3010 ×16, 254011/3000 ×14 …
- 공격 이벤트 없는 애니: 17 — 3500 ×12, 2006 ×3, 701 ×1, 2052 ×1. `blame`은 봇의 추정(가까운 적)이라 이 중 일부는 다른 적이 때렸을 수 있음.
- **TAE에 없는 애니: 9 — 254011의 3040 · 3041 · 3043 · 3044.** c2540.anibnd에 없는 번호. NpcParam `AnimationIDOffset`이나 다른 anibnd를
  빌리는지 확인할 것 (아직 모름).
- 한계: `hit` 이벤트엔 애니 진행 시간이 없어 타이밍은 못 봄 → 3b.

## [win] 할 일

**A. DSAnimStudio 대조 (필수, 30분)** — 2단계
1. DSAnimStudio에서 `chr/c2540.anibnd.dcx` 열기.
2. `python tae_verify.py sheet c2540 3000 3003 3010` 출력을 옆에 두고 애니마다 비교:
   - 애니 id가 같은 이름(`a00_3000` 등)으로 있나
   - 출력에 있는 이벤트(type 1 attack · type 2 bullet)가 같은 type 번호로 있나, 시작/끝 (초 또는 프레임) 같은가
   - 이벤트 안 숫자(p 네 개 — DSAnimStudio의 필드 이름도 적기, 특히 p[2]가 BehaviorJudgeID로 나오는지)
   - "그 밖 이벤트" 개수가 type별로 같은가 (예: 3000은 type 0 ×10, 128 ×11 …)
3. 아래 "결과"에 애니마다 같음 / 다름(무엇이)을 적는다. 하나라도 다르면 2단계 실패로 적고 멈춤 — [cloud]가 리더를 고친다.
4. 덤으로: 254011의 3040–3044가 DSAnimStudio에 보이는지 (다른 anibnd를 빌리는지).

**B. 런타임 타이밍 (가능하면, 20분)** — 3b
1. 오프라인, 할로우(c2540) 한 마리 앞. 죽지 않게: `tm.set_dbg(tm.DBG_PLAYER_NO_DEAD, True)` (끝나면 끄기).
2. `python tae_verify.py probe 120` — 2분 동안 가만히 서서 맞기 (막지 말 것). 기록: `data/samples/<시각>_tae-probe.jsonl`.
3. `python tae_verify.py timing data/samples/<그 파일>` — 출력과 평균 프레임 간격(`mean_dt`)을 결과에 적고, 기록 파일을 커밋.
   `inside` = 피격 시각이 활성 구간 ± 한 프레임 간격 안. `outside`가 많으면 3b 실패 (어긋난 정도를 보고 [cloud]가 판단).

## 결과

### A. 2단계 독립 도구 대조 — 2026-10-16 [win]: **통과 보류 (다른 것 1종) · 시뮬레이터 연결 중단**

MoKa 10-16 지시: "하나라도 다르면 독립 대조 통과를 보류하고 시뮬레이터 연결은 중단한다. 단, 가능하면 예정된 세 애니메이션의 비교 자료는 모두 수집한다.
차이가 난 항목은 원본 값·표시 단위·이벤트 종류와 함께 남긴다." → 첫 차이에서 멈추지 않고 3000 · 3003 · 3010 셋 다 모음.

**도구**: DSAnimStudio 4.9.9 (`DSAS_4.9.9_HOTFIX_b.zip`, github.com/Meowmaritus/DSAnimStudio 릴리스 `ver4.9.9`, sha256 `21a0f7e3…305b` — 릴리스에 공개 해시 없음),
`D:\tools\dsas`. GUI 조작 권한은 거절돼서(10-16) **GUI 대신 DSAnimStudio 안의 TAE 파서**(`SoulsAssetPipeline.Animation.TAE`)와 그 이벤트 이름표
(`Res/TAE.Template.DS1.xml`)를 PowerShell에서 직접 불러 읽음 — `experiments/dsas_tae.ps1`. GUI가 보여 주는 값과 같은 코드이지만 화면 확인은 아님.
원본 자료: `data/gamefiles/tae_check_c2540_dsas.json` (이벤트마다 type · 이름 · 시작/끝 float32 초 · 매개변수 바이트 hex · 이름 붙은 값 + 대조 결과).

**같은 것** (세 애니 모두)
- 파일: `c2540.tae` 1개, TAE id 202540, 형식 DS1, 애니 170개 — 우리와 같음.
- 애니 id 3000 · 3003 · 3010 있음. 이벤트 총수 30 · 28 · 49 = 우리 (kept + other_types 합).
- type 1 = DSAnimStudio 이름 `InvokeAttackBehavior` (매개변수 `AttackType` · `AttackIndex` · `BehaviorJudgeID`) — 개수 1 · 1 · 6 같음, 순서 같음.
- **p[2] = `BehaviorJudgeID`** — 100 · 130 · 300 같음. p[0] = AttackType 0, p[1] = AttackIndex (3010에서 0 · 1 · 2 · 2 · 2 · 2) 같음.
- 시작/끝: 8개 이벤트 모두 |차이| < 0.00005 s (아래 표시 단위). 30 fps 프레임으로 같은 칸 (3000 = 26–31, 3003 = 37–40, 3010 = 32–36 · 41–44 · 52–55 · 59–62 · 68–71 · 77–81).
- 그 밖 type별 개수 같음 (3000: 0 ×10 · 16 ×1 · 66 ×1 · 112 ×5 · 118 ×1 · 128 ×11 등). type 2 · 5 는 세 애니에 없음.
- 덤: 254011의 3040 · 3041 · 3042 · 3043 · 3044 — DSAnimStudio 파서로도 c2540.anibnd에 **없음** (우리와 같음; 어디서 오는지는 여전히 모름).

**다른 것 — 1종, 8건 (type 1 `InvokeAttackBehavior` 매개변수 개수)**

| 애니 | 이벤트 | 우리 `p` (s32 ×4) | DSAnimStudio 원본 바이트 (12 B) | DSAnimStudio 값 (s32 ×3) |
|---|---|---|---|---|
| 3000 | type 1 0.8667–1.0333 s | [0, 0, 100, **128**] | `00-00-00-00-00-00-00-00-64-00-00-00` | AttackType 0 · AttackIndex 0 · BehaviorJudgeID 100 |
| 3003 | type 1 1.2333–1.3333 s | [0, 0, 130, **128**] | `00-00-00-00-00-00-00-00-82-00-00-00` | 0 · 0 · 130 |
| 3010 | type 1 1.0667–1.2000 s | [0, 0, 300, **1**] | `00-00-00-00-00-00-00-00-2C-01-00-00` | 0 · 0 · 300 |
| 3010 | type 1 1.3667–1.4667 s | [0, 1, 300, **112**] | `00-00-00-00-01-00-00-00-2C-01-00-00` | 0 · 1 · 300 |
| 3010 | type 1 1.7333–1.8333 s | [0, 2, 300, **1**] | `00-00-00-00-02-00-00-00-2C-01-00-00` | 0 · 2 · 300 |
| 3010 | type 1 1.9667–2.0667 s | [0, 2, 300, **112**] | `00-00-00-00-02-00-00-00-2C-01-00-00` | 0 · 2 · 300 |
| 3010 | type 1 2.2667–2.3667 s | [0, 2, 300, **1**] | `00-00-00-00-02-00-00-00-2C-01-00-00` | 0 · 2 · 300 |
| 3010 | type 1 2.5667–2.7000 s | [0, 2, 300, **112**] | `00-00-00-00-02-00-00-00-2C-01-00-00` | 0 · 2 · 300 |

- 원인(추정): `tae_extract` 32비트 리더가 type에 상관없이 매개변수를 **s32 4개(16 B)** 읽음. type 1은 12 B라 p[3]은 이벤트 밖 바이트 — 값 128 · 112 · 1은
  바로 뒤 이벤트 데이터의 첫 4바이트(다음 이벤트 type 128 PlaySound · 112 · …)로 보임. 앞 세 값은 같으니 judge 대조·활성 구간엔 영향 없지만,
  `p`를 그대로 쓰면 틀린 값이 섞임. 고칠 곳: type별 매개변수 길이(템플릿: type 1 = 12 B, type 2 = s32 ×3 + u8 + b + s16 = 16 B, type 5 = s32 ×2 = 8 B).
- 덤 (대조 범위 밖, 참고): 템플릿에서 **type 5 `InvokeCommonBehavior`의 BehaviorJudgeID는 p[1]** (p[0] = AttackIndex). 10-16 [cloud]가 type 5를 judge에서 뺀 건 맞는 방향.

**표시 단위 (차이로 세지 않음, 기록만)**: DSAnimStudio = float32 초 그대로 (예 0.8666667, 1.0333333). 우리 tae.json = 초를 소수 4자리로 반올림 (0.8667, 1.0333).
차이는 모두 0.00005 s 미만 = 30 fps 한 프레임(0.0333 s)의 0.2 % 미만. 프레임 단위로 바꾸면 같은 정수 프레임.

**판정**: 2단계 **통과 보류**. 시뮬레이터 연결(AI Lua · 수직 슬라이스) **중단** — type 1 매개변수 길이를 고친 뒤 다시 대조.
3b(런타임 타이밍 probe)는 이번에 안 함.

### A-2. 2단계 재대조 — 2026-10-16 [cloud]: **type 1 통과**

- 고친 것 (`tae_extract.py`): 매개변수를 type별 길이로 읽음 — DSAnimStudio `TAE.Template.DS1.xml` 기준 type 1 = s32 ×3 (AttackType ·
  AttackIndex · BehaviorJudgeID), type 2 = s32 ×3 · u8 · s8 · s16, type 5 = s32 ×2 (AttackIndex · BehaviorJudgeID → judge는 p[1]).
  tae.json은 `--rebuild`로 다시 씀 (옛 4 × s32 값에서 앞부분만 남기고, type 2는 넷째 값을 u8 · s8 · s16으로 풂). 결과 그대로 66/66, judge (attack + bullet) 1241/1245.
- 대조: `python tae_verify.py dsas` — [win]이 모은 `data/gamefiles/tae_check_c2540_dsas.json`(DSAnimStudio 파서가 읽은 값)과 tae.json을 비교.
  3000 · 3003 · 3010: 이벤트 총수 · 그 밖 type별 개수 · type 1의 시작/끝(±0.00005 s) · 매개변수 3개 모두 같음 → **차이 0**.
- 이 대조가 예전 잘못을 잡는지: 옛 읽기(넷째 값 붙이기)로 되돌리면 [win]이 찾은 8건이 그대로 나옴 (`tests/tae_verify_test.py`).
- 범위 밖 (아직 독립 대조 없음): **type 2 (bullet)** 와 **type 5 (common)** — 세 애니에 없었음. 길이는 템플릿만 따름.
  type 5의 judge (p[1]) 741개는 그 적 자신의 BehaviorParam에 하나도 없음(0/741) → 공용 behavior를 가리키는 것으로 보고 `attacks`에서 뺌 (그대로).
- 화면 확인은 아님: [win]이 DSAnimStudio의 파서를 PowerShell로 불러 읽은 값 (GUI 조작은 거절됨). 같은 코드이지만 그렇게 적어 둠.

## 다음 (10-16 [cloud])

시뮬레이터 연결 조건(MoKa): 이 검증이 통과하면 c2540 하나로 AI Lua와 연결. 2단계는 type 1만 통과, 3b(런타임 타이밍)는 아직.
첫 수직 슬라이스는 c2540의 **근접 공격(type 1)만** 쓰고, 투사체(254012의 3008 화염병 = type 2)는 대조 전이라 빼고 시작한다.

**[win] 할 일**
1. (필수) AI Lua: `python ai_extract.py c2540` → `data/gamefiles/ai/*.lua` + `index.json` 커밋. c2540의 goal = battle 254000 · 254001 · 254002, logic 10000.
   `index.json`의 `calls_outside`에 aiCommon 함수가 많으면 `python ai_extract.py c2540 --common`도 한 번 (공용 함수 전부).
   못 찾은 goal (`missing`)이나 실패 (`ok: false`)는 그대로 적기.
2. (가능하면) 3b 런타임 타이밍: 위 "B" 그대로 (`tae_verify.py probe` → `timing`).
3. (가능하면) type 2 대조: `experiments/dsas_tae.ps1`로 c2540 3008 (bullet) 한 개 더 → `tae_check_c2540_dsas.json`에 추가, `python tae_verify.py dsas`.
