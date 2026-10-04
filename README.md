# agent-kit

A plugin for Claude Code, with a Codex twin, that carries the parts of an
agent setup which are true about _working with an agent_ rather than
about any one project: guard hooks with their tests, planning and review
skills, method rules, and generic agent roles. It is installed once per
machine, at user scope; everything project-specific stays in each
project's own `AGENTS.md`.

## The trap this kit exists to avoid

The setup it was extracted from carried roughly 107k characters of
always-on instruction, and it worked because **every rule in it was paid
for by an incident**. A new project seeded with all of it inherits the
full context cost, none of the earned specificity, and — worst — rules
whose premises were never tested there.

So the kit is deliberately small, and almost none of it is always on:
one short SessionStart note, three guard hooks, and skills that load when
their task comes up. It carries the _method_ (mechanize the convention;
state what would falsify the decision; give every finding a terminal
destination) and leaves the _instances_ to accrete in each project the
way the originals did.

**Copy the volume and you get cargo cult. Copy the method and you get a
setup that grows the way the original did.**

## What is here

| Component | What it is | Portability |
| --------- | ---------- | ----------- |
| `hooks/pipe_status_guard.py` | Denies reading a gate's exit status through a pipe (`make test \| tail`) | Any repository, either shell; gate list covers make, pytest, Maven, Gradle, npm/pnpm, cargo, go and more |
| `hooks/tea_guard.py` | Denies a `tea` single issue/PR read without `--comments` | Gitea/`tea` only; silent everywhere else |
| `hooks/decisions_status_guard.py` | An agent may draft and amend decisions-log entries but not ratify, de-ratify or delete them | Repositories with a `docs/decisions.md` in the format below; a no-op elsewhere |
| `hooks/hook_lib.py` | Shared plumbing: payload parse, deny envelope, shell tokenizer, Claude and Codex path resolution | Internal |
| `hooks/session-context.md` | The four delegation rules that hold on every dispatch, injected at session start | Any repository |
| `skills/delegation` | Pinned-dispatch policy, the judgment threshold, cost reports | Any repository |
| `skills/review-triage` | Context gathering, recording, `novel`/`instance` marks, finding destinations | Any repository; release bar comes from the project's decisions log |
| `skills/plan-create`, `skills/plan-run` | Decision → closed spec → pinned dispatches → PR | Any repository; gates and PR conventions come from the project's `AGENTS.md` |
| `skills/ai-review` | Multi-agent review with pinned agents, stance-split verification and no finding cap | Any repository; risk paths can be named in the project's `AGENTS.md` |
| `agents/*` | scout, code-reviewer, software-architect, backend-developer, frontend-developer | Claude Code only; each reads the project's own docs before acting |

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
guard at all. Codex plugins carry no agents, so the five roles are Claude
Code only.

The hooks run under the first `python3` on `PATH` and need 3.10 or newer.
Under an older one — the Command Line Tools `python3` on macOS is 3.9 —
each guard refuses every call that reaches it, with a message naming the
floor, rather than crashing and so letting everything through.

## Warning: a broken hook is a silent hook

A `PreToolUse` hook that crashes **fails open** — the tool call proceeds.
So a guard broken by a bad edit is not loud, it is inert, and you find out
when the thing it guarded against happens again. Every hook here is pinned
by tests of what it denies _and_ of what it deliberately lets through, and
`hooks.json` by a test that runs each registered command the way the
clients do and requires a deny. Change a hook only with its tests.

## Known limits

- The decisions guard vets the edit tools only (Write, Edit, apply_patch),
  reading markers as they render. Shell commands that write the log are
  not vetted, by design: a Bash arm was removed because the ways a shell
  can write a file are open-ended and chasing them was not worth it. Code
  review catches undesired status changes.
- Hooks read no project configuration and detect no project kind yet;
  that lands with the first hook that branches on one.
- Two method rules — debugging, and design exploration — are held back
  until the repository's licence is settled, because they adapt
  MIT-licensed material whose notice must travel with them.

## Developing

See [AGENTS.md](AGENTS.md). `make test` syncs a uv-locked `.venv`
(bootstrapping the pinned uv when none is installed) and runs the suite;
CI runs the same target.
