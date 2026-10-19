# REA — 이 프로젝트에서 쓰는 법 · 결과 원장

ROADMAP `rea-anim-time`. 1 · 2차 시험 기록(설치, 덤프, 시험 B 5/5)은 [`rea-trial.md`](rea-trial.md). 여기는 **지금 쓰는 방법**,
**찾은 것의 원장**, **진행 중인 지시문**만 둔다.

## 쓰는 법 (2026-10-19, REA 6.5.0 · Ghidra 12.1.4 · Windows)

- 대상은 디스크 exe가 아니라 **실행 중 덤프** (`exe_dump.py`): 디스크 exe는 코드가 암호화돼 있다 (rea-trial 1차).
- Ghidra 자동 분석은 `REA_GHIDRA_DISABLED_ANALYZERS`로 15개를 끄면 약 3분 (rea-trial 2차). MCP 서버는 **사용자 환경 변수**로 뜨므로 `setx` 후 Claude Code 재시작.
1. **CLI 대신 MCP 세션.** CLI는 명령마다 별도 프로세스라 Ghidra를 새로 띄운다(2차: 질문 하나 2.5–3분). MCP는 `open_binary` 한 번 →
   같은 세션에서 `search_bytes` · `xrefs` · `procedure_pseudo_code` · `read_bytes` … → 끝에 `close_binary`. 같은 질문 반복엔 CLI `--snapshot <json>` 캐시.
2. **런타임 닻에서 시작.** 2차가 강했던 건 패턴 → 주소라는 닻이 있었기 때문이고, 시험 C(피해 계산식)가 막힌 건 닻이 없었기 때문.
   읽기 전용 Python으로 후보(오프셋 · 객체 vtable · 아는 주소)를 먼저 잡고, REA로 그 코드를 읽고, 다시 게임에서 확인한다.
3. **이 문서가 원장.** Windows Ghidra P0는 Ghidra DB에 이름 · 주석을 저장하지 못한다. 함수 주소 · 오프셋 · Evidence ID는 아래 "원장"에.
- 못 하는 것: 게임 데이터 파일(TAE 등 — `unsupported binary format`, TAE는 `tae_extract.py`). Frida는 REA 문서상 검증이 Linux만, Windows 미확인 ·
  게임 프로세스에 코드를 넣는 일이라 쓰려면 MoKa 결정. Cheat Engine "쓰는 코드 찾기"도 디버거를 붙이므로 같음.
- **남이 이미 역분석한 것부터 찾는다.** DSR은 DS1 Overhaul(`OverhaulDLL/include/PlayerInsStruct.h`: ChrIns · ChrCtrl · 애니 큐 · HitIns 오프셋),
  DSR-Gadget(우리 포인터 맵의 출처), SoulMemory/SoulSplitter(이벤트 플래그)가 있다. 거기서 닻을 얻고, REA는 그 뜻을 확인하는 데 쓴다.
- 결과는 CLAUDE.md "How to state results"대로: 후보 / 정적으로 읽음(Evidence ID) / 게임에서 확인(n/n)을 나눠 적는다.

## 원장 (찾은 것)

| 무엇 | 주소 · 오프셋 | 근거 | 상태 |
|---|---|---|---|
| ChrDbg 플래그 배열 16바이트 이름 | `0x141c77e59` +0x0…+0xF | 게임 디버그 메뉴 `CHR DBG` 이름표 (rea-trial 2차 표) | 정적으로 읽음, 15개 `dsr_telemetry.DBG_*`; +0xA AllNoHit 효과는 tae-verify probe 4 |
| CHR DBG 메뉴를 만드는 함수 | `0x1403744xx`–`0x1403748xx` | 2차 decompile | 정적으로 읽음 |
| 클래스 vtable (RTTI) | PlayerCtrl `0x14132c258` · EnemyCtrl `0x14132bea8` · ActionCtrl `0x14132d318` · FrpgDefaultAnimationControl `0x1413460d0` · hkaDefaultAnimationControl `0x141412728` | 덤프의 MSVC RTTI `.?AV…@@` → COL → vtable (Python, 10-19) | PlayerIns · EnemyIns vtable이 `dsr_telemetry`의 값과 같음 (2/2) |
| AllNoDamage(+0x9)를 읽는 곳 | `FUN_140322925` | 2차 xrefs | 정적으로 읽음 — 피해 계산식(시험 C)의 출발점 후보 |
| 애니 재생 시간 | `[ChrIns+0x68]+0x18` 큐 → 엔트리(0x78) `+0x8` → `FrpgDefaultAnimationControl` `+0x10` 시간 · `+0x14` 무게 · 엔트리 `+0x20` 애니 정보 | Overhaul 경로 + 게임에서 읽음 (10-19, 플레이어 · 적 9 · A의 3000 10번) | 게임에서 봄: 새 재생 0.017부터, 맞는 시각이 TAE 구간 안 10/10. 같은 ID 재시작: 아직 안 나옴 |

## 3차 지시문 — 애니 재생 시간 필드, Overhaul 구조체 경로를 닻으로 ([cloud] 2026-10-19 개정)

MoKa: "애니 재생 시간 필드부터 MCP 세션 방식으로" → "Overhaul의 ChrCtrl→AnimationQueue→hkaDefaultAnimationControl 경로를 기준점으로".

목적: `docs/design-player-options.md` "Known blind spots" 1 — **같은 ID 재시작**. 지금은 애니 ID(`[ChrIns+0x68]+0x48 → +0x80`)만 읽어서,
할로우가 3000을 두 번 이어 휘두르면 하나로 보이고 `restart_possible`로 버린다(probe 3 · options pilot에서 7/100). 게임이 들고 있는
**애니 재생 시간**을 읽으면 두 번째 3000이 보이고 "age"가 게임 자신의 값이 된다.

### 닻: DS1 Overhaul의 DSR 구조체 (읽기만, 코드는 가져오지 않음)

출처: [metal-crow/Dark-Souls-1-Overhaul](https://github.com/metal-crow/Dark-Souls-1-Overhaul) `OverhaulDLL/include/PlayerInsStruct.h`
(그 파일의 마지막 커밋 `1c900fdf9a`, 2026-04-01). DSR용 PvP 모드가 롤백 넷코드를 위해 캐릭터 상태를 통째로 복사하려고 적어 둔 구조체로,
`static_assert`로 오프셋이 고정돼 있다. 저장소 라이선스가 명시돼 있지 않으니(GitHub `NOASSERTION`) **코드를 복사하지 않고** 오프셋 사실만 쓴다.
이 구조체는 어디를 **복사할지**만 적었지 필드 이름은 거의 없다(`data_0[16]` 같은 덩어리) — 시간 필드는 거기 이름으로 적혀 있지 않다.

우리 체인과 맞대 본 것 ([cloud], 문서끼리만 대조함 — 게임에선 아직):

| Overhaul | 오프셋 | 우리 쪽 (`dsr_telemetry.py` 머리말) |
|---|---|---|
| `ChrIns.playerCtrl` → `ChrCtrl` (PlayerCtrl의 첫 멤버) | ChrIns +0x68 | "ChrMapData" — 같은 오프셋 |
| `ChrCtrl.havokChara` | +0x28 | ChrPosData (+0x10 x …) — 같은 오프셋 |
| `ChrCtrl.actionctrl` | +0x48 | 애니 ID를 읽는 객체 (+0x80) — 같은 오프셋 |
| `ChrIns.curHp` · `maxHp` · `curSp` | +0x3E8 · +0x3EC · +0x3F8 | 같음 |
| `ChrCtrl.chrins` (부모 ChrIns를 다시 가리킴) | +0x10 | 우리는 안 읽음 → 1의 점검에 씀 |

시간 후보로 가는 경로 (Overhaul 오프셋):

```
ChrIns +0x68 → ChrCtrl
  +0x18 → ChrCtrl_AnimationQueue     (+0x0 array_length u32, +0x8 arry, +0x18 → hkaAnimatedSkeleton)
            arry[i]  (엔트리 0x78바이트):  +0x8 → hkaDefaultAnimationControl (0xC0바이트),  +0x20 → 애니 정보(animbnd 쪽, 상수 포인터)
            hkaAnimatedSkeleton: +0x20 → animCtrl_list,  +0x28 animCtrl_list_len   ← 같은 컨트롤들로 가는 둘째 길
  +0x20 → AnimationMediator           (states_list[31], 0xA8바이트씩, 각 +0x0 = animationId — Overhaul의 dev_scripts/DSR_AnimationMediator.CT)
```

**추론 (Overhaul에는 없음):** `hkaDefaultAnimationControl`은 Havok 애니메이션 SDK의 클래스 이름 그대로다. Havok의 `hkaAnimationControl`은
`hkReferencedObject`(vtable + 참조 수, 0x10바이트) 다음에 `m_localTime`(float) · `m_weight`(float)를 두는 꼴로 알려져 있다 → **+0x10 = 재생 시간,
+0x14 = 섞는 무게** 일 가능성이 높다. Overhaul의 `data_0[16]`(+0x8–+0x18)이 그 자리를 덮는다는 것과도 맞는다. 하지만 SDK 판마다 배치가 달라질 수 있으니
1 · 2에서 확인하기 전엔 "후보"다. 같은 ID 재시작 쪽에도 단서가 있다: 새로 재생할 때마다 컨트롤 객체가 새로 생기면 **포인터가 바뀌는 것만으로도** 재시작이 보인다.

### 지킬 것
- 게임 메모리는 **읽기만**. ChrDbg 플래그 쓰기도 이번엔 필요 없음. Steam 오프라인, 봇 실행 중이 아닐 때.
- 덤프 · 디컴파일 결과는 커밋하지 않는다(`D:\tools\rea-target\` · 스크래치에만). 커밋하는 건 이 문서의 결과 글과 `experiments/` 스크립트.
- Frida · Cheat Engine은 쓰지 않는다 (위 "쓰는 법").
- 시간 상한 **2시간** (닻이 있어서 2.5시간에서 줄임). 아래 각 단계의 멈춤 조건을 지킨다.

### 0. 준비 (15분)
- 사용자 환경 변수 두 개를 넣고 Claude Code 재시작 (MCP 서버는 사용자 환경 변수로 뜬다 — 2차 메모):
  `setx REA_GHIDRA_DISABLED_ANALYZERS "Windows x86 PE Exception Handling,PE RTTI Analyzer,Decompiler Switch Analysis,Call Convention ID,Function ID,Demangler Microsoft,Non-Returning Functions - Discovered,Create Address Tables,Embedded Media,Apply Data Archives,Shared Return Calls,x86 Constant Reference Analyzer,PDB Universal,Stack,ASCII Strings"`
  (2차 결과 2.의 15개 그대로 — 2차에 쓴 문자열과 한 글자라도 다르면 REA가 바로 멈추니, 2차 셸 기록이 있으면 그걸 쓴다) ·
  `setx REA_GHIDRA_STARTUP_TIMEOUT_MS 900000`. Claude는 자기 설정을 못 바꾸므로 MoKa가 실행할 수 있다.
- 재시작 뒤 `binary_session` `{}` → `result.tool_availability`에서 `open_binary` · `search_strings` · `xrefs` · `read_bytes` ·
  `procedure_pseudo_code` · `procedure_callers`가 available인지. 아니면 reason · remediation을 적고 멈춘다.
- 덤프: 지금 `DarkSoulsRemastered.exe`의 SHA-256이 10-16과 같으면 2차 덤프 `D:\tools\rea-target\dsr.dump.exe`(sha256 `88d8d84e…e5cf`)를
  그대로 쓴다. 다르면 `python exe_dump.py --out …`로 새로 뜨고 `OK`(AOB 6개 모두 1번) 확인.
- REA는 2에서만 쓴다. 1에서 후보가 3 조건을 다 통과하면 2는 "확인용"이라 짧게 끝낸다.

### 1. Overhaul 경로를 게임에서 읽기 — 읽기 전용 Python (30분)
`experiments/anim_time_scan.py`를 새로 짠다(봇은 import 안 함, `dsr_telemetry`의 읽기 함수만 씀).
- **a. 경로 점검 (먼저, 2분):** 플레이어와 할로우 하나에서 `[ChrCtrl+0x10] == ChrIns` · `[ChrCtrl+0x28] == 우리 posd` · `[ChrCtrl+0x48] == 우리 animst`.
  `ChrCtrl_AnimationQueue.array_length`가 작은 수(대략 1–10)인지, `arry[i]+0x8`이 0이 아닌 포인터인지.
  **하나라도 어긋나면 멈추고** 어긋난 값을 적는다 — Overhaul의 판과 우리 판이 다르다는 뜻(우리 module size 0x319B000).
- **b. 기록:** 약 60 Hz로 각 엔트리 i에 대해 `hkaDefaultAnimationControl` 포인터 값 + 그 객체 `+0x00…+0xC0`(float32 · u32 둘 다), 엔트리 `+0x20`
  (애니 정보 포인터), 그리고 `ActionCtrl+0x80`(지금 애니 ID)과 QPC 시각. 덤으로 `AnimationMediator` states_list에서 `animationId`가 지금 애니 ID와
  같은 칸의 `+0x00…+0xA8`.
- **c. 동작**(`control.Pad`): 서 있기 5 s → 구르기 1 → 서 있기 3 s → 약공 1 → 서 있기 3 s → **구르기 2번 연속**(같은 ID 재시작) → 서 있기.
- **d. 판정:** 컨트롤 `+0x10`(먼저) — 그 밖의 오프셋은 그다음 — 이 (1) 애니가 바뀔 때 0 근처로, (2) 애니 동안 기울기 ≈ 1.0 (게임 시간 / 실제 시간,
  30 fps 계단 가능), (3) **같은 ID 연속 재시작에서도 0으로** 가는가. 함께 볼 것: 재시작 때 컨트롤 **포인터가 바뀌는가**, `+0x14`(무게 후보)가
  여러 컨트롤 중 지금 애니 쪽에서 가장 큰가(섞임 중엔 컨트롤이 둘 이상일 수 있다 — 어느 엔트리가 "지금 애니"인지 고르는 규칙도 적는다).
- 적을 것: 오프셋별 표(형식 · 기울기 · ID 변경 시 리셋 n/n · 같은 ID 재시작 리셋 n/n · 포인터 변경 n/n).

### 2. REA로 확인 — 한 MCP 세션 안에서 (45분)
- `open_binary`(덤프) **한 번** — 걸린 시간 적기(2차 CLI `rea analyze` 2분 41초와 비교). 10분 넘으면 멈춘다.
- **a. 클래스 이름 닻:** Havok 클래스 이름 문자열 `hkaDefaultAnimationControl`을 `search_strings` → `xrefs`로 그 클래스 정보 · vtable 근처로.
  1에서 읽은 컨트롤 객체의 첫 8바이트(vtable)와 같은 주소인지 대 본다. 못 찾으면(문자열이 없거나 xref 0) 1의 vtable 값으로 바로 시작.
- **b. vtable 메서드:** vtable을 `read_bytes` → 메서드 포인터 → `procedure_pseudo_code`. "+0x10에 dt(× 속도)를 더함", "+0x10 = 0 / 값 대입"(새 재생 ·
  `setLocalTime` 꼴)을 찾는다. 1에서 다른 오프셋이 이겼으면 그 오프셋으로.
- **c. 재시작 경로:** 그 리셋 · 생성 함수의 호출자(`procedure_callers`)를 거슬러 `ActionCtrl` 쪽까지 — "이전 ID와 같으면 건너뜀" 비교가 있는지.
  있으면 이 필드로도 재시작이 안 보일 수 있다 — 그대로 적는다.
- 결론마다 **관찰 / 추론 / 모름**을 나누고 REA Evidence ID를 단다. 45분에 b가 안 나오면 멈추고 무엇을 해 봤는지 적는다 (1의 결과만으로도 3은 할 수 있음).
- 끝에 `close_binary`.

### 3. 적에서 다시 확인 (20분)
- options pilot 세이브(`backup-20261016-234951-options-pilot-ready-A-only`, 할로우 A만)에서 할로우의 같은 경로(EnemyIns도 같은 ChrIns · ChrCtrl —
  위치 · 애니를 이미 같은 체인으로 읽음)를 1과 같은 스크립트로 읽는다.
- 3000 **5번 이상**에서 시작값 ≈ 0, 끝값 ≈ `data/gamefiles/tae.json`의 c2540 3000 길이(±0.05 s), 이어 휘두른 3000이 있으면 리셋 · 포인터 변경.
- 이 단계를 통과하지 못하면 "후보"로만 적는다(확인됐다고 쓰지 않는다 — CLAUDE.md "How to state results").

### 4. 결과 (아래 "3차 결과"에) · ROADMAP
- 1-a 경로 점검 결과, 1-d 표, 2의 함수 주소 · Evidence ID 표, 3의 n/n.
- 0 · 2의 시간: `open_binary` 시간 · 질문 수 · 총 시간 (2차 CLI 방식과 비교). 닻이 시간을 얼마나 줄였는지.
- [win] 한 줄 의견: Overhaul 구조체 + MCP 세션 방식이 다음 질문(시험 C 피해 계산식 · 3000 판정 끝 · `HitIns`)에도 쓸 만한가.
- 확인되면 위 "원장" 표에 한 줄, ROADMAP `rea-anim-time` 줄 갱신. [cloud]가 `dsr_telemetry`에 재생 시간 읽기를 넣고 `tae_verify.py` ·
  `options_pilot.py`의 `restart_possible`(1.5 × 중앙값 추정)을 이 값으로 바꾼다 — 그 전엔 바꾸지 않는다.

## 3차 결과

2026-10-19 07:30–07:45, 이 세션([win] 자리에서 Windows Claude Code)이 직접 함. 게임은 MoKa가 켬, `keys.py continue`로 들어감 → 세이브는 options pilot 자리
(플레이어 (−1.3, −10.0, −62.7), 할로우 254010 15.5 m). 게임 메모리는 읽기만, 입력은 패드(백스텝 · 약공). 도구 `experiments/anim_time_scan.py`,
기록 `data/samples/20261019_073848_anim-time-scan.jsonl`(drill) · `20261019_073938_anim-time-scan.jsonl`(drill --restart).

**0. 준비 — REA는 이번에 거의 안 씀.** `REA_GHIDRA_DISABLED_ANALYZERS`가 사용자 환경 변수에 없어서 MCP 세션은 안 열었고(열면 전체 분석 1시간+), CLI에
환경 변수를 그 자리에서 주고 `rea decompile` 4개를 병렬로 보냈더니 **34초 만에 4개 모두 `execution_failure`** — 원인은 안 봄(병렬 Ghidra 4개 ·
같은 시각 게임 시작이 겹침). 대신 Python으로 덤프를 직접 읽음:
- 덤프에 MSVC RTTI 이름(`.?AVhkaDefaultAnimationControl@@`, `.?AVFrpgDefaultAnimationControl@NS_FRPG@@`, `.?AVChrCtrl@NS_FRPG@@` …)이 있음 →
  TypeDescriptor → CompleteObjectLocator → vtable로 10개 클래스의 vtable을 구함 (위 "원장"). **PlayerIns `0x1413251f0` · EnemyIns `0x141322e68`이
  `dsr_telemetry`가 쓰던 값과 같아서(2/2)** 이 방법은 믿을 만함. 이 방법은 Ghidra 없이 몇 초.
- 실제 애니 컨트롤의 클래스는 `FrpgDefaultAnimationControl`(FromSoft가 Havok의 `hkaDefaultAnimationControl`을 이어받은 것; vtable 17개 중 15개가 같은 함수).

**1-a. 경로 점검 — 통과 (플레이어 1, 적 9).**
- 플레이어: `ChrIns+0x68`의 vtable = PlayerCtrl, `+0x10` = 그 ChrIns(역포인터 맞음), `+0x48` = ActionCtrl, `+0x28` = 우리 위치 데이터. 애니 큐 길이 16, 엔트리 16개 모두
  `FrpgDefaultAnimationControl`.
- 적 9명(254010 · 254011 · 254012 ×3 · 255000 ×2 · 255001 · 251001): 모두 EnemyIns / EnemyCtrl, 역포인터 맞음, 큐 길이 12. → Overhaul의 오프셋은 **우리 판(module size
  0x319B000)에서도 맞다** (이 10명 범위).

**1-b/d. `+0x10`은 재생 시간으로 보임 — 플레이어, 백스텝 · 약공 · 대기 범위.**
- 무게 `+0x14`가 1.0인 동안 `+0x10`의 기울기 **0.987–1.007 (게임 초 / 실제 초)**, 17구간 중 16구간 (첫 구간 0.922는 기록 시작 직후 구간).
- 새 애니가 시작되면 **다른 엔트리**의 컨트롤이 `0.017`(1프레임)부터 세고, `+0x14`가 0.04 → 1.0으로 넘어감(섞임 약 0.1–0.4 s). 엔트리 `+0x20`(애니 정보 포인터)이 애니마다
  다름: 대기 `…ae37f0`, 백스텝(690) `…ad8e30`, 약공(253000) `…aef930`.
- 끝값: 백스텝 1.833, 약공 2.633 (2번 모두 같음). 애니 ID가 −1로 돌아가는 순간의 값.
- 대기 애니는 2.000에서 0.017로 **돌아감**(고리) → 고리 애니에선 "재생 시작부터의 시간"이 아니라 "고리 안 위치".
- **같은 애니를 다시 재생하면 0부터**: 백스텝 · 약공 뒤 대기 애니(같은 정보 포인터)가 다시 시작될 때 0.017 — 4/4 (두 기록 × 2).

**못 한 것 (다음)**
- **공격의 같은 ID 재시작은 시험 못 함.** 이어 누르기가 안 먹음: 백스텝 뒤 0.4–1.0 s에 백스텝 9번 → 0번 나감, 약공 뒤 0.5–1.6 s에 약공 8번 → 0번 나감(입력이 취소 구간보다
  이름; 언제 받는지 모름). 같은 ID가 다른 엔트리로 가는지, 같은 엔트리에서 0으로 가는지는 아직 모름.
- **적 3000은 안 함.** 적에서도 같은 필드가 오른다는 것만 봄(254010 0.5 s에 1.117 → 1.617, 대기). 3000 길이를 `tae.json`과 대 보는 것, 이어 휘두른 3000은 options pilot 준비
  (A 깨우기, PlayerNoDead)가 필요.
- REA 2단계(디컴파일로 `+0x10`에 dt를 더하는 코드 확인)는 안 함 — 위 CLI 실패.

### 3차 결과 2 — 할로우 A의 3000 (2026-10-19 07:45–07:53)

MoKa: "options pilot 방식대로 할로우 A를 깨워서 3000의 +0x10 시작·끝값과 이어 휘두를 때 리셋되는지 시험해 줘. PlayerNoDead 써도 돼."
`savepoint.py restore backup-20261016-234951-options-pilot-ready-A-only` (live 세이브는 `…-before-restore-…`로 먼저 백업됨) →
`python experiments/anim_time_scan.py foe 150`: PlayerNoDead 켬(끝나고 원래 값으로) → NavMesh 경로로 A에서 3.5 m까지 걸어감 →
**A 반대쪽을 보고** 헛스윙 1번에 깸 → 150 s 기록(서 있기, 뒤 절반은 3000의 0.3 s에 백스텝), HP 500 아래면 793으로 채움(16번).
기록 `data/samples/20261019_074957_anim-time-foe.jsonl`.

- **[이 세션의 실수] 첫 시도에서 A를 죽임** (`20261019_074649_anim-time-foe.jsonl`, A HP 75 → 0, 애니 2205 · 2255 — B-8과 같은 꼴):
  A를 **바라보고** 헛스윙하게 짜서 깨던 A가 다가와 맞음. 세이브를 다시 복원하고 반대 방향 헛스윙으로 고침.
- 3000은 10번 (A HP 75 그대로, 끝까지 깨어 있음). 3000의 컨트롤(정보 포인터 `…dba030`)만 본 값:

| | 값 | n |
|---|---|---|
| 시작 | 애니 ID가 3000으로 바뀐 읽기부터 0.03 s 안에 새 컨트롤이 보이고, 그때 `+0x10` = 0.0167–0.0333 | 10/10 |
| 맞은 순간 | HP가 준 읽기 바로 앞 · 그 읽기의 `+0x10` = 0.883–0.933 (괄호). **TAE 판정 구간 0.8667–1.0333 안** | 10/10 |
| 끝 | 1.167–1.183에서 3001로 이어짐 | 9/10 |
| 끝 (긴 것) | `+0x10` 0.017 → **2.417까지 한 번도 안 돌아가고** 이어진 뒤 3010 (3000 길이 2.389 s) | 1/10 |

- 맞은 순간이 TAE 구간 안에 드는 것(10/10)은 `+0x10`이 TAE와 같은 시간 축(애니 안 시각)이라는 독립 대조다 — probe 3의 첫 닿음 0.89–0.92 s와도 맞음.
- **같은 ID 재시작은 이번에 한 번도 안 나옴.** 10번 중 리셋 0. 2.4 s짜리 3000은 **한 번 재생이 길게 간 것**(시간이 끊기지 않음)이지 같은 ID를 두 번 한 것이 아니다 —
  B-11의 "2.42–2.48 s = 1.2 s 두 벌, 한 ID"라는 해석은 이 한 건에선 틀림(그때 것들이 같은 꼴인지는 B-11 기록엔 시간이 없어 모름).
  진짜 재시작이 일어나면 새 컨트롤이 0부터 세는지(플레이어 대기 애니에선 그랬음, 4/4)는 아직 못 봄.
- 백스텝(뒤 절반 3번)은 3000을 길게 만들지 못함 — 셋 다 1.18에서 3001.

**지금 말할 수 있는 것 (범위: 플레이어 백스텝 · 약공 · 대기, c2540 할로우 1마리의 3000 10번):** `FrpgDefaultAnimationControl +0x10`은 애니 안 시각이고
(초당 약 1.0, 새 재생은 0.017부터, 맞는 시각이 TAE 구간과 맞음), 무게 `+0x14`가 큰 쪽이 지금 애니다. `restart_possible`로 버리던 긴 3000은 적어도
이번 한 건에선 재시작이 아니었다 → [cloud]: `tae_verify.py` · `options_pilot.py`의 "1.5 × 중앙값이면 재시작일 수 있음" 제외를 이 값으로 바꿀 수 있음
(시간이 끊기면 재시작, 아니면 한 번) — 바꾸기 전에 재시작이 실제로 끊기는지 한 번은 봐야 함.
