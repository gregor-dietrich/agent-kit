# agent-kit

A plugin for Claude Code, Codex and Google Antigravity CLI (`agy`) that
carries the parts of an agent setup which are true about _working with an
agent_ rather than about any one project: guard hooks with their tests,
planning and review skills, method rules, and generic agent roles. It is
installed once per machine, at user scope; everything project-specific
stays in each project's own `AGENTS.md`.

## The trap this kit exists to avoid

The setup it was extracted from carried roughly 107k characters of
always-on instruction, and it worked because **every rule in it was paid
for by an incident**. A new project seeded with all of it inherits the
full context cost, none of the earned specificity, and — worst — rules
whose premises were never tested there.

So the kit is deliberately small, and almost none of it is always on:
one short SessionStart note, three guard hooks, a session temp-dir pruner,
and skills that load when their task comes up. It carries the _method_
(mechanize the convention; state what would falsify the decision; give
every finding a terminal destination) and leaves the _instances_ to
accrete in each project the way the originals did.

**Copy the volume and you get cargo cult. Copy the method and you get a
setup that grows the way the original did.**

## What is here

| Component | What it is | Portability |
| --------- | ---------- | ----------- |
| `hooks/pipe_status_guard.py` | Denies reading a gate's exit status through a pipe (`make test \| tail`) | Any repository, either shell; gate list covers make, pytest, Maven, Gradle, npm/pnpm, cargo, go and more |
| `hooks/tea_guard.py` | Denies a `tea` single issue/PR read without `--comments` | Gitea/`tea` only; silent everywhere else |
| `hooks/decisions_status_guard.py` | An agent may draft and amend decisions-log entries but not ratify, de-ratify or delete them | Repositories with a `docs/decisions.md` in the format below; a no-op elsewhere |
| `hooks/prune_session_tmp.py` | At Claude Code and Codex session start (`hooks/hooks.json`; not registered in Antigravity's root `hooks.json`), in a detached background child, removes Claude Code session temp dirs under `claude-<uid>` untouched for 4 days, never the current or a running session. Tracks Claude Code internals as of 2.1.310 and stops pruning silently if they move | Linux; macOS unverified (#73); inert below Python 3.10 |
| `hooks/hook_lib.py` | Shared plumbing: payload parse, deny envelope, shell tokenizer, Claude, Codex and Antigravity path resolution | Internal |
| `hooks/session-context.md` | The four delegation rules that hold on every dispatch, injected at session start | Any repository |
| `skills/delegation` | Pinned-dispatch policy, per-client pins, the judgment threshold, cost reports | Any repository |
| `skills/review-triage` | Context gathering, recording, `novel`/`instance` marks, finding destinations | Any repository; release bar comes from the project's decisions log |
| `skills/debugging`, `skills/design-exploration` | Method: no fix without a root cause; two or three options and the operator's choice for a real design decision | Any repository; boundaries and gates come from the project's rules. |
| `skills/plan-create`, `skills/plan-run` | Decision → closed spec → pinned dispatches → PR | Any repository; gates and PR conventions come from the project's rules |
| `skills/next` | Goal → bundled PRs: reads the tracker, proposes how the work splits into dispatches and PRs, then runs plan-create, plan-run and the push gate, with ai-review before the push under `--review` | Any repository; tracker through `gh`, `glab` or `tea`; PR conventions come from the project's rules |
| `skills/wrap-up` | End of session: reviews the session for knowledge, skill gaps, friction and automation candidates, reports them as a numbered list with a proposed destination each, and edits or files only the items the operator approves by number | Any repository; destinations come from the project's own docs and rules |
| `skills/push-gate` | Which gate a push owes, and how it runs | Any repository; narrower gates come from the project's rules |
| `skills/ai-review` | Multi-agent review with pinned agents, stance-split verification and no finding cap | Any repository; risk paths can be named in the project's `AGENTS.md` |
| `agents/*`, `claude-agents/*` | scout, code-reviewer, software-architect, backend-developer, frontend-developer | Antigravity loads `agents/*` natively (`model:` tiers), Claude Code loads `claude-agents/*` via `.claude-plugin/plugin.json`, Codex spawns `agents/*` on `codex-model` and `codex-effort`; each reads the project's own docs before acting |
| `scripts/agy-agent.sh` | Pinned read-only Antigravity dispatch for ai-review Stage 1c | Opt-in per user via `~/.config/agent-kit/agy-bridge`; needs `agy` 1.5.16 or later |
| `scripts/codex-agent.sh` | Pinned Codex dispatch for ai-review Stage 1c | Opt-in per user via `~/.config/agent-kit/codex-bridge`; needs codex-cli 0.160.0 or later |

### The one that matters most

The pipe-status guard. It targets a genuinely universal failure —
`make test | tail -5` reports **tail's** exit status, so a red gate reads
as green — and prose demonstrably does not fix it: the session that
produced the original had the rule in context, quoted it, and tripped
over it twice. It is a fluent shell habit, and only a check at the moment
of the call reaches it. It is also shell-aware: bash spells the array
`${PIPESTATUS[0]}` and zsh `${pipestatus[1]}`, each is silently empty in
the other shell, and the guard reads `$SHELL` to name the right one.

### The decisions-log format the guard reads

Entries are `## ADR-NNNN — title` headings, each with a
`**Status:** Accepted` or `**Status:** Proposed` marker. An Accepted entry
closes its question; a Proposed one is a draft. An entry decided on
analysis carries a `**Premise:**` (it stays closed only while the premise
holds) and a `**Guard:**` naming what notices when it fails. Agents draft;
the author ratifies.

## Installing

The repository is its own marketplace (`.claude-plugin/marketplace.json`,
plugin at the root). Claude Code:

```sh
claude plugin marketplace add ssh://git@git.vptr.de:222/gregor/agent-kit.git
claude plugin install agent-kit@agent-kit
```

or, per machine through settings, an `extraKnownMarketplaces` entry with
`{"source": "git", "url": "<the URL above>"}` and
`"enabledPlugins": {"agent-kit@agent-kit": true}`.

Codex reads the same marketplace file and `hooks/hooks.json`:

```sh
codex plugin marketplace add ssh://git@git.vptr.de:222/gregor/agent-kit.git
codex plugin add agent-kit@agent-kit
```

Codex holds plugin hooks back until they are trusted: open `/hooks` once
after installing, and again after any update that changes a hook command —
an untrusted hook is indistinguishable, from inside a session, from no
guard at all. Codex plugins carry no agent types; a Codex session
dispatches the five roles by spawning subagents (the delegation skill,
"Pins by client"). That is separate from the opt-in bridges below, which
provide cross-family reviews in Stage 1c.

Antigravity CLI (`agy`) loads `.antigravity-plugin/plugin.json`, root
`hooks.json`, `skills/` and `agents/` natively. Install from a clean
export (a development checkout carries a `.devkit` symlink outside the
tree, which `agy plugin install` refuses to copy):

```sh
tmp=$(mktemp -d)
git archive HEAD | tar -x -C "$tmp"
agy plugin install "$tmp"
rm -rf "$tmp"
```

Under Antigravity's **Orchestrator** mode, the conversation already pairs
a planner model with a faster executor model inside one turn. The bundled
Antigravity roles complement that: the judgment roles (`code-reviewer`
and `software-architect`) stay on your active Orchestrator/planner session
and omit write tools while keeping their sandboxed shell read-only, while
the exploration and writing roles (`scout`, `backend-developer` and
`frontend-developer`) run on a faster tier.

The hooks run under the first `python3` on `PATH` and need 3.10 or newer.
Under an older one — the Command Line Tools `python3` on macOS is 3.9 —
each guard refuses every call that reaches it, with a message naming the
floor, rather than crashing and so letting everything through. The pruner,
a SessionStart hook with no call to refuse, exits quietly and prunes
nothing, so under that `python3` it is inert.

### Cross-family review bridges (opt-in)

`/agent-kit:ai-review` Stage 1c can send a second-opinion review to
`code-reviewer` on another vendor through two opt-in wrappers, each
verifying the pinned model actually ran and reading its pin from
`agents/code-reviewer.md`. Each wrapper sends the review prompt (the
diff, the PR and issue threads, the context digest) to a second vendor,
plus any file that vendor chooses to read, and the preamble itself
points it at files outside the project. So each runs only once you opt
in, with one marker file that covers every project:

- **Antigravity bridge (`scripts/agy-agent.sh`)** — cross-family from
  Claude Code or Codex. Pins `agy-model` from `agents/code-reviewer.md`,
  runs `--sandbox` with `--settings` locking permissions read-only (no
  writes, shell, network or MCP), refuses repositories with project-level
  Antigravity config unless `AGY_AGENT_ALLOW_REPO_CONFIG=1` is set, and
  verifies `model`, `permission_mode`, read-only `tools` and
  `result.status` (and reads token usage) from `agy`'s `stream-json`
  `init` and `result` events. Residual boundary: `agy` has no
  `--ignore-user-config`, so user-level settings and MCP config still
  apply. Needs `agy` 1.5.16 or later and `python3`. Opt in with:

  ```sh
  mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/agent-kit"
  touch "${XDG_CONFIG_HOME:-$HOME/.config}/agent-kit/agy-bridge"
  ```

- **Codex bridge (`scripts/codex-agent.sh`)** — cross-family from Claude
  Code or Antigravity. Pins `codex-model`, `codex-effort` and
  `codex-sandbox` from `agents/code-reviewer.md` and verifies them against
  the session banner. Needs codex-cli 0.160.0 or later and passes
  `--ignore-user-config`: your `$CODEX_HOME/config.toml` is not loaded,
  so a custom provider or proxy setup cannot be used with it, while auth
  still comes from `CODEX_HOME`. Opt in with:

  ```sh
  mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/agent-kit"
  touch "${XDG_CONFIG_HOME:-$HOME/.config}/agent-kit/codex-bridge"
  ```

When both opt-in files exist in a Claude Code session, Stage 1c prefers
`agy-bridge`. Each marker file lives outside every checkout, so no branch
can opt you in. A project that names its own bridge keeps it, unless the
checkout changes that bridge.

## Warning: a broken hook is a silent hook

A `PreToolUse` hook that crashes **fails open** — the tool call proceeds.
So a guard broken by a bad edit is not loud, it is inert, and you find out
when the thing it guarded against happens again. Every hook here is pinned
by tests of what it denies _and_ of what it deliberately lets through, and
both `hooks/hooks.json` and root `hooks.json` by a test that runs each
registered command the way the clients do: each guard must deny, and the
pruner (registered in `hooks/hooks.json`) must remove a stale session.
Change a hook only with its tests.

## Known limits

- The decisions guard vets the edit tools only (Claude Write/Edit, Codex
  `apply_patch`, and Antigravity file edit tools), reading markers as they
  render. Shell commands that write the log are not vetted, by design: a
  Bash arm was removed because the ways a shell can write a file are
  open-ended and chasing them was not worth it. Code review catches
  undesired status changes.
- Hooks read no project configuration and detect no project kind yet;
  that lands with the first hook that branches on one.

## Developing

See [AGENTS.md](AGENTS.md). `make lint` runs devkit's repository gates,
shellcheck, ruff, vulture and devkit's Python gates; `make test` runs
the suite under a coverage floor. Both first sync a uv-locked `.venv`,
installing the pinned uv hash-verified when devkit's cache lacks it.
CI runs both. Every `make` target fetches the pinned devkit on first
use, which needs forge access.
