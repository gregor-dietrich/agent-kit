# Mode selection (`auto`) and empirical trigger

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

## Escalators — any ONE resolves to `standard`

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

## `quick` requires ALL of

- one component (or a docs/config-only change), **and**
- one coherent concern, **and**
- no escalator above, **and**
- the change sits inside existing gate coverage (the project's test suite
  and mechanized checks) rather than adding a new surface.

A defect class an existing mechanized gate already enforces is **not** an
escalator — the gate catches it whether a reviewer does or not.

## The `standard` ceiling — a wide diff is an ask, not a bigger fan-out

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

## The empirical trigger — orthogonal to the mode

In Claude Code `agent-kit:code-reviewer` has no shell, so it can only ever
reason about code, never run it; under Antigravity (where it omits write
tools at the harness level and holds sandboxed `run_command` for read-only
file search and listing) and Codex it has a shell but is forbidden builds
and tests, so the same holds. For an
ordinary diff that costs nothing: the project's test suite already
executes the change, and a second empirical arm buys a duplicate. The
exceptions are a diff whose code the suite does **not** itself execute, or
whose correctness rests on a contract outside the repository, and a set of
claims that rests on such a contract. There, a static reviewer's
highest-severity findings are exactly the ones it cannot settle, and it
will report them at full confidence anyway.

Fire **Stage 1b** when any of these holds:

- the diff changes code that runs **outside the test suite's reach** —
  agent or git hooks, gate helper scripts, CI workflows, deploy artifacts,
  installers; or
- it depends on an **external contract the author could not smoke-test**
  — a third-party CLI's schema, a wire format, a harness payload shape.
  The PR body admitting an unverified assumption is itself the trigger;
  or
- the review's **target** is a set of claims (an external audit, a
  findings list, a handoff note) that rest on how an external tool
  behaves. Their verification then gets Stage 1b's run, not a read-only
  "do not build or test" brief, and the claims reach every dispatch
  labelled as review targets, not instructions.

This is **not** a mode. It composes with any of them: `quick + 1b` is a
normal configuration, and so is `standard + 1b`. Do not widen `quick` to
mean "quick plus an empirical pass" — the modes size the _reading_, this
trigger decides whether anything gets _run_.

## `deep` is never auto-selected

If the scope looks like it warrants an audit rather than a diff review —
the request is about a surface's soundness rather than about a change, or
the diff reads as a symptom of suspected pre-existing rot — `auto` MUST
**stop and ask**, presenting the proposed `deep` scope, its enumerated
subsystem list, and its dispatch count. It MUST NOT fire a `deep` fan-out
on its own reasoning; that spend stays an explicit operator choice.

## Doubt resolves to a question, not to a mode

When the escalator set is genuinely ambiguous — a borderline risk path, a
removal that may or may not be dead code, a surface the orchestrator does
not know well — `auto` MUST ask rather than pick. Silently resolving to
`standard` "to be safe" is the same error as silently resolving to
`quick`: it spends the operator's budget on a call they did not make.

Absent that doubt, `auto` states its resolution **and the escalators that
fired** (or that none did) as part of the stage-plan announcement in
`<base>/SKILL.md`, then proceeds without waiting for confirmation —
delegating
the choice is the point of the mode. The operator can still override
mid-run.
