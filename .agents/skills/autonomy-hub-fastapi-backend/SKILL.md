---
name: autonomy-hub-fastapi-backend
description: Use when editing the FastAPI backend, services, adapters, DB layer, dashboard serving, or backend tests in Lobo Builder. Covers the `src/autonomy_hub` Python application and its planner-runner-service architecture.
---

# Autonomy Hub FastAPI Backend

Use this skill for backend implementation work in the Python app.

## Read first

- `src/autonomy_hub/main.py`
- `src/autonomy_hub/api/routes.py`
- `src/autonomy_hub/db.py`
- `src/autonomy_hub/domain/models.py`
- `src/autonomy_hub/services/*`
- `tests/*`

## Guardrails

- Keep routes thin and push orchestration into services.
- Keep shell/runtime and third-party calls behind adapters when possible.
- Preserve local-first startup assumptions and runtime recovery behavior.
- Avoid mixing versioned config concerns with mutable mission/run state.
- If the change touches runner, planner, or graph behavior, treat it as orchestration work, not a narrow route edit.

## Validation

- Run `.venv/bin/pytest`.
- When feasible, target the narrow test file first, then broaden if the change crosses services.
