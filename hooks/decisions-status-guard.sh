#!/usr/bin/env bash
# PreToolUse guard for the edit tools (Status is the author's). The rules
# live in decisions_status_guard.py, pinned by
# tests/hooks/test_decisions_status_guard.py.
# This wrapper exists for the flags: Python starts with `-E -s`, so the
# session's Python environment cannot crash the guard open (AGENTS.md,
# "Rules").

set -euo pipefail

exec python3 -E -s "$(dirname "${BASH_SOURCE[0]}")/decisions_status_guard.py"
