"""lint-repo, the target hooks and CI run, still runs lint-shell."""

import os
import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
# Extends devkit's gate.sh list (MAKEFLAGS, MFLAGS, MAKELEVEL, MAKEFILES) with
# GNUMAKEFLAGS: keeps an outer make's jobserver, or an injected makefile, out
# of the run.
_MAKE_ENV = ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEFILES", "GNUMAKEFLAGS")


def _lint_repo_rules() -> tuple[int, str, list[str]]:
    """Return make's exit status, its stderr and the `lint-repo:` rule lines.

    -n runs no recipe; only the parse-time devkitw lookup executes. -p dumps
    the environment, so stdout and the environment stay inside this helper:
    neither can reach an assert, a failure message or a `-l` locals dump.
    """
    made = subprocess.run(
        ["make", "-pn", "lint-repo"],
        cwd=_ROOT,
        env={k: v for k, v in os.environ.items() if k not in _MAKE_ENV},
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        timeout=60,
    )
    rules = re.findall(r"^lint-repo:(.*)$", made.stdout, re.M)
    return made.returncode, made.stderr, rules


def test_lint_repo_runs_lint_shell() -> None:
    returncode, stderr, rules = _lint_repo_rules()
    if returncode:
        pytest.fail(stderr, pytrace=False)
    assert len(rules) == 1, rules
    prereqs = rules[0].split()
    assert "lint-shell" in prereqs
    # Were devkit's target renamed, the Makefile's own line would still
    # define a lint-repo whose only prerequisite is lint-shell.
    assert set(prereqs) - {"lint-shell"}
