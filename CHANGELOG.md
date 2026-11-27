# Changelog

All notable user-facing changes to `agent-kit` are documented here.
Releases `v0.1.0` through `v0.5.1` predate this file and are recorded in
git tag annotations (`git tag -n1 'v0.*'`).

## [0.6.0] - 2026-11-27

### Added

- The tea guard denies a `tea` comment or pull request write (`comments`;
  `pulls create`, `edit`, `approve`, `reject`, `reply` and `merge`) whose
  text carries a closing or reopen keyword directly before an issue
  reference, since the forge acts on one wherever it stands. It also
  denies a write whose text it cannot read: a shell expansion,
  `--description-file`, or a comment with no body argument. In a pull
  request description, lines holding only `Closes #N` are admitted.

### Changed

- Releases are now deliberate: a version is cut from `main` by a release
  pull request, tagged `vX.Y.Z` and published on the `release` branch,
  and `main` carries unreleased work in between. Installs track `release`
  or a release tag (`README.md`, "Installing"). An install registered
  before this release keeps tracking `main` until its marketplace source
  is re-pointed. Under Claude Code, adding `"ref": "release"` to the
  entry in `~/.claude/settings.json` alone leaves the plugin unloaded,
  and every guard with it: the registered source in
  `~/.claude/plugins/known_marketplaces.json` needs the same `"ref"`,
  followed by `claude plugin marketplace update agent-kit`.
- The tea guard's read rule reaches more calls, so some single issue or
  pull request reads that passed without `--comments` are now denied: a
  `tea` call behind a precommand wrapper (`env`, `time`, `sudo` and the
  others the shared prefix list knows), after a global flag, inside
  `( )`, `$( )` or `{ }`, after `!`, in the body of an `if` or a loop,
  and one whose index follows the short value flags `-l`, `-r` or `-R`.
  The write rule reaches the same calls.
- Every hook that runs a `hooks/*.py` script starts it from a bash
  wrapper as `python3 -E -s`. A `PYTHON*` variable or startup code in the
  user site could crash a guard before it decided, and the guarded call
  then went ahead in silence. The decisions-log status guard and the
  session temp-dir pruner are now registered through such wrappers, so
  under Codex open `/hooks` once after updating to trust the changed hook
  commands.
- The session-context hook runs its Python isolated (`python3 -I`) on its
  Antigravity path, so a `json.py` on `PYTHONPATH` or in the working
  directory is never imported in place of the stdlib module.
- The Antigravity bridge (`scripts/agy-agent.sh`) needs `agy` 1.5.18 or
  later and verifies what a run did, not the tools its `init` event
  lists. It checks the events as they arrive and stops `agy` at a
  mismatched `init`, at the first step that is neither a plain step nor a
  `read_file` call, at an event it does not know and at a line it cannot
  read; such a run exits 3. A run that calls `view_file`, `grep_search`,
  `list_dir` or `find_by_name`, which the bridge accepted before, is now
  rejected. This detects and rejects, it does not prevent: `README.md`
  states what can run before the stop.

### Fixed

- On `agy` 1.5.18 the Antigravity bridge refused every dispatch, and only
  after a full, billed run (#99).
- The tea guard no longer takes a file-descriptor redirect for an issue
  index: `tea pr --output json 2>&1` was denied.
