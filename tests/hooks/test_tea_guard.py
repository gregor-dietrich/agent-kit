"""Behavioral pin for the Bash tea guard hook (``hooks/``).

Runs the real hook — the bash prefilter wrapper plus ``tea_guard.py`` —
as a subprocess with crafted tool JSON. Load-bearing like every hook's
pin: a crashed PreToolUse hook fails OPEN in the harness, so a
broken guard denies nothing and nothing else would notice. (The guard
exists because tea's single-entity views silently omit comments, which has
shipped work against a diagnosis already recorded on its own issue.)
"""

import subprocess
from pathlib import Path

from bash_hook import run_bash_hook

_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _ROOT / "hooks" / "tea-guard.sh"


def _denied(command: str) -> bool:
    return '"permissionDecision": "deny"' in run_bash_hook(_HOOK, command)


# --- single-entity reads must carry --comments ------------------------------


def test_issue_read_without_comments_is_denied() -> None:
    assert _denied("tea issues 256")


def test_issue_json_read_without_comments_is_denied() -> None:
    assert _denied("tea issues 256 --output json")


def test_flag_value_before_the_index_is_still_denied() -> None:
    assert _denied("tea issues --output json 256")


def test_issue_read_with_comments_is_allowed() -> None:
    assert not _denied("tea issues 256 --comments")
    assert not _denied("tea issues 256 --comments --output json")


def test_pr_read_without_comments_is_denied() -> None:
    assert _denied("tea pr 288 --output json")
    assert _denied("tea pulls 288")


def test_pr_read_with_comments_is_allowed() -> None:
    assert not _denied("tea pr 288 --comments --output json")


# --- everything else stays untouched ----------------------------------------


def test_write_subcommands_are_allowed() -> None:
    assert not _denied("tea pulls edit 288 --description 'x'")
    assert not _denied("tea comments 256 'a body'")
    assert not _denied("tea issues create --title 'x'")


def test_listings_are_allowed() -> None:
    assert not _denied("tea issues ls --limit 50")
    assert not _denied("tea comments list 256")


def test_a_here_string_does_not_swallow_the_rest() -> None:
    # `<<<` is a here-string, not a heredoc — it starts no body. The shared
    # heredoc regex matched at its second `<` and dropped everything after
    # it, so one here-string blinded this guard for the whole command.
    assert _denied("grep -c x <<< 'data'\ntea issues 256")


def test_tea_inside_a_quoted_string_is_ignored() -> None:
    assert not _denied("grep -rn 'tea issues 256' docs/")


def test_unrelated_commands_are_allowed() -> None:
    assert not _denied("git status")


def test_malformed_payload_fails_open() -> None:
    # Mentions tea so the bash prefilter passes it through to the Python
    # payload parse, which must exit clean and deny nothing.
    result = subprocess.run(
        ["bash", str(_HOOK)],
        input="tea, but not json",
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert result.stdout == ""
