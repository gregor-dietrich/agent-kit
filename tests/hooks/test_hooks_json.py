"""Registration pins for hooks/hooks.json, read by Claude Code and Codex.

A hook that is registered but cannot start fails open exactly like one
that crashes, so the wiring is pinned as carefully as the guards.
"""

import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import hook_lib

_ROOT = Path(__file__).resolve().parents[2]
_HOOKS: dict[str, list[dict[str, Any]]] = json.loads(
    (_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8")
)["hooks"]
# Both clients expand ${CLAUDE_PLUGIN_ROOT} (Codex sets it for compatibility
# alongside its own PLUGIN_ROOT), so it is the one spelling that serves both.
_COMMAND = re.compile(r'^"\$\{CLAUDE_PLUGIN_ROOT\}/hooks/([\w.-]+)"$')

# The PreToolUse registrations' `"timeout": 5` is enough: measured on the
# development machine, each guard answers in 17 to 22 ms warm and about
# 90 ms on a first run. A guard that exceeds its timeout lets the call
# through, so the value needs a recorded reason; it stays unless a
# measurement says otherwise. (The SessionStart hooks were not measured and
# have no call to let through.)


def _registrations() -> list[tuple[str, str, str]]:
    return [
        (event, group.get("matcher", ""), hook["command"])
        for event, groups in _HOOKS.items()
        for group in groups
        for hook in group["hooks"]
    ]


def _script(command: str) -> Path:
    match = _COMMAND.fullmatch(command)
    assert match, f"not a plugin-root hook command: {command}"
    return _ROOT / "hooks" / match.group(1)


def _registered(name: str) -> str:
    """The one registered command that runs hooks/*name*."""
    [command] = [c for _, _, c in _registrations() if _script(c).name == name]
    return command


@pytest.mark.parametrize(("event", "matcher", "command"), _registrations())
def test_every_registered_script_exists_and_is_executable(
    event: str, matcher: str, command: str
) -> None:
    script = _script(command)
    assert script.is_file(), script
    assert os.access(script, os.X_OK), f"{script} lost its exec bit"


def test_the_guards_are_wired_to_the_tools_they_guard() -> None:
    wired = {
        (event, matcher, _script(command).name)
        for event, matcher, command in _registrations()
    }
    assert wired == {
        ("SessionStart", "", "session-context.sh"),
        ("SessionStart", "", "prune_session_tmp.py"),
        ("PreToolUse", "Bash", "pipe-status-guard.sh"),
        ("PreToolUse", "Bash", "tea-guard.sh"),
        ("PreToolUse", "Write|Edit|apply_patch", "decisions_status_guard.py"),
    }


def _probe(matcher: str, script: str, root: Path) -> dict[str, Any]:
    """A payload the registered guard must deny, run from *root*."""
    log = root / "docs" / "decisions.md"
    if script == "decisions_status_guard.py":
        return {
            "cwd": str(root),
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(log),
                "old_string": "**Status:** Proposed",
                "new_string": "**Status:** Accepted",
            },
        }
    command = {
        "pipe-status-guard.sh": "make test | tail -5",
        "tea-guard.sh": "tea issues 1",
    }[script]
    return {
        "cwd": str(root),
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


_GUARDS = [r for r in _registrations() if r[0] == "PreToolUse"]


def _run_guard(
    matcher: str, command: str, root: Path, path_prefix: Path | None = None
) -> dict[str, Any]:
    """Run a registered guard on its probe; return its decision envelope.

    Expanded and run through a shell the way the clients invoke it.
    *path_prefix* goes first on PATH, so its ``python3`` is the one both
    the prefilters and the ``env python3`` shebang find.
    """
    (root / ".git").mkdir()
    (root / "docs").mkdir()
    (root / "docs" / "decisions.md").write_text(
        "## ADR-0001 — x\n\n**Status:** Proposed\n", encoding="utf-8"
    )
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(_ROOT)}
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["sh", "-c", command],
        cwd=root,
        env=env,
        input=json.dumps(_probe(matcher, _script(command).name, root)),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    decision: dict[str, Any] = json.loads(result.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny", decision
    return decision


@pytest.mark.parametrize(("event", "matcher", "command"), _GUARDS)
def test_the_registered_command_denies_end_to_end(
    event: str, matcher: str, command: str, tmp_path: Path
) -> None:
    # A hook that cannot start, or whose prefilter drops what it should
    # pass on, would fail open in a session and in silence — here it fails
    # the test.
    _run_guard(matcher, command, tmp_path)


@pytest.fixture(scope="session")
def python3_dir(
    pytestconfig: pytest.Config, tmp_path_factory: pytest.TempPathFactory
) -> Callable[[str], Path]:
    """A directory whose ``python3`` is CPython *version*, fetched by uv.

    Fetched into ``.test-python/`` under the repository (a temporary
    directory when the pytest cache plugin is disabled), with HOME, the XDG
    directories and uv's own pointed there as well, so the real global
    install is never touched and a warm directory skips the download. Not
    the pytest cache: devkit's test.sh passes ``--cache-clear``, which would
    wipe it and fetch both CPythons on every ``make test``.
    """
    if getattr(pytestconfig, "cache", None):
        root = _ROOT / ".test-python"
        root.mkdir(exist_ok=True)
    else:
        root = tmp_path_factory.mktemp("python3")
    env = {k: v for k, v in os.environ.items() if not k.startswith("UV_")}
    env |= {
        key: str(root / key.lower())
        for key in (
            "XDG_CACHE_HOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_BIN_HOME",
            "UV_CACHE_DIR",
            "UV_PYTHON_INSTALL_DIR",
        )
    }
    env["HOME"] = str(root)
    uv = Path(sys.executable).with_name("uv")

    def run_uv(*args: str) -> str:
        result = subprocess.run(
            [str(uv), *args],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def fetch(version: str) -> Path:
        run_uv("python", "install", "--no-bin", version)
        found = run_uv(
            "python", "find", "--no-project", "--managed-python", version
        )
        bin_dir = root / f"bin-{version}"
        bin_dir.mkdir(exist_ok=True)
        # Renamed into place, so a session sharing the directory never finds
        # python3 missing and falls through to the next one on PATH.
        link = bin_dir / f".python3.{os.getpid()}"
        link.unlink(missing_ok=True)
        link.symlink_to(found)
        link.replace(bin_dir / "python3")
        ran = subprocess.run(
            [
                bin_dir / "python3",
                "-c",
                "import sys; print(*sys.version_info[:2], sep='.')",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.strip()
        assert ran == version, ran
        return bin_dir

    return fetch


@pytest.mark.parametrize("version", ["3.8", "3.9", "3.10"])
@pytest.mark.parametrize(("event", "matcher", "command"), _GUARDS)
def test_the_registered_command_holds_the_python_floor(
    event: str,
    matcher: str,
    command: str,
    version: str,
    tmp_path: Path,
    python3_dir: Callable[[str], Path],
) -> None:
    # The hooks run under whatever python3 a client finds first on PATH,
    # not under this venv's. Below the floor a guard cannot even import,
    # and a crash fails open, so each must deny naming the floor; at the
    # floor each must reach its own verdict, which keeps the floor honest.
    floor = f"need Python {hook_lib.FLOOR[0]}.{hook_lib.FLOOR[1]} or newer"
    reason = _run_guard(matcher, command, tmp_path, python3_dir(version))[
        "permissionDecisionReason"
    ]
    below = tuple(map(int, version.split("."))) < hook_lib.FLOOR
    assert (floor in reason) == below, reason


# Run under the floor interpreter: prints every import in a ``*.py`` directly
# in argv[1] that is neither 3.10's stdlib nor a sibling module.
_IMPORT_CHECK = """
import ast, sys
from pathlib import Path

files = sorted(Path(sys.argv[1]).glob("*.py"))
known = sys.stdlib_module_names | {f.stem for f in files}
for file in files:
    for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [node.module] if node.module else []
        else:
            continue
        for name in names:
            if name.split(".")[0] not in known:
                print(f"{file.name}:{node.lineno}: {name.split('.')[0]}")
"""


def _unknown_imports(
    directory: Path, bin_dir: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [bin_dir / "python3", "-I", "-c", _IMPORT_CHECK, str(directory)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_hooks_import_only_the_floors_stdlib(
    python3_dir: Callable[[str], Path],
) -> None:
    # The floor test probes one path per guard; an import inside a function
    # on an unprobed path would pass it, and the venv the tests run under
    # has third-party packages that would satisfy the import anyway. Checked
    # against 3.10's stdlib, a function-level ``tomllib`` (3.11+) shows too.
    result = _unknown_imports(_ROOT / "hooks", python3_dir("3.10"))
    assert (result.returncode, result.stdout) == (0, ""), result.stdout


def test_the_import_check_names_what_is_not_stdlib_or_a_sibling(
    tmp_path: Path, python3_dir: Callable[[str], Path]
) -> None:
    (tmp_path / "a.py").write_text("import json\n", encoding="utf-8")
    (tmp_path / "b.py").write_text(
        "import a\n\n\ndef f():\n"
        "    import tomli\n"
        "    from tomllib import loads\n",
        encoding="utf-8",
    )
    result = _unknown_imports(tmp_path, python3_dir("3.10"))
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["b.py:5: tomli", "b.py:6: tomllib"]


def test_session_context_is_injected_verbatim(tmp_path: Path) -> None:
    command = _registered("session-context.sh")
    result = subprocess.run(
        ["sh", "-c", command],
        cwd=tmp_path,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(_ROOT)},
        input="{}",
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    context = (_ROOT / "hooks" / "session-context.md").read_text(
        encoding="utf-8"
    )
    assert result.stdout == context


def test_session_context_stays_small() -> None:
    # It is injected into every session in every repository the plugin is
    # installed for; anything longer belongs in a skill.
    context = (_ROOT / "hooks" / "session-context.md").read_text(
        encoding="utf-8"
    )
    assert len(context) <= 1200


_SESSION = "00000000-0000-4000-8000-00000000000{}"


def _run_pruner(base: Path, path_prefix: Path | None = None) -> Path:
    """Run the registered pruner on a stale session and the current one.

    Returns the stale one; the current one must outlive every run. The
    registry it consults is an empty directory, not this machine's.
    """
    root = base / f"claude-{os.getuid()}"
    root.mkdir(exist_ok=True)
    root.chmod(0o700)  # as Claude Code makes it, whatever the umask
    sessions = root / "-proj"
    for n in (0, 1):
        (sessions / _SESSION.format(n)).mkdir(parents=True, exist_ok=True)
        os.utime(sessions / _SESSION.format(n), (0, 0))
    env = {
        **os.environ,
        "CLAUDE_PLUGIN_ROOT": str(_ROOT),
        "CLAUDE_CODE_TMPDIR": str(base),
        "CLAUDE_CONFIG_DIR": str(base / "config"),
    }
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["sh", "-c", _registered("prune_session_tmp.py")],
        cwd=base,
        env=env,
        input=json.dumps(
            {
                "hook_event_name": "SessionStart",
                "session_id": _SESSION.format(1),
            }
        ),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert (result.returncode, result.stdout) == (0, ""), result.stderr
    return sessions / _SESSION.format(0)


def _gone(path: Path) -> bool:
    """Whether *path* disappears within a generous wait for the child."""
    deadline = time.monotonic() + 20
    while path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    return not path.exists()


def test_the_pruner_removes_a_stale_session_in_the_background(
    tmp_path: Path,
) -> None:
    # Smoke only: that it returns cleanly (_run_pruner) and that the
    # detached child finishes the job. What it keeps is pinned in process,
    # deterministically, in test_prune_session_tmp.py.
    assert _gone(_run_pruner(tmp_path))


@pytest.mark.parametrize("version", ["3.8", "3.9", "3.10"])
def test_the_pruner_holds_the_python_floor(
    version: str, tmp_path: Path, python3_dir: Callable[[str], Path]
) -> None:
    # A SessionStart hook has no call to deny: below the floor it exits
    # quietly, which _run_pruner checks (status 0, empty stdout: an import
    # crash would not give that), and it forks nothing, so the stale dir is
    # still there when the hook has exited; at the floor it prunes.
    stale = _run_pruner(tmp_path, python3_dir(version))
    below = tuple(map(int, version.split("."))) < hook_lib.FLOOR
    assert stale.is_dir() if below else _gone(stale)
