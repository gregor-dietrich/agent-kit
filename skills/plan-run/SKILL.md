---
name: plan-run
description: "Execution of a closed spec — takes a /agent-kit:plan-create plan file from .plans/, a tracker issue that already states its design, or a decision just made in conversation, groups the work into closed specs, and dispatches pinned agent-kit:backend-developer / agent-kit:frontend-developer subagents rather than defaulting to implementation in the steering loop. Reads every returned diff, runs the project's gates, commits (and pushes and opens the PR where the project's AGENTS.md makes that part of the ask), and reports the dispatch cost. Use whenever asked to execute a plan or implement work whose design is already settled — not to decide a design, which is /agent-kit:plan-create's job."
argument-hint: "[plan file | issue #]"
---

Execute a closed spec: **$ARGUMENTS**

(If no arguments were given, look for a plan in `.plans/` matching the
conversation's target and confirm it before dispatching. With neither a
plan nor a settled design, stop — see "When this skill applies".)

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
  vetting. The `model:` pin in the agent's definition is the source of
  truth — **read it**, do not recall it from memory or from this skill.
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
asking. That means a `/agent-kit:plan-create` plan file, an issue that
already states its design, or a decision the operator has just made in
conversation.

If the work still carries a decision with more than one defensible answer,
this is the wrong skill: the route is `/agent-kit:plan-create`. Do not
resolve the design in flight — see "Stop conditions".

## Stage plan

State to the operator, before dispatching anything: the plan being
executed, the work items and their grouping, and the planned dispatch
count. The declared bounds are the contract.

### Stage 0 — Re-read the ground (main loop, zero dispatches)

A plan is working state and the tree moves under it. Before executing:

- read the plan file, or the issue **with its comments** (with `tea`, pass
  `--comments`: every other single-issue view silently omits them, and the
  tea guard denies a read without the flag). A plan file carries the five
  elements `/agent-kit:plan-create` requires of it ("The plan file"); a
  missing one — no work items, no testing story, no stated open questions
  — hands back to `/agent-kit:plan-create` rather than being filled in
  here. The other two inputs carry none of them by construction, so derive
  the work items and the testing story before Stage 1 and say that you
  did;
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
  time and disk. A sequential run needs none of it.
- **Where auto mode is on, keep worktrees under `.worktrees/`.** The
  harness's isolation option puts its worktrees under `.claude/worktrees/`,
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
  needs its own. Once its work has landed, remove it with
  `git worktree remove --force .worktrees/<name>`: the harness cleans up
  only its own worktrees, and the work in this one was never committed.
- When a dispatch runs isolated, say how its work reaches the tree Stage 4
  gates and commits. Subagents never commit, so the work sits uncommitted
  in the worktree, its new files untracked: stage it there
  (`git -C <worktree> add -A`), read `git -C <worktree> diff --cached` in
  full, and apply it to the landing tree. That tree is the one the gates
  run against, and an isolated result that never lands there is not in
  what gets pushed.
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

### Stage 4 — Gates, commit, PR (only as far as the ask covers)

Invoking this skill is the ask to _execute_: commit the work. Push and
open the PR only when the ask covers it — being handed an issue to
implement counts as that ask only where the project's `AGENTS.md` says so.
Otherwise commit, then say what is uncommitted and what a push would
carry, rather than pushing unasked. Hold the push too whenever the run
implies more commits are still coming.

The gates are the project's, as its `AGENTS.md` names them (e.g.
`make lint`, `make test`):

- the **fast gate** before every commit;
- the **full gate** before the single push, on a **clean tree**
  (everything committed, no untracked files), so what it verified is
  exactly what is pushed. Give it, and any push whose hook runs it, a tool
  timeout long enough to finish, and never retry a timed-out push with
  `--no-verify`. The invariant is that the pushed **tip** is gate-green;
- never read a gate's exit status through a pipe (`make test | tail`
  reports `tail`'s), and the pipe-status guard denies that shape;
- never invoke interactive or publishing targets (build, tag, release,
  publish and the like) from a tool call: an interactive one blocks on a
  prompt until timeout, and publishing is the operator's act;
- push **once**, after the last commit the request implies, and a push
  request also means open the PR.

The PR description is the durable session summary: what landed and why,
verification results, notable decisions, proposed follow-ups, and the
Stage 5 cost report. Follow the project's PR conventions (labels, linked
issue, closing keywords).

**Record the plan in the PR description** — its `.plans/` filename and a
short digest of the decision it carries. `.plans/` is gitignored, so
without this the PR does not say what it was built against. Once the PR is
open, delete the plan file: the description has taken over as the record,
and a plan left behind is indistinguishable from a live one. A run that
stops short of the PR leaves the plan in place and says so.

When folding the plan record (or anything else) into an existing
description, rebuild from the body as the tracker holds it **now**,
preserve every existing part, and re-read the result afterwards, first
line included — observed in practice: a fold-in silently dropped the
description's closing-keyword line.

### Stage 5 — Cost report

Per the `agent-kit:delegation` skill, "Cost observability": every
dispatch — stage, agent type, pinned model, tokens from the tool result —
plus totals. If a tool result carries no token count, report the dispatch
count and mark tokens unavailable; never invent figures.

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
