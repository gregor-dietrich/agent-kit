#!/usr/bin/env bash
# PreToolUse prefilter for the Bash tea guard. The rules (a single-entity
# issue/PR read must carry --comments — every other tea view hides them;
# a comment or PR write must not carry a closing or reopen keyword before
# an issue reference, nor text the guard cannot read) live in tea_guard.py,
# pinned by tests/hooks/test_tea_guard.py. This wrapper only keeps the hot
# path cheap: commands that never mention tea — the vast majority — exit
# here without paying an interpreter spawn. Conservative by construction:
# any mention at all falls through to the real tokenizing checks in Python.
# `-E` makes Python ignore PYTHONPATH and PYTHONHOME, and `-s` leaves out the
# user site: a module on PYTHONPATH named like a stdlib one, a PYTHONHOME
# that points nowhere, or startup code in the user site (a `.pth` file, a
# usercustomize.py) would otherwise crash the guard open before it reads
# the call. The script's own directory stays importable.

set -euo pipefail

input=$(cat)
case "$input" in
*tea*) ;;
*) exit 0 ;;
esac

printf '%s' "$input" |
	python3 -E -s "$(dirname "${BASH_SOURCE[0]}")/tea_guard.py"
