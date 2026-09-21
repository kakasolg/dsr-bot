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
}


@dataclass
class Playbook:
    version: int = 1
    retreat_hp_pct: float = 0.35      # 이 아래면 직전 웨이포인트로 후퇴
    flask_hp_pct: float = 0.50        # 이 아래고 근처에 적 없으면 성배병
    crowd_threshold: int = 3          # 20 m 내 적이 이만큼이면 스프린트
    flee_distance: float = 12.0       # avoid 타입이 이 거리 안에 오면 후퇴
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
    elif k == "crowd_threshold":
        val = int(v) if op == "set" else pb.crowd_threshold + int(v)
        lo, hi = BOUNDS[k]
        if not (lo <= val <= hi):
            return None
        new.crowd_threshold = val
    elif k == "avoid_types":
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
    rs = [r["seconds"] for r in results(version)]
    return statistics.median(rs) if rs else None
