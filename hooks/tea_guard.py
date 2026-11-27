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

Behavior is pinned by tests/hooks/test_tea_guard.py — a crashed PreToolUse
hook fails OPEN in the harness, so those tests are what notices a broken
guard. Shared plumbing and the shell tokenizer live in hook_lib.py.
"""

import re

from hook_lib import (
    ENV_ASSIGN,
    command_text,
    deny,
    effective_tool,
    read_payload,
    simple_commands,
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
# Words the shell allows in front of a command, and `(`/`)` around one.
SHELL_WORDS = {"{", "}", "!", "then", "do", "else"}

# `$(cat <<'EOF' ... EOF)`, the one readable multi-line body form. An
# unquoted delimiter matches too, so its body leaves the text and cannot
# unbalance the quotes around it; it is then denied as an expansion.
_HEREDOC_SUB = re.compile(
    r"\$\(\s*cat\s+<<-?\s*(['\"]?)([\w-]+)\1[ \t]*\n"
    r"(?:(.*?)\n)?[ \t]*\2\s*\)",
    re.DOTALL,
)
_PLACEHOLDER = re.compile("\x1f(\\d+)\x1f")
# A number glued to a redirect operator is a descriptor (`2>&1`), not an
# index; `tea issues 2 > out` keeps its `2`.
_FD = re.compile(r"(?<![\w.$#-])\d+(?=[<>])")
_REDIRECT = re.compile(r"[<>&|]+")
_EXPANSION = re.compile(r"`|\$[A-Za-z0-9_{(@*#?!$-]")
_CLOSES_LINE = re.compile(r"^[ \t]*Closes #\d+[ \t]*$", re.MULTILINE)
_KEYWORD = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|reopen(?:s|ed)?):?[ \t]*"
    r"(?:[\w.-]+/[\w.-]+)?#\d+",
    re.IGNORECASE,
)

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


def _without_redirects(args: list[str]) -> list[str]:
    """Drop each redirect operator and the token after it."""
    out: list[str] = []
    skip = False
    for tok in args:
        if skip:
            skip = False
        elif _REDIRECT.fullmatch(tok) and ("<" in tok or ">" in tok):
            skip = True
        else:
            out.append(tok)
    return out


def _posted(rest: list[str], bodies: list[str], admit: bool) -> list[str]:
    """Each token as tea would send it, heredoc bodies put back.

    An admitting call's description, and nothing else, loses its
    `Closes #N` lines.
    """

    def body(m: re.Match[str]) -> str:
        n = int(m[1])
        return bodies[n] if n < len(bodies) else m[0]

    out = []
    for i, tok in enumerate(rest):
        text = _PLACEHOLDER.sub(body, tok)
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
        if found := _EXPANSION.search(tok):
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
        if found := _KEYWORD.search(text):
            deny(_KEYWORD_MSG.format(found=found.group(0)))


def _commands(cmd: str) -> list[tuple[str, list[str]]]:
    """Each simple command, entered through `( )`, `$( )` and shell words.

    `pr=$(tea pulls create ...)`, `(tea ...)`, `{ tea ...; }`, `! tea ...`
    and the body of an `if` or a loop hide the command word behind a token
    the shared tokenizer leaves in place. A wrapper (`command`, `env`, ...)
    is unwrapped, then tea's own global flags (`tea --debug comment ...`),
    none of which takes a value, are skipped.
    """
    out: list[tuple[str, list[str]]] = []
    for first, tail in simple_commands(cmd, multiline=True):
        seg: list[str] = []
        for tok in [first, *_without_redirects(tail), ")"]:
            if tok not in {"(", ")"}:
                seg.append(tok)
                continue
            while seg and (seg[0] in SHELL_WORDS or ENV_ASSIGN.match(seg[0])):
                seg = seg[1:]
            if seg:
                word = seg[0].rsplit("/", 1)[-1]
                name, args = effective_tool(word, seg[1:])
                while args and args[0].startswith("-"):
                    args = args[1:]
                out.append((name, args))
            seg = []
    return out


def main() -> None:
    cmd = command_text(tool_input(read_payload()))
    bodies: list[str] = []

    def lift(m: re.Match[str]) -> str:
        if not m[1]:
            return "$(unquoted-heredoc)"
        bodies.append(m[3] or "")
        return f"\x1f{len(bodies) - 1}\x1f"

    cmd = _FD.sub("", _HEREDOC_SUB.sub(lift, cmd))
    for name, args in _commands(cmd):
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
