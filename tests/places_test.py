"""구역 이름·적 라벨 오프라인 테스트 — places.py ([MoKa] 2026-10-01: "구역과 이름을 특정하기 힘들어서").

  python tests/places_test.py
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # repo root first (the bot's modules), then this folder
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent)]

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import places


def test_zones() -> None:
    assert places.zone(-54.0, -60.0, 58.0) == "Firelink bonfire"
    assert places.zone(-54.0, -60.0, 58.0, en=False) == "불의 제전 화톳불"
    assert places.zone(-28.1, -13.4, -58.8) == "town #4 street (packs)"           # where 09-30b / 10-01a died
    assert places.zone(-39.2, -19.8, -67.8) == "merchant"
    assert places.zone(-30.0, -49.25, 29.0) == "ramp flat"
    assert places.zone(-28.1, 40.0, -58.8) is None                               # right x/z, wrong level
    print("ok  zones: Firelink bonfire / town #4 street / merchant / ramp flat; other level → none")


def test_labels() -> None:
    L = places.Labels(spawns={("경사로", "ramp"): [{"npc": 255010, "pos": [-23.4, -49.67, 16.15]}]},
                      msb=[(254010, (-28.0, -13.4, -58.0), "c2540_0012"), (254010, (60.0, -13.4, 60.0), "c2540_0099")])
    shield = {"ptr": 1, "npc": 255010, "x": -22.0, "y": -49.6, "z": 17.0}
    assert L.of(shield) == "ramp#1 shield" and L.of(shield, en=False) == "경사로#1 방패병"
    shield.update(x=10.0, z=10.0)                                                # wanders off — keeps its name
    assert L.of(shield) == "ramp#1 shield"
    hollow = {"ptr": 2, "npc": 254010, "x": -27.0, "y": -13.4, "z": -57.0}
    assert L.of(hollow) == "hollow-12"
    lost = {"ptr": 3, "npc": 254010, "x": 0.0, "y": -13.4, "z": 0.0}
    assert L.of(lost) == "hollow?"
    twin = {"ptr": 5, "npc": 255010, "x": -22.5, "y": -49.6, "z": 16.5}            # a second one at the same spawn
    assert L.of(twin) != "ramp#1 shield", L.of(twin)
    assert L.of({"ptr": 4, "npc": 255002, "x": 0.0, "y": 0.0, "z": 0.0}).startswith("crossbow")
    print("ok  labels: mission spawn → ramp#1 shield (kept when it wanders) · other → MSB number · none → '?'")


def test_real_data() -> None:
    L = places.Labels()
    town4 = {"ptr": 9, "npc": 254010, "x": -1.83, "y": -10.02, "z": -64.24}
    assert L.of(town4) == "town#4 hollow", L.of(town4)
    print(f"ok  real data: town #4 spawn → {L.of(town4)!r}, {len(L.msb)} game-file placements, {len(places.ZONES)} zones")


if __name__ == "__main__":
    test_zones()
    test_labels()
    test_real_data()
    print("전부 통과")
