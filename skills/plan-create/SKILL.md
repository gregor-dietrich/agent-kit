---
name: plan-create
description: "Planning that turns a design decision into a closed spec — use this INSTEAD of the harness's built-in plan mode agents, whose Explore/Plan types carry no model pin and so inherit the steering model. Dispatches pinned agent-kit:scout subagents to gather context and pinned agent-kit:software-architect subagents to produce competing designs, puts the choice to the operator, and writes a plan file under .plans/ that /agent-kit:plan-run can execute in a later session. Use whenever asked to plan, design, scope, or explore an approach to a change that carries a decision with more than one defensible answer. NOT for work whose design is already settled — a closed spec, a bug fix with an established cause, a rename or a doc fix go straight to /agent-kit:plan-run or straight to the edit."
argument-hint: "[issue # | a description of the work]"
---

Plan a change: **$ARGUMENTS**

(If no arguments were given, infer the target from the conversation and
confirm it before dispatching anything. If the target is a tracker issue,
read it **with its comments** — see Stage 0.)

## Why this skill exists

**Spec closure**, not model routing. A skill has to be invoked, so on
routing grounds alone the `agent-kit:delegation` skill already dominates
it. What this skill carries is the discipline of turning a decision into a
closed spec **before** implementation starts: options actually compared,
the rejected ones recorded with their reasons, work items sized to be
executed without asking, and a testing story. That pays off whichever
model executes the work.

Routing is the corroborating context, not the reason. The harness's
built-in plan-mode agent types (`Explore`, `Plan`) carry no `model:` pin,
so a bare dispatch inherits the steering model — observed in practice, one
session's plan phase sent ~190k steering-model tokens to such dispatches.
**Those agent types MUST NOT be used for planning; this skill replaces
them.** Being _in_ plan mode is fine; what is banned is routing its phases
through unpinned vehicles.

## Dispatch policy

- Every dispatch MUST name a pinned agent type — here, `agent-kit:scout`
  (context) and `agent-kit:software-architect` (design), or the project's
  own type for the same role, which takes precedence here and wherever a
  stage below names an agent-kit type (`agent-kit:delegation`, "The
  policy"). The `model:` pin in the agent's definition is the source of
  truth — **read it**, do not recall it from memory or from this skill.
- General-purpose (unpinned) dispatches are **FORBIDDEN**, as are the
  harness's built-in types, for the reason above. The
  `agent-kit:delegation` skill, "The policy", carries the reasoning **and
  the override rule** for a harness workflow that leaves no other choice.
- `agent-kit:scout` is read-only by instruction, not by harness — it has
  Bash for read-only `git` and tracker reads. Scope its dispatches
  accordingly. `agent-kit:software-architect` has no Bash and is read-only
  at the harness level; it cannot fetch, so give it what it needs.
- The steering loop orchestrates: it dispatches, reads back every return,
  puts the decision to the operator, and writes the plan. It MUST NOT do
  the exploration or the design work itself when a dispatch is warranted.
- **When a dispatch is warranted is the `agent-kit:delegation` skill's
  "The judgment threshold", and that skill owns it.** Read it; do not
  restate or re-derive it. Planning work below the threshold stays in the
  steering loop, and the Stage 5 report says so.

## When this skill applies

When the work carries **a decision with more than one defensible answer**
— and only then. The `agent-kit:design-exploration` skill, "When this
binds", owns that test and what falls outside it; this skill runs that
skill's method through pinned dispatches.

If you cannot name the decision being made, there is no plan to write: say
so and hand straight to `/agent-kit:plan-run` (or just build the thing).

## Stage plan

State to the operator, before dispatching anything: the target, the
subsystems Stage 1 will cover, and the planned dispatch count. The
declared bounds are the contract.

### Stage 0 — Ground (main loop, zero dispatches)

Gather in the main loop what Stage 1 and 2 prompts must carry:

- the tracker issue **and its comments**, through the project's tracker
  CLI (`gh`, `glab`, `tea`). With `tea`, pass `--comments` on every
  single-issue read: every other view silently omits comments, and the tea
  guard denies a read without the flag;
- the project's decisions log, if it keeps one (`docs/decisions.md`) —
  **always**, read as the `agent-kit:design-exploration` skill's "Before
  proposing anything" says, since it changes what is even proposable;
- the project's `AGENTS.md` (or `CLAUDE.md`), any nested one for the area
  the work touches, and the scoped rule files that apply to it.

**Size the scope here**, per that same section: a request spanning
several independent subsystems gets a proposed decomposition now, not one
design for all of it.

### Stage 1 — Context fan-out (`agent-kit:scout`)

One dispatch per subsystem the change touches, concurrent. Each prompt
carries the Stage 0 digest and asks a closed question — "what exists here,
where, and how does it fit together", with `file:line` references and no
file dumps.

Soft cap ~5 dispatches; past that, say so and get confirmation. Zero
dispatches is a legitimate outcome when the ground is already in context —
say that in Stage 5 rather than dispatching to look busy.

### Stage 2 — Design options (`agent-kit:software-architect`)

Ask for **two or three** approaches with a recommendation among them, as
the `agent-kit:design-exploration` skill's "Proposing" sets out.

Either one dispatch asked for two or three approaches, or (for a decision
worth the spend) one dispatch per approach from a stated angle, judged
against each other in the main loop. Say which shape you chose and why.

Every prompt MUST carry the Stage 0 material, the Stage 1 returns, and
that section's constraints, copied in full — YAGNI, design for isolation,
follow what is already here, and the project's priority ordering as a
tie-breaker only. They bind every option **before** it is offered, and
the agent cannot load the skill itself.

`agent-kit:software-architect` cannot fetch, so give it the tracker
material as **files**, not as a summary: write the issue body and its full
comment thread to a scratchpad file in Stage 0 and pass the path. A digest
alongside is useful; a digest _instead_ anchors the design to the
orchestrator's reading of the thread, which is the one input the agent
cannot go and check itself.

### Stage 3 — The decision (main loop; it is the operator's)

Present the options as the `agent-kit:design-exploration` skill's
"Presenting, and who decides" requires. **The choice MUST be put where it
can be answered — visible end-of-turn text, or a question.** A plan file
is one more place that only _records_ a decision: do not report the run
as complete while the choice is open, and do not write the plan file
until it is made.

### Stage 4 — Write the plan

Only after Stage 3 is answered. See "The plan file" below.

Then apply the `agent-kit:design-exploration` skill's "After a decision"
to the plan: one fresh-eyes self-review, fixed inline, and — where the
project keeps a decisions log and the decision passes that section's three
tests — an entry drafted with `**Status:** Proposed`. You MUST NOT mark it
`**Status:** Accepted`: ratification is the operator's act alone, and the
decisions-log status guard enforces it.

### Stage 5 — Cost report

Per the `agent-kit:delegation` skill, "Cost observability": every
dispatch — stage, agent type, model run, tokens from the tool result —
plus totals. If a tool result carries no token count, report the dispatch
count and mark tokens unavailable; never invent figures.

Report a run that dispatched **nothing** just as explicitly, with the
reason. A cost report of zero that says nothing implies the question never
came up.

## The plan file

Written to **`.plans/<slug>.md`**, where `<slug>` is the issue number when
there is one (`42.md`) and a short kebab-case name otherwise. The project
should gitignore `.plans/`: a plan is working state, not a repo artifact
that goes stale the moment the work lands, and not a tracker mutation. If
`.plans/` is not ignored yet, tell the operator rather than committing a
plan.

That choice has one cost, and `/agent-kit:plan-run` pays it rather than
ignoring it: the plan is invisible to review, so the implementing PR
records the plan's **filename and a short digest** in its description.
Otherwise nobody but the operator can see what the implementation was run
against.

A plan file MUST carry these five elements:

- the **target** (issue number or a one-line statement of the work);
- the **decision** Stage 3 settled, the option chosen, and the options
  rejected with the reason each was rejected — the rejections are what
  stop a later session relitigating;
- the **work items**, each small enough to be a closed spec a competent
  stranger could execute without asking, and each naming the files it
  touches and the component that owns them;
- **how it will be tested**, per the project's test conventions, including
  which gated suite (if any) the work belongs in;
- anything the plan is **unsure about** — the open questions, stated as
  open, not smoothed over.

Plans are not versioned and not authoritative once merged: when the work
lands, the PR description is the durable record, and `/agent-kit:plan-run`
deletes the plan file once it has opened that PR. Until then the plan
stays, so a resumed session can pick it up — which is why
`/agent-kit:plan-run` re-checks the ground rather than trusting the file's
presence.

## Reliability

Whether a decision has more than one defensible answer is a judgment, not
a formula — this skill states the gate and the stages, not a test. It will
occasionally run for work that needed no plan, and occasionally be skipped
for work that did. Overriding it, before or during the run, is expected
use rather than a failure.

The Stage 1 subsystem split is instruction-based routing over a codebase
map, so it is right _usually_, not _always_: expect to catch a missed
subsystem by hand and widen the fan-out mid-run.
