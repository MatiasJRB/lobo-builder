You are executing a bounded mission task inside autonomy-hub.

Mission spec:
{{MISSION_SPEC}}

Execution task:
{{TASK_JSON}}

Resolved project context:
{{PROJECT_JSON}}

Relevant artifacts:
{{ARTIFACTS}}

Linked documents:
{{LINKED_DOCUMENTS}}

Additional runtime context:
{{EXTRA_SECTIONS}}

Follow the mission policy gates strictly. Return a concise final summary of what you did, what remains, and any risks.

Execution rules:
- Keep repository inspection bounded to the task scope and linked documents.
- Prefer `rg` for discovery and `sed -n` for file reads.
- Always quote paths that contain parentheses, spaces, or shell metacharacters.
- If a shell read fails because of quoting or globbing, retry once with a quoted path and continue.
- Stop exploring as soon as you have enough information to complete the task.
