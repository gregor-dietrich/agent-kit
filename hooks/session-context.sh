#!/usr/bin/env bash
# SessionStart hook: put the delegation rules that must hold on every
# dispatch into context. Everything else agent-kit carries is a skill,
# loaded when its task comes up; a dispatch happens mid-task, where no
# skill would be invoked first. Plain stdout is added to the session's
# context by Claude Code and Codex; Antigravity sends a camelCase JSON
# payload and reads an injectSteps JSON envelope on stdout.
set -euo pipefail

dir="$(dirname "${BASH_SOURCE[0]}")"
input=""
if [[ ! -t 0 ]]; then
	input="$(cat)"
fi

case "$input" in
*'"hookEventName"'* | *'"conversationId"'*)
	python3 -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    text = fh.read()
print(json.dumps({"injectSteps": [{"systemMessage": {"systemMessage": text}}]}))
' "$dir/session-context.md"
	;;
*)
	cat "$dir/session-context.md"
	;;
esac
