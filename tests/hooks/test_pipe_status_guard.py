"""Behavioral pin for the Bash pipe-status guard hook (``hooks/``).

Runs the real hook — the bash prefilter wrapper plus ``pipe_status_guard.py``
— as a subprocess with crafted tool JSON. Load-bearing like every hook's
pin: a crashed PreToolUse hook fails OPEN in the harness, so a broken guard
denies nothing and nothing else would notice.

The guard exists because ``make test | tail`` reports **tail's** exit status,
so a red gate reads as green — a trap that prose already named and that
kept happening anyway, twice in one session. The two halves worth pinning
are therefore symmetric: the traps are denied, and ordinary browsing is not
— an over-eager guard that blocks ``git log | head`` would simply be turned
off.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _ROOT / "hooks" / "pipe-status-guard.sh"


def _run_hook(command: str, shell: str = "/bin/zsh") -> str:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    result = subprocess.run(
        ["bash", str(_HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        env={**os.environ, "SHELL": shell},
    )
    return result.stdout


def _denied(command: str, shell: str = "/bin/zsh") -> bool:
    return '"permissionDecision": "deny"' in _run_hook(command, shell)


# --- a gate's status read through a pass-through filter ---------------------


def test_make_test_piped_to_tail_is_denied() -> None:
    assert _denied("make test | tail -5")


def test_pytest_piped_to_head_is_denied() -> None:
    assert _denied("pytest tests/ | head -20")


def test_repo_script_gate_piped_to_tail_is_denied() -> None:
    assert _denied("scripts/test.sh core | tail -3")


def test_gate_piped_to_tee_is_denied() -> None:
    # tee is pass-through too: its success says nothing about the gate.
    assert _denied("make lint | tee lint.log")


@pytest.mark.parametrize(
    "command",
    [
        "mvn verify | tail -20",
        "./mvnw -q test | tail -5",
        "gradle build | tail -5",
        "./gradlew check | head -40",
    ],
)
def test_jvm_build_gates_piped_to_a_filter_are_denied(command: str) -> None:
    assert _denied(command)


def test_jvm_build_gate_through_a_redirect_is_allowed() -> None:
    assert not _denied('./mvnw verify > build.log 2>&1; echo "EXIT=$?"')


def test_gate_behind_a_runner_is_denied() -> None:
    # effective_tool unwraps the runner, so hiding behind uv does not help.
    assert _denied("uv run pytest | tail -1")


# --- git commit / git push run gates --------------------------------------
#
# In a clone whose git hooks run gates, a refused commit or push is visible
# only in git's exit status. The subcommand decides: every other git
# subcommand is browsing and stays allowed.


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main | tail -3",
        "git push --force-with-lease | tail -3",
        "git commit -m 'x' | head -5",
        # Global options before the subcommand, with and without a value.
        "git -C /some/repo push | tail -2",
        "git -c core.pager=cat commit -am x | tee commit.log",
        "git --no-pager push origin HEAD | tail -1",
        # Every global option that takes its value as the NEXT word, so
        # the value is never mistaken for the subcommand.
        "git --git-dir x push | tail",
        "git --work-tree x push | tail",
        "git --namespace x push | tail",
        "git --super-prefix x push | tail",
        "git --config-env x=Y push | tail",
        "git --attr-source x push | tail",
        # Behind an assignment, a builtin and a precommand modifier.
        "GIT_DIR=x git push | tail",
        "command git push | tail",
        "sudo git push | tail",
    ],
)
def test_git_gate_subcommands_piped_to_a_filter_are_denied(
    command: str,
) -> None:
    assert _denied(command)


@pytest.mark.parametrize(
    "command",
    [
        "git log --oneline | head -5",
        "git show HEAD | head -40",
        "git status --short | tail -3",
        # `push`/`commit` as a VALUE, not the subcommand.
        "git -C push log | head -3",
        "git log --grep push | head -3",
        # `push` as a stash sub-subcommand: no hook runs.
        "git stash push | tail -3",
    ],
)
def test_other_git_subcommands_stay_browsing(command: str) -> None:
    assert not _denied(command)


def test_git_push_through_a_redirect_is_allowed() -> None:
    assert not _denied(
        'git push origin main > push.log 2>&1; echo "EXIT=$?"; tail -5 push.log'
    )


# --- status explicitly consumed, even by a non-gate -------------------------


def test_pipe_to_tail_followed_by_and_is_denied() -> None:
    assert _denied("./gradlew build | tail -2 && echo OK")


def test_pipe_to_tail_followed_by_or_is_denied() -> None:
    assert _denied("./gradlew build | tail -2 || echo FAILED")


def test_pipe_to_tail_then_reading_status_var_is_denied() -> None:
    assert _denied('./gradlew build | tail -2; echo "EXIT=$?"')


def test_denial_names_the_filter_and_the_real_command() -> None:
    out = _run_hook("make test | tail -5")
    assert "tail" in out
    assert "make" in out


# --- what must stay allowed -------------------------------------------------


def test_browsing_output_is_allowed() -> None:
    # No gate, no status consumed — the overwhelmingly common case.
    assert not _denied("git log --oneline | head -5")


def test_grep_predicate_is_allowed() -> None:
    # grep is a real predicate, not a pass-through: its status is precisely
    # what the caller is asking for.
    assert not _denied("cat build.log | grep -q ERROR && echo found")


def test_pipefail_is_allowed_in_both_shells() -> None:
    # `set -o pipefail` means the same thing in bash and zsh.
    cmd = "set -o pipefail; make test | tail -5"
    assert not _denied(cmd, shell="/bin/zsh")
    assert not _denied(cmd, shell="/bin/bash")


def test_mentioning_pipefail_is_not_opting_into_it() -> None:
    # The word in a grep pattern, a commit message or an echo is prose.
    for cmd in (
        "grep -rn pipefail .claude/rules/; make test | tail -5",
        'git commit -m "use set -o pipefail" && make test | tail -5',
        "echo pipe_fail; make test | tee out.log",
        "set +o pipefail; make test | tail -5",
        "make test | tail -5 # pipefail",
    ):
        for shell in ("/bin/zsh", "/bin/bash"):
            assert _denied(cmd, shell=shell), (cmd, shell)


def test_zsh_options_that_turn_pipefail_off_are_denied() -> None:
    for cmd in ("setopt no_pipe_fail", "unsetopt pipefail"):
        assert _denied(f"{cmd}; make test | tail -5", shell="/bin/zsh")


def test_set_option_clusters_and_scopes_opt_into_pipefail() -> None:
    for cmd in (
        "set -euo pipefail; make test | tail -5",
        "set -euxo pipefail; make test | tail -5",
        "set -o errexit -o pipefail; make test | tail -5",
        "(set -o pipefail; make test | tail -5)",
        "{ set -o pipefail; make test | tail -5; }",
        "set -o pipefail\nmake test | tail -5",
    ):
        for shell in ("/bin/zsh", "/bin/bash"):
            assert not _denied(cmd, shell=shell), (cmd, shell)


def test_set_forms_that_still_enable_pipefail_are_allowed() -> None:
    for cmd in (
        "time set -o pipefail; make test | tail -5",
        "builtin set -o pipefail; make test | tail -5",
        "X=1 set -o pipefail; make test | tail -5",
        "set +o pipefail -o pipefail; make test | tail -5",
        # The set line does not tokenize: unreadable, so never blocked.
        'set -o pipefail; echo "a\nb"\nmake test | tail -5',
    ):
        for shell in ("/bin/zsh", "/bin/bash"):
            assert not _denied(cmd, shell=shell), (cmd, shell)


def test_set_forms_that_leave_pipefail_off_are_denied() -> None:
    for cmd in (
        "set -- -o pipefail; make test | tail -5",
        "set x -o pipefail; make test | tail -5",
        'set "" -o pipefail; make test | tail -5',
        # zsh reads -oe as `-o e`; denied in bash too, conservatively.
        "set -oe pipefail; make test | tail -5",
        # Untokenizable line, but no pipefail mention: still denied.
        'echo "a\nb"\nmake test | tail -5',
    ):
        for shell in ("/bin/zsh", "/bin/bash"):
            assert _denied(cmd, shell=shell), (cmd, shell)


def test_setopt_is_not_a_bash_builtin() -> None:
    assert _denied("setopt pipefail; make test | tail -5", shell="/bin/bash")


def test_pipefail_opt_out_is_order_blind_by_decision() -> None:
    # Deliberate: any qualifying segment anywhere opts the whole command
    # out, even one that runs after the pipeline.
    cmd = "make test | tail -5; set -o pipefail"
    assert not _denied(cmd, shell="/bin/zsh")
    assert not _denied(cmd, shell="/bin/bash")


# --- the pipe-status array is spelled differently per shell -----------------
#
# Each array is silently EMPTY in the other shell, so the wrong spelling
# prints nothing and proves nothing while looking like a check. The guard is
# keyed to $SHELL, not written for one shell — these pin both directions.


def test_zsh_array_is_allowed_under_zsh() -> None:
    assert not _denied(
        'make test | tail -5; echo "${pipestatus[1]}"', shell="/bin/zsh"
    )


def test_bash_array_is_allowed_under_bash() -> None:
    assert not _denied(
        'make test | tail -5; echo "${PIPESTATUS[0]}"', shell="/bin/bash"
    )


def test_bash_array_under_zsh_is_denied() -> None:
    # The regression: this exact shape printed an empty PW_EXIT= during the
    # a review, and the guard's first version waved it through.
    assert _denied(
        'make test | tail -5; echo "${PIPESTATUS[0]}"', shell="/bin/zsh"
    )


def test_zsh_array_under_bash_is_denied() -> None:
    assert _denied(
        'make test | tail -5; echo "${pipestatus[1]}"', shell="/bin/bash"
    )


def test_zsh_braceless_subscript_is_allowed_under_zsh() -> None:
    # zsh subscripts without braces and does so idiomatically. This is a
    # fully correct check that the guard denied — the worst kind of miss,
    # since the denial pointed at the form already being used.
    assert not _denied(
        'make test | tail -5; echo "rc=$pipestatus[1]"', shell="/bin/zsh"
    )


def test_zsh_braceless_subscript_is_denied_under_bash() -> None:
    # bash has no lowercase `pipestatus` at all, braces or not.
    assert _denied(
        'make test | tail -5; echo "rc=$pipestatus[1]"', shell="/bin/bash"
    )


def test_reading_the_whole_array_is_allowed() -> None:
    # `$pipestatus` / `${PIPESTATUS[@]}` print every segment's status —
    # a genuine read, not a bare mention of the name.
    assert not _denied(
        'make test | tail -5; echo "all=$pipestatus"', shell="/bin/zsh"
    )
    assert not _denied(
        'make test | tail -5; echo "all=${PIPESTATUS[@]}"', shell="/bin/bash"
    )


def test_zsh_setopt_spelling_of_pipefail_is_allowed() -> None:
    # zsh option names ignore case and underscores, so `setopt PIPE_FAIL`
    # is the same request as `set -o pipefail` and must not be denied.
    for cmd in ("setopt PIPE_FAIL", "setopt pipe_fail", "setopt pipefail"):
        assert not _denied(f"{cmd}; make test | tail -5", shell="/bin/zsh")


def test_explicitly_invoking_the_other_shell_is_allowed() -> None:
    # `bash -c '… ${PIPESTATUS[0]}'` really does run under bash.
    assert not _denied(
        "bash -c 'make test | tail -5; echo \"${PIPESTATUS[0]}\"'",
        shell="/bin/zsh",
    )


def test_unknown_shell_disables_the_array_arm() -> None:
    # Fail open on a shell we have no spelling for; the pass-through rule
    # below is shell-agnostic and still applies.
    assert not _denied(
        'make test | tail -5; echo "${PIPESTATUS[0]}"', shell="/usr/bin/fish"
    )


def test_naming_the_array_without_dereferencing_is_not_a_claim() -> None:
    # A grep pattern mentioning PIPESTATUS is not an attempt to check it.
    assert not _denied("grep -rn PIPESTATUS scripts/", shell="/bin/zsh")


def test_redirect_then_check_is_allowed() -> None:
    # The form the denial message recommends must itself pass.
    assert not _denied('make test > out.log 2>&1; echo "EXIT=$?"')


def test_gate_without_a_pipe_is_allowed() -> None:
    assert not _denied("make test")


def test_status_var_belonging_to_an_earlier_command_is_allowed() -> None:
    # Regression: `$?` here reports the push, not the browsing pipeline that
    # follows it. Scanning the whole command for `$?` (rather than only the
    # pipeline that immediately consumes it) denied this real command.
    assert not _denied(
        'git push origin main > push.log 2>&1; echo "EXIT=$?"; '
        "git status -sb | head -1"
    )


def test_status_var_read_by_the_very_next_pipeline_is_still_denied() -> None:
    # The narrowing above must not blind the guard to the real case.
    assert _denied('make test | tail -3; echo "EXIT=$?"')


def test_heredoc_body_is_data_not_commands() -> None:
    # Regression: a commit message *about* this rule contains the very
    # pipeline it forbids. Heredoc bodies must never be tokenized — this
    # exact command was denied when they were.
    assert not _denied(
        "git commit -F - <<'EOF'\n"
        "tooling: explain the pipe rule\n\n"
        'Never write `make test | tail -3; echo "EXIT=$?"` — it reads\n'
        "tail's status. Use ${PIPESTATUS[0]} instead.\n"
        "EOF"
    )


def test_a_real_pipeline_after_a_heredoc_is_still_denied() -> None:
    # Skipping the body must not skip what follows the terminator.
    assert _denied(
        "git commit -F - <<'EOF'\nsome message\nEOF\nmake test | tail -5"
    )


def test_a_here_string_does_not_swallow_the_rest() -> None:
    # `<<<` is a here-string — a one-line argument, not a heredoc, in both
    # shells. The heredoc regex matched at its second `<`, took `data` for
    # a delimiter no later line equals, and dropped everything after it:
    # one here-string anywhere blinded the guard for the whole command.
    assert _denied("grep -c x <<< 'data'\nmake test | tail -5")


# --- precommand modifiers: the command word is not the command --------------
#
# `time`/`command`/`builtin`/`exec` are shell keywords or builtins in both
# shells; `noglob`/`nocorrect` are zsh's own. All of them merely stand in
# front of the real command, and a gate hidden behind one was invisible.


def test_gate_behind_a_shell_keyword_is_denied() -> None:
    assert _denied("time make test | tail -5")
    assert _denied("command make test | tail -5")


def test_gate_behind_a_zsh_precommand_modifier_is_denied() -> None:
    assert _denied("noglob make test | tail -5")
    assert _denied("nocorrect make test | tail -5")


def test_gate_behind_a_prefix_program_is_denied() -> None:
    assert _denied("sudo make test | tail -5")
    assert _denied("nice -n 10 make test | tail -5")
    assert _denied("env FOO=1 make test | tail -5")


def test_unbalanced_quotes_fail_open() -> None:
    # An unparseable command is never blocked (every hook here fails open).
    assert not _denied("make test | tail -5 'unclosed")
