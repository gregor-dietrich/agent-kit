"""Behavioral pin for the release snippet in ``README.md``, "Releasing".

Extracts the first ``sh`` block under that heading and runs it as printed,
under bash and, where installed, zsh, in a throwaway clone of a scratch
bare origin, signing with a throwaway key. Nothing leaves ``tmp_path``:
PATH is a farm of the few tools the snippet needs and the environment is
built from scratch.
"""

import json
import shlex
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_MANIFESTS = (
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    ".antigravity-plugin/plugin.json",
)
_TOOLS = ("git", "ssh-keygen", "sed", "cut", "grep", "bash", "zsh")
_NOT_CLEAN = "working tree is not clean"
_NOT_SIGNED = "is not signed by the release key allowed_signers names"
_SHELLS = [
    "bash",
    pytest.param(
        "zsh",
        marks=pytest.mark.skipif(
            shutil.which("zsh") is None, reason="zsh not installed"
        ),
    ),
]


def _snippet() -> str:
    lines = (_ROOT / "README.md").read_text().splitlines()
    start = lines.index("## Releasing")
    first = next(
        i for i in range(start, len(lines)) if lines[i].strip() == "```sh"
    )
    end = next(
        i for i in range(first + 1, len(lines)) if lines[i].strip() == "```"
    )
    text = textwrap.dedent("\n".join(lines[first + 1 : end]))
    assert "tag -a -s" in text, "extracted the wrong block"
    return text


_SNIPPET = _snippet()
_VERSION = json.loads((_ROOT / _MANIFESTS[0]).read_text())["version"]
_TAG = f"v{_VERSION}"
_BAD_JSON = "raise SystemExit('shadowed json imported')\n"


def _farm(tmp_path: Path) -> Path:
    farm = tmp_path / "bin"
    farm.mkdir()
    for name in _TOOLS:
        found = shutil.which(name)
        if found is None and name != "zsh":
            pytest.fail(f"the snippet's tool is missing: {name}")
        if found:
            (farm / name).symlink_to(found)
    (farm / "python3").symlink_to(sys.executable)
    out = subprocess.run(
        [farm / "git", "--version"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    major, minor = (int(p) for p in out.split()[2].split(".")[:2])
    assert (major, minor) >= (2, 35), f"git 2.35 or later needed: {out}"
    return farm


def _env(tmp_path: Path, farm: Path) -> dict[str, str]:
    config = tmp_path / "gitconfig"
    config.write_text(
        "[init]\n\tdefaultBranch = main\n\tdefaultRefFormat = files\n"
    )
    (tmp_path / "home").mkdir()
    (tmp_path / "tmp").mkdir()
    env = {
        "PATH": str(farm),
        "HOME": str(tmp_path / "home"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(config),
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
        "LC_ALL": "C",
        "TMPDIR": str(tmp_path / "tmp"),
    }
    for role in ("AUTHOR", "COMMITTER"):
        env[f"GIT_{role}_NAME"] = "Release Test"
        env[f"GIT_{role}_EMAIL"] = "release@example.invalid"
    return env


@pytest.fixture(scope="module")
def key(tmp_path_factory):
    """A throwaway ed25519 key pair."""
    path = tmp_path_factory.mktemp("keys") / "release"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)],
        check=True,
        capture_output=True,
    )
    return path


class _Case:
    def __init__(self, tmp_path: Path, key: Path, signers: str | None = None):
        self.env = _env(tmp_path, _farm(tmp_path))
        self.env["AGENT_KIT_RELEASE_KEY"] = str(key)
        self.origin = tmp_path / "origin.git"
        self.clone = tmp_path / "clone"
        self.pub = key.with_name(key.name + ".pub").read_text()
        self.git("init", "-q", "--bare", str(self.origin), cwd=tmp_path)
        self.git("clone", "-q", str(self.origin), str(self.clone), cwd=tmp_path)
        for rel in _MANIFESTS:
            (self.clone / rel).parent.mkdir(exist_ok=True)
            shutil.copy(_ROOT / rel, self.clone / rel)
        fields = " ".join(self.pub.split()[:2])
        (self.clone / "allowed_signers").write_text(
            signers or f'agent-kit-release namespaces="git" {fields}\n'
        )
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")
        self.git("push", "-q", "-u", "origin", "main")

    def git(self, *args, cwd=None):
        done = subprocess.run(
            ["git", *args],
            cwd=cwd or self.clone,
            env=self.env,
            capture_output=True,
            check=False,
            text=True,
            timeout=60,
        )
        assert done.returncode == 0, done.stderr
        return done.stdout.strip()

    def origin_git(self, *args):
        return self.git(*args, cwd=self.origin)

    def hook(self, body: str):
        path = self.origin / "hooks" / "pre-receive"
        path.write_text(f"#!/bin/sh\n{body}\nexit 1\n")
        path.chmod(0o755)

    def run(self, shell: str, **extra):
        return subprocess.run(
            [*(["zsh", "-f"] if shell == "zsh" else ["bash"]), "-c", _SNIPPET],
            cwd=self.clone,
            env={**self.env, **extra},
            capture_output=True,
            check=False,
            text=True,
            timeout=60,
        )

    def tags(self, cwd=None) -> str:
        return self.git("tag", "-l", cwd=cwd)

    def assert_released(self, done):
        assert done.returncode == 0, done.stderr
        ref = f"refs/tags/{_TAG}"
        local = self.git("rev-parse", ref)
        assert local == self.origin_git("rev-parse", ref)
        subject = self.git("tag", "-l", "--format=%(contents:subject)", _TAG)
        assert subject == f"agent-kit {_TAG}"
        commit = self.git("rev-parse", f"{ref}^{{commit}}")
        assert commit == self.origin_git("rev-parse", "refs/heads/main")
        assert commit == self.origin_git("rev-parse", "refs/heads/release")
        self.git(
            "-c",
            "gpg.ssh.allowedSignersFile=allowed_signers",
            "verify-tag",
            ref,
        )


@pytest.fixture
def case(tmp_path, key):
    return _Case(tmp_path, key)


@pytest.mark.parametrize("shell", _SHELLS)
def test_tags(case, shell):
    case.assert_released(case.run(shell))


@pytest.mark.parametrize("shell", _SHELLS)
def test_branch_named_like_the_tag(case, shell):
    case.git("branch", _TAG)
    done = case.run(shell)
    case.assert_released(done)
    assert "ambiguous" not in done.stderr


@pytest.mark.parametrize("shell", _SHELLS)
def test_push_rejected(case, shell):
    case.hook("")
    done = case.run(shell)
    assert done.returncode != 0
    assert f"git ls-remote origin refs/tags/{_TAG}" in done.stderr
    assert f"deleted local {_TAG}" in done.stderr
    assert case.tags() == ""


@pytest.mark.parametrize("shell", _SHELLS)
def test_delete_fails(case, shell):
    lock = case.clone / ".git" / "refs" / "tags" / f"{_TAG}.lock"
    case.hook(f": > '{lock}'")
    done = case.run(shell)
    assert done.returncode != 0
    assert f"git ls-remote origin refs/tags/{_TAG}" in done.stderr
    assert "deleted local" not in done.stderr
    assert case.tags() == _TAG
    assert case.tags(case.origin) == ""


@pytest.mark.parametrize("shell", _SHELLS)
def test_tag_exists(case, shell):
    case.git("tag", _TAG)
    before = case.git("rev-parse", f"refs/tags/{_TAG}")
    done = case.run(shell)
    assert done.returncode != 0
    assert "fatal:" not in done.stderr
    assert (
        f"tag {_TAG} already exists in this clone: if main's manifests "
        f"({_VERSION}) still name the last release, land the release pull "
        f"request first; if git ls-remote origin refs/tags/{_TAG} lists "
        'it, only the release push is left (README.md, "Releasing"); '
        f"otherwise a failed run left it: git tag -d {_TAG}"
    ) in done.stderr
    assert case.git("rev-parse", f"refs/tags/{_TAG}") == before


@pytest.mark.parametrize("shell", _SHELLS)
def test_shadowed_json(case, shell, tmp_path):
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "json.py").write_text(_BAD_JSON)
    (case.clone / ".gitignore").write_text("/json.py\n")
    (case.clone / "json.py").write_text(_BAD_JSON)
    case.git("add", ".gitignore")
    case.git("commit", "-q", "-m", "ignore json.py")
    case.git("push", "-q", "origin", "main")
    case.assert_released(case.run(shell, PYTHONPATH=str(shadow)))


@pytest.mark.parametrize("flag", ["--skip-worktree", "--assume-unchanged"])
@pytest.mark.parametrize("shell", _SHELLS)
def test_hidden_edit(case, shell, flag):
    manifest = case.clone / _MANIFESTS[0]
    manifest.write_text(manifest.read_text() + "\n")
    case.git("update-index", flag, _MANIFESTS[0])
    done = case.run(shell)
    assert done.returncode != 0
    assert _NOT_CLEAN in done.stderr
    assert case.tags() == ""


@pytest.mark.parametrize("shell", _SHELLS)
def test_push_mapping_cannot_force(case, shell):
    case.git("tag", "-a", _TAG, "-m", "published")
    case.git("push", "-q", "origin", f"refs/tags/{_TAG}")
    published = case.origin_git("rev-parse", f"refs/tags/{_TAG}")
    case.git("tag", "-d", _TAG)
    case.git("config", "remote.origin.push", "+refs/tags/*:refs/tags/*")
    done = case.run(shell)
    assert done.returncode != 0
    assert case.origin_git("rev-parse", f"refs/tags/{_TAG}") == published


@pytest.mark.parametrize("shell", _SHELLS)
def test_grep_fails(case, shell):
    (Path(case.env["PATH"]) / "grep").unlink()
    done = case.run(shell)
    assert done.returncode != 0
    assert _NOT_CLEAN in done.stderr
    assert case.tags() == ""


@pytest.mark.parametrize("shell", _SHELLS)
def test_verify_fails(case, shell):
    revoked = case.clone.parent / "revoked"
    revoked.write_text(case.pub)
    case.git("config", "gpg.ssh.revocationFile", str(revoked))
    done = case.run(shell)
    assert done.returncode != 0
    assert _NOT_SIGNED in done.stderr
    assert f"deleted local {_TAG}" in done.stderr
    assert case.tags() == ""
    assert case.tags(case.origin) == ""


@pytest.mark.parametrize("shell", _SHELLS)
def test_verify_delete_fails(case, shell, tmp_path):
    lock = case.clone / ".git" / "refs" / "tags" / f"{_TAG}.lock"
    real = shlex.quote(str(shutil.which("ssh-keygen")))
    wrapper = tmp_path / "signer.sh"
    wrapper.write_text(
        "#!/bin/sh\n"
        'case " $* " in\n'
        f'  *" -Y sign "*) exec {real} "$@" ;;\n'
        "esac\n"
        f": > {shlex.quote(str(lock))}\n"
        "exit 1\n"
    )
    wrapper.chmod(0o755)
    case.git("config", "gpg.ssh.program", str(wrapper))
    done = case.run(shell)
    assert done.returncode != 0
    assert _NOT_SIGNED in done.stderr
    assert "deleted local" not in done.stderr
    assert case.tags() == _TAG
    assert case.tags(case.origin) == ""


@pytest.mark.parametrize("shell", _SHELLS)
def test_fsmonitor_hidden_edit(case, shell, tmp_path):
    hook = tmp_path / "fsmon.sh"
    hook.write_text(
        "#!/bin/sh\n"
        "if [ -z \"$2\" ]; then printf 'tok1\\0/\\0'; "
        "else printf 'tok1\\0'; fi\n"
    )
    hook.chmod(0o755)
    case.git("config", "core.fsmonitor", str(hook))
    case.git("status", "--porcelain")
    case.git("status", "--porcelain")
    manifest = case.clone / _MANIFESTS[0]
    manifest.write_text(manifest.read_text() + "\n")
    assert case.git("status", "--porcelain") == ""
    done = case.run(shell)
    assert done.returncode != 0
    assert _NOT_CLEAN in done.stderr
    assert case.tags() == ""


@pytest.mark.parametrize("shell", _SHELLS)
def test_wrong_key(tmp_path, key, shell):
    real = (_ROOT / "allowed_signers").read_text()
    case = _Case(tmp_path, key, signers=real)
    done = case.run(shell)
    assert done.returncode != 0
    assert "is not the release key" in done.stderr
    assert case.tags() == ""
