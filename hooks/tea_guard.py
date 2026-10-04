#!/usr/bin/env python3
"""PreToolUse guard (Bash): tea single-entity reads must fetch comments.

``tea issues <n>`` and ``tea pr <idx>`` look complete while silently
omitting comments — ``--output json`` even prints a ``"comments"`` key
that is ``[]`` when comments exist. That has shipped an implementation, and
then its review, against an issue whose decisive diagnosis sat in a
comment, so the honest form is enforced, not just documented: a ``tea``
read of a single issue/PR index is denied unless it carries
``--comments``. The flag composes with ``--output json`` (body and fields
unchanged), so no workflow loses anything by complying. Write forms
(``tea pulls edit …``, ``tea comments add …``) and listings are untouched.

Behavior is pinned by tests/hooks/test_tea_guard.py — a crashed PreToolUse
hook fails OPEN in the harness, so those tests are what notices a broken
guard. Shared plumbing and the shell tokenizer live in hook_lib.py.
"""

from hook_lib import (
    command_text,
    deny,
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
    "--repo",
    "--remote",
    "--fields",
    "-f",
    "--limit",
    "--page",
}


def _first_positional(args: list[str]) -> str:
    """The first non-flag token, skipping value-flag arguments."""
    i = 0
    while i < len(args):
        tok = args[i]
        if tok in VALUE_FLAGS:
            i += 2
        elif tok.startswith("-"):
            i += 1
        else:
            return tok
    return ""


def main() -> None:
    cmd = command_text(tool_input(read_payload()))
    for name, args in simple_commands(cmd):
        if name != "tea" or not args or args[0] not in READ_SUBCOMMANDS:
            continue
        rest = args[1:]
        if _first_positional(rest).isdigit() and "--comments" not in rest:
            deny(
                "tea's single-issue/PR view hides comments: --output json "
                'prints "comments": [] even when comments exist, and the '
                "plain view omits them too, so a diagnosis recorded in a "
                "comment is invisible. Add --comments — it composes with "
                "--output json and leaves body/fields unchanged: 'tea "
                "issues <n> --comments [--output json]'."
            )


if __name__ == "__main__":
    main()
