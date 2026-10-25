---
name: wrap-up
description: "End-of-session retro: reviews the session for knowledge (project facts, conventions, quirks), skill gaps, friction and automation candidates, presents a numbered report with a proposed destination for each item, saves it under .plans/, and edits or files only what the operator approves by number. Use when asked to wrap up, to say what we learned, or to run a retro on this session."
argument-hint: "[focus, e.g. a part of the session]"
---

Wrap up the session: **$ARGUMENTS**

(With no argument, review the whole session.)

## Why this skill exists

The kit's method is that rules accrete in each project from incidents.
Nothing in the kit prompts that accretion: it depends on the operator
remembering to ask at the end of a session. Approval by number makes it
routine without letting the agent write rules unasked.

The review and the report run in the steering loop and dispatch
nothing: the session is in its context, and a subagent would not have it.
Applying an approved item follows the `agent-kit:delegation` skill's
judgment threshold like any other change: a non-trivial one, such as a
check or hook with its tests, goes through `/agent-kit:plan-run`.

## The review

Go through the session for four categories:

- **knowledge**: a project fact, convention or quirk learned the hard way
  that the next session would otherwise rediscover;
- **skill gaps**: a skill or agent that was missing, wrong or silent where
  the session needed it;
- **friction**: a detour, a retry or a correction that cost the session
  time;
- **automation**: a manual step repeated, or a mistake a check could catch.

Skip an item an existing rule already covers, unless the session broke
that rule anyway: that item is a candidate for destination 3. Read the
rule files, the `AGENTS.md` and the decisions log, if the project keeps
one, first, so that what is skipped is skipped on a read and not on
memory.

## The report

Present a numbered list, one line per item:

```text
N. [category] finding → [destination] proposed change
```

Save the same report to `.plans/wrap-up-YYYY-MM-DD-HHMM.md`, then
**stop and wait**. The project should gitignore `.plans/`
(`/agent-kit:plan-create`, "The plan"); if it does not, tell the operator
rather than committing the report.

## Destinations

Pick the first that fits, smallest viable first:

1. the project's `AGENTS.md`, or the nested one for the area;
2. a scoped rule file;
3. a check or hook in the project, where prose has demonstrably failed to
   hold;
4. a skill or agent change, in the project, or in agent-kit only when the
   item holds for working with an agent in any repository. An agent-kit
   item is never applied from another project's session: approved, it is
   carried to a session in agent-kit's own checkout;
5. a decisions-log entry, where the project keeps a log, drafted
   `**Status:** Proposed` and never Accepted, and only when it passes the
   three tests in the `agent-kit:design-exploration` skill, "After a
   decision";
6. a tracker issue, for work rather than knowledge;
7. the client's auto memory, last: it is machine-local and reaches no
   other contributor.

## Approval

Approving an item by number is what authorises its edit and, for
destination 6, filing that issue. Nothing is edited or filed unapproved.
Apply exactly the approved items to the working tree and leave them
uncommitted, then say what changed and which branch it sits on, so the
operator decides where it lands.
