# dsr-bot — Dark Souls Remastered 규칙 기반 봇

**오프라인 전용.** 다크소울 리마스터(PC, Steam)를 게임 메모리 읽기 + NavMesh A\* 길찾기 + 규칙 기반 전투로 진행하는 파이썬 봇입니다.
지금은 **불의 제전 → 성벽 마을 경사로 6마리 → 성벽 마을 → 상인 → 성벽 마을 화톳불**까지 혼자 갑니다.

> 온라인에 접속한 상태로 쓰지 마세요. 메모리를 일부 쓰는 기능(화톳불 워프, 타이틀로 나가기)이 있어 온라인에선 제재 위험이 있고,
> 다른 플레이어에게 피해가 갑니다. 이 저장소는 연구·학습용입니다.

## 현재 상태 (2026-09)

- 실행 중에는 LLM·학습 모델을 쓰지 않습니다 — 전부 규칙과 수치입니다. (`tactic_llm.py`, `bandit.py`, `learn.py` 등은 예전 실험)
- 개발은 AI 코딩 도구(Claude)가 코드 대부분을 쓰고, 사람이 플레이 시연·판단·검증을 맡는 방식으로 했습니다. 커밋의 `Co-Authored-By` 참고.
- 최근 판: 경사로 6/6, 성벽 마을 화톳불 도착. 최소 장비에서 최저 HP 27~47% — 여럿이 붙는 싸움이 약점.
- 원 작성자는 더 이어가기 어려워 공개합니다. **이어받거나 함께할 분 환영** — 특히 LLM / JEPA 같은 모델을 한 층에 끼워 보고 싶은 분.

## 구조

```
dsr_telemetry.py / telemetry.py   게임 메모리 읽기 (pymem) — 위치·HP·애니·적·카메라
navmesh.py / nav.py               게임 파일의 NavMesh(soulstruct) → 삼각형 그래프 A* 길찾기, 발밑 검사
souls/                            층 구조 — 아래 층은 위 층을 모른다 (LAYERS.md)
  moves.py     1층 조작 (패드: vgamepad)
  duel.py      2층 1:1 싸움 규칙
  foes.py      적 종류별 데이터 (애니 번호·막으면 안 되는 공격 등)
  field.py     4층 필드 — 교전 큐, 끌어오기(투척 나이프), 제자리 고수, 안전 구역
  missions.py  5층 임무 — 경사로 / 성벽 마을 / 상인 / 화톳불
run.py                            실행 진입점
observe_record.py                 읽기 전용 관찰 녹화 (사람 시연과 봇 판을 같은 형식으로)
risk_report.py, blackbox.py       판 평가 — 큰 피격, 최저 HP, 막힘
```

규칙과 그 근거는 [LAYERS.md](LAYERS.md) 한 곳에 있습니다 — 특히 **"근거 등급 게이트"**: 수치마다 사람 시연 / 반복 관찰 / NavMesh 추정 /
코드 상수 / 모름 중 무엇이 근거인지 적고, 등급이 허용하는 행동만 합니다. 관찰 녹화 형식은 [OBSERVE.md](OBSERVE.md).

## 실행

필요한 것: Windows, DSR (Steam), Xbox 패드 드라이버용 [ViGEmBus](https://github.com/nefarius/ViGEmBus), Python 3.12, [uv](https://docs.astral.sh/uv/).
Steam Input 은 끄세요 (패드 입력을 Steam 이 가로챕니다).

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/Scripts/python.exe -r requirements-lock.txt
# DSR 설치 경로가 다르면: set DSR_GAME_DIR=...\DARK SOULS REMASTERED
BOT_GAME=dsr .venv/Scripts/python run.py clear-ramp      # 경사로만
BOT_GAME=dsr .venv/Scripts/python run.py burg-bonfire    # 불의 제전 → 성벽 마을 화톳불
.venv/Scripts/python observe_record.py --minutes 15      # 읽기 전용 녹화 (F9 = 마커)
```

오프라인 테스트: `python field_*_test.py`, `duel_shadow_test.py`, `moves_test.py` 등 (게임 없이 가짜 월드로).

`data/` 에는 임무에 필요한 작은 파일만 올렸습니다 — 사람이 걸어 녹화한 경로(`data/routes/`), 적 스폰 지도, 안전 구역(`safe-zones.json`).
관찰 녹화·실행 기록(1 GB+)은 없습니다. 필요하면 이슈로 요청해 주세요.

## 이어서 해 볼 만한 것

- 여럿이 붙는 싸움 (지금 가장 큰 피해원) — 떼어놓기, 자리 선택
- 적 공격 예측 — 애니 번호의 뜻이 아직 영상으로 검증되지 않음 (`foes.py` 의 3004/3500 등)
- 사람 시연에서 배우기 — 관찰 녹화가 사람·봇 같은 형식이라 비교·학습 재료로 쓸 수 있음
- NavMesh 경로 다듬기(funnel), 부서지는 물체 인식

## 예전 문서

엘든링 시절 README 는 [README-legacy.md](README-legacy.md). 이 봇은 원래 [chzzk-souls-chaos](https://github.com/kakasolg/chzzk-souls-chaos)
(치지직 후원 → 게임 효과 어댑터)의 하위 폴더에서 시작했습니다.
