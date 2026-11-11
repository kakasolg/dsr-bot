"""Viewer camera director (MoKa M1111-34): sim/godot/cam_director_check.gd on made-up routes, headless — sections in order,
switches held apart, stacked floors, ladder side shot and hand-back to the route direction. Also checks that the scene
builder's cam_path tags are not noise (no section shorter than CAM_MIN_RUN points) when a built scene is present.
Skipped without Godot. The director's own rules only — not how the picture looks.   python tests/godot_viewcam_test.py"""
from __future__ import annotations
import sys as _sys, pathlib as _pl
_sys.path[:0] = [str(_pl.Path(__file__).resolve().parent.parent), str(_pl.Path(__file__).resolve().parent.parent / "sim")]

import json
import subprocess

import pytest

import godot_link as GL

ROOT = _pl.Path(__file__).resolve().parent.parent


def test_director_rules():
    if not GL.GODOT.exists():
        pytest.skip("no Godot")
    r = subprocess.run([str(GL.GODOT), "--headless", "--path", str(GL.PROJECT), "-s", "res://cam_director_check.gd"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    print(r.stdout)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "cam_director_check: 0 failed" in r.stdout


def test_scene_sections_not_noise():
    import burg_scene
    found = False
    for name in ("burg", "firelink_taurus", "firelink_demon"):
        f = GL.PROJECT / "assets" / f"{name}_scene.json"
        if not f.exists():
            continue
        P = json.loads(f.read_text(encoding="utf-8")).get("cam_path")
        if not P:
            continue
        found = True
        runs, k = [], 0
        while k < len(P):
            j = k
            while j < len(P) and P[j][4] == P[k][4]:
                j += 1
            runs.append(j - k)
            k = j
        assert min(runs[1:] or [99]) >= burg_scene.CAM_MIN_RUN, (name, runs)
    if not found:
        pytest.skip("no built scene with cam_path (python sim/burg_scene.py)")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-s"]))
