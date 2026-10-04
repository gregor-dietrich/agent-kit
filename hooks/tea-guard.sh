#!/usr/bin/env bash
# PreToolUse prefilter for the Bash tea guard. The rule (a single-entity
# issue/PR read must carry --comments — every other tea view hides them)
# lives in tea_guard.py, pinned by tests/hooks/test_tea_guard.py. This
# wrapper only keeps the hot path cheap: commands that never mention tea —
# the vast majority — exit here without paying an interpreter spawn.
# Conservative by construction: any mention at all falls through to the
# real tokenizing checks in Python.

set -euo pipefail

input=$(cat)
case "$input" in
*tea*) ;;
*) exit 0 ;;
esac

printf '%s' "$input" |
	python3 "$(dirname "${BASH_SOURCE[0]}")/tea_guard.py"
