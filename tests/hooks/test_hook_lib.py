"""Unit pins for hook_lib: the shell tokenizer, payload parsing and paths.

Every Bash guard reads commands through this tokenizer, so a regression
here blinds all of them at once — and a blind PreToolUse guard fails open,
silently. The guard suites cover it end to end; these name the cases.
"""

import json
from pathlib import Path
from typing import Any

import pytest

import hook_lib
from hook_lib import (
    changed_paths,
    command_text,
    effective_tool,
    is_antigravity_payload,
    payload_cwd,
    simple_commands,
    tool_input,
    tool_name,
)

_PAYLOADS: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "codex_hook_payloads.json").read_text(
        encoding="utf-8"
    )
)
_AGY_PAYLOADS: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "agy_hook_payloads.json").read_text(
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


def _multiline(text: str) -> list[tuple[str, list[str]]]:
    return list(simple_commands(text, multiline=True))


def test_multiline_keeps_a_quoted_argument_whole() -> None:
    assert _multiline("tea comment 5 'a\nb'") == [
        ("tea", ["comment", "5", "a\nb"])
    ]
    assert _names("tea comment 5 'a\nb'") == []


def test_multiline_still_sees_a_command_after_the_argument() -> None:
    assert [n for n, _ in _multiline("echo 'a\nb'\nmake test")] == [
        "echo",
        "make",
    ]


def test_multiline_backslash_newline_continues_a_line() -> None:
    assert _multiline("make \\\ntest") == [("make", ["test"])]


def test_multiline_apostrophes_in_comments_open_no_quote() -> None:
    # Two comments with one apostrophe each once read as one quoted span,
    # which hid every command between them.
    text = "echo a # don't\nmake test\ncd x;# can't\necho b"
    assert [n for n, _ in _multiline(text)] == ["echo", "make", "cd", "echo"]


def test_multiline_keeps_a_hash_inside_a_word() -> None:
    # shlex alone reads `owner/repo#3` as `owner/repo` plus a comment.
    assert _multiline("tea comment 5 see owner/repo#3 now") == [
        ("tea", ["comment", "5", "see", "owner/repo#3", "now"])
    ]


def test_multiline_reads_a_quoted_heredoc_operator_as_text() -> None:
    # `<<` inside quotes starts no heredoc; read as one, it swallowed the
    # rest of the command.
    text = 'echo "cout << x\nmore"\nmake test'
    assert [n for n, _ in _multiline(text)] == ["echo", "make"]


def test_multiline_still_drops_an_unquoted_heredoc_body() -> None:
    text = "git commit -F - <<'EOF'\nit's `tea issues 1`\nEOF\nls"
    assert [n for n, _ in _multiline(text)] == ["git", "ls"]


def test_multiline_unbalanced_quote_falls_back_to_physical_lines() -> None:
    text = "echo 'unclosed\nmake test"
    assert [n for n, _ in _multiline(text)] == ["make"]


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


def test_command_text_falls_back_and_prefers_agy_command_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert command_text({"command": "", "CommandLine": "echo hi"}) == "echo hi"
    assert (
        command_text({"command": None, "CommandLine": "echo hi"}) == "echo hi"
    )
    monkeypatch.setattr(hook_lib, "_ANTIGRAVITY_MODE", True)
    assert (
        command_text(
            {"command": "echo safe", "CommandLine": "make test | tail -5"}
        )
        == "make test | tail -5"
    )


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


# --- captured Antigravity payloads (agy 1.5.16) -----------------------------
#
# agy 1.5.16 CLI emits write_file/edit_file; the 4 IDE-era tools
# (write_to_file, replace_file_content, multi_replace_file_content, sed_file)
# remain defensively handled.


def test_captured_antigravity_payloads_parse_through_shared_helpers() -> None:
    run_cmd = _AGY_PAYLOADS["PreToolUse:run_command"]
    assert is_antigravity_payload(run_cmd)
    assert not is_antigravity_payload(_PAYLOADS["PreToolUse:Bash"])
    assert tool_name(run_cmd) == "run_command"
    assert command_text(tool_input(run_cmd)) == "echo hi | cat"

    write_p = _AGY_PAYLOADS["PreToolUse:write_file"]
    assert tool_name(write_p) == "write_file"
    assert changed_paths(write_p) == [Path("/repo/notes.md")]

    edit_p = _AGY_PAYLOADS["PreToolUse:edit_file"]
    assert tool_name(edit_p) == "edit_file"
    assert changed_paths(edit_p) == [Path("/repo/notes.md")]


def test_antigravity_target_file_and_workspace_cwd_fallback(
    tmp_path: Path,
) -> None:
    payload: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "workspacePaths": [str(tmp_path)],
        "toolCall": {
            "name": "replace_file_content",
            "args": {"TargetFile": "docs/decisions.md"},
        },
    }
    assert payload_cwd(payload) == tmp_path
    assert changed_paths(payload) == [tmp_path / "docs" / "decisions.md"]
    empty_args: dict[str, Any] = {
        "toolCall": {"name": "write_file", "args": "bad"}
    }
    assert tool_input(empty_args) == {}
    assert changed_paths(empty_args) == []


def test_antigravity_path_and_target_file_handling(tmp_path: Path) -> None:
    decoy_str: dict[str, Any] = {
        "cwd": str(tmp_path),
        "toolCall": {
            "name": "replace_file_content",
            "args": {
                "Path": "README.md",
                "TargetFile": "docs/decisions.md",
            },
        },
    }
    assert changed_paths(decoy_str) == [
        tmp_path / "README.md",
        tmp_path / "docs" / "decisions.md",
    ]
    non_str: dict[str, Any] = {
        "cwd": str(tmp_path),
        "toolCall": {
            "name": "replace_file_content",
            "args": {"Path": 1, "TargetFile": "docs/decisions.md"},
        },
    }
    assert changed_paths(non_str) == [tmp_path / "docs" / "decisions.md"]
    dup: dict[str, Any] = {
        "cwd": str(tmp_path),
        "toolCall": {
            "name": "replace_file_content",
            "args": {
                "Path": "docs/decisions.md",
                "TargetFile": "./docs/decisions.md",
            },
        },
    }
    assert changed_paths(dup) == [tmp_path / "docs" / "decisions.md"]
