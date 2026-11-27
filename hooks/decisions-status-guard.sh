#!/usr/bin/env bash
# PreToolUse guard for the edit tools (Status is the author's). The rules
# live in decisions_status_guard.py, pinned by
# tests/hooks/test_decisions_status_guard.py.
# This wrapper exists for the flags: `-E` makes Python ignore PYTHONPATH and
# PYTHONHOME, and `-s` leaves out the user site. A module on PYTHONPATH
# named like a stdlib one, a PYTHONHOME that points nowhere, or startup
# code in the user site (a `.pth` file, a usercustomize.py) would otherwise
# crash the guard open before it reads the call. The script's own directory
# stays importable.

set -euo pipefail

exec python3 -E -s "$(dirname "${BASH_SOURCE[0]}")/decisions_status_guard.py"
