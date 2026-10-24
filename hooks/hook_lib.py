"""Shared plumbing for the Claude Code and Codex hooks in this directory.

One definition of the hook wire format instead of a hand-maintained copy per
hook: the stdin payload parse — which fails OPEN, because an absent or
malformed payload must never block a tool call — the PreToolUse deny
envelope, the path resolution for Claude edits and Codex patches, and the
shell tokenizer every Bash guard reads commands with. Import as a sibling
module (``import hook_lib``; hooks run by path, so this directory is already
on ``sys.path``).
"""

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
_SHELL_WRAPPERS = {"sh", "bash", "zsh", "dash", "ksh", "ash"}
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


def tokenize_lines(text: str) -> Iterator[list[str]]:
    """Yield each line of heredoc-stripped *text* as a shell token list.

    Line by line, because shlex treats a newline as ordinary *whitespace*: a
    single pass over a multi-line command splices every line into one
    segment, and only the first line's command word is ever seen. A newline
    IS a command separator in shell. A line that does not tokenize
    (unbalanced quotes, a quoted string spanning lines) is skipped, never
    blocked. ``punctuation_chars`` emits ``|``, ``&&``, ``;`` and friends as
    standalone tokens.
    """
    for line in strip_heredocs(text).split("\n"):
        if not line.strip():
            continue
        try:
            lex = shlex.shlex(line, posix=True, punctuation_chars=True)
            lex.whitespace_split = True
            yield list(lex)
        except ValueError:
            continue


def simple_commands(text: str) -> Iterator[tuple[str, list[str]]]:
    """Yield (command_basename, args) for each simple command in *text*.

    Leading ``VAR=value`` assignments are skipped, so the yielded name is
    the command word. A heredoc body is prose and is never read: a commit
    message quoting a guarded command would otherwise be read as one.
    """
    for tokens in tokenize_lines(text):
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


def read_payload() -> dict[str, Any]:
    """The tool-invocation payload from stdin; exits 0 when there is none."""
    try:
        data: Any = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, AttributeError):
        sys.exit(0)  # empty/malformed/unexpected input — never block
    if not isinstance(data, dict):
        sys.exit(0)
    return cast("dict[str, Any]", data)


def deny(reason: str) -> NoReturn:
    """Emit the PreToolUse deny envelope and end the hook."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.exit(0)


# The interpreter is whatever python3 the client finds first on PATH, not
# the test venv's, and the PEP 604 unions below (`str | None`) are evaluated
# when their def runs: under 3.9 importing this module raised, the hook
# crashed, and a crashed PreToolUse hook fails OPEN — every guard allowed.
# Every entry point imports this module before defining anything of its
# own, so this check, placed before the first such def, is what each one
# hits instead. A payload it cannot read still passes, as everywhere.
FLOOR = (3, 10)
if sys.version_info < FLOOR:
    read_payload()
    deny(
        f"agent-kit's hooks need Python {FLOOR[0]}.{FLOOR[1]} or newer, but "
        f"python3 here is {sys.version.split()[0]} ({sys.executable}). Put "
        "a newer python3 first on PATH; until then this guard refuses each "
        "call that reaches it rather than letting it through unchecked."
    )


def tool_input(payload: dict[str, Any]) -> dict[str, Any]:
    """The payload's ``tool_input`` object, or ``{}`` when oddly shaped."""
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
    if len(parts) < 3 or os.path.basename(parts[0]) not in _SHELL_WRAPPERS:
        return None
    for i, tok in enumerate(parts[1:-1], start=1):
        if _SHELL_C_FLAG.fullmatch(tok):
            return parts[i + 1]
        if not tok.startswith("-"):
            return None
    return None


def command_text(ti: dict[str, Any]) -> str:
    """The shell command a tool payload carries, as one scannable string.

    Claude's Bash tool sends ``tool_input.command`` as a string, and so does
    Codex's shell tool in the payloads captured so far; an argv list
    (``["bash", "-lc", "make test | tail -5"]``) is handled too. ``str()``
    on the list would yield its Python repr, which matches none of the
    guards' patterns — every Bash guard would go blind on that shape.
    """
    raw: Any = ti.get("command")
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
    return Path.cwd()


def absolute_path(payload: dict[str, Any], raw: str) -> Path:
    """Resolve one Claude/Codex path without requiring it to exist."""
    path = Path(raw)
    if not path.is_absolute():
        path = payload_cwd(payload) / path
    return Path(os.path.abspath(path))


def changed_paths(payload: dict[str, Any]) -> list[Path]:
    """Return every path targeted by a Claude edit or Codex patch.

    Claude's Edit/Write tools carry one ``tool_input.file_path``. Codex's
    ``apply_patch`` carries its patch language in ``tool_input.command`` and
    can update multiple files in one invocation. Move destinations count as
    changed too; duplicate paths retain only their first occurrence.
    """
    ti = tool_input(payload)
    tool = str(payload.get("tool_name", "") or "")
    if tool in ("Edit", "Write"):
        raw = ti.get("file_path")
        if isinstance(raw, str) and raw:
            return [absolute_path(payload, raw)]
        return []
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
