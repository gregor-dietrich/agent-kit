---
name: design-exploration
description: "The method for work that carries a design decision with more than one defensible answer: when it binds and when it does not, reading the ground and the decisions log first, offering two or three approaches under YAGNI and isolation constraints, putting the choice to the operator where it can be answered, and recording a load-bearing decision. Read it before proposing a design, or when a design question surfaces mid-implementation. /agent-kit:plan-create runs it with pinned dispatches."
---

# Design Exploration

RFC 2119 key words (MUST/MUST NOT/SHOULD/MAY) are to be interpreted as
described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) /
[RFC 8174](https://www.rfc-editor.org/rfc/rfc8174): they bind only when
written in uppercase.

**This is not a universal gate.** Putting every change, down to a
config value or a one-function helper, behind a present-and-approve step
contradicts the `agent-kit:review-triage` skill's "Asking has a cost too,
and it is the higher one" and turns every trivial edit into a question.
The method below is for work that carries a real design decision, and
only for that.

## When this binds

It binds when the work carries a **decision with more than one
defensible answer** — the same test the `agent-kit:review-triage` skill
applies to proposing a review finding. In practice:

- a new module, service, or feature spanning more than one component;
- a change to a module boundary, a data model, or a privileged path;
- anything whose obvious implementation would contradict a
  decisions-log entry, or would need a new one;
- a request whose shape is ambiguous enough that two competent readings
  produce materially different work.

It does **not** bind for: implementing a closed spec (an issue that
already states the design), a bug fix whose cause is established (the
`agent-kit:debugging` skill owns that path), a rename, a doc correction,
or any edit where you cannot name the decision being made. If you cannot
name it, there is no decision to surface — build the thing.

**Do not let this rule become a preamble.** A design section written for
work that needed none spends the reader's attention for nothing, which is
the precise cost the rule above is priced against.

## Before proposing anything

1. **Read the ground first.** The relevant code, the component's own
   guide, the tracker issue _and its comments_, and — always — the
   project's decisions log, if it keeps one (`docs/decisions.md`).
2. **Check the decisions log properly**, because it changes what is even
   proposable. An **Accepted** entry closes its question: a design that
   contradicts one is dead on arrival, and re-raising it is a false
   positive rather than an idea. An entry marked `**Status:** Proposed`
   carries no such force — cite it as a draft, never as settled. An
   entry carrying a **Premise:** is closed only while that premise
   holds.
3. **Size the scope before refining details.** If the request spans
   several independent subsystems, say so immediately and propose a
   decomposition rather than designing all of it at once. Each piece
   then gets its own cycle.

## Proposing

Offer **two or three** approaches, not one and not seven. Lead with the
one you recommend and say why; give each the trade-off that actually
distinguishes it, not a symmetric paragraph of prose. One approach
presented alone is a decision already made and dressed as a question.

Constraints that bind every option before it is offered:

- **YAGNI, ruthlessly.** Strip anything the request did not ask for.
  Applied to shared code, this means extraction happens when a second
  consumer actually lands, never speculatively — a rule worth
  mechanizing, because a speculative abstraction otherwise only ages
  badly instead of failing loudly.
- **Design for isolation.** Each unit should have one purpose, a stated
  interface, and be testable on its own. The check: its interface
  alone tells a caller what it is for, and its implementation can be
  rewritten with no caller noticing. Where either fails, move the
  boundary. A design that is awkward to test is a design problem
  surfacing early, not a testing problem to solve later.
- **Follow what is already here.** Match the existing pattern rather
  than introducing a second way to do the same thing. Where code you
  must touch has a real problem, fold a _targeted_ improvement into the
  design; do not propose unrelated refactoring.
- **State your priority ordering once, and use it as the tie-breaker.**
  Some ordering of security, reliability and performance will decide
  options that conflict on those axes. Put it in the project's decisions
  log so it is cited rather than re-argued — and keep it a
  _tie-breaker_, not an admission criterion for what gets built.

## Presenting, and who decides

Give each part of the design the space its difficulty earns — a few
sentences where it is straightforward. Cover the parts that carry risk:
boundaries, data flow, failure handling, and how it will be tested.

**The choice between defensible options is the operator's**, and it MUST
be put where it can be answered: visible end-of-turn text, or a question.
A design recorded only in a PR description, an issue comment, or a commit
message _records_ a decision instead of asking for one — the same failure
the `agent-kit:review-triage` skill documents for review findings, and
the same remedy. Do not report work as complete while a design question
is still open.

Where the design is genuinely closed and only its execution remains, hand
it to a pinned writing agent under the `agent-kit:delegation` skill
(`/agent-kit:plan-run` does that); where the judgment is the hard part,
use a pinned read-only judgment type for it (`/agent-kit:plan-create`
does that).

## After a decision

Self-review the written design once, with fresh eyes, and fix inline: any
placeholder or TBD, any two sections that contradict each other, any
requirement admitting two readings, and any scope that has quietly grown
past one implementation.

If the decision is load-bearing — it constrains future work, or a later
reader would otherwise relitigate it — it becomes a decisions-log entry,
in the shape that log defines: **Premise** where it was decided on
analysis under stated conditions, and then a **Guard** naming what
notices when the premise fails. An agent MAY draft the entry and MUST NOT
mark it `**Status:** Accepted`; ratification is the author's act alone,
and agent-kit's decisions-log status guard enforces that.
