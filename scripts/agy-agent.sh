#!/usr/bin/env bash

# Dispatch one agent-kit role that carries an Antigravity bridge model pin to
# `agy` headlessly, pinned and read-only, and prove afterwards that the pin
# actually took.
#
# `agy` headless runs default to whatever model the user selected last, and a
# hand-built call does not prove the requested model ran or lock permissions
# read-only. So this wrapper reads `agy-model` from `agents/<role>.md` (never
# a copy kept here), passes an inline `--settings` JSON object that allows
# `read_file(*)` and denies writes, shell commands, MCP tools and URL fetches,
# streams the prompt via `--input-format stream-json` (avoiding ARG_MAX on
# large diffs), and VERIFIES the `stream-json` `init` and `result` events.
#
# The `init` event's `model` must equal the pin and its `permission_mode` must
# not be `always-proceed`; the `result` event must report `status: "SUCCESS"`
# and a non-empty `response`. A run whose stream lacks either event, or whose
# `init.model` disagrees, exits 3 rather than handing back an answer nobody
# can attribute to the pinned model.
#
# The user opts in, with one file that covers every project, by creating
# ${XDG_CONFIG_HOME:-$HOME/.config}/agent-kit/agy-bridge; its content is not
# read. Without it, `agy` is never called: the file is the user's consent to
# send the review prompt, and whatever `agy` chooses to read, to a second
# vendor. It lives outside every checkout, so no branch can grant it.
#
# The stream-json `init`, `result` and `usage` shapes parsed below were
# measured on Antigravity CLI 1.5.16, which is the floor.
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
#   2    usage error, failed precondition, user not opted in, or a pin
#        key missing or malformed in the role file; `agy` did not run
#   3    the pin could not be verified (`init` absent or mismatched),
#        permissions were bypassed, or `agy` returned no answer: discard
#   124  the wall-clock bound stopped the run; 137 it had to be killed
#   128+n  this wrapper got signal n (HUP, INT, TERM) and stopped `agy`
#   else `agy`'s own status, when `agy` itself failed
#
# Environment: AGY_AGENT_TIMEOUT bounds one dispatch, in whole seconds
# (default 7200). Passed to `agy --print-timeout` and, when GNU `timeout`
# (`gtimeout` on macOS) is on PATH, also enforced externally.
#
# Portable down to bash 3.2 (stock macOS): no mapfile, no case-folding
# expansions, no associative arrays.

set -euo pipefail

USAGE='usage: agy-agent.sh <role> <prompt-file> [<transcript-file>]'
OPT_IN="${XDG_CONFIG_HOME:-${HOME:-}/.config}/agent-kit/agy-bridge"
MIN_VERSION='1.5.16'
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

[[ -f "$OPT_IN" ]] ||
	die "not opted in: $OPT_IN does not exist. Antigravity was not called." \
		'Create that file to let every project send reviews to Antigravity.'

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
You run read-only with no shell, no writes, no network fetches and no MCP \
tools; read files directly. Do not delegate, commit, push or mutate tracker \
state."

command -v agy > /dev/null 2>&1 ||
	die 'agy is not installed or not on PATH.'
command -v python3 > /dev/null 2>&1 ||
	die 'python3 is not installed or not on PATH.'

# A floor, not a notice: an older agy CLI is unmeasured (see the header),
# so its pin and stream-json contract cannot be proven. Newer versions pass.
INSTALLED_VERSION="$(agy --version 2> /dev/null | awk 'NF { print; exit }' || true)"
VERSION_RE='^([0-9]+)\.([0-9]+)\.([0-9]+)([^0-9].*)?$'
below_floor() {
	local -a have want
	local i
	IFS=. read -r -a want <<< "$MIN_VERSION"
	have=("$1" "$2" "$3")
	for i in 0 1 2; do
		((10#${have[i]} > 10#${want[i]})) && return 1
		((10#${have[i]} < 10#${want[i]})) && return 0
	done
	return 1
}
if [[ ! "$INSTALLED_VERSION" =~ $VERSION_RE ]] ||
	below_floor "${BASH_REMATCH[@]:1:3}"; then
	die "agy reports \"$INSTALLED_VERSION\"; this wrapper needs" \
		"agy >= $MIN_VERSION. Upgrade Antigravity CLI."
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
stop() {
	[[ -z "${!:-}" ]] || kill -TERM "$!" 2> /dev/null || true
	exit $((128 + $1))
}
trap 'stop 1' HUP
trap 'stop 2' INT
trap 'stop 15' TERM

STREAM_FILE="${TRANSCRIPT:-$WORKDIR/stream.jsonl}"
STDERR_FILE="$WORKDIR/stderr"
MESSAGE_FILE="$WORKDIR/message"
# Created now, after every cheap refusal and before anything is spent.
{ : > "$STREAM_FILE"; } 2> /dev/null ||
	die "transcript path is not writable: $STREAM_FILE"

INPUT_JSON="$WORKDIR/input.jsonl"
python3 -c '
import json, sys
preamble, prompt_path, out_path = sys.argv[1:4]
with open(prompt_path, encoding="utf-8") as fh:
    body = fh.read()
event = {"event": "user", "message": {"content": f"{preamble}\n\n{body}"}}
with open(out_path, "w", encoding="utf-8") as out:
    out.write(json.dumps(event) + "\n")
' "$PREAMBLE" "$PROMPT_FILE" "$INPUT_JSON"

printf 'Dispatching %s to Antigravity: model %s,\n' "$ROLE" "$MODEL" >&2
printf '  sandbox read-only, in %s\n' "$ROOT" >&2

if [[ -n "$TIMEOUT_BIN" ]]; then
	AGY_CMD=("$TIMEOUT_BIN" -k 30 "$TIMEOUT_SECONDS" agy)
else
	AGY_CMD=(agy)
fi

cd -- "$ROOT"
STATUS=0
"${AGY_CMD[@]}" \
	--input-format stream-json \
	--output-format stream-json \
	--model "$MODEL" \
	--disable-slash-commands \
	--print-timeout "${TIMEOUT_SECONDS}s" \
	--settings "$SETTINGS" \
	< "$INPUT_JSON" > "$STREAM_FILE" 2> "$STDERR_FILE" &
wait "$!" || STATUS=$?

fail() {
	local status="$1"
	shift
	printf 'ERROR: %s\n' "$1" >&2
	shift
	[[ $# -eq 0 ]] || printf '  %s\n' "$@" >&2
	[[ -z "$TRANSCRIPT" ]] ||
		printf '  agy transcript: %s\n' "$TRANSCRIPT" >&2
	exit "$status"
}

VERIFY_OUT="$WORKDIR/verify"
VERIFY_STATUS=0
python3 -c '
import json, sys

stream_path, expected_model, msg_path = sys.argv[1:4]
init_obj = None
result_obj = None
with open(stream_path, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        ev = obj.get("event")
        if ev == "init" and init_obj is None and isinstance(obj.get("init"), dict):
            init_obj = obj["init"]
        elif ev == "result" and isinstance(obj.get("result"), dict):
            result_obj = obj["result"]

tokens = None
if isinstance(result_obj, dict):
    usage = result_obj.get("usage")
    if isinstance(usage, dict):
        tt = usage.get("total_tokens")
        if isinstance(tt, int) and not isinstance(tt, bool) and tt >= 0:
            tokens = tt

if tokens is not None:
    print(f"TOKENS={tokens}")
else:
    print("TOKENS=UNAVAILABLE")

if init_obj is None:
    print("ERR=no init event in stream-json output")
    sys.exit(3)

observed_model = init_obj.get("model")
if observed_model != expected_model:
    print(
        f"ERR=pin mismatch on model: expected {expected_model!r}, "
        f"actual {observed_model!r}"
    )
    sys.exit(3)

perm_mode = init_obj.get("permission_mode")
if perm_mode == "always-proceed":
    print("ERR=permission_mode is always-proceed; read-only boundary bypassed")
    sys.exit(3)

if result_obj is None:
    print("ERR=no result event in stream-json output")
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
' "$STREAM_FILE" "$MODEL" "$MESSAGE_FILE" > "$VERIFY_OUT" || VERIFY_STATUS=$?

TOKENS="$(awk -F= '$1 == "TOKENS" { print $2; exit }' "$VERIFY_OUT")"
if [[ "$TOKENS" =~ ^[0-9]+$ ]]; then
	printf 'tokens used (normalised): %s\n' "$TOKENS" >&2
else
	printf 'tokens unavailable; never estimate.\n' >&2
fi

if [[ -n "$TIMEOUT_BIN" ]] && ((STATUS == 124 || STATUS == 137)); then
	fail "$STATUS" "agy exited $STATUS." \
		"Most likely the $TIMEOUT_SECONDS-second bound (137: killed" \
		'after ignoring TERM, or the OOM killer). Raise' \
		'it with AGY_AGENT_TIMEOUT=<seconds>.'
fi
[[ "$STATUS" -eq 0 ]] || fail "$STATUS" "agy exited $STATUS."

if [[ "$VERIFY_STATUS" -ne 0 ]]; then
	ERR_MSG="$(awk -F= '$1 == "ERR" { sub(/^ERR=/, ""); print; exit }' "$VERIFY_OUT")"
	fail 3 "${ERR_MSG:-the run did not verify against $ROLE_FILE}" \
		'Discard the result and re-dispatch.'
fi

printf 'Pin verified from the stream-json init event.\n' >&2
cat -- "$MESSAGE_FILE"
