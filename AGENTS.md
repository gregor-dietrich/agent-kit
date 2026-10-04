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
| `agents/` | Generic role definitions (Claude Code only; Codex plugins carry no agents) |
| `tests/` | pytest suite; every hook is pinned here |

## Rules

- **No hook ships without its tests.** A PreToolUse hook that crashes
  fails open — the tool call proceeds — so a broken guard is silent, and
  the tests are what notices. Test what a guard denies *and* what it
  deliberately lets through.
- Hooks are stdlib-only Python 3.13 plus a bash prefilter, and fail open
  on any payload they cannot parse. Never block a call you cannot read.
  A call a guard *has* read, that targets what it protects but whose
  effect it cannot model (a patch it cannot simulate, an Edit whose
  `old_string` it cannot locate), is denied: passing it is the bypass.
- Keep `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` at the
  same `name` and `version`.
- Name no other repository, project or person in shipped files. Anything
  a project needs to say about itself belongs in that project's own
  `AGENTS.md`.
- Python and Markdown are hard-wrapped at 80 columns.

## Gates

- `make test` — syncs `.venv` from `uv.lock` (bootstrapping the pinned
  uv when none is found) and runs pytest. CI runs the same target.
- `claude plugin validate .` — after any manifest, hook, skill or agent
  change. Expected warnings: the two missing `author` fields, and the
  root `CLAUDE.md` not being plugin context (it is this repository's).
