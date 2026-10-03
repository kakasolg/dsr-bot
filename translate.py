"""Korean → English for what the radar page and the overlay show (the bot's log lines and route tags).

Only the display is translated — log files stay Korean, so runs can still be compared line by line.
  translate.line("휘청 → light×2 피해 75, 옆 0, 내 피해 0")  → "stagger → light×2 dealt 75, others 0, took 0"

Two passes: RULES rewrite whole common lines into natural English; GLOSSARY then replaces remaining words (longest first).
Anything left untranslated stays as is — add it to GLOSSARY when it shows up on screen.
"""
from __future__ import annotations

import re

# (pattern, replacement) — applied in order to the whole line
RULES: list[tuple[str, str]] = [
    (r"^(.*): 락온 안 걸림 — 이 놈은 (\d+) m 안으로 다가가지 않는다", r"\1: no lock-on — won't go within \2 m of this one"),
    (r"^(.*): 끌어오기 (\d+)번 안 됨 — 맨 뒤로 미룬다", r"\1: lure failed \2× — moved to the back of the queue"),
    (r"^(.*): 끌어오기 (\d+)번 안 됨, 남은 게 이놈뿐 — 제자리에서 한 바퀴 더", r"\1: lure failed \2×, only one left — one more round from the spot"),
    (r"^물건 비켜 가기 \(지난 실행에서 (\d+)번 이상 부숨\): (.*)", r"steering around props (smashed \1+ times in earlier runs): \2"),
    (r"^⚠ 투척 나이프\(290\)가 퀵 슬롯에 없음 (.*)", r"⚠ throwing knife (290) not in a quick slot \1"),
    (r"^투척 나이프\(290\)가 퀵 슬롯에 없어서 (\d+)번째 빈 칸에 넣음 \(가진 수 (\d+)\) → 슬롯 (.*)",
     r"throwing knife (290) wasn't in a quick slot — put it in empty slot \1 (have \2) → slots \3"),
    (r"^붙는 중: 나 (\(.*?\)) → 목표 (\(.*?\)) \| 그놈 (\(.*?\)) 애니 (-?\d+), 거리 ([\d.]+)",
     r"closing in: me \1 → goal \2 | foe \3 anim \4, dist \5"),
    (r"^붙는 중: 나 (\(.*?\)) → 목표 (\(.*?\)) \| ([\d.]+) m 밖\(안 보임\)", r"closing in: me \1 → goal \2 | out of sight beyond \3 m"),
    (r"^(휘청|먼저 치기) → (\S+) 피해 (\d+), 옆 (\d+), 내 피해 (\d+)", lambda m: f"{'stagger punish' if m[1] == '휘청' else 'first strike'} → {m[2]} dealt {m[3]}, others {m[4]}, took {m[5]}"),
    (r"^목표 바꿈: (\d+) \(([\d.]+) m, 애니 (-?\d+)\) — 원래 목표 ([\d.]+) m", r"switch target: \1 (\2 m, anim \3) — original target \4 m"),
    (r"^원거리부터: (\d+) \(([\d.]+) m, 높이차 ([+-][\d.]+)\) — 원래 목표 ([\d.]+) m", r"ranged first: \1 (\2 m, height \3) — original target \4 m"),
    (r"^끼어든 (\d+) 처치 — 원래 목표로", r"interloper \1 killed — back to the original target"),
    (r"^에스트: 근처에 적 — 안 마심", r"Estus: foes nearby — not drinking"),
    (r"^▣ 블랙박스 #(\d+): ([\d.]+) s 동안 (-?\d+) → HP (\d+)/(\d+), 추정 (.*)", r"▣ black box #\1: \3 in \2 s → HP \4/\5, likely \6"),
    (r"^⚠ 퀵 종료: 둘러싸임 (\d+)명, HP (\d+)/(\d+), ([\d.]+) s 뒤 예상 (-?\d+)", r"⚠ quit-out: surrounded by \1, HP \2/\3, expected \5 in \4 s"),
    (r"^떼어놓기 (\d+): (.*) → (\w+)", r"separate #\1: \2 → \3"),
    (r"^(.*): 안 보임 — 가는 길에 이미 잡았거나 죽음", r"\1: not visible — already killed on the way, or dead"),
    (r"^(.*): 길 막은 (\w+) \((\w+)\) 부숨 시도 — (.*)", r"\1: smashing \2 (\3) blocking the path — \4"),
    (r"^(.*): 막힘 감지 \((\d+) s 동안 ([\d.]+) m 미만\) — 앞길에 (\w+) \((\w+), ([\d.]+) m\)",
     r"\1: stuck (under \3 m in \2 s) — \4 (\5) ahead, \6 m"),
    (r"^(.*): 점 못 감 \((\w+)\) — 앞길에 (\w+) \((\w+), ([\d.]+) m\)", r"\1: point missed (\2) — \3 (\4) ahead, \5 m"),
    (r"경로 재탐색 — 이어갈 점이 다른 층 \(Δy ([+-][\d.]+) m\), (\d+)점", lambda m: f"re-plan path — resume point on another level (Δy {m[1]} m), {m[2]} points"),
    (r"^후퇴 모드: (\w+)(?: \(가장 가까운 (\d+) ([\d.]+) m\))?", lambda m: f"retreat mode: {m[1]}" + (f" (nearest {m[2]} {m[3]} m)" if m[2] else "")),
    (r"^(.*): 적이 가깝고 HP (\d+) — 화톳불 쪽으로 물러남: (\w+)", r"\1: foes close, HP \2 — retreating toward the bonfire: \3"),
    (r"^(.*) 이동: 따라온 (\d+) — 찍어 둔 자리 (\(.*?\))로 가드 든 채 물러남: (\w+)", r"\1 move: chaser \2 — backing off to marked spot \3, guard up: \4"),
    (r"^(.*): 다가가지 않고 던질 자리에서 (\d+) s 기다림", r"\1: waiting \2 s at the throwing spot instead of approaching"),
    (r"^(.*) (\d+): 스폰 ([\d.]+) m 안인데 안 보임 — 이미 잡음, 걸어가지 않음", r"\1 \2: not visible within \3 m of its spawn — already killed, not walking there"),
    (r"^─+ (.*): (\S+)$", r"── \1: \2"),
    # 2026-10-01 — new lines (backstab R1 timing, wall retreat, two-hand combo, careful walk, crate detour, bloodstain)
    (r"^뒤잡기 R1: 판정 (\S+)·(\S+) m → 누른 직후 (\S+)·(\S+) m \(([\d.]+) s, 적 애니 (.*)\)",
     r"backstab R1: decided at \1·\2 m → just after \3·\4 m (\5 s, foe anim \6)"),
    (r"^벽 ([\d.]+) m — 강공\(수직\)", r"wall \1 m — vertical heavy"),
    (r"^방패병: 양손으로", r"shield soldier: switching to two hands"),
    (r"^양손 전환 안 됨 — 약공", r"two-hand switch failed — light attack"),
    (r"^셋 이상 붙음 — 벽으로 (\(.*?\)) ([\d.]+) s: (\w+), 벽까지 (\S+) m, 그 자리에서 하나씩",
     r"three or more on us — back to the wall \1 \2 s: \3, wall \4 m, one at a time here"),
    (r"^셋 이상 붙음 — 갈 벽 자리 없음 \(후보 (\d+)\), (\d+) s 동안 그 자리에서 싸움",
     r"three or more on us — no wall spot (\1 candidates), fighting here for \2 s"),
    (r"^경로가 (\w+) \((\w+)\) 위를 지나감 — 옆 ([\d.]+) m로 비켜 감", r"path crosses \1 (\2) — detouring \3 m to the side"),
    (r"^(.*): (\d+) 끌어오기 (\d+)번째 — (\w+)", r"\1: lure \2 (try \3) — \4"),
    (r"락온 안 걸림 — (\d+) m 까지 다가감", r"no lock-on — closing to \1 m"),
    (r"^카메라 정렬: 싸움 중 목표에서 중앙 (\d+)° · 90 % (\d+)° · (\d+)° 안 (\S+) \((\d+)번\)",
     r"camera alignment: off the fight target median \1° · 90 % \2° · within \3° \4 (\5 samples)"),
    (r"^기본 플레이: 방패 \+ 약공만 \(뒤잡기·강공 끔\)", r"basic play: shield + light only (backstab and heavy off)"),
    (r"^══ 구역 (\d+) \((\w+)\) 끝: (.*)", r"══ zone \1 (\2) done: \3"),
    (r"^(.*): 나이프 (\d+) \((.*?)\) → 피해 (\S+), 반응 없음 \| 락온 안 걸림 — 안 던짐 \(락온 없는 나이프는 오늘 (\S+)\)",
     r"\1: knife \2 (\3) → damage \4, no reaction | no lock-on — not thrown (knives without lock-on today \5)"),
    (r"^핏자국: (회수|못 주움) \(소울 (\d+) → (\S+)\)",
     lambda m: f"bloodstain: {'recovered' if m[1] == '회수' else 'not picked up'} (souls {m[2]} → {m[3]})"),
    # Asylum route (souls/asylum.py, run.py asylum) — step labels are left for GLOSSARY
    (r"^수용소 구간 (\d+): (\d+)단계 \((.*)\)", r"Asylum segment \1: \2 steps (\3)"),
    (r"^수용소: 첫 단계에서 (\d+) m — 가장 가까운 구간 (\d+)의 (\d+)번째 단계부터 이어감",
     r"Asylum: \1 m from the first step — resuming at step \3 of the nearest segment \2"),
    (r"^수용소(\d+) (\d+)/(\d+) ", r"Asylum\1 \2/\3 "),
    (r"^수용소(\d+) ", r"Asylum\1 "),
    (r"^\(퀵 종료 꺼짐\) 낙사 \(발밑 바닥 (\d+) m 아래\) — 나가지 않고 계속",
     r"(quit-out off) falling to death (floor \1 m below) — not quitting, carrying on"),
    (r"^\(퀵 종료 꺼짐\) 낙사 \(바닥 모름, 0\.8 s 에 ([\d.]+) m\) — 나가지 않고 계속",
     r"(quit-out off) falling to death (floor unknown, \1 m in 0.8 s) — not quitting, carrying on"),
    (r"^⚠ 모르는 무기 (\d+) — (.*) 사용법으로 \(souls/weapons\.py 에 추가할 것\)",
     r"⚠ unknown weapon \1 — using the \2 moveset (add it to souls/weapons.py)"),
]

# word / phrase → English, longest first (built at import)
GLOSSARY: dict[str, str] = {
    # places & route tags
    "성벽 마을(순서 고정)": "Undead Burg (fixed order)", "성벽 마을(귀환)": "Undead Burg (return)", "성벽 마을": "Undead Burg",
    "불의 제전": "Firelink Shrine", "경사로": "ramp", "상인 길": "merchant path", "상인": "merchant", "창고 방(귀환)": "storeroom (return)",
    "창고 방": "storeroom", "통로(귀환)": "passage (return)", "통로": "passage", "화톳불": "bonfire", "귀환 길": "return path",
    "공격 애니 중인 적 없음": "no foe mid-attack", "투사체·낙하·범위 밖?": "projectile / fall / out of range?",
    "칸 고르는 사이 적이 옴": "a foe came while picking the slot", "그놈부터": "that one first", "중단": "stopped", "접근": "approaching",
    "계단 위로 (안전 구역)": "up the stairs (safe zone)", "계단 위로": "up the stairs",
    "R3 때": "at R3", "몸": "body", "방향": "face",
    "끌어온": "lured", "더 가까이": "closer", "순서": "order", "벽까지": "to wall", "벽으로": "to the wall",
    "마을 정리": "town cleanup", "안개벽": "fog wall", "평지 구역": "flat zone", "평지": "flat ground", "꼭대기": "top",
    # actions
    "교전": "fight", "끌어오기": "lure", "이동": "move", "따라온": "chasing", "오는 놈": "incoming", "끼어든": "interloper", "처치": "killed",
    "목표 바꿈": "switch target", "원래 목표로": "back to original target", "원래 목표": "original target", "목표": "target",
    "먼저 치기": "first strike", "먼저치기": "first strike", "휘청반격": "stagger punish", "휘청돌기": "stagger turn", "휘청": "stagger",
    "막으며다가감": "guard-approach", "누움대기": "wait-downed", "기다림유지": "keep waiting", "기다림": "waiting", "반사": "reflex",
    "붙기": "approach", "돌기": "circle", "등뒤돌기": "circle behind", "뒤치기": "backstab", "뒤잡기": "backstab", "백스텝공격": "backstep attack",
    "백스텝 공격": "backstep attack", "백스텝": "backstep", "가장자리방어": "edge guard", "늦은windup막기": "late windup block",
    "빠른발차기": "quick kick", "빠른 발차기": "quick kick", "자리옮김": "reposition", "피함대기": "evade-wait", "안옴": "not coming",
    "떼어놓기": "separate", "부숨 시도": "smash", "부숨": "smash", "후퇴 모드": "retreat mode", "물러남": "retreat",
    "그림자 발차기": "shadow kick", "발차기": "kick", "약공": "light attack", "강공": "heavy attack", "연타": "hits",
    "나이프": "knife", "투척 나이프": "throwing knives", "락온": "lock-on", "조준": "aim", "움직임": "moved", "반응 없음": "no reaction",
    "휴식": "rest", "앉음": "sat", "에스트": "Estus", "안 마심": "not drinking", "수리": "repair", "핏자국": "bloodstain", "회수": "recover",
    "퀵 종료": "quit-out", "둘러싸임": "surrounded", "블랙박스": "black box", "위험 판정": "risk verdict", "결과": "result",
    "경계": "watch", "카메라": "camera", "텔레메트리 피드": "telemetry feed", "스타일": "style", "캐릭터": "character", "무기": "weapon",
    # states & words
    "싸우는 중": "fighting", "붙는 중": "closing in", "안 보임": "not visible", "보임": "visible", "죽음": "dead", "도착": "arrived",
    "끝까지": "to the end", "끝": "done", "됨": "ok", "안 됨": "failed", "실패": "failed", "없음": "none", "막힘": "stuck", "걸림": "caught",
    "근처에 적": "foes nearby", "적이 가깝고": "foes close", "가장 가까운": "nearest", "가까운": "near", "위험": "danger", "주의": "caution",
    "깨끗": "clean", "사망": "death", "낙사": "fell to death", "스폰": "spawn", "그놈 애니": "foe anim", "그놈": "foe", "내 애니": "my anim",
    "내 피해": "took", "준 피해": "dealt", "받은 피해": "taken", "피해": "damage", "공격": "attacks", "옆": "others", "애니": "anim",
    "거리": "dist", "높이차": "height", "높이": "dy", "각": "angle", "나": "me", "적": "foe", "망자": "Hollow", "방패 병사": "shield soldier",
    "석궁 병사": "crossbowman", "실제 상대": "actually fought", "번째": "#", "번 점": "point", "점": "point", "초": "s", "동안": "for",
    "미만": "under", "앞길에": "ahead:", "위치": "position", "밖": "outside", "안": "inside", "정면": "front", "추정": "likely",
    "평지와 높이차": "height vs flat ground", "평지에서 기다림": "waiting on flat ground", "찾아가지 않고": "not going after it,",
    "다가가지 않음": "not approaching", "다가가지 않고": "without approaching", "안전 구역": "safe zone", "제자리 고수 대상": "hold-position target",
    "지금 자리에서 찾아본다": "searching from here", "스폰에서": "from spawn", "그림자 발차기 후보": "shadow kick candidate",
    "그림자 발차기 결과": "shadow kick result", "안 함": "skipped", "잘림": "cut", "막기": "block", "마무리": "finish", "회복": "recover",
    "최저": "lowest", "큰 피격": "big hits", "범인": "culprits", "못 감": "missed", "레이더": "radar", "보내는 중": "sending",
    "브로드소드": "Broadsword", "닿는 거리": "reach", "안 씀": "unused", "씀": "used", "오른스틱": "right stick", "첫 펄스로 배움": "learned from the first pulse",
    "핸들": "handle", "세대": "generation", "예상": "expected", "다른 놈": "another foe", "깸": "woke", "마지막": "last", "귀환 지점": "return point",
    "바뀜": "changed", "모르는": "unknown", "뒤": "after", "명": "foes", "곳": "spot", "번": "×", "중": "in progress", "후보": "candidate",
    "화톳불로": "to the bonfire", "불의 제전으로": "to Firelink Shrine", "화톳불까지": "to the bonfire", "상인까지": "to the merchant",
    "내 HP": "my HP", "길로": "to the path", "길까지": "up to the path", "배틀 액스": "Battle Axe", "던질 자리로": "to the throwing spot",
    "제자리로": "back to the spot", "끊김": "lost", "개수 그대로": "count unchanged", "돌아서": "detour", "죽기직전": "near death",
    "강종": "force quit", "는 안전 구역 밖": "is outside the safe zone", "로": "to", "는": "", "에": "",
    "칸을 못 고름": "slot not selectable", "밴딧 나이프": "Bandit's Knife", "휘두를 때": "while it swings",
    "발밑 가장자리": "edge underfoot", "싸움 자리": "fight spot", "시작 자리": "start spot", "찍어 둔 자리": "marked spot",
    "가드 든 채": "guard up,", "맨 뒤로 미룬다": "moved to the back of the queue", "뒤잡기안함": "no-backstab",
    # Asylum step labels (data/routes/asylum-fresh.json) and souls/asylum.py words
    "감방: 열쇠 줍기·문 열기": "cell: pick up key · open door", "사다리 (감방 복도 → 뜰)": "ladder (cell corridor → courtyard)",
    "첫 화톳불 (1812960) 불 붙이기": "light the first bonfire (1812960)", "큰 방 문 (데몬 처음 나옴 → 도망)": "big hall door (demon appears → run)",
    "도망친 방 화톳불 (1812961)": "bonfire in the escape room (1812961)",
    "시작 장비 줍기 1: 방패 + 메뉴 장착 (확인, 항상 같음)": "starting gear 1: shield + equip in menu (verified, always the same)",
    "시작 장비 줍기 2: 배틀 액스 + 메뉴 장착 (확인, 항상 같음)": "starting gear 2: Battle Axe + equip in menu (verified, always the same)",
    "위층 문": "upstairs door", "굴러오는 바위 — 떨어져 피함 (확인)": "rolling boulder — drop down to dodge (verified)",
    "오스카 대화 (에스트·열쇠)": "talk to Oscar (Estus · key)", "위층 기사 뒤 A": "A behind the upstairs knight",
    "데몬 위 안개벽 → 떨어지며 치기 (들어가면 바로 뛰어내림)": "fog wall above the demon → plunging attack (jump right after entering)",
    "데몬 열쇠 줍기 (데몬 죽은 자리)": "pick up the demon's key (where it died)",
    "데몬 열쇠로 잠긴 문 열기 → 까마귀 쪽 (확인)": "open the locked door with the demon's key → toward the crow (verified)",
    "화톳불 목록에 추가": "added to bonfire list", "화톳불에서 못 일어남": "couldn't stand up from the bonfire",
    "방향 못 맞춤": "couldn't face the recorded heading", "끝 점까지": "to the end point", "걷기": "walk", "멈춤": "stopped",
    "안개벽 통과": "fog wall passed", "안개벽 못 지나감": "fog wall not passed", "가운데에서": "from center",
    "안 올라감": "not climbing", "올라감": "climbed", "다시": "again", "사다리": "ladder", "떨어지기": "drop",
    "메뉴 건너뜀": "menu skipped", "까마귀 장면 넘기기": "skipping the crow scene", "메뉴": "menu", "장착 확인": "equip check",
    "맞음": "correct", "이미": "already", "안 옮겨짐": "not moved", "까마귀": "crow", "양손 잡기": "two-hand grip", "안 바뀜": "unchanged",
    "떨어지며 치기": "plunging attack", "데몬 처치": "demon killed", "데몬 싸움 중 에스트": "Estus during the demon fight", "데몬": "demon",
    "에스트 없음": "no Estus", "왼손1": "left hand 1", "오른손1": "right hand 1", "방패": "shield",
    "사용자 중지": "stopped by user", "입력 중립": "inputs neutral", "퀵 종료 안 함": "no quit-out", "오류로 멈춤": "stopped on error",
    "소울": "souls", "인간성": "humanity", "반지": "rings", "왼손": "left hand", "양손": "two-handed", "잡기": "grip", "원함": "want",
}
# short entries (≤ 2 syllables) only as whole words, so "나" doesn't eat the start of "나가지"
_GLOSS = [(ko, en, re.compile(f"(?<![\uac00-\ud7a3]){re.escape(ko)}(?![\uac00-\ud7a3])") if len(ko) <= 2 else None)
          for ko, en in sorted(GLOSSARY.items(), key=lambda kv: -len(kv[0]))]
_RULES = [(re.compile(p), r) for p, r in RULES]
_HANGUL = re.compile("[가-힣]")


def line(s: str | None) -> str | None:
    """Translate one display line (or tag). Non-Korean text passes through unchanged."""
    if not s or not _HANGUL.search(s):
        return s
    lead = s[:len(s) - len(s.lstrip())]                # the bot indents its lines — '^' rules never matched an indented one
    s = s[len(lead):]
    for rx, rep in _RULES:
        m = rx.search(s)
        if m:
            s = rx.sub(rep, s, count=1)
            break
    s = lead + s
    if _HANGUL.search(s):
        for ko, en, rx in _GLOSS:
            if ko in s:
                s = rx.sub(en, s) if rx else s.replace(ko, en)
    return s
