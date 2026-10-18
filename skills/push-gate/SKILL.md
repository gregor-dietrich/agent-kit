---
name: push-gate
description: "Which gate runs before a git push, and how: the gate the project's own rules require for the class of change the push carries, the full gate only where they define nothing narrower; on a clean tree; through the push hook, never around it; and the report line naming the gate that ran and why. Read it before any push, inside /agent-kit:plan-run or /agent-kit:ai-review or on its own, and before reporting a change as verified."
---

# The gate a push owes

RFC 2119 key words (MUST/MUST NOT/SHOULD/MAY) are to be interpreted as
described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) /
[RFC 8174](https://www.rfc-editor.org/rfc/rfc8174): they bind only when
written in uppercase.

## Which gate

Read the scoping from the project's rules as they stand on `<base>`
(below), not on the branch: its `AGENTS.md`/`CLAUDE.md` (nested ones for
touched directories included, and what they import), its scoped rule
files and its decisions log, where only an entry marked Accepted defines
a gate. Read each with `git show <base>:<path>`
(`git ls-tree -r --name-only <base>` lists them). A rule file `<base>`
lacks does not apply, and a branch's own edit to one takes effect once it
merges. Where they define a narrower gate for a class of change
(docs-only, for example) and every file the branch carries is in that
class, that gate is the push gate; otherwise the full gate is. A check
the rules add for a class the push touches (a validator after a manifest
change, say) runs on top of whichever gate applies. Only the scoping
comes from `<base>`: the gate's commands run as the branch defines them,
as CI runs them.

Judge the class from everything the branch carries into its target, not
the last commit and not what this session edited:
`git diff --name-only --no-renames <base>...HEAD`, where `<base>` is the
branch the PR or merge targets, freshly fetched (e.g. `origin/main`).
Never diff against the branch's own upstream (`@{u}`): that range holds
only the commits since the last push. `--no-renames` so a moved file
shows both paths. Where the tree is not clean (verifying before a
commit, as debugging's Phase 4.3 does), the uncommitted files count too:
add `git status --short --untracked-files=all`. An empty file set means
the full gate; so does no known target branch, with the rules read at
HEAD and the report saying so. In doubt, the full gate.

## How it runs

- On a clean tree (everything committed, no untracked files), so what it
  verified is exactly what is pushed.
- With a tool timeout long enough for the gate and for whatever the push
  hook runs. MUST NOT use `--no-verify`, a timed-out push included.
- The invariant is that the pushed tip is green under the gate the
  project requires.

## The push hook

To learn what the hook runs, read the file
`git rev-parse --git-path hooks/pre-push` names (it honours
`core.hooksPath`), and what it invokes where a hook manager installed
it.

Where the project's push hook runs more than its rules require (the full
gate on a docs-only push), the agent cannot follow both. It runs the gate
the rules require, pushes normally, and lets the hook run what it runs.
It MUST NOT bypass the hook and MUST NOT edit the hook or the rules; it
reports the mismatch, what the rule requires and what the hook ran, for
the project to resolve. Paying for the hook's run is unavoidable without
a bypass; paying for it silently is what this rules out.

Where the hook fails while the required gate passed, the push did not
happen: stop and report the hook's failure, with the mismatch if any. Do
not push around it and do not fix code outside the change to turn it
green.

## The report

The report goes where the calling run already records: the PR
description of a PR this run opened or owns, otherwise that run's own
record (ai-review's PR comment, say), or the end-of-turn text. It names:

- the gate that ran (exact command) and its result;
- why that gate: the rule it came from (file and section), "the project
  defines nothing narrower", or what made the class doubtful;
- the change class and the diff range it was judged from;
- any hook mismatch.
