---
name: delegation
description: "The subagent dispatch policy: route work only by explicit dispatch to a pinned agent type, never to general-purpose or built-in Explore/Plan types that inherit the steering model; the judgment threshold for what stays in the steering loop; and the end-of-session cost report. Read it before dispatching subagents, planning a fan-out, or deciding whether to implement a change yourself or hand it to a writing agent."
---

# Subagent delegation and model routing

RFC 2119 key words (MUST/MUST NOT/SHOULD/MAY) are to be interpreted as
described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) /
[RFC 8174](https://www.rfc-editor.org/rfc/rfc8174): they bind only when
written in uppercase.

## The policy

Work is routed by explicit dispatch, and only by explicit dispatch:

- A dispatch MUST name a pinned agent type. agent-kit ships one writing
  pair (`agent-kit:backend-developer`, `agent-kit:frontend-developer`),
  two read-only judgment types (`agent-kit:code-reviewer`,
  `agent-kit:software-architect`) and one read-only exploration type
  (`agent-kit:scout`); a project may define its own. The `model:` pin in
  the agent's frontmatter is the source of truth — read it, never recall
  it.
- Read-only types are not read-only _alike_. A type that omits `Bash`
  from its `tools:` is read-only at the harness level; a type granted
  Bash for read-only `git` reads is read-only by _instruction only_.
  Scope its dispatches with that difference in mind.
- You MUST NOT rely on a `general-purpose` (or omitted-`subagent_type`)
  dispatch inheriting something useful: it silently inherits the steering
  model. That looks like delegation while buying nothing model-wise.
- **The harness's built-in agent types (`Explore`, `Plan`, …) are the
  same trap**: they carry no `model:` pin, so a bare dispatch inherits
  the steering model. This binds in plan mode too — the plan-mode
  workflow's own instructions name `Explore`/`Plan` as the phase
  vehicles, and this rule overrides them: route exploration and design to
  pinned types (`/agent-kit:plan-create` does exactly that). Where a
  harness workflow leaves no choice but a built-in type, the dispatch
  MUST carry an explicit `model` override read from the closest pinned
  agent's frontmatter.
- The steering loop plans, dispatches, reads every returned diff, and
  decides what lands. It SHOULD NOT implement non-trivial changes itself
  — implementation of a closed spec belongs in a pinned writing agent's
  dispatch. (Framing a request as "plan, then execute" does not cause
  delegation; only an explicit pinned dispatch does.)
- Never merge a subagent diff unread. Subagents never commit, and never
  re-delegate.
- Keep delegations small and their specs closed (a competent stranger
  could execute without asking); require subagents to report what they
  were unsure about, not just what they did. Escalate a tier only on
  failure (a second red gate run or a diff needing rewrite) — do not
  pre-empt.

## The judgment threshold

Delegate-or-not is a judgment threshold, not a binary: for small edits
the subagent's context-rediscovery tax exceeds the saving, and those stay
in the steering loop. The test: would the closed spec outweigh the diff?
If so, make the edit. This rule therefore yields _usually_, not
_always_ — the operator should expect to catch cases by hand. Unlike
mechanized guards, "is this change big enough to delegate?" has no one
right answer, so no check enforces this rule.

## One policy, every consumer

The skills that dispatch agents — `/agent-kit:plan-create`,
`/agent-kit:plan-run`, `/agent-kit:ai-review` — and this rule instantiate
the SAME policy: review and implementation MUST NOT diverge on when and
how work is dispatched. Change the policy in one place and reconcile the
others in the same change.

The failure this prevents, observed in practice: a review skill carried a
blanket "MUST NOT apply fixes itself" with no smallness exception,
diverging from the threshold above, and consequently dispatched a
~50k-token agent — with a spec longer than the patch — for a three-line
fix.

## Cost observability

A session that dispatched agents MUST report, at the end: agents spawned
(per dispatch: agent type, pinned model, tokens from the tool result) and
totals. If a tool result carries no token count, report the dispatch
count and mark tokens unavailable — never invent figures.

## Rejected alternative: a PreToolUse hook (do not re-propose)

A PreToolUse guard denying main-loop Edit/Write under a given steering
model is the only true mechanization of this rule, and it was evaluated
and rejected: it is blunt — it would block one-line fixes, doc tweaks,
and every edit where the context-rediscovery tax exceeds the saving — and
the question it would need to answer ("big enough to delegate?") has no
single right answer, so a faithful mechanized guard does not exist.
Re-proposing it is a settled-decision re-raise to drop, not a finding,
unless the steering-model economics change fundamentally.

Recording a _rejected_ alternative is as load-bearing as recording the
accepted one: without it, the same proposal returns every few sessions
and is re-argued from scratch.
