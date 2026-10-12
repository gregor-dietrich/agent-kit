"""Behavioral pin for the pinned Codex bridge (``scripts/codex-agent.sh``).

Runs the real wrapper, copied into a throwaway kit layout under
``tmp_path``, against a fake ``codex`` and a throwaway git project. The
bridge exists because ``codex exec`` has no agent selector, so a hand-built
call silently runs the default model; what it refuses, and what it
verifies from the session banner, is what keeps a second-vendor review
attributable. No real codex, no network, nothing written outside
``tmp_path``: PATH is a farm of the few tools the wrapper needs, so a
codex installed on the machine can never answer.
"""

import os
import shutil
import signal
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "codex-agent.sh"
_FIXTURE = (
    Path(__file__).parent / "fixtures" / "codex_exec_stderr_0.160.0.txt"
)
_TOOLS = (
    "bash", "cat", "dirname", "git", "grep", "awk", "mktemp", "rm", "sleep",
)
# Optional, as in the wrapper: GNU coreutils' bound, absent on a stock macOS.
_BOUND = shutil.which("timeout") or shutil.which("gtimeout")
_PIN = {
    "codex-model": "gpt-test",
    "codex-effort": "high",
    "codex-sandbox": "read-only",
}
_OPT_IN = "<!-- agent-kit:codex-bridge -->"
_MESSAGE = "the final message\n"
_PROMPT = "Review the diff.\n"

# Answers --version from a file, records every call, its argv (NUL
# separated) and stdin, writes the -o file and, as real codex does, the
# same final message on stdout, emits the canned stderr and exits with the
# canned status. With a `sleep` file it marks itself started, sleeps, and
# marks itself a survivor if nothing stopped it.
_FAKE_CODEX = """#!{bash}
d="$FAKE_CODEX_DIR"
printf '%s\\n' "$*" >> "$d/calls"
if [ "$1" = --version ]; then cat "$d/version"; exit 0; fi
printf '%s\\0' "$@" > "$d/argv"
cat > "$d/stdin"
if [ -f "$d/sleep" ]; then
    : > "$d/started"
    sleep "$(cat "$d/sleep")"
    : > "$d/survived"
    exit 0
fi
while [ $# -gt 0 ]; do
    [ "$1" = -o ] && [ -f "$d/message" ] && cat "$d/message" > "$2"
    shift
done
[ -f "$d/message" ] && cat "$d/message"
cat "$d/stderr" >&2
exit "$(cat "$d/status")"
"""


def _banner(
    model: str = "gpt-test",
    effort: str | None = "high",
    sandbox: str = "read-only",
    provider: str = "openai",
    approval: str = "never",
) -> str:
    effort_line = "" if effort is None else f"reasoning effort: {effort}\n"
    return (
        "OpenAI Codex v0.160.0\n--------\nworkdir: /tmp/project\n"
        f"model: {model}\nprovider: {provider}\napproval: {approval}\n"
        f"sandbox: {sandbox}\n{effort_line}"
        "reasoning summaries: none\nsession id: 0\n--------\n"
        "user\nReview the diff.\ncodex\nLooks fine.\n"
    )


def _role(pin: dict[str, str | None], body: str = "Body.\n") -> str:
    lines = [f"{k}: {v}" for k, v in pin.items() if v is not None]
    return "\n".join(["---", "name: x", "model: opus", *lines, "---", body])


@dataclass
class Bridge:
    kit: Path
    project: Path
    fake: Path
    tmp: Path
    env: dict[str, str]

    @property
    def calls(self) -> list[str]:
        log = self.fake / "calls"
        return log.read_text().splitlines() if log.exists() else []

    @property
    def argv(self) -> list[str]:
        return (self.fake / "argv").read_text().split("\0")[:-1]

    @property
    def dispatched(self) -> bool:
        return (self.fake / "argv").exists()

    def stderr(self, text: str) -> None:
        (self.fake / "stderr").write_text(text, encoding="utf-8")

    def role(self, text: str) -> None:
        (self.kit / "agents" / "code-reviewer.md").write_text(text)

    def unbound(self) -> None:
        """Drops `timeout`/`gtimeout` from the PATH farm."""
        if _BOUND:
            (self.project.parent / "tools" / Path(_BOUND).name).unlink()

    @property
    def prompt(self) -> str:
        return str(self.project / "prompt.md")

    def _argv(self, args: list[str] | None) -> list[str]:
        argv = ["code-reviewer", self.prompt] if args is None else args
        return [str(self.kit / "scripts" / "codex-agent.sh"), *argv]

    def run(
        self,
        args: list[str] | None = None,
        cwd: Path | None = None,
        **env: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self._argv(args),
            cwd=cwd or self.project,
            env={**self.env, **env},
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=60,
        )

    def start(self) -> subprocess.Popen[str]:
        return subprocess.Popen(
            self._argv(None),
            cwd=self.project,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )


@pytest.fixture
def bridge(tmp_path: Path) -> Bridge:
    tmp_path = tmp_path.resolve()
    tools = tmp_path / "tools"
    tools.mkdir()
    for tool in _TOOLS:
        found = shutil.which(tool)
        assert found, f"test needs {tool} on PATH"
        (tools / tool).symlink_to(found)
    if _BOUND:
        (tools / Path(_BOUND).name).symlink_to(_BOUND)
    fake_bin, fake = tmp_path / "fake-bin", tmp_path / "fake"
    fake_bin.mkdir()
    fake.mkdir()
    codex = fake_bin / "codex"
    codex.write_text(_FAKE_CODEX.format(bash=shutil.which("bash")))
    codex.chmod(0o755)
    (fake / "version").write_text("codex-cli 0.160.0\n")
    (fake / "message").write_text(_MESSAGE)
    (fake / "status").write_text("0\n")
    (fake / "stderr").write_text(_banner() + "tokens used\n1,234\n")

    kit = tmp_path / "kit"
    (kit / "scripts").mkdir(parents=True)
    (kit / "agents").mkdir()
    shutil.copy2(_SCRIPT, kit / "scripts" / _SCRIPT.name)
    (kit / "agents" / "code-reviewer.md").write_text(_role(dict(_PIN)))

    (tmp_path / "home").mkdir()
    (tmp_path / "tmp").mkdir()
    env = {
        "PATH": f"{fake_bin}{os.pathsep}{tools}",
        "HOME": str(tmp_path / "home"),
        "TMPDIR": str(tmp_path / "tmp"),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
        "FAKE_CODEX_DIR": str(fake),
    }
    project = tmp_path / "project"
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "init", "-q", str(project)],
        env=env,
        check=True,
        timeout=30,
    )
    (project / "AGENTS.md").write_text(f"# Project\n\n{_OPT_IN}\n")
    (project / "prompt.md").write_text(_PROMPT)
    return Bridge(kit, project, fake, tmp_path / "tmp", env)


# --- a verified run -----------------------------------------------------


def test_verified_run_passes_the_pin_and_prints_the_message(
    bridge: Bridge,
) -> None:
    (bridge.project / "sub").mkdir()
    result = bridge.run(cwd=bridge.project / "sub")
    assert result.returncode == 0, result.stderr
    # Once: codex's own stdout copy is discarded, the -o file printed.
    assert result.stdout == _MESSAGE
    argv = bridge.argv
    assert argv[0] == "exec"
    assert argv[-1] == "-"
    pairs = list(zip(argv, argv[1:]))
    assert ("--cd", str(bridge.project)) in pairs
    assert ("--color", "never") in pairs
    assert ("-m", "gpt-test") in pairs
    assert ("-c", "model_reasoning_effort=high") in pairs
    assert ("--sandbox", "read-only") in pairs
    assert "--ignore-user-config" in argv
    assert "-o" in argv
    stdin = (bridge.fake / "stdin").read_text()
    role_file = bridge.kit / "agents" / "code-reviewer.md"
    assert stdin.startswith(
        f"Your role instructions are in {role_file}; read it in full. "
        "Its model: and tools: frontmatter is Claude-only"
    )
    assert "you have a read-only shell for reading files" in stdin
    assert "you MUST NOT run builds, tests" in stdin
    assert stdin.endswith("tracker state.\n\n" + _PROMPT)
    assert "Pin verified" in result.stderr
    assert not any(bridge.tmp.iterdir()), "temp dir left behind"


def test_the_captured_0_160_0_banner_parses_and_verifies(
    bridge: Bridge,
) -> None:
    bridge.role(
        _role(
            {
                "codex-model": "gpt-6.1-sol",
                "codex-effort": "xhigh",
                "codex-sandbox": "read-only",
            }
        )
    )
    shutil.copyfile(_FIXTURE, bridge.fake / "stderr")
    result = bridge.run()
    assert result.returncode == 0, result.stderr
    assert result.stdout == _MESSAGE
    assert "tokens used (raw): 2,990" in result.stderr
    assert "tokens used (normalised): 2990" in result.stderr


def test_transcript_receives_codex_stderr_privately(bridge: Bridge) -> None:
    transcript = bridge.project.parent / "transcript.log"
    result = bridge.run(["code-reviewer", bridge.prompt, str(transcript)])
    assert result.returncode == 0, result.stderr
    assert transcript.read_text() == (bridge.fake / "stderr").read_text()
    assert stat.S_IMODE(transcript.stat().st_mode) == 0o600


def test_codex_stderr_is_never_mirrored(bridge: Bridge) -> None:
    # It carries the answer too: only the transcript may hold it.
    transcript = bridge.project.parent / "transcript.log"
    result = bridge.run(["code-reviewer", bridge.prompt, str(transcript)])
    assert result.returncode == 0, result.stderr
    for line in ("OpenAI Codex v0.160.0", "Looks fine.", "session id: 0"):
        assert line not in result.stderr
        assert line in transcript.read_text()


def test_without_a_bound_the_run_says_so_and_still_verifies(
    bridge: Bridge,
) -> None:
    bridge.unbound()
    result = bridge.run()
    assert result.returncode == 0, result.stderr
    assert "NOTE: no timeout (nor gtimeout) on PATH" in result.stderr
    assert bridge.argv[0] == "exec"
    assert result.stdout == _MESSAGE


# --- the pin is verified, not assumed -----------------------------------


@pytest.mark.parametrize(
    ("field", "banner"),
    [
        ("model", _banner(model="gpt-default")),
        ("reasoning effort", _banner(effort="medium")),
        ("sandbox", _banner(sandbox="workspace-write")),
        ("provider", _banner(provider="proxy")),
        ("approval", _banner(approval="on-request")),
    ],
)
def test_a_banner_mismatch_exits_3(
    bridge: Bridge, field: str, banner: str
) -> None:
    bridge.stderr(banner)
    result = bridge.run()
    assert result.returncode == 3
    assert f"pin mismatch on {field}: expected" in result.stderr
    assert "actual '" in result.stderr
    # The fake printed the message on its stdout; none of it gets out.
    assert result.stdout == ""


def test_an_absent_banner_key_is_reported_as_absent(bridge: Bridge) -> None:
    bridge.stderr(_banner(effort=None))
    result = bridge.run()
    assert result.returncode == 3
    assert "pin mismatch on reasoning effort" in result.stderr
    assert "actual '<absent>'" in result.stderr
    assert result.stdout == ""


def test_an_absent_banner_exits_3(bridge: Bridge) -> None:
    bridge.stderr("codex\nLooks fine.\ntokens used\n1,234\n")
    result = bridge.run()
    assert result.returncode == 3
    assert "no codex session banner" in result.stderr
    assert result.stdout == ""


def test_only_the_first_banner_counts(bridge: Bridge) -> None:
    # An echoed block later in the stream cannot vouch for the run.
    echoed = "--------\nmodel: gpt-test\n--------\n"
    bridge.stderr(_banner(model="gpt-default") + echoed)
    result = bridge.run()
    assert result.returncode == 3
    assert "actual 'gpt-default'" in result.stderr
    assert result.stdout == ""


def test_an_unclosed_banner_does_not_count(bridge: Bridge) -> None:
    opened = _banner().split("--------\n")
    bridge.stderr("--------\n".join(opened[:2]) + "tokens used\n1,234\n")
    result = bridge.run()
    assert result.returncode == 3
    assert "no codex session banner" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("message", [None, ""])
def test_codex_exit_0_without_an_answer_exits_3(
    bridge: Bridge, message: str | None
) -> None:
    path = bridge.fake / "message"
    if message is None:
        path.unlink()
    else:
        path.write_text(message)
    result = bridge.run()
    assert result.returncode == 3
    assert "returned no answer" in result.stderr
    assert "this stage did not happen" in result.stderr
    assert result.stdout == ""


def test_codex_failure_status_passes_through(bridge: Bridge) -> None:
    (bridge.fake / "status").write_text("7\n")
    result = bridge.run()
    assert result.returncode == 7
    assert "codex exec exited 7" in result.stderr
    assert "codex stderr:" not in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("how", "status"), [("failure", 7), ("mismatch", 3), ("no answer", 3)]
)
def test_an_error_after_codex_ran_names_the_transcript(
    bridge: Bridge, how: str, status: int
) -> None:
    if how == "failure":
        (bridge.fake / "status").write_text("7\n")
    elif how == "mismatch":
        bridge.stderr(_banner(model="gpt-default"))
    else:
        (bridge.fake / "message").unlink()
    transcript = bridge.project.parent / "transcript.log"
    result = bridge.run(["code-reviewer", bridge.prompt, str(transcript)])
    assert result.returncode == status
    assert f"codex stderr: {transcript}\n" in result.stderr
    assert result.stdout == ""


@pytest.mark.skipif(not _BOUND, reason="no timeout/gtimeout on PATH")
def test_the_wall_clock_bound_exits_124(bridge: Bridge) -> None:
    (bridge.fake / "sleep").write_text("30")
    result = bridge.run(CODEX_AGENT_TIMEOUT="1")
    assert result.returncode == 124
    assert "1-second bound" in result.stderr


@pytest.mark.parametrize("bounded", [True, False])
def test_a_terminated_wrapper_takes_codex_with_it(
    bridge: Bridge, bounded: bool
) -> None:
    if bounded and not _BOUND:
        pytest.skip("no timeout/gtimeout on PATH")
    if not bounded:
        bridge.unbound()
    (bridge.fake / "sleep").write_text("2")
    proc = bridge.start()
    deadline = time.monotonic() + 30
    while not (bridge.fake / "started").exists():
        assert proc.poll() is None and time.monotonic() < deadline
        time.sleep(0.05)
    started = time.monotonic()
    proc.send_signal(signal.SIGTERM)
    stdout, _ = proc.communicate(timeout=30)
    assert proc.returncode == 128 + signal.SIGTERM
    assert stdout == ""
    time.sleep(max(0.0, started + 3 - time.monotonic()))
    assert not (bridge.fake / "survived").exists(), "codex outlived it"


# --- tokens: reported, never estimated ----------------------------------


@pytest.mark.parametrize("locale", ["C", "C.UTF-8"])
@pytest.mark.parametrize(
    "figure", ["1,234", "1.234", "1 234", "1 234"]
)
def test_token_figure_is_normalised(
    bridge: Bridge, figure: str, locale: str
) -> None:
    bridge.stderr(_banner() + f"tokens used\n{figure}\n")
    result = bridge.run(LC_ALL=locale)
    assert result.returncode == 0, result.stderr
    assert f"tokens used (raw): {figure}\n" in result.stderr
    assert "tokens used (normalised): 1234\n" in result.stderr


def test_the_final_token_marker_wins(bridge: Bridge) -> None:
    # codex echoes files the agent reads; an earlier marker may be docs.
    bridge.stderr(
        _banner() + "tokens used\n5\nmore output\ntokens used\n1,234\n\n"
    )
    result = bridge.run()
    assert result.returncode == 0, result.stderr
    assert "tokens used (normalised): 1234\n" in result.stderr
    assert "normalised): 5" not in result.stderr


def test_a_token_marker_the_run_went_past_is_not_a_figure(
    bridge: Bridge,
) -> None:
    bridge.stderr(_banner() + "tokens used\n1,234\nERROR: stream lost\n")
    result = bridge.run()
    assert result.returncode == 0, result.stderr
    assert "tokens unavailable; never estimate" in result.stderr
    assert "normalised" not in result.stderr


def test_a_token_line_that_is_no_figure_is_shown_not_guessed(
    bridge: Bridge,
) -> None:
    bridge.stderr(_banner() + "tokens used\nmany\n")
    result = bridge.run()
    assert result.returncode == 0, result.stderr
    assert "tokens unavailable; never estimate" in result.stderr
    assert "  (not a figure: many)\n" in result.stderr


def test_tokens_are_reported_on_a_failed_run(bridge: Bridge) -> None:
    (bridge.fake / "status").write_text("7\n")
    result = bridge.run()
    assert result.returncode == 7
    assert "tokens used (normalised): 1234\n" in result.stderr


def test_no_token_marker_is_reported_and_does_not_fail(
    bridge: Bridge,
) -> None:
    bridge.stderr(_banner())
    result = bridge.run()
    assert result.returncode == 0, result.stderr
    assert "tokens unavailable; never estimate" in result.stderr
    assert result.stdout == _MESSAGE


# --- refusals: codex is never called ------------------------------------


@pytest.mark.parametrize(
    "agents_md",
    [
        None,
        "# Project\n\nNo bridge here.\n",
        "Never add agent-kit:codex-bridge here.\n",
        "<!-- agent-kit:codex-bridge-disabled -->\n",
        f"Opted in: {_OPT_IN}\n",
        f" {_OPT_IN}\n",
    ],
)
def test_a_project_not_opted_in_is_refused(
    bridge: Bridge, agents_md: str | None
) -> None:
    target = bridge.project / "AGENTS.md"
    if agents_md is None:
        target.unlink()
    else:
        target.write_text(agents_md)
    result = bridge.run()
    assert result.returncode == 2
    assert _OPT_IN in result.stderr
    assert str(target) in result.stderr
    assert bridge.calls == []


def test_a_symlinked_agents_md_does_not_opt_in(bridge: Bridge) -> None:
    target = bridge.project / "AGENTS.md"
    elsewhere = bridge.project.parent / "AGENTS.md"
    target.rename(elsewhere)
    target.symlink_to(elsewhere)
    result = bridge.run()
    assert result.returncode == 2
    assert "not opted in" in result.stderr
    assert bridge.calls == []


@pytest.mark.parametrize(
    "agents_md",
    [f"# P\n\n{_OPT_IN}\n", f"# P\r\n\r\n{_OPT_IN}\r\n", f"# P\n{_OPT_IN}"],
)
def test_the_exact_opt_in_line_is_accepted(
    bridge: Bridge, agents_md: str
) -> None:
    (bridge.project / "AGENTS.md").write_bytes(agents_md.encode())
    result = bridge.run()
    assert result.returncode == 0, result.stderr


def test_outside_a_git_repository_is_refused(bridge: Bridge) -> None:
    elsewhere = bridge.project.parent / "elsewhere"
    elsewhere.mkdir()
    result = bridge.run(cwd=elsewhere)
    assert result.returncode == 2
    assert "git repository" in result.stderr
    assert bridge.calls == []


@pytest.mark.parametrize(
    "role",
    ["nope", "../agents/code-reviewer", "agents/code-reviewer", "..", ""],
)
def test_an_unknown_or_path_like_role_is_refused(
    bridge: Bridge, role: str
) -> None:
    result = bridge.run([role, bridge.prompt])
    assert result.returncode == 2
    assert "unknown role" in result.stderr
    assert bridge.calls == []


@pytest.mark.parametrize("key", list(_PIN))
@pytest.mark.parametrize("how", ["missing", "empty", "only in the body"])
def test_a_missing_pin_key_is_refused_by_name(
    bridge: Bridge, key: str, how: str
) -> None:
    pin: dict[str, str | None] = {
        **_PIN, key: "" if how == "empty" else None
    }
    body = f"{key}: {_PIN[key]}\n" if how == "only in the body" else "B.\n"
    bridge.role(_role(pin, body))
    result = bridge.run()
    assert result.returncode == 2
    assert key in result.stderr
    assert bridge.calls == []


@pytest.mark.parametrize(
    "value",
    ['"gpt-test"', "'gpt-test'", "gpt-test # pinned", "gpt test", "gpt\ttest"],
)
def test_a_quoted_or_commented_pin_value_is_refused(
    bridge: Bridge, value: str
) -> None:
    bridge.role(_role({**_PIN, "codex-model": value}))
    result = bridge.run()
    assert result.returncode == 2
    assert "codex-model" in result.stderr
    assert "write it bare" in result.stderr
    assert bridge.calls == []


@pytest.mark.parametrize("prefix", ["\n", "# Title\n", " "])
def test_a_role_file_not_opening_with_frontmatter_is_refused(
    bridge: Bridge, prefix: str
) -> None:
    bridge.role(prefix + _role(dict(_PIN)))
    result = bridge.run()
    assert result.returncode == 2
    assert "no frontmatter" in result.stderr
    assert bridge.calls == []


def test_a_sandbox_other_than_read_only_is_refused(bridge: Bridge) -> None:
    bridge.role(_role({**_PIN, "codex-sandbox": "workspace-write"}))
    result = bridge.run()
    assert result.returncode == 2
    assert "no preamble for this sandbox yet" in result.stderr
    assert bridge.calls == []


def test_codex_missing_from_path_is_refused(bridge: Bridge) -> None:
    result = bridge.run(PATH=str(bridge.project.parent / "tools"))
    assert result.returncode == 2
    assert "not on PATH" in result.stderr


@pytest.mark.parametrize(
    ("version", "status"),
    [
        ("codex-cli 0.159.2", 2),
        ("codex-cli 0.159.9", 2),
        ("codex-cli 0.160.0", 0),
        ("codex-cli 0.160.1", 0),
        ("codex-cli 1.0.0", 0),
        ("codex-cli dev", 2),
    ],
)
def test_the_version_floor(bridge: Bridge, version: str, status: int) -> None:
    (bridge.fake / "version").write_text(version + "\n")
    result = bridge.run()
    assert result.returncode == status, result.stderr
    assert bridge.dispatched == (status == 0)


@pytest.mark.parametrize("prompt", [None, ""])
def test_a_missing_or_empty_prompt_file_is_refused(
    bridge: Bridge, prompt: str | None
) -> None:
    path = Path(bridge.prompt)
    if prompt is None:
        path.unlink()
    else:
        path.write_text(prompt)
    result = bridge.run()
    assert result.returncode == 2
    assert "prompt file" in result.stderr
    assert bridge.calls == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_an_unreadable_prompt_file_is_refused(bridge: Bridge) -> None:
    Path(bridge.prompt).chmod(0)
    result = bridge.run()
    assert result.returncode == 2
    assert "missing or unreadable" in result.stderr
    assert bridge.calls == []


@pytest.mark.parametrize("kind", ["file", "dangling symlink", "the prompt"])
def test_an_existing_transcript_path_is_refused(
    bridge: Bridge, kind: str
) -> None:
    transcript = bridge.project.parent / "transcript.log"
    if kind == "file":
        transcript.write_text("keep me\n")
    elif kind == "dangling symlink":
        transcript.symlink_to(bridge.project.parent / "nowhere")
    else:
        transcript = Path(bridge.prompt)
    result = bridge.run(["code-reviewer", bridge.prompt, str(transcript)])
    assert result.returncode == 2
    assert "transcript path already exists" in result.stderr
    assert bridge.calls == []
    assert Path(bridge.prompt).read_text() == _PROMPT
    assert kind != "file" or transcript.read_text() == "keep me\n"
    assert not (bridge.project.parent / "nowhere").exists()


def test_an_unwritable_transcript_path_is_refused(bridge: Bridge) -> None:
    transcript = bridge.project.parent / "no-such-dir" / "transcript.log"
    result = bridge.run(["code-reviewer", bridge.prompt, str(transcript)])
    assert result.returncode == 2
    assert "transcript path is not writable" in result.stderr
    assert not bridge.dispatched


@pytest.mark.parametrize("count", [0, 1, 4])
def test_a_wrong_argument_count_is_refused(
    bridge: Bridge, count: int
) -> None:
    args = ["code-reviewer", bridge.prompt, "transcript.log", "extra"]
    result = bridge.run(args[:count])
    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert bridge.calls == []


@pytest.mark.parametrize("value", ["0", "2h", "-5", "abc", "1.5"])
def test_a_bad_timeout_is_refused(bridge: Bridge, value: str) -> None:
    result = bridge.run(CODEX_AGENT_TIMEOUT=value)
    assert result.returncode == 2
    assert "CODEX_AGENT_TIMEOUT" in result.stderr
    assert bridge.calls == []


# --- the shipped pin and the skill's path to it -------------------------


def test_the_shipped_code_reviewer_carries_a_read_only_pin() -> None:
    lines = (_ROOT / "agents" / "code-reviewer.md").read_text().splitlines()
    assert lines[0] == "---"
    frontmatter = lines[1 : lines.index("---", 1)]
    pin = dict(
        line.split(": ", 1) for line in frontmatter if line.startswith("codex-")
    )
    assert set(pin) == set(_PIN)
    assert all(value.strip() for value in pin.values())
    assert pin["codex-sandbox"] == "read-only"


def test_the_skill_reaches_the_shipped_bridge() -> None:
    # ai-review runs the bridge relative to its own base directory.
    skill = _ROOT / "skills" / "ai-review"
    assert "<base>/../../scripts/codex-agent.sh" in (
        skill / "SKILL.md"
    ).read_text()
    target = skill / ".." / ".." / "scripts" / "codex-agent.sh"
    assert target.is_file()
    assert os.access(target, os.X_OK)
