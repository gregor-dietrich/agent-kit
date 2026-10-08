agent-kit is installed. Four rules from its `agent-kit:delegation` skill
apply whenever you dispatch subagents (read the skill before a fan-out):

- Dispatch only pinned agent types (`agent-kit:scout`,
  `agent-kit:code-reviewer`, `agent-kit:software-architect`,
  `agent-kit:backend-developer`, `agent-kit:frontend-developer`). Where
  the project defines its own pinned agent, or its own skill, for the same
  role, use the project's instead. A general-purpose or built-in
  `Explore`/`Plan` dispatch carries no model pin and silently inherits the
  steering model; where a harness workflow forces one, pass an explicit
  model override.
- Read every returned diff before it lands. Subagents never commit and
  never re-delegate.
- A small edit whose closed spec would outweigh its diff stays in the
  steering loop; a non-trivial one goes to a pinned writing agent.
- A session that dispatched agents ends with a cost report: per dispatch
  the agent type, model run and tokens from the tool result, plus
  totals. Mark tokens unavailable when none were reported; never estimate.
