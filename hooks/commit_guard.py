"""PreToolUse guard (Bash): no closing keyword in a commit message.

The forge closes or reopens an issue on a keyword directly before an issue
reference wherever it stands, negated or quoted included, once the commit
reaches the default branch (and on a push to a branch an issue references).
A ``git commit`` or ``git merge`` whose message, given with ``-m`` or
``--message`` (and, for ``commit``, ``--trailer``), carries one is denied.
A commit message admits no deliberate ``Closes #N`` line: that form belongs
only in a pull request description.

A call the guard has read but cannot model is denied too: a message holding
a shell expansion (an unquoted heredoc included), one taken from
``-F``/``--file`` (stdin included) or, with no ``-m``, from a template
(``-t``), and, for ``commit``, one left to the editor (``-e``, ``-c``, or no
message and no flag that settles one). A message holding a ``$`` or a
backtick outside a quoted heredoc is denied even when the shell would leave
it literal (``'costs $5'``), because the tokenizer drops the quoting; see
``hook_lib.unreadable``. For ``merge`` only ``-e``/``--edit`` is denied:
without ``-m`` git prepares the message itself.

Accepted limits: the guard catches ordinary commits, not a determined
bypass. Not read: messages git carries or prepares (``--amend
--no-edit``, ``-C``, ``--fixup``, ``--no-edit`` after a conflict, merge's
own message, ``revert``, ``cherry-pick`` (whose ``-m`` is a parent
number), ``rebase``, ``pull``, ``commit-tree``), abbreviated long options
(``--mess=``), a ``git`` call inside an inner shell (``bash -c '...'``), in
backticks, as the condition of ``if``, ``while`` or ``until``, or behind a
wrapper the shared prefix list lacks (``timeout 30 git ...``); an expansion
outside the message values (a variable argument, ``"$@"``, a subcommand
built from a variable), which can supply a message option itself (the scope
is set out in ``hook_lib.unreadable``); git aliases and
``help.autocorrect``; a negated option that unsets an earlier one
(``--no-message``, ``--no-dry-run``); ``git merge --continue``; a template
named by ``commit.template``; ``eval``; a shell function's body; a redirect
standing before the subcommand (``git 2>x commit``); a command word built
from a variable; brace expansion; a quoted redirect operator passed as an
argument of its own; a command that does not tokenize at all; commits made
outside the agent's shell tool; and squash or merge messages the forge
composes.

Behavior is pinned by tests/hooks/test_commit_guard.py and, for the text
forms it shares with the tea guard, tests/hooks/test_text_forms.py — a
crashed PreToolUse hook fails OPEN in the harness, so those tests are what
notices a broken guard. Shared plumbing and the shell tokenizer live in
hook_lib.py.
"""

import re

from hook_lib import (
    CLOSING_KEYWORD,
    FD,
    command_text,
    command_words,
    deny,
    git_subcommand,
    lift_heredocs,
    read_payload,
    restore_heredocs,
    tool_input,
    unreadable,
)

# The subcommands whose message the guard reads.
GIT_MESSAGE_SUBCOMMANDS = {"commit", "merge"}
# Short options that take a value: the rest of the cluster, or the next token.
SHORT_VALUE = {"commit": "mFCct", "merge": "mFsX"}
# `-u` and `-S` take only an attached value, never the next token.
SHORT_ATTACHED = "uS"
# Long options that take their value as the next token (or after `=`).
LONG_VALUE = {
    "commit": {
        "--message",
        "--file",
        "--trailer",
        "--reuse-message",
        "--reedit-message",
        "--template",
        "--fixup",
        "--squash",
        "--author",
        "--date",
        "--cleanup",
        "--pathspec-from-file",
    },
    "merge": {
        "--message",
        "--file",
        "--strategy",
        "--strategy-option",
        "--cleanup",
        "--into-name",
    },
}
# Help flags: git prints usage and commits nothing.
HELP_FLAGS = {"-h", "--help"}
# Commit flags with which git opens no editor: `--no-edit`, the help flags,
# and `--dry-run` with the status formats that imply it.
NO_EDITOR_FLAGS = {
    *HELP_FLAGS,
    "--no-edit",
    "--dry-run",
    "--short",
    "--porcelain",
    "--long",
}
_REWORDING_FIXUPS = ("amend:", "reword:")
# The first `=` or `:` of a trailer, with the blanks around it: git records
# the trailer as `token: value`.
_TRAILER_SEP = re.compile(r"^([^=:]*?)[ \t]*[=:][ \t]*")

_KEYWORD_MSG = (
    "This git {sub} would record {found!r} in its message: a closing or "
    "reopen keyword directly before an issue reference. The forge acts on "
    "it once the commit reaches the default branch, and on a push to a "
    "branch an issue references, negated or quoted included. Reword it "
    "('addresses #N', or the bare '#N'). A commit message admits no such "
    "line: 'Closes #N' belongs only in a pull request description."
)
_EXPANSION_MSG = (
    "The commit guard cannot read this message: an argument holds a shell "
    "expansion ({found!r}), so a closing keyword before an issue reference "
    "cannot be ruled out. Write it literally; for text with '$', backticks "
    'or several lines, use a quoted heredoc: git {sub} -m "$(cat '
    "<<'EOF' ... EOF)\"."
)
_FILE_MSG = (
    "The commit guard cannot read a message taken from -F/--file "
    "({value!r}), stdin included, so a closing keyword before an issue "
    "reference cannot be ruled out. Pass it with -m, as a quoted heredoc "
    "if it is long: git {sub} -m \"$(cat <<'EOF' ... EOF)\"."
)
_EDITOR_MSG = (
    "This git {sub} takes its message from an editor, which the commit "
    "guard cannot read and an agent's shell cannot drive. Pass the message "
    "with -m, as a quoted heredoc if it is long, or --no-edit to keep the "
    "message git already has."
)


def _option_values(sub: str, args: list[str]) -> list[tuple[str, str | None]]:
    """Each option before ``--`` as (name, value).

    The value is None for an option that takes no value, or whose value is
    missing.

    A short cluster yields one pair per letter, its first value-taking
    letter taking the rest of the cluster or the next token. `-u` and `-S`
    take only an attached value, so they end a cluster without the next
    token. Short names carry their dash (`-m`).
    """
    out: list[tuple[str, str | None]] = []
    i = 0
    while i < len(args) and args[i] != "--":
        tok = args[i]
        i += 1
        nxt = args[i] if i < len(args) else None
        if not tok.startswith("-"):
            continue
        if tok.startswith("--"):
            name, eq, value = tok.partition("=")
            if name in LONG_VALUE[sub] and not eq:
                value = nxt
                i += 1
            out.append((name, value if name in LONG_VALUE[sub] else None))
            continue
        for j, letter in enumerate(tok[1:], 1):
            if letter in SHORT_VALUE[sub]:
                value = tok[j + 1 :] or None
                if value is None and nxt is not None:
                    value, i = nxt, i + 1
                out.append((f"-{letter}", value))
                break
            out.append((f"-{letter}", None))
            if letter in SHORT_ATTACHED:
                break
    return out


def _settles_message(name: str, value: str | None) -> bool:
    """Whether a commit option fixes the message without an editor."""
    return (
        name in NO_EDITOR_FLAGS
        or name in {"-C", "--reuse-message"}
        or (
            name == "--fixup"
            and not (value or "").startswith(_REWORDING_FIXUPS)
        )
    )


def _messages(
    sub: str, args: list[str], bodies: list[str]
) -> tuple[list[str], str | None]:
    """The message texts of a commit or merge, and why one is unreadable.

    The second item is the formatted deny reason, None when the message can
    be read. A trailer yields its value as typed and as git records it.
    """
    options = _option_values(sub, args)
    names = {name for name, _ in options}
    for name, value in options:
        if name in {"-F", "--file"}:
            return [], _FILE_MSG.format(sub=sub, value=value or "")
    if sub == "commit" and not names & {
        "-m",
        "--message",
        "-C",
        "--reuse-message",
    }:
        for name, value in options:
            if name in {"-t", "--template"}:
                return [], _FILE_MSG.format(sub=sub, value=value or "")
    edit = bool(names & {"-e", "--edit"})
    if sub == "commit":
        edit = edit or bool(names & {"-c", "--reedit-message"})
        edit = edit or not (
            names & {"-m", "--message"}
            or any(_settles_message(*opt) for opt in options)
        )
    if edit:
        return [], _EDITOR_MSG.format(sub=sub)
    tokens: list[str] = []
    texts: list[str] = []
    for name, value in options:
        tok = value or ""
        if name in {"-m", "--message"}:
            tokens.append(tok)
            texts.append(restore_heredocs(tok, bodies))
        elif sub == "commit" and name == "--trailer":
            tokens.append(tok)
            text = restore_heredocs(tok, bodies)
            texts += [text, _TRAILER_SEP.sub(r"\1: ", text, count=1)]
    for tok in tokens:
        if found := unreadable(tok):
            return [], _EXPANSION_MSG.format(sub=sub, found=found)
    return texts, None


def _check(sub: str, args: list[str], bodies: list[str]) -> None:
    texts, reason = _messages(sub, args, bodies)
    if reason:
        deny(reason)
    for text in texts:
        if found := CLOSING_KEYWORD.search(text):
            deny(_KEYWORD_MSG.format(sub=sub, found=found.group(0)))


def main() -> None:
    cmd = command_text(tool_input(read_payload()))
    cmd, bodies = lift_heredocs(cmd)
    for name, args in command_words(FD.sub("", cmd)):
        if name != "git":
            continue
        sub, rest = git_subcommand(args)
        # `git --help commit` prints usage: the global arguments say so.
        before = args[: len(args) - len(rest) - 1]
        if sub in GIT_MESSAGE_SUBCOMMANDS and not HELP_FLAGS & set(before):
            _check(sub, rest, bodies)


if __name__ == "__main__":
    main()
