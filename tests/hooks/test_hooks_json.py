"""Registration pins for hooks/hooks.json, read by Claude Code and Codex.

A hook that is registered but cannot start fails open exactly like one
that crashes, so the wiring is pinned as carefully as the guards.
"""

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import hook_lib

_ROOT = Path(__file__).resolve().parents[2]
_HOOKS: dict[str, list[dict[str, Any]]] = json.loads(
    (_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8")
)["hooks"]
# Both clients expand ${CLAUDE_PLUGIN_ROOT} (Codex sets it for compatibility
# alongside its own PLUGIN_ROOT), so it is the one spelling that serves both.
_COMMAND = re.compile(r'^"\$\{CLAUDE_PLUGIN_ROOT\}/hooks/([\w.-]+)"$')


def _registrations() -> list[tuple[str, str, str]]:
    return [
        (event, group.get("matcher", ""), hook["command"])
        for event, groups in _HOOKS.items()
        for group in groups
        for hook in group["hooks"]
    ]


def _script(command: str) -> Path:
    match = _COMMAND.fullmatch(command)
    assert match, f"not a plugin-root hook command: {command}"
    return _ROOT / "hooks" / match.group(1)


@pytest.mark.parametrize(("event", "matcher", "command"), _registrations())
def test_every_registered_script_exists_and_is_executable(
    event: str, matcher: str, command: str
) -> None:
    script = _script(command)
    assert script.is_file(), script
    assert os.access(script, os.X_OK), f"{script} lost its exec bit"


def test_the_guards_are_wired_to_the_tools_they_guard() -> None:
    wired = {
        (event, matcher, _script(command).name)
        for event, matcher, command in _registrations()
    }
    assert wired == {
        ("SessionStart", "", "session-context.sh"),
        ("PreToolUse", "Bash", "pipe-status-guard.sh"),
        ("PreToolUse", "Bash", "tea-guard.sh"),
        ("PreToolUse", "Write|Edit|apply_patch", "decisions_status_guard.py"),
    }


def _probe(matcher: str, script: str, root: Path) -> dict[str, Any]:
    """A payload the registered guard must deny, run from *root*."""
    log = root / "docs" / "decisions.md"
    if script == "decisions_status_guard.py":
        return {
            "cwd": str(root),
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(log),
                "old_string": "**Status:** Proposed",
                "new_string": "**Status:** Accepted",
            },
        }
    command = {
        "pipe-status-guard.sh": "make test | tail -5",
        "tea-guard.sh": "tea issues 1",
    }[script]
    return {
        "cwd": str(root),
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


_GUARDS = [r for r in _registrations() if r[0] == "PreToolUse"]


def _run_guard(
    matcher: str, command: str, root: Path, path_prefix: Path | None = None
) -> dict[str, Any]:
    """Run a registered guard on its probe; return its decision envelope.

    Expanded and run through a shell the way the clients invoke it.
    *path_prefix* goes first on PATH, so its ``python3`` is the one both
    the prefilters and the ``env python3`` shebang find.
    """
    (root / ".git").mkdir()
    (root / "docs").mkdir()
    (root / "docs" / "decisions.md").write_text(
        "## ADR-0001 — x\n\n**Status:** Proposed\n", encoding="utf-8"
    )
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(_ROOT)}
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["sh", "-c", command],
        cwd=root,
        env=env,
        input=json.dumps(_probe(matcher, _script(command).name, root)),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    decision: dict[str, Any] = json.loads(result.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny", decision
    return decision


@pytest.mark.parametrize(("event", "matcher", "command"), _GUARDS)
def test_the_registered_command_denies_end_to_end(
    event: str, matcher: str, command: str, tmp_path: Path
) -> None:
    # A hook that cannot start, or whose prefilter drops what it should
    # pass on, would fail open in a session and in silence — here it fails
    # the test.
    _run_guard(matcher, command, tmp_path)


@pytest.fixture(scope="session")
def python3_dir(
    pytestconfig: pytest.Config, tmp_path_factory: pytest.TempPathFactory
) -> Callable[[str], Path]:
    """A directory whose ``python3`` is CPython *version*, fetched by uv.

    Fetched into the pytest cache (a temporary directory when the cache is
    disabled), with HOME, the XDG directories and uv's own pointed there as
    well, so the real global install is never touched and a warm cache
    skips the download.
    """
    cache = getattr(pytestconfig, "cache", None)
    root = (
        cache.mkdir("python3") if cache else tmp_path_factory.mktemp("python3")
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("UV_")}
    env |= {
        key: str(root / key.lower())
        for key in (
            "XDG_CACHE_HOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_BIN_HOME",
            "UV_CACHE_DIR",
            "UV_PYTHON_INSTALL_DIR",
        )
    }
    env["HOME"] = str(root)
    uv = Path(sys.executable).with_name("uv")

    def run_uv(*args: str) -> str:
        result = subprocess.run(
            [str(uv), *args],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def fetch(version: str) -> Path:
        run_uv("python", "install", "--no-bin", version)
        found = run_uv(
            "python", "find", "--no-project", "--managed-python", version
        )
        bin_dir = root / f"bin-{version}"
        bin_dir.mkdir(exist_ok=True)
        (bin_dir / "python3").unlink(missing_ok=True)
        (bin_dir / "python3").symlink_to(found)
        return bin_dir

    return fetch


@pytest.mark.parametrize("version", ["3.9", "3.10"])
@pytest.mark.parametrize(("event", "matcher", "command"), _GUARDS)
def test_the_registered_command_holds_the_python_floor(
    event: str,
    matcher: str,
    command: str,
    version: str,
    tmp_path: Path,
    python3_dir: Callable[[str], Path],
) -> None:
    # The hooks run under whatever python3 a client finds first on PATH,
    # not under this venv's. Below the floor a guard cannot even import,
    # and a crash fails open, so each must deny naming the floor; at the
    # floor each must reach its own verdict, which keeps the floor honest.
    floor = f"need Python {hook_lib.FLOOR[0]}.{hook_lib.FLOOR[1]} or newer"
    reason = _run_guard(matcher, command, tmp_path, python3_dir(version))[
        "permissionDecisionReason"
    ]
    below = tuple(map(int, version.split("."))) < hook_lib.FLOOR
    assert (floor in reason) == below, reason


def test_session_context_is_injected_verbatim(tmp_path: Path) -> None:
    [(_, _, command)] = [r for r in _registrations() if r[0] == "SessionStart"]
    result = subprocess.run(
        ["sh", "-c", command],
        cwd=tmp_path,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(_ROOT)},
        input="{}",
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    context = (_ROOT / "hooks" / "session-context.md").read_text(
        encoding="utf-8"
    )
    assert result.stdout == context


def test_session_context_stays_small() -> None:
    # It is injected into every session in every repository the plugin is
    # installed for; anything longer belongs in a skill.
    context = (_ROOT / "hooks" / "session-context.md").read_text(
        encoding="utf-8"
    )
    assert len(context) <= 1200
