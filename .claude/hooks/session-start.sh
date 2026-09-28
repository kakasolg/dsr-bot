#!/bin/bash
# Claude Code on the web: Python 3.12 venv with the offline-test dependencies
# (Windows-only pymem/vgamepad are skipped — see ROADMAP.md P-1).
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"
VENV="$CLAUDE_PROJECT_DIR/.venv"

if [ ! -x "$VENV/bin/python" ]; then
  uv venv "$VENV" --python 3.12 -q
fi
grep -viE '^(pymem|vgamepad)==' requirements-lock.txt > /tmp/dsr-bot-req.txt
uv pip install -q --python "$VENV/bin/python" -r /tmp/dsr-bot-req.txt pytest

echo "export VIRTUAL_ENV=\"$VENV\"" >> "$CLAUDE_ENV_FILE"
echo "export PATH=\"$VENV/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
