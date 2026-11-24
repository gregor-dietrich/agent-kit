agent-kit is installed. Four rules from its `agent-kit:delegation` skill
apply whenever you dispatch subagents (read it first):

- Dispatch only pinned agent types (`agent-kit:scout`,
  `agent-kit:code-reviewer`, `agent-kit:software-architect`,
  `agent-kit:backend-developer`, `agent-kit:frontend-developer`) on your
  client's pin: Claude Code's `model:`, Antigravity's `model:` tier, or
  Codex's `codex-model` and `codex-effort`. Where the project defines its
  own pinned agent or skill for the same role, use the project's instead
  (not a reviewer this checkout changed). Never rely on an unpinned
  general-purpose or built-in (`Explore`/`Plan`/`self`) dispatch; where a
  harness workflow forces one, pass the closest role's pin.
- Read every returned diff before it lands. Subagents never commit and
  never re-delegate.
- A small edit whose closed spec would outweigh its diff stays in the
  steering loop; a non-trivial one goes to a pinned writing agent.
- A session that dispatched agents ends with a cost report: per dispatch
  the agent type, client, model and effort run and tokens, plus totals.
  Mark tokens unavailable when none were reported; never estimate.
