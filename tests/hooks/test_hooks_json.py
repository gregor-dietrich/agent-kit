"""Registration pins for hooks/hooks.json (Claude/Codex) and hooks.json (Agy).

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
# development machine, each guard answers in 17 to 23 ms warm and about
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
        ("SessionStart", "", "prune-session-tmp.sh"),
        ("PreToolUse", "Bash", "pipe-status-guard.sh"),
        ("PreToolUse", "Bash", "tea-guard.sh"),
        ("PreToolUse", "Write|Edit|apply_patch", "decisions-status-guard.sh"),
    }


def _probe(matcher: str, script: str, root: Path) -> dict[str, Any]:
    """A payload the registered guard must deny, run from *root*."""
    log = root / "docs" / "decisions.md"
    if script == "decisions-status-guard.sh":
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


def _run_guard_cmd(
    command: str,
    run_cwd: Path,
    root: Path,
    payload: dict[str, Any],
    path_prefix: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run *command* on *payload* in a prepared repo under *root*."""
    (root / ".git").mkdir()
    (root / "docs").mkdir()
    (root / "docs" / "decisions.md").write_text(
        "## ADR-0001 — x\n\n**Status:** Proposed\n", encoding="utf-8"
    )
    env = {**os.environ, **(extra_env or {})}
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["sh", "-c", command],
        cwd=run_cwd,
        env=env,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _run_guard(
    matcher: str,
    command: str,
    root: Path,
    path_prefix: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run a registered guard on its probe; return its decision envelope.

    Expanded and run through a shell the way the clients invoke it.
    *path_prefix* goes first on PATH, so its ``python3`` is the one the
    wrappers find. *extra_env* joins the environment.
    """
    raw = _run_guard_cmd(
        command,
        root,
        root,
        _probe(matcher, _script(command).name, root),
        path_prefix=path_prefix,
        extra_env={"CLAUDE_PLUGIN_ROOT": str(_ROOT), **(extra_env or {})},
    )
    decision: dict[str, Any] = raw["hookSpecificOutput"]
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


@pytest.fixture(params=["pythonpath", "pythonhome", "user-site"])
def hostile(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    python3_dir: Callable[[str], Path],
) -> tuple[dict[str, str], Path | None]:
    """An environment that breaks a Python started without ``-E -s``.

    Returns the extra environment and the PATH prefix to run under.
    """
    if request.param == "pythonpath":
        # A stdlib-named module ahead of the standard library.
        shadow = tmp_path / "shadow"
        shadow.mkdir()
        (shadow / "json.py").write_text(
            'raise RuntimeError("shadowed")\n', encoding="utf-8"
        )
        return {"PYTHONPATH": str(shadow)}, None
    if request.param == "pythonhome":
        return {"PYTHONHOME": str(tmp_path / "nonexistent")}, None
    # The venv's python3 has the user site disabled, so this case runs the
    # floor interpreter, where each guard reaches its own verdict.
    bin_dir = python3_dir("3.10")
    home = tmp_path / "home"
    env = {"HOME": str(home), "PYTHONUSERBASE": str(home / ".local")}
    site = subprocess.run(
        [
            bin_dir / "python3",
            "-c",
            "import site; print(site.getusersitepackages())",
        ],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()
    Path(site).mkdir(parents=True)
    (Path(site) / "usercustomize.py").write_text(
        'raise SystemExit("usercustomize ran")\n', encoding="utf-8"
    )
    return env, bin_dir


@pytest.mark.parametrize(("event", "matcher", "command"), _GUARDS)
def test_the_registered_command_ignores_a_hostile_python_environment(
    event: str,
    matcher: str,
    command: str,
    tmp_path: Path,
    hostile: tuple[dict[str, str], Path | None],
) -> None:
    # Each case stops or hijacks a Python started without -E -s (a
    # stdlib-named module on PYTHONPATH, a bad PYTHONHOME, a raising
    # usercustomize in the user site), so the hook would give no decision
    # and the guarded call would proceed, in silence. Started with -E -s,
    # it still reaches its verdict.
    env, prefix = hostile
    _run_guard(matcher, command, tmp_path, prefix, env)


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


@pytest.mark.parametrize(
    "stdin_payload",
    [
        pytest.param("{}", id="empty-object"),
        pytest.param(
            json.dumps(
                {
                    "hook_event_name": "SessionStart",
                    "cwd": '/tmp/"conversationId',
                }
            ),
            id="claude-cwd-with-substring",
        ),
    ],
)
def test_session_context_is_injected_verbatim(
    tmp_path: Path, stdin_payload: str
) -> None:
    command = _registered("session-context.sh")
    result = subprocess.run(
        ["sh", "-c", command],
        cwd=tmp_path,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(_ROOT)},
        input=stdin_payload,
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


def _run_pruner(
    base: Path,
    path_prefix: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> Path:
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
        **(extra_env or {}),
    }
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["sh", "-c", _registered("prune-session-tmp.sh")],
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


def test_the_pruner_ignores_a_hostile_python_environment(
    tmp_path: Path, hostile: tuple[dict[str, str], Path | None]
) -> None:
    # Same as the guards: none of these environments may stop the pruner
    # (status 0, empty stdout, as _run_pruner checks) or keep it from
    # pruning.
    env, prefix = hostile
    assert _gone(_run_pruner(tmp_path, prefix, env))


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


# --- Antigravity root hooks.json --------------------------------------------

_AGY_HOOKS: dict[str, Any] = json.loads(
    (_ROOT / "hooks.json").read_text(encoding="utf-8")
)["agent-kit"]
_AGY_COMMAND = re.compile(r"^\./hooks/([\w.-]+)$")
_AGY_PAYLOADS: dict[str, Any] = json.loads(
    (
        _ROOT / "tests" / "hooks" / "fixtures" / "agy_hook_payloads.json"
    ).read_text(encoding="utf-8")
)


def _agy_registrations() -> list[tuple[str, str, str]]:
    assert set(_AGY_HOOKS) <= {"SessionStart", "PreToolUse"}
    out: list[tuple[str, str, str]] = []
    for handler in _AGY_HOOKS.get("SessionStart", []):
        out.append(("SessionStart", "", handler["command"]))
    for group in _AGY_HOOKS.get("PreToolUse", []):
        matcher = group.get("matcher", "")
        for handler in group["hooks"]:
            out.append(("PreToolUse", matcher, handler["command"]))
    return out


def _agy_script(command: str) -> Path:
    match = _AGY_COMMAND.fullmatch(command)
    assert match, f"not a relative plugin-root hook command: {command}"
    return _ROOT / "hooks" / match.group(1)


_AGY_GUARDS = [r for r in _agy_registrations() if r[0] == "PreToolUse"]


@pytest.mark.parametrize(("event", "matcher", "command"), _agy_registrations())
def test_every_antigravity_script_exists_and_is_executable(
    event: str, matcher: str, command: str
) -> None:
    script = _agy_script(command)
    assert script.is_file(), script
    assert os.access(script, os.X_OK), f"{script} lost its exec bit"


def test_antigravity_guards_are_wired_to_the_tools_they_guard() -> None:
    wired = {
        (event, matcher, _agy_script(command).name)
        for event, matcher, command in _agy_registrations()
    }
    assert wired == {
        ("SessionStart", "", "session-context.sh"),
        ("PreToolUse", "run_command", "pipe-status-guard.sh"),
        ("PreToolUse", "run_command", "tea-guard.sh"),
        (
            "PreToolUse",
            (
                "write_file|edit_file|write_to_file|replace_file_content|"
                "multi_replace_file_content|sed_file"
            ),
            "decisions-status-guard.sh",
        ),
    }
    [dsg_matcher] = [
        matcher
        for _, matcher, name in wired
        if name == "decisions-status-guard.sh"
    ]
    assert set(dsg_matcher.split("|")) == hook_lib.ANTIGRAVITY_FILE_TOOLS


def _agy_probe(script: str, root: Path) -> dict[str, Any]:
    log = root / "docs" / "decisions.md"
    if script == "decisions-status-guard.sh":
        return {
            "hookEventName": "PreToolUse",
            "conversationId": "0000",
            "cwd": str(root),
            "toolCall": {
                "name": "edit_file",
                "args": {
                    "Path": str(log),
                    "Target": "**Status:** Proposed",
                    "Replacement": "**Status:** Accepted",
                },
            },
        }
    command = {
        "pipe-status-guard.sh": "make test | tail -5",
        "tea-guard.sh": "tea issues 1",
    }[script]
    return {
        "hookEventName": "PreToolUse",
        "conversationId": "0000",
        "cwd": str(root),
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": command},
        },
    }


def _run_agy_guard(
    command: str,
    root: Path,
    path_prefix: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    # Antigravity runs plugin hooks with cwd = <plugin-root>.
    decision = _run_guard_cmd(
        command,
        _ROOT,
        root,
        _agy_probe(_agy_script(command).name, root),
        path_prefix=path_prefix,
        extra_env=extra_env,
    )
    assert decision["decision"] == "deny", decision
    return decision


@pytest.mark.parametrize(("event", "matcher", "command"), _AGY_GUARDS)
def test_antigravity_registered_command_denies_end_to_end(
    event: str, matcher: str, command: str, tmp_path: Path
) -> None:
    _run_agy_guard(command, tmp_path)


@pytest.mark.parametrize(("event", "matcher", "command"), _AGY_GUARDS)
def test_antigravity_registered_command_ignores_a_hostile_python_environment(
    event: str,
    matcher: str,
    command: str,
    tmp_path: Path,
    hostile: tuple[dict[str, str], Path | None],
) -> None:
    # Same as the Claude registrations: none of these environments may
    # crash a guard open.
    env, prefix = hostile
    _run_agy_guard(command, tmp_path, prefix, env)


@pytest.mark.parametrize("version", ["3.8", "3.9", "3.10"])
@pytest.mark.parametrize(("event", "matcher", "command"), _AGY_GUARDS)
def test_antigravity_registered_command_holds_the_python_floor(
    event: str,
    matcher: str,
    command: str,
    version: str,
    tmp_path: Path,
    python3_dir: Callable[[str], Path],
) -> None:
    floor = f"need Python {hook_lib.FLOOR[0]}.{hook_lib.FLOOR[1]} or newer"
    reason = _run_agy_guard(command, tmp_path, python3_dir(version))["reason"]
    below = tuple(map(int, version.split("."))) < hook_lib.FLOOR
    assert (floor in reason) == below, reason


def test_antigravity_session_context_emits_inject_steps() -> None:
    [command] = [
        c
        for ev, _, c in _agy_registrations()
        if ev == "SessionStart" and _agy_script(c).name == "session-context.sh"
    ]
    result = subprocess.run(
        ["sh", "-c", command],
        cwd=_ROOT,
        input=json.dumps(_AGY_PAYLOADS["SessionStart"]),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    context = (_ROOT / "hooks" / "session-context.md").read_text(
        encoding="utf-8"
    )
    assert payload == {
        "injectSteps": [{"systemMessage": {"systemMessage": context}}]
    }


@pytest.mark.parametrize("python", ["venv", "3.10"])
@pytest.mark.parametrize("via", ["cwd", "PYTHONPATH"])
def test_session_context_python_never_imports_a_shadowing_json_py(
    tmp_path: Path,
    via: str,
    python: str,
    python3_dir: Callable[[str], Path],
) -> None:
    # Antigravity starts plugin hooks in the plugin root, so there the
    # exposure is PYTHONPATH. The working directory matters where a client
    # starts the hook in the session's directory and its payload holds one
    # of the two marker strings the hook switches on.
    #
    # The environment is built, not inherited, or the cwd case passes
    # without the flag: coverage's variable starts coverage in the venv's
    # python3 while `site` runs, which imports the stdlib json before the
    # working directory is on the path, and an ambient PYTHONSAFEPATH
    # keeps it off by itself. -I keeps it off by isolated mode at the 3.10
    # floor and by the -P it implies from 3.11, so both run.
    marker = tmp_path / "imported"
    (tmp_path / "json.py").write_text(
        f"open({str(marker)!r}, 'w').close()\n", encoding="utf-8"
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("COVERAGE_", "PYTHON"))
    }
    if python != "venv":
        env["PATH"] = os.pathsep.join([str(python3_dir(python)), env["PATH"]])
    if via == "PYTHONPATH":
        env["PYTHONPATH"] = str(tmp_path)
    result = subprocess.run(
        ["bash", str(_ROOT / "hooks" / "session-context.sh")],
        cwd=tmp_path if via == "cwd" else _ROOT,
        env=env,
        input=json.dumps(_AGY_PAYLOADS["SessionStart"]),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "injectSteps" in json.loads(result.stdout)
    assert not marker.exists()


def test_antigravity_session_start_below_floor_exits_quietly(
    python3_dir: Callable[[str], Path],
    tmp_path: Path,
) -> None:
    env = {
        **os.environ,
        "PATH": f"{python3_dir('3.9')}{os.pathsep}{os.environ['PATH']}",
        "CLAUDE_CODE_TMPDIR": str(tmp_path),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "config"),
    }
    result = subprocess.run(
        [str(_ROOT / "hooks" / "prune_session_tmp.py")],
        env=env,
        input=json.dumps(
            {"hookEventName": "SessionStart", "conversationId": "0000"}
        ),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert (result.returncode, result.stdout) == (0, ""), result.stderr
