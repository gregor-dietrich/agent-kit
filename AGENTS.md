# agent-kit — working in this repository

agent-kit is a plugin installed once per machine at user scope, so every
hook, skill and agent here runs in **every** repository its user opens.
That sets the bar for each change: nothing project-specific, and nothing
that can break silently.

## Layout

| Path | What it is |
| ---- | ---------- |
| `.claude-plugin/` | Claude Code plugin manifest (pointing `agents` at `claude-agents/`), and the marketplace manifest that makes this repo installable |
| `.codex-plugin/plugin.json` | The Codex twin: same name and version, plus Codex's `interface` block |
| `.antigravity-plugin/plugin.json` | The Antigravity twin: same name and version |
| `hooks.json` | Antigravity root hook registration (relative `./hooks/...` commands and Antigravity tool matchers) |
| `hooks/` | `hooks.json` (read by Claude Code and Codex), the guard scripts and the session temp-dir pruner it registers, each behind its bash wrapper, and `session-context.md`, the only text injected into every session |
| `skills/` | One `<name>/SKILL.md` per skill, shared by all three clients (keep `SKILL.md` bodies at most 24,000 bytes for Antigravity; put bulk reference docs under `references/`) |
| `agents/` | Antigravity-native role definitions (`model:` tiers, YAML `tools:` lists — `code-reviewer`, `software-architect` and `scout` omit write tools and hold sandboxed `run_command`) plus Codex (`codex-model`, `codex-effort`, `codex-sandbox`) and Antigravity bridge (`agy-model`) pins |
| `claude-agents/` | Claude Code role definitions (`model:`, comma `tools:`), bodies kept byte-for-byte identical to `agents/` and pinned by `tests/test_role_pins.py`; the manifest's `agents` list replaces Claude Code's default `agents/` scan, so the Antigravity files never load there (#94) |
| `scripts/` | `agy-agent.sh` and `codex-agent.sh`, the opt-in cross-family bridges ai-review Stage 1c fires |
| `tests/` | pytest suite; every hook, and every script a skill fires, is pinned here |
| `allowed_signers` | The release key's public half: the tagging snippet in `README.md`, "Releasing", signs only with the key it names |
| `devkitw`, `devkit.toml` | devkit's wrapper, copied verbatim from the pinned tag and never edited, and its pin |

## Rules

- **No hook — and no script a skill fires — ships without its tests.**
  A PreToolUse hook that crashes fails open — the tool call proceeds —
  so a broken guard is silent, and the tests are what notices. Test what
  a guard denies _and_ what it deliberately lets through.
- Hooks are stdlib-only Python behind a bash wrapper, which for the two
  Bash guards is also a prefilter, and fail open on any payload they
  cannot parse. Never block a call you cannot read.
  They run under the user's `python3`, not the 3.13 test venv, so hook
  code stays within `hook_lib.FLOOR` (3.10); below it every guard denies,
  naming the floor, and the pruner, a SessionStart hook with no call to
  refuse, exits quietly.
  A call a guard _has_ read, that targets what it protects but whose
  effect it cannot model (a patch it cannot simulate, an Edit whose
  `old_string` it cannot locate), is denied: passing it is the bypass.
  The wrapper starts its `hooks/*.py` script as `python3 -E -s`. `-E`
  ignores every `PYTHON*` variable and `-s` leaves out the user site: a
  module on `PYTHONPATH` named like a stdlib one, a `PYTHONHOME` that
  points nowhere, a `PYTHONSAFEPATH` that hides `hook_lib`, or startup
  code in the user site (a `.pth` file, a `usercustomize.py`) would
  otherwise crash the hook open. (`-I` would also drop the script's
  directory, from which the hooks import `hook_lib`.)
  `tests/hooks/test_hooks_json.py` runs each such registration under a
  shadowing `PYTHONPATH`, a bad `PYTHONHOME` and a user site that exits.
- Keep `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json` and
  `.antigravity-plugin/plugin.json` at the same `name` and `version`.
  Pull requests never change `version` or edit `CHANGELOG.md`; only a deliberate
  release PR does (see "Releasing" below). Claude Code and Codex cache an
  installed copy keyed by `version`, so installs track the `release`
  branch (and Antigravity installs from a `v*` tag), never unreleased
  `main`. Changes to what an installed copy loads — `.claude-plugin/`,
  `.codex-plugin/`, `.antigravity-plugin/`, `hooks.json`, `hooks/`,
  `skills/`, `agents/`, `claude-agents/` and `scripts/` — accumulate on
  `main` until the next release.
- Name no other repository, project or person in shipped files. Anything
  a project needs to say about itself belongs in that project's own
  `AGENTS.md`. The exception is devkit, whose pin and wrapper the build
  needs.
- Python and Markdown are hard-wrapped at 80 columns.
- Tracked `*.sh` scripts pass shellcheck; a `disable` directive carries
  its reason. `devkitw` is exempt: it is vendored verbatim and
  shellchecked upstream.

## Gates

- Every `make` target first runs `./devkitw`, which fetches the pinned
  devkit once per pin (forge access and `ssh-keygen` needed then: it
  verifies the release tag's signature); CI fetches it with the
  `DEVKIT_TOKEN` secret.
- `make lint-repo` — devkit's repository gates (action pins, gitleaks
  over the history and uncommitted changes, markdownlint), plus this
  project's `lint-shell`: shellcheck, pinned in `uv.lock`, over every
  tracked `*.sh`, hung on `lint-repo` as a prerequisite so both hooks
  and CI run it; `tests/test_makefile.py` pins that prerequisite. It ignores
  `SHELLCHECK_OPTS` and every `.shellcheckrc`, so a local run judges
  what CI judges. Needs python3 3.11 or later, node and npm, curl and
  tar, the network on first use, and everything `make install` needs,
  because `lint-shell` syncs `.venv` first. `.markdownlint.jsonc` holds
  this project's profile.
- shellcheck-py ships wheels only for macOS, x86_64 glibc Linux and
  x86_64 Windows, and its marker in `pyproject.toml` installs it only
  there; `tests/test_lock_wheels.py` fails when the locked wheel set
  changes. `no-build-package` keeps uv from building it from source, a
  build that runs an unlocked backend and downloads the binary.
  Elsewhere `make install` and `make test` work, but `lint-shell` fails,
  saying so, and with it `make lint-repo`, `make gate` and both git
  hooks (pre-push never reaches `test`); a shellcheck-py built from
  source earlier is gone after the next `make install`. There, run
  `make test` by hand, then commit and push with `--no-verify`: CI runs
  the gate. An agent bound by the push-gate skill cannot, and hands the
  push to its operator. In an arm64 container on a Mac, run the gates on
  the host instead. x86_64 musl matches the marker but has no wheel, so
  `make install` fails there (#48). uv, msgpack and ruff are on
  `no-build-package` too, so where one ships no wheel `make install`
  fails instead of building it (#49 lists uv's platforms, #71
  msgpack's and ruff's). charset-normalizer, coverage and tomli are
  listed as well, but each ships a pure-Python wheel.
- `make install` — devkit's: installs the uv `uv.lock` pins,
  hash-verified, into devkit's tool cache (never a uv on PATH or in
  `.venv`), then runs `uv sync --locked`, which fails on a `uv.lock`
  stale against `pyproject.toml`; uv fetches CPython 3.13 when none
  is found. Needs python3 3.11 or later. `make lint-repo`, through
  `lint-shell`, and `make test` run it first.
- `make test` — devkit's, after `make install`: checks `.venv`
  against `uv.lock`, then holds the statement and branch coverage of
  `hooks/` to the Makefile's `COVERAGE_FLOOR`. `tests/conftest.py`
  puts `.venv`'s `bin` first on PATH, so the hooks the tests start
  run under the venv's python3, where coverage measures them; in a
  session they run under the user's python3. The floor tests run each
  guard once at 3.8, 3.9 and 3.10, and an import check holds every
  `hooks/*.py` import, function-level ones included, to 3.10's stdlib.
- `make lint` — `lint-repo`, then ruff (80 columns, E501 included;
  target py310, the hooks' floor, and py313 for `tests/`), vulture,
  and devkit's anchored-match and copy-paste gates (`devkit.toml`).
  CI runs `make lint` and `make test`; `make gate` and pre-push run
  `lint-repo test` only, so run `make lint` before pushing.
  `make format` applies ruff.
- `make hooks` once per clone: `pre-commit` runs `make lint-repo`,
  `pre-push` `make lint-repo test`.
- `make gate` — runs the push gate (`lint-repo test`) and records a HEAD
  that passed on a strictly clean tree; pre-push skips that HEAD while
  the tree stays unchanged. A run that records nothing says why.
- `claude plugin validate .` — after any manifest, hook, skill or agent
  change. Expected warnings: the two missing `author` fields, the root
  `CLAUDE.md` not being plugin context (it is this repository's), and
  the plugin-directory check's `ICON_MISSING`. It checks the manifest,
  not which role file a session loads: to confirm that, dispatch a role
  with a probe that calls no tools and read `message.model` from its
  task-output transcript. Probe a role whose two files resolve to
  different models: an `inherit` that resolves to the role's Claude pin
  proves nothing.
- `agy plugin validate .` — after any manifest, hook, skill or agent
  change. Must pass with zero errors. Expected multi-tool warnings: root
  `AGENTS.md` and `hooks/hooks.json` (both are intentionally for other
  tools; Antigravity reads root `hooks.json` and `skills/`/`agents/`).

## Releasing

Only the maintainer cuts a release, by the procedure in `README.md`,
"Releasing". An agent prepares the release pull request of its step 2,
the `version` bump and the `CHANGELOG.md` entry, only when the maintainer
asks for that release, and never tags a release or pushes `release`.
