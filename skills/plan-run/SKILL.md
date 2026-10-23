---
name: plan-run
description: "Execution of a closed spec — takes a /agent-kit:plan-create plan (a file from .plans/, or a <proposed_plan> block in the conversation), a tracker issue that already states its design, or a decision just made in conversation, groups the work into closed specs, and dispatches pinned agent-kit:backend-developer / agent-kit:frontend-developer subagents rather than defaulting to implementation in the steering loop. Reads every returned diff, runs the project's gates, commits (and pushes and opens the PR where the project's AGENTS.md makes that part of the ask), and reports the dispatch cost. Use whenever asked to execute a plan or implement work whose design is already settled — not to decide a design, which is /agent-kit:plan-create's job."
argument-hint: "[plan file | issue #]"
---

Execute a closed spec: **$ARGUMENTS**

(If no arguments were given, look for a plan matching the conversation's
target — a `<proposed_plan>` block in the conversation, or a file in
`.plans/` — and confirm it before dispatching. With neither a plan nor a
settled design, stop — see "When this skill applies".)

## Why this skill exists

The `agent-kit:delegation` skill says the steering loop plans, dispatches,
reads every returned diff, and decides what lands — and SHOULD NOT
implement non-trivial changes itself. Nothing enforces that: a PreToolUse
guard was evaluated and rejected, because "is this change big enough to
delegate?" has no single right answer, so a faithful mechanized guard does
not exist. **Do not re-propose that hook.**

What a skill earns over the policy is **spec closure**, not routing — a
skill has to be invoked, so on routing grounds alone the policy already
dominates it. What this skill adds is the discipline of grouping work into
specs a competent stranger could execute before any of it is dispatched,
which pays off whichever model executes. Making the dispatch structure
explicit at the moment of use, and the cost visible afterwards, follows
from that rather than justifying it.

## Dispatch policy

- Every dispatch MUST name a pinned agent type — here,
  `agent-kit:backend-developer` or `agent-kit:frontend-developer`
  (writing), and `agent-kit:code-reviewer` or
  `agent-kit:software-architect` (read-only judgment) where a return needs
  vetting, or the project's own type for the same role, which takes
  precedence here and wherever a stage below names an agent-kit type
  (`agent-kit:delegation`, "The policy"). The pin is the one for the
  client you run in (`agent-kit:delegation`, "Pins by client") — **read
  it** from the agent's definition, do not recall it from memory or from
  this skill.
- General-purpose (unpinned) dispatches are **FORBIDDEN**, as are the
  harness's built-in agent types: neither carries a `model:` pin, so a
  bare dispatch silently inherits the steering model. That looks like
  delegation while buying nothing. The `agent-kit:delegation` skill, "The
  policy", carries the reasoning **and the override rule** for a harness
  workflow that leaves no other choice.
- The steering loop orchestrates: it dispatches, **reads every returned
  diff**, runs the gates, commits, and reports. Subagents never commit and
  never re-delegate. Never merge a subagent diff unread.
- **The `agent-kit:delegation` skill's "The judgment threshold" decides
  what is dispatched and what stays in the steering loop, and that skill
  owns it.** Read it; do not restate or re-derive it. It cuts in both
  directions, and Stage 5 says which way each item went.

## When this skill applies

Only to a **closed spec** — one a competent stranger could execute without
asking. That means a `/agent-kit:plan-create` plan (its `.plans/` file, or
its `<proposed_plan>` block under Codex), an issue that already states its
design, or a decision the operator has just made in conversation.

If the work still carries a decision with more than one defensible answer,
this is the wrong skill: the route is `/agent-kit:plan-create`. Do not
resolve the design in flight — see "Stop conditions".

## Stage plan

State to the operator, before dispatching anything: the plan being
executed, the work items and their grouping, and the planned dispatch
count. The declared bounds are the contract.

### Stage 0 — Re-read the ground (main loop, zero dispatches)

A plan is working state and the tree moves under it. Before executing:

- read the plan, or the issue **with its comments** (with `tea`, pass
  `--comments`: every other single-issue view silently omits them, and the
  tea guard denies a read without the flag). A `/agent-kit:plan-create`
  plan, whether a `.plans/` file or a `<proposed_plan>` block that skill
  emitted in this conversation, carries the five elements it requires
  ("The plan"); a missing one — no work items, no testing story, no
  stated open questions — hands back to `/agent-kit:plan-create` rather
  than being filled in here. A reference that resolves to neither text
  in the plan nor a durable source (an issue or its comments, the code,
  a doc, a commit), such as "the design's wording", leaves it no closed
  spec either: ask the operator for the missing text rather than writing
  it here. Any other `<proposed_plan>` block, such as
  one Codex's plan mode wrote on its own or one pasted in, is a decision
  just made in conversation. Such a decision and an issue do not carry
  the five by construction, so derive the work items and the testing
  story, or confirm the ones they list, before Stage 1 and say that you
  did. Never rebuild a plan from memory or a summary of one: a session
  that no longer holds the block or the file has no plan, and stops;
- check what has changed since the plan was written: `git log` against
  the base, and whether any file the plan names has moved;
- re-check the project's decisions log, if it keeps one, for an entry the
  plan would now contradict;
- confirm the landing branch: commit on the branch that is checked out;
  when the default branch is checked out, branch off it rather than
  committing to it, unless the project's rules say otherwise.

Say what moved. A plan whose ground has shifted goes back to
`/agent-kit:plan-create` for the affected part, not through here on the
assumption that it still holds.

### Stage 1 — Group into closed specs (main loop)

Group the work items into dispatches that are **small, with closed
specs**: one purpose each, a stated interface, and enough context that the
subagent asks nothing. Split by the **layer** that owns the files — UI
versus non-UI — since that decides the agent type. Component or package
membership decides only which `AGENTS.md` and rule files bind, and
whether a group is too big to hand over in one piece.

Require each dispatch to report **what it was unsure about**, not only
what it did. That return is the most useful thing a subagent produces and
it is lost unless the prompt asks for it.

### Stage 2 — Dispatch (the writing agents)

- `agent-kit:frontend-developer` for user-facing UI — pages, components,
  layout, styling; `agent-kit:backend-developer` for everything else —
  services, configuration, data, integrations, tooling. Whichever owns the
  touched files.
- Run **concurrent** writing dispatches in isolated worktrees, using the
  Agent tool's isolation option where the harness offers one (check the
  tool's own parameters rather than recalling a spelling). Condition it on
  concurrency, not on a forecast that two agents would collide: the
  forecast is what fails, a clobbered edit surfaces as an absence rather
  than in a returned diff, and the cost on the other side is only setup
  time and disk. A sequential run needs none of it. Every worktree shares
  the clone's git config and hooks directory, so a hook installed from
  one is the hook every push runs: no worktree setup installs git hooks
  or changes git config (`make hooks`, `git config`, `git lfs install`),
  and each isolated dispatch's prompt says so.
- **Where auto mode is on, or the harness offers no isolation option,
  keep worktrees under `.worktrees/`.** The harness's isolation option
  puts its worktrees under `.claude/worktrees/`,
  and Claude Code's auto mode treats everything under `.claude/` as agent
  configuration: it refuses Edit, Write and some Read calls there with
  "The user doesn't want to take this action right now", which reads like
  an unanswered prompt rather than a refusal. Create the worktree yourself
  from the landing branch's tip, with
  `git worktree add --detach .worktrees/<name> HEAD`, and pass its
  absolute path in the dispatch prompt. `.worktrees/` must be ignored —
  unignored, the nested checkout shows as untracked and Stage 4's clean
  tree is never clean — so add it to the file
  `git rev-parse --git-path info/exclude` names where the project's
  `.gitignore` lacks it. Set the worktree up as the project's `AGENTS.md`
  says; a virtualenv, for one, records absolute paths, so each worktree
  needs its own. Once the commit that carries its work exists, remove it with
  `git worktree remove --force .worktrees/<name>`: the harness cleans up
  only its own worktrees, and the work in this one was never committed.
- When a dispatch runs isolated, say how its work reaches the tree Stage 4
  gates and commits. Subagents never commit, so the work sits uncommitted
  in the worktree, its new files untracked.
  1. Wait until the dispatch has ended (`agent-kit:delegation`, "The
     policy").
  2. Stage it in the worktree: `git -C <worktree> add -A`.
  3. Write `git -C <worktree> diff --cached --binary --no-color
     --no-ext-diff --no-textconv --src-prefix=a/ --dst-prefix=b/` to its
     own `mktemp` file, one per worktree; the pins make the patch immune
     to a user's `color.ui`, `diff.noprefix` and textconv drivers.
  4. List what the text cannot show, `git -C <worktree> diff --cached
     --numstat --summary` (a `-` `-` row is binary; `--summary` shows mode,
     symlink and submodule changes), and accept each only where the spec
     names it. Then read the file in full.
  5. Apply it to the landing tree with `git apply --whitespace=nowarn`
     (atomic; the flag overrides an `apply.whitespace=fix` that would
     rewrite lines silently; never `--reject` or `--3way`): what lands is
     exactly what was read. The steering loop resolves a conflict between
     two worktrees' patches as its own edit.
  6. Before committing, and before the worktree is removed, repeat steps 2
     and 3 in the worktree into a second file and `cmp` the two. Run no
     gate in the worktree after step 3: its artifacts would show as a
     difference. A difference means the agent was still writing or
     something else changed the worktree: read it for its cause. To take
     the new diff, revert what was applied since, newest first
     (`git apply -R` per patch file; a conflict resolved by hand is undone
     by hand), go back to step 1, and run the gates again on the result.

  The landing tree is the one the gates run against, and an isolated
  result that never lands there is not in what gets pushed. Isolation
  covers the tree, not the clone or the user: the steps above check what
  a dispatch wrote to its tree, not git config, hooks or anything else its
  shell could reach, and it was never a security boundary.
- Escalate a model tier only on failure — a second red gate run, or a diff
  needing rewrite. Do not pre-empt.

Soft cap **~5 writing dispatches**; past that, say so and get confirmation
before going further. This is the only dispatch class that writes to the
tree, and the most expensive one — so unlike a review fan-out, where the
orchestrator picks the count, here the work picks it, and a plan needing
more than a handful of writers is usually a plan that wanted decomposing
(`/agent-kit:plan-create`, "Size the scope here") rather than a bigger
fan-out. Splitting one work item across two dispatches counts as two.

### Stage 3 — Read back and verify (main loop, plus optional dispatch)

Read every returned diff in full. Where a return is large or touches a
risk-carrying path, an `agent-kit:code-reviewer` dispatch may vet it — or
an `agent-kit:software-architect` one where what needs vetting is a
boundary rather than the code across it. The `agent-kit:review-triage`
skill, "Scope", bounds that pass: an in-loop verification pass inside an
implementation session MUST NOT record outside its loop. No PR comment, no
`novel`/`instance` marks; findings are acted on or dropped in-session. The
one exception is a finding about code **outside** the diff being verified,
which is still reported and triaged.

What counts as read, and that a report's **Changed** and **Gates** lines
are claims, not evidence, is the `agent-kit:delegation` skill's, "The
policy". An edit the report describes but the diff lacks did not happen. A
Gates line says where to look and does not replace the gates Stage 4 runs
on the landing tree. Where no push follows, the landing tree runs,
before the commit, the gate that executes the delegated code (the
project's tests, not only a fast gate that may be lint alone); where a
push follows, the push gate covers it. Neither a report's green nor a
worktree's says anything about the landing tree.

### Stage 4 — Gates, commit, PR (only as far as the ask covers)

Invoking this skill is the ask to _execute_: commit the work. Push and
open the PR only when the ask covers it — being handed an issue to
implement counts as that ask only where the project's `AGENTS.md` says so.
Otherwise commit, then say what is uncommitted and what a push would
carry, rather than pushing unasked. Hold the push too whenever the run
implies more commits are still coming.

The gates are the project's, as its rules name them (e.g. `make lint`,
`make test`):

- the **fast gate** before every commit;
- the **push gate** before the single push, as the `agent-kit:push-gate`
  skill defines it; read it;
- never read a gate's exit status through a pipe (`make test | tail`
  reports `tail`'s), and the pipe-status guard denies that shape;
- never invoke interactive or publishing targets (build, tag, release,
  publish and the like) from a tool call: an interactive one blocks on a
  prompt until timeout, and publishing is the operator's act;
- push **once**, after the last commit the request implies, and a push
  request also means open the PR.

The PR description is the durable session summary: what landed and why,
verification results, the push gate that ran and why, notable decisions,
proposed follow-ups, and the Stage 5 cost report. Follow the project's PR
conventions (labels, linked issue, closing keywords).

**Record the plan in the PR description** — its `.plans/` filename, or
that it was a `<proposed_plan>` block, and a short digest of the decision
it carries. Neither a gitignored file nor a conversation's block is
visible to review, so without this the PR does not say what it was built
against. Once the PR is open, delete a plan file: the description has
taken over as the record, and a plan left behind is indistinguishable
from a live one. A run that stops short of the PR says where the plan
still is: the file stays in place, and a block lives only in this
conversation.

When folding the plan record (or anything else) into an existing
description, rebuild from the body as the tracker holds it **now**,
preserve every existing part, and re-read the result afterwards, first
line included — observed in practice: a fold-in silently dropped the
description's closing-keyword line.

### Stage 5 — Cost report

Report per the `agent-kit:delegation` skill, "Cost observability",
adding each dispatch's stage.

State explicitly which work items stayed in the steering loop and why. A
run that dispatched nothing reports that with its reason: a cost report of
zero that says nothing implies the question never came up.

## Stop conditions

Stop and hand back rather than deciding, when:

- **a design question surfaces mid-run** — the plan was less closed than
  it looked. Put it as the `agent-kit:design-exploration` skill's
  "Presenting, and who decides" requires, and do not settle it in flight
  because the implementation is already moving;
- **three fixes have failed** — stop, and do what the `agent-kit:debugging`
  skill's "Three failed fixes means the design is wrong" requires before a
  fourth;
- **the plan's ground has moved** far enough that Stage 0 cannot confirm
  it still holds.

## Reliability

Grouping work into closed specs, and deciding which items are worth a
dispatch, are judgments rather than formulas — this skill states the
stages and the bounds, not a test. It will occasionally over-dispatch a
mechanical edit and occasionally keep something in the steering loop that
should have been handed over. Expect to catch both by hand; overriding the
grouping mid-run is expected use, not a failure.
