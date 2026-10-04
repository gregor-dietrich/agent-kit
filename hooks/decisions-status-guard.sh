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
# "decisions.md" in the payload falls through to the exact checks in Python,
# and so does an Edit/Write whose file_path resolves to the log through a
# symlink — a lexical test alone would wave that edit through unseen.

set -euo pipefail

input=$(cat)
case "$input" in
*decisions.md*) ;;
*'"file_path"'*)
	# Escaped quotes inside a JSON string never match '"file_path": "',
	# so this reads the tool_input field and not a mention in content.
	path=$(printf '%s' "$input" |
		sed -n 's/.*"file_path": *"\([^"]*\)".*/\1/p')
	resolved=$(realpath -m -- "$path" 2>/dev/null || true)
	[[ -n "$path" && "$resolved" == */docs/decisions.md ]] || exit 0
	;;
*) exit 0 ;;
esac

printf '%s' "$input" |
	python3 "$(dirname "${BASH_SOURCE[0]}")/decisions_status_guard.py"
