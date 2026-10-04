#!/usr/bin/env bash
# PreToolUse prefilter for the decisions-log status guard (Write|Edit/
# apply_patch, Bash). The real guard lives in decisions_status_guard.py,
# pinned by tests/hooks/test_decisions_status_guard.py (what it blocks and
# why is documented there and in its module docstring). This wrapper exists
# only to keep the hot path cheap: hooks fire on EVERY matched tool call in
# every repository, and an interpreter spawn (~20-50 ms) is real money
# there, so the vast majority of payloads — which cannot concern
# docs/decisions.md at all — are dropped by a bash substring test before
# Python starts. Conservative by construction: ANY mention of
# "decisions.md" in the payload falls through to the exact checks in Python.

set -euo pipefail

input=$(cat)
case "$input" in
*decisions.md*) ;;
*) exit 0 ;;
esac

printf '%s' "$input" |
	python3 "$(dirname "${BASH_SOURCE[0]}")/decisions_status_guard.py"
