#!/usr/bin/env python3
"""PreToolUse guard (Write|Edit|apply_patch): Status is the author's.

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
Markers are counted both in the text as written and as it renders (HTML
comments and tags, entities, invisible format characters, compatibility
forms and markup around the value resolved), and a blocked move in either
view is denied. A value with any non-ASCII letter is neither Proposed nor
Accepted but held like Accepted, in a count of its own: one may be neither
added nor removed. Look-alike letters from another script (Cyrillic А in
``Аccepted``) render as Accepted, and the stdlib has no confusables table
to read them by, so refusing them costs only a re-spelling.

A no-op in a repository that keeps no decisions log: an edit is vetted only
when the file it targets already exists. The guarded path is matched
lexically and after resolving symlinks.

Scope, honestly: this constrains the Claude Code and Codex edit tools only,
in whatever checkout they target (the path test is a suffix match, so
worktrees and secondary checkouts are covered). A shell command that writes
the file is deliberately not vetted. A Bash arm that tried was removed on
purpose: the ways a shell can write a file are open-ended, every review
round found more, and the cost was out of proportion to what it protects.
Undesired status changes are caught in code review. Do not reintroduce
it. The guard catches an agent ratifying its own draft in the ordinary
course of editing, not one set on getting around it.
``git log -p docs/decisions.md`` remains the audit trail.
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

import html
import os
import re
import sys
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hook_lib import (
    PATCH_FILE,
    PATCH_MOVE,
    absolute_path,
    changed_paths,
    command_text,
    deny,
    is_guarded_suffix,
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
# itself is what classifies the marker. Markup inside or around the value
# (`Accepted`, _**Accepted**_, [Accepted](#), Ac*cep*ted) is dropped from
# it before it is read. The value is read in letters of any script, so a
# look-alike spelling is captured whole rather than cut off or missed.
_STATUS_MARKER = re.compile(
    r"(?:\*\*|__)\s*Status\s*:?\s*(?:\*\*|__)\s*:?\s*"
    r"[\s*_`\[]*(?P<value>[^\W\d_](?:[^\W\d]|[*`-])*)",
    re.IGNORECASE,
)
_VALUE_MARKUP = str.maketrans("", "", "*_`")

# What a reader never sees: a closed HTML comment and the tags themselves.
# A comment kept a Proposed marker in the source while the page showed only
# the Accepted written next to it. Only tag-shaped `<…>` is stripped: `3 < 5`
# is text. An unclosed `<!--` hides the rest of the page only where it opens
# a line, as an HTML block does; mid-line, as in a code span, it is text.
# This view is an approximation of rendering, so `_vet` judges the raw text
# as well and denies when either view shows a blocked move.
_UNRENDERED = re.compile(
    r"<!--.*?-->|^ {0,3}<!--(?!.*?-->).*"
    r"|</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>",
    re.DOTALL | re.MULTILINE,
)

_HEADING = re.compile(r"^## (ADR-\d+)", re.MULTILINE)

GUARDED = "docs/decisions.md"

def _rendered(text: str) -> str:
    """*text* as a reader sees it, as far as status markers go."""
    text = html.unescape(_UNRENDERED.sub("", text))
    text = unicodedata.normalize("NFKC", text)
    return "".join(c for c in text if unicodedata.category(c) != "Cf")


def _marker_counts(block: str) -> tuple[int, int, int]:
    """(proposed, accepted, non-ASCII) markers in *block*, however spelled."""
    values = [
        m.group("value").translate(_VALUE_MARKUP).lower()
        for m in _STATUS_MARKER.finditer(block)
    ]
    foreign = sum(not v.isascii() for v in values)
    return values.count("proposed"), values.count("accepted"), foreign


def _entry_status_counts(text: str) -> dict[str, tuple[int, ...]]:
    """Per-ADR ``_marker_counts``; ``""`` is non-entry text."""
    matches = list(_HEADING.finditer(text))
    first = matches[0].start() if matches else len(text)
    counts = {"": _marker_counts(text[:first])}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = _marker_counts(text[m.start() : end])
        prev = counts.get(m.group(1), (0, 0, 0))
        counts[m.group(1)] = tuple(map(sum, zip(prev, block)))
    return counts


def _vet(before: str, after: str) -> None:
    """Deny iff any entry (or the non-entry remainder) makes a blocked move.

    Judged on the raw text and on the rendered view alike: where the two
    disagree about what a span hides, the stricter reading wins.
    """
    _vet_view(before, after)
    _vet_view(_rendered(before), _rendered(after))


def _vet_view(before: str, after: str) -> None:
    """One view's verdict; see ``_vet``."""
    old = _entry_status_counts(before)
    new = _entry_status_counts(after)
    for adr in sorted(set(old) | set(new)):
        old_p, old_a, old_f = old.get(adr, (0, 0, 0))
        new_p, new_a, new_f = new.get(adr, (0, 0, 0))
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
        if new_f != old_f:
            deny(
                f"Refused: this edit {'adds' if new_f > old_f else 'removes'} "
                f"a status value spelled with non-ASCII letters ({where}) in "
                "docs/decisions.md. Such a value can render as Accepted while "
                "reading as neither Proposed nor Accepted, so it is held like "
                "Accepted. Spell a new status in ASCII letters; to change an "
                "existing one, ask the maintainer."
            )


# Claude's Edit matches old_string through curly/straight quote differences
# (measured), so an old_string missing verbatim may still apply. Line
# endings need no such step: read_text already reads CRLF as LF.
_QUOTES = str.maketrans("\u2018\u2019\u201c\u201d", "''\"\"")



def _is_guarded(path: str) -> bool:
    """Whether *path* names the log, lexically or once symlinks resolve.

    The lexical test alone missed an edit made through a symlink whose own
    name is something else; the resolved path is what actually changes.
    Case-blind, because on a case-insensitive filesystem (macOS, Windows)
    ``docs/Decisions.md`` is the log, and ``realpath`` does not fix case.
    """
    return any(
        is_guarded_suffix(p.lower(), GUARDED)
        for p in (path, os.path.realpath(path))
    )


def _sections(command: str) -> Iterator[tuple[str, str, str]]:
    """(action, header, body) for each file section of an apply_patch.

    A body runs to the next section header or the end-of-patch marker.
    """
    matches = list(PATCH_FILE.finditer(command))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(command)
        body = command[m.end() : end].split("*** End Patch", 1)[0]
        yield m.group(1), m.group(2), body.removeprefix("\n")


@dataclass
class _Hunk:
    anchor: str | None = None
    old: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)
    at_eof: bool = False


def _hunks(body: str) -> list[_Hunk] | None:
    """Parse an Update section's body; None when a line fits no hunk.

    As Codex reads it: the first hunk may omit its ``@@`` line, and ``@@
    <line>`` names a line to seek to before matching. A blank line is
    unchanged context — apply_patch writes it as the empty string rather
    than as a lone space, and reading it as a parse failure denied every
    prose edit whose context crossed a paragraph break.
    """
    hunks: list[_Hunk] = []
    lines = body.split("\n")
    if lines[-1] == "":
        lines.pop()  # the body's own final newline
    for line in lines:
        if line.startswith("*** Move to:"):
            continue
        if line.startswith("@@"):
            hunks.append(_Hunk(line[3:] or None))
            continue
        if not hunks:
            hunks.append(_Hunk())
        hunk = hunks[-1]
        if line == "*** End of File":
            hunk.at_eof = True
            continue
        if line and line[0] not in " +-":
            return None
        prefix, text = (line[0], line[1:]) if line else (" ", "")
        if prefix in " -":
            hunk.old.append(text)
        if prefix in " +":
            hunk.new.append(text)
    return hunks


def _seek(lines: list[str], pattern: list[str], start: int) -> int | None:
    """First index from *start* where *pattern* occurs as whole lines."""
    n = len(pattern)
    ends = range(start, len(lines) - n + 1)
    return next((i for i in ends if lines[i : i + n] == pattern), None)


def _apply_update(before: str, body: str) -> str | None:
    """Simulate one Update section the way Codex applies it.

    Each semantic here was measured against Codex's own apply_patch.
    Hunks move strictly forward: an anchor, and then the old lines, are
    sought from where the previous hunk ended — replacing the first match
    anywhere let two anchored hunks vet one entry while changing two
    others. A hunk without old lines appends at the end of the file,
    anchor or not. Matching is exact: Codex's whitespace-tolerant fallback
    is not modelled, so such a hunk is denied rather than vetted against
    text it does not touch.
    """
    hunks = _hunks(body)
    if not hunks:
        return None
    lines = before.split("\n")
    if lines[-1] == "":
        lines.pop()
    cursor = 0
    for hunk in hunks:
        if hunk.anchor is not None:
            at = _seek(lines, [hunk.anchor], cursor)
            if at is None:
                return None
            cursor = at + 1
        old, new = hunk.old, hunk.new
        if not old:
            lines += new
            continue
        start = max(cursor, len(lines) - len(old)) if hunk.at_eof else cursor
        at = _seek(lines, old, start)
        if at is None and len(old) > 1 and old[-1] == "":
            # Codex retries without a trailing blank context line.
            old, new = old[:-1], new[:-1] if new[-1:] == [""] else new
            at = _seek(lines, old, start)
        if at is None:
            return None
        lines[at : at + len(old)] = new
        cursor = at + len(new)
    return "\n".join(lines) + "\n"


def _codex_after(
    payload: dict[str, Any], command: str, path: Path, before: str
) -> str | None:
    """The simulated text of the log at *path* after a Codex patch.

    Only sections whose header resolves to *path* apply. Folding every
    log-shaped section into one buffer let an Add of a decoy log elsewhere
    overwrite the simulated result of the real one, and simulated a second
    log against the first one's text. Headers resolve against the payload's
    cwd, as ``changed_paths`` resolves them.
    """
    target = os.path.realpath(path)
    after = before
    for action, header, body in _sections(command):
        if os.path.realpath(absolute_path(payload, header)) != target:
            continue
        if action == "Delete":
            after = ""
        elif action == "Add":
            lines = body.splitlines()
            if any(not line.startswith("+") for line in lines):
                return None
            after = "".join(f"{line[1:]}\n" for line in lines)
        elif (updated := _apply_update(after, body)) is None:
            return None
        else:
            after = updated
    return after


def _moves_guarded_file(payload: dict[str, Any], command: str) -> bool:
    """Whether a patch section moves docs/decisions.md from or to a path."""
    for _, header, body in _sections(command):
        move = PATCH_MOVE.search(body)
        if move and any(
            _is_guarded(str(absolute_path(payload, raw)))
            for raw in (header, move.group(1))
        ):
            return True
    return False


def _read(path: Path) -> str:
    """The log's current text; empty when it cannot be read.

    Undecodable bytes are replaced rather than raised: a UnicodeDecodeError
    crashed the hook, and a crashed hook fails open. Markers are ASCII, so
    a replacement character never changes a count.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


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

    if tool == "apply_patch":
        command = command_text(ti)
        logs = _existing_logs(data)
        if logs and _moves_guarded_file(data, command):
            deny(
                "Refused: this patch moves docs/decisions.md. Moving the "
                "guarded file implicitly removes or replaces all of its ADR "
                "status markers, which is an author-only decision. Make the "
                "non-status edits without moving the file."
            )
        for path in logs:
            before = _read(path)
            after = _codex_after(data, command, path, before)
            if after is None:
                deny(
                    "Refused: this patch targets docs/decisions.md but the "
                    "ADR status guard cannot safely simulate its patch "
                    "structure. Use a standard apply_patch Add/Delete/Update "
                    "section whose context lines match the file exactly, so "
                    "the status-marker transitions can be vetted."
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
    before = _read(edited[0])

    if tool == "Write":
        after = str(ti.get("content", "") or "")
    else:
        old_string = str(ti.get("old_string", "") or "")
        new_string = str(ti.get("new_string", "") or "")
        if old_string not in before:
            before, old_string, new_string = (
                t.translate(_QUOTES) for t in (before, old_string, new_string)
            )
        if not old_string:
            # Measured: the Edit fills a blank file, and fails on any other.
            after = before if before.strip() else new_string
        elif old_string in before:
            count = -1 if ti.get("replace_all") else 1
            after = before.replace(old_string, new_string, count)
        else:
            deny(
                "Refused: old_string does not occur in docs/decisions.md, "
                "so the ADR status guard cannot tell what this edit would "
                "change. Re-read the file and copy old_string exactly."
            )

    _vet(before, after)
    sys.exit(0)


if __name__ == "__main__":
    main()
