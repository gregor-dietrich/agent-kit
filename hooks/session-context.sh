#!/usr/bin/env bash
# SessionStart hook: put the delegation rules that must hold on every
# dispatch into context. Everything else agent-kit carries is a skill,
# loaded when its task comes up; a dispatch happens mid-task, where no
# skill would be invoked first. Plain stdout is added to the session's
# context by both Claude Code and Codex.
set -euo pipefail
cat "$(dirname "${BASH_SOURCE[0]}")/session-context.md"
