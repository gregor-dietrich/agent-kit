# agent-kit — working in this repository

agent-kit is a plugin installed once per machine at user scope, so every
hook, skill and agent here runs in **every** repository its user opens.
That sets the bar for each change: nothing project-specific, and nothing
that can break silently.

## Layout

| Path | What it is |
| ---- | ---------- |
| `.claude-plugin/` | Claude Code plugin manifest, and the marketplace manifest that makes this repo installable |
| `.codex-plugin/plugin.json` | The Codex twin: same name and version, plus Codex's `interface` block |
| `hooks/` | `hooks.json` (read by both clients), the guard scripts it registers, and `session-context.md`, the only text injected into every session |
| `skills/` | One `<name>/SKILL.md` per skill, shared by both clients |
| `agents/` | Generic role definitions (Claude Code only; Codex plugins carry no agents); code-reviewer's `codex-*` keys pin the Codex bridge |
| `scripts/` | `install.sh`, the dev venv helper `make install` runs, and `codex-agent.sh`, the opt-in Codex bridge ai-review Stage 1c fires |
| `tests/` | pytest suite; every hook, and every script a skill fires, is pinned here |
| `devkitw`, `devkit.toml` | devkit's wrapper, copied verbatim from the pinned tag and never edited, and its pin |

This repository opts in to that bridge for its own reviews:

<!-- agent-kit:codex-bridge -->

## Rules

- **No hook — and no script a skill fires — ships without its tests.**
  A PreToolUse hook that crashes fails open — the tool call proceeds —
  so a broken guard is silent, and the tests are what notices. Test what
  a guard denies _and_ what it deliberately lets through.
- Hooks are stdlib-only Python plus a bash prefilter, and fail open on
  any payload they cannot parse. Never block a call you cannot read.
  They run under the user's `python3`, not the 3.13 test venv, so hook
  code stays within `hook_lib.FLOOR` (3.10); below it every guard denies,
  naming the floor.
  A call a guard _has_ read, that targets what it protects but whose
  effect it cannot model (a patch it cannot simulate, an Edit whose
  `old_string` it cannot locate), is denied: passing it is the bypass.
- Keep `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` at the
  same `name` and `version`, and bump that version past main's in every
  change that lands. Claude Code caches an installed copy of the whole
  tree under its version and updates only when the version moves, so a
  change shipped at an unchanged version never reaches a machine that
  already has it, not even through a reinstall; Codex keys its cache by
  version too. Two branches bumping to the same number merge without a
  conflict, so check main's version before merging.
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
  devkit once per pin (forge access needed then); CI fetches it with the
  `DEVKIT_TOKEN` secret.
- `make lint-repo` — devkit's repository gates (action pins, gitleaks
  over the history and uncommitted changes, markdownlint), plus this
  project's `lint-shell`: shellcheck, pinned in `uv.lock`, over every
  tracked `*.sh`, hung on `lint-repo` as a prerequisite so both hooks
  and CI run it. It ignores `SHELLCHECK_OPTS` and every `.shellcheckrc`,
  so a local run judges what CI judges. Needs python3 3.11 or later,
  node and npm, curl and tar, the network on first use, and everything
  `make install` needs, because `lint-shell` syncs `.venv` first.
  `.markdownlint.jsonc` holds this project's profile.
- `make install` — syncs `.venv` exactly from `uv.lock`, removing
  anything installed into it by hand. It takes uv from PATH, then
  `.venv`, else bootstraps the pinned uv with `python3 -m venv` and pip;
  uv fetches CPython 3.13 when none is found. `make test` and
  `make lint-repo` both run it first.
- `make test` — runs pytest after `make install`. CI runs `lint-repo`
  and `test`.
- `make hooks` once per clone: `pre-commit` runs `make lint-repo`,
  `pre-push` `make lint-repo test`.
- `make gate` — runs the push gate (`lint-repo test`) and records a HEAD
  that passed on a strictly clean tree; pre-push skips that HEAD while
  the tree stays unchanged. A run that records nothing says why.
- `claude plugin validate .` — after any manifest, hook, skill or agent
  change. Expected warnings: the two missing `author` fields, and the
  root `CLAUDE.md` not being plugin context (it is this repository's).
