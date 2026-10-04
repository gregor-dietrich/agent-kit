"""Registration pins for hooks/hooks.json, read by Claude Code and Codex.

A hook that is registered but cannot start fails open exactly like one
that crashes, so the wiring is pinned as carefully as the guards.
"""

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

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
        ("PreToolUse", "Bash", "pipe-status-guard.sh"),
        ("PreToolUse", "Bash", "tea-guard.sh"),
        ("PreToolUse", "Bash", "decisions-status-guard.sh"),
        ("PreToolUse", "Write|Edit|apply_patch", "decisions-status-guard.sh"),
    }


def _probe(matcher: str, script: str, root: Path) -> dict[str, Any]:
    """A payload the registered guard must deny, run from *root*."""
    log = root / "docs" / "decisions.md"
    if script == "decisions-status-guard.sh" and matcher != "Bash":
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
        "decisions-status-guard.sh": "echo x >> docs/decisions.md",
    }[script]
    return {
        "cwd": str(root),
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


@pytest.mark.parametrize(("event", "matcher", "command"), _registrations())
def test_the_registered_command_denies_end_to_end(
    event: str, matcher: str, command: str, tmp_path: Path
) -> None:
    # Expanded and run through a shell the way the clients invoke it, with
    # a payload this guard must deny: a hook that cannot start, or whose
    # prefilter drops what it should pass on, would fail open in a session
    # and in silence — here it fails the test.
    (tmp_path / ".git").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "decisions.md").write_text(
        "## ADR-0001 — x\n\n**Status:** Proposed\n", encoding="utf-8"
    )
    payload = _probe(matcher, _script(command).name, tmp_path)
    result = subprocess.run(
        ["sh", "-c", command],
        cwd=tmp_path,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(_ROOT)},
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert '"permissionDecision": "deny"' in result.stdout
