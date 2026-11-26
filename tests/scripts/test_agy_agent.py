"""Behavioral pin for the pinned Antigravity bridge (``scripts/agy-agent.sh``).

Runs the real wrapper, copied into a throwaway kit layout under
``tmp_path``, against a fake ``agy`` and a throwaway git project. What it
refuses, and what it verifies from the ``stream-json`` ``init`` and
``result`` events, is what keeps a second-vendor review attributable. No
real ``agy``, no network, nothing written outside ``tmp_path``: PATH is a
farm of the few tools the wrapper needs.
"""

import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "agy-agent.sh"
_FIXTURE = Path(__file__).parent / "fixtures" / "agy_stream_json_1.5.16.jsonl"
_TOOLS = (
    "awk",
    "bash",
    "cat",
    "dirname",
    "git",
    "mktemp",
    "rm",
    "sleep",
)
_BOUND = shutil.which("timeout") or shutil.which("gtimeout")
_MODEL = "gemini-test-xhigh"
_MESSAGE = "the final message\n"
_PROMPT = "Review the diff.\n"
_DEFAULT = object()
_REDISPATCH = "Discard the result and re-dispatch."
_NO_REDISPATCH = "Do not re-dispatch"

_FAKE_AGY = """#!{bash}
d="$FAKE_AGY_DIR"
printf '%s\\n' "$*" >> "$d/calls"
if [ "$1" = --version ]; then cat "$d/version"; exit 0; fi
printf '%s\\0' "$@" > "$d/argv"
pwd -P > "$d/cwd"
cat > "$d/stdin"
if [ -f "$d/sleep" ]; then
    : > "$d/started"
    sleep "$(cat "$d/sleep")"
    : > "$d/survived"
    exit 0
fi
cat "$d/stdout"
if [ -f "$d/linger" ]; then
    : > "$d/started"
    sleep "$(cat "$d/linger")"
    : > "$d/survived"
    exit 0
fi
[ -f "$d/stderr" ] && cat "$d/stderr" >&2
exit "$(cat "$d/status")"
"""


def _stream(
    model: str | None = _MODEL,
    permission_mode: str | None = "request-review",
    tools: object = _DEFAULT,
    status: str = "SUCCESS",
    response: str | None = _MESSAGE,
    tokens: int | None = 12345,
    include_init: bool = True,
    include_result: bool = True,
) -> str:
    lines: list[str] = []
    if include_init:
        init_body: dict[str, object] = {"cwd": "/repo"}
        if tools is _DEFAULT:
            init_body["tools"] = ["view_file", "grep_search"]
        elif tools is not None:
            init_body["tools"] = tools
        if permission_mode is not None:
            init_body["permission_mode"] = permission_mode
        if model is not None:
            init_body["model"] = model
        lines.append(
            json.dumps(
                {
                    "event": "init",
                    "conversation_id": "0000",
                    "init": init_body,
                }
            )
        )
    if include_result:
        res_body: dict[str, object] = {
            "conversation_id": "0000",
            "status": status,
        }
        if response is not None:
            res_body["response"] = response
        if tokens is not None:
            res_body["usage"] = {"total_tokens": tokens}
        lines.append(json.dumps({"event": "result", "result": res_body}))
    return "\n".join(lines) + ("\n" if lines else "")


def _role(agy_model: str | None = _MODEL, body: str = "Body.\n") -> str:
    lines = ["---", "name: x", "model: inherit"]
    if agy_model is not None:
        lines.append(f"agy-model: {agy_model}")
    lines.extend(["---", body])
    return "\n".join(lines)


@dataclass
class Bridge:
    wrapper: Path
    kit: Path
    project: Path
    prompt: Path
    opt_in: Path
    fake: Path
    bin_dir: Path
    tmp_dir: Path
    env: dict[str, str]

    def run(
        self,
        *args: str,
        cwd: Path | None = None,
        extra_env: dict[str, str | None] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = dict(self.env)
        if extra_env:
            for key, val in extra_env.items():
                if val is None:
                    env.pop(key, None)
                else:
                    env[key] = val
        return subprocess.run(
            [str(self.wrapper), *args],
            cwd=cwd or self.project,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def calls(self) -> list[str]:
        path = self.fake / "calls"
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8").splitlines()

    def argv(self) -> list[str]:
        raw = (self.fake / "argv").read_text(encoding="utf-8")
        return raw.rstrip("\0").split("\0")

    def stdin_event(self) -> dict[str, object]:
        return json.loads((self.fake / "stdin").read_text(encoding="utf-8"))


@pytest.fixture
def bridge(tmp_path: Path) -> Bridge:
    tmp_path = tmp_path.resolve()
    kit = tmp_path / "kit"
    (kit / "scripts").mkdir(parents=True)
    (kit / "agents").mkdir()
    wrapper = kit / "scripts" / "agy-agent.sh"
    shutil.copy2(_SCRIPT, wrapper)
    (kit / "agents" / "code-reviewer.md").write_text(_role(), encoding="utf-8")
    (kit / "agents" / "scout.md").write_text(_role(None), encoding="utf-8")

    prompt = tmp_path / "prompt.md"
    prompt.write_text(_PROMPT, encoding="utf-8")

    xdg = tmp_path / "xdg"
    opt_in = xdg / "agent-kit" / "agy-bridge"
    opt_in.parent.mkdir(parents=True)
    opt_in.touch()

    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "version").write_text("1.5.16\n", encoding="utf-8")
    (fake / "stdout").write_text(_stream(), encoding="utf-8")
    (fake / "status").write_text("0\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in _TOOLS:
        found = shutil.which(tool)
        assert found, f"missing required tool on PATH: {tool}"
        (bin_dir / tool).symlink_to(found)
    if _BOUND:
        (bin_dir / Path(_BOUND).name).symlink_to(_BOUND)
    (bin_dir / "python3").symlink_to(sys.executable)

    agy_bin = bin_dir / "agy"
    agy_bin.write_text(
        _FAKE_AGY.format(bash=shutil.which("bash")), encoding="utf-8"
    )
    agy_bin.chmod(agy_bin.stat().st_mode | stat.S_IXUSR)

    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()

    env = {
        "PATH": str(bin_dir),
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(xdg),
        "TMPDIR": str(tmp_dir),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
        "FAKE_AGY_DIR": str(fake),
    }

    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "init", "-q"],
        cwd=project,
        env=env,
        check=True,
        timeout=30,
    )
    return Bridge(
        wrapper, kit, project, prompt, opt_in, fake, bin_dir, tmp_dir, env
    )


def test_verified_run_prints_response_and_tokens(bridge: Bridge) -> None:
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 0, res.stderr
    assert res.stdout == _MESSAGE
    assert "tokens used (normalised): 12345" in res.stderr
    assert "Pin verified" in res.stderr
    argv = bridge.argv()
    pairs = list(pairwise(argv))
    assert ("--input-format", "stream-json") in pairs
    assert ("--output-format", "stream-json") in pairs
    assert ("--model", _MODEL) in pairs
    assert ("--print-timeout", "7200s") in pairs
    assert "--sandbox" in argv
    assert "--disable-slash-commands" in argv
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert settings["permissions"]["allow"] == ["read_file(*)"]
    assert set(settings["permissions"]["deny"]) == {
        "write_file(*)",
        "command(*)",
        "mcp(*)",
        "read_url(*)",
        "execute_url(*)",
        "download_url(*)",
    }
    ev = bridge.stdin_event()
    assert ev["event"] == "user"
    content = str(ev["message"]["content"])  # type: ignore[index]
    assert str(bridge.kit / "agents" / "code-reviewer.md") in content
    assert _PROMPT in content
    assert not any(bridge.tmp_dir.iterdir())


def test_real_stream_json_fixture_verifies(bridge: Bridge) -> None:
    (bridge.kit / "agents" / "code-reviewer.md").write_text(
        _role("gemini-4-neon-xhigh"), encoding="utf-8"
    )
    (bridge.fake / "stdout").write_text(
        _FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 0, res.stderr
    assert res.stdout == "No verified findings.\n"
    assert "tokens used (normalised): 11574" in res.stderr


def test_shipped_code_reviewer_pin_verifies(bridge: Bridge) -> None:
    shipped = _ROOT / "agents" / "code-reviewer.md"
    shutil.copy2(shipped, bridge.kit / "agents" / "code-reviewer.md")
    pin_model = next(
        line.split(": ", 1)[1].strip()
        for line in shipped.read_text(encoding="utf-8").splitlines()
        if line.startswith("agy-model:")
    )
    (bridge.fake / "stdout").write_text(
        _stream(model=pin_model), encoding="utf-8"
    )
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 0, res.stderr
    assert res.stdout == _MESSAGE
    assert ("--model", pin_model) in list(pairwise(bridge.argv()))
    assert "--sandbox" in bridge.argv()


@pytest.mark.parametrize(
    "role_name",
    sorted(
        p.stem
        for p in (_ROOT / "agents").glob("*.md")
        if p.stem != "code-reviewer"
    ),
)
def test_shipped_roles_without_agy_model_are_refused(
    bridge: Bridge, role_name: str
) -> None:
    shutil.copy2(
        _ROOT / "agents" / f"{role_name}.md",
        bridge.kit / "agents" / f"{role_name}.md",
    )
    res = bridge.run(role_name, str(bridge.prompt))
    assert res.returncode == 2
    assert "no agy-model key" in res.stderr
    assert bridge.calls() == []


def test_skill_references_executable_agy_bridge() -> None:
    skill_md = _ROOT / "skills" / "ai-review" / "SKILL.md"
    assert "<base>/../../scripts/agy-agent.sh" in skill_md.read_text(
        encoding="utf-8"
    )
    assert _SCRIPT.is_file()
    assert os.access(_SCRIPT, os.X_OK)


def test_missing_opt_in_refuses_without_calling_agy(bridge: Bridge) -> None:
    bridge.opt_in.unlink()
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 2
    assert "not opted in" in res.stderr
    assert bridge.calls() == []


def test_relative_xdg_config_home_does_not_grant_consent(
    bridge: Bridge,
) -> None:
    bridge.opt_in.unlink()
    rel = bridge.project / "rel-xdg" / "agent-kit"
    rel.mkdir(parents=True)
    (rel / "agy-bridge").touch()
    res = bridge.run(
        "code-reviewer",
        str(bridge.prompt),
        extra_env={"XDG_CONFIG_HOME": "rel-xdg"},
    )
    assert res.returncode == 2
    assert "not opted in" in res.stderr
    assert bridge.calls() == []


@pytest.mark.parametrize("xdg_val", [None, "rel-xdg"])
def test_home_config_fallback_for_unset_or_relative_xdg(
    bridge: Bridge, xdg_val: str | None
) -> None:
    bridge.opt_in.unlink()
    home_opt_in = Path(bridge.env["HOME"]) / ".config" / "agent-kit"
    home_opt_in.mkdir(parents=True)
    (home_opt_in / "agy-bridge").touch()
    res = bridge.run(
        "code-reviewer",
        str(bridge.prompt),
        extra_env={"XDG_CONFIG_HOME": xdg_val},
    )
    assert res.returncode == 0, res.stderr
    assert res.stdout == _MESSAGE


@pytest.mark.parametrize(
    "rel_path",
    [
        ".agents/hooks.json",
        ".agent/mcp_config.json",
        "_agents/plugins.json",
        "_agent/plugins/",
    ],
)
def test_repo_local_config_is_refused(bridge: Bridge, rel_path: str) -> None:
    target = bridge.project / rel_path
    if rel_path.endswith("/"):
        target.mkdir(parents=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}\n", encoding="utf-8")
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 2
    assert rel_path in res.stderr
    assert "AGY_AGENT_ALLOW_REPO_CONFIG=1" in res.stderr
    assert bridge.calls() == []


def test_allow_repo_config_env_permits_verified_run(bridge: Bridge) -> None:
    cfg = bridge.project / ".agents" / "hooks.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("{}\n", encoding="utf-8")
    (bridge.project / "_agent" / "plugins").mkdir(parents=True)
    res = bridge.run(
        "code-reviewer",
        str(bridge.prompt),
        extra_env={"AGY_AGENT_ALLOW_REPO_CONFIG": "1"},
    )
    assert res.returncode == 0, res.stderr
    assert res.stdout == _MESSAGE


def test_role_without_agy_model_is_refused(bridge: Bridge) -> None:
    res = bridge.run("scout", str(bridge.prompt))
    assert res.returncode == 2
    assert "no agy-model key" in res.stderr
    assert bridge.calls() == []


@pytest.mark.parametrize(
    "bad_role", ["nope", "../agents/code-reviewer", "agents/code-reviewer", ""]
)
def test_unknown_or_traversal_role_is_refused(
    bridge: Bridge, bad_role: str
) -> None:
    res = bridge.run(bad_role, str(bridge.prompt))
    assert res.returncode == 2
    assert "unknown role" in res.stderr
    assert bridge.calls() == []


@pytest.mark.parametrize(
    "bad_pin",
    [
        '"gemini-test"',
        "'gemini-test'",
        "gemini-test # comment",
        "gemini test",
    ],
)
def test_quoted_or_commented_agy_model_refused(
    bridge: Bridge, bad_pin: str
) -> None:
    (bridge.kit / "agents" / "code-reviewer.md").write_text(
        _role(bad_pin), encoding="utf-8"
    )
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 2
    assert "write it bare" in res.stderr
    assert bridge.calls() == []


def test_below_version_floor_is_refused(bridge: Bridge) -> None:
    (bridge.fake / "version").write_text("1.5.15\n", encoding="utf-8")
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 2
    assert "agy >= 1.5.16" in res.stderr
    assert bridge.calls() == ["--version"]


def test_model_mismatch_exits_3_and_discards_response(bridge: Bridge) -> None:
    (bridge.fake / "stdout").write_text(
        _stream(model="gemini-wrong"), encoding="utf-8"
    )
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 3
    assert res.stdout == ""
    assert "pin mismatch on model" in res.stderr
    assert _NO_REDISPATCH in res.stderr
    assert _REDISPATCH not in res.stderr


def test_missing_init_event_exits_3(bridge: Bridge) -> None:
    (bridge.fake / "stdout").write_text(
        _stream(include_init=False), encoding="utf-8"
    )
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 3
    assert res.stdout == ""
    assert "no init event" in res.stderr
    assert _REDISPATCH in res.stderr


def test_duplicate_init_event_exits_3(bridge: Bridge) -> None:
    init_only = _stream(include_result=False)
    (bridge.fake / "stdout").write_text(init_only + _stream(), encoding="utf-8")
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 3
    assert res.stdout == ""
    assert "init event count" in res.stderr
    assert _REDISPATCH in res.stderr


@pytest.mark.parametrize(
    "perm_mode", [None, "auto", "accept-edits", "always-proceed"]
)
def test_unexpected_permission_mode_exits_3(
    bridge: Bridge, perm_mode: str | None
) -> None:
    (bridge.fake / "stdout").write_text(
        _stream(permission_mode=perm_mode), encoding="utf-8"
    )
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 3
    assert res.stdout == ""
    assert "permission_mode" in res.stderr
    if perm_mode is not None:
        assert perm_mode in res.stderr
    assert _NO_REDISPATCH in res.stderr
    assert _REDISPATCH not in res.stderr


@pytest.mark.parametrize(
    "bad_tools",
    [
        None,
        [],
        ["run_command"],
        ["write_file"],
        ["view_file", "search_web"],
    ],
)
def test_unexpected_init_tools_exits_3(
    bridge: Bridge, bad_tools: list[str] | None
) -> None:
    (bridge.fake / "stdout").write_text(
        _stream(tools=bad_tools), encoding="utf-8"
    )
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 3
    assert res.stdout == ""
    assert "unexpected tools" in res.stderr
    assert _NO_REDISPATCH in res.stderr
    assert _REDISPATCH not in res.stderr


def test_missing_result_event_exits_3(bridge: Bridge) -> None:
    (bridge.fake / "stdout").write_text(
        _stream(include_result=False), encoding="utf-8"
    )
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 3
    assert res.stdout == ""
    assert "no result event" in res.stderr
    assert _REDISPATCH in res.stderr


def test_duplicate_result_event_exits_3(bridge: Bridge) -> None:
    err_res = _stream(include_init=False, status="ERROR")
    (bridge.fake / "stdout").write_text(_stream() + err_res, encoding="utf-8")
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 3
    assert res.stdout == ""
    assert "result event count" in res.stderr
    assert _REDISPATCH in res.stderr


def test_non_success_result_exits_3(bridge: Bridge) -> None:
    (bridge.fake / "stdout").write_text(
        _stream(status="ERROR"), encoding="utf-8"
    )
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 3
    assert res.stdout == ""
    assert "not SUCCESS" in res.stderr
    assert _REDISPATCH in res.stderr


def test_empty_response_exits_3(bridge: Bridge) -> None:
    (bridge.fake / "stdout").write_text(
        _stream(response="   \n"), encoding="utf-8"
    )
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 3
    assert res.stdout == ""
    assert "empty response" in res.stderr
    assert _REDISPATCH in res.stderr


def test_missing_usage_reports_tokens_unavailable(bridge: Bridge) -> None:
    (bridge.fake / "stdout").write_text(_stream(tokens=None), encoding="utf-8")
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 0
    assert "tokens unavailable; never estimate." in res.stderr


def test_non_utf8_prompt_encodes_with_replacement(bridge: Bridge) -> None:
    bridge.prompt.write_bytes(b"Review bytes: \xff\xfe end\n")
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 0, res.stderr
    assert res.stdout == _MESSAGE
    content = str(bridge.stdin_event()["message"]["content"])  # type: ignore[index]
    assert "\ufffd" in content


def test_pre_dispatch_encoding_failure_leaves_no_transcript(
    bridge: Bridge, tmp_path: Path
) -> None:
    py = bridge.bin_dir / "python3"
    py.unlink()
    py.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    py.chmod(0o755)
    transcript = tmp_path / "no-leak.jsonl"
    res = bridge.run("code-reviewer", str(bridge.prompt), str(transcript))
    assert res.returncode == 2
    assert "failed to encode prompt file" in res.stderr
    assert not transcript.exists()
    assert not transcript.is_symlink()
    assert bridge.calls() == ["--version"]
    assert not (bridge.fake / "argv").exists()


@pytest.mark.parametrize(
    ("agy_status", "model", "expected_code"),
    [("7", _MODEL, 7), ("0", "gemini-wrong", 3)],
)
def test_failure_surfaces_bounded_stderr_and_transcript(
    bridge: Bridge,
    tmp_path: Path,
    agy_status: str,
    model: str,
    expected_code: int,
) -> None:
    diag = "".join(f"diag-line-{i}\n" for i in range(1, 26))
    (bridge.fake / "stderr").write_text(diag, encoding="utf-8")
    (bridge.fake / "status").write_text(f"{agy_status}\n", encoding="utf-8")
    (bridge.fake / "stdout").write_text(_stream(model=model), encoding="utf-8")
    transcript = tmp_path / "run.jsonl"
    res = bridge.run("code-reviewer", str(bridge.prompt), str(transcript))
    assert res.returncode == expected_code
    assert res.stdout == ""
    assert "diag-line-1\n" in res.stderr
    assert "diag-line-20\n" in res.stderr
    assert "diag-line-21\n" not in res.stderr
    assert f"agy transcript: {transcript}" in res.stderr


def test_success_does_not_leak_agy_stderr(bridge: Bridge) -> None:
    (bridge.fake / "stderr").write_text("quiet-on-success\n", encoding="utf-8")
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 0, res.stderr
    assert "quiet-on-success" not in res.stderr


def test_transcript_is_saved_with_private_mode(
    bridge: Bridge, tmp_path: Path
) -> None:
    transcript = tmp_path / "run.jsonl"
    res = bridge.run("code-reviewer", str(bridge.prompt), str(transcript))
    assert res.returncode == 0
    assert transcript.is_file()
    assert stat.S_IMODE(transcript.stat().st_mode) == 0o600
    assert '"event": "init"' in transcript.read_text(encoding="utf-8")


@pytest.mark.parametrize("kind", ["file", "dangling", "prompt"])
def test_existing_transcript_path_is_refused(
    bridge: Bridge, tmp_path: Path, kind: str
) -> None:
    target = tmp_path / "dangling-target"
    transcript = tmp_path / "existing.jsonl"
    if kind == "file":
        transcript.write_text("keep\n", encoding="utf-8")
    elif kind == "dangling":
        transcript.symlink_to(target)
    else:
        transcript = bridge.prompt
    res = bridge.run("code-reviewer", str(bridge.prompt), str(transcript))
    assert res.returncode == 2
    assert "transcript path already exists" in res.stderr
    assert bridge.calls() == []
    assert bridge.prompt.read_text(encoding="utf-8") == _PROMPT
    assert not target.exists()


def test_relative_transcript_resolves_against_caller_cwd(
    bridge: Bridge,
) -> None:
    sub = bridge.project / "nested"
    sub.mkdir()
    res = bridge.run("code-reviewer", str(bridge.prompt), "out.jsonl", cwd=sub)
    assert res.returncode == 0, res.stderr
    assert (sub / "out.jsonl").is_file()
    assert Path((bridge.fake / "cwd").read_text(encoding="utf-8").strip()) == (
        bridge.project.resolve()
    )


def test_cdpath_cannot_redirect_kit_root(
    bridge: Bridge, tmp_path: Path
) -> None:
    decoy = tmp_path / "decoy"
    (decoy / "scripts").mkdir(parents=True)
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "init", "-q"],
        cwd=bridge.kit,
        env=bridge.env,
        check=True,
        timeout=30,
    )
    res = subprocess.run(
        ["scripts/agy-agent.sh", "code-reviewer", str(bridge.prompt)],
        cwd=bridge.kit,
        env={**bridge.env, "CDPATH": str(decoy)},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert res.returncode == 0, res.stderr
    role_file = bridge.kit / "agents" / "code-reviewer.md"
    content = str(bridge.stdin_event()["message"]["content"])  # type: ignore[index]
    assert f"instructions are in {role_file};" in content


@pytest.mark.skipif(not _BOUND, reason="no timeout/gtimeout on PATH")
def test_wall_clock_timeout_exits_124(bridge: Bridge) -> None:
    (bridge.fake / "sleep").write_text("30\n", encoding="utf-8")
    res = bridge.run(
        "code-reviewer",
        str(bridge.prompt),
        extra_env={"AGY_AGENT_TIMEOUT": "1"},
    )
    assert res.returncode == 124
    assert "1-second bound" in res.stderr


def test_without_timeout_binary_still_succeeds(bridge: Bridge) -> None:
    if _BOUND:
        (bridge.bin_dir / Path(_BOUND).name).unlink()
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 0, res.stderr
    assert res.stdout == _MESSAGE


@pytest.mark.parametrize("bad_timeout", ["0", "2h", "-5"])
def test_invalid_timeout_is_refused(bridge: Bridge, bad_timeout: str) -> None:
    res = bridge.run(
        "code-reviewer",
        str(bridge.prompt),
        extra_env={"AGY_AGENT_TIMEOUT": bad_timeout},
    )
    assert res.returncode == 2
    assert "AGY_AGENT_TIMEOUT" in res.stderr
    assert bridge.calls() == []


@pytest.mark.parametrize("count", [0, 1, 4])
def test_wrong_arg_count_is_refused(bridge: Bridge, count: int) -> None:
    args = ["code-reviewer", str(bridge.prompt), "out.jsonl", "extra"]
    res = bridge.run(*args[:count])
    assert res.returncode == 2
    assert "usage:" in res.stderr
    assert bridge.calls() == []


@pytest.mark.parametrize("content", [None, ""])
def test_missing_or_empty_prompt_is_refused(
    bridge: Bridge, content: str | None
) -> None:
    if content is None:
        bridge.prompt.unlink()
    else:
        bridge.prompt.write_text(content, encoding="utf-8")
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 2
    assert "prompt file" in res.stderr
    assert bridge.calls() == []


@pytest.mark.parametrize("binary", ["agy", "python3"])
def test_missing_required_binary_is_refused(
    bridge: Bridge, binary: str
) -> None:
    (bridge.bin_dir / binary).unlink()
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 2
    assert "not installed" in res.stderr
    assert bridge.calls() == []


def test_outside_git_repo_is_refused(bridge: Bridge, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    res = bridge.run("code-reviewer", str(bridge.prompt), cwd=outside)
    assert res.returncode == 2
    assert "git repository" in res.stderr
    assert bridge.calls() == []


def _unbound(bridge: Bridge, bounded: bool) -> None:
    """Run with (bounded) or without the external timeout binary."""
    if bounded and not _BOUND:
        pytest.skip("no timeout/gtimeout on PATH")
    if not bounded and _BOUND:
        (bridge.bin_dir / Path(_BOUND).name).unlink()


def _spawn(bridge: Bridge) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [str(bridge.wrapper), "code-reviewer", str(bridge.prompt)],
        cwd=bridge.project,
        env=bridge.env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


@pytest.mark.parametrize("bounded", [True, False])
def test_sigterm_stops_child_process(bridge: Bridge, bounded: bool) -> None:
    _unbound(bridge, bounded)
    (bridge.fake / "sleep").write_text("2\n", encoding="utf-8")
    proc = _spawn(bridge)
    deadline = time.monotonic() + 30
    started = bridge.fake / "started"
    while not started.exists():
        assert proc.poll() is None and time.monotonic() < deadline
        time.sleep(0.05)
    sent_at = time.monotonic()
    proc.terminate()
    out, _ = proc.communicate(timeout=30)
    assert (proc.returncode, out) == (128 + signal.SIGTERM, "")
    remaining = sent_at + 3.0 - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)
    assert not (bridge.fake / "survived").exists()


def _watcher_pids(root: Path) -> list[int]:
    """Pids whose command line names a path under ``root``, as /proc shows."""
    needle = str(root).encode()
    pids = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if needle in cmdline:
            pids.append(int(entry.name))
    return pids


def _assert_no_leftover(bridge: Bridge) -> None:
    """No process names this test's temp dir (the watcher's arguments do).

    The scan is proven by a control process that does name it.
    """
    if not Path("/proc/self/cmdline").exists():
        pytest.skip("no /proc")
    control = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
            str(bridge.tmp_dir),
        ]
    )
    try:
        time.sleep(0.2)
        assert _watcher_pids(bridge.tmp_dir) == [control.pid]
    finally:
        control.kill()
        control.wait()
    time.sleep(0.2)
    assert _watcher_pids(bridge.tmp_dir) == []


@pytest.mark.parametrize("bounded", [True, False])
@pytest.mark.parametrize(
    "bad_stream, expected",
    [
        (_stream(model="gemini-wrong", include_result=False), "pin mismatch"),
        (
            _stream(permission_mode="auto", include_result=False),
            "unexpected permission_mode 'auto'",
        ),
        (
            _stream(tools=["run_command"], include_result=False),
            "unexpected tools in init event",
        ),
    ],
)
def test_init_mismatch_stops_agy_early(
    bridge: Bridge, bounded: bool, bad_stream: str, expected: str
) -> None:
    _unbound(bridge, bounded)
    (bridge.fake / "stdout").write_text(bad_stream, encoding="utf-8")
    (bridge.fake / "linger").write_text("30\n", encoding="utf-8")
    start = time.monotonic()
    res = bridge.run("code-reviewer", str(bridge.prompt))
    # The wrapper waits for agy, so returning well inside the 30-second
    # linger is the proof that agy was stopped.
    assert time.monotonic() - start < 10
    assert res.returncode == 3, res.stderr
    assert res.stdout == ""
    assert f"ERROR: {expected}" in res.stderr
    assert "Stopped agy at its init event" in res.stderr
    assert _NO_REDISPATCH in res.stderr
    assert "installed agy (1.5.16)" in res.stderr
    assert _REDISPATCH not in res.stderr
    assert (bridge.fake / "started").exists()
    _assert_no_leftover(bridge)


def test_init_mismatch_early_stop_names_transcript(
    bridge: Bridge, tmp_path: Path
) -> None:
    (bridge.fake / "stdout").write_text(
        _stream(model="gemini-wrong", include_result=False), encoding="utf-8"
    )
    (bridge.fake / "linger").write_text("30\n", encoding="utf-8")
    transcript = tmp_path / "early.jsonl"
    res = bridge.run("code-reviewer", str(bridge.prompt), str(transcript))
    assert res.returncode == 3, res.stderr
    assert f"agy transcript: {transcript}" in res.stderr
    assert '"event": "init"' in transcript.read_text(encoding="utf-8")


def test_valid_init_is_not_stopped(bridge: Bridge) -> None:
    (bridge.fake / "stdout").write_text(
        _stream(include_result=False), encoding="utf-8"
    )
    (bridge.fake / "linger").write_text("1\n", encoding="utf-8")
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 3, res.stderr
    assert (bridge.fake / "survived").exists()
    assert "no result event" in res.stderr
    assert _REDISPATCH in res.stderr
    assert "Stopped agy" not in res.stderr
    _assert_no_leftover(bridge)


@pytest.mark.parametrize("version", ["1.5.17", "1.6.0", "2.0.0"])
def test_newer_agy_runs_with_notice(bridge: Bridge, version: str) -> None:
    (bridge.fake / "version").write_text(f"{version}\n", encoding="utf-8")
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 0, res.stderr
    assert res.stdout == _MESSAGE
    assert f"NOTE: agy {version} is newer than 1.5.16," in res.stderr
    assert res.stderr.index("NOTE:") < res.stderr.index("Dispatching")


def test_measured_version_has_no_notice(bridge: Bridge) -> None:
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 0, res.stderr
    assert "NOTE:" not in res.stderr


def test_verified_run_leaves_no_watcher(bridge: Bridge) -> None:
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 0, res.stderr
    _assert_no_leftover(bridge)


@pytest.mark.parametrize("bounded", [True, False])
def test_sigterm_leaves_no_watcher(bridge: Bridge, bounded: bool) -> None:
    _unbound(bridge, bounded)
    (bridge.fake / "stdout").write_text(
        _stream(include_result=False), encoding="utf-8"
    )
    (bridge.fake / "linger").write_text("20\n", encoding="utf-8")
    proc = _spawn(bridge)
    deadline = time.monotonic() + 30
    while not (bridge.fake / "started").exists():
        assert proc.poll() is None and time.monotonic() < deadline
        time.sleep(0.05)
    proc.terminate()
    proc.communicate(timeout=30)
    assert proc.returncode == 128 + signal.SIGTERM
    _assert_no_leftover(bridge)
