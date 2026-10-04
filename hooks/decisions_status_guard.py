#!/usr/bin/env python3
"""PreToolUse guard (Write|Edit|apply_patch|Bash): Status is the author's.

A decisions log (docs/decisions.md) marks each ``## ADR-NNNN`` entry
**Status:** Accepted | Proposed | retired. Accepted carries real force: a
review finding that re-raises an Accepted entry is a false positive. So an
agent that can set Accepted can ratify its own draft and thereby suppress
objections to it.

Three transitions are therefore blocked on docs/decisions.md, judged
**per entry** on the simulated result of the edit (never on the edit's raw
fragments — fragment counting was bypassable by excluding the marker prefix
from ``old_string``, and by compound edits whose global counts net to zero):

  1. An entry LOSING a "**Status:** Proposed" marker — the Proposed→Accepted
     flip, and equally the quiet deletion of a draft.
  2. An entry GAINING a "**Status:** Accepted" marker — writing a new entry
     as Accepted outright rather than flipping an existing one.
  3. An entry LOSING a "**Status:** Accepted" marker — de-ratification, the
     mirror image of (2): an agent could demote a decision it dislikes and
     then "legitimately" re-raise it. Retiring a spent entry trips this too
     — that is intended; it is a decision act and belongs to the author.

Everything else — drafting a Proposed entry, amending prose, adding Premise/
Guard lines — passes untouched. Markers appearing outside any ``## ADR-``
entry are compared globally as a backstop.

A marker is recognised by its VALUE, case-insensitively and whatever
whitespace separates the tokens: ``**Status:** accepted`` renders as a
ratified entry to every reader, so it must count as one here. Enforcing one
exact spelling is a job for the project's own format check, not this hook.

The Bash tool cannot be vetted the same way, so any command that mentions
decisions.md AND carries a write-shaped token (in-place editors, redirects,
tee/mv/cp/apply_patch, inline interpreters) is denied with a pointer to
Edit/Write — best-effort by design; plain reads (grep/cat/git log) pass. An
argv-list ``command`` is scanned like a string one, and a ``bash -lc
<script>`` wrapper is unwrapped to the script it runs.

A no-op in a repository that keeps no decisions log: an edit is vetted only
when the file it targets already exists, and a Bash command only when the
checkout it runs in (found by walking up from the payload's cwd to the
directory holding ``.git``) has a docs/decisions.md.

Scope, honestly: this constrains Claude Code and Codex tool calls only, in
whatever checkout they target (the path test is a suffix match, so worktrees
and secondary checkouts are covered). It is a guardrail on those clients, not
a repo invariant; ``git log -p docs/decisions.md`` remains the audit trail.
Deliberately NOT paired with a pre-commit ban on committing a Proposed entry
— committing a draft is legitimate, and blocking it would pressure a
premature flip to Accepted, manufacturing the rubber-stamp the rule exists
to prevent.

Behavior is pinned by tests/hooks/test_decisions_status_guard.py — a crashed
PreToolUse hook fails OPEN in the harness (only exit 2 or a deny payload
blocks), so those tests are what notices a broken guard.

Receives tool invocation JSON on stdin. Claude Edit/Write uses
``tool_input.file_path`` and Codex apply_patch uses ``tool_input.command``;
the wire-format plumbing is shared across hooks via hook_lib.py.
"""

import re
import sys
from pathlib import Path
from typing import Any

from hook_lib import (
    absolute_path,
    changed_paths,
    command_text,
    deny,
    is_guarded_suffix,
    payload_cwd,
    read_payload,
    tool_input,
)

PROPOSED = "**Status:** Proposed"
ACCEPTED = "**Status:** Accepted"

# Marker detection is deliberately NOT byte-exact. Counting the literal
# spelling meant `**Status:** accepted`, `**Status:**Accepted` and
# `__Status:__ Accepted` all read as *no* Accepted marker, so drafting a
# new entry that way slipped the guard while still rendering as a
# ratified entry to every human reader. The value's case and the
# whitespace between the tokens are therefore both free; the value word
# itself is what classifies the marker.
_STATUS_MARKER = re.compile(
    r"(?:\*\*|__)\s*Status\s*:?\s*(?:\*\*|__)\s*:?\s*"
    r"(?:\*\*|__|\*|_)?\s*(?P<value>[A-Za-z][A-Za-z-]*)",
    re.IGNORECASE,
)

_HEADING = re.compile(r"^## (ADR-\d+)", re.MULTILINE)

# An email in angle brackets (a commit trailer's <user@host>) is not a
# redirect — stripped before the token scan, or every `git commit` carrying
# the standard Co-Authored-By trailer would read as write-shaped.
_EMAIL_SPAN = re.compile(r"<[^<>\s]+@[^<>\s]+>")

# Write-shaped tokens for the Bash route: in-place editors, any redirect,
# file movers/writers, inline interpreters. Conservative on purpose — a
# false deny costs a re-phrase; a false allow costs the invariant.
# `-c` is matched as a combined short option too (`bash -lc`, `python3
# -uc`) and in its separated form (`bash -l -c`): `-lc` is the standard
# wrapper spelling an agent harness emits, and requiring `-c` to be its
# own contiguous token defeated the whole arm against real payloads.
# Between the interpreter name and the flag only further option words
# are allowed, so an unrelated `-c` later in a long command still does
# not match. `apply_patch` is a first-class writer and belongs here for
# the same reason `tee`/`mv` do — Codex spells it as argv[0] of a shell
# call.
_OPTS = r"(?:\s+-[A-Za-z]+)*"
_BASH_WRITE_TOKENS = re.compile(
    r"(?:\bsed\b[^|;&]*\s-[A-Za-z]*i"
    r"|\bperl\b[^|;&]*\s-[A-Za-z]*i"
    r"|>"
    r"|\b(?:tee|mv|cp|dd|truncate|sponge|install|rsync|apply_patch)\b"
    r"|\bpython3?(?:\.\d+)?\b[^|;&]*\s-[A-Za-z]*c\b"
    r"|\b(?:sh|bash|zsh|dash|ksh|ash)\b" + _OPTS + r"\s+-[A-Za-z]*c\b)"
)

# Trailing whitespace/CR is excluded from the capture — see hook_lib's
# copy of these patterns for what a CRLF patch header did without it.

GUARDED = "docs/decisions.md"
_PATCH_SECTION = re.compile(
    r"^\*\*\* (Add|Delete|Update) File: (.+?)[ \t\r]*$", re.MULTILINE
)
_PATCH_MOVE = re.compile(r"^\*\*\* Move to: (.+?)[ \t\r]*$", re.MULTILINE)


def _marker_counts(block: str) -> tuple[int, int]:
    """(proposed, accepted) markers in *block*, however cased or spaced."""
    values = [m.group("value").lower() for m in _STATUS_MARKER.finditer(block)]
    return values.count("proposed"), values.count("accepted")


def _entry_status_counts(text: str) -> dict[str, tuple[int, int]]:
    """Per-ADR (proposed, accepted) marker counts; ``""`` is non-entry text."""
    matches = list(_HEADING.finditer(text))
    first = matches[0].start() if matches else len(text)
    counts = {"": _marker_counts(text[:first])}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        p, a = counts.get(m.group(1), (0, 0))
        block_p, block_a = _marker_counts(text[m.start() : end])
        counts[m.group(1)] = (p + block_p, a + block_a)
    return counts


def _vet(before: str, after: str) -> None:
    """Deny iff any entry (or the non-entry remainder) makes a blocked move."""
    old = _entry_status_counts(before)
    new = _entry_status_counts(after)
    for adr in sorted(set(old) | set(new)):
        old_p, old_a = old.get(adr, (0, 0))
        new_p, new_a = new.get(adr, (0, 0))
        where = adr or "outside any ADR entry"
        if new_p < old_p:
            deny(
                f"Refused: this edit removes a '{PROPOSED}' marker "
                f"({where}) in docs/decisions.md. Ratifying a draft ADR — "
                "or silently dropping one — is the author's act alone. "
                "Leave the entry Proposed and ask the maintainer to flip it."
            )
        if new_a > old_a:
            deny(
                f"Refused: this edit adds a '{ACCEPTED}' marker ({where}) "
                "in docs/decisions.md. A new entry is drafted "
                f"'{PROPOSED}' and ratified by the author — writing it "
                "Accepted outright is the same act by another route."
            )
        if new_a < old_a:
            deny(
                f"Refused: this edit removes a '{ACCEPTED}' marker "
                f"({where}) in docs/decisions.md. De-ratifying an entry "
                "strips its anti-relitigation force — the mirror image of "
                "granting it, and a route to re-raising a decision by "
                "first demoting it. Retiring a spent entry counts as well. "
                "Ask the maintainer to make the change."
            )


def _is_guarded(path: str) -> bool:
    return is_guarded_suffix(path, GUARDED)


def _checkout_has_log(payload: dict[str, Any]) -> bool:
    """Whether the checkout the payload's cwd sits in keeps a decisions log.

    Walks up to the directory holding ``.git`` (a file in a worktree, a
    directory otherwise) and looks for the log there. With no ``.git`` on
    the way up, the cwd itself is the only candidate root.
    """
    cwd = payload_cwd(payload)
    for root in (cwd, *cwd.parents):
        if (root / ".git").exists():
            return (root / GUARDED).is_file()
    return (cwd / GUARDED).is_file()


def _is_guarded_header(payload: dict[str, Any], raw: str) -> bool:
    """Whether an apply_patch header names the guarded file.

    The header is relative to the client's cwd, so it is absolutised first —
    the same resolution ``changed_paths`` applies. Both spellings are then
    accepted, because a session rooted at the repo top writes
    ``docs/decisions.md`` and one rooted in ``docs/`` writes ``decisions.md``.
    """
    return _is_guarded(str(absolute_path(payload, raw)))


def _patch_lines(lines: list[str]) -> tuple[str, str] | None:
    """Translate one apply_patch hunk to its old/new text fragments."""
    old: list[str] = []
    new: list[str] = []
    for line in lines:
        if line == "*** End of File":
            continue
        if not line:
            # A blank CONTEXT line. apply_patch writes it as the empty
            # string rather than as a lone space, so it is unchanged text on
            # both sides, not a parse failure — reading it as one denied
            # every prose edit whose context crossed a paragraph break.
            old.append("\n")
            new.append("\n")
            continue
        if line[0] not in " +-":
            return None
        prefix = line[0]
        content = f"{line[1:]}\n"
        if prefix in " -":
            old.append(content)
        if prefix in " +":
            new.append(content)
    return "".join(old), "".join(new)


def _apply_update(before: str, body: str) -> str | None:
    """Simulate the update hunks relevant to the guarded file."""
    after = before
    chunks = re.split(r"^@@.*$", body, flags=re.MULTILINE)[1:]
    if not chunks:
        return None
    for chunk in chunks:
        # Only the split's own artefacts are dropped: the empty first
        # element left by the `@@` line, and the empty last one left by a
        # trailing newline. Every other empty line is a blank context line
        # and must survive — `_patch_lines` reads it as context.
        raw_lines = chunk.split("\n")[1:]
        if raw_lines and not raw_lines[-1]:
            raw_lines = raw_lines[:-1]
        move = "*** Move to:"
        lines = [line for line in raw_lines if not line.startswith(move)]
        fragments = _patch_lines(lines)
        if fragments is None:
            return None
        old, new = fragments
        if old not in after:
            # apply_patch accepts a final file line without a newline. Mirror
            # that case without weakening an otherwise exact-context match.
            old = old.removesuffix("\n")
            new = new.removesuffix("\n")
        if not old or old not in after:
            return None
        after = after.replace(old, new, 1)
    return after


def _codex_after(
    payload: dict[str, Any],
    command: str,
    before: str,
) -> str | None:
    """Return the simulated docs/decisions.md after a Codex patch.

    Headers are resolved against the payload's cwd before the guarded-path
    test, exactly as ``changed_paths`` resolves them. Testing the raw header
    here instead made the two disagree for a session rooted anywhere but the
    repo top: a bare ``decisions.md`` header from ``docs/`` was picked up as
    the guarded file by one and skipped by the other, so ``found`` stayed
    False and every edit from such a session — prose included — was denied.
    """
    matches = list(_PATCH_SECTION.finditer(command))
    after = before
    found = False
    for index, match in enumerate(matches):
        if not _is_guarded_header(payload, match.group(2)):
            continue
        found = True
        if index + 1 < len(matches):
            end = matches[index + 1].start()
        else:
            end = len(command)
        body = command[match.end() : end]
        body = body.split("*** End Patch", 1)[0].lstrip("\n")
        action = match.group(1)
        if action == "Delete":
            after = ""
            continue
        if action == "Add":
            lines = body.splitlines()
            if any(not line.startswith("+") for line in lines):
                return None
            after = "".join(f"{line[1:]}\n" for line in lines)
            continue
        updated = _apply_update(after, body)
        if updated is None:
            return None
        after = updated
    return after if found else None


def _moves_guarded_file(payload: dict[str, Any], command: str) -> bool:
    """Whether a patch section moves docs/decisions.md from or to a path."""
    matches = list(_PATCH_SECTION.finditer(command))
    for index, match in enumerate(matches):
        if index + 1 < len(matches):
            end = matches[index + 1].start()
        else:
            end = len(command)
        move = _PATCH_MOVE.search(command, match.end(), end)
        if move and (
            _is_guarded_header(payload, match.group(2))
            or _is_guarded_header(payload, move.group(1))
        ):
            return True
    return False


def _existing_logs(payload: dict[str, Any]) -> list[Path]:
    """The guarded paths an edit targets, where that log already exists.

    Creating a decisions log is not a status transition: a repository
    without one is outside this guard's remit until it has one.
    """
    return [
        path
        for path in changed_paths(payload)
        if _is_guarded(str(path)) and path.is_file()
    ]


def main() -> None:
    data = read_payload()
    tool = str(data.get("tool_name", "") or "")
    ti = tool_input(data)

    if tool == "Bash":
        command = command_text(ti)
        scannable = _EMAIL_SPAN.sub("", command)
        if (
            "decisions.md" in command
            and _BASH_WRITE_TOKENS.search(scannable)
            and _checkout_has_log(data)
        ):
            deny(
                "Refused: this shell command looks like it writes "
                "docs/decisions.md, which would bypass the ADR status "
                "guard. Make the change through the Edit/Write tools so "
                "the guard can vet it; for pure reads, drop the "
                "write-shaped tokens (redirects, -i, tee/mv/cp, inline "
                "interpreters) from the command."
            )
        sys.exit(0)

    if tool == "apply_patch":
        paths = _existing_logs(data)
        if not paths:
            sys.exit(0)
        command = command_text(ti)
        if _moves_guarded_file(data, command):
            deny(
                "Refused: this patch moves docs/decisions.md. Moving the "
                "guarded file implicitly removes or replaces all of its ADR "
                "status markers, which is an author-only decision. Make the "
                "non-status edits without moving the file."
            )
        path = paths[0]
        try:
            before = path.read_text(encoding="utf-8")
        except OSError:
            before = ""
        after = _codex_after(data, command, before)
        if after is None:
            deny(
                "Refused: this patch targets docs/decisions.md but the ADR "
                "status guard cannot safely simulate its patch structure. "
                "Use a standard apply_patch Add/Delete/Update section so the "
                "status-marker transitions can be vetted."
            )
        _vet(before, after)
        sys.exit(0)

    if tool not in ("Edit", "Write"):
        sys.exit(0)
    # Resolved through changed_paths, so a RELATIVE file_path is read
    # against the payload's cwd rather than the hook process's own. Opening
    # the raw string meant the same edit was vetted when the hook happened to
    # run from the repo root and waved through when it did not.
    edited = _existing_logs(data)
    if not edited:
        sys.exit(0)
    target = edited[0]

    try:
        before = target.read_text(encoding="utf-8")
    except OSError:
        before = ""

    if tool == "Write":
        after = str(ti.get("content", "") or "")
    else:
        old_string = str(ti.get("old_string", "") or "")
        new_string = str(ti.get("new_string", "") or "")
        if not old_string or old_string not in before:
            sys.exit(0)  # the Edit itself will fail; nothing to vet
        if ti.get("replace_all"):
            after = before.replace(old_string, new_string)
        else:
            after = before.replace(old_string, new_string, 1)

    _vet(before, after)
    sys.exit(0)


if __name__ == "__main__":
    main()
