"""DSR 봇 — 층 구조. 아래 층은 위 층을 모른다. 자세한 건 ../LAYERS.md.

  0층 게임 연결   control.py · dsr_telemetry.py · env.py · nav.py · navmesh.py · quitout.py · farm.py (bot/ 바로 아래)
  1층 기본 동작   moves.py      버튼·타이밍
  2층 무기 사용법 weapons.py    무기별 사거리·연타·강공
  3층 적 상대법   foes.py(데이터) · duel.py(한 마리)
  4층 플레이북   field.py(필드) · watch.py(탈출·핏자국)   — 보스는 ../boss/
  5층 임무       missions.py   → ../run.py
"""
