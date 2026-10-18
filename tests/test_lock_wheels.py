"""uv.lock locks the shellcheck-py wheels the platform marker promises."""

import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_EXPECTED = {
    "macosx_10_9_x86_64",
    "macosx_11_0_arm64",
    "manylinux1_x86_64.manylinux2014_x86_64.manylinux_2_17_x86_64"
    ".manylinux_2_5_x86_64",
    "win_amd64",
}


def test_shellcheck_py_wheels_match_the_platform_marker() -> None:
    lock = tomllib.loads((_ROOT / "uv.lock").read_text(encoding="utf-8"))
    (package,) = (p for p in lock["package"] if p["name"] == "shellcheck-py")
    # <name>-<version>-<python tag>-<abi tag>-<platform tag>.whl
    tags = {
        w["url"].rsplit("/", 1)[-1].removesuffix(".whl").split("-", 4)[4]
        for w in package["wheels"]
    }
    assert tags == _EXPECTED, (
        "the shellcheck-py wheel set changed: update the PEP 508 marker on "
        "shellcheck-py in pyproject.toml and the platform sentence in "
        'AGENTS.md ("Gates") with it'
    )
