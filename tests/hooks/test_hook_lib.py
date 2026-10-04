"""Unit pins for hook_lib: the shell tokenizer, payload parsing and paths.

Every Bash guard reads commands through this tokenizer, so a regression
here blinds all of them at once — and a blind PreToolUse guard fails open,
silently. The guard suites cover it end to end; these name the cases.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from hook_lib import (
    changed_paths,
    command_text,
    effective_tool,
    simple_commands,
)

_PAYLOADS: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "codex_hook_payloads.json").read_text(
        encoding="utf-8"
    )
)


def _names(text: str) -> list[str]:
    return [name for name, _ in simple_commands(text)]


def _tool(command: str) -> str:
    [(name, args)] = list(simple_commands(command))
    return effective_tool(name, args)[0]


# --- the tokenizer: every line, never a heredoc body -----------------------


def test_a_command_on_a_later_line_is_still_seen() -> None:
    # shlex treats a newline as ordinary WHITESPACE, so a single pass would
    # splice every line into one segment and see only the first command.
    assert _names("echo starting\nmake test") == ["echo", "make"]


def test_separators_split_simple_commands() -> None:
    assert _names("a | b && c; d || e & f") == ["a", "b", "c", "d", "e", "f"]


def test_env_assignments_are_not_the_command_word() -> None:
    assert _names("FOO=1 BAR=2 make test") == ["make"]


def test_a_heredoc_body_is_data_not_commands() -> None:
    # A commit message quoting a guarded form is prose, not an invocation.
    text = "git commit -F - <<'EOF'\nnever run `tea issues 1`\nEOF\nls"
    assert _names(text) == ["git", "ls"]


def test_a_here_string_does_not_swallow_the_rest() -> None:
    # `<<<` starts no body — it is a one-line argument in both shells. The
    # heredoc regex once matched at its second `<` and dropped everything
    # after, so one here-string blinded every guard for the whole command.
    assert _names("grep -c x <<< 'data'\nmake test") == ["grep", "make"]


def test_an_unbalanced_line_is_skipped_not_fatal() -> None:
    assert _names("echo 'unclosed\nmake test") == ["make"]


def test_a_quoted_command_is_an_argument() -> None:
    assert _names("grep -rn 'make test | tail' docs/") == ["grep"]


# --- effective_tool: runners and precommand modifiers ----------------------


@pytest.mark.parametrize(
    "command",
    [
        "uv run pytest -q",
        "uv run --no-sync pytest",
        "poetry run pytest",
        "python3 -m pytest",
        "python3.13 -m pytest",
        "uvx pytest",
        "time pytest",
        "noglob pytest",
        "nocorrect pytest",
        "sudo pytest",
        "nice -n 10 pytest",
        "env FOO=1 pytest",
        "sudo uv run pytest",
    ],
)
def test_wrappers_unwrap_to_the_real_tool(command: str) -> None:
    assert _tool(command) == "pytest"


def test_command_dash_v_is_a_lookup_not_a_run() -> None:
    # `command -v make` invokes nothing; unwrapping it would read a probe
    # as an invocation.
    assert _tool("command -v make") == "command"


def test_the_tools_own_v_flag_is_not_a_lookup() -> None:
    # The lookup test reads the PREFIX's flags only; scanning every argument
    # would read `pytest -v` as a lookup and stop unwrapping.
    assert _tool("sudo pytest -v") == "pytest"


# --- command_text: string and argv shapes -----------------------------------


def test_argv_wrapper_yields_the_script_it_runs() -> None:
    ti = {"command": ["bash", "-lc", "make test | tail -5"]}
    assert command_text(ti) == "make test | tail -5"


def test_plain_argv_is_joined_with_quoting() -> None:
    assert command_text({"command": ["echo", "a b"]}) == "echo 'a b'"


def test_missing_command_is_empty() -> None:
    assert command_text({}) == ""


# --- changed_paths: Claude edits and Codex patches --------------------------


def test_apply_patch_yields_every_changed_path(tmp_path: Path) -> None:
    payload: dict[str, Any] = {
        "cwd": str(tmp_path),
        "tool_name": "apply_patch",
        "tool_input": {
            "command": "*** Begin Patch\n"
            "*** Update File: old.py\n"
            "*** Move to: moved.py\n"
            "@@\n-old\n+new\n"
            "*** Add File: added.py\n+new\n"
            "*** Delete File: deleted.py\n"
            "*** End Patch"
        },
    }
    assert set(changed_paths(payload)) == {
        tmp_path / "old.py",
        tmp_path / "moved.py",
        tmp_path / "added.py",
        tmp_path / "deleted.py",
    }


def test_a_relative_edit_path_resolves_against_the_payload_cwd(
    tmp_path: Path,
) -> None:
    payload: dict[str, Any] = {
        "cwd": str(tmp_path),
        "tool_name": "Edit",
        "tool_input": {"file_path": "docs/x.md"},
    }
    assert changed_paths(payload) == [tmp_path / "docs" / "x.md"]


# --- captured Codex payloads (real, not constructed) ------------------------
#
# Every other test builds its payloads from the same assumption the hooks
# make, so the suite alone could not detect a schema mismatch. These were
# captured from a live Codex session (codex-cli 0.160.0) by wrapping the
# registered hooks to record their stdin, and sanitised of host paths and
# session identifiers. Re-capture after a Codex upgrade that touches hooks.


def test_captured_payloads_name_the_tools_the_guards_branch_on() -> None:
    # The decisions guard branches on these literals: a different spelling
    # would make an arm unreachable while every matcher still fired.
    assert _PAYLOADS["PreToolUse:Bash"]["tool_name"] == "Bash"
    assert _PAYLOADS["PreToolUse:apply_patch"]["tool_name"] == "apply_patch"


def test_captured_shell_payload_carries_a_plain_string_command() -> None:
    # Codex runs it through a `-lc` wrapper, but the wrapper does not reach
    # the hook — so the guards scan exactly what the model asked for.
    payload = _PAYLOADS["PreToolUse:Bash"]
    command = payload["tool_input"]["command"]
    assert isinstance(command, str)
    assert not command.startswith("/bin/")
    assert command_text(payload["tool_input"]) == command


def test_captured_patch_payload_resolves_against_its_own_cwd() -> None:
    payload = _PAYLOADS["PreToolUse:apply_patch"]
    assert payload["cwd"] == "/repo"
    assert changed_paths(payload) == [Path("/repo/probe_tmp.txt")]
