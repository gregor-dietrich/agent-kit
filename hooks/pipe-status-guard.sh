#!/usr/bin/env bash
# PreToolUse prefilter for the Bash pipe-status guard. The rule (never read
# an exit status through a pipe — `make test | tail` reports tail's status,
# so a red gate reads as green) lives in pipe_status_guard.py, pinned by
# tests/hooks/test_pipe_status_guard.py. This wrapper only keeps the hot
# path cheap: a command with no pipe at all cannot trip the rule and exits
# here without paying an interpreter spawn. Conservative by construction:
# any pipe character falls through to the real tokenizing checks in Python.

set -euo pipefail

input=$(cat)
case "$input" in
*"|"*) ;;
*) exit 0 ;;
esac

printf '%s' "$input" |
	python3 "$(dirname "${BASH_SOURCE[0]}")/pipe_status_guard.py"
