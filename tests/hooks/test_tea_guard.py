"""Behavioral pin for the Bash tea guard hook (``hooks/``).

Runs the real hook — the bash prefilter wrapper plus ``tea_guard.py`` —
as a subprocess with crafted tool JSON. Load-bearing like every hook's
pin: a crashed PreToolUse hook fails OPEN in the harness, so a
broken guard denies nothing and nothing else would notice. (The guard
exists because tea's single-entity views silently omit comments, which has
shipped work against a diagnosis already recorded on its own issue, and
because a closing keyword before an issue reference in posted text closes
that issue wherever it stands.)
"""

import json
import subprocess
from pathlib import Path

import pytest
from bash_hook import deny_reason, run_agy_command_hook

_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _ROOT / "hooks" / "tea-guard.sh"


def _reason(command: str) -> str:
    return deny_reason(_HOOK, command)


def _denied(command: str) -> bool:
    return bool(_reason(command))


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


# --- what neither rule covers -----------------------------------------------


def test_writes_without_a_keyword_are_allowed() -> None:
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


def test_antigravity_run_command_payload_denies_and_allows() -> None:
    out = run_agy_command_hook(_HOOK, "tea issues 256")
    parsed = json.loads(out)
    assert parsed["decision"] == "deny"
    assert "--comments" in parsed["reason"]
    assert run_agy_command_hook(_HOOK, "tea issues 256 --comments") == ""


# --- writes must not carry a closing or reopen keyword ----------------------

_HEREDOC = 'tea comment 5 "$(cat <<{delim}\n{body}\nEOF\n)"'
_KEYWORD = "closing or reopen keyword"
_EXPANSION = "shell expansion"
_FILE = "--description-file"
_NO_BODY = "no body argument"


@pytest.mark.parametrize(
    "command",
    [
        'tea comment 5 "this fixes #3"',
        'tea comments add 5 "Resolved #3"',
        'tea comments edit 12 "reopens #3"',
        'tea comment 5 -d "does not close #3"',
        'tea comment 5 -d="does not close #3"',
        'tea c 5 "fix: #3"',
        'tea comment 5 "closes owner/repo#3"',
        "tea comment 5 closes owner/repo#3",
        "tea comment 5 'first\nthen fixes #3'",
        'tea comment 5 "cout << x\nthis fixes #3"',
        'tea comment 5 "this fixes" "#3"',
        'tea comment 5 see#1 "a\nfixes #3"',
        'tea comment 5 "Closes #3"',
        'tea pulls merge 5 -m "Closes #3"',
        'tea pulls create -t "fixes #3"',
        "tea pulls create -d x -t \"$(cat <<'EOF'\nCloses #3\nEOF\n)\"",
        'tea pulls create -d "Closes #1\nand fixes #2"',
        'tea pulls edit 5 --description "Closes #1, fixes #2"',
        'tea pulls approve 5 "fixes #3"',
        'tea pulls reject 5 "fixes #3"',
        'tea pulls reply 5 "fixes #3"',
        'tea pulls merge 5 -t "fixes #3"',
        _HEREDOC.format(delim="'EOF'", body="line one\nthis closes #3"),
        _HEREDOC.format(delim='"EOF"', body="this closes #3"),
        _HEREDOC.format(delim="-'EOF'", body="this closes #3"),
        # the command word behind a wrapper, a flag or shell structure
        "command tea comment 5 'fixes #3'",
        "env X=1 tea comment 5 'fixes #3'",
        "tea --debug comment 5 'fixes #3'",
        'pr=$(tea pulls create -t "fixes #3")',
        'echo $(tea comment 5 "fixes #3")',
        '(tea comment 5 "fixes #3")',
        '{ tea comment 5 "fixes #3"; }',
        '! tea comment 5 "fixes #3"',
        'if true; then tea comment 5 "fixes #3"; fi',
        '2>&1 tea comment 5 "fixes #3"',
        '>/dev/null tea comment 5 "fixes #3"',
        'for i in 1; do tea comment 5 "fixes #3"; done',
        'cd x;# don\'t\ntea comment 5 "a\nfixes #3"',
    ],
)
def test_a_closing_keyword_is_denied(command: str) -> None:
    assert _KEYWORD in _reason(command)


@pytest.mark.parametrize(
    ("command", "why"),
    [
        ('tea comment 5 "$(cat body.md)"', _EXPANSION),
        ('tea comment 5 "$body"', _EXPANSION),
        ("tea comment 5 `cat body.md`", _EXPANSION),
        # tests/hooks/test_text_forms.py runs its forms as a comment only
        ("tea pulls create -d $'[x]\\nfixes #3'", _EXPANSION),
        # A lone quote in an unquoted-delimiter body once unbalanced the
        # whole command, which then passed unread.
        (_HEREDOC.format(delim="EOF", body='He said "fixes #3'), _EXPANSION),
        ("tea pulls create --description-file body.md", _FILE),
        ("tea pulls create --description-file=body.md", _FILE),
        ("tea pulls create --description-file -", _FILE),
        ("tea comment 5", _NO_BODY),
        ("tea comments edit 12", _NO_BODY),
        ("tea comment 5 < body.md", _NO_BODY),
        ('tea comment 5 <<< "text"', _NO_BODY),
        ("cat body.md | tea comments add 5", _NO_BODY),
    ],
)
def test_text_the_guard_cannot_read_is_denied(command: str, why: str) -> None:
    assert why in _reason(command)


def test_a_keyword_is_denied_through_the_antigravity_payload() -> None:
    out = run_agy_command_hook(_HOOK, 'tea comment 5 "fixes #3"')
    assert json.loads(out)["decision"] == "deny"


def test_a_redirect_does_not_hide_an_index() -> None:
    assert _denied("tea issues 2 > out.txt")


def test_a_wrapper_or_flag_does_not_hide_a_read() -> None:
    assert _denied("command tea issues 5")
    assert _denied("tea --debug issues 5")
    assert _denied("n=$(tea issues 5)")
    assert not _denied("command -v tea")


def test_apostrophes_in_comments_do_not_hide_a_read() -> None:
    assert _denied("echo a # don't\ntea issues 5\necho b # can't")


@pytest.mark.parametrize(
    "command",
    [
        'tea comment 5 "addresses #3, see #4"',
        'tea comment 5 "hotfix #3"',
        'tea comment 5 "fixes the parser, see #3"',
        'tea comment 5 -d="looks good"',
        "tea comments list 5",
        "tea comments add --help",
        "tea pulls edit 5 --add-labels bug",
        'tea pulls create --head feature -t "Title"',
        'tea pulls create -d "a\nCloses #97\nb"',
        'tea pulls create -d "Closes #97"',
        'tea pulls create --description="Closes #97"',
        'tea pulls create -t T -d="Closes #97"',
        'tea pulls create -d "Closes #1\nCloses #2"',
        'pr=$(tea pulls create -t T -d "Closes #97")',
        (
            "tea pulls create --description \"$(cat <<'EOF'\n"
            'Summary\n\nCloses #97\nEOF\n)"'
        ),
        'tea comment 5 "ok" && git log --grep "fixes #3"',
        'git commit -m "fixes #3"',
        "tea pulls -h 2>&1",
        "tea issues ls 2>/dev/null",
    ],
)
def test_reworded_and_unrelated_text_is_allowed(command: str) -> None:
    assert _reason(command) == ""
