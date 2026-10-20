---
name: ai-review
description: "Multi-agent code review with pinned subagents and no finding cap. Use this INSTEAD of the built-in /code-review, which fans out unpinned general-purpose subagents that inherit the steering model and caps findings at 10; this skill dispatches pinned agent-kit code-reviewer/scout/developer subagents, verifies findings adversarially by stance, reports every verified finding, and covers a diff/branch/PR review, an auto mode that sizes the review to the diff, and exhaustive audits of a named surface or the whole tree. Use whenever asked to review a branch, PR or diff, or to audit a surface or the repository."
argument-hint: "[auto|quick|standard|deep <surface>|deep tree] [PR# | branch]"
---

Multi-agent code review: **$ARGUMENTS**

(If no arguments were given, default to **`auto`** against the current
branch's diff against the default branch, or the open PR if one exists.
`auto` sizes the review itself, choosing between `quick` and `standard` —
see "Mode selection" below, which also governs when it must stop and ask
instead of resolving. Confirm the review **target** with the user when it
was not named; the resolved mode is announced, not confirmed.)

## Why this skill exists

The built-in `/code-review` fans out "general-purpose" subagents with no
`model:` pin, so every one of them inherits the steering model. Observed in
practice: 13 unpinned dispatches on one review — 8 reviewing, 5 applying
fixes — all on the steering model, plus direct main-loop edits. Against a
capped token budget, an unpinned fan-out of that size is a large,
uncontrollable draw. The built-in also truncates its output to the 10 "most
severe" findings; this skill reports every verified finding, no cap, no
top-N slice.

**The built-in `/code-review` MUST NOT be used for reviews.** This skill
replaces it end to end.

## Dispatch policy

- Every dispatch MUST name a pinned agent type (`agent-kit:code-reviewer`,
  `agent-kit:scout`, `agent-kit:backend-developer`,
  `agent-kit:frontend-developer`, …, or the project's own type for the
  same role, which takes precedence here and wherever a stage below names
  an agent-kit type: `agent-kit:delegation`, "The policy"), except an
  optional Stage 1c cross-family bridge the project provides or the user
  opts into. The pin is the one for the client you run in
  (`agent-kit:delegation`, "Pins by client") — **read it** from the
  agent's definition, do not recall it from memory or from this skill.
- General-purpose (unpinned) dispatches are **FORBIDDEN** in this
  workflow — that is the exact defect this skill exists to route around.
  The harness's built-in agent types (`Explore`, `Plan`, …) are **equally
  forbidden**: they carry no `model:` pin either, so a bare dispatch
  inherits the steering model (see the `agent-kit:delegation` skill, "The
  policy").
- The steering loop orchestrates: it dispatches, reads back findings and
  diffs, commits, and reports. It MUST NOT review code itself, and MUST NOT
  implement non-trivial fixes itself. Fixes below the judgment threshold of
  the `agent-kit:delegation` skill (an edit whose closed spec would
  outweigh its own diff) are applied directly in the steering loop — the
  two instantiate ONE policy and must not diverge (delegation, "One policy,
  every consumer"). Observed in practice: a blanket ban on main-loop edits
  sent a ~50k-token dispatch, with a spec longer than the patch, to apply a
  three-line fix.

## Mode selection (`auto`)

`auto` resolves the mode itself, to **`quick` or `standard` only**. It MUST
NOT resolve to `deep`. It runs in the main loop with **zero dispatches**,
reading only cheap metadata for the scope — `git diff --stat`, the
changed-file list, the commit subjects — plus, for a deletion-heavy file,
that file's hunks alone, which is what escalator 3 needs to see. No
subagents, and no reading of the diff at large: this step decides _how
much_ review to buy, it does not review. Every project instruction file
it reads, such as the `AGENTS.md` that draws components and names risk
paths below, is read as its `<merge-base>` copy where the checkout
changes it (`agent-kit:delegation`, "The policy").

**Size is not the criterion.** A 700-line mechanical rename is `quick`; a
40-line change to proxy-header trust is `standard`. What decides it is
whether the diff carries an escalator.

### Escalators — any ONE resolves to `standard`

1. **More than one component touched** — two or more packages, apps or
   modules as the project's `AGENTS.md` draws its boundaries, or repo-root
   infra plus one. A single dispatch covering every review dimension
   across two components' idioms is spread too thin.
2. **A risk-carrying path** — the categories whose defects are not ordinary
   quality findings:
   - auth, crypto, sessions, and trust boundaries (proxy headers, outbound
     request gates, input that crosses a privilege line),
   - transports and privileged paths (remote execution, sockets, anything
     running with elevated rights),
   - release and CI machinery (workflows, version and release scripts,
     deploy artifacts),
   - schema and migrations.

   The project's `AGENTS.md` may name its own risk paths; those count too.
3. **Net removal of behaviour or coverage** — deleted test functions or
   files, a removed public symbol, a deleted module or re-export shim, a
   dropped alias. Refactor diffs fail by silent loss, which is precisely
   what Stage 2 re-reads source to catch — and `quick` has no Stage 2.
4. **A new direct dependency, or a changed dependency floor.** Lockfile
   churn on its own does not count.
5. **Breadth ceiling** — more than ~15 changed files, even with no other
   escalator firing. This is an attention bound on the single `quick`
   dispatch, not a size threshold.

### `quick` requires ALL of

- one component (or a docs/config-only change), **and**
- one coherent concern, **and**
- no escalator above, **and**
- the change sits inside existing gate coverage (the project's test suite
  and mechanized checks) rather than adding a new surface.

A defect class an existing mechanized gate already enforces is **not** an
escalator — the gate catches it whether a reviewer does or not.

### The `standard` ceiling — a wide diff is an ask, not a bigger fan-out

`standard`'s three dispatches are split by **dimension**, and that split
assumes **one coherent surface**: each reviewer holds one component's
idioms and reads the whole diff through one lens. Escalator 5 lifts a wide
diff out of `quick`; nothing above it notices when the same diff also
overruns `standard`. Both failure modes are silent — three dispatches
spread across four subsystems under-cover without saying so, and a fan-out
large enough to cover them is a spend the operator did not authorise.

So `auto` MUST **stop and ask** when the diff breaches the ceiling — the
same rule, for the same reason, as `deep` never being auto-selected. The
ceiling is **two or more** of these, all read from the same cheap metadata:

- **three or more components**, or two plus repo-root infra;
- **more than ~25 changed files**;
- **more than ~1000 added lines** (`git diff --shortstat`), deletions and
  lockfile churn excluded;
- **more than two coherent concerns** — subsystems whose reviewers would
  share no idiom (a page's teardown paths, a privileged wire protocol, a
  release-gate script, an operator doc set).

Present the options with their dispatch counts and let the operator
choose. The three usually live:

1. **`standard` as declared** — 3 dimension dispatches, 1 verifier. Say
   what it will not hold: name which surfaces would share a reviewer.
2. **`standard`, widened** — Stage 1 re-split by **surface**, one dispatch
   per subsystem, **plus one cross-cutting security dispatch over the
   whole diff**; Stage 2 stance-diverse. Where a Stage 1c bridge is
   available, it is an element the operator may include or decline:
   quote the total both with and without it, then record the choice.
3. **`deep <surface>`** — when the concern is the surface's soundness
   rather than this change (see below).

The re-split in option 2 is the part worth understanding rather than
copying. Per-dimension is the wrong axis for a wide diff: it asks one
reviewer to carry several components' conventions at once, which is what
escalator 1 predicts will spread thin. Per-surface gives each reviewer one
idiom — but **security is the one dimension that cannot be
surface-split**, because its findings live at the boundaries between
surfaces, so it stays a whole-diff pass alongside the per-surface ones.

Observed in practice: a 44-file, three-component diff of over 3000 added
lines resolved to plain `standard` under rules that priced only `quick`
under-buying and `deep` over-buying. The wider review that actually ran
did so only because the operator asked for that shape up front, and its
finding set included several that came from exactly one arm of the
fan-out.

### The empirical trigger — orthogonal to the mode

In Claude Code `agent-kit:code-reviewer` has no shell, so it can only
ever reason about code, never run it; under Codex it has a shell but is
forbidden builds and tests, so the same holds. For an ordinary diff that
costs nothing: the project's test suite already executes the change, and
a second empirical arm buys a duplicate. The exception is a diff whose
code the suite does **not** itself execute, or whose correctness rests
on a contract outside the repository. There, a static reviewer's
highest-severity findings are exactly the ones it cannot settle, and it
will report them at full confidence anyway.

Fire **Stage 1b** when either holds:

- the diff changes code that runs **outside the test suite's reach** —
  agent or git hooks, gate helper scripts, CI workflows, deploy artifacts,
  installers; or
- it depends on an **external contract the author could not smoke-test**
  — a third-party CLI's schema, a wire format, a harness payload shape.
  The PR body admitting an unverified assumption is itself the trigger.

This is **not** a mode. It composes with any of them: `quick + 1b` is a
normal configuration, and so is `standard + 1b`. Do not widen `quick` to
mean "quick plus an empirical pass" — the modes size the _reading_, this
trigger decides whether anything gets _run_.

### `deep` is never auto-selected

If the scope looks like it warrants an audit rather than a diff review —
the request is about a surface's soundness rather than about a change, or
the diff reads as a symptom of suspected pre-existing rot — `auto` MUST
**stop and ask**, presenting the proposed `deep` scope, its enumerated
subsystem list, and its dispatch count. It MUST NOT fire a `deep` fan-out
on its own reasoning; that spend stays an explicit operator choice.

### Doubt resolves to a question, not to a mode

When the escalator set is genuinely ambiguous — a borderline risk path, a
removal that may or may not be dead code, a surface the orchestrator does
not know well — `auto` MUST ask rather than pick. Silently resolving to
`standard` "to be safe" is the same error as silently resolving to
`quick`: it spends the operator's budget on a call they did not make.

Absent that doubt, `auto` states its resolution **and the escalators that
fired** (or that none did) as part of the stage-plan announcement below,
then proceeds without waiting for confirmation — delegating the choice is
the point of the mode. The operator can still override mid-run.

## Stage plan

The declared bounds are the contract. Before dispatching anything, state
to the user: the resolved mode, the review target, and the planned
dispatch count (with the subsystem/surface list, for `deep` and for a
widened `standard`) — including which Stage 2 stances will run and whether
Stages 1b and 1c are part of the count.

### Stage 0 — Context (main loop, zero dispatches)

Gather, in the main loop, before any subagent is dispatched (see the
`agent-kit:review-triage` skill, "Gather context before finalizing
findings"):

- the PR description and its linked issue(s) and epic, via the tracker
  CLI (`gh`, `glab`, `tea`),
- the **comments** on each of those. With `tea`, a single-issue or PR read
  needs `--comments` explicitly: every other view, `--output json`
  included, silently omits them (the tea guard enforces this). Observed in
  practice: a comment missed this way is how an implementation
  contradicted a diagnosis recorded on its own issue,
- the status of any entry in the project's decisions log, if it keeps one,
  that the diff touches or that a candidate finding might re-raise: an
  **Accepted** entry is closed — a finding it refutes is a false
  positive, and a true one it accepts is a stated `instance` drop —
  **except** where its `**Premise:**` line has demonstrably failed,
  which is a real finding; a **Proposed** entry is context only, never
  settled (review-triage, "Settled decisions are not findings"),
- the **open issue list**, paged — a per-page limit silently truncates a
  single call. A follow-up the PR body says it "proposed, not filed" may
  since have been filed, and a gap the diff leaves open may already be
  tracked. Observed in practice: a `standard` pass proposed two issues
  that already existed and "corrected" a PR-body note the tracker had
  already overtaken.

Write the **full artifacts** to scratchpad files — the complete `git diff`
for the scope, the complete issue/comment threads, and the `<merge-base>`
copy of each project instruction file the checkout changes, labelled as
the copy that binds this review (`agent-kit:delegation`, "The policy") —
and pass those file paths into every Stage 1/2 reviewer prompt, alongside
a short **context digest** (a few sentences: what the change is for, which
issues it closes, which decisions bear on it). Reviewers are read-only (in
Claude Code no shell, no tracker; under Codex the Stage 1 and Stage 2
reviewer prompts also carry Stage 1b's list): they Read the artifact files
themselves, so their scope and tracker context stay lossless instead of
anchored to the orchestrator's summary — and they never re-fetch.

### Stage 1 — Review fan-out (`agent-kit:code-reviewer`)

Dispatch count depends on mode (`auto` has already resolved to `quick` or
`standard` by this point):

- **`quick`** — 1 dispatch, covering all review dimensions
  (correctness/tests/performance, security,
  conventions/architecture/maintainability/docs) at once, self-verifying.
  No Stage 2.
- **`standard`** (default) — 3 dispatches, split by dimension: (a)
  correctness + tests + performance, (b) security, (c)
  conventions/architecture/maintainability/docs.
- **`standard`, widened** — only after the ceiling ask above was put and
  answered. One dispatch per surface, **plus** one cross-cutting security
  dispatch over the whole diff, which is not one more surface but the
  dimension that cannot be surface-split.
- **`deep <surface>`** — one dispatch per subsystem of the named surface.
  Enumerate the subsystem list and state it to the user before
  dispatching. Soft cap ~6 dispatches; past that, say so and get
  confirmation before proceeding.
- **`deep tree`** — one dispatch per subsystem of the whole repository.
  The enumerated subsystem list and total dispatch count MUST be confirmed
  by the user before any dispatch fires — this is the largest spend this
  skill can make.

This skill makes every scope from `quick` to `deep tree` available; the
operator chooses which one the moment warrants.

Each Stage 1 prompt MUST embed:

- the scope (the path to the full-diff artifact, or an explicit file list
  for `deep`),
- the Stage 0 context digest,
- the false-positive rule: a finding that a linked issue, epic or
  comment, an Accepted decision's rationale (with the `Premise:`
  exception above) or a pattern the project records as settled
  explains away,
- the tracked-finding rule: a finding that any of those, or any other
  tracker issue, already accepts or tracks is not a false positive. It
  is not re-raised, but it stays in the report as a stated drop, marked
  `instance` and naming what holds it,
- an explicit **NO-CAP** instruction: report every verified finding,
  ranked by severity, tail included — the built-in's 10-finding cap does
  not apply here,
- the output format the `agent-kit:code-reviewer` agent defines,
- an instruction to also report what the reviewer was **unsure about**,
  not only what it found.

### Stage 1b — Empirical verification (`agent-kit:scout`), when triggered

Runs in parallel with Stage 1, not after it: the two are independent, and
serializing them doubles the wall-clock for no gain. 1 dispatch; a second
only if the surface splits cleanly (e.g. hooks vs. deploy artifacts).

`agent-kit:scout` is the pinned type because it is the read-only agent
granted a shell. That grant is exactly what this stage needs and exactly
what makes it dangerous: its read-only guarantee is **instruction-level
only**, enforced by nothing but its prompt. So every Stage 1b prompt MUST
carry, in its own words:

- scratchpad-only scratch files, named explicitly; **no writes anywhere in
  the repo**, and `git status --porcelain` reported at the end to prove it;
- no `git` write commands, no mutating build targets, no package
  installs, no tracker writes;
- **a nested agent session (`claude -p`, `codex exec`) runs in the
  scratch dir with no more than its client's built-in permissions and
  sandbox**: no flag, settings or config override, or added directory
  that bypasses or loosens them (among them
  `--permission-mode bypassPermissions`,
  `--dangerously-skip-permissions`, `--allowedTools`, `--settings`,
  `--dangerously-bypass-approvals-and-sandbox`,
  `--sandbox danger-full-access`, `--approve-for-me`, `-c`, `--profile`,
  `--add-dir`), and none under a user configuration that already loosens
  them. A loosened session runs whatever its model chooses outside any
  sandbox or permission check, and Stage 1b's rules are not in its
  prompt. A probe that cannot run on these terms, such as one that needs
  the repo as its working directory, is reported as not run. One that
  runs tests the client and is not a dispatch, but its model and tokens
  are reported for Stage 5, marked unavailable when the run shows none;
- **never point a formatter or fixer at a repo path** — it rewrites
  whatever path it is handed. Copy the file under test into the scratch
  dir first;
- **do not verify a guard by breaking a file the review does not own.**
  Use a temporary fixture. Sibling agents may be editing that file, and
  "restore until `git diff` is empty" silently reverts their work —
  observed in practice, and only the other agent noticing recovered it;
- read exit codes directly (`cmd < payload.json; echo "EXIT=$?"`), never
  through a pipe into `tail`/`head` (the pipe-status guard denies it).

**Report what you ran, not what you inferred.** Every empirical claim MUST
carry its command and that command's actual output. An inference from
`strings` over a stripped binary, a guess from a symbol's absence, or a
reading of code the agent did not execute is **not** an empirical result
and MUST be labelled as an ordinary static finding — with the doubt
stated. The failure this rule exists to prevent: an empirical pass
concluded from `strings` that a tool-name alias table did not exist,
reported the change's headline feature as unreachable, and was refuted by
one query against upstream source. Absence of evidence in a stripped
binary is not evidence of absence, and the breadth of an empirical pass
reads as authority — so its wrong answers are believed harder than a
static reviewer's.

Where the external contract has **documentation or source**, read that
too, and prefer it over inference from a shipped artifact.

Stage 1b's findings pool with Stage 1's for Stage 3. Where the two
disagree on the same claim, the executed result wins over the read one —
unless the "executed" result is an inference, per the paragraph above.

### Stage 1c — Cross-family second opinion (optional)

Only when a pinned cross-family bridge is available, checked in this
order:

- the project's `AGENTS.md` names its own pinned cross-family bridge —
  e.g. a wrapper that runs a pinned Codex agent and verifies the pin
  took. That one takes precedence, as the project's own agent types do,
  and on their terms: one the checkout adds or changes runs only once the
  operator confirms it (`agent-kit:delegation`, "The policy");
  unconfirmed, fall through to the opt-in below;
- otherwise, agent-kit's bridge, where the user has opted in by creating
  the file `${XDG_CONFIG_HOME:-~/.config}/agent-kit/codex-bridge`. The
  opt-in is the user's, once for every project, and lives outside every
  checkout: a branch must not grant its own consent. The bridge checks
  the file itself and exits 2 without it. Run
  `<base>/../../scripts/codex-agent.sh code-reviewer <prompt-file>
  <transcript-file>` from inside the project with the Bash tool's
  `run_in_background` (a foreground call is capped at 10 minutes),
  `<base>` being this skill's base directory and `<transcript-file>` a
  fresh scratchpad path that does not exist yet. Read the bridge's
  stdout (the verified answer) and its own short stderr lines, never the
  transcript wholesale. The pin is the `codex-*` keys in
  `<base>/../../agents/code-reviewer.md`. Any non-zero exit means this
  stage did not happen. Exit 2 means codex was not run; on any other
  exit (3, 124, 137, codex's own status) it ran and billed: record the
  dispatch and the tokens the bridge reports in Stage 5. The bridge is a
  cross-family arm only from a Claude Code steering session; a Codex
  steering loop gets none from it. From a Codex steering session, Stage
  1's dispatches are already Codex spawns on their Codex pins
  (`agent-kit:delegation`, "Pins by client"): native work, not this
  stage.

Every dispatch above runs on one model family. Correlated blind spots
survive that unanimously, and five same-family reviewers agreeing is
weaker evidence than it reads as. This stage buys the one thing another
same-family dispatch cannot: a different family reading the same
artifacts. Pass it the same scratchpad artifacts every other reviewer
gets, so it re-fetches nothing, and read its pin from the bridge's own
configuration rather than recalling it.

The bridge must prove the pin was applied. An invocation that silently
falls back to an unpinned agent on a default model reviews anyway and
reports that it ran — a stage that bought nothing. If the bridge's check
fails, this stage did **not** happen, whatever the returned findings look
like.

On the `standard`-ceiling path, include it only when the operator selected
it, and include it in the stated count. Outside the ceiling path, fire it
on a risk-carrying path whose defect class would be expensive to miss. It
is **not** a mode, and it does not replace a Stage 1 dispatch: its
findings pool with theirs and go through Stage 2 unprivileged. A
cross-family finding is not more likely to be true; it is less likely to
be one the rest of the pool would ever have raised. Its empirical claims
are bound by Stage 1b's "report what you ran, not what you inferred" rule
exactly as the scout's are.

Observed in practice: on one wide review, the cross-family arm produced
two in-diff findings no same-family dispatch raised, and settled the top
finding by executing the validator the static reviewers had argued about
from source.

### Stage 2 — Adversarial verification (`agent-kit:code-reviewer`), by stance

Every verifier is prompted to **refute** each pooled finding against
source rather than confirm it, re-reading every High-severity finding
individually against the file it names. Verdicts: `CONFIRMED` /
`PLAUSIBLE` / `REFUTED`. Drop `REFUTED` findings.

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

### Stage 3 — Report (main loop)

Report every surviving finding, ranked by severity, no cap. Per finding:

- severity,
- triage destination, per the `agent-kit:review-triage` skill ("Triaging
  findings"): **fix in-branch** when the finding is about the diff under
  review (the standing ask — see Stage 4); otherwise a tracked issue, or a
  release milestone only on the project's release-admission bar, if its
  decisions log defines one,
- a one-word `novel` / `instance` mark — `instance` names the mechanized
  check, `AGENTS.md` rule, prior finding or tracking issue it instances
  (review-triage, "Mark each finding novel or instance").

When the review target is, or has, an open PR, post the full verified set
as a PR comment with the tracker CLI **before** acting on any of it.
The comment names the branch the review ran against and its
`<merge-base>` (`agent-kit:delegation`, "The policy"), so a PR retargeted
after review visibly has none for its new base.
Proposed follow-up issues are proposed to the user — never filed
unprompted. That bar is about **writing to the tracker**, not about fixing
code: a small out-of-diff fix is applied and reported, not proposed.

Every finding must reach a terminal destination — fixed, filed, or
explicitly dropped with the drop stated as such, on one of review-triage's
drop grounds ("What may be dropped"). "Recorded in the review
comment" is reporting, not a destination (review-triage, "Every finding
reaches a terminal destination").

**Proposing is not a destination** — it is a question owed an answer, and
the finding stays pending until the user rules. A run holding open
proposals is **not** finished: put each one in visible end-of-turn text or
a question (never only in the PR comment or description), and report the
run as complete only once they are answered and routed. If the run cannot
wait, file or drop the finding and say which.

**Before assigning a destination, measure the fix** (review-triage,
"Measure the fix"). Grep for what depends on the thing; the size test
compares the real patch against the issue text that would describe it,
and a headline is not a measurement. Then apply "Asking has a cost too":
"propose to the user" is for findings whose **decision** is the user's (a
design choice with more than one defensible answer, a user-visible
behaviour change, a scope call, a tracker mutation) — never a parking
space for a finding that is merely out-of-diff. If you cannot name the
decision you are deferring, fix, file or drop it.

### Stage 4 — Fixes (only when the standing ask applies)

Reviewing an unmerged branch or PR is itself the ask for the fixes it
produces; this stage runs only then.

- Group confirmed in-branch findings into small, closed specs.
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
- Gates are the project's, as its rules name them (e.g. `make lint`,
  `make test`): the fast gate before each commit; once every
  fix is committed, the push gate before the single push at the end, as
  the `agent-kit:push-gate` skill defines it.

### Stage 5 — Cost report (every run, all modes)

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

Record the same pair for **Stage 1c**, where it ran, and for each Stage 2
**stance**: what that arm produced which nothing else did, and where it
was wrong. These are the least established arms, so the evidence has to be
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
