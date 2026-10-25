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

* the pipeline's first command is a known verification command (``make``,
  ``pytest``, ``npx``, ``mvn``/``./mvnw``, ``gradle``/``./gradlew``, any
  ``*.sh`` script, a ``scripts/*.py`` gate, …) — or ``git commit``/``git
  push``, which run the pre-commit and pre-push gates in a clone that
  installs them — so the caller is reading a gate's verdict, or
* the status is explicitly consumed — the pipeline is introduced by ``if``,
  ``elif``, ``while`` or ``until``, followed by ``&&`` or ``||``, or ``$?``
  is read afterwards.

"First command" sees through what stands in front of it: the ``then``,
``do`` or ``else`` that opens a body (``while read l; do make test | tail;
done``), a ``{`` that opens a group (``{ make test | tail; }``), a ``!``
that negates the pipeline, ``VAR=val``,
``sudo``/``env``/``time``-style prefixes, runners (``uv run``), ``timeout``
with its options and duration, ``xargs`` with its flags, a shell running a
script (``bash x.sh``, ``sh ./gradlew test``) and a subshell, whose last
command is what a following ``|`` reads (``(cd x && make test) | tail``).
Where an option's value cannot be classified the unwrapping stops: that only
costs a check. Only the first command is unwrapped that far: the last
segment is read as written, so ``… | xargs sed -i s/a/b/ && git diff``
reads ``xargs``, not a ``sed`` filter. A pass-through filter is anything
whose status ignores its input: the pagers and ``cat``/``tee`` family, and
``wc``/``sort``/``sed``/``cut``/``uniq``/``tr``, which succeed whatever the
gate did (bar ``sort -c``, see below).

Deliberately NOT denied: ``git log | head``-style browsing (no gate, no
status consumed); ``cmd | grep -q x && …`` (grep is a genuine predicate, not
a pass-through — its status is exactly what the caller wants);
``cmd | sort -c`` (``-C``, ``--check``, ``-uc`` too), whose status says
whether its input is sorted; and anything already doing it correctly via
``set -o pipefail`` or the ambient shell's pipe-status array.

That last one is shell-sensitive, and the guard is **not** written for one
shell. bash spells it ``${PIPESTATUS[0]}`` and zsh ``${pipestatus[1]}``
(lowercase, 1-indexed) or, just as idiomatically, ``$pipestatus[1]`` without
the braces — which bash cannot parse at all. Each array is silently EMPTY in
the other shell, so the wrong one prints nothing and proves nothing while
looking like a check. The ambient shell is read from ``$SHELL`` and the
mismatched form is denied with the right spelling named; an explicit
``bash -c …``/``zsh -c …`` in the same command is taken at its word, and an
unrecognised shell disables that arm entirely. The opt-out is read the same
way, from the parsed commands and not from a mention of the word: a ``set``
segment whose option words (``-o``, ``-eo``, ``-euo``, ...) name
``pipefail``, in either shell, or a ``setopt`` segment naming zsh's
``PIPE_FAIL`` (not under bash). Order does not matter: one such segment
anywhere opts the whole command out. A line that does not tokenize cannot be
read, so if one exists and the command mentions pipefail, it is let through.
Everything else here is shell-agnostic: a pipeline reports its last
segment's status in both.

Accepted risk: the quoted string of a ``bash -c``/``zsh -c`` is never parsed
as commands, so a gated pipeline inside one (``bash -c 'make test | tail'``)
passes, and so does an opt-out inside one. Writing a command that way is a
deliberate choice, not the slip this guard catches. Two more forms pass for
a different reason: a group the pipeline starts with at its closing brace
(``{ make test; } | tail``) and a loop the pipeline starts with at its
closing word (``for t in a b; do make "$t"; done | tail``). Seeing them
takes a depth count over openers, closers and case patterns, as well as the
parentheses counted here, and each attempt grew new edge cases. An
arithmetic ``$(( … ))`` is read as nested parentheses, so a bitwise ``|``
in it splits its operands into a pipeline of their own (``$(( a | b ))``
reads as ``a | b``); the outer command is still read right, and only
operands named like a gate and a filter would be denied.

This arm exists because a first version of this guard treated any mention
of ``PIPESTATUS`` as "already correct", and therefore waved through a zsh
command that printed an empty status during a review.

Behavior is pinned by tests/hooks/test_pipe_status_guard.py — a crashed
PreToolUse hook fails OPEN in the harness, so those tests are what notices
a broken guard. Shared plumbing and the shell tokenizer live in hook_lib.py.
"""

import os
import re
from collections.abc import Iterator

from hook_lib import (
    ENV_ASSIGN,
    SHELL_WRAPPERS,
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
# Tokens that open a parenthesis: a subshell, or a command substitution.
OPENERS = {"(", "<(", ">("}

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
    "wc",
    "sort",
    "sed",
    "cut",
    "uniq",
    "tr",
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
    "npx",
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
# Repo gates invoked by path: any `*.sh` script (judged on the command's
# basename, so `./test.sh`, `ci/run.sh` and `bash x.sh` all count) and the
# `scripts/*.py` ones. Unanchored + fullmatch: '$' would also accept a
# trailing newline, and .match() would accept any matching prefix.
GATE_PATH = re.compile(r"(?:\./)?scripts/[\w.-]+\.py")
# Words that open a condition: the pipeline after one has its status read.
CONDITION_KEYWORDS = {"if", "elif", "while", "until"}
# Words that open a body: the command after one is what the pipeline runs.
# `{` opens a group and `!` negates the pipeline; neither changes which
# command comes first.
BODY_KEYWORDS = {"then", "do", "else", "{", "!"}
# `timeout`'s duration word, and its options that take their value as the
# next word, with what that value may look like.
DURATION = re.compile(r"\d+(?:\.\d+)?[smhd]?")
TIMEOUT_VALUE_OPTS = {
    "-k": DURATION.pattern,
    "--kill-after": DURATION.pattern,
    "-s": r"\w+",
    "--signal": r"\w+",
}
# `xargs`'s flags that take their value as the next word.
XARGS_VALUE_OPTS = {"-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a", "-J"}

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
    return (
        f"{ARRAY_FORM[ambient]}, or 'set -o pipefail'"
        if ambient in ARRAY_FORM
        else "'set -o pipefail'"
    )


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
    return (
        name in GATES or name.endswith(".sh") or bool(GATE_PATH.fullmatch(raw))
    )


# A punctuation token the tokenizer merged (`)|`, `);`, `&&(`, `((`, `|(`):
# its parts. `<(` and `>(` stay whole, `>&`, `&>` and `>>` are redirections
# and stay words; `&&`, `||`, `;;` and `|&` stay the operators they are.
_PUNCT_RUN = re.compile(r"[();|&<>]+")
_PUNCT_PART = re.compile(r"[<>]\(|&&|\|\||;;|\|&|[()|;&]|[<>]+")


def _split_punctuation(tokens: list[str]) -> Iterator[str]:
    """*tokens* with every merged punctuation run cut into its parts."""
    for tok in tokens:
        if _PUNCT_RUN.fullmatch(tok) and ("(" in tok or ")" in tok):
            yield from _PUNCT_PART.findall(tok)
        else:
            yield tok


def _pipelines(text: str) -> list[tuple[list[list[str]], str]]:
    """Split *text* into (pipeline, control_op) pairs.

    A pipeline is its list of ``|``-separated segments, each a token list.
    The tokenizer works line by line — a newline IS a command separator, so
    ``foo\nmake test | tail`` must not read ``foo`` as the command whose
    status is piped — and drops heredoc bodies and anything that does not
    tokenize: like every other hook here, an unparseable command is never
    blocked.

    Parentheses are tracked with a stack. A bare ``(`` ends the words before
    it on the same command, and its ``)`` changes nothing, so a subshell's
    last command starts the pipeline a following ``|`` extends, and a
    subshell after a ``|`` is that segment (``make test | (cat)``). A
    command substitution (``$(``, ``<(``, ``>(``) is a pipeline of its own:
    it is emitted when its ``)`` closes, and the outer command goes on with
    the words it had — the substitution contributes none, so
    ``pytest $(git ls-files)`` is still ``pytest``. An unbalanced ``)`` is
    dropped.
    """
    out: list[tuple[list[list[str]], str]] = []
    for tokens in tokenize_lines(text):
        pipeline: list[list[str]] = []
        segment: list[str] = []
        # One frame per open parenthesis: the outer (pipeline, segment) to
        # resume after a substitution, None for a bare subshell.
        stack: list[tuple[list[list[str]], list[str]] | None] = []

        parts = list(_split_punctuation(tokens))
        # Close what the line leaves open: an unclosed `$(` still has its
        # inner pipeline, and surplus `)` are dropped.
        parts += [")"] * sum(p in OPENERS for p in parts)
        for tok in parts:
            if tok == ")":
                frame = stack.pop() if stack else None
                if frame is not None:
                    out.append(([*pipeline, segment], ";"))
                    pipeline, segment = frame
            elif tok in OPENERS:
                if tok == "(" and segment and segment[-1].endswith("$"):
                    segment[-1] = segment[-1][:-1]  # `$(`: drop the `$`
                    if not segment[-1]:
                        segment.pop()
                elif tok == "(":
                    if segment:
                        pipeline.append(segment)
                        out.append((pipeline, ";"))
                        pipeline, segment = [], []
                    stack.append(None)
                    continue
                stack.append((pipeline, segment))
                pipeline, segment = [], []
            elif tok in PIPE_OPS:
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


def _is_predicate(name: str, args: list[str]) -> bool:
    """True for ``sort -c``/``-C``/``--check``, whose status is its answer."""
    options = args[: args.index("--")] if "--" in args else args
    return name == "sort" and any(
        a.startswith("--check") or re.fullmatch(r"-[A-Za-z]*[cC][A-Za-z]*", a)
        for a in options
    )


def _after_timeout(args: list[str]) -> list[str] | None:
    """What follows ``timeout``'s options and duration, None if unsure."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        value = TIMEOUT_VALUE_OPTS.get(args[i])
        if value is None:
            i += 1
        elif i + 1 < len(args) and re.fullmatch(value, args[i + 1]):
            i += 2
        else:
            return None
    if i < len(args) and DURATION.fullmatch(args[i]):
        return args[i + 1 :]
    return None


def _after_xargs(args: list[str]) -> list[str]:
    """What follows ``xargs``'s own flags (and their separate values)."""
    i = 0
    while i < len(args) and args[i].startswith("-") and args[i] != "--":
        i += 2 if args[i] in XARGS_VALUE_OPTS else 1
    return args[i + 1 :] if args[i : i + 1] == ["--"] else args[i:]


def _command_of(
    segment: list[str], *, wrapped: bool = False
) -> tuple[str, str, list[str]]:
    """(basename, raw token, args) of a segment's command, skipping VAR=val.

    Unwraps what effective_tool knows. With *wrapped*, also ``timeout``,
    ``xargs`` and a shell's script argument (``bash x.sh``), which the
    other guards do not want unwrapped and which only the first command of
    a pipeline wants: ``xargs sed -i`` as the LAST segment is ``xargs``
    running ``sed``, not a display filter. They stack, so the two are
    interleaved.
    """
    i = 0
    while i < len(segment) and ENV_ASSIGN.match(segment[i]):
        i += 1
    if i >= len(segment):
        return "", "", []
    raw = segment[i]
    name, args = os.path.basename(raw), segment[i + 1 :]
    while True:
        name, args = effective_tool(name, args)
        if not wrapped:
            break
        if name == "timeout":
            rest = _after_timeout(args)
        elif name == "xargs":
            rest = _after_xargs(args)
        elif (
            name in SHELL_WRAPPERS
            and args[:1] != []
            and not args[0].startswith("-")
        ):
            rest = args
        else:
            break
        if not rest:
            break
        raw = rest[0]
        name, args = os.path.basename(raw), rest[1:]
    return name, raw, args


def _set_enables_pipefail(args: list[str]) -> bool:
    """Walk ``set``'s option words the way the shell does, left to right."""
    i = 0
    while i < len(args) and re.fullmatch(r"[-+][^-]+", args[i]):
        if not args[i].endswith("o"):
            i += 1
            continue
        if args[i][0] == "-" and args[i + 1 : i + 2] == ["pipefail"]:
            return True
        i += 2
    return False


def _opts_into_pipefail(parsed: list[tuple[list[list[str]], str]]) -> bool:
    """True if any segment turns pipefail on (order-blind, by decision).

    ``set`` options are read left to right and stop at ``-``, ``--`` or the
    first word not starting with ``-``/``+``. A ``-``/``+`` word ending in
    ``o`` (``-o``, ``-eo``, ``-euxo``) takes the next word as an option
    name; ``-`` plus ``pipefail`` opts in, ``+o pipefail`` does not. ``-oe
    pipefail`` is denied: zsh reads it as ``-o e`` (bash would accept it, but
    one rule for both is simpler). ``setopt`` counts outside bash, which has
    none, and takes zsh's option-name rule: case and underscores ignored, so
    ``no_pipe_fail`` does not match.
    """
    for pipeline, _ in parsed:
        for segment in pipeline:
            i = 0
            while i < len(segment) and segment[i] == "{":
                i += 1
            name, _, args = _command_of(segment[i:], wrapped=True)
            if name == "set" and _set_enables_pipefail(args):
                return True
            if (
                name == "setopt"
                and _ambient_shell() != "bash"
                and any(a.lower().replace("_", "") == "pipefail" for a in args)
            ):
                return True
    return False


def _unreadable_pipefail_mention(raw: str, parsed_lines: int) -> bool:
    """True when a line was skipped as untokenizable and pipefail is named.

    The skipped line may be the very ``set`` that opts in, and a call the
    guard cannot read is never blocked.
    """
    lines = sum(1 for ln in strip_heredocs(raw).split("\n") if ln.strip())
    return lines > parsed_lines and bool(
        re.search("pipe_?fail", raw, re.IGNORECASE)
    )


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
    parsed = _pipelines(raw)
    if (
        _opts_into_pipefail(parsed)
        or _unreadable_pipefail_mention(raw, len(list(tokenize_lines(raw))))
        or any(ARRAY_RE[s].search(cmd) for s in accepted)
    ):
        return
    for index, (pipeline, follower) in enumerate(parsed):
        if len(pipeline) < 2:
            continue
        last_name, _, last_args = _command_of(pipeline[-1])
        if last_name not in PASS_THROUGH or _is_predicate(last_name, last_args):
            continue
        head = pipeline[0]
        while head[:1] and head[0] in BODY_KEYWORDS:
            head = head[1:]
        in_condition = head[:1] != [] and head[0] in CONDITION_KEYWORDS
        first_name, first_raw, first_args = _command_of(
            head[1:] if in_condition else head, wrapped=True
        )
        # `$?` only refers to THIS pipeline when it is read by the very next
        # one — anything in between resets it. Scanning the whole command
        # instead would flag `make x > log; echo $?; git log | head`, where
        # the `$?` belongs to make and the pipeline is plain browsing.
        next_pipeline = parsed[index + 1][0] if index + 1 < len(parsed) else []
        reads_status_var = any(
            "$?" in token for segment in next_pipeline for token in segment
        )
        consumed = in_condition or follower in {"&&", "||"} or reads_status_var
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
            f"{_right_incantation()}."
        )


if __name__ == "__main__":
    main()
