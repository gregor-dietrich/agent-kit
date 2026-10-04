"""Behavioral pin for the decisions-log status guard hook (``hooks/``).

Runs the real hook — the bash prefilter wrapper plus the Python guard — as a
subprocess with crafted tool JSON, covering the routes a review found around
an earlier fragment-counting version: partial-marker Edits,
compound edits whose global marker counts net to zero, secondary-checkout /
worktree paths, and write-shaped Bash commands.

These tests are load-bearing: a crashed PreToolUse hook fails OPEN in the
harness (only exit 2 or an emitted deny payload blocks), so a broken guard
denies nothing and nothing else would notice.
"""

import json
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
# hooks.json registers the bash prefilter for the Bash tool and the Python
# guard itself for Write|Edit|apply_patch; each payload runs through the
# one its tool reaches.
_HOOK = _ROOT / "hooks" / "decisions-status-guard.sh"
_GUARD = _ROOT / "hooks" / "decisions_status_guard.py"

_DOC = (
    "## ADR-0001 — a draft\n\n"
    "**Date:** d · **Status:** Proposed\n\n"
    "**Decision:** draft one.\n\n"
    "## ADR-0002 — settled\n\n"
    "**Date:** d · **Status:** Accepted\n\n"
    "**Decision:** settled one.\n"
)


def _run(payload: dict[str, object], cwd: Path | None = None) -> str:
    bash = payload.get("tool_name") == "Bash"
    result = subprocess.run(
        ["bash", str(_HOOK)] if bash else [str(_GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        cwd=None if cwd is None else str(cwd),
    )
    return result.stdout


def _denied(payload: dict[str, object], cwd: Path | None = None) -> bool:
    return '"permissionDecision": "deny"' in _run(payload, cwd)


def _decisions_file(tmp_path: Path, text: str = _DOC) -> Path:
    doc = tmp_path / "docs" / "decisions.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(text, encoding="utf-8")
    return doc


@pytest.fixture(autouse=True)
def _in_a_checkout_with_a_log(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run every hook from a checkout that keeps a decisions log.

    A payload without ``cwd`` resolves against the hook process's own cwd,
    and the Bash arm is a no-op in a checkout without a log — so the tests
    that pin it need one to stand in.
    """
    root = tmp_path_factory.mktemp("checkout")
    (root / ".git").mkdir()
    _decisions_file(root)
    monkeypatch.chdir(root)


def _edit(path: Path, old: str, new: str) -> dict[str, object]:
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(path),
            "old_string": old,
            "new_string": new,
        },
    }


def _bash(command: str) -> dict[str, object]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _patch_header(
    cwd: Path, header: str, body: str, more: str = ""
) -> dict[str, object]:
    """An apply_patch payload whose Update File header is given verbatim.

    *more* is appended as further file sections before the end marker.
    """
    return {
        "cwd": str(cwd),
        "tool_name": "apply_patch",
        "tool_input": {
            "command": "*** Begin Patch\n"
            f"*** Update File: {header}\n"
            f"{body}{more}"
            "*** End Patch"
        },
    }


def _patch(root: Path, body: str, more: str = "") -> dict[str, object]:
    return _patch_header(root, "docs/decisions.md", body, more)


_FLIP_HUNK = (
    "@@\n"
    "-**Date:** d · **Status:** Proposed\n"
    "+**Date:** d · **Status:** Accepted\n"
)
_PROSE_HUNK = (
    "@@\n"
    "-**Decision:** settled one.\n"
    "+**Decision:** settled one (amended d2).\n"
)


# --- Edit: the three blocked transitions ------------------------------------


def test_flip_to_accepted_is_denied(tmp_path: Path) -> None:
    doc = _decisions_file(tmp_path)
    payload = _edit(doc, "**Status:** Proposed", "**Status:** Accepted")
    assert _denied(payload)


def test_writing_a_new_entry_as_accepted_is_denied(tmp_path: Path) -> None:
    doc = _decisions_file(tmp_path)
    payload = _edit(
        doc,
        "**Decision:** settled one.\n",
        "**Decision:** settled one.\n\n"
        "## ADR-0003 — new\n\n**Status:** Accepted\n\n**Decision:** mine.\n",
    )
    assert _denied(payload)


def test_deleting_a_draft_is_denied(tmp_path: Path) -> None:
    doc = _decisions_file(tmp_path)
    payload = _edit(
        doc,
        "## ADR-0001 — a draft\n\n"
        "**Date:** d · **Status:** Proposed\n\n"
        "**Decision:** draft one.\n\n",
        "",
    )
    assert _denied(payload)


def test_deratification_is_denied(tmp_path: Path) -> None:
    doc = _decisions_file(tmp_path)
    payload = _edit(doc, "**Status:** Accepted", "**Status:** Proposed")
    assert _denied(payload)


# --- Edit: the bypass routes the review reproduced --------------------------


def test_partial_fragment_flip_is_denied(tmp_path: Path) -> None:
    # The fragments exclude the marker prefix — fragment counting saw 0/0.
    doc = _decisions_file(tmp_path)
    payload = _edit(doc, "Status:** Proposed", "Status:** Accepted")
    assert _denied(payload)


def test_net_zero_compound_edit_is_denied(tmp_path: Path) -> None:
    # One edit demotes ADR-0002 while drafting a new Accepted ADR-0003:
    # global counts net to zero; per-entry comparison still catches both.
    doc = _decisions_file(tmp_path)
    payload = _edit(
        doc,
        "## ADR-0002 — settled\n\n**Date:** d · **Status:** Accepted\n",
        "## ADR-0002 — settled\n\n**Date:** d · **Status:** Proposed\n\n"
        "## ADR-0003 — new\n\n**Date:** d · **Status:** Accepted\n",
    )
    assert _denied(payload)


def test_secondary_checkout_paths_are_guarded(tmp_path: Path) -> None:
    # The guard matches any */docs/decisions.md, not one anchored checkout —
    # tmp_path stands in for a worktree the project dir does not point at.
    doc = _decisions_file(tmp_path)
    assert _denied(_edit(doc, "**Status:** Proposed", "**Status:** Accepted"))


# --- Edit/Write: legitimate acts pass ---------------------------------------


def test_drafting_a_proposed_entry_is_allowed(tmp_path: Path) -> None:
    doc = _decisions_file(tmp_path)
    payload = _edit(
        doc,
        "**Decision:** settled one.\n",
        "**Decision:** settled one.\n\n"
        "## ADR-0003 — new\n\n**Status:** Proposed\n\n**Decision:** mine.\n",
    )
    assert not _denied(payload)


def test_prose_amendment_is_allowed(tmp_path: Path) -> None:
    doc = _decisions_file(tmp_path)
    payload = _edit(doc, "settled one.", "settled one (amended d2).")
    assert not _denied(payload)


def test_write_preserving_markers_is_allowed(tmp_path: Path) -> None:
    doc = _decisions_file(tmp_path)
    payload: dict[str, object] = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(doc),
            "content": _DOC + "\namended prose.\n",
        },
    }
    assert not _denied(payload)


def test_write_dropping_an_accepted_marker_is_denied(tmp_path: Path) -> None:
    doc = _decisions_file(tmp_path)
    payload: dict[str, object] = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(doc),
            "content": _DOC.replace("**Status:** Accepted", ""),
        },
    }
    assert _denied(payload)


def test_edit_whose_old_string_cannot_be_located_is_denied(
    tmp_path: Path,
) -> None:
    # Passing it on the premise that "the Edit itself will fail" was wrong:
    # Claude's Edit matches through quote and line-ending differences (see
    # below), so an unlocated old_string is denied, not assumed harmless.
    doc = _decisions_file(tmp_path)
    assert _denied(_edit(doc, "no such text", "**Status:** Accepted"))


# Measured against Claude Code's Edit tool: curly quotes in old_string match
# straight ones in the file, an LF old_string matches a CRLF file, and an
# empty old_string fills a blank file (and fails on any other).


def test_flip_through_curly_quote_matching_is_denied(tmp_path: Path) -> None:
    doc = _decisions_file(tmp_path, _DOC.replace("draft one", '"draft" one'))
    old = "**Status:** Proposed\n\n**Decision:** \u201cdraft\u201d one."
    assert _denied(_edit(doc, old, old.replace("Proposed", "Accepted")))


def test_flip_through_line_ending_matching_is_denied(tmp_path: Path) -> None:
    doc = tmp_path / "docs" / "decisions.md"
    doc.parent.mkdir(parents=True)
    doc.write_bytes(_DOC.replace("\n", "\r\n").encode())
    old = "**Status:** Proposed\n\n**Decision:** draft one."
    assert _denied(_edit(doc, old, old.replace("Proposed", "Accepted")))


def test_prose_edit_through_line_ending_matching_is_allowed(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "docs" / "decisions.md"
    doc.parent.mkdir(parents=True)
    doc.write_bytes(_DOC.replace("\n", "\r\n").encode())
    old = "**Decision:** draft one.\n\n## ADR-0002"
    assert not _denied(_edit(doc, old, old.replace("one", "two")))


@pytest.mark.parametrize("blank", ["", "  \n"])
def test_filling_a_blank_log_with_an_accepted_entry_is_denied(
    tmp_path: Path, blank: str
) -> None:
    doc = _decisions_file(tmp_path, blank)
    new = "## ADR-0001 — x\n\n**Status:** Accepted\n"
    assert _denied(_edit(doc, "", new))
    assert not _denied(_edit(doc, "", new.replace("Accepted", "Proposed")))


def test_empty_old_string_on_a_written_log_is_allowed(tmp_path: Path) -> None:
    # Claude's Edit refuses it ("file already exists"); nothing changes.
    doc = _decisions_file(tmp_path)
    assert not _denied(_edit(doc, "", "**Status:** Accepted\n"))


def test_undecodable_log_still_vets_a_flip(tmp_path: Path) -> None:
    # A UnicodeDecodeError crashed the hook, and a crashed hook fails open.
    doc = tmp_path / "docs" / "decisions.md"
    doc.parent.mkdir(parents=True)
    doc.write_bytes(_DOC.encode().replace(b"draft one", b"Caf\xe9"))
    assert _denied(_edit(doc, "**Status:** Proposed", "**Status:** Accepted"))
    assert _denied(_patch(tmp_path, _FLIP_HUNK))


@pytest.mark.parametrize("name", ["Decisions.md", "DECISIONS.md"])
def test_a_differently_cased_log_name_is_guarded(
    tmp_path: Path, name: str
) -> None:
    # On a case-insensitive filesystem (macOS, Windows) this IS the log.
    doc = tmp_path / "docs" / name
    doc.parent.mkdir(parents=True)
    doc.write_text(_DOC, encoding="utf-8")
    assert _denied(_edit(doc, "**Status:** Proposed", "**Status:** Accepted"))
    assert _denied(_bash(f"sed -i s/Proposed/Accepted/ docs/{name}"))


def test_other_files_are_not_guarded(tmp_path: Path) -> None:
    other = tmp_path / "notes-on-decisions.md"
    other.write_text("**Status:** Proposed\n", encoding="utf-8")
    payload = _edit(other, "**Status:** Proposed", "**Status:** Accepted")
    assert not _denied(payload)


# --- Codex apply_patch: the same transitions and safe edits ----------------


def test_codex_flip_to_accepted_is_denied(tmp_path: Path) -> None:
    _decisions_file(tmp_path)
    payload = _patch(
        tmp_path,
        "@@\n"
        "-**Date:** d · **Status:** Proposed\n"
        "+**Date:** d · **Status:** Accepted\n",
    )
    assert _denied(payload)


def test_codex_accepted_addition_is_denied(tmp_path: Path) -> None:
    _decisions_file(tmp_path)
    payload = _patch(
        tmp_path,
        "@@\n"
        " **Decision:** settled one.\n"
        "+\n"
        "+## ADR-0003 — new\n"
        "+\n"
        "+**Status:** Accepted\n"
        "+\n"
        "+**Decision:** mine.\n",
    )
    assert _denied(payload)


def test_codex_proposed_removal_is_denied(tmp_path: Path) -> None:
    _decisions_file(tmp_path)
    payload = _patch(
        tmp_path,
        "@@\n-**Date:** d · **Status:** Proposed\n",
    )
    assert _denied(payload)


def test_codex_accepted_removal_is_denied(tmp_path: Path) -> None:
    _decisions_file(tmp_path)
    payload = _patch(
        tmp_path,
        "@@\n-**Date:** d · **Status:** Accepted\n",
    )
    assert _denied(payload)


def test_codex_proposed_draft_is_allowed(tmp_path: Path) -> None:
    _decisions_file(tmp_path)
    payload = _patch(
        tmp_path,
        "@@\n"
        " **Decision:** settled one.\n"
        "+\n"
        "+## ADR-0003 — new\n"
        "+\n"
        "+**Status:** Proposed\n"
        "+\n"
        "+**Decision:** mine.\n",
    )
    assert not _denied(payload)


def test_codex_prose_amendment_is_allowed(tmp_path: Path) -> None:
    _decisions_file(tmp_path)
    payload = _patch(
        tmp_path,
        "@@\n"
        "-**Decision:** settled one.\n"
        "+**Decision:** settled one (amended d2).\n",
    )
    assert not _denied(payload)


def test_codex_move_of_decisions_file_is_denied(tmp_path: Path) -> None:
    _decisions_file(tmp_path)
    payload: dict[str, object] = {
        "cwd": str(tmp_path),
        "tool_name": "apply_patch",
        "tool_input": {
            "command": "*** Begin Patch\n"
            "*** Update File: docs/decisions.md\n"
            "*** Move to: docs/decisions-archive.md\n"
            "*** End Patch"
        },
    }
    assert _denied(payload)


def test_unparseable_codex_decisions_patch_is_denied(tmp_path: Path) -> None:
    _decisions_file(tmp_path)
    payload = _patch(tmp_path, "not a valid hunk\n")
    assert _denied(payload)



# --- Codex apply_patch: simulated as Codex applies it ----------------------
# Each semantic below was measured against Codex's own apply_patch: a first
# hunk may omit its `@@` line, `@@ <line>` seeks forward to that line, hunks
# only ever move forward, and a hunk without old lines appends at the end.

_THREE = (
    "## ADR-0001 — one\n\n**Status:** Proposed\n\n"
    "## ADR-0002 — two\n\n**Status:** Proposed\n\n"
    "## ADR-0003 — three\n\n**Status:** Accepted\n"
)


def test_codex_flip_with_a_decoy_log_added_is_denied(tmp_path: Path) -> None:
    # The Add section creates a different file; it must not stand in for the
    # simulated result of the real log.
    _decisions_file(tmp_path)
    decoy = "".join(f"+{line}\n" for line in _DOC.splitlines())
    more = f"*** Add File: scratch/docs/decisions.md\n{decoy}"
    assert _denied(_patch(tmp_path, _FLIP_HUNK, more))


def test_codex_prose_edits_to_two_logs_are_allowed(tmp_path: Path) -> None:
    # Each log is simulated against its own text, not the first one's.
    _decisions_file(tmp_path)
    other = tmp_path / "wt" / "docs" / "decisions.md"
    other.parent.mkdir(parents=True)
    other.write_text("## ADR-0001 — x\n\n**Status:** Accepted\nprose\n")
    more = "*** Update File: wt/docs/decisions.md\n@@\n-prose\n+amended\n"
    assert not _denied(_patch(tmp_path, _PROSE_HUNK, more))


def test_codex_first_hunk_without_an_at_line_is_vetted(tmp_path: Path) -> None:
    _decisions_file(tmp_path)
    body = _FLIP_HUNK.removeprefix("@@\n") + _PROSE_HUNK
    assert _denied(_patch(tmp_path, body))


def test_codex_anchored_hunks_are_vetted_where_they_land(
    tmp_path: Path,
) -> None:
    # Applied first-match-anywhere, both hunks hit ADR-0001 and cancel out;
    # Codex ratifies ADR-0002 and de-ratifies ADR-0003.
    _decisions_file(tmp_path, _THREE)
    body = (
        "@@ ## ADR-0002 — two\n"
        " \n"
        "-**Status:** Proposed\n"
        "+**Status:** Accepted\n"
        "@@ ## ADR-0003 — three\n"
        " \n"
        "-**Status:** Accepted\n"
        "+**Status:** Proposed\n"
    )
    assert _denied(_patch(tmp_path, body))


def test_codex_hunks_out_of_file_order_are_denied(tmp_path: Path) -> None:
    # Codex fails such a patch; the guard cannot vet what will not apply.
    _decisions_file(tmp_path)
    body = (
        "@@\n-**Decision:** settled one.\n+**Decision:** amended.\n"
        "@@\n-**Decision:** draft one.\n+**Decision:** amended.\n"
    )
    assert _denied(_patch(tmp_path, body))


def test_codex_appended_draft_is_allowed(tmp_path: Path) -> None:
    _decisions_file(tmp_path)
    body = "@@\n+\n+## ADR-0003 — new\n+\n+**Status:** Proposed\n"
    assert not _denied(_patch(tmp_path, body))


def test_codex_appended_accepted_entry_is_denied(tmp_path: Path) -> None:
    _decisions_file(tmp_path)
    body = (
        "@@ ## ADR-0001 — a draft\n"
        "+## ADR-0003 — new\n"
        "+**Status:** Accepted\n"
    )
    assert _denied(_patch(tmp_path, body))


# --- Bash: write-shaped commands are denied, reads pass ---------------------


def test_bash_in_place_edit_is_denied() -> None:
    cmd = "sed -i s/Proposed/Accepted/ docs/decisions.md"
    assert _denied(_bash(cmd))


def test_bash_redirect_is_denied() -> None:
    assert _denied(_bash("echo x >> docs/decisions.md"))


def test_bash_read_is_allowed() -> None:
    assert not _denied(_bash("grep -n Status docs/decisions.md"))


def test_bash_git_add_is_allowed() -> None:
    assert not _denied(_bash("git add docs/decisions.md && git commit"))


def test_bash_commit_with_email_trailer_is_allowed() -> None:
    # The trailer's <user@host> is not a redirect; without the email-span
    # strip, every standard commit naming the file would be denied.
    cmd = (
        "git add docs/decisions.md && git commit -m 'docs: amend\n\n"
        "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>'"
    )
    assert not _denied(_bash(cmd))


@pytest.mark.parametrize(
    "argv", [["bash", str(_HOOK)], [str(_GUARD)]], ids=["bash-arm", "edit-arm"]
)
def test_malformed_payload_fails_open(argv: list[str]) -> None:
    result = subprocess.run(
        argv,
        input="decisions.md but not json",
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0
    assert '"deny"' not in result.stdout


# --- patch headers: whitespace, CR, and a nested cwd ------------------------


@pytest.mark.parametrize("suffix", ["\r", " ", "\t"])
def test_patch_header_with_trailing_whitespace_is_still_guarded(
    tmp_path: Path, suffix: str
) -> None:
    # `re.MULTILINE`'s `$` matches before a `\n` and `.` matches `\r`, so a
    # CRLF patch — or one stray space — used to capture a path no
    # guarded-file test matches, and the flip below was allowed outright.
    _decisions_file(tmp_path)
    payload = _patch_header(tmp_path, f"docs/decisions.md{suffix}", _FLIP_HUNK)
    assert _denied(payload)


def test_prose_patch_from_a_nested_cwd_is_allowed(tmp_path: Path) -> None:
    # A session rooted in docs/ writes the header as a bare `decisions.md`.
    # Judged against the raw header, the guard found no guarded section and
    # denied the patch as unsimulatable — every prose edit included.
    doc = _decisions_file(tmp_path)
    payload = _patch_header(doc.parent, "decisions.md", _PROSE_HUNK)
    assert not _denied(payload)


def test_flip_from_a_nested_cwd_is_denied(tmp_path: Path) -> None:
    # The pair to the test above: the bare header is resolved, not ignored.
    doc = _decisions_file(tmp_path)
    payload = _patch_header(doc.parent, "decisions.md", _FLIP_HUNK)
    assert _denied(payload)


# --- Edit: a relative file_path is resolved against the payload cwd ---------


def test_relative_edit_path_is_read_from_the_payload_cwd(
    tmp_path: Path,
) -> None:
    # The hook runs from a directory holding no docs/decisions.md, so
    # opening the raw relative path found nothing, left `before` empty and
    # waved the flip through.
    _decisions_file(tmp_path)
    payload: dict[str, object] = {
        "cwd": str(tmp_path),
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "docs/decisions.md",
            "old_string": "**Status:** Proposed",
            "new_string": "**Status:** Accepted",
        },
    }
    assert _denied(payload, cwd=tmp_path.parent)


# --- apply_patch: blank context lines are context, not a parse failure ------


def test_hunk_with_a_blank_context_line_is_allowed(tmp_path: Path) -> None:
    # apply_patch spells a blank context line as the empty string. Dropping
    # every empty line to shed the `@@` split artefact took this one with
    # it, so the simulation could not match its own context and the guard
    # denied a prose-only edit.
    _decisions_file(tmp_path)
    payload = _patch(
        tmp_path,
        "@@\n"
        "-**Decision:** draft one.\n"
        "+**Decision:** draft one (amended).\n"
        "\n"
        " ## ADR-0002 — settled\n",
    )
    assert not _denied(payload)


def test_flip_in_a_hunk_with_a_blank_context_line_is_denied(
    tmp_path: Path,
) -> None:
    # Keeping blank context lines must not cost the simulation its teeth.
    _decisions_file(tmp_path)
    payload = _patch(
        tmp_path,
        "@@\n"
        "-**Date:** d · **Status:** Proposed\n"
        "+**Date:** d · **Status:** Accepted\n"
        "\n"
        " **Decision:** draft one.\n",
    )
    assert _denied(payload)


# --- Bash: apply_patch, wrapper shells, and argv-list commands -------------


def test_bash_apply_patch_heredoc_is_denied() -> None:
    # apply_patch is a first-class writer; run from a shell it bypassed the
    # apply_patch route the guard vets.
    cmd = (
        'apply_patch <<"PATCH"\n'
        "*** Begin Patch\n"
        "*** Update File: docs/decisions.md\n"
        "@@\n"
        "-**Status:** Proposed\n"
        "+**Status:** Accepted\n"
        "*** End Patch\n"
        "PATCH\n"
    )
    assert _denied(_bash(cmd))


@pytest.mark.parametrize(
    "cmd",
    [
        "bash -lc 'true docs/decisions.md'",
        "sh -lc 'true docs/decisions.md'",
        "zsh -ic 'true docs/decisions.md'",
        "bash -l -c 'true docs/decisions.md'",
        "python3 -uc 'print(1) docs/decisions.md'",
    ],
)
def test_combined_short_option_interpreters_are_denied(cmd: str) -> None:
    # `-lc` is the standard wrapper spelling an agent harness emits;
    # requiring `-c` to be its own contiguous token defeated this whole arm.
    assert _denied(_bash(cmd))


def test_unrelated_dash_c_is_allowed() -> None:
    # The interpreter arm stays anchored on the interpreter name: a `-c`
    # belonging to some other tool is not a write.
    assert not _denied(_bash("cat docs/decisions.md | grep -c Status"))


@pytest.mark.parametrize(
    "argv",
    [
        ["python3", "-c", "open('docs/decisions.md', 'w')"],
        ["sed", "-i", "s/Proposed/Accepted/", "docs/decisions.md"],
    ],
)
def test_argv_list_command_is_scanned(argv: list[str]) -> None:
    # Codex's shell tool sends an argv list. `str()` on it yields a Python
    # repr whose quoting and commas break every adjacency the write-token
    # patterns rely on, so the guard read these as harmless.
    payload: dict[str, object] = {
        "tool_name": "Bash",
        "tool_input": {"command": argv},
    }
    assert _denied(payload)


def test_argv_wrapper_script_is_scanned_not_the_wrapper() -> None:
    # `["bash", "-lc", <script>]` is harness plumbing: the script is the
    # command, and it is what gets scanned.
    payload: dict[str, object] = {
        "tool_name": "Bash",
        "tool_input": {
            "command": ["bash", "-lc", "tee docs/decisions.md"],
        },
    }
    assert _denied(payload)


def test_argv_wrapper_around_a_read_is_allowed() -> None:
    payload: dict[str, object] = {
        "tool_name": "Bash",
        "tool_input": {
            "command": ["bash", "-lc", "grep -n Status docs/decisions.md"],
        },
    }
    assert not _denied(payload)


# --- status values: caught however they are cased or spaced ----------------


@pytest.mark.parametrize(
    "marker",
    [
        "**Status:** accepted",
        "**Status:** ACCEPTED",
        "**Status:**Accepted",
        "**Status:**  Accepted",
        "__Status:__ Accepted",
    ],
)
def test_drafting_an_entry_accepted_in_any_spelling_is_denied(
    tmp_path: Path, marker: str
) -> None:
    # Byte-exact marker counting saw no Accepted marker in any of these, so
    # the entry was written straight to ratified — and renders as ratified.
    doc = _decisions_file(tmp_path)
    payload = _edit(
        doc,
        "**Decision:** settled one.\n",
        "**Decision:** settled one.\n\n"
        f"## ADR-0003 — new\n\n{marker}\n\n**Decision:** mine.\n",
    )
    assert _denied(payload)


def test_drafting_a_lowercase_proposed_entry_is_allowed(
    tmp_path: Path,
) -> None:
    # The tolerant match must not turn drafting into a denied act.
    doc = _decisions_file(tmp_path)
    payload = _edit(
        doc,
        "**Decision:** settled one.\n",
        "**Decision:** settled one.\n\n"
        "## ADR-0003 — new\n\n**Status:** proposed\n\n**Decision:** mine.\n",
    )
    assert not _denied(payload)


def test_lowercase_deratification_is_denied(tmp_path: Path) -> None:
    # Rewriting `Accepted` as some other word is still de-ratification, and
    # a case-insensitive match is what notices the reverse move too.
    doc = _decisions_file(tmp_path)
    payload = _edit(doc, "**Status:** Accepted", "**Status:** Retired")
    assert _denied(payload)



# --- status values: counted as they render ---------------------------------
# A comment keeps a Proposed marker in the source while the page shows only
# the new value, so each value below must count as the Accepted it renders
# as — and the commented-out Proposed must not count at all.


@pytest.mark.parametrize(
    "value",
    [
        "`Accepted`",
        "_**Accepted**_",
        "[Accepted](#)",
        "<span>Accepted</span>",
        "Acc\u200bepted",
        "&#65;ccepted",
        "\uff21ccepted",
        "Ac*cep*ted",
    ],
)
def test_a_flip_hidden_behind_markup_is_denied(
    tmp_path: Path, value: str
) -> None:
    doc = _decisions_file(tmp_path)
    new = f"**Status:** {value} <!-- **Status:** Proposed -->"
    assert _denied(_edit(doc, "**Status:** Proposed", new))


def test_an_unclosed_comment_hides_what_follows(tmp_path: Path) -> None:
    doc = _decisions_file(tmp_path)
    new = "**Status:** Accepted <!-- **Status:** Proposed"
    assert _denied(_edit(doc, "**Status:** Proposed", new))


@pytest.mark.parametrize("value", ["Proposed", "Accepted"])
def test_a_lone_comment_opener_hiding_a_marker_is_denied(
    tmp_path: Path, value: str
) -> None:
    # On a line of its own an unclosed `<!--` opens an HTML block that runs
    # to the end of the page: every marker after it vanishes for a reader
    # while the source, and so the raw view, still holds it.
    doc = _decisions_file(tmp_path)
    line = f"**Date:** d · **Status:** {value}"
    assert _denied(_edit(doc, line, f"<!--\n{line}"))


def test_a_bare_angle_bracket_does_not_hide_a_marker(tmp_path: Path) -> None:
    # `3 < 5` is text, not a tag: stripping `<…>` across it erased the
    # Accepted marker the reader still sees.
    doc = _decisions_file(tmp_path)
    new = (
        "**Decision:** settled one.\n\n## ADR-0003 — new\n\n"
        "Note: 3 < 5\n\n**Status:** Accepted\n\nso 5 > 3\n"
    )
    assert _denied(_edit(doc, "**Decision:** settled one.\n", new))


def test_a_comment_opener_in_a_code_span_hides_nothing(
    tmp_path: Path,
) -> None:
    # Rendered, `<!--` in a code span is literal text and the page goes on;
    # read as an unclosed comment it silenced every rule after it.
    doc = _decisions_file(
        tmp_path, _DOC.replace("draft one.", "draft one. `<!--`")
    )
    new = "**Decision:** settled one.\n\n## ADR-0003\n\n**Status:** Accepted\n"
    assert _denied(_edit(doc, "**Decision:** settled one.\n", new))
    assert _denied(_edit(doc, "**Status:** Proposed", "**Status:** Accepted"))


def test_prose_edit_in_a_log_with_comments_is_allowed(tmp_path: Path) -> None:
    doc = _decisions_file(
        tmp_path, _DOC.replace("draft one.", "draft one. <!-- todo -->")
    )
    assert not _denied(_edit(doc, "<!-- todo -->", "<!-- done -->"))


# --- a no-op in a checkout without a decisions log -------------------------


def _bare_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "bare"
    (root / ".git").mkdir(parents=True)
    return root


def test_bash_write_without_a_log_is_allowed(tmp_path: Path) -> None:
    root = _bare_checkout(tmp_path)
    payload = _bash("echo x >> docs/decisions.md")
    payload["cwd"] = str(root)
    assert not _denied(payload, cwd=root)


def test_bash_write_from_a_subdirectory_of_a_logged_checkout_is_denied(
    tmp_path: Path,
) -> None:
    # The log is looked up at the checkout root, not at the cwd.
    _decisions_file(tmp_path)
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)
    payload = _bash("sed -i s/a/b/ ../../docs/decisions.md")
    payload["cwd"] = str(nested)
    assert _denied(payload, cwd=nested)


def test_creating_a_log_with_an_accepted_entry_is_allowed(
    tmp_path: Path,
) -> None:
    # Starting a decisions log is not a status transition on an existing
    # one; the guard takes over once the file exists.
    root = _bare_checkout(tmp_path)
    payload: dict[str, object] = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(root / "docs" / "decisions.md"),
            "content": _DOC,
        },
    }
    assert not _denied(payload, cwd=root)


def test_codex_patch_adding_a_log_is_allowed(tmp_path: Path) -> None:
    root = _bare_checkout(tmp_path)
    payload: dict[str, object] = {
        "cwd": str(root),
        "tool_name": "apply_patch",
        "tool_input": {
            "command": "*** Begin Patch\n"
            "*** Add File: docs/decisions.md\n"
            "+## ADR-0001 — x\n"
            "+**Status:** Accepted\n"
            "*** End Patch"
        },
    }
    assert not _denied(payload, cwd=root)


# --- routes around the no-op and the lexical path test ----------------------


def test_bash_write_by_absolute_path_from_a_bare_cwd_is_denied(
    tmp_path: Path,
) -> None:
    # The cwd's checkout keeps no log, but the command names one that
    # exists elsewhere: the no-op must not become the way around the guard.
    doc = _decisions_file(tmp_path / "logged")
    root = _bare_checkout(tmp_path)
    payload = _bash(f"sed -i s/Proposed/Accepted/ {doc}")
    payload["cwd"] = str(root)
    assert _denied(payload, cwd=root)


@pytest.mark.parametrize(
    "command",
    [
        "cd ../logged && sed -i s/Proposed/Accepted/ docs/decisions.md",
        "git -C ../logged checkout HEAD~1 -- docs/decisions.md",
    ],
)
def test_bash_write_after_changing_directory_is_denied(
    tmp_path: Path, command: str
) -> None:
    # Where the command ends up running cannot be resolved here, so its
    # target is assumed to be a log rather than ruled out.
    root = _bare_checkout(tmp_path)
    payload = _bash(command)
    payload["cwd"] = str(root)
    assert _denied(payload, cwd=root)


@pytest.mark.parametrize(
    "command",
    [
        "git checkout HEAD~3 -- docs/decisions.md",
        "git restore --source HEAD~3 docs/decisions.md",
        "patch docs/decisions.md < x.diff",
        "ln -sf other.md docs/decisions.md",
        "awk -i inplace '{print}' docs/decisions.md",
        "node -e \"require('fs').writeFileSync('docs/decisions.md', '')\"",
    ],
)
def test_other_writers_are_denied(command: str) -> None:
    # Reverting the file to an older revision de-ratifies as surely as an
    # edit; each of these rewrites it without passing through Edit/Write.
    assert _denied(_bash(command))



@pytest.mark.parametrize(
    "command",
    [
        "sed --in-place s/a/b/ docs/decisions.md",
        "sed --in-place=.bak s/a/b/ docs/decisions.md",
        "gawk -i inplace '{print}' docs/decisions.md",
        "vim -es -c '%s/a/b/' -c wq docs/decisions.md",
        "python3 - <<'EOF'\nopen('docs/decisions.md', 'w')\nEOF",
        "node <<'EOF'\n"
        "require('fs').writeFileSync('docs/decisions.md', '')\nEOF",
        "echo \"open('docs/decisions.md', 'w')\" | python3",
        "eval \"$(cat <<'EOF'\nsed -i s/a/b/ docs/decisions.md\nEOF\n)\"",
    ],
)
def test_writers_the_token_list_missed_are_denied(command: str) -> None:
    assert _denied(_bash(command))


@pytest.mark.parametrize(
    "command",
    [
        "grep -n Status docs/decisions.md 2>/dev/null",
        "grep -q Status docs/decisions.md >/dev/null 2>&1",
        "git add docs/decisions.md && git commit -F - <<'EOF'\n"
        "Proposed -> reviewed in docs/decisions.md\nEOF",
        "python3 tools/lint.py < docs/decisions.md",
        "git commit -m \"$(cat <<'EOF'\n"
        "Proposed -> reviewed in docs/decisions.md\nEOF\n)\"",
        "git tag -a v1 --file=- <<'EOF'\n"
        "Proposed -> reviewed in docs/decisions.md\nEOF",
    ],
)
def test_reads_with_benign_redirects_or_prose_are_allowed(
    command: str,
) -> None:
    assert not _denied(_bash(command))


_SED = "sed -i s/a/b/ docs/decisions.md"


@pytest.mark.parametrize(
    "command",
    [
        # A quoted or commented `<<` opens no heredoc: the next line runs.
        f'echo "<<X"\n{_SED}',
        f"# <<X\n{_SED}",
        # No terminator line: what the body is cannot be told.
        f"cat <<X\n{_SED}",
        # Readers that run a script read from stdin.
        "awk -f - /dev/null <<'EOF'\n"
        'BEGIN{print "x" > "docs/decisions.md"}\nEOF',
        "sed -n -f - x <<EOF\nw docs/decisions.md\nEOF",
        "printf 'w docs/decisions.md' | sed -n -f /dev/stdin x",
        # A substitution's output run as a command, at once or later.
        f"$(cat <<'EOF'\n{_SED}\nEOF\n)",
        f"sudo $(cat <<'EOF'\n{_SED}\nEOF\n)",
        f"M=\"$(cat <<'EOF'\n{_SED}\nEOF\n)\"; $M",
        f"M=\"$(cat <<'EOF'\n{_SED}\nEOF\n)\"; if true; then $M; fi",
        # Commands that run their argument: only git's message is prose.
        f"watch \"$(cat <<'EOF'\n{_SED}\nEOF\n)\"",
        f"su -c \"$(cat <<'EOF'\n{_SED}\nEOF\n)\"",
    ],
)
def test_heredoc_bodies_a_shell_may_run_are_scanned(command: str) -> None:
    assert _denied(_bash(command))


@pytest.mark.parametrize(
    "command",
    ["echo x >&1/docs/decisions.md", "echo x >/dev/null.md docs/decisions.md"],
)
def test_a_redirect_that_only_starts_benign_is_denied(command: str) -> None:
    # `>&1/…` opens a file, not a descriptor; `/dev/null.md` is not
    # /dev/null. Only the whole shell word makes a redirect benign.
    assert _denied(_bash(command))


def test_a_log_path_after_a_quoted_heredoc_opener_is_reached(
    tmp_path: Path,
) -> None:
    # Reading `<<X` in quotes as a heredoc hid the line naming the log.
    doc = _decisions_file(tmp_path / "my repo")
    payload = _bash(f'echo "<<X"\nsed -i s/a/b/ "{doc}"')
    payload["cwd"] = str(_bare_checkout(tmp_path))
    assert _denied(payload, cwd=tmp_path)


@pytest.mark.parametrize("quote", ['"{}"', "{}"])
def test_bash_write_to_a_log_path_with_a_space_is_denied(
    tmp_path: Path, quote: str
) -> None:
    root = tmp_path / "my repo"
    doc = _decisions_file(root)
    escaped = str(doc).replace(" ", "\\ ")
    spelled = str(doc) if quote.startswith('"') else escaped
    payload = _bash(f"sed -i s/a/b/ {quote.format(spelled)}")
    payload["cwd"] = str(_bare_checkout(tmp_path))
    assert _denied(payload, cwd=tmp_path)


def test_git_reads_of_the_log_are_allowed() -> None:
    assert not _denied(_bash("git log -p docs/decisions.md"))
    assert not _denied(_bash("git diff HEAD~1 -- docs/decisions.md"))


def test_an_edit_through_a_symlink_is_vetted(tmp_path: Path) -> None:
    # The lexical suffix test sees `notes.md`; the file that changes is the
    # log, so the resolved path is tested too.
    doc = _decisions_file(tmp_path)
    link = tmp_path / "notes.md"
    link.symlink_to(doc)
    payload = _edit(link, "**Status:** Proposed", "**Status:** Accepted")
    assert _denied(payload)


def test_bash_write_through_an_env_var_path_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `"$HOME/…/docs/decisions.md"` names a log only once the variable is
    # expanded; unexpanded, it resolved to nothing and passed as a no-op.
    _decisions_file(tmp_path / "logged")
    monkeypatch.setenv("LOGGED_ROOT", str(tmp_path / "logged"))
    root = _bare_checkout(tmp_path)
    payload = _bash('sed -i s/a/b/ "$LOGGED_ROOT/docs/decisions.md"')
    payload["cwd"] = str(root)
    assert _denied(payload, cwd=root)
