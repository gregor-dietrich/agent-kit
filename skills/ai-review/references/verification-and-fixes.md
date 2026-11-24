# Stages 2, 4, 5, reliability and deliberate omissions

## Stage 2 — Adversarial verification (`agent-kit:code-reviewer`), by stance

Every verifier is prompted to **refute** each pooled finding against
source rather than confirm it, re-reading every error- or
warning-severity finding individually against the file it names.
Verdicts: `CONFIRMED` / `PLAUSIBLE` / `REFUTED` /
`TRACKED <what holds it>`. Drop `REFUTED` findings. `TRACKED` is for a claim
that is true but that Stage 1's tracked-finding rule covers: it is not a
refutation, and the verdict adds a note of what the review adds beyond what
holds it (another occurrence, a root cause, a reproduction). `TRACKED`
never rests on an issue for a defect the diff introduces or makes
reachable; only an accepting record gives it.

A finding that names a defect class is verified by repeating the sweep:
the verifier greps the affected files and their siblings and adds the
instances the reviewer missed. A completed instance list corrects the
finding, never refutes it, and a finding whose sweep was not done comes
back with the sweep done, not dropped.

**Under the widened-`standard` ceiling, split multiple verifiers by stance
rather than by finding volume.** N verifiers under the same prompt
re-derive the same doubts; what changes the answer is what each one is
allowed to count as evidence. The `deep` modes retain their lower,
volume-split verifier bound below, but every such verifier still receives
an explicit stance. Three stances have earned their place:

- **the attacker**, holding whatever the diff's own threat model concedes
  (a stolen cookie, a compromised peer, a non-cooperative client): what is
  the residual capability, as opposed to the one the code intends? This is
  the stance that keeps a stated bound honest — and that declines to claim
  a bound nobody measured.
- **the maintainer**, reading the change a year later with no author
  present: does each claim survive what the code says about itself —
  docstrings, comments, the justification on a coverage omit, the test
  aimed at the branch? Its characteristic find is a guard written for the
  case the same file documents elsewhere as unreachable.
- **the operator**, upgrading a live deployment at 3am: what changes under
  existing sessions and accounts, what is the recovery path when it goes
  wrong, and do the operator-facing docs say so? Its characteristic output
  is a per-shape impact table — the cheapest way there is to falsify a PR
  body's stated bounds.

Dispatch count by mode:

- **`quick`** — skipped. Say so explicitly in the Stage 5 cost report.
- **`standard`** — 1 verifier over the pooled findings, and it MUST still
  be given a stance explicitly: the one the diff's risk earns (a
  risk-carrying path → attacker; a refactor, or a change to a
  justification or docstring → maintainer; a migration, deploy artifact or
  behaviour-at-upgrade change → operator). An unstanced verifier falls
  back to the reviewer's own lens, which is the lens that already ran.
- **widened `standard`** (the ceiling ask) — one verifier per stance. Past
  three, split by finding volume within a stance rather than inventing a
  fourth.
- **`deep <surface>` / `deep tree`** — 1–2 verifier dispatches, split by
  the volume of pooled findings. Each verifier MUST still receive an
  explicit stance chosen by the diff's risk under the `standard` mapping
  above; a volume split does not make it unstanced.

**Report disagreement; do not resolve it silently.** Stances legitimately
disagree about severity as well as survival, and the disagreement is
itself information: say which stance dissented and on what. A finding two
stances down-rank is not thereby refuted, and one stance refuting on
reasoning the others never considered is a result rather than noise.

A refutation is itself refutable. Observed in practice: a verifier killed
a finding by asserting a table's contents without reading the table; the
table said the opposite. Read the evidence a refutation rests on before
dropping the finding it kills.

Observed in practice: on one review where all three stances ran, each
produced something the other two did not — the maintainer also corrected
a premise three Stage 1 reviewers shared, and the operator's impact table
showed the PR body wrong in both directions and the documented
break-glass path broken.

## Stage 4 — Fixes (only when the standing ask applies)

Reviewing an unmerged branch or PR is itself the ask for the fixes it
produces; this stage runs only then.

- Group confirmed in-branch findings into small, closed specs. A fix
  closes every instance a finding lists, not only the first.
- A finding that reports a contradiction names both sides, and its
  suggested fix is one reading. Before writing the spec, the steering
  loop establishes which side holds (from the issue, the process behind
  the rule, or by asking the operator); the spec names it.
- A confirmed in-branch finding whose fix is a design an open issue
  holds goes to the operator; it is not dropped as tracked.
- The fix report states what each fix adds, not only what it removes
  (review-triage, "Measure the fix, not its headline").
- After the fixes, the steering loop re-reads each draft against the
  final diff before it leaves the machine (a PR opens or is edited, a
  reply or comment is posted): a fix changes counts and claims the draft
  stated.
- **Prove a coverage gap before closing it.** A finding that claims a
  behaviour is pinned by no test is proven before its test is written.
  The steering loop runs the proof (plants, runs, copies); only the test
  is written as a fix. The proof plants the defect in a throwaway
  worktree, never in the working tree: restoring a file there silently
  reverts any write made to it since it was copied, and a planted file
  the live session runs (a project hook) breaks the session mid-proof.
  Caches stay off for every run of the proof (Python:
  `PYTHONDONTWRITEBYTECODE=1`): a cache keyed on mtime and size survives
  a same-size edit made within the same second, as a corrected re-plant
  or a re-copied test can be, and gave a false red.
  1. Check `git worktree list` first. A `.worktrees/proof-<finding>`
     present is from an interrupted run: remove it
     (`git worktree remove --force`). Other `proof-*` entries may belong
     to a live session: report them, remove none. Create the worktree
     from HEAD as `.worktrees/proof-<finding>` and set it up as
     `/agent-kit:plan-run` Stage 2 sets out for an isolated dispatch
     (excluded from git status, its own virtualenv as the project's
     `AGENTS.md` says, no git hooks or git config). Carry the working
     tree's changes across only while no fix dispatch that could touch
     them runs, leaving out the finding's test where a restart finds it
     already written: step 3 copies it. Carry the tracked changes as that
     Stage's steps 3 and 5 carry a patch, from `git diff HEAD` rather
     than `--cached`, and only where `git diff HEAD --quiet` exits 1 (an
     empty patch makes `git apply` exit 128). Carry the untracked files
     `git ls-files -z --others --exclude-standard` lists, run from the
     top level, each to the same relative path in the worktree. Run
     every suite that reaches the code, those outside the gates included
     (`agent-kit:debugging`, Phase 4). A red baseline that is green in
     the working tree is a setup gap (an ignored input the worktree
     lacks), reported as such; either red stops the proof and waits on
     the operator.
  2. Plant the exact defect the finding describes in the worktree and run
     those suites. Green is the proof; a list of tests that "could have
     caught it" is not. Red counts only when a test asserting the
     behaviour fails: the gap does not exist, and the finding is dropped
     as refuted. A red from an import or collection error means the plant
     is malformed: correct it and run again.
  3. Write the test in the working tree as any fix is written (dispatched
     above the judgment threshold), copy every file its change touches
     into the worktree and run the suites there against the planted
     defect. Red counts only when the new test's assertion fails (as in
     step 2), and the others stay green. A test that stays green under
     the defect proves nothing: it goes back to its writer with that
     result, and step 3 repeats once; a second green stops the proof.
     Check that the worktree's suites import the worktree's code, and
     report to the operator. Remove the worktree
     (`git worktree remove --force`) here, and on every path that ends
     the proof, a stop included, before step 4.
  4. Run the suites from step 1 in the working tree: the new test
     passes; a red goes back to its writer. Report each run's result.
- Dispatch each group to `agent-kit:backend-developer` or
  `agent-kit:frontend-developer` — whichever owns the touched files.
  Exception, per the `agent-kit:delegation` skill ("The judgment
  threshold"): a fix so small that its closed spec would outweigh its diff
  (a few mechanical lines, no design freedom) is applied directly by the
  steering loop — a spec longer than the patch spends more of every
  budget, steering tokens included, than the edit itself.
- The steering loop MUST NOT apply fixes above that threshold itself. It
  MUST read every returned diff before committing, as the
  `agent-kit:delegation` skill, "The policy", sets out (once the dispatch
  has ended, commit what was read, report lines are claims). Where a fix
  dispatch runs isolated, its work lands by `/agent-kit:plan-run`'s
  Stage 2 procedure.
- Subagents never commit and never re-delegate; the steering loop commits.
- **One review pass over the fixes.** Once every fix is committed, where
  the fix diff (`<pre-fix>..HEAD`, `<pre-fix>` being the HEAD the review
  ran on) would itself fire an escalator in
  `<base>/references/mode-selection.md`, one `quick` Stage 1
  dispatch reviews it. The escalators pick which fix diffs earn a pass;
  the prompt's findings and specs bound what it reads. Its prompt adds the
  verified findings and the fix specs, and asks it to mark each finding
  introduced by the fixes, a fix left incomplete, or present before. Its
  set is posted and fixed as the first round's is (Stage 3 and this
  stage); where the first round's comment is still held (as under
  `/agent-kit:next --review`), one comment carries both. There is no
  further pass. The steering loop reads fixes against its own specs, as
  meant, not as written; observed in practice: over a fix commit of 8
  files (+157/−87) that the diff read and the gates had passed, this pass
  found five warnings, three introduced by the fixes (one carried by the
  fix spec) and two fixes left incomplete.
- Gates are the project's, as its rules name them (e.g. `make lint`,
  `make test`): the fast gate before each commit; once every fix is
  committed, the fix pass's included, the push gate before the single
  push at the end, as the `agent-kit:push-gate` skill defines it.

## Stage 5 — Cost report (every run, all modes)

A table of every dispatch made — stage, then the fields the
`agent-kit:delegation` skill, "Cost observability", names — plus totals:
agents spawned and tokens consumed. State explicitly when Stage 2 was
skipped (`quick`).

When the run was invoked as `auto`, record the resolved mode and the
escalators that fired (or that none did) — that line is the only durable
evidence of whether the routing rule is calling diffs correctly. Where the
**`standard` ceiling** fired, record that it was offered, which option the
operator chose, and the count they were quoted; where it did not fire on a
diff that in hindsight wanted it, say so, because that is the only way the
ceiling's thresholds ever get corrected.

Record whether **Stage 1b** ran and which trigger fired, for the same
reason. Where it ran, also say what it settled that Stage 1 could not, and
what it got wrong — that pair is the only evidence of whether the
empirical arm is worth its cost, and a run that reports only its successes
cannot support the judgment either way.

Record the same pair for **Stage 1c**, where it ran, for each Stage 2
**stance**, and for Stage 4's **fix pass**, with its findings counted by
mark: what that arm produced which nothing else did, and where it was
wrong. These are the least established arms, so the evidence has to be
gathered deliberately or the next session is left arguing from
impressions. For Stage 1c, take the token figure the bridge reports; mark
it **unavailable** only when a run surfaced no count at all. Never
estimate either way.

## Reliability

Whether a given piece of code is worth a dispatch is a judgment threshold,
not a binary — this skill states the bounds and stages, not a formula.
Instruction-based routing (subsystem boundaries, mode selection) yields
correctly _usually_, not _always_; expect to catch misses by hand and
adjust mode or scope mid-run rather than trusting the first pass. `auto`
inherits that caveat in full: its escalator list is a checklist over cheap
metadata, not a risk model, so it will occasionally under-call a diff
whose risk lives in the contents rather than the paths. Overriding it —
before or during the run — is expected use, not a failure. The `standard`
ceiling is the same kind of checklist and inherits the same caveat, with
one asymmetry worth knowing: under-calling it costs coverage silently,
while over-calling it costs an operator one answered question.

## Deliberately left out (do not re-propose)

Decided against, with the reason, so the proposals do not return:

- **A tracker comment drafted per `TRACKED` finding whose review adds
  something.** Each would be a tracker-write ask, priced above filing.
  Stage 3's "adds" notes leave the choice to the operator.
- **An open issue holding a defect the diff introduces, with the visible
  "held by #N" drop as the safeguard.** Anyone who can file could skip a
  fix that way. The cost of closing it is accepted: a fix whose design
  an open issue holds goes to the operator, even where that issue never
  states the finding.
- **Operator confirmation of every new normative wording a fix writes.**
  In a skill repo nearly every fix is wording, so it would ask on nearly
  every fix. Stating what each fix adds keeps it reviewable.
- **A separate pre-push review skill looping fresh reviewer passes with
  `--fixup` and autosquash.** It overlaps `next --review` and Stage 4 and
  multiplies reviewer spend; Stage 4's fix pass runs once, not in a loop.
