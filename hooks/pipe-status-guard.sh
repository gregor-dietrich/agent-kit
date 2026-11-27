#!/usr/bin/env bash
# PreToolUse prefilter for the Bash pipe-status guard. The rule (never read
# an exit status through a pipe — `make test | tail` reports tail's status,
# so a red gate reads as green) lives in pipe_status_guard.py, pinned by
# tests/hooks/test_pipe_status_guard.py. This wrapper only keeps the hot
# path cheap: a command with no pipe at all cannot trip the rule and exits
# here without paying an interpreter spawn. Conservative by construction:
# any pipe character falls through to the real tokenizing checks in Python.
# `-E` makes Python ignore PYTHONPATH and PYTHONHOME, and `-s` leaves out the
# user site: a module on PYTHONPATH named like a stdlib one, a PYTHONHOME
# that points nowhere, or startup code in the user site (a `.pth` file, a
# usercustomize.py) would otherwise crash the guard open before it reads
# the call. The script's own directory stays importable.

set -euo pipefail

input=$(cat)
case "$input" in
*"|"*) ;;
*) exit 0 ;;
esac

printf '%s' "$input" |
	python3 -E -s "$(dirname "${BASH_SOURCE[0]}")/pipe_status_guard.py"
