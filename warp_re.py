"""다크사인·뼛조각·화톳불 워프를 게임이 어떻게 하는지 메모리로 관찰한다 — safe_warp 를 게임 방식에 맞추려고 (2026-09-25).

  python warp_re.py [--secs 90]      → data/trace/warp_re_<시각>.jsonl + 화면 요약

**읽기만 한다.** 사람이 그동안 다크사인을 쓰면 된다.
20 Hz 로 본다: 내 좌표·HP·애니, 메뉴 플래그, 구역별 캐릭터 목록 크기, ChrClassWarp·WorldChrMan 구조체의 4바이트 칸들.
요약: 로딩(플레이어 없음) 구간, 그 전후로 값이 바뀐 칸 — 자주 흔들리는 칸(카운터·타이머)은 뺀다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import env
import dsr_telemetry as D

ROOT = Path(__file__).resolve().parent
REGIONS = {"ChrClassWarp": 0xC00, "WorldChrMan": 0x200}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=90.0)
    a = ap.parse_args()
    tm = env.make_telemetry({})
    out = ROOT / "data" / "trace" / f"warp_re_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
    fh = out.open("w", encoding="utf-8")
    print(f"기록 → {out} ({a.secs:.0f} s) — 다크사인을 써 주세요", flush=True)
    prev: dict = {}
    changes: dict = {}
    t0 = time.time()
    loading = None
    while time.time() - t0 < a.secs:
        t = round(time.time() - t0, 2)
        row: dict = {"t": t}
        try:
            pp = tm.player_ptr()
            p = tm.read_chr(pp) if pp else None
        except Exception:
            p = None
        row["me"] = None if not p else [round(p.x, 2), round(p.y, 2), round(p.z, 2), p.hp, p.anim]
        try:
            row["menu"] = tm.pm.read_uchar(tm.base + D.OFF_MENU_FLAG)
        except Exception:
            row["menu"] = None
        w = None
        try:
            w = tm.world_chr_man()
            row["lists"] = [(tm.i32(tm.q(w + o) + 0x0) if w and tm.q(w + o) else None) for o in D.CHR_LIST_OFFSETS]
        except Exception:
            row["lists"] = None
        row["lastbon"] = tm.last_bonfire()
        now_loading = row["me"] is None
        if now_loading != loading:
            print(f"[{t:6.2f}] {'로딩 시작 (플레이어 없음)' if now_loading else '플레이어 있음'}  {row['me']}", flush=True)
            loading = now_loading
        for name, n in REGIONS.items():
            base = tm.q(tm.static[name]) if name == "ChrClassWarp" else w
            if not base:
                continue
            try:
                raw = tm.pm.read_bytes(base, n)
            except Exception:
                continue
            for o in range(0, n, 4):
                k = f"{name}+{o:#x}"
                v = int.from_bytes(raw[o:o + 4], "little")
                if k in prev and prev[k] != v:
                    changes.setdefault(k, []).append((t, prev[k], v))
                    row.setdefault("diff", {})[k] = [prev[k], v]
                prev[k] = v
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        time.sleep(0.05)
    fh.close()
    print("\n── 바뀐 칸 (10번 이하로 바뀐 것만 — 카운터·타이머 제외) ──")
    for k, ch in sorted(changes.items(), key=lambda kv: kv[1][0][0]):
        if len(ch) <= 10:
            print(f"  {k:<22} " + "  ".join(f"[{t:.2f}] {a:#x}→{b:#x}" for t, a, b in ch[:5]))


if __name__ == "__main__":
    main()
