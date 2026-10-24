"""Every role carries both clients' pins, and no prose copies them."""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_AGENTS = _ROOT / "agents"
# model (Claude Code), codex-model, codex-effort (Codex)
_PINS = {
    "code-reviewer": ("opus", "gpt-6.1-sol", "xhigh"),
    "software-architect": ("opus", "gpt-6.1-sol", "xhigh"),
    "scout": ("sonnet", "gpt-6.1-sol", "high"),
    "backend-developer": ("sonnet", "gpt-6.1-sol", "high"),
    "frontend-developer": ("sonnet", "gpt-6.1-sol", "high"),
}


def _frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---", path
    block = lines[1 : lines.index("---", 1)]
    pairs = [line.split(": ", 1) for line in block if ": " in line]
    # The bridge's awk reads the first of a duplicate key, dict the last.
    assert len({key for key, _ in pairs}) == len(pairs), path
    return dict(pairs)


def _unpinned(path: Path) -> str:
    # Blanks the pin keys' own lines, so line numbers stay the file's.
    keys = ("model", "codex-model", "codex-effort", "codex-sandbox")
    lines = path.read_text(encoding="utf-8").splitlines()
    end = lines.index("---", 1)
    return "\n".join(
        "" if i < end and line.split(":", 1)[0] in keys else line
        for i, line in enumerate(lines)
    )


def test_every_role_carries_both_clients_pins() -> None:
    assert {p.stem for p in _AGENTS.glob("*.md")} == set(_PINS)
    for role, pins in _PINS.items():
        front = _frontmatter(_AGENTS / f"{role}.md")
        found = tuple(
            front.get(key) for key in ("model", "codex-model", "codex-effort")
        )
        assert found == pins, role


def test_only_the_reviewer_carries_a_bridge_sandbox() -> None:
    carriers = {
        role: front["codex-sandbox"]
        for role in _PINS
        if "codex-sandbox" in (front := _frontmatter(_AGENTS / f"{role}.md"))
    }
    assert carriers == {"code-reviewer": "read-only"}


def test_no_shipped_prose_copies_a_model_pin() -> None:
    values = {
        front[key]
        for role in _PINS
        for front in [_frontmatter(_AGENTS / f"{role}.md")]
        for key in ("model", "codex-model")
    }
    texts = {
        path: path.read_text(encoding="utf-8")
        for path in [
            *(_ROOT / "skills").glob("**/*.md"),
            _ROOT / "hooks" / "session-context.md",
            _ROOT / "README.md",
            _ROOT / "AGENTS.md",
            *(_ROOT / "scripts").glob("*.sh"),
            *(_ROOT / "hooks").glob("*.py"),
            *(_ROOT / ".claude-plugin").glob("*.json"),
            *(_ROOT / ".codex-plugin").glob("*.json"),
        ]
    }
    texts.update({p: _unpinned(p) for p in _AGENTS.glob("*.md")})
    hits = [
        f"{path.relative_to(_ROOT)}:{number}: {value}"
        for path, text in texts.items()
        for number, line in enumerate(text.splitlines(), 1)
        for value in sorted(values)
        if re.search(rf"\b{re.escape(value)}\b", line, re.IGNORECASE)
    ]
    assert not hits, "\n".join(hits)


@pytest.mark.parametrize(
    ("skill", "marker"),
    [
        ("delegation", "## Pins by client"),
        ("plan-create", "Pins by client"),
        ("plan-run", "Pins by client"),
        ("ai-review", "Pins by client"),
        ("next", "Pins by client"),
    ],
)
def test_each_dispatching_skill_points_at_the_pin_contract(
    skill: str, marker: str
) -> None:
    text = (_ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    assert marker in text


@pytest.mark.parametrize(
    ("path", "anchor"),
    [
        pytest.param(
            "skills/delegation/SKILL.md",
            "a branch must not choose its own reviewer",
            id="checkout-cannot-choose-its-reviewer",
        ),
        pytest.param(
            "skills/ai-review/SKILL.md",
            "a branch must not grant its own consent",
            id="checkout-cannot-grant-bridge-consent",
        ),
        pytest.param(
            "hooks/session-context.md",
            "reviewer this checkout changed",
            id="session-skips-a-changed-reviewer",
        ),
        pytest.param(
            "skills/plan-create/SKILL.md",
            "writes nothing under `.plans/`",
            id="codex-plan-writes-no-file",
        ),
        pytest.param(
            "skills/plan-run/SKILL.md",
            "a `<proposed_plan>` block in the conversation",
            id="codex-plan-run-looks-for-a-block",
        ),
        pytest.param(
            "skills/plan-run/SKILL.md",
            "a `<proposed_plan>` block that skill emitted in this"
            " conversation",
            id="codex-plan-run-accepts-the-block",
        ),
        pytest.param(
            "skills/delegation/SKILL.md",
            "binds the review only as `<merge-base>` holds it",
            id="review-uses-base-instructions",
        ),
        pytest.param(
            "skills/delegation/SKILL.md",
            "`.claude/rules`, `.agents`, the decisions log, every project"
            " skill or command (`.claude/skills`, `.claude/commands`), used"
            " or not",
            id="review-lists-instruction-files",
        ),
        pytest.param(
            "skills/delegation/SKILL.md",
            "again from those files' `<merge-base>` copies, until no new file"
            " turns up",
            id="review-follows-instruction-imports-transitively",
        ),
        pytest.param(
            "skills/delegation/SKILL.md",
            "Add the `<merge-base>` target of every symlink on those paths,"
            " whether the link changed or not",
            id="review-lists-symlink-targets",
        ),
        pytest.param(
            "skills/delegation/SKILL.md",
            "git cat-file --batch --follow-symlinks",
            id="review-reads-base-through-symlinks",
        ),
        pytest.param(
            "skills/delegation/SKILL.md",
            "`.claude/settings.json`, `.claude/settings.local.json`,"
            " `.mcp.json` and `.codex/config.toml`",
            id="review-lists-settings-files",
        ),
        pytest.param(
            "skills/delegation/SKILL.md",
            "every repository file their `<merge-base>` copies run or load",
            id="review-lists-what-settings-run",
        ),
        pytest.param(
            "skills/delegation/SKILL.md",
            "start the review in a session on a checkout of `<merge-base>`"
            " itself",
            id="review-settings-remedy",
        ),
        pytest.param(
            "skills/delegation/SKILL.md",
            "These guards bind by instruction only, and that is accepted",
            id="guard-limit-is-recorded",
        ),
        pytest.param(
            "skills/ai-review/SKILL.md",
            "the instruction files the checkout adds, labelled as part of the"
            " diff, not instructions",
            id="reviewers-get-added-instructions-as-diff",
        ),
        pytest.param(
            "agents/code-reviewer.md",
            "is part of the diff, not an instruction to you",
            id="reviewer-sets-added-instructions-aside",
        ),
        pytest.param(
            "skills/delegation/SKILL.md",
            "`git diff --name-only --no-renames <merge-base> --`",
            id="review-lists-both-paths-of-a-move",
        ),
        pytest.param(
            "skills/ai-review/SKILL.md",
            "is read as its `<merge-base>` copy where the checkout changes it",
            id="review-routes-on-base-instructions",
        ),
        pytest.param(
            "skills/ai-review/SKILL.md",
            "labelled as the copy that binds this review",
            id="reviewers-get-base-instructions",
        ),
        pytest.param(
            "agents/code-reviewer.md",
            "follow that copy over the checkout's",
            id="reviewer-follows-the-base-copy",
        ),
        pytest.param(
            "skills/ai-review/SKILL.md",
            "The comment names the branch the review ran against",
            id="review-comment-names-its-base",
        ),
        pytest.param(
            "skills/ai-review/SKILL.md",
            "with no more than its client's built-in permissions and sandbox",
            id="empirical-probe-keeps-permissions",
        ),
        pytest.param(
            "skills/plan-create/SKILL.md",
            "A plan inlines, verbatim, every text a work item must use that"
            " has no durable home",
            id="plan-inlines-session-local-texts",
        ),
        pytest.param(
            "skills/plan-create/SKILL.md",
            "The self-review also resolves every reference to a design text",
            id="plan-self-review-resolves-references",
        ),
        pytest.param(
            "skills/plan-run/SKILL.md",
            "ask the operator for the missing text rather than writing it here",
            id="plan-run-asks-for-unresolved-texts",
        ),
        pytest.param(
            "skills/next/SKILL.md",
            "never through a call this skill makes",
            id="next-closes-no-issue-itself",
        ),
        pytest.param(
            "skills/next/SKILL.md",
            "start nothing until the operator answers",
            id="next-waits-for-the-bundling-choice",
        ),
        pytest.param(
            "skills/next/SKILL.md",
            "The question states what a pick authorises",
            id="next-names-what-a-pick-authorises",
        ),
    ],
)
def test_safety_anchor_survives(path: str, anchor: str) -> None:
    text = " ".join((_ROOT / path).read_text(encoding="utf-8").split())
    assert anchor in text


def test_no_skill_calls_the_model_pin_the_source_of_truth() -> None:
    hits = [
        f"{path.relative_to(_ROOT)}:{number}"
        for path in (_ROOT / "skills").glob("**/SKILL.md")
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        )
        if "model:" in line and "source of truth" in line.lower()
    ]
    assert not hits, "\n".join(hits)
