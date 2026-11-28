#!/usr/bin/env bash
# PreToolUse prefilter for the Bash commit guard. The rule (a git commit or
# git merge message must not carry a closing or reopen keyword before an
# issue reference, nor be one the guard cannot read) lives in
# commit_guard.py, pinned by tests/hooks/test_commit_guard.py and
# tests/hooks/test_text_forms.py. This wrapper only keeps the hot path
# cheap: commands that do not mention git together with commit or merge —
# the vast majority — exit here without paying an interpreter spawn.
# Conservative by construction: any mention at all falls through to the
# real tokenizing checks in Python.
# Python starts with `-E -s`, so the session's Python environment cannot
# crash the guard open (AGENTS.md, "Rules").

set -euo pipefail

input=$(cat)
case "$input" in
*git*)
	case "$input" in
	*commit* | *merge*) ;;
	*) exit 0 ;;
	esac
	;;
*) exit 0 ;;
esac

printf '%s' "$input" |
	python3 -E -s "$(dirname "${BASH_SOURCE[0]}")/commit_guard.py"
