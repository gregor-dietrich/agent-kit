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
one short SessionStart note, four guard hooks, a session temp-dir pruner,
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
| `hooks/tea_guard.py` | Denies a `tea` single issue/PR read without `--comments`, and a `tea` comment or PR write that carries a closing or reopen keyword before `#N` or text it cannot read (admits `Closes #N` lines in a PR description) | Gitea/`tea` only; silent everywhere else |
| `hooks/commit_guard.py` | Denies a `git commit` or `git merge` whose message carries a closing or reopen keyword before `#N`, or whose message it cannot read | Any repository; silent on commands that are not a commit or merge |
| `hooks/decisions_status_guard.py` | An agent may draft and amend decisions-log entries but not ratify, de-ratify or delete them | Repositories with a `docs/decisions.md` in the format below; a no-op elsewhere |
| `hooks/prune_session_tmp.py` | At Claude Code and Codex session start (`hooks/hooks.json`; not registered in Antigravity's root `hooks.json`), in a detached background child, removes Claude Code session temp dirs under `claude-<uid>` untouched for 4 days, never the current or a running session. Tracks Claude Code internals as of 2.1.310 and stops pruning silently if they move | Linux; macOS unverified (#73); inert below Python 3.10 |
| `hooks/hook_lib.py` | Shared plumbing: payload parse, deny envelope, shell tokenizer, the closing-keyword and expansion patterns, git subcommand reading, Claude, Codex and Antigravity path resolution | Internal |
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
| `scripts/agy-agent.sh` | Pinned Antigravity dispatch for ai-review Stage 1c; rejects a run that called any tool but `read_file` | Opt-in per user via `~/.config/agent-kit/agy-bridge`; needs `agy` 1.5.18 or later |
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

### What the commit guard reads

The commit guard reads `git commit` and `git merge` messages given with
`-m`/`--message`, literally or as a quoted `$(cat <<'EOF' ... EOF)`
heredoc (for `commit`, also its `--trailer` values), and denies one
carrying a closing or reopen keyword before `#N`. It denies as unreadable
a message holding a `$` or a backtick outside such a heredoc, even one the
shell would leave literal; one taken from `-F`/`--file` (stdin included)
or from a template with no `-m`; and one left to the editor. It does not
read messages git carries or prepares (`--amend --no-edit`, `-C`,
`--fixup`, merge's own message, `merge --continue`, `revert`,
`cherry-pick`, `rebase`), abbreviated long options (`--mess=`), git
aliases, an expansion outside the message values (a variable argument can
supply `-m` itself), commands the shared shell reading does not see,
commits made outside the agent's shell tool, or the squash and merge
messages the forge composes. `hooks/commit_guard.py` lists the limits in
full.

### The decisions-log format the guard reads

Entries are `## ADR-NNNN — title` headings, each with a
`**Status:** Accepted` or `**Status:** Proposed` marker. An Accepted entry
closes its question; a Proposed one is a draft. An entry decided on
analysis carries a `**Premise:**` (it stays closed only while the premise
holds) and a `**Guard:**` naming what notices when it fails. Agents draft;
the author ratifies.

## Installing

The repository is its own marketplace (`.claude-plugin/marketplace.json`,
plugin at the root). Releases are published on the protected `release`
branch and tagged `vX.Y.Z`; `main` carries unreleased work between
releases, so installs track `release` (or a release tag) rather than
`main`.

Claude Code — configure the marketplace per machine in
`~/.claude/settings.json` with `"ref": "release"`:

```json
{
  "extraKnownMarketplaces": {
    "agent-kit": {
      "source": {
        "source": "git",
        "url": "ssh://git@git.vptr.de:222/gregor/agent-kit.git",
        "ref": "release"
      }
    }
  },
  "enabledPlugins": {
    "agent-kit@agent-kit": true
  }
}
```

Update with `claude plugin marketplace update agent-kit` (followed by
`claude plugin update agent-kit@agent-kit` if auto-update is off).
`claude plugin marketplace add` is no route to a release: it accepts no
`--ref` flag, so a source it takes tracks `main` and caches unreleased
commits under the previous release's version, and it rejects this
`ssh://` URL as an invalid source format (Claude Code 2.1.332).

A machine that registered the marketplace without the ref tracks `main`
and needs the ref in two places. Added to `settings.json` alone, it
leaves the registered source and the settings entry in disagreement:
Claude Code ignores the marketplace, `claude plugin list` reports
agent-kit as failed to load, and no guard runs, with nothing inside a
session saying so. Add the same `"ref": "release"` to the `source` of
the `agent-kit` entry in `~/.claude/plugins/known_marketplaces.json`,
run `claude plugin marketplace update agent-kit`, and check that
`claude plugin list` shows the plugin enabled. That switch was measured
on Claude Code 2.1.332; whether a new session repairs the disagreement
by itself was not.

Codex reads the same marketplace file and `hooks/hooks.json`; pin it to
`release`:

```sh
codex plugin marketplace add --ref release ssh://git@git.vptr.de:222/gregor/agent-kit.git
codex plugin add agent-kit@agent-kit
```

Refresh with `codex plugin marketplace upgrade agent-kit`. Codex holds
plugin hooks back until they are trusted: open `/hooks` once after
installing, and again after any update that changes a hook command — an
untrusted hook is indistinguishable, from inside a session, from no guard
at all. Codex plugins carry no agent types; a Codex session dispatches
the five roles by spawning subagents (the delegation skill, "Pins by
client"). That is separate from the opt-in bridges below, which provide
cross-family reviews in Stage 1c.

Antigravity CLI (`agy`) loads `.antigravity-plugin/plugin.json`, root
`hooks.json`, `skills/` and `agents/` natively. Install or update from a
clean export of a release tag (a development checkout carries a `.devkit`
symlink outside the tree, which `agy plugin install` refuses to copy):

```sh
git fetch origin --tags
tmp=$(mktemp -d)
git archive vX.Y.Z | tar -x -C "$tmp"
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
  runs `--sandbox` with `--settings` that deny writes and shell commands,
  refuses repositories with project-level Antigravity config unless
  `AGY_AGENT_ALLOW_REPO_CONFIG=1` is set, and verifies `agy`'s
  `stream-json` events: `model` and `permission_mode` in `init`, every
  step, and `result.status` (it also reads token usage). The checks run
  as the events arrive: the bridge stops `agy` at the first step that is
  neither a plain step nor a `read_file` call, at an event it does not
  know or a line it cannot read, and at a mismatched `init`, and exits 3.
  This detects and rejects, it does not prevent: on 1.5.18 the settings
  were measured to deny writes and shell commands only (web search and
  subagent tools ran under every deny rule tried), so a call of another
  tool, and any call queued behind it, may run before the stop, a
  subagent's own calls never show in the stream, and rejecting the run
  undoes none of it. A CLI newer than the measured
  version runs with a notice; a tool call it reported in a new shape
  would pass. Residual boundary: `agy` has no `--ignore-user-config`, so
  user-level settings and MCP config still apply. Needs `agy` 1.5.18 or
  later and `python3`. Opt in with:

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

## Versioning

From `1.0.0` on, releases follow semantic versioning, and the part of
the version that changes says what an update asks of you. Releases
before `1.0.0` promise nothing.

A **major** release is one in which something you or a project wrote,
or a name you type, stops working, or a protection is taken away:

- the hooks' Python floor rises above 3.10;
- a supported client (Claude Code, Codex, Antigravity) is dropped;
- a skill, a role, or an argument a skill's `argument-hint` lists is
  removed or renamed;
- a hook is removed, or a guard stops denying, or a bridge stops
  rejecting, what its row in "What is here" says it denies or rejects;
- a role that ships without write tools gains one;
- the decisions-log format above changes: its `## ADR-NNNN` headings,
  its `**Status:**` markers, or its `**Premise:**` and `**Guard:**`
  lines;
- an opt-in marker file is renamed or removed, or an environment
  variable that a hook or bridge reads and this README names is renamed
  or no longer read;
- the marketplace name, the plugin id `agent-kit@agent-kit`, the
  `release` branch or the `vX.Y.Z` tag scheme is renamed.

A **minor** release may make the kit do more, refuse more, or need a
step from you when you update:

- a guard denies, or a bridge rejects, what the previous release let
  through: a new guard or rule, or an existing rule that reaches more
  spellings of the call it names;
- the session temp-dir pruner removes more than it did;
- a hook command changes, which Codex holds back until you trust it
  again in `/hooks`;
- a skill, role, hook or opt-in is added;
- an opt-in bridge needs a newer version of its CLI;
- a role's model pin changes, or a skill, a role or the SessionStart
  note tells an agent to do something different;
- `allowed_signers` names a new release key.

A **patch** release asks nothing of you and refuses nothing the previous
release let through: a guard that stops denying a call it denied by
mistake, a crash fixed, a clearer message, a wording change that
instructs the same.

A guard that newly denies a call is minor, not major: the deny reaches
the agent inside the session, with its reason, before the call runs,
and nothing you wrote has to change. The `CHANGELOG.md` entry of a minor
or major release names each call newly denied, each thing that stops
working and each step the update needs.

Outside the promise, and free to change in any release:
`hooks/hook_lib.py`, the bridge scripts' arguments and exit statuses
and the names of the role frontmatter keys they read (only this kit's
own skills call them), section headings inside skills, the `.plans/`
working files, and the client versions this README gives as measured:
they say where behaviour was measured and are not minimums. (A bridge's
CLI floor is a minimum, and raising it is minor, as above.) A move of
the repository is outside it too, since an install on the old address
never sees the release that announces it.

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

## Releasing

Only the maintainer cuts a release. Tags are never moved or reused; fix
a broken release with a new patch release. Tag with the snippet in
step 4, not with `make tag`: that target prompts for a version and signs
with the ambient git signing key, where a release tag takes its version
from the manifests and is signed with a dedicated SSH release key
(`~/.ssh/id_agent_kit`, overridable via `AGENT_KIT_RELEASE_KEY`).

1. Confirm at least one installed-copy path changed since the last tag
   (`git log <last-tag>..origin/main --stat`). Do not cut a release with
   nothing shippable to list.
2. Open a release pull request targeting `main` that:
   - bumps `version` in `.claude-plugin/plugin.json`,
     `.codex-plugin/plugin.json` and `.antigravity-plugin/plugin.json` to
     `X.Y.Z`, raising the part "Versioning" above names for the changes
     since the last release (`pyproject.toml` is test-environment
     metadata and is not bumped);
   - adds a `## [X.Y.Z] - YYYY-MM-DD` section to `CHANGELOG.md`
     summarizing user-facing changes since the last release, with what
     "Versioning" asks of a minor or major entry (no `## [Unreleased]`
     section; ordinary PRs never edit `CHANGELOG.md`);
   - passes `make lint`, `make gate`, `claude plugin validate .` and
     `agy plugin validate .`.
3. Merge the release pull request to `main` with no other pull request
   landing between it and tagging. The forge merges fast-forward only,
   so the pull request's commits land as they are and the tag goes on
   the last of them.
4. Tag with the snippet below, from the clone's root. It takes no
   version: it tags the one the three manifests on `main` declare, so it
   runs only after step 3. Before that the manifests still name the last
   release, and it stops at "tag ... already exists". It needs git 2.35
   or later, ssh-keygen (OpenSSH 8.2 or later), and the release key's
   private key file
   (`SHA256:dYsHxqttXNQpFhcKpXte7CSrVi2uHdexcEBomV0SHCE`) at
   `~/.ssh/id_agent_kit`, or at the path `AGENT_KIT_RELEASE_KEY` names;
   no ssh-agent is needed. It switches to `main`, fast-forwards it to
   the remote's, refuses when the two still differ, the tree is not
   clean or the tag exists, and signs with that file only when its
   public key is the one `allowed_signers` names. It then verifies the
   new tag against `allowed_signers` and deletes it when another key
   signed it, so only a tag the pinned key signed is pushed: git signs
   with the key a `.pub` file beside the key file names, and lets an
   ssh-agent that holds that key sign. It pushes the tag, deleting the
   local one when that push fails, and fast-forwards the protected
   `release` branch to the tagged commit:

   ```sh
   git switch -q main && git pull -q --ff-only origin main &&
     { [ "$(git rev-parse HEAD)" = "$(git rev-parse FETCH_HEAD)" ] ||
       { echo "main differs from origin's main" >&2; false; }; } &&
     { [ -z "$(git status --porcelain --untracked-files=all --ignore-submodules=none)" ] ||
       { echo "working tree is not clean" >&2; false; }; } &&
   tag=v$(python3 -c 'import json, sys; vs = {json.load(open(p))["version"].strip() for p in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", ".antigravity-plugin/plugin.json")}; len(vs) == 1 or sys.exit(f"manifest versions differ: {vs}"); v = next(iter(vs)); print(v or sys.exit("plugin.json declares no version"))') &&
     { ! git rev-parse --verify --quiet "refs/tags/$tag" >/dev/null ||
       { echo "tag $tag already exists: main's manifests declare ${tag#v}; a new release needs its pull request merged first" >&2; false; }; } &&
   key=$(sed -n 's/^agent-kit-release namespaces="git" \(.*\)$/\1/p' allowed_signers) &&
     : "${key:?allowed_signers carries no agent-kit-release line}" &&
   file=${AGENT_KIT_RELEASE_KEY:-$HOME/.ssh/id_agent_kit} &&
     { [ "$(ssh-keygen -y -f "$file" | cut -d' ' -f1,2)" = "$key" ] ||
       { echo "$file is not the release key allowed_signers names" >&2; false; }; } &&
     git -c gpg.format=ssh -c user.signingKey="$file" tag -a -s "$tag" -m "agent-kit $tag" &&
     { git -c gpg.ssh.allowedSignersFile=allowed_signers verify-tag "$tag" ||
       { git tag -d "$tag" >/dev/null; echo "$tag is not signed by the release key allowed_signers names; deleted local $tag" >&2; false; }; } &&
     { git push origin "$tag" ||
       { git tag -d "$tag" >/dev/null; echo "tag push failed; deleted local $tag" >&2; false; }; } &&
     git push origin "${tag}^{commit}:refs/heads/release"
   ```

   When only the last push fails, the tag is already published and a
   rerun stops at "tag ... already exists": push `release` alone, with
   `git push origin "vX.Y.Z^{commit}:refs/heads/release"`.

   The release key signs agent-kit's release tags and nothing else: a
   signature binds the tag object (its commit, type, tag name, tagger
   and message) and the namespace, not the repository. To check a tag
   against the pinned key, run
   `git -c gpg.ssh.allowedSignersFile=allowed_signers verify-tag vX.Y.Z`.
   Tags before `v0.6.0` carry no signature.
