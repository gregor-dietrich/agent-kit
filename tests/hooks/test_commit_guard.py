"""Behavioral pin for the Bash commit guard hook (``hooks/``).

Runs the real hook — the bash prefilter wrapper plus ``commit_guard.py`` —
as a subprocess with crafted tool JSON. Load-bearing like every hook's
pin: a crashed PreToolUse hook fails OPEN in the harness, so a broken
guard denies nothing and nothing else would notice. (The guard exists
because a closing keyword before an issue reference closes that issue
wherever it stands, a commit message included, and a commit message admits
no deliberate ``Closes #N`` line.)
"""

import json
import os
import subprocess
from pathlib import Path

import pytest
from bash_hook import run_agy_command_hook, run_bash_hook

_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _ROOT / "hooks" / "commit-guard.sh"


def _reason(command: str) -> str:
    """The deny reason the hook gives for *command*, or "" when it passes."""
    out = run_bash_hook(_HOOK, command)
    decision = json.loads(out)["hookSpecificOutput"] if out else {}
    return decision.get("permissionDecisionReason", "")


_HEREDOC = 'git commit -m "$(cat <<{delim}\n{body}\nEOF\n)"'
_KEYWORD = "closing or reopen keyword"
_EXPANSION = "shell expansion"
_FILE = "taken from -F/--file"
_EDITOR = "takes its message from an editor"


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m 'Fixes #3'",
        "git commit -am 'fix #3'",
        "git commit --message='resolves #3'",
        "git commit --message 'resolves #3'",
        "git commit -m'closes #3'",
        "git commit -amcloses#3",
        "git commit -m ok -m 'fixes #3'",
        "git -C d commit -m 'fixes #3'",
        "git commit --amend -m 'fixes #3'",
        "git merge topic -m 'closes #3'",
        "git merge -m 'closes #3' topic",
        "git commit --trailer 'Fixes: #3' -m ok",
        "git commit --trailer='Fixes: #3' -m ok",
        "git commit -m 'closes owner/repo#3'",
        "git commit -m ok --fixup=amend:X -m 'fixes #3'",
        _HEREDOC.format(delim="'EOF'", body="line one\nthis reopened #3"),
        _HEREDOC.format(delim='"EOF"', body="reopened #3"),
        # the command word behind a wrapper or shell structure
        "env X=1 git commit -m 'fixes #3'",
        "command git commit -m 'fixes #3'",
        "(git commit -m 'fixes #3')",
        "git add . && git commit -m 'fixes #3'",
        'if true; then git commit -m "fixes #3"; fi',
        "{ git commit -m 'fixes #3'; }",
        "! git commit -m 'fixes #3'",
        # a redirect in front of the command word
        "2>&1 git commit -m 'fixes #3'",
        ">/dev/null git commit -m 'fixes #3'",
        "x=$(git commit -m 'fixes #3')",
        # a trailer is recorded as `token: value`
        "git commit -m ok --trailer 'Closes=#3'",
        "git commit -m ok --trailer=Fixes=#3",
        "git commit -m ok --trailer 'Fixes = #3'",
        "git commit -m ok --trailer 'Fixes :#3'",
        # a descriptor before the message, an escaped space, real newlines
        "git commit -m 2>/dev/null 'fixes #3'",
        "git commit -m fixes\\ #3",
        'git commit -m "Title\n\nfixes #3"',
        _HEREDOC.format(delim="-'EOF'", body="line one\nfixes #3"),
    ],
)
def test_a_closing_keyword_is_denied(command: str) -> None:
    assert _KEYWORD in _reason(command)


@pytest.mark.parametrize(
    ("command", "why"),
    [
        ('git commit -m "$x"', _EXPANSION),
        ('git commit -m "$(cat msg)"', _EXPANSION),
        ("git commit -m `cat msg`", _EXPANSION),
        ('git merge topic -m "$x"', _EXPANSION),
        (_HEREDOC.format(delim="EOF", body="hello"), _EXPANSION),
        ("git commit -F msg", _FILE),
        ("git commit -F -", _FILE),
        ("git commit -Fmsg", _FILE),
        ("git commit -aF msg", _FILE),
        ("git commit --file msg", _FILE),
        ("git commit --file=msg", _FILE),
        ("git merge topic -F msg", _FILE),
        ("git commit -F", _FILE),
        ("git commit", _EDITOR),
        ("git commit -a", _EDITOR),
        ("git commit --amend", _EDITOR),
        ("git commit --squash=HEAD", _EDITOR),
        ("git commit --squash HEAD", _EDITOR),
        ("git commit --fixup=amend:HEAD", _EDITOR),
        ("git commit --fixup reword:HEAD", _EDITOR),
        ("git commit --trailer 'A: b'", _EDITOR),
        ("git commit -e -m ok", _EDITOR),
        ("git commit --edit -m ok", _EDITOR),
        ("git commit -c HEAD", _EDITOR),
        ("git commit --reedit-message=HEAD", _EDITOR),
        ("git commit --no-edit -c HEAD", _EDITOR),
        ("git merge -e topic", _EDITOR),
        ("git merge --edit topic", _EDITOR),
        ("git commit -unormal", _EDITOR),
        # `$` and a backtick are unreadable even where the shell keeps them
        ("git commit -m $'[tag] Add X\\n\\nFixes #3'", _EXPANSION),
        ("git commit -m 'costs $5'", _EXPANSION),
        ("git commit -m 'a $ b'", _EXPANSION),
        ("git commit -m 'Move `foo` into lib'", _EXPANSION),
        # a template is a file, unless a message or -C settles it
        ("git commit -t m", _FILE),
        ("git commit -t m --no-edit --allow-empty-message", _FILE),
        ("git commit --template=m --no-edit", _FILE),
        ("git commit --file", _FILE),
    ],
)
def test_a_message_the_guard_cannot_read_is_denied(
    command: str, why: str
) -> None:
    assert why in _reason(command)


def test_the_deny_reasons_name_the_subcommand_and_the_match() -> None:
    assert "git merge would record 'closes #3'" in _reason(
        "git merge t -m 'closes #3'"
    )
    assert "git merge takes" in _reason("git merge -e t")
    assert "('$x')" in _reason('git commit -m "$x"')
    assert "('msg')" in _reason("git commit -F msg")
    assert "('m')" in _reason("git commit -t m")
    assert "git merge -m" in _reason('git merge t -m "$x"')
    assert "git merge -m" in _reason("git merge t -F msg")
    assert "git commit -m" in _reason("git commit -F msg")


def test_the_checks_run_file_editor_expansion_keyword() -> None:
    assert _FILE in _reason("git commit -F msg -m 'fixes #3' -e")
    assert _EDITOR in _reason('git commit -e -m "$x"')
    assert _EXPANSION in _reason("git commit -m \"$x\" -m 'fixes #3'")


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m 'address #3'",
        "git commit -m 'prefix #3'",
        "git commit -m 'hotfix #3, fixes the parser'",
        "git commit -m ''",
        # a value-less -m is a git usage error, not a message to read
        "git commit -m",
        "git commit -am",
        "git commit -m ok -- 'fix #3.txt'",
        "git commit -m ok --trailer 'Co-Authored-By: x'",
        "git commit -m ok --trailer 'Co-Authored-By: x <a=b>'",
        "git commit -h",
        "git commit --help",
        "git --help commit",
        "git -h commit",
        "git commit -Cdeadbeef",
        "git commit -tfile -m ok",
        "git commit -t m -C HEAD",
        "git merge -Xtheirs topic",
        "git merge -sresolve topic",
        "git commit --message",
        # a placeholder-like token too long to be one
        f"git commit -m '\x1f{'1' * 5000}\x1f'",
        "git commit -uno -m ok",
        "git commit -Skey -m ok",
        "git commit -S -m ok",
        "git commit -sam ok",
        "git commit -m ok --author 'A <a@b>'",
        "git commit -m 'ok' --date=now --cleanup strip",
        "git commit --amend --no-edit",
        "git commit -C HEAD",
        "git commit --reuse-message=HEAD",
        "git commit --fixup=X",
        "git commit --fixup X",
        "git commit --dry-run",
        "git commit --short",
        "git commit --porcelain",
        "git commit --long",
        "git merge topic",
        "git merge --no-ff topic",
        "git merge -s ours topic",
        "git merge -m ok -s ours topic",
        "git revert -m 1 X",
        "git cherry-pick -m 1 X",
        "git log --grep 'fixes #3'",
        "git status",
        "git -c user.name=x commit -m ok",
        "echo \"git commit -m 'fixes #1'\"",
        _HEREDOC.format(
            delim="'EOF'", body='costs $5, `x`, "q" and it\'s fine'
        ),
        "git commit -m ok -- -F",
        "git commit -m ok -",
        "git commit -m ok -- x",
        # the prefilter's first case matches, the tokenizer finds no call
        "git commit -m 'unterminated",
    ],
)
def test_reworded_and_unrelated_commands_are_allowed(command: str) -> None:
    assert _reason(command) == ""


def test_a_long_hyphenated_message_does_not_hang_the_keyword_pattern() -> None:
    # An unbounded pattern backtracks past the helper's subprocess timeout.
    # Not a parameter: pytest puts a test id in the environment, and this
    # command is too long for it.
    command = _HEREDOC.format(delim="'EOF'", body="fix-" * 50000)
    assert _reason(command) == ""


def test_a_payload_the_prefilter_does_not_match_is_ignored(
    tmp_path: Path,
) -> None:
    # A stub python3 first on PATH marks every call that reaches Python.
    stub = tmp_path / "python3"
    stub.write_text("#!/bin/sh\necho STUB\n", encoding="utf-8")
    stub.chmod(0o755)
    env = {"PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"}
    for command in (
        "git status 'fixes #3'",
        "echo commit -m 'fixes #3'",
        "tea comment 5 'commit fixes #3 merge'",
    ):
        assert run_bash_hook(_HOOK, command, **env) == ""
    assert run_bash_hook(_HOOK, "git commit -m ok", **env) == "STUB\n"


def test_malformed_payload_fails_open() -> None:
    # Mentions git and commit so the bash prefilter passes it through to the
    # Python payload parse, which must exit clean and deny nothing.
    result = subprocess.run(
        ["bash", str(_HOOK)],
        input="git commit, but not json",
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert result.stdout == ""


def test_antigravity_run_command_payload_denies_and_allows() -> None:
    out = run_agy_command_hook(_HOOK, "git commit -m 'fixes #3'")
    parsed = json.loads(out)
    assert parsed["decision"] == "deny"
    assert "closing or reopen keyword" in parsed["reason"]
    assert run_agy_command_hook(_HOOK, "git commit -m 'ok'") == ""


@pytest.mark.parametrize(
    "argv",
    [
        ["bash", "-lc", "git commit -m 'fixes #3'"],
        ["git", "commit", "-m", "fixes #3"],
    ],
)
def test_a_codex_argv_command_is_denied(argv: list[str]) -> None:
    payload = {"tool_name": "Bash", "tool_input": {"command": argv}}
    result = subprocess.run(
        ["bash", str(_HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert _KEYWORD in result.stdout
