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

(아직 없음)
