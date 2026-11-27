"""The plugin manifests describe one plugin across all three clients."""

import itertools
import json
import re
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_SEMVER_RE = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
)
_CHANGELOG_HEADING_RE = re.compile(
    r"## \[([0-9]+\.[0-9]+\.[0-9]+)\] - \d{4}-\d{2}-\d{2}"
)


def _load(relative: str) -> dict[str, Any]:
    return json.loads((_ROOT / relative).read_text(encoding="utf-8"))


def test_all_three_manifests_agree() -> None:
    claude = _load(".claude-plugin/plugin.json")
    codex = _load(".codex-plugin/plugin.json")
    agy = _load(".antigravity-plugin/plugin.json")
    for key in ("name", "version", "license"):
        assert codex[key] == claude[key], key
        assert agy[key] == claude[key], key


def test_marketplace_lists_the_plugin_at_the_repo_root() -> None:
    market = _load(".claude-plugin/marketplace.json")
    entry = next(p for p in market["plugins"] if p["name"] == "agent-kit")
    assert entry["source"] == "./"
    assert _load(".claude-plugin/plugin.json")["name"] == entry["name"]


def test_codex_manifest_paths_stay_inside_the_plugin() -> None:
    # Codex ignores a manifest path that escapes the plugin root or does
    # not start with "./"; it does not fail on one, so check the shape.
    codex = _load(".codex-plugin/plugin.json")
    for key in ("skills", "hooks"):
        assert codex[key].startswith("./") and ".." not in codex[key], key


def test_claude_manifest_lists_every_claude_agent() -> None:
    claude = _load(".claude-plugin/plugin.json")
    listed = claude["agents"]
    assert isinstance(listed, list) and listed
    for rel in listed:
        assert rel.startswith("./claude-agents/") and rel.endswith(".md"), rel
        assert ".." not in rel, rel
        assert (_ROOT / rel).is_file(), rel
    on_disk = {
        f"./claude-agents/{p.name}"
        for p in (_ROOT / "claude-agents").glob("*.md")
    }
    assert len(listed) == len(on_disk) and set(listed) == on_disk


def test_manifest_version_is_strict_semver() -> None:
    version = _load(".claude-plugin/plugin.json")["version"]
    assert isinstance(version, str) and _SEMVER_RE.fullmatch(version), version


def test_changelog_top_entry_matches_manifest_version() -> None:
    # A release pull request bumps the manifests and writes the entry
    # together: a bump without an entry, or an entry that lists nothing,
    # fails here.
    lines = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    headings = map(_CHANGELOG_HEADING_RE.fullmatch, lines)
    top, heading = next((i, m) for i, m in enumerate(headings) if m)
    assert heading[1] == _load(".claude-plugin/plugin.json")["version"]
    entry = itertools.takewhile(
        lambda line: not line.startswith("## "), lines[top + 1 :]
    )
    assert any(line.startswith("- ") and line[2:].strip() for line in entry)
