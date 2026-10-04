---
name: review-triage
description: "How code-review findings are gathered, recorded and routed: context to read before finalizing findings (linked issues and their comments), recording on the PR, novel/instance marks, settled decisions, no finding cap, and the destination every finding must reach (fixed, filed, or explicitly dropped). Read it whenever reviewing a diff, PR or audit, triaging review findings, or deciding whether to fix, file or ask about one."
---

# Code review: context, recording and triage

RFC 2119 key words (MUST/MUST NOT/SHOULD/MAY) are to be interpreted as
described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) /
[RFC 8174](https://www.rfc-editor.org/rfc/rfc8174): they bind only when
written in uppercase.

## Gather context before finalizing findings

Before finalizing code-review findings, gather all surrounding context:
the PR description, its linked issue(s), the overarching epic, and the
**comments** on each. A candidate finding that a linked issue, epic or
comment already explains, accepts, or tracks is a **false positive** —
drop it.

Comments are the part most often missed, and tracker CLIs omit them from
some single-entity reads. With `tea`, every single-issue/PR view but
`--comments` omits them (`--output json` even prints `"comments": []`);
agent-kit's tea guard denies a read without the flag. With `gh` or
`glab`, ask for comments explicitly.

## Record the findings where they outlive the session

When the review target is (or has) an open PR, post the full verified
findings as a **comment on that PR** before acting on them — the review
then outlives the session that produced it, fix commits can cite it, and
the next reviewer's context gathering finds it. The in-session reply
still reports the findings; the PR comment is the durable copy, not a
substitute.

## Mark each finding novel or instance

One word per finding: a **novel class** nothing in the repo yet
anticipates, or an **instance** of a known one — naming the mechanized
check, rule file, or prior finding it instances.

An instance of a class a check already covers is the stronger signal of
the two: it means the rule has the wrong _scope_, so say which rule and
which files it misses. Without these marks you cannot tell whether your
review loop is finding new classes of defect or re-finding the same ones,
and any audit of the loop's yield can only report itself as unevaluable.

## Scope

These duties bind review sessions, not every dispatch. They apply when
the review is the deliverable — a pre-merge diff review, a commissioned
audit. An in-loop verification pass (a reviewer dispatch vetting a
subagent's diff inside an implementation session) MUST NOT record outside
its loop — no PR comment, no `novel`/`instance` marks; its findings are
acted on or dropped in-session. One exception: a finding about code
**outside** the diff being verified is still reported and triaged so it
is not lost.

## Settled decisions are not findings

Decisions recorded in the project's decisions log (`docs/decisions.md`,
if it keeps one) are not to be re-raised. That force belongs to
**Accepted** entries only: an entry marked `**Status:** Proposed` is a
draft — cite it as context, never as settled, and a finding that
contradicts it is an ordinary finding.

**Exception:** an entry carrying a **Premise:** line is closed only while
that premise holds. A finding that shows the premise has failed is a real
finding — say which premise and why.

## Triaging findings

Report **every** verified finding — there is no cap, and no top-N slice.
This overrides any cap a review tool imposes: built-in review tooling
commonly truncates to the N "most severe" findings, and that limit MUST
NOT be honoured — surface all confirmed (and worth-mentioning uncertain)
findings, ranked by severity but never cut at the tail. Likewise, when
asked to fix review findings, fix the whole confirmed set rather than a
top-N slice.

What is bounded is not the reporting but the **destination**:

- **Default: a tracker issue.** Quality, reuse, dead code, naming, test
  hygiene, non-hang performance, refactors — all real work, none of it a
  reason to hold a release.
- **Admit to the current release only on a stated bar** — the project's
  release-admission bar, if its decisions log defines one (e.g. a
  crash/hang in a shipped surface, a security defect, data loss, or a gap
  that a release tag makes permanently unfixable). Admit nothing that
  misses it. There is no second bar.
- **Fix in-branch** when the finding is _about the diff under review_.
  The triage bar governs findings about the **rest of the codebase**
  that a review happens to surface; those get filed rather than fixed in
  passing — **unless they are small, in which case the
  filing-has-a-cost rule below sends them back to "fix it and say so."**
  Read that rule before choosing this bullet: it outranks the default
  for anything trivial.

Say which bucket each finding landed in when reporting. An LLM-driven
review of a large codebase always returns more findings, so an unstated
default of "fix it now" silently converts every review into scope.

### Filing has a cost

When the fix is smaller than the issue describing it would be — a wrong
word in a doc, a stale enumeration, a one-line guard — fix it and say so,
rather than filing tracker litter.

### Asking has a cost too, and it is the higher one

Filing spends tracker space; asking spends the reader's attention, which
is scarcer. So "propose it to the user" is **not** the safe default for a
borderline finding — it is reserved for findings where the **decision**
is the user's: a design choice with more than one defensible answer, a
user-visible behaviour change, a scope call, a tracker mutation. Being
merely out-of-diff does not qualify a finding for it. When you propose,
**name the decision you are deferring and why it is not yours to make**;
if you cannot name one, that is the signal to fix it or drop it instead.

### Measure the fix, not its headline

The size test compares the _actual patch_ against the issue text that
would describe it, so check the blast radius before picking a
destination. A "one-line rename" that ten assertions select on is not a
one-line fix; a "dead code" finding may be a one-line delete. Both
directions are common, and the cheap check — grep for what depends on the
thing — takes seconds.

### Every finding reaches a terminal destination

Filing-has-a-cost kills the _filing_, never the _finding_: every reported
finding must reach a terminal destination — **fixed**, **filed**, or
**explicitly dropped** with the drop stated as such. "Recorded in the
review comment" is reporting, not a destination — a merged PR's comments
are not a tracking home, so a finding parked there is a drop that doesn't
say its name.

**Proposing is not one of them.** A proposal is a question you owe an
answer to, not a place a finding comes to rest: it stays _pending_ until
the user rules, and their ruling is what routes it to fixed, filed or
dropped. So a review holding open proposals is **not finished** — do not
report it as complete, and do not count proposals under "every finding
reached a destination". Put the proposal where it can actually be
answered: **visible end-of-turn text, or a question** — never only in a
PR description, an issue comment or a commit message, all of which
_record_ a decision instead of asking for one. If the session genuinely
cannot wait for the answer, the finding does not thereby become terminal:
file it or drop it, and say which.

> This last rule took three passes to state correctly, and the failure
> mode is worth knowing before you inherit it. The first version wrote
> the list as `filed/proposed`, fusing the two so that proposing
> inherited filing's terminality. The second split them in order to
> _price_ asking — correctly — but the split promoted `proposed` into a
> standalone terminal destination, the opposite of what that change set
> out to do. A later review then closed by reporting five open proposals
> as disposed of, four of them recorded only in a PR description.
> Proposing has never been a way to be done with a finding.
