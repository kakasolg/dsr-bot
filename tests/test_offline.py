"""pytest entry for the offline tests — each tests/*_test.py is a standalone script (python tests/x_test.py still works);
here every one of them runs as its own pytest case from the repo root and must exit 0.

  python -m pytest tests            all
  python -m pytest tests -k radar   one
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = sorted(p.name for p in Path(__file__).resolve().parent.glob("*_test.py"))


@pytest.mark.parametrize("script", SCRIPTS)
def test_script(script: str) -> None:
    r = subprocess.run([sys.executable, str(Path("tests") / script)], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    assert r.returncode == 0, f"{script} exited {r.returncode}\n--- stdout ---\n{r.stdout[-4000:]}\n--- stderr ---\n{r.stderr[-4000:]}"
