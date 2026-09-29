"""asylum_steps.build 오프라인 테스트 — 녹화(월드 + 패드)에서 걷기·누르기(연타 묶음)·메뉴·사다리·싸움·점프 단계를 뽑는다.

  python tests/asylum_steps_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import asylum_steps as A


def w(ms, pos, enemies=()):
    return {"k": "w", "ms": ms, "p": {"pos": list(pos)}, "e": [dict(id=f"h{i}", vt="enemy", npc=npc, hp_raw=hp) for i, npc, hp in enemies]}


def pad(ms, btn):
    return {"k": "pad", "ms": ms, "btn": btn}


def test_build() -> None:
    ws, pads = [], []
    # 0-4 s: walk x 0 → 8 with B held; A ×3 at x=8 (0.3 s apart); menu START RIGHT A B
    for i in range(41):
        ws.append(w(i * 100, (min(i * 0.2, 8.0), 0.0, 0.0)))
    pads += [pad(0, 0x2000), pad(3900, 0)]
    pads += [pad(4000, 0x1000), pad(4100, 0), pad(4300, 0x1000), pad(4400, 0), pad(4600, 0x1000), pad(4700, 0)]
    pads += [pad(5000, 0x0010), pad(5100, 0), pad(5300, 0x0008), pad(5400, 0), pad(5600, 0x1000), pad(5700, 0), pad(5900, 0x2000), pad(6000, 0)]
    # 6-8 s: ladder — off mesh, y 0 → 5
    for i in range(1, 11):
        ws.append(w(6000 + i * 200, (8.0, i * 0.5, 0.0)))
    # 8-10 s: walk on top, an enemy loses HP twice (one fight), then a 50 m jump
    for i in range(1, 11):
        ws.append(w(8000 + i * 200, (8.0 + i * 0.3, 5.0, 0.0), enemies=[(1, 250000, 75 - min(i, 2) * 40)]))
    ws.append(w(10400, (60.0, 5.0, 0.0)))
    on_mesh = lambda x, y, z: not (x == 8.0 and 0.0 < y < 5.0)
    steps = A.build(ws, pads, on_mesh, mks=[{"k": "mk", "ms": 4200}])
    kinds = [s["type"] for s in steps]
    assert kinds[0] == "walk" and steps[0]["run"] and steps[0]["pts"][-1][0] >= 6.0, steps[0]
    pr = next(s for s in steps if s["type"] == "press")
    assert pr["n"] == 3, pr                                               # 연타 묶음
    mn = next(s for s in steps if s["type"] == "menu")
    assert mn["keys"] == ["START", "RIGHT", "A", "B"], mn
    cl = next(s for s in steps if s["type"] == "climb")
    assert cl["from"][1] < 1.0 and cl["to"][1] >= 4.5, cl
    fi = [s for s in steps if s["type"] == "fight"]
    assert len(fi) == 1 and fi[0]["npc"] == 250000 and fi[0]["killed"], fi
    assert kinds[-1] == "jump" and steps[-1]["to"][0] == 60.0, steps[-1]
    mk = [s for s in steps if s["type"] == "mark"]
    assert len(mk) == 1 and mk[0]["n"] == 1 and mk[0]["pos"][0] == 8.0, mk
    assert not any(k.startswith("_") for s in steps for k in s), steps
    print(f"ok  {kinds}")


if __name__ == "__main__":
    test_build()
    print("전부 통과")
