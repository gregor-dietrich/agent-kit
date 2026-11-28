"""Shared plumbing for the Claude Code, Codex and Antigravity hooks.

One definition of the hook wire format instead of a hand-maintained copy per
hook: the stdin payload parse — which fails OPEN, because an absent or
malformed hook payload must never block a tool call — the PreToolUse deny
envelope (Claude/Codex snake_case vs Antigravity camelCase), the path
resolution for Claude edits, Codex patches and Antigravity file tools, and
the shell tokenizer every Bash guard reads commands with. Shared by the
guards that read what a command posts or records: ``CLOSING_KEYWORD`` and
``EXPANSION``, the patterns for a closing or reopen keyword before an issue
reference and for a shell expansion; ``lift_heredocs`` and
``restore_heredocs``, which take a quoted ``$(cat <<'EOF' ... EOF)`` body out
of a command and put it back; ``command_words``, each simple command seen
through ``( )``, ``$( )`` and shell words; and ``git_subcommand``, a ``git``
call's subcommand past its global options. Import as a
sibling module (``import hook_lib``; hooks run by path, so this directory is
already on ``sys.path``).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NoReturn, cast

# `<<WORD` / `<<-'WORD'` — the body that follows is data, not commands.
#
# The lookarounds exclude the HERE-STRING `<<<WORD`, which is a one-line
# argument in both bash and zsh and starts no body at all. Without them the
# regex matched at the *second* `<` of `<<<'data'` and read `data` as a
# delimiter; no later line ever equals it, so the unterminated-heredoc rule
# below swallowed the whole rest of the command and every check downstream
# went blind. `(?<!<)` blocks that shifted start, `(?!<)` blocks the one at
# the first `<`.
_HEREDOC_START = re.compile(r"(?<!<)<<(?!<)-?\s*([\"']?[A-Za-z_][\w-]*[\"']?)")

# The trailing `[ \t\r]*` is load-bearing, not cosmetic: under `re.MULTILINE`
# `$` matches *before* a `\n` and `.` matches `\r`, so a CRLF patch — or a
# header carrying one stray space — captured `docs/decisions.md\r`, which no
# guarded-path test matches. That is a fail-OPEN on the very file the
# decisions guard exists to protect. `is_guarded_suffix` strips as well: the
# raw header string is tested there too, so neither site may be the exposed
# one.
PATCH_FILE = re.compile(
    r"^\*\*\* (Add|Delete|Update) File: (.+?)[ \t\r]*$", re.MULTILINE
)
PATCH_MOVE = re.compile(r"^\*\*\* Move to: (.+?)[ \t\r]*$", re.MULTILINE)

# Shells whose `-c` argument IS the command text, and the combined
# short-option spelling of that flag (`-lc`, `-ic`, `-euc`, …).
SHELL_WRAPPERS = {"sh", "bash", "zsh", "dash", "ksh", "ash"}
_SHELL_C_FLAG = re.compile(r"-[A-Za-z]*c")

SEPARATORS = {";", "&", "|", "&&", "||", ";;", "|&"}
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Runners that exec another tool: `uv run pytest`, `poetry run pytest`, …
RUNNERS = {"uv", "pipx", "poetry", "pdm", "hatch", "rye"}
# Words that stand *in front of* the real command rather than being it, so
# the command word is further right. The first four are shell keywords or
# builtins in bash and zsh alike; `noglob`/`nocorrect` are zsh's own
# precommand modifiers and exist in no other shell — a guard that did not
# know them is a guard that stops working when the shell changes. The rest
# are ordinary prefix programs that take flags of their own.
PREFIXES = {
    "time",
    "command",
    "builtin",
    "exec",
    "noglob",
    "nocorrect",
    "sudo",
    "doas",
    "env",
    "nice",
    "ionice",
    "nohup",
    "setsid",
    "stdbuf",
}
# `command -v make` LOOKS UP a tool, it does not run one — unwrapping it
# would read a probe as an invocation. Judged only on the prefix's OWN
# flags: scanning the whole argument list would read the real tool's `-v`
# (`sudo pytest -v`) as a lookup and stop checking.
LOOKUP_PREFIXES = {"command", "builtin"}
LOOKUP_FLAGS = {"-v", "-V"}

# A closing or reopen keyword directly before an issue reference: the forge
# acts on it wherever it stands.
CLOSING_KEYWORD = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|reopen(?:s|ed)?):?[ \t]*"
    r"(?:[\w.-]+/[\w.-]+)?#\d+",
    re.IGNORECASE,
)
# A shell expansion: the text it stands in cannot be read from the command.
EXPANSION = re.compile(r"`|\$[A-Za-z0-9_{(@*#?!$-]")
# Words the shell allows in front of a command, and `(`/`)` around one.
SHELL_WORDS = {"{", "}", "!", "then", "do", "else"}
_REDIRECT = re.compile(r"[<>&|]+")
# `$(cat <<'EOF' ... EOF)`, the one readable multi-line body form. An
# unquoted delimiter matches too, so its body leaves the text and cannot
# unbalance the quotes around it; it is then denied as an expansion.
_HEREDOC_SUB = re.compile(
    r"\$\(\s*cat\s+<<-?\s*(['\"]?)([\w-]+)\1[ \t]*\n"
    r"(?:(.*?)\n)?[ \t]*\2\s*\)",
    re.DOTALL,
)
_PLACEHOLDER = re.compile("\x1f(\\d+)\x1f")
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


def strip_heredocs(text: str) -> str:
    """Drop heredoc bodies, which are DATA and must not be tokenized.

    ``git commit -F - <<'EOF' … EOF`` carries prose, and prose *about* shell
    — a commit message explaining one of these very rules — tokenizes into
    perfectly good-looking commands. Without this a guard reads its own
    documentation as a command and denies it, which is exactly what happened
    the first time the pipe-status guard met a commit message.

    Handles ``<<WORD``/``<<-WORD`` with the word optionally quoted. An
    unterminated heredoc drops the rest of the text: the body is the part we
    must not read, so consuming too much only risks missing a check, never a
    false deny.
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        starts = _HEREDOC_START.findall(line)
        i += 1
        for raw_delim in starts:
            delim = raw_delim.strip("\"'")
            while i < len(lines) and lines[i].strip() != delim:
                i += 1
            i += 1  # skip the terminator line itself
    return "\n".join(out)


def logical_lines(text: str) -> list[str] | None:
    """Split *text* at the newlines that are outside quotes.

    A quoted argument spanning lines stays on one logical line, so its
    command tokenizes whole. Outside single quotes a backslash escapes the
    next character, and a backslash-newline pair is a line continuation and
    is removed. A ``#`` at the start of the text or after whitespace, ``;``,
    ``&``, ``|`` or ``(`` begins a comment, which is dropped to the end of
    its line, so an apostrophe in one opens no quote. A heredoc
    body is dropped, as :func:`strip_heredocs` drops it, but only where its
    ``<<`` stands outside quotes: quoted, it is text (``"cout << x"``), and
    reading it as a heredoc swallowed the rest of the command. A quote still
    open at the end returns None: the caller falls back to the physical
    lines, so an unbalanced command behaves as it always did.
    """
    lines: list[str] = []
    cur: list[str] = []
    delims: list[str] = []
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and quote != "'" and i + 1 < len(text):
            if text[i + 1] != "\n":
                cur.append(text[i : i + 2])
            i += 2
            continue
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1] in " \t\n;&|("):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
            continue
        elif m := _HEREDOC_START.match(text, i):
            delims.append(m[1].strip("\"'"))
            cur.append(m[0])
            i = m.end()
            continue
        elif ch == "\n":
            lines.append("".join(cur))
            cur = []
            i += 1
            for delim in delims:
                while i < len(text):
                    end = text.find("\n", i)
                    end = len(text) if end < 0 else end
                    body_line, i = text[i:end], end + 1
                    if body_line.strip() == delim:
                        break
            delims = []
            continue
        cur.append(ch)
        i += 1
    return None if quote else [*lines, "".join(cur)]


def tokenize_lines(
    text: str, *, multiline: bool = False
) -> Iterator[list[str]]:
    """Yield each line of heredoc-stripped *text* as a shell token list.

    Line by line, because shlex treats a newline as ordinary *whitespace*: a
    single pass over a multi-line command splices every line into one
    segment, and only the first line's command word is ever seen. A newline
    IS a command separator in shell. A line that does not tokenize
    (unbalanced quotes, a quoted string spanning lines) is skipped, never
    blocked. ``punctuation_chars`` emits ``|``, ``&&``, ``;`` and friends as
    standalone tokens. With *multiline*, lines are the logical lines of
    :func:`logical_lines`, so a quoted string spanning lines tokenizes; its
    comments are already gone, so shlex is told of none: left to itself it
    reads a ``#`` inside a word (``owner/repo#3``) as a comment start, which
    the shell does not.
    """
    logical = logical_lines(text) if multiline else None
    lines = strip_heredocs(text).split("\n") if logical is None else logical
    for line in lines:
        if not line.strip():
            continue
        try:
            lex = shlex.shlex(line, posix=True, punctuation_chars=True)
            lex.whitespace_split = True
            if logical is not None:
                lex.commenters = ""
            yield list(lex)
        except ValueError:
            continue


def simple_commands(
    text: str, *, multiline: bool = False
) -> Iterator[tuple[str, list[str]]]:
    """Yield (command_basename, args) for each simple command in *text*.

    Leading ``VAR=value`` assignments are skipped, so the yielded name is
    the command word. A heredoc body is prose and is never read: a commit
    message quoting a guarded command would otherwise be read as one.
    """
    for tokens in tokenize_lines(text, multiline=multiline):
        segment: list[str] = []
        segments: list[list[str]] = []
        for tok in tokens:
            if tok in SEPARATORS:
                segments.append(segment)
                segment = []
            else:
                segment.append(tok)
        segments.append(segment)
        for seg in segments:
            i = 0
            while i < len(seg) and ENV_ASSIGN.match(seg[i]):
                i += 1
            if i < len(seg):
                yield os.path.basename(seg[i]), seg[i + 1 :]


def _after_prefix(args: list[str]) -> list[str]:
    """Drop a prefix command's own flags/assignments/numeric flag values.

    Covers ``env FOO=1 …``, ``nice -n 10 …``, ``sudo -E …``. A flag whose
    value is a *word* (``sudo -u someone make test``) stops the scan there:
    the word reads as the command, matches no rule, and the command passes.
    Like every unwrap here, stopping early only costs a check.
    """
    i = 0
    while i < len(args):
        tok = args[i]
        if tok.startswith("-") or ENV_ASSIGN.match(tok) or tok.isdigit():
            i += 1
        else:
            break
    return args[i:]


def effective_tool(name: str, args: list[str]) -> tuple[str, list[str]]:
    """Unwrap runners and precommand modifiers to the real tool.

    Catches ``python -m pytest``, ``uv run pytest``, ``uvx tox``, and the
    prefix forms — ``time make test``, ``sudo make test``, ``noglob make
    test`` — so a guarded form cannot slip past by hiding behind a word.
    Applied repeatedly, because the wrappers stack (``sudo uv run pytest``);
    every step consumes at least one token, so the loop is bounded by the
    argument list. Errs toward the original command when unsure — a missed
    unwrap only means we do not block, never a false deny.
    """
    while True:
        if name in {"python", "python3"} or name.startswith("python3."):
            if args[:1] == ["-m"] and len(args) >= 2:
                name, args = os.path.basename(args[1]), args[2:]
                continue
        elif name == "uvx":
            if args:
                name, args = os.path.basename(args[0]), args[1:]
                continue
        elif name in RUNNERS and args[:1] == ["run"]:
            rest = args[1:]
            i = 0
            while i < len(rest) and rest[i].startswith("-"):
                i += 1  # skip runner flags (uv run --no-sync …)
            if i < len(rest):
                name, args = os.path.basename(rest[i]), rest[i + 1 :]
                continue
        elif name in PREFIXES:
            rest = _after_prefix(args)
            own_flags = set(args[: len(args) - len(rest)])
            lookup = name in LOOKUP_PREFIXES and bool(LOOKUP_FLAGS & own_flags)
            if rest and not lookup:
                name, args = os.path.basename(rest[0]), rest[1:]
                continue
        return name, args


def lift_heredocs(cmd: str) -> tuple[str, list[str]]:
    """*cmd* with each ``$(cat <<'WORD' ... WORD)`` body made a placeholder.

    Returns the command and the lifted bodies; :func:`restore_heredocs` puts
    one back. An unquoted delimiter becomes the literal
    ``$(unquoted-heredoc)``, which :data:`EXPANSION` matches.
    """
    bodies: list[str] = []

    def lift(m: re.Match[str]) -> str:
        if not m[1]:
            return "$(unquoted-heredoc)"
        bodies.append(m[3] or "")
        return f"\x1f{len(bodies) - 1}\x1f"

    return _HEREDOC_SUB.sub(lift, cmd), bodies


def restore_heredocs(tok: str, bodies: list[str]) -> str:
    """*tok* with each placeholder replaced by its lifted heredoc body."""

    def body(m: re.Match[str]) -> str:
        n = int(m[1])
        return bodies[n] if n < len(bodies) else m[0]

    return _PLACEHOLDER.sub(body, tok)


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


def command_words(cmd: str) -> list[tuple[str, list[str]]]:
    """Each simple command, entered through `( )`, `$( )` and shell words.

    `pr=$(tea pulls create ...)`, `(tea ...)`, `{ tea ...; }`, `! tea ...`
    and the body of an `if` or a loop hide the command word behind a token
    the tokenizer leaves in place. A wrapper (`command`, `env`, ...) is
    unwrapped; redirects are dropped.
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
                out.append(effective_tool(word, seg[1:]))
            seg = []
    return out


def git_subcommand(args: list[str]) -> tuple[str, list[str]]:
    """A ``git`` call's subcommand, past its global options, and its args."""
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in GIT_OPTS_WITH_VALUE:
            i += 2
        elif arg.startswith("-"):
            i += 1
        else:
            return arg, args[i + 1 :]
    return "", []


ANTIGRAVITY_FILE_TOOLS: frozenset[str] = frozenset(
    {
        "write_file",
        "edit_file",
        "write_to_file",
        "replace_file_content",
        "multi_replace_file_content",
        "sed_file",
    }
)
_ANTIGRAVITY_MODE = False


def is_antigravity_payload(payload: dict[str, Any]) -> bool:
    """Whether *payload* uses Antigravity's camelCase hook wire format."""
    return (
        isinstance(payload.get("toolCall"), dict)
        or "hookEventName" in payload
        or "conversationId" in payload
    )


def read_payload() -> dict[str, Any]:
    """The hook payload from stdin; exits 0 when there is none."""
    global _ANTIGRAVITY_MODE
    try:
        data: Any = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, AttributeError):
        sys.exit(0)  # empty/malformed/unexpected input — never block
    if not isinstance(data, dict):
        sys.exit(0)
    parsed = cast("dict[str, Any]", data)
    _ANTIGRAVITY_MODE = is_antigravity_payload(parsed)
    return parsed


def deny(reason: str) -> NoReturn:
    """Emit the PreToolUse deny envelope and end the hook."""
    if _ANTIGRAVITY_MODE:
        envelope: dict[str, Any] = {"decision": "deny", "reason": reason}
    else:
        envelope = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    print(json.dumps(envelope))
    sys.exit(0)


# The interpreter is whatever python3 the client finds first on PATH, not
# the test venv's, and the PEP 604 unions below (`str | None`) would be
# evaluated when their def runs: under 3.9 importing this module raised, the
# hook crashed, and a crashed PreToolUse hook fails OPEN — every guard
# allowed. `from __future__ import annotations` defers them, so the import
# reaches this check on any 3.7+; the check, placed before the first def of
# a hook's own, is what each entry point hits instead. A payload it cannot
# read still passes, as everywhere, and so does a SessionStart hook's, which
# has no tool call to refuse.
FLOOR = (3, 10)
if sys.version_info < FLOOR:
    _floor_payload = read_payload()
    if (
        _floor_payload.get("hook_event_name") == "SessionStart"
        or _floor_payload.get("hookEventName") == "SessionStart"
    ):
        sys.exit(0)
    deny(
        f"agent-kit's hooks need Python {FLOOR[0]}.{FLOOR[1]} or newer, but "
        f"python3 here is {sys.version.split()[0]} ({sys.executable}). Put "
        "a newer python3 first on PATH; until then this guard refuses each "
        "call that reaches it rather than letting it through unchecked."
    )


def tool_name(payload: dict[str, Any]) -> str:
    """The tool name carried by a Claude/Codex or Antigravity payload."""
    tc: Any = payload.get("toolCall")
    if isinstance(tc, dict):
        return str(tc.get("name", "") or "")
    return str(payload.get("tool_name", "") or "")


def tool_input(payload: dict[str, Any]) -> dict[str, Any]:
    """The tool-arguments object, or ``{}`` when oddly shaped."""
    tc: Any = payload.get("toolCall")
    if isinstance(tc, dict):
        args: Any = tc.get("args")
        return cast("dict[str, Any]", args) if isinstance(args, dict) else {}
    ti: Any = payload.get("tool_input")
    return cast("dict[str, Any]", ti) if isinstance(ti, dict) else {}


def _wrapper_script(parts: list[str]) -> str | None:
    """The script of a ``bash -lc <script>``-style argv, if that is what it is.

    Returning the script rather than the joined argv is what keeps the
    downstream guards working: quoting the script back into one string (as
    ``shlex.join`` would) hides the very ``|``, ``>`` and command words they
    tokenize for, so ``["bash", "-lc", "make test | tail -5"]`` would still
    read as a single opaque token.
    """
    if len(parts) < 3 or os.path.basename(parts[0]) not in SHELL_WRAPPERS:
        return None
    for i, tok in enumerate(parts[1:-1], start=1):
        if _SHELL_C_FLAG.fullmatch(tok):
            return parts[i + 1]
        if not tok.startswith("-"):
            return None
    return None


def command_text(ti: dict[str, Any]) -> str:
    """The shell command a tool payload carries, as one scannable string.

    Claude's Bash tool sends ``tool_input.command`` as a string, Codex's
    shell tool sends the same or an argv list
    (``["bash", "-lc", "make test | tail -5"]``), and Antigravity's
    ``run_command`` sends ``toolCall.args.CommandLine``. ``str()`` on an
    argv list would yield its Python repr, which matches none of the guards'
    patterns — every Bash guard would go blind on that shape.
    """
    if _ANTIGRAVITY_MODE:
        raw: Any = ti.get("CommandLine") or ti.get("command")
    else:
        raw = ti.get("command") or ti.get("CommandLine")
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, list):
        return "" if raw is None else str(raw)
    items = cast("list[Any]", raw)
    parts = [item if isinstance(item, str) else str(item) for item in items]
    script = _wrapper_script(parts)
    if script is not None:
        return script
    return shlex.join(parts)


def is_guarded_suffix(path: str, suffix: str) -> bool:
    """Whether *path* is, or ends with, ``/<suffix>`` — whitespace tolerant.

    Trailing whitespace and a CR are stripped first: an apply_patch header is
    matched out of the raw command text, so a CRLF patch or a stray trailing
    space would otherwise make the guarded file unrecognisable.
    """
    norm = path.strip().replace("\\", "/")
    return norm == suffix or norm.endswith(f"/{suffix}")


def payload_cwd(payload: dict[str, Any]) -> Path:
    """Return the client cwd used to resolve relative tool paths."""
    raw: Any = payload.get("cwd")
    if isinstance(raw, str) and raw:
        return Path(raw)
    workspaces: Any = payload.get("workspacePaths")
    if (
        isinstance(workspaces, list)
        and workspaces
        and isinstance(workspaces[0], str)
        and workspaces[0]
    ):
        return Path(workspaces[0])
    return Path.cwd()


def absolute_path(payload: dict[str, Any], raw: str) -> Path:
    """Resolve one client tool path without requiring it to exist."""
    path = Path(raw)
    if not path.is_absolute():
        path = payload_cwd(payload) / path
    return Path(os.path.abspath(path))


def changed_paths(payload: dict[str, Any]) -> list[Path]:
    """Return every path targeted by a Claude, Codex or Antigravity edit.

    Claude's Edit/Write tools carry one ``tool_input.file_path``. Codex's
    ``apply_patch`` carries its patch language in ``tool_input.command`` and
    can update multiple files in one invocation. Antigravity's file edit
    tools carry ``toolCall.args.Path`` or ``toolCall.args.TargetFile``. Move
    destinations count as changed too; duplicate paths retain only their
    first occurrence.
    """
    ti = tool_input(payload)
    tool = tool_name(payload)
    if tool in ("Edit", "Write"):
        raw = ti.get("file_path")
        if isinstance(raw, str) and raw:
            return [absolute_path(payload, raw)]
        return []
    if tool in ANTIGRAVITY_FILE_TOOLS:
        paths: list[Path] = []
        for key in ("Path", "TargetFile"):
            raw = ti.get(key)
            if isinstance(raw, str) and raw:
                path = absolute_path(payload, raw)
                if path not in paths:
                    paths.append(path)
        return paths
    if tool != "apply_patch":
        return []

    command = command_text(ti)
    if not command:
        return []
    raw_paths = [m.group(2) for m in PATCH_FILE.finditer(command)]
    raw_paths += PATCH_MOVE.findall(command)
    result: list[Path] = []
    seen: set[Path] = set()
    for raw in raw_paths:
        path = absolute_path(payload, raw)
        if path not in seen:
            result.append(path)
            seen.add(path)
    return result
