"""
플레이북 — 봇이 "배우는" 대상. 자유 텍스트가 아니라 **범위가 정해진 파라미터**만 있다.
복기(postmortem)가 제안하는 수정도 이 범위 안에서만 허용된다 (LLM 을 붙여도 마찬가지).

버전마다 data/playbook/v<N>.json 으로 저장하고, 어떤 버전으로 몇 초 살았는지 성적을 기록한다.
"""
from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIR = ROOT / "data" / "playbook"

# 파라미터 범위 (min, max). 제안이 이 밖이면 거부.
BOUNDS = {
    "retreat_hp_pct": (0.20, 0.60),
    "flask_hp_pct": (0.30, 0.80),
    "crowd_threshold": (2, 5),
    "flee_distance": (6.0, 20.0),
    "avoid_types_max": (0, 8),
    "stamina_walk_pct": (0.10, 0.50),
    "attack_range": (1.2, 3.0),
    "attack_cooldown": (0.8, 4.0),
    "hold_range": (1.5, 5.0),
    "lock_range": (3.0, 12.0),
    "stam_backoff": (0.10, 0.50),
    "stam_resume": (0.45, 0.95),
    "retreat_dist": (6.0, 30.0),
    "slow_radius": (0.0, 30.0),
    "bomb_min_dist": (4.0, 15.0),
    "bombs_per_episode": (0, 6),
    "bomb_min_enemies": (1, 4),
}
MODES = ("walk", "sprint", "guardjump")


@dataclass
class Playbook:
    version: int = 1
    retreat_hp_pct: float = 0.35      # 이 아래면 직전 웨이포인트로 후퇴
    flask_hp_pct: float = 0.50        # 이 아래고 근처에 적 없으면 성배병
    crowd_threshold: int = 3          # 20 m 내 적이 이만큼이면 스프린트
    flee_distance: float = 12.0       # avoid 타입이 이 거리 안에 오면 후퇴
    mode_open: str = "sprint"          # 적 없을 때 이동 모드
    mode_near_enemy: str = "guardjump" # 적 20 m 안일 때 이동 모드 (가드+점프 전진: 빠르고 점프 무적+가드 보호)
    stamina_walk_pct: float = 0.25     # 스태미나가 이 아래면 걷기로 회복
    # ── DSR 전투 (사용자 원칙: 막고 → 한 대) ──
    attack_range: float = 1.8          # 적이 이 안이면 RB 한 대
    attack_cooldown: float = 2.0       # 한 대 치고 이만큼은 가드
    hold_range: float = 2.5            # 적이 이 안이면 전진을 멈추고 가드한 채 싸운다
    lock_range: float = 6.0            # 적이 이 안에 오면 락온(R3), 두 배 밖으로 나가면 해제
    # 스태미나·후퇴 (사용자: "HP·스태미나 관리가 이 게임 전투의 핵심")
    stam_backoff: float = 0.30         # 스태미나가 이 아래면 교전을 멈추고 물러나 회복
    stam_resume: float = 0.70          # 이만큼 차면 다시 붙는다
    retreat_dist: float = 18.0         # HP 가 낮아 후퇴할 때 지나온 길을 따라 물러나는 거리 (m)
    slow_radius: float = 20.0          # 전에 맞은 자리 이 반경 안에서는 아주 천천히 (0 이면 끔)
    # 파이어밤 — 사용자 교리: 적이 보이면 안전한 곳으로 물러나 멀리서 깎는다
    use_bombs: bool = False            # 기본 꺼짐. 켜고 끈 판을 비교해서 실제로 도움이 되는지 본다
    bomb_min_dist: float = 7.0         # 가장 가까운 적이 이보다 멀 때만 던진다 (던지는 데 2 s 걸린다)
    bombs_per_episode: int = 2         # 한 판에 이만큼만. 보급이 어렵다 (50 소울, 성벽 마을 상인까지 가야 함)
    bomb_min_enemies: int = 2          # 15 m 안에 적이 이만큼일 때만 — 하나는 근접으로 충분하다          # 전에 맞은 자리 이 반경 안에서는 아주 천천히 (0 이면 끔)
    pull_one: bool = False             # 다수면 하나만 끌어내기(뒤로 빠지기) — 실측상 모퉁이에서 후퇴가 막혀 죽음. 기본 꺼짐
    flee_on_second: bool = False       # 교전 중 둘째가 3 m 붙으면 도망 — 같은 이유로 기본 꺼짐
    avoid_types: list[int] = field(default_factory=list)   # 보이면 피하는 NpcParamId
    sprint_segments: list[int] = field(default_factory=list)  # 항상 달려서 지나가는 웨이포인트 구간
    rejected: list[str] = field(default_factory=list)  # 롤백된 제안의 change_id (다시 제안하지 않음)
    change: str = ""   # 이 버전을 만든 제안의 change_id
    note: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=1)

    @staticmethod
    def from_json(s: str) -> "Playbook":
        d = json.loads(s)
        return Playbook(**{k: v for k, v in d.items() if k in Playbook.__dataclass_fields__})


def set_dir(path: Path) -> None:
    """A/B 실험용 — 플레이북 버전·성적을 별도 디렉터리에 둔다 (learn.py --arm). 두 팔의 v8 이 서로의 중앙값에 섞이지 않게."""
    global DIR, RESULTS
    DIR = Path(path)
    RESULTS = DIR / "results.jsonl"


def load_current() -> Playbook:
    DIR.mkdir(parents=True, exist_ok=True)
    cur = DIR / "current.json"
    if cur.exists():
        return Playbook.from_json(cur.read_text(encoding="utf-8"))
    pb = Playbook()
    save(pb)
    return pb


def save(pb: Playbook) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"v{pb.version}.json").write_text(pb.to_json(), encoding="utf-8")
    (DIR / "current.json").write_text(pb.to_json(), encoding="utf-8")


def load_version(v: int) -> Playbook:
    return Playbook.from_json((DIR / f"v{v}.json").read_text(encoding="utf-8"))


# ── 제안 적용 ──
def apply(pb: Playbook, change: dict) -> Playbook | None:
    """change = {"key": ..., "op": "set"|"add"|"append", "value": ..., "why": ...}. 범위 밖이면 None."""
    new = Playbook(**asdict(pb))
    new.version = pb.version + 1
    new.note = change.get("why", "")
    new.change = change_id(change)
    k, op, v = change["key"], change.get("op", "set"), change["value"]
    if k in ("retreat_hp_pct", "flask_hp_pct", "flee_distance"):
        cur = getattr(pb, k)
        val = float(v) if op == "set" else cur + float(v)
        lo, hi = BOUNDS[k]
        if not (lo <= val <= hi):
            return None
        setattr(new, k, round(val, 3))
    elif k in ("pull_one", "flee_on_second", "use_bombs"):
        if getattr(pb, k) == bool(v):
            return None
        setattr(new, k, bool(v))
    elif k in ("mode_open", "mode_near_enemy"):
        if v not in MODES or getattr(pb, k) == v:
            return None
        setattr(new, k, v)
    elif k in ("stamina_walk_pct", "attack_range", "attack_cooldown", "hold_range", "lock_range",
               "stam_backoff", "stam_resume", "retreat_dist", "slow_radius", "bomb_min_dist"):
        val = float(v) if op == "set" else getattr(pb, k) + float(v)
        lo, hi = BOUNDS[k]
        if not (lo <= val <= hi):
            return None
        setattr(new, k, round(val, 3))
    elif k in ("bombs_per_episode", "bomb_min_enemies"):
        val = int(v) if op == "set" else getattr(pb, k) + int(v)
        lo, hi = BOUNDS[k]
        if not (lo <= val <= hi) or val == getattr(pb, k):
            return None
        setattr(new, k, val)
    elif k == "crowd_threshold":
        val = int(v) if op == "set" else pb.crowd_threshold + int(v)
        lo, hi = BOUNDS[k]
        if not (lo <= val <= hi):
            return None
        new.crowd_threshold = val
    elif k == "avoid_types":
        if op == "remove":
            if int(v) not in pb.avoid_types:
                return None
            new.avoid_types = [t for t in pb.avoid_types if t != int(v)]
        else:
            if int(v) in pb.avoid_types or len(pb.avoid_types) >= BOUNDS["avoid_types_max"][1]:
                return None
            new.avoid_types = pb.avoid_types + [int(v)]
    elif k == "sprint_segments":
        if int(v) in pb.sprint_segments:
            return None
        new.sprint_segments = sorted(pb.sprint_segments + [int(v)])
    else:
        return None
    return new


def change_id(change: dict) -> str:
    return f"{change['key']}:{change.get('op', 'set')}:{change['value']}"


# ── 성적 ──
RESULTS = DIR / "results.jsonl"


def record_result(pb_version: int, seed: int, seconds: float, laps: int, reason: str, extra: dict | None = None) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": round(time.time(), 1), "version": pb_version, "seed": seed, "seconds": round(seconds, 1),
                            "laps": laps, "reason": reason, **(extra or {})}, ensure_ascii=False) + "\n")


def results(version: int | None = None) -> list[dict]:
    if not RESULTS.exists():
        return []
    rows = [json.loads(l) for l in RESULTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r for r in rows if version is None or r["version"] == version]


def median_survival(version: int) -> float | None:
    rs = [r["seconds"] for r in results(version) if r.get("reason") != "stall"]   # 멈춤(입력 불능)은 플레이북 탓이 아니다
    return statistics.median(rs) if rs else None
