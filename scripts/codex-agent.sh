#!/usr/bin/env bash

# Dispatch one agent-kit role that carries a bridge sandbox pin to Codex
# headlessly, pinned, and prove afterwards that the pin actually took.
#
# `codex exec` has NO agent selector: no `--agent` flag picks a role with
# its model, reasoning effort and sandbox. A hand-built call has to spell
# all three on the command line, and forgetting one does not announce
# itself: the run succeeds against the DEFAULT model and reads exactly like
# the cross-family dispatch it was meant to be.
#
# So this wrapper reads the pin out of the role file's frontmatter
# (`codex-model`, `codex-effort`, `codex-sandbox` in agents/<role>.md,
# never a copy kept here), builds the invocation, and then VERIFIES it.
# The session banner codex prints on stderr is the only positive evidence
# of what a run really used: its `model:`, `reasoning effort:` and
# `sandbox:` lines must equal the pin, its `provider:` and `approval:`
# lines `openai` and `never`, and a run with no banner, or one that
# disagrees, exits 3 rather than hand back an answer nobody can attribute
# to the pinned model.
#
# `--ignore-user-config` keeps $CODEX_HOME/config.toml out of the run. Its
# project trust is what makes codex load a checked-out repository's own
# `.codex/config.toml`, and start that file's `mcp_servers` at launch,
# outside the sandbox; a `-c mcp_servers={}` override does not stop that.
# The user's own provider and MCP servers are left out with it; auth still
# comes from CODEX_HOME.
#
# The user opts in, once for every project, by creating the file
# ${XDG_CONFIG_HOME:-$HOME/.config}/agent-kit/codex-bridge; its content is
# not read. Without it, codex is never called: the file is the user's
# consent to send the review prompt, and whatever codex chooses to read,
# to a second vendor. It lives outside every checkout, so no branch can
# grant it.
#
# The banner and token formats parsed below were read on codex-cli
# 0.147.0, 0.159.2 and 0.160.0; everything else relied on here,
# `--ignore-user-config` included, only on 0.160.0, which is the floor.
# codex prints the final message on stdout as well as in the `-o` file:
# stdout is discarded, and the `-o` file printed only once the run
# verified. stderr carries the banner and the token count (`tokens used`,
# the figure on the FOLLOWING line, locale-formatted), and the answer
# too: it goes only to a file, parsed once the run is over, never shown.
#
# Usage:
#   codex-agent.sh <role> <prompt-file> [<transcript-file>]
#
# Run from anywhere inside the target project; its git top level is the
# directory codex works in. <role> names agents/<role>.md beside this
# script, and must carry a `codex-sandbox` pin: a role without one is not
# a bridge role and is refused. <prompt-file> holds the dispatch prompt;
# a fixed read-only preamble pointing codex at the role file goes before
# it. The final message of a verified run is printed on stdout; this
# wrapper's own status lines go to stderr. <transcript-file>, a path that
# must not exist yet, keeps codex's stderr, and an ERROR raised after
# codex ran names it; without one, codex's stderr is deleted with the run.
#
# Exit status:
#   0    the run finished, the banner verified the pin, codex answered
#   2    usage error, failed precondition, user not opted in, or a pin
#        key missing or malformed in the role file; codex did not run
#   3    the pin could not be verified (banner absent or mismatched), or
#        codex returned no answer: discard the run
#   124  the wall-clock bound stopped the run; 137 it had to be killed
#   128+n  this wrapper got signal n (HUP, INT, TERM) and stopped codex
#   else codex's own status, when codex itself failed
#
# Environment: CODEX_AGENT_TIMEOUT bounds one dispatch, in whole seconds
# (default 7200). 0 and suffix forms (`2h`) are refused: `timeout` reads 0
# as "no limit", and a suffix would be echoed back unparsed. The bound
# needs GNU `timeout` (`gtimeout` on macOS with coreutils); without either
# the run proceeds unbounded and says so.
#
# Portable down to bash 3.2 (stock macOS): no mapfile, no case-folding
# expansions, no associative arrays.

set -euo pipefail

USAGE='usage: codex-agent.sh <role> <prompt-file> [<transcript-file>]'
OPT_IN="${XDG_CONFIG_HOME:-${HOME:-}/.config}/agent-kit/codex-bridge"
MIN_VERSION='0.160.0'
# Not the role's to choose: the vendor this bridge crosses to, and a
# headless run that never stops to ask.
PROVIDER='openai'
APPROVAL='never'

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

TIMEOUT_SECONDS="${CODEX_AGENT_TIMEOUT:-7200}"
if [[ ! "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
	die "CODEX_AGENT_TIMEOUT must be a positive whole number of seconds;" \
		"got \"$TIMEOUT_SECONDS\"."
fi

ROOT="$(git rev-parse --show-toplevel 2> /dev/null)" ||
	die 'not inside a git repository; run from the target project.'

[[ -f "$OPT_IN" ]] ||
	die "not opted in: $OPT_IN does not exist. Codex was not called." \
		'Create that file to let every project send reviews to Codex.'

FIRST_LINE=""
IFS= read -r FIRST_LINE < "$ROLE_FILE" || true
[[ "${FIRST_LINE%$'\r'}" == --- ]] ||
	die "$ROLE_FILE: no frontmatter; line 1 is not ---."

# `key: value` from the frontmatter: the lines between the first two `---`.
# A value is passed to codex verbatim, so a quoted or commented one is
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
	if [[ -z "$found" && "$1" == codex-sandbox ]]; then
		die "$ROLE_FILE has no codex-sandbox key: the bridge runs only" \
			'roles that carry a sandbox pin, and this role has none.'
	fi
	value="${found#=}"
	[[ -n "$value" ]] ||
		die "$ROLE_FILE: frontmatter key $1 missing or empty."
	[[ "$value" != *[\"\'#[:space:]]* ]] ||
		die "$ROLE_FILE: frontmatter key $1 is \"$value\";" \
			'write it bare: no quotes, comment or whitespace.'
	printf '%s' "$value"
}
MODEL="$(pin codex-model)"
EFFORT="$(pin codex-effort)"
SANDBOX="$(pin codex-sandbox)"

[[ "$SANDBOX" == read-only ]] ||
	die "codex-sandbox is $SANDBOX: no preamble for this sandbox yet."
PREAMBLE="Your role instructions are in $ROLE_FILE; read it in full. \
Its model: and tools: frontmatter is Claude-only and replaced by this \
run's configuration. Where its body says you have no shell or cannot run \
commands, that does not hold here: you have a read-only shell for reading \
files; you MUST NOT run builds, tests or any command that changes state. \
Do not delegate, commit, push or mutate tracker state."

command -v codex > /dev/null 2>&1 ||
	die 'codex is not installed or not on PATH.'

# A floor, not a notice: an older codex-cli is unmeasured (see the header),
# so its pin cannot be proven. Newer versions pass.
INSTALLED_VERSION="$(codex --version 2> /dev/null || true)"
VERSION_RE='^codex-cli ([0-9]+)\.([0-9]+)\.([0-9]+)$'
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
	die "codex-cli reports \"$INSTALLED_VERSION\"; this wrapper needs" \
		"codex-cli >= $MIN_VERSION. Upgrade codex-cli."
fi

TIMEOUT_BIN=""
if command -v timeout > /dev/null 2>&1; then
	TIMEOUT_BIN=timeout
elif command -v gtimeout > /dev/null 2>&1; then
	TIMEOUT_BIN=gtimeout
else
	printf 'NOTE: no timeout (nor gtimeout) on PATH; this dispatch\n' >&2
	printf '  runs unbounded. Install GNU coreutils for the limit.\n' >&2
fi

# Everything below holds the prompt, the agent's reasoning or its answer;
# codex inherits the umask too, so its `-o` file is private as well.
umask 077
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/codex-agent.XXXXXX")"
trap 'rm -rf -- "$WORKDIR"' EXIT
# A signal stops codex too, rather than orphaning it: TERM whatever the
# signal, as a background child starts with INT ignored, and `timeout`
# passes it on. `$!` is set the moment the launch below returns, before
# any trap can run, so no signal finds codex started but unknown.
stop() {
	[[ -z "${!:-}" ]] || kill -TERM "$!" 2> /dev/null || true
	exit $((128 + $1))
}
trap 'stop 1' HUP
trap 'stop 2' INT
trap 'stop 15' TERM

MESSAGE_FILE="$WORKDIR/message"
STDERR_FILE="${TRANSCRIPT:-$WORKDIR/stderr}"
# Created now, after every cheap refusal and before anything is spent.
{ : > "$STDERR_FILE"; } 2> /dev/null ||
	die "transcript path is not writable: $STDERR_FILE"

COMBINED="$WORKDIR/prompt"
{
	printf '%s\n\n' "$PREAMBLE"
	cat -- "$PROMPT_FILE"
} > "$COMBINED"

printf 'Dispatching %s to Codex: model %s, reasoning effort %s,\n' \
	"$ROLE" "$MODEL" "$EFFORT" >&2
printf '  sandbox %s, in %s\n' "$SANDBOX" "$ROOT" >&2

# Always at least one element: "${EMPTY[@]}" is an unbound-variable error
# under `set -u` on bash 3.2. `-k 30` KILLs a run that ignores TERM.
if [[ -n "$TIMEOUT_BIN" ]]; then
	CODEX_CMD=("$TIMEOUT_BIN" -k 30 "$TIMEOUT_SECONDS" codex)
else
	CODEX_CMD=(codex)
fi

# `--color never` is load-bearing: both parses read whole lines, and an
# escape-wrapped banner line or marker would silently lose its match. In
# the background and waited on, because bash holds a trap until a
# foreground command finishes; the status kept is codex's.
STATUS=0
"${CODEX_CMD[@]}" exec \
	--cd "$ROOT" \
	--color never \
	--ignore-user-config \
	-m "$MODEL" \
	-c "model_reasoning_effort=$EFFORT" \
	--sandbox "$SANDBOX" \
	-o "$MESSAGE_FILE" \
	- < "$COMBINED" > /dev/null 2> "$STDERR_FILE" &
wait "$!" || STATUS=$?

# An ERROR after codex ran: as die, plus where its stderr was kept.
fail() {
	local status="$1"
	shift
	printf 'ERROR: %s\n' "$1" >&2
	shift
	[[ $# -eq 0 ]] || printf '  %s\n' "$@" >&2
	[[ -z "$TRANSCRIPT" ]] ||
		printf '  codex stderr: %s\n' "$TRANSCRIPT" >&2
	exit "$status"
}

# The figure counts only as the last non-empty line, right under a
# `tokens used` marker: codex echoes every file the agent reads into this
# stream, so any other marker may be documentation, or a figure the run
# went on past. Separators (`,` `.` space, NBSP, narrow NBSP) are
# stripped; anything else left over is reported, never guessed.
RAW="$(awk 'NF { marker = last; last = $0 }
	END { if (marker == "tokens used") print last }' "$STDERR_FILE")"
COUNT="${RAW//[.,[:space:]]/}"
COUNT="${COUNT//$'\xc2\xa0'/}"
COUNT="${COUNT//$'\xe2\x80\xaf'/}"
if [[ "$COUNT" =~ ^[0-9]+$ ]]; then
	printf 'tokens used (raw): %s\n' "$RAW" >&2
	printf 'tokens used (normalised): %s\n' "$COUNT" >&2
else
	printf 'tokens unavailable; never estimate.\n' >&2
	[[ -z "$RAW" ]] || printf '  (not a figure: %s)\n' "$RAW" >&2
fi

if [[ -n "$TIMEOUT_BIN" ]] && ((STATUS == 124 || STATUS == 137)); then
	fail "$STATUS" "codex exec exited $STATUS." \
		"Most likely the $TIMEOUT_SECONDS-second bound (137: killed" \
		'after ignoring TERM, or the OOM killer). Raise' \
		'it with CODEX_AGENT_TIMEOUT=<seconds>.'
fi
[[ "$STATUS" -eq 0 ]] || fail "$STATUS" "codex exec exited $STATUS."

# The banner is the block between the first two `----` rules, and only a
# closed one counts; bounding the search keeps a prompt or answer line
# starting `model: ` from counting.
BANNER="$(awk '/^-+$/ { if (++seen == 2) { closed = 1; exit } next }
	seen == 1 { block = block $0 "\n" }
	END { if (closed) printf "%s", block }' "$STDERR_FILE")"
[[ -n "${BANNER//[[:space:]]/}" ]] ||
	fail 3 'no codex session banner on stderr. The banner' \
		'is the only evidence the pin took: discard this run.'

MISMATCH=0
check() {
	local observed
	observed="$(awk -v key="$1: " 'index($0, key) == 1 {
		print substr($0, length(key) + 1); exit }' <<< "$BANNER")"
	if [[ "$observed" != "$2" ]]; then
		printf "ERROR: pin mismatch on %s: expected '%s',\n" \
			"$1" "$2" >&2
		printf "  actual '%s'.\n" "${observed:-<absent>}" >&2
		MISMATCH=1
	fi
}
check model "$MODEL"
check 'reasoning effort' "$EFFORT"
check sandbox "$SANDBOX"
check provider "$PROVIDER"
check approval "$APPROVAL"
[[ "$MISMATCH" -eq 0 ]] ||
	fail 3 "the run did not use the pin in $ROLE_FILE;" \
		'discard the result and re-dispatch.'

[[ -s "$MESSAGE_FILE" ]] ||
	fail 3 'codex exited 0 but returned no answer (no -o file, or' \
		'an empty one): this stage did not happen.'

printf 'Pin verified from the banner.\n' >&2
cat -- "$MESSAGE_FILE"
