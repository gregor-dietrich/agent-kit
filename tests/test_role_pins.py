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
        (
            "skills/delegation/SKILL.md",
            "a branch must not choose its own reviewer",
        ),
        (
            "skills/ai-review/SKILL.md",
            "a branch must not grant its own consent",
        ),
        ("hooks/session-context.md", "reviewer this checkout changed"),
    ],
)
def test_the_checkout_cannot_choose_its_own_reviewer(
    path: str, anchor: str
) -> None:
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
