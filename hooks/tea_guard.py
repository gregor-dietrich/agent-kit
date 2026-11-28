"""PreToolUse guard (Bash): two rules for ``tea``.

Reads: ``tea issues <n>`` and ``tea pr <idx>`` look complete while silently
omitting comments — ``--output json`` even prints a ``"comments"`` key
that is ``[]`` when comments exist. That has shipped an implementation, and
then its review, against an issue whose decisive diagnosis sat in a
comment, so the honest form is enforced, not just documented: a ``tea``
read of a single issue/PR index is denied unless it carries
``--comments``. The flag composes with ``--output json`` (body and fields
unchanged), so no workflow loses anything by complying. Listings are
untouched.

Writes: the forge closes or reopens an issue on a keyword directly before
an issue reference wherever it stands, negated or quoted included. A
``tea`` comment or PR write (``comments``, ``pulls create|edit|approve|
reject|reply|merge``) carrying one is denied, and so is one whose text the
guard cannot read (an expansion, ``--description-file``, a comment with no
body argument): a call it has read but cannot model is denied. The one
admitted form is a line holding only ``Closes #N`` in a PR description.

Accepted limits: the guard catches ordinary posting, not a determined
bypass, and each rule added to its shell reading is one more place for it
to disagree with the shell. Not seen: a ``tea`` call inside an inner shell
(``bash -c '...'``), in backticks, as the condition of ``if``, ``while`` or
``until``, or behind a wrapper the shared prefix list lacks (``timeout 30
tea ...``); a command word built from a variable; brace expansion; a
quoted redirect operator passed as an argument of its own; a command that
does not tokenize at all; and text piped into a comment that also has a
body argument. ``tea issues create|edit`` is outside both rules; commit
messages are the commit guard's (commit_guard.py).

Behavior is pinned by tests/hooks/test_tea_guard.py — a crashed PreToolUse
hook fails OPEN in the harness, so those tests are what notices a broken
guard. Shared plumbing and the shell tokenizer live in hook_lib.py.
"""

import re

from hook_lib import (
    CLOSING_KEYWORD,
    EXPANSION,
    FD,
    command_text,
    command_words,
    deny,
    lift_heredocs,
    read_payload,
    restore_heredocs,
    tool_input,
)

READ_SUBCOMMANDS = {"issue", "issues", "pull", "pulls", "pr"}
# Flags that consume the following token as a value; their value must not
# be mistaken for the positional index (``tea issues --output json 256``).
# An unknown value-flag only fails open: its value reads as a non-numeric
# positional and the command passes.
VALUE_FLAGS = {
    "--output",
    "-o",
    "--login",
    "-l",
    "--repo",
    "-r",
    "--remote",
    "-R",
    "--fields",
    "-f",
    "--limit",
    "--page",
    "-d",
    "--description",
    "-t",
    "--title",
    "-m",
    "--message",
}
COMMENT_GROUPS = {"comments", "comment", "c"}
PULL_GROUPS = {"pulls", "pull", "pr"}
# The comment subcommands that post no text.
COMMENT_READS = {"list", "ls", "delete", "rm"}
PULL_GUARDED = {"approve", "lgtm", "a", "reject", "reply", "merge", "m"}
PULL_ADMITTING = {"create", "c", "edit", "e"}
DESCRIPTION_FLAGS = {"-d", "--description"}
DESCRIPTION_PREFIXES = ("-d=", "--description=")
_CLOSES_LINE = re.compile(r"^[ \t]*Closes #\d+[ \t]*$", re.MULTILINE)

_KEYWORD_MSG = (
    "This tea call would post {found!r}: a closing or reopen keyword "
    "directly before an issue reference. The forge acts on it wherever it "
    "stands, negated or quoted included. Reword it ('addresses #N', or the "
    "bare '#N'). The one admitted form is a line holding only 'Closes "
    "#N' in the description of 'tea pulls create' or 'tea pulls edit'."
)
_EXPANSION_MSG = (
    "The tea guard cannot read what this call would post: an argument "
    "holds a shell expansion ({found!r}), so a closing keyword before an "
    "issue reference cannot be ruled out. Write every argument literally. "
    "For text with '$', backticks or several lines, use a quoted heredoc: "
    "tea comment <n> \"$(cat <<'EOF' ... EOF)\"."
)
_FILE_MSG = (
    "The tea guard cannot read a description that comes from "
    "--description-file, so a closing keyword before an issue reference "
    "cannot be ruled out. Pass the text with --description, as a quoted "
    "heredoc if it is long: --description \"$(cat <<'EOF' ... EOF)\"."
)
_NO_BODY_MSG = (
    "This tea comment call has no body argument, so tea would read it from "
    "stdin or an editor, which the guard cannot read. Pass the body as an "
    "argument, as a quoted heredoc if it is long: tea comment <n> "
    "\"$(cat <<'EOF' ... EOF)\"."
)


def _positionals(args: list[str]) -> list[str]:
    """Every non-flag token, skipping value-flag arguments."""
    out: list[str] = []
    i = 0
    while i < len(args):
        if args[i] in VALUE_FLAGS:
            i += 2
            continue
        if not args[i].startswith("-"):
            out.append(args[i])
        i += 1
    return out


def _first_positional(args: list[str]) -> str:
    return (_positionals(args) or [""])[0]


def _posted(rest: list[str], bodies: list[str], admit: bool) -> list[str]:
    """Each token as tea would send it, heredoc bodies put back.

    An admitting call's description, and nothing else, loses its
    `Closes #N` lines.
    """
    out = []
    for i, tok in enumerate(rest):
        text = restore_heredocs(tok, bodies)
        if admit and tok.startswith(DESCRIPTION_PREFIXES):
            text = _CLOSES_LINE.sub("", text.split("=", 1)[1])
        elif admit and i and rest[i - 1] in DESCRIPTION_FLAGS:
            text = _CLOSES_LINE.sub("", text)
        out.append(text)
    return out


def _check_write(group: str, rest: list[str], bodies: list[str]) -> None:
    sub = _first_positional(rest)
    comment = group in COMMENT_GROUPS
    pull = group in PULL_GROUPS
    admit = pull and sub in PULL_ADMITTING
    if not (
        (comment and sub not in COMMENT_READS)
        or (pull and (admit or sub in PULL_GUARDED))
    ):
        return
    if any(t.startswith("--description-file") for t in rest):
        deny(_FILE_MSG)
    for tok in rest:
        if found := EXPANSION.search(tok):
            deny(_EXPANSION_MSG.format(found=found.group(0)))
    texts = _posted(rest, bodies, admit)
    if comment:
        # An index (after `add`/`edit`, when spelled out), then the body,
        # which tea joins with blanks when it comes as several arguments.
        pos = _positionals(rest)
        pos = pos[1:] if pos[:1] in (["add"], ["a"], ["edit"], ["e"]) else pos
        if len(pos) == 1 and not any(
            t in DESCRIPTION_FLAGS or t.startswith(DESCRIPTION_PREFIXES)
            for t in rest
        ):
            deny(_NO_BODY_MSG)
        texts.append(" ".join(_posted(pos[1:], bodies, admit=False)))
    for text in texts:
        if found := CLOSING_KEYWORD.search(text):
            deny(_KEYWORD_MSG.format(found=found.group(0)))


def main() -> None:
    cmd = command_text(tool_input(read_payload()))
    cmd, bodies = lift_heredocs(cmd)
    for name, args in command_words(FD.sub("", cmd)):
        # tea's own global flags (`tea --debug comment ...`) take no value.
        while args and args[0].startswith("-"):
            args = args[1:]
        if name != "tea" or not args:
            continue
        group, rest = args[0], args[1:]
        if (
            group in READ_SUBCOMMANDS
            and _first_positional(rest).isdigit()
            and "--comments" not in rest
        ):
            deny(
                "tea's single-issue/PR view hides comments: --output json "
                'prints "comments": [] even when comments exist, and the '
                "plain view omits them too, so a diagnosis recorded in a "
                "comment is invisible. Add --comments — it composes with "
                "--output json and leaves body/fields unchanged: 'tea "
                "issues <n> --comments [--output json]'."
            )
        _check_write(group, rest, bodies)


if __name__ == "__main__":
    main()
