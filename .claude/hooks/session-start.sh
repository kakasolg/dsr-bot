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

# Cloud sessions start from `main`, which lags the work branch by hundreds of commits — say so up front
# (printed text reaches the session's context). Never fails the hook.
WORK=claude/dsr-bot-project-review-r3hh9f
if git fetch -q origin "$WORK" 2>/dev/null; then
  behind=$(git rev-list --count HEAD..FETCH_HEAD 2>/dev/null || echo 0)
  if [ "$behind" -gt 0 ]; then
    echo "NOTE: this checkout is $behind commits behind origin/$WORK (the work branch, see CLAUDE.md)."
    echo "      Bring it in before working: git merge --ff-only FETCH_HEAD   (or git merge FETCH_HEAD if HEAD has its own commits)"
  fi
fi
