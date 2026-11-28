"""One rule for unreadable text, pinned against both Bash guards.

The commit guard and the tea guard read text the forge scans for closing
keywords, and each once decided alone what makes that text unreadable, so
a gap fixed in one stayed open in the other (``tea comment 5 $'[x]\\nfixes
#3'`` passed). The rule now lives in ``hook_lib.unreadable``; this table
runs every text form through both real wrappers (the bash prefilter plus
the guard script) so a gap fixed in one cannot reopen in the other. A row
whose verdicts differ by design says so with a per-guard override and a
``why``.
"""

import json
from pathlib import Path

import pytest
from bash_hook import run_bash_hook

_HOOKS = Path(__file__).resolve().parents[2] / "hooks"
_KEYWORD = "closing or reopen keyword"
_EXPANSION = "shell expansion"
_CALLS = {"commit": "git commit -m", "tea": "tea comment 5"}
_HEREDOC = '{call} "$(cat <<{delim}\n{body}\nEOF\n)"'
_QUOTED = 'costs $5, `x`, "q" and it\'s fine'


def _reason(guard: str, command: str) -> str:
    """The deny reason *guard* gives for *command*, or "" when it passes."""
    out = run_bash_hook(_HOOKS / f"{guard}-guard.sh", command)
    decision = json.loads(out)["hookSpecificOutput"] if out else {}
    return decision.get("permissionDecisionReason", "")


def _heredoc(delim: str, body: str) -> str:
    # str.replace, not .format: the forms hold braces and `{call}` is filled
    # later.
    return _HEREDOC.replace("{delim}", delim).replace("{body}", body)


def _row(
    template: str,
    verdict: str,
    *,
    tea: str | None = None,
    why: str = "",
) -> tuple[str, str, str, str]:
    """A template, its verdict for the commit guard and for the tea guard.

    The tea verdict is the commit one unless *tea* overrides it, and then
    *why* says why they differ.
    """
    return template, verdict, verdict if tea is None else tea, why


_ROWS = [
    _row("{call} $'[x]\\nfixes #3'", _EXPANSION),
    _row("{call} 'a $ b'", _EXPANSION),
    _row("{call} 'costs $5'", _EXPANSION),
    _row("{call} 'Move `foo` into lib'", _EXPANSION),
    _row(_heredoc("EOF", "hello"), _EXPANSION),
    _row(_heredoc("'EOF'", "fixes #3"), _KEYWORD),
    _row(_heredoc('"EOF"', "fixes #3"), _KEYWORD),
    _row(_heredoc("-'EOF'", "fixes #3"), _KEYWORD),
    _row(_heredoc("'EOF'", _QUOTED), ""),
    _row("{call} fixes\\ #3", _KEYWORD),
    _row('{call} "Title\n\nfixes #3"', _KEYWORD),
    _row("{call} 2>/dev/null 'fixes #3'", _KEYWORD),
    _row("2>&1 {call} 'fixes #3'", _KEYWORD),
    _row(">/dev/null {call} 'fixes #3'", _KEYWORD),
    _row(
        '{call} ok "$extra"',
        "",
        tea=_EXPANSION,
        why="the commit guard passes only message values, so `git merge "
        '"$branch"` passes; the tea guard reads every argument as posted '
        "text (see hook_lib.unreadable)",
    ),
    # Known, documented limits (each guard's "not seen" list). A guard that
    # starts seeing these fails here, and its docstring changes with it.
    _row("eval \"{call} 'fixes #3'\"", ""),
    _row("f() { {call} 'fixes #3'; }", ""),
]


@pytest.mark.parametrize("guard", ["commit", "tea"])
@pytest.mark.parametrize(
    ("template", "commit", "tea", "why"), _ROWS, ids=[r[0] for r in _ROWS]
)
def test_a_text_form_gets_the_same_verdict_from_both_guards(
    guard: str, template: str, commit: str, tea: str, why: str
) -> None:
    command = template.replace("{call}", _CALLS[guard])
    expected = commit if guard == "commit" else tea
    reason = _reason(guard, command)
    assert (expected in reason) if expected else (reason == ""), why
