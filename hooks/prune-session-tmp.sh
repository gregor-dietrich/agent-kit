#!/usr/bin/env bash
# SessionStart hook that prunes stale session temp dirs. The rules live in
# prune_session_tmp.py, pinned by tests/hooks/test_prune_session_tmp.py.
# This wrapper exists for the flags: `-E` makes Python ignore PYTHONPATH and
# PYTHONHOME, and `-s` leaves out the user site. A module on PYTHONPATH
# named like a stdlib one, a PYTHONHOME that points nowhere, or startup
# code in the user site (a `.pth` file, a usercustomize.py) would otherwise
# stop the hook before it starts. The script's own directory stays importable.

set -euo pipefail

exec python3 -E -s "$(dirname "${BASH_SOURCE[0]}")/prune_session_tmp.py"
