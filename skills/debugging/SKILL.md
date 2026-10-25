---
name: debugging
description: "The root-cause method for any bug, test failure, flake or unexpected behaviour: no fix without an established cause. Read the error, reproduce it, check what changed, instrument the boundaries, compare against a working analogue, test one hypothesis at a time, land the failing test first, and after three failed fixes stop and raise the design question. Read it before proposing or committing a fix, and whenever a fix has not held."
---

# Debugging

RFC 2119 key words (MUST/MUST NOT/SHOULD/MAY) are to be interpreted as
described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) /
[RFC 8174](https://www.rfc-editor.org/rfc/rfc8174): they bind only when
written in uppercase.

Two steps take the project's specifics: the boundaries in Phase 1.4 and
the gates in Phase 4.3, both from the project's rules, the gate a change
owes as the `agent-kit:push-gate` skill reads them. This skill owns the
general method, not individual tool traps; those belong in the project's
own docs, and the two should not restate each other.

## The rule

**No fix without a root cause.** A change that makes the symptom go away
without an account of _why_ it was happening is not a fix, and MUST NOT
be committed as one.

This binds for any bug, test failure, flake, or unexpected behaviour, and
it binds hardest exactly where it feels most skippable: under time
pressure, when the cause "is obvious", and when a previous fix did not
work. A simple bug still has a root cause, and finding it is usually
faster than the guess-and-check loop it replaces.

The one honest exit is Phase 4's last step: an investigation that
_completes_ and shows the cause is genuinely external (upstream defect,
timing, hardware) ends in handling plus a recorded note, not in a silent
patch.

## Phase 1 — Establish the cause

1. **Read the error completely.** Whole stack trace, exit code, the line
   numbers. Errors are frequently self-describing, and skimming them is
   how a session spends an hour re-deriving what the first line said.
2. **Reproduce it deterministically**, and _hermetically_ — under an
   environment that does not depend on the developer's ambient shell. An
   intermittent repro is not a repro: gather more data instead of
   guessing.
3. **Check what changed.** `git log`/`git diff` against the last
   known-good state, dependency bumps, config, and environment.
4. **Instrument the boundaries before theorising.** A bug in a
   multi-component path is nearly always _a value crossing a boundary in
   a shape the far side did not expect_. Log what enters and what leaves
   each side, once, and let the evidence name the failing component.

   Use the boundaries the project's `AGENTS.md` names; where it names
   none, list them before instrumenting — every place a value changes
   custody. Typical shapes: a network or RPC hop, a privilege transition
   (a helper process, a setuid path), a shell-out to another program, an
   ORM/database edge, a serialization boundary, a CI-runner edge. Naming
   them concretely is what makes this step fast; a generic "check your
   boundaries" is what makes it get skipped.

5. **Trace backwards to the origin.** When the error surfaces deep in a
   call stack, walk _up_: where did the bad value first exist? Fix it
   there. A guard added at the point of the crash leaves every sibling
   caller broken.

## Phase 2 — Compare against something that works

Find the working analogue — a sibling module solving the same problem, a
prior version, a reference implementation — read it **completely** rather
than skimming, and list _every_ difference before deciding which one
matters. "That can't be relevant" is the assumption that costs the next
hour.

Codebases with deliberate structural repetition (parallel
implementations over different backends, files pinned byte-identical,
one baseline shape per component) make this the fastest diagnostic
available. Where the project's `AGENTS.md` says it has that property,
start here.

## Phase 3 — One hypothesis at a time

State it in a sentence — "X is the cause, because Y" — then test it with
the **smallest** change that would distinguish true from false. One
variable. If it is wrong, form a new hypothesis; do not stack a second
fix on the first, because you can no longer tell which one moved the
result.

Say "I do not understand X" when that is the true state. An unstated
guess presented as a diagnosis is worse than no diagnosis.

## Phase 4 — Fix the cause

1. **The failing test comes first** wherever the defect is expressible as
   a test, and it MUST fail for the right reason before the fix lands —
   otherwise you have not shown it tests the bug. For a coverage gap,
   where the code already behaves, plant the defect to show it
   (`agent-kit:ai-review`, Stage 4, "Prove a coverage gap before closing
   it"). A regression test follows your normal test conventions like any
   other.
   Some real defects are not expressible: a wrong URL or a stale
   enumeration in a doc, or an operator-facing comment in a shipped config
   file. There, say plainly that no test can express it and verify the fix
   directly instead — the honest exit, not a licence to skip a test that
   could have been written.
   A defect in code your coverage config deliberately omits is **not** one
   of those cases: an omit takes code out of the coverage gate, not out of
   testing. Its regression test lands in whatever suite reaches that code
   — integration tests, a browser journey (Playwright or the like) — and
   simply does not move the coverage number. That suite may sit outside
   the gates, so run it to see the test fail first. Where no suite reaches
   the code yet, say so as a test gap, not as the not-expressible exit.
2. **One change.** No bundled refactor, no "while I'm here" cleanup —
   those are separate commits at best and separate PRs at worst.
3. **Verify with the real gate**, not by inspection: the project's fast
   gate, and the gate its rules require for this change (the
   `agent-kit:push-gate` skill, "Which gate"). Never read a gate's exit
   status through a pipe — agent-kit's pipe-status guard denies that at
   the moment of the call, which is the only place prose reliably fails
   to reach.

4. **If the investigation shows no internal cause**, say so explicitly,
   note what was ruled out and how, and implement handling (retry,
   timeout, a legible error) rather than a speculative patch. Most "no
   root cause" verdicts are incomplete investigations; this one has to
   survive being written down.

## Three failed fixes means the design is wrong

Count them. After **three** fixes that did not hold — especially when
each one surfaces a new problem somewhere else, or the next one would
mean restructuring half the component — stop. That is not a run of bad
hypotheses, it is a structural problem wearing them as a disguise.

Two things to do before attempting a fourth:

- **Check the decisions log for a failed premise**, if the project keeps
  one (`docs/decisions.md`). An entry carrying a **Premise:** is closed
  only while that premise holds, and a bug that keeps regrowing is one of
  the few signals that can falsify one. If a premise has failed, say
  which and why — that is a real finding.
- **Raise the architectural question with the operator**, rather than
  deciding it. Which pattern is wrong, and what would replace it, is a
  design call — the `agent-kit:design-exploration` skill governs how to
  put it.

## Red flags

Go back to Phase 1 when you catch yourself:

- editing code before you can say where the bad value first appears;
- making a change whose only justification is to see what it does;
- holding more than one change in play while re-running the gate;
- naming causes in bulk without having tested any of them;
- planning to land a patch now and find the cause afterwards;
- relying on a change whose working you cannot explain;
- reaching for a fourth fix.
