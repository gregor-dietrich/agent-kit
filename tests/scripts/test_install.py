"""Behavioral pin for the uv bootstrap in ``scripts/install.sh``.

Runs the real script, copied under ``tmp_path``, with no uv on PATH, a
fake ``python3`` whose ``-m venv`` leaves a recording ``pip`` and a no-op
``uv``. What the bootstrap hands pip is the guarantee: the locked version
and every sha256 uv.lock records for uv's wheels, installed with hash
checking on and sdists off. No real uv or pip, no network, nothing written
outside ``tmp_path``.
"""

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_TOOLS = ("bash", "awk", "dirname", "rm", "cat", "mkdir", "chmod")

# Fakes `python3 -m venv <dir>`: a pip that records its argv and the
# requirements file after -r, and a uv that succeeds.
_FAKE_PYTHON = """#!{bash}
d="$3"
mkdir -p "$d/bin"
cat > "$d/bin/pip" <<'PIP'
#!{bash}
printf '%s\\n' "$*" >> "$FAKE_LOG/pip"
while [ $# -gt 0 ]; do
    if [ "$1" = -r ]; then cat "$2" > "$FAKE_LOG/reqs"; fi
    shift
done
PIP
printf '#!{bash}\\nexit 0\\n' > "$d/bin/uv"
chmod +x "$d/bin/pip" "$d/bin/uv"
"""

_NO_WHEELS = """[[package]]
name = "uv"
version = "1.2.3"
source = {{ registry = "https://pypi.org/simple" }}
sdist = {{ url = "u/uv-1.2.3.tar.gz", hash = "sha256:{h}", size = 1 }}
"""
_UV_THEN_OTHER = """[[package]]
name = "uv"
version = "1.2.3"
wheels = [
    {{ url = "u/uv-1.2.3-py3-none-any.whl", hash = "sha256:{u}", size = 1 }},
]

[[package]]
name = "other"
version = "9.9.9"
wheels = [
    {{ url = "o/other-9.9.9-py3-none-any.whl", hash = "sha256:{o}", size = 1 }},
]
"""
_NO_UV = '[[package]]\nname = "other"\nversion = "1.0"\n'


_Result = tuple[subprocess.CompletedProcess[str], Path]


def _run(tmp_path: Path, lock: str) -> _Result:
    (tmp_path / "scripts").mkdir()
    shutil.copy(_ROOT / "scripts" / "install.sh", tmp_path / "scripts")
    (tmp_path / "uv.lock").write_text(lock, encoding="utf-8")
    farm, log = tmp_path / "farm", tmp_path / "log"
    farm.mkdir()
    log.mkdir()
    for tool in _TOOLS:
        found = shutil.which(tool)
        assert found, f"test needs {tool} on PATH"
        (farm / tool).symlink_to(found)
    bash = shutil.which("bash")
    assert bash, "test needs bash on PATH"
    (farm / "python3").write_text(
        _FAKE_PYTHON.format(bash=bash), encoding="utf-8"
    )
    (farm / "python3").chmod(0o755)
    env = {"PATH": str(farm), "FAKE_LOG": str(log)}
    assert shutil.which("uv", path=env["PATH"]) is None
    proc = subprocess.run(
        [bash, "scripts/install.sh"], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=60,
    )
    return proc, log


def test_bootstrap_installs_only_hashed_uv_wheels(tmp_path: Path) -> None:
    lock = (_ROOT / "uv.lock").read_text(encoding="utf-8")
    uv = next(
        p for p in tomllib.loads(lock)["package"] if p["name"] == "uv"
    )
    proc, log = _run(tmp_path, lock)
    assert proc.returncode == 0, proc.stderr
    argv = (log / "pip").read_text(encoding="utf-8")
    assert "--require-hashes" in argv
    assert "--only-binary=:all:" in argv
    reqs = (log / "reqs").read_text(encoding="utf-8")
    assert reqs.split()[0] == f"uv=={uv['version']}"
    hashes = {
        tok.split("=", 1)[1]
        for tok in reqs.split()
        if tok.startswith("--hash=")
    }
    assert hashes == {w["hash"] for w in uv["wheels"]}
    assert uv["sdist"]["hash"] not in reqs


def test_bootstrap_stops_at_the_end_of_the_uv_block(tmp_path: Path) -> None:
    u, o = "a" * 64, "b" * 64
    proc, log = _run(tmp_path, _UV_THEN_OTHER.format(u=u, o=o))
    assert proc.returncode == 0, proc.stderr
    reqs = (log / "reqs").read_text(encoding="utf-8")
    assert reqs.split() == ["uv==1.2.3", f"--hash=sha256:{u}"]


@pytest.mark.parametrize(
    "lock",
    [_NO_WHEELS.format(h="a" * 64), _NO_UV],
    ids=["no-wheels", "no-uv"],
)
def test_bootstrap_refuses_without_a_hashed_pin(
    tmp_path: Path, lock: str
) -> None:
    proc, log = _run(tmp_path, lock)
    assert proc.returncode != 0
    assert "uv.lock" in proc.stderr
    assert not (log / "pip").exists()
