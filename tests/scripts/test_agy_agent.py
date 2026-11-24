"""Behavioral pin for the pinned Antigravity bridge (``scripts/agy-agent.sh``).

Runs the real wrapper, copied into a throwaway kit layout under
``tmp_path``, against a fake ``agy`` and a throwaway git project. What it
refuses, and what it verifies from the ``stream-json`` ``init`` and
``result`` events, is what keeps a second-vendor review attributable. No
real ``agy``, no network, nothing written outside ``tmp_path``: PATH is a
farm of the few tools the wrapper needs.
"""

import json
import shutil
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
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
[ -f "$d/stderr" ] && cat "$d/stderr" >&2
exit "$(cat "$d/status")"
"""


def _stream(
    model: str | None = _MODEL,
    permission_mode: str = "request-review",
    status: str = "SUCCESS",
    response: str | None = _MESSAGE,
    tokens: int | None = 12345,
    include_init: bool = True,
    include_result: bool = True,
) -> str:
    lines: list[str] = []
    if include_init:
        init_body: dict[str, object] = {
            "cwd": "/repo",
            "tools": ["view_file", "grep_search"],
            "permission_mode": permission_mode,
        }
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
    env: dict[str, str]

    def run(
        self,
        *args: str,
        cwd: Path | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = {**self.env, **(extra_env or {})}
        return subprocess.run(
            ["bash", str(self.wrapper), *args],
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
    kit = tmp_path / "kit"
    (kit / "scripts").mkdir(parents=True)
    (kit / "agents").mkdir()
    wrapper = kit / "scripts" / "agy-agent.sh"
    shutil.copy2(_SCRIPT, wrapper)
    (kit / "agents" / "code-reviewer.md").write_text(_role(), encoding="utf-8")
    (kit / "agents" / "scout.md").write_text(_role(None), encoding="utf-8")

    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True, timeout=30)

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

    env = {
        "PATH": str(bin_dir),
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(xdg),
        "TMPDIR": str(tmp_path),
        "FAKE_AGY_DIR": str(fake),
    }
    return Bridge(wrapper, kit, project, prompt, opt_in, fake, bin_dir, env)


def test_verified_run_prints_response_and_tokens(bridge: Bridge) -> None:
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 0, res.stderr
    assert res.stdout == _MESSAGE
    assert "tokens used (normalised): 12345" in res.stderr
    assert "Pin verified" in res.stderr
    argv = bridge.argv()
    assert "--input-format" in argv and "stream-json" in argv
    assert "--output-format" in argv
    assert "--disable-slash-commands" in argv
    idx = argv.index("--model")
    assert argv[idx + 1] == _MODEL
    settings = json.loads(argv[argv.index("--settings") + 1])
    deny_rules = settings["permissions"]["deny"]
    assert "write_file(*)" in deny_rules
    assert "command(*)" in deny_rules
    assert "mcp(*)" in deny_rules
    assert settings["permissions"]["allow"] == ["read_file(*)"]
    ev = bridge.stdin_event()
    assert ev["event"] == "user"
    content = str(ev["message"]["content"])  # type: ignore[index]
    assert str(bridge.kit / "agents" / "code-reviewer.md") in content
    assert _PROMPT in content


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


def test_missing_opt_in_refuses_without_calling_agy(bridge: Bridge) -> None:
    bridge.opt_in.unlink()
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 2
    assert "not opted in" in res.stderr
    assert bridge.calls() == []


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


def test_missing_init_event_exits_3(bridge: Bridge) -> None:
    (bridge.fake / "stdout").write_text(
        _stream(include_init=False), encoding="utf-8"
    )
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 3
    assert res.stdout == ""
    assert "no init event" in res.stderr


def test_always_proceed_permission_mode_exits_3(bridge: Bridge) -> None:
    (bridge.fake / "stdout").write_text(
        _stream(permission_mode="always-proceed"), encoding="utf-8"
    )
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 3
    assert res.stdout == ""
    assert "always-proceed" in res.stderr


def test_non_success_result_exits_3(bridge: Bridge) -> None:
    (bridge.fake / "stdout").write_text(
        _stream(status="ERROR"), encoding="utf-8"
    )
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 3
    assert res.stdout == ""
    assert "not SUCCESS" in res.stderr


def test_empty_response_exits_3(bridge: Bridge) -> None:
    (bridge.fake / "stdout").write_text(
        _stream(response="   \n"), encoding="utf-8"
    )
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 3
    assert res.stdout == ""
    assert "empty response" in res.stderr


def test_missing_usage_reports_tokens_unavailable(bridge: Bridge) -> None:
    (bridge.fake / "stdout").write_text(_stream(tokens=None), encoding="utf-8")
    res = bridge.run("code-reviewer", str(bridge.prompt))
    assert res.returncode == 0
    assert "tokens unavailable; never estimate." in res.stderr


def test_transcript_is_saved_and_existing_path_refused(
    bridge: Bridge, tmp_path: Path
) -> None:
    transcript = tmp_path / "run.jsonl"
    res = bridge.run("code-reviewer", str(bridge.prompt), str(transcript))
    assert res.returncode == 0
    assert transcript.is_file()
    assert '"event": "init"' in transcript.read_text(encoding="utf-8")

    again = bridge.run("code-reviewer", str(bridge.prompt), str(transcript))
    assert again.returncode == 2
    assert "transcript path already exists" in again.stderr


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


def test_invalid_timeout_is_refused(bridge: Bridge) -> None:
    res = bridge.run(
        "code-reviewer",
        str(bridge.prompt),
        extra_env={"AGY_AGENT_TIMEOUT": "0"},
    )
    assert res.returncode == 2
    assert "AGY_AGENT_TIMEOUT" in res.stderr
    assert bridge.calls() == []


def test_sigterm_stops_child_process(bridge: Bridge) -> None:
    (bridge.fake / "sleep").write_text("30\n", encoding="utf-8")
    proc = subprocess.Popen(
        ["bash", str(bridge.wrapper), "code-reviewer", str(bridge.prompt)],
        cwd=bridge.project,
        env=bridge.env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    started = bridge.fake / "started"
    while not started.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert started.exists()
    proc.send_signal(signal.SIGTERM)
    proc.communicate(timeout=10)
    assert proc.returncode == 128 + signal.SIGTERM
    assert not (bridge.fake / "survived").exists()
