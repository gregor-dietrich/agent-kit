#!/usr/bin/env bash

# Dispatch one agent-kit role that carries an Antigravity bridge model pin to
# `agy` headlessly, pinned and read-only, and prove afterwards that the pin
# actually took.
#
# `agy` headless runs default to whatever model the user selected last, and a
# hand-built call does not prove the requested model ran or lock permissions
# read-only. So this wrapper reads `agy-model` from `agents/<role>.md` (never
# a copy kept here), passes `--sandbox`, `--disable-slash-commands`,
# `--print-timeout`, and an inline `--settings` JSON object that allows
# `read_file(*)` and denies writes, shell commands, MCP tools and URL fetches,
# streams the prompt via `--input-format stream-json` (avoiding ARG_MAX on
# large diffs), and VERIFIES the `stream-json` `init` and `result` events.
#
# Verification requires exactly one `init` and one `result` event: `init.model`
# must equal the pin, `init.permission_mode` must equal `request-review`,
# every `step_update` must be a plain step (`user_input`, `system_message`,
# `agent_response`) or a `read_file` tool step, and `result` must report
# `status: "SUCCESS"` and a non-empty `response`. A run violating any check
# exits 3 rather than handing back an unverified answer. `init.tools` is the
# CLI's whole registry on 1.5.18, whatever the settings say, and is not read.
# The `init` content and every step are checked as they arrive, by a watcher
# beside `agy`: a mismatch gets `agy` a SIGTERM before it spends more. The
# checks always run again over the whole stream once `agy` has exited, and a
# run the watcher stopped exits 3 whatever they find. The accepted limit: the
# settings deny writes and shell commands, but web search and subagent tools
# cannot be denied by settings on 1.5.18, so such a call is detected at its
# `ACTIVE` line and the run rejected, after the call may have started. An
# event the bridge does not know is ignored.
#
# Before dispatching, this wrapper scans the target repository for repo-local
# executable Antigravity configs under `.agents`, `.agent`, `_agents`, `_agent`
# (`hooks.json`, `mcp_config.json`, `plugins.json`, `plugins/`) and refuses
# (exit 2) unless `AGY_AGENT_ALLOW_REPO_CONFIG=1` is set after reviewing them.
# Residual limitation: `agy 1.5.18` has no `--ignore-user-config` flag, so
# user-level Antigravity settings remain active.
#
# The user opts in, with one file that covers every project, by creating
# ${XDG_CONFIG_HOME:-$HOME/.config}/agent-kit/agy-bridge (a relative
# XDG_CONFIG_HOME is ignored per the XDG Base Directory Spec); its content is
# not read. Without it, `agy` is never called: the file is the user's consent
# to send the review prompt, and whatever `agy` chooses to read, to a second
# vendor. It lives outside every checkout, so no branch can grant it.
#
# The stream-json `init`, `step_update`, `result` and `usage` shapes parsed
# below were measured on the Antigravity CLI version named by MEASURED_VERSION
# below; MIN_VERSION is the floor.
#
# Usage:
#   agy-agent.sh <role> <prompt-file> [<transcript-file>]
#
# Run from anywhere inside the target project; its git top level is the
# directory `agy` works in. <role> names `agents/<role>.md` beside this script
# and must carry an `agy-model` pin: a role without one is not a bridge role
# and is refused. <prompt-file> holds the dispatch prompt; a fixed read-only
# preamble pointing `agy` at the role file goes before it. The final message
# of a verified run is printed on stdout; this wrapper's own status lines go
# to stderr. <transcript-file>, a path that must not exist yet, keeps `agy`'s
# raw `stream-json` output, and an ERROR raised after `agy` ran names it.
#
# Exit status:
#   0    the run finished, `init` verified the pin, `agy` answered
#   2    usage error, failed precondition, user not opted in, repo-local
#        configs refused, or a pin key missing/malformed; `agy` did not run
#   3    the pin could not be verified (`init` absent, duplicated or
#        mismatched), permissions were unexpected, a step was outside the
#        read-only set, or `agy` returned no valid answer: discard. A
#        mismatched `init` content, an out-of-set step, and a run the
#        watcher stopped, take precedence over `agy`'s own status. A
#        permission mismatch recurs until the bridge or the CLI changes, so
#        do not re-dispatch it; a model mismatch or an out-of-set step may
#        not.
#   124  the wall-clock bound stopped the run; 137 it had to be killed
#   128+n  this wrapper got signal n (HUP, INT, TERM) and stopped `agy`
#   else `agy`'s own status, when `agy` itself failed
#
# Environment:
#   AGY_AGENT_TIMEOUT           bounds one dispatch in whole seconds (default
#                               7200), passed to `agy --print-timeout` and,
#                               when GNU `timeout` (`gtimeout`) is on PATH,
#                               also enforced externally.
#   AGY_AGENT_ALLOW_REPO_CONFIG set to 1 to allow repo-local Antigravity
#                               configs after confirming them.
#
# Portable down to bash 3.2 (stock macOS): no mapfile, no case-folding
# expansions, no associative arrays.

set -euo pipefail

USAGE='usage: agy-agent.sh <role> <prompt-file> [<transcript-file>]'
if [[ "${XDG_CONFIG_HOME:-}" == /* ]]; then
	CONFIG_HOME="$XDG_CONFIG_HOME"
else
	CONFIG_HOME="${HOME:-}/.config"
fi
OPT_IN="$CONFIG_HOME/agent-kit/agy-bridge"
MIN_VERSION='1.5.18'
# The newest version the stream-json shapes were measured on.
MEASURED_VERSION='1.5.18'
SETTINGS='{"permissions":{"allow":["read_file(*)"],"deny":["write_file(*)","command(*)","mcp(*)","read_url(*)","execute_url(*)","download_url(*)"]}}'

# One ERROR line, then any further arguments as indented continuations.
die() {
	printf 'ERROR: %s\n' "$1" >&2
	shift
	[[ $# -eq 0 ]] || printf '  %s\n' "$@" >&2
	exit 2
}

[[ $# -ge 2 && $# -le 3 ]] || die "$USAGE"
ROLE="$1"
PROMPT_FILE="$2"
TRANSCRIPT="${3:-}"

KIT="$(CDPATH='' cd -L -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -L)"
ROLE_FILE="$KIT/agents/$ROLE.md"

# Validated before the existence check, so no name walks out of agents/.
if [[ ! "$ROLE" =~ ^[a-z][a-z0-9-]*$ || ! -f "$ROLE_FILE" ]]; then
	die "unknown role: $ROLE (no $KIT/agents/<role>.md by that name)"
fi

if [[ ! -f "$PROMPT_FILE" || ! -r "$PROMPT_FILE" ]]; then
	die "prompt file is missing or unreadable: $PROMPT_FILE"
elif [[ ! -s "$PROMPT_FILE" ]]; then
	die "prompt file is empty: $PROMPT_FILE" \
		'An empty prompt still dispatches, and still bills.'
fi

# A fresh path only: an existing one would be truncated, or followed when
# a symlink, and the prompt itself would be emptied before it is read.
if [[ -n "$TRANSCRIPT" && (-e "$TRANSCRIPT" || -L "$TRANSCRIPT") ]]; then
	die "transcript path already exists: $TRANSCRIPT" \
		'Pass a path that does not exist yet.'
fi

TIMEOUT_SECONDS="${AGY_AGENT_TIMEOUT:-7200}"
if [[ ! "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
	die "AGY_AGENT_TIMEOUT must be a positive whole number of seconds;" \
		"got \"$TIMEOUT_SECONDS\"."
fi

ROOT="$(git rev-parse --show-toplevel 2> /dev/null)" ||
	die 'not inside a git repository; run from the target project.'

if [[ "$CONFIG_HOME" != /* || ! -f "$OPT_IN" ]]; then
	die "not opted in: $OPT_IN does not exist. Antigravity was not called." \
		'Create that file to let every project send reviews to Antigravity.'
fi

if [[ "${AGY_AGENT_ALLOW_REPO_CONFIG:-}" != "1" ]]; then
	REPO_CONFIGS=()
	for cfg_dir in .agents .agent _agents _agent; do
		for cfg_file in hooks.json mcp_config.json plugins.json; do
			cfg_path="$ROOT/$cfg_dir/$cfg_file"
			[[ ! -e "$cfg_path" && ! -L "$cfg_path" ]] ||
				REPO_CONFIGS+=("$cfg_dir/$cfg_file")
		done
		cfg_dir_path="$ROOT/$cfg_dir/plugins"
		[[ ! -d "$cfg_dir_path" && ! -L "$cfg_dir_path" ]] ||
			REPO_CONFIGS+=("$cfg_dir/plugins/")
	done
	if [[ "${#REPO_CONFIGS[@]}" -gt 0 ]]; then
		die "refusing repo-local Antigravity config(s) in $ROOT:" \
			"${REPO_CONFIGS[@]}" \
			'Review from a clean checkout, or set' \
			'AGY_AGENT_ALLOW_REPO_CONFIG=1 only after confirming them.'
	fi
fi

FIRST_LINE=""
IFS= read -r FIRST_LINE < "$ROLE_FILE" || true
[[ "${FIRST_LINE%$'\r'}" == --- ]] ||
	die "$ROLE_FILE: no frontmatter; line 1 is not ---."

# `key: value` from the frontmatter: the lines between the first two `---`.
# A value is passed to agy verbatim, so a quoted or commented one is
# refused here rather than after a billed run fails to verify.
pin() {
	local found value
	found="$(awk -v key="$1" '
		/^---[ \t\r]*$/ { if (++rules == 2) exit; next }
		rules == 1 && index($0, key ":") == 1 {
			value = substr($0, length(key) + 2)
			gsub(/^[ \t]+|[ \t\r]+$/, "", value)
			print "=" value
			exit
		}' "$ROLE_FILE")"
	if [[ -z "$found" && "$1" == agy-model ]]; then
		die "$ROLE_FILE has no agy-model key: the bridge runs only" \
			'roles that carry an Antigravity bridge model pin, and this role has none.'
	fi
	value="${found#=}"
	[[ -n "$value" ]] ||
		die "$ROLE_FILE: frontmatter key $1 missing or empty."
	[[ "$value" != *[\"\'#[:space:]]* ]] ||
		die "$ROLE_FILE: frontmatter key $1 is \"$value\";" \
			'write it bare: no quotes, comment or whitespace.'
	printf '%s' "$value"
}
MODEL="$(pin agy-model)"

PREAMBLE="Your role instructions are in $ROLE_FILE; read it in full. \
Its model: and tools: frontmatter is replaced by this run's configuration. \
You run read-only: read_file is the only tool this run accepts. Any other \
tool call (shell, write, web search, URL fetch, MCP, subagent) ends the run \
and discards your answer. Do not commit, push or mutate tracker state."

command -v agy > /dev/null 2>&1 ||
	die 'agy is not installed or not on PATH.'
command -v python3 > /dev/null 2>&1 ||
	die 'python3 is not installed or not on PATH.'

# A floor: an older agy CLI is unmeasured (see the header), so its pin and
# stream-json contract cannot be proven, and 1.5.18 is the first whose
# step events the check reads. A newer one than MEASURED_VERSION
# runs, with a notice.
INSTALLED_VERSION="$(agy --version 2> /dev/null | awk 'NF { print; exit }' || true)"
# Anything after X.Y.Z is ignored, by the floor and the notice alike.
VERSION_RE='^([0-9]+)\.([0-9]+)\.([0-9]+)([^0-9].*)?$'
# older_than <a> <b>: true when dotted version <a> is older than <b>.
older_than() {
	local -a have want
	local i
	IFS=. read -r -a have <<< "$1"
	IFS=. read -r -a want <<< "$2"
	for i in 0 1 2; do
		((10#${have[i]} > 10#${want[i]})) && return 1
		((10#${have[i]} < 10#${want[i]})) && return 0
	done
	return 1
}
INSTALLED_CORE=""
if [[ "$INSTALLED_VERSION" =~ $VERSION_RE ]]; then
	INSTALLED_CORE="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}.${BASH_REMATCH[3]}"
fi
if [[ -z "$INSTALLED_CORE" ]] || older_than "$INSTALLED_CORE" "$MIN_VERSION"; then
	die "agy reports \"$INSTALLED_VERSION\"; this wrapper needs" \
		"agy >= $MIN_VERSION. Upgrade Antigravity CLI."
fi
if older_than "$MEASURED_VERSION" "$INSTALLED_CORE"; then
	printf 'NOTE: agy %s is newer than %s, the newest version this\n' \
		"$INSTALLED_VERSION" "$MEASURED_VERSION" >&2
	printf '  bridge was measured on; the run may fail verification.\n' >&2
fi

TIMEOUT_BIN=""
if command -v timeout > /dev/null 2>&1; then
	TIMEOUT_BIN=timeout
elif command -v gtimeout > /dev/null 2>&1; then
	TIMEOUT_BIN=gtimeout
fi

# Resolve a relative transcript path before `cd -- "$ROOT"` changes cwd.
if [[ -n "$TRANSCRIPT" && "$TRANSCRIPT" != /* ]]; then
	TRANSCRIPT="$(pwd -L)/$TRANSCRIPT"
fi

# Everything below holds the prompt, the agent's reasoning or its answer.
umask 077
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/agy-agent.XXXXXX")"
trap 'rm -rf -- "$WORKDIR"' EXIT
AGY_PID=""
AGY_WAITED=""
# A signal stops agy too, rather than orphaning it, unless it was already
# waited for (its pid may be reused). `$!` is set the moment the launch below
# returns, before any trap can run, so in the window before AGY_PID is
# assigned no signal finds agy started but unknown (as in codex-agent.sh).
stop() {
	local pid="${AGY_PID:-${!:-}}"
	[[ -n "$AGY_WAITED" || -z "$pid" ]] || kill -TERM "$pid" 2> /dev/null || true
	exit $((128 + $1))
}
trap 'stop 1' HUP
trap 'stop 2' INT
trap 'stop 15' TERM

STREAM_FILE="${TRANSCRIPT:-$WORKDIR/stream.jsonl}"
STDERR_FILE="$WORKDIR/stderr"
MESSAGE_FILE="$WORKDIR/message"
INPUT_JSON="$WORKDIR/input.jsonl"

python3 -I -c '
import json, sys
preamble, prompt_path, out_path = sys.argv[1:4]
with open(prompt_path, encoding="utf-8", errors="replace") as fh:
    body = fh.read()
event = {"event": "user", "message": {"content": f"{preamble}\n\n{body}"}}
with open(out_path, "w", encoding="utf-8") as out:
    out.write(json.dumps(event) + "\n")
' "$PREAMBLE" "$PROMPT_FILE" "$INPUT_JSON" ||
	die "failed to encode prompt file: $PROMPT_FILE"

# One program for both uses, so the init and step checks exist once: `watch`
# stops agy at a bad init event or step, `verify` checks the whole finished
# stream. It is kept in a variable and run with `python3 -I -c`, so nothing
# the wrapper executes is ever written under WORKDIR.
IFS= read -r -d '' CHECK_SRC << 'PY' || true
import json
import os
import signal
import sys
import time

# Tuples: `in` then compares, and never raises on an unhashable JSON value.
ALLOWED_TOOLS = ("read_file",)
PLAIN_STEPS = ("user_input", "system_message", "agent_response")


def parse_event(line):
    try:
        obj = json.loads(line.strip())
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def init_error(init, expected_model):
    """(kind, message) for an init content mismatch, None when it is fine."""
    model = init.get("model")
    if model != expected_model:
        return (
            "pin",
            f"pin mismatch on model: expected {expected_model!r}, "
            f"actual {model!r}",
        )
    perm_mode = init.get("permission_mode")
    if perm_mode != "request-review":
        return (
            "init",
            f"unexpected permission_mode {perm_mode!r}; "
            "expected 'request-review'",
        )
    return None


def step_error(step):
    """A message for a step outside the read-only set, None when it is fine."""
    if not isinstance(step, dict):
        return "unreadable step_update event"
    step_type = step.get("step_type")
    tool_name = step.get("tool_name")
    if (step_type in PLAIN_STEPS and tool_name is None) or (
        step_type == "tool" and tool_name in ALLOWED_TOOLS
    ):
        return None
    return (
        f"step outside the read-only set: step_type {step_type!r}, "
        f"tool_name {tool_name!r}, step_index {step.get('step_index')!r}"
    )


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        # EPERM: the process exists but is not ours to signal. Only "no such
        # process" proves it is gone; anything else must not end the watch.
        pass
    return True


def watch(stream_path, expected_model, pid):
    """TERM pid and exit 3 at a bad first init, 4 at a bad step.

    Otherwise return once pid is gone. Lines end at a newline only;
    `verify` also splits at a bare carriage return, so a stream using
    one is judged by `verify` alone. The watch also ends when the
    wrapper is gone: a signalled wrapper exits without reaping agy, and
    a pid nobody reaps would look alive forever.
    """
    pos = 0
    buf = b""
    seen = False
    parent = os.getppid()
    while os.getppid() == parent and pid_alive(pid):
        try:
            with open(stream_path, "rb") as fh:
                fh.seek(pos)
                chunk = fh.read()
        except OSError:
            chunk = b""
        pos += len(chunk)
        *lines, buf = (buf + chunk).split(b"\n")
        for line in lines:
            obj = parse_event(line.decode("utf-8", errors="replace"))
            if obj is None:
                continue
            ev = obj.get("event")
            if ev == "init" and not seen:
                seen = True
                init = obj.get("init")
                bad = isinstance(init, dict) and init_error(
                    init, expected_model
                )
                code = 3
            elif ev == "step_update":
                bad = step_error(obj.get("step_update"))
                code = 4
            else:
                continue
            if bad:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    return
                sys.exit(code)
        time.sleep(0.1)


def verify(stream_path, expected_model, msg_path):
    init_obj = None
    init_count = 0
    result_obj = None
    result_count = 0
    bad_result_status = None
    bad_step = None
    with open(stream_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            obj = parse_event(line)
            if obj is None:
                continue
            ev = obj.get("event")
            if ev == "init":
                init_count += 1
                if init_obj is None and isinstance(obj.get("init"), dict):
                    init_obj = obj["init"]
            elif ev == "step_update" and bad_step is None:
                bad_step = step_error(obj.get("step_update"))
            elif ev == "result":
                result_count += 1
                res = obj.get("result")
                if isinstance(res, dict):
                    if result_obj is None:
                        result_obj = res
                    status = res.get("status")
                    if status != "SUCCESS" and bad_result_status is None:
                        bad_result_status = status

    tokens = None
    if isinstance(result_obj, dict):
        usage = result_obj.get("usage")
        if isinstance(usage, dict):
            tt = usage.get("total_tokens")
            if isinstance(tt, int) and not isinstance(tt, bool) and tt >= 0:
                tokens = tt

    print(f"TOKENS={tokens}" if tokens is not None else "TOKENS=UNAVAILABLE")

    if init_count == 0 or init_obj is None:
        print("ERR=no init event in stream-json output")
        sys.exit(3)

    if init_count != 1:
        print(f"ERR=unexpected init event count: {init_count}; expected 1")
        sys.exit(3)

    mismatch = init_error(init_obj, expected_model)
    if mismatch is not None:
        print(f"ERR={mismatch[1]}")
        print(f"KIND={mismatch[0]}")
        sys.exit(3)

    if bad_step is not None:
        print(f"ERR={bad_step}")
        print("KIND=step")
        sys.exit(3)

    if result_count == 0 or result_obj is None:
        print("ERR=no result event in stream-json output")
        sys.exit(3)

    if result_count != 1:
        print(f"ERR=unexpected result event count: {result_count}; expected 1")
        sys.exit(3)

    if bad_result_status is not None:
        print(f"ERR=result status is {bad_result_status!r}, not SUCCESS")
        sys.exit(3)

    res_status = result_obj.get("status")
    if res_status != "SUCCESS":
        print(f"ERR=result status is {res_status!r}, not SUCCESS")
        sys.exit(3)

    response = result_obj.get("response")
    if not isinstance(response, str) or not response.strip():
        print("ERR=empty response in result event")
        sys.exit(3)

    with open(msg_path, "w", encoding="utf-8") as out:
        out.write(response)


cmd = sys.argv[1:2]
if cmd == ["watch"] and len(sys.argv) == 5:
    watch(sys.argv[2], sys.argv[3], int(sys.argv[4]))
elif cmd == ["verify"] and len(sys.argv) == 5:
    verify(*sys.argv[2:5])
else:
    sys.exit(2)
PY

# Created now, after every cheap refusal and before anything is spent.
{ : > "$STREAM_FILE"; } 2> /dev/null ||
	die "transcript path is not writable: $STREAM_FILE"

printf 'Dispatching %s to Antigravity: model %s,\n' "$ROLE" "$MODEL" >&2
printf '  sandbox read-only, in %s\n' "$ROOT" >&2

if [[ -n "$TIMEOUT_BIN" ]]; then
	AGY_CMD=("$TIMEOUT_BIN" -k 30 "$TIMEOUT_SECONDS" agy)
else
	AGY_CMD=(agy)
fi

cd -- "$ROOT"
STATUS=0
WATCH_STATUS=0
"${AGY_CMD[@]}" \
	--input-format stream-json \
	--output-format stream-json \
	--model "$MODEL" \
	--sandbox \
	--disable-slash-commands \
	--print-timeout "${TIMEOUT_SECONDS}s" \
	--settings "$SETTINGS" \
	< "$INPUT_JSON" > "$STREAM_FILE" 2> "$STDERR_FILE" &
AGY_PID=$!
# Under `timeout`, AGY_PID is timeout's, which forwards TERM to agy. The
# watcher exits 3 after TERMing agy at a bad init, 4 at a bad step, and 0 once
# agy is gone; any other status is a crash, which changes nothing: the
# verification below decides. It is never signalled: it ends within a poll
# of agy, or of this wrapper.
python3 -I -c "$CHECK_SRC" watch "$STREAM_FILE" "$MODEL" "$AGY_PID" \
	> /dev/null 2>&1 &
WATCH_PID=$!
wait "$AGY_PID" || STATUS=$?
AGY_WAITED=1
wait "$WATCH_PID" || WATCH_STATUS=$?

fail() {
	local status="$1"
	shift
	printf 'ERROR: %s\n' "$1" >&2
	shift
	[[ $# -eq 0 ]] || printf '  %s\n' "$@" >&2
	[[ -z "$TRANSCRIPT" ]] ||
		printf '  agy transcript: %s\n' "$TRANSCRIPT" >&2
	if [[ -s "${STDERR_FILE:-}" ]]; then
		printf '  agy stderr:\n' >&2
		awk 'NR <= 20 { print "    " $0 }' "$STDERR_FILE" >&2
	fi
	exit "$status"
}

# The value of KEY= in the verify output; the value may itself contain `=`.
field() {
	awk -v key="$1" '
		index($0, key "=") == 1 { print substr($0, length(key) + 2); exit }
	' "$VERIFY_OUT"
}

VERIFY_OUT="$WORKDIR/verify"
VERIFY_STATUS=0
python3 -I -c "$CHECK_SRC" verify "$STREAM_FILE" "$MODEL" "$MESSAGE_FILE" \
	> "$VERIFY_OUT" || VERIFY_STATUS=$?

TOKENS="$(field TOKENS)"
if [[ "$TOKENS" =~ ^[0-9]+$ ]]; then
	printf 'tokens used (normalised): %s\n' "$TOKENS" >&2
else
	printf 'tokens unavailable; never estimate.\n' >&2
fi

# An init content mismatch or an out-of-set step outranks agy's own status (a
# TERMed agy exits non-zero) and does not depend on whether the watcher saw it
# first.
KIND="$(field KIND)"
if [[ "$KIND" == init || "$KIND" == pin || "$KIND" == step ||
	"$WATCH_STATUS" -eq 3 || "$WATCH_STATUS" -eq 4 ]]; then
	DETAILS=()
	[[ "$WATCH_STATUS" -ne 3 ]] ||
		DETAILS+=('Sent agy SIGTERM at its init event.')
	[[ "$WATCH_STATUS" -ne 4 ]] ||
		DETAILS+=('Sent agy SIGTERM at a step outside the read-only set.')
	if [[ "$KIND" == init ]]; then
		# Deterministic for the installed agy: say so.
		DETAILS+=(
			"The installed agy ($INSTALLED_VERSION) reports this in its init event,"
			'so a re-dispatch fails the same way and bills again. Do not re-dispatch:'
			'the bridge stays unavailable until it or the installed agy changes.'
		)
	elif [[ "$KIND" == step ]]; then
		DETAILS+=(
			'The call may already have run: the settings deny writes and shell'
			'commands, not web searches or subagents.'
			'Discard the result and re-dispatch.'
		)
	else
		DETAILS+=('Discard the result and re-dispatch.')
	fi
	ERR_MSG="$(field ERR)"
	fail 3 "${ERR_MSG:-the run did not verify against $ROLE_FILE}" \
		"${DETAILS[@]}"
fi

if [[ -n "$TIMEOUT_BIN" ]] && ((STATUS == 124 || STATUS == 137)); then
	fail "$STATUS" "agy exited $STATUS." \
		"Most likely the $TIMEOUT_SECONDS-second bound (137: killed" \
		'after ignoring TERM, or the OOM killer). Raise' \
		'it with AGY_AGENT_TIMEOUT=<seconds>.'
fi
[[ "$STATUS" -eq 0 ]] || fail "$STATUS" "agy exited $STATUS."

if [[ "$VERIFY_STATUS" -ne 0 ]]; then
	ERR_MSG="$(field ERR)"
	fail 3 "${ERR_MSG:-the run did not verify against $ROLE_FILE}" \
		'Discard the result and re-dispatch.'
fi

printf 'Pin and read-only steps verified from the stream-json events.\n' >&2
cat -- "$MESSAGE_FILE"
