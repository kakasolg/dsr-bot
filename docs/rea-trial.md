# REA (Reverse Engineer Anything) 시험 — [win] 지시문

MoKa 2026-10-16: "Win local에게 R E Anything 으로 테스트 해 보라는 지시문 내려줘. 뭔지는 보자."
ROADMAP `rea-trial`. 목적은 **써 보고 판단할 자료를 모으는 것**. 봇에 붙이지 않는다.

## 미리 알 것

- REA = 코딩 에이전트(Claude Code 등)에 역분석 도구를 MCP로 붙여 주는 오픈소스 (github.com/morluto/rea, npm `rea-agents`, MIT).
  네이티브 exe는 REA 자체가 아니라 **Ghidra / IDA / Hopper를 따로 설치해서** 붙인다. 공식 README: Windows의 Ghidra 지원은 **"experimental"**.
- 블로그에 돌던 "재구성 의무 원장 · Coverage Score · 120개 이상 툴"은 공식 페이지에 없다 ([cloud] 10-16 확인). 시뮬레이션 기능도 없다.
- 판마다 호환이 깨진 적이 있다는 글이 있다 → **버전을 고정**하고 적어 둔다.
- 분석은 로컬에서 돌지만 결과는 에이전트(모델)로 간다.

## 지킬 것

1. **게임을 끄고**, 게임 폴더 밖에 `DarkSoulsRemastered.exe` **복사본**을 만들어 그걸로만 분석한다. Steam 폴더의 원본은 건드리지 않는다.
2. exe, 디컴파일한 코드, 덤프는 **커밋하지 않는다** (공개 저장소 · 저작권). 커밋하는 건 이 문서의 결과 글뿐.
3. REA가 게임 메모리에 붙거나 실행 중인 게임을 건드리는 기능(디버거 · 런타임 추적)은 이번에 **쓰지 않는다**. 정적 분석만.
4. 시간 상한은 **전체 2시간**. Ghidra나 REA 설치가 30분 안에 안 되면 거기서 멈추고 무엇이 막혔는지만 적는다.

## 순서

**0. 준비**
- `node -v` → 22 이상인지. 아니면 Node 22 LTS 설치.
- Ghidra가 없으면 설치 (JDK 21 필요). 이미 IDA가 있으면 IDA도 된다. 어느 쪽을 썼는지 적는다.

**1. 설치**
- `npm view rea-agents version` 으로 지금 버전을 보고, 그 버전으로 고정해서 설치: `npm install --global rea-agents@<버전>`.
- `rea-agents setup` (또는 `npx rea-agents@<버전> setup`). **어떤 설정 파일을 바꿨는지** 출력에서 적는다.
- Claude Code를 다시 열고 REA 툴이 보이는지, 몇 개인지 확인.

**2. 시험 A — 열리기는 하나** (10분)
- 복사한 exe를 대상으로: 형식(PE64), import 목록, 문자열 몇 개. 걸린 시간 (Ghidra 첫 분석은 오래 걸릴 수 있다 — 시간 적기).

**3. 시험 B — 답을 아는 문제** (핵심, 40분)
우리가 이미 정답을 아는 것으로 REA의 정확도를 본다. 에이전트에게 이렇게 묻는다:
> 이 exe에서 바이트 패턴 `80 3D ? ? ? ? 00 48 8B 8F ? ? ? ? 0F B6 DB` 를 찾고, `80 3D` 가 비교하는 전역 바이트 배열의 주소를 구해라.
> 그 배열(디버그 플래그 배열)의 각 바이트를 읽는 함수들을 찾아, 바이트 위치마다 그것이 무엇을 하는지 증거(호출 위치, 디컴파일 줄)와 함께 표로 만들어라.

정답 (`dsr_telemetry.py` · DSR-Gadget · 실측):

| 위치 | 뜻 | 근거 |
|---|---|---|
| +0x0 | PlayerNoDead (안 죽음) | 실측 |
| +0x1 | PlayerExterminate (즉사) | 실측 (`kill_player`) |
| +0x6 | PlayerHide (적이 못 봄) | DSR-Gadget, legacy 사용 |
| +0x9 | AllNoDamage (피해 없음) | DSR-Gadget |
| +0xB | AllNoAttack (아무도 공격 안 함) | DSR-Gadget, legacy 사용 |

적을 것: 주소를 맞혔나, 다섯 개 중 몇 개를 맞혔나, 틀린 것·지어낸 것(증거 없이 단정)이 있었나, 우리가 모르는 위치를 새로 알려 줬나.

**4. 시험 C — 모르는 문제** (선택, 40분)
`data/gamefiles/combat.json` 의 공격 위력(AtkParam `PhysicalAttackPower`)이 플레이어가 실제로 받는 피해로 바뀌는 **피해 계산식**을 찾게 한다.
> 적 공격이 플레이어에게 맞을 때 피해를 계산하는 함수를 찾아, 공격력 · 방어력 · 막기 감소율이 어떻게 섞이는지 식으로 써라. 근거 주소를 함께.
답은 모르니 **확인 방법**만 적어 둔다: 할로우 254010 공격 위력 177 vs 우리 기록의 실제 피해(`data/samples` 로그)로 식이 맞는지 [cloud]가 나중에 대조.

**5. (선택) TAE**
REA가 `chr/c2540.anibnd.dcx` 같은 게임 데이터 파일을 다루는지 한 번만 시도. 못 하면 "못 함" 한 줄.

## 결과 적기 (이 문서 아래 "결과"에, 그리고 커밋)

- 버전, 사용한 디스어셈블러, 설치에 걸린 시간, 바뀐 설정 파일
- 시험 A · B · C 각각: 걸린 시간, 결과, 맞은 것 / 틀린 것 / 지어낸 것
- 쓴 토큰이나 비용 (보이면)
- [win]의 한 줄 의견: 계속 쓸 만한가, 어디에
- ROADMAP `rea-trial` 줄을 `cloud | verify`(또는 막혔으면 `blocked`)로 바꾸고 push → [cloud]가 읽고 판단 정리

## 결과

2026-10-16 [win] 12:37–13:50 (73분). **시험 A 실패 — Ghidra 첫 분석이 60분 안에 안 끝남. 시험 B · C · TAE 못 함.**

**설치 (12:37–12:40 + setup, 약 15분 — 문제 없음)**
- rea-agents **6.5.0** (npm 2026-10-14 게시, 설치 스크립트 없음, 178 패키지). 디스어셈블러: **Ghidra 12.1.4** (NSA GitHub 릴리스, SHA-256
  `ddac49f9…d4db` 릴리스 노트와 같음) + **Temurin JDK 21.0.12** (winget). 이 PC의 기존 Java는 17이라 Ghidra에 안 맞았음.
- `rea doctor`: Ghidra 9개 점검 모두 통과 (win32/x64, headless, native decompiler, JDK 21, Job Object 격리).
- `rea setup --client claude_code`: 바뀐 파일 `C:\Users\moka\.claude.json` (MCP 서버 `rea` 추가, 백업 `.claude.json.rea.backup`)
  + `C:\Users\moka\.claude\skills\reverse-engineer-anything` (스킬). Claude는 자기 설정이라 못 바꿔서(자동 모드 거부) MoKa가 직접 실행.
  주의: setup은 실행한 셸의 `GHIDRA_INSTALL_DIR` · `JAVA_HOME`만 MCP 등록에 적음 — MoKa 셸엔 없어서 빠짐 → 사용자 환경 변수(setx)로 넣어야 함.
- CLI 명령 153개. [cloud]가 "공식 페이지에 없다"고 한 `build-reconstruction-obligation-ledger` · `evaluate-reconstruction-coverage`는 **6.5.0 CLI에 있음**.
  시뮬레이션 명령은 없음. Claude Code 재시작 전이라 MCP 툴 수는 못 셈 (CLI로 대신 시험).

**시험 A — 열리기는 하나**
- exe 복사본 `D:\tools\rea-target\` (원본과 SHA-256 같음, 게임 꺼진 상태). `rea analyze <exe> --provider ghidra`.
- 1회: 기본 상한 330 s에서 `provider_timeout` (operation `list_documents`). README대로 `REA_GHIDRA_STARTUP_TIMEOUT_MS=3600000` →
  2회: **60분 뒤 같은 `provider_timeout`**. Ghidra는 PE64 `x86:LE:64:default:windows`로 불러와 import(d3d11, dinput8, dxgi, XInput1_3, ws2_32 …)까지
  잡았지만 자동 분석 단계에서 안 끝남. 로그: 예외 처리 표 해석 실패 2087번(`EHDataTypeUtilities`), `CreateEHFuncInfo` 375번, 디컴파일
  "Unable to read bytes" 193번, "body contains referring thunk" — 난독화된 코드에서 보이는 꼴. REA는 분석이 끝나야 답을 주므로 형식 · import · 문자열 결과 0.
- 남긴 것 없음: REA 임시 폴더(`%TEMP%\rea-ghidra-*`)는 스스로 지움, Ghidra 프로세스 종료됨.

**시험 B를 미리 대 본 것 (REA 아님, Python으로 exe 바이트 직접)**
- 패턴 `80 3D ? ? ? ? 00 48 8B 8F ? ? ? ? 0F B6 DB` — **파일에 0번**. 앞부분 `80 3D ? ? ? ? 00`은 1632번, 뒷부분 `48 8B 8F ? ? ? ? 0F B6 DB`는 0번.
  `dsr_telemetry.py`는 실행 중 메모리에서 찾음 → 이 코드는 **디스크에선 암호화돼 있다가 실행 중에 풀림**(Arxan 계열 보호로 추정; `.text` 두 개,
  첫 `.text` 엔트로피 6.90). 그러니 시험 B는 정적 분석으로는 원래 못 푸는 문제 — REA가 끝까지 돌았다면 "못 찾음"이라 했는지 지어냈는지가 시험이 됐을 것.

**토큰 · 비용**: REA CLI 자체는 모델 호출 없음. 이 세션 토큰 외 추가 비용 없음.

**[win] 의견**: 이 exe에는 쓸 만하지 않음 — 정적으로는 보호된 코드가 안 보이고, Ghidra 전체 분석이 1시간 넘게 걸림. 다시 해 본다면
(1) Ghidra를 REA 밖에서 headless로 끝까지 한 번 분석해 프로젝트를 만들고 REA에 그 DB를 주거나, (2) 실행 중 덤프(게임 메모리 — 이번 규칙상 금지,
MoKa 결정)가 있어야 시험 B가 의미 있음. 지금의 메모리 패턴 + DSR-Gadget 방식이 더 빠름.
