#!/usr/bin/env bash
# SessionStart hook that prunes stale session temp dirs. The rules live in
# prune_session_tmp.py, pinned by tests/hooks/test_prune_session_tmp.py.
# This wrapper exists for the flags: Python starts with `-E -s`, so the
# session's Python environment cannot stop the pruner (AGENTS.md, "Rules").

set -euo pipefail

exec python3 -E -s "$(dirname "${BASH_SOURCE[0]}")/prune_session_tmp.py"
