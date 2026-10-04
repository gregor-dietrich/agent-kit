#!/usr/bin/env python3
"""PreToolUse guard (Bash): never read an exit status through a pipe.

``make test | tail -5`` reports **tail's** exit status, not the gate's, so a
red gate reads as green. Prose does not fix this: it has been observed in a
session that had the rule in context, quoted it verbatim, and tripped over
it twice anyway. It is not a belief failure but a fluent shell habit,
emitted while attention is on *what* is being checked rather than on the
exit-code plumbing, so it wants a guard at the moment of the call.

Denied when a pipeline's LAST segment is a pass-through display filter
(``tail``/``head``/``cat``/``tee``/``less``/…) — i.e. a command whose status
says nothing about the work — **and** that status is load-bearing, which
means either:

* the pipeline's first segment is a known verification command (``make``,
  ``pytest``, ``mvn``/``./mvnw``, ``gradle``/``./gradlew``, a
  ``scripts/*.sh`` gate, …) — or ``git commit``/``git push``, which run the
  pre-commit and pre-push gates in a clone that installs them — so the
  caller is reading a gate's verdict, or
* the status is explicitly consumed — the pipeline is followed by ``&&`` or
  ``||``, or ``$?`` is read afterwards.

Deliberately NOT denied: ``git log | head``-style browsing (no gate, no
status consumed); ``cmd | grep -q x && …`` (grep is a genuine predicate, not
a pass-through — its status is exactly what the caller wants); and anything
already doing it correctly via ``set -o pipefail`` or the ambient shell's
pipe-status array.

That last one is shell-sensitive, and the guard is **not** written for one
shell. bash spells it ``${PIPESTATUS[0]}`` and zsh ``${pipestatus[1]}``
(lowercase, 1-indexed) or, just as idiomatically, ``$pipestatus[1]`` without
the braces — which bash cannot parse at all. Each array is silently EMPTY in
the other shell, so the wrong one prints nothing and proves nothing while
looking like a check. The ambient shell is read from ``$SHELL`` and the
mismatched form is denied with the right spelling named; an explicit
``bash -c …``/``zsh -c …`` in the same command is taken at its word, and an
unrecognised shell disables that arm entirely. The opt-out is read the same
way: ``set -o pipefail`` in either shell, or zsh's ``setopt PIPE_FAIL``,
whose option names ignore case and underscores. Everything else here is
shell-agnostic: a pipeline reports its last segment's status in both.

This arm exists because a first version of this guard treated any mention
of ``PIPESTATUS`` as "already correct", and therefore waved through a zsh
command that printed an empty status during a review.

Behavior is pinned by tests/hooks/test_pipe_status_guard.py — a crashed
PreToolUse hook fails OPEN in the harness, so those tests are what notices
a broken guard. Shared plumbing and the shell tokenizer live in hook_lib.py.
"""

import os
import re

from hook_lib import (
    ENV_ASSIGN,
    command_text,
    deny,
    effective_tool,
    read_payload,
    strip_heredocs,
    tokenize_lines,
    tool_input,
)

# Control operators that end a pipeline (as opposed to ``|``, which extends
# one). The tokenizer emits these as standalone tokens.
CONTROL_OPS = {";", "&&", "||", "&", "\n", ";;"}
PIPE_OPS = {"|", "|&"}

# Commands that pass their input through unchanged (or merely reformat it):
# their exit status reflects the display, never the work that produced it.
PASS_THROUGH = {
    "tail",
    "head",
    "cat",
    "tee",
    "less",
    "more",
    "nl",
    "tac",
    "column",
    "fold",
    "bat",
}

# Commands whose exit status IS the thing being asked about. Not exhaustive
# and does not need to be: an unlisted gate only means we do not block.
GATES = {
    "make",
    "pytest",
    "ruff",
    "pyright",
    "vulture",
    "bandit",
    "mypy",
    "tox",
    "nox",
    "jscpd",
    "markdownlint",
    "markdownlint-cli2",
    "pip-audit",
    "uv",
    "npm",
    "pnpm",
    "yarn",
    "cargo",
    "go",
    "docker",
    "alembic",
    "playwright",
    "mvn",
    "mvnw",
    "gradle",
    "gradlew",
}
# git subcommands that run a gate in a clone that installs git hooks
# (pre-commit running the lint gate, pre-push the test gate), where a
# refusal is only visible in the exit status — so `git push … | tail`
# reports tail's success over a refused push. Every other subcommand stays
# browsing (`git log | head`).
GIT_GATE_SUBCOMMANDS = {"commit", "push"}
# git's global options that take their value as the NEXT word; every other
# option is one token (`--git-dir=x`, `--no-pager`, `-p`).
GIT_OPTS_WITH_VALUE = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--super-prefix",
    "--config-env",
    "--attr-source",
}
# Repo gates invoked by path (scripts/test.sh, scripts/lint.sh, …).
# Unanchored + fullmatch: '$' would also accept a trailing newline, and
# .match() would accept any matching prefix.
GATE_PATH = re.compile(r"(?:\./)?scripts/[\w.-]+\.(?:sh|py)")

# `set -o pipefail` means the same thing in bash and zsh — always correct.
# zsh reaches the same option through `setopt`, where option names ignore
# case and underscores, so `setopt PIPE_FAIL` and `setopt pipe_fail` are the
# same request and must count too.
PIPEFAIL = re.compile(r"pipe_?fail", re.IGNORECASE)

# The two shells' pipe-status arrays. Same idea, different spelling, and each
# is silently EMPTY in the other shell — `"${PIPESTATUS[0]}"` under zsh
# expands to nothing, so the check prints an empty status and proves nothing.
#
# Matched as a real dereference rather than a bare mention: the leading `$`
# is required, so a grep pattern or a docstring naming the array is not a
# claim to be checking it. Both subscript spellings count — zsh subscripts
# without braces and does so idiomatically (`$pipestatus[1]`), a form bash
# cannot parse at all, and a guard that knew only `${…[` denied the very
# spelling it should have been teaching. The whole array (`$pipestatus`,
# `${PIPESTATUS[@]}`) is a genuine read too. Case-sensitive on purpose: the
# case IS the difference between the two shells.
ARRAY_RE = {
    "bash": re.compile(r"\$\{?PIPESTATUS\b"),
    "zsh": re.compile(r"\$\{?pipestatus\b"),
}

# The canonical spelling to *recommend* per shell. bash's array is 0-indexed
# and zsh's is 1-indexed; both of these name the pipeline's first command.
ARRAY_FORM = {"bash": '"${PIPESTATUS[0]}"', "zsh": '"${pipestatus[1]}"'}


def _ambient_shell() -> str:
    """The shell these commands run in, per ``$SHELL`` ("" when unknown).

    Keyed to the environment rather than hardcoded: the correct spelling
    differs per shell, so a guard that assumed one would hand out wrong
    advice on the other. An unrecognised shell disables this arm entirely
    (fail open) — the pass-through/gate rule below is shell-agnostic and
    still applies.
    """
    shell = os.path.basename(os.environ.get("SHELL", "")).lower()
    return shell if shell in ARRAY_RE else ""


def _right_incantation() -> str:
    """The pipe-status read that actually works in the ambient shell.

    With no known shell, only the shell-agnostic advice is offered.
    """
    ambient = _ambient_shell()
    return ARRAY_FORM.get(ambient, "'set -o pipefail'")


def _wrong_array_for_shell(cmd: str) -> tuple[str, str] | None:
    """(wrong_shell, right_form) when *cmd* uses the other shell's array.

    An explicit invocation of the other shell in the same command is taken
    at its word — ``bash -c '… ${PIPESTATUS[0]}'`` is correct under zsh.
    """
    ambient = _ambient_shell()
    if not ambient:
        return None
    other = "zsh" if ambient == "bash" else "bash"
    if ARRAY_RE[other].search(cmd) and other not in cmd:
        return other, ARRAY_FORM[ambient]
    return None


def _git_subcommand(args: list[str]) -> str:
    """The subcommand of a ``git`` invocation, past its global options."""
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in GIT_OPTS_WITH_VALUE:
            i += 2
        elif arg.startswith("-"):
            i += 1
        else:
            return arg
    return ""


def _is_gate(name: str, raw: str, args: list[str]) -> bool:
    if name == "git":
        return _git_subcommand(args) in GIT_GATE_SUBCOMMANDS
    return name in GATES or bool(GATE_PATH.fullmatch(raw))


def _pipelines(text: str) -> list[tuple[list[list[str]], str]]:
    """Split *text* into (pipeline, control_op) pairs.

    A pipeline is its list of ``|``-separated segments, each a token list.
    The tokenizer works line by line — a newline IS a command separator, so
    ``foo\nmake test | tail`` must not read ``foo`` as the command whose
    status is piped — and drops heredoc bodies and anything that does not
    tokenize: like every other hook here, an unparseable command is never
    blocked.
    """
    out: list[tuple[list[list[str]], str]] = []
    for tokens in tokenize_lines(text):
        pipeline: list[list[str]] = []
        segment: list[str] = []
        for tok in tokens:
            if tok in PIPE_OPS:
                pipeline.append(segment)
                segment = []
            elif tok in CONTROL_OPS:
                pipeline.append(segment)
                out.append((pipeline, tok))
                pipeline, segment = [], []
            else:
                segment.append(tok)
        pipeline.append(segment)
        out.append((pipeline, ";"))
    if out:
        out[-1] = (out[-1][0], "")
    return out


def _command_of(segment: list[str]) -> tuple[str, str, list[str]]:
    """(basename, raw token, args) of a segment's command, skipping VAR=val."""
    i = 0
    while i < len(segment) and ENV_ASSIGN.match(segment[i]):
        i += 1
    if i >= len(segment):
        return "", "", []
    raw = segment[i]
    name, args = effective_tool(os.path.basename(raw), segment[i + 1 :])
    return name, raw, args


def main() -> None:
    raw = command_text(tool_input(read_payload()))
    # Heredoc bodies are prose and must not be read as commands — nor as
    # claims about pipe status: a commit message quoting "${PIPESTATUS[0]}"
    # is documentation, not a check. The pipeline split strips them itself
    # (stripping twice would re-read the kept `<<EOF` line as a fresh
    # heredoc and swallow whatever follows), so it gets the raw text.
    cmd = strip_heredocs(raw)
    mismatch = _wrong_array_for_shell(cmd)
    if mismatch is not None:
        # Caught by measurement, not by reading: a first version treated
        # any mention of PIPESTATUS as "already handling it correctly", and
        # waved through a command that printed an empty status.
        wrong_shell, right = mismatch
        deny(
            f"That is {wrong_shell}'s pipe-status array, and this shell is "
            f"{_ambient_shell()}: it expands to nothing here, so the check "
            "prints an empty status and proves nothing rather than failing "
            f"loudly. Use {right} — note bash's PIPESTATUS is 0-indexed and "
            "zsh's pipestatus is 1-indexed, and zsh also takes the braceless "
            "$pipestatus[1] — or, simpler and shell-agnostic, redirect and "
            "read the command's own code: 'cmd > out.log 2>&1; echo "
            '"EXIT=$?"; tail -20 out.log\'.'
        )
    # With a known shell only its own array counts (the other one is empty
    # and was denied above); with an unknown shell neither can be judged, so
    # either is accepted as a genuine attempt rather than denied blindly.
    ambient = _ambient_shell()
    accepted = [ambient] if ambient else list(ARRAY_RE)
    if PIPEFAIL.search(cmd) or any(ARRAY_RE[s].search(cmd) for s in accepted):
        return
    parsed = _pipelines(raw)
    for index, (pipeline, follower) in enumerate(parsed):
        if len(pipeline) < 2:
            continue
        last_name, _, _ = _command_of(pipeline[-1])
        if last_name not in PASS_THROUGH:
            continue
        first_name, first_raw, first_args = _command_of(pipeline[0])
        # `$?` only refers to THIS pipeline when it is read by the very next
        # one — anything in between resets it. Scanning the whole command
        # instead would flag `make x > log; echo $?; git log | head`, where
        # the `$?` belongs to make and the pipeline is plain browsing.
        next_pipeline = parsed[index + 1][0] if index + 1 < len(parsed) else []
        reads_status_var = any(
            "$?" in token for segment in next_pipeline for token in segment
        )
        consumed = follower in {"&&", "||"} or reads_status_var
        if not (consumed or _is_gate(first_name, first_raw, first_args)):
            continue
        deny(
            f"This reads {last_name}'s exit status, not "
            f"{first_name or 'the command'}'s: in a pipeline the shell "
            f"reports the LAST segment, and {last_name} succeeds even when "
            "the work it is displaying failed — so a red gate reads as "
            "green. Capture the real status instead: redirect to a file and "
            "check the command's own code ('cmd > out.log 2>&1; echo "
            '"EXIT=$?"; tail -20 out.log\'), or use '
            f"{_right_incantation()}, or 'set -o pipefail'."
        )


if __name__ == "__main__":
    main()
