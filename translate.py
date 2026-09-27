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
    (r"^후퇴 모드: (\w+)(?: \(가장 가까운 (\d+) ([\d.]+) m\))?", lambda m: f"retreat mode: {m[1]}" + (f" (nearest {m[2]} {m[3]} m)" if m[2] else "")),
    (r"^(.*): 적이 가깝고 HP (\d+) — 화톳불 쪽으로 물러남: (\w+)", r"\1: foes close, HP \2 — retreating toward the bonfire: \3"),
    (r"^(.*) 이동: 따라온 (\d+) — 찍어 둔 자리 (\(.*?\))로 가드 든 채 물러남: (\w+)", r"\1 move: chaser \2 — backing off to marked spot \3, guard up: \4"),
    (r"^(.*): 다가가지 않고 던질 자리에서 (\d+) s 기다림", r"\1: waiting \2 s at the throwing spot instead of approaching"),
    (r"^(.*) (\d+): 스폰 ([\d.]+) m 안인데 안 보임 — 이미 잡음, 걸어가지 않음", r"\1 \2: not visible within \3 m of its spawn — already killed, not walking there"),
    (r"^─+ (.*): (\S+)$", r"── \1: \2"),
]

# word / phrase → English, longest first (built at import)
GLOSSARY: dict[str, str] = {
    # places & route tags
    "성벽 마을(순서 고정)": "Undead Burg (fixed order)", "성벽 마을(귀환)": "Undead Burg (return)", "성벽 마을": "Undead Burg",
    "불의 제전": "Firelink Shrine", "경사로": "ramp", "상인 길": "merchant path", "상인": "merchant", "창고 방(귀환)": "storeroom (return)",
    "창고 방": "storeroom", "통로(귀환)": "passage (return)", "통로": "passage", "화톳불": "bonfire", "귀환 길": "return path",
    "마을 정리": "town cleanup", "안개벽": "fog wall", "평지 구역": "flat zone", "평지": "flat ground", "꼭대기": "top",
    # actions
    "교전": "fight", "끌어오기": "lure", "이동": "move", "따라온": "chasing", "오는 놈": "incoming", "끼어든": "interloper", "처치": "killed",
    "목표 바꿈": "switch target", "원래 목표로": "back to original target", "원래 목표": "original target", "목표": "target",
    "먼저 치기": "first strike", "먼저치기": "first strike", "휘청반격": "stagger punish", "휘청돌기": "stagger turn", "휘청": "stagger",
    "막으며다가감": "guard-approach", "누움대기": "wait-downed", "기다림유지": "keep waiting", "기다림": "waiting", "반사": "reflex",
    "붙기": "approach", "돌기": "circle", "등뒤돌기": "circle behind", "뒤치기": "backstab", "백스텝공격": "backstep attack",
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
    for rx, rep in _RULES:
        m = rx.search(s)
        if m:
            s = rx.sub(rep, s, count=1)
            break
    if _HANGUL.search(s):
        for ko, en, rx in _GLOSS:
            if ko in s:
                s = rx.sub(en, s) if rx else s.replace(ko, en)
    return s
