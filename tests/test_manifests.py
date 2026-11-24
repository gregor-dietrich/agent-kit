"""The plugin manifests describe one plugin across all three clients."""

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]


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
