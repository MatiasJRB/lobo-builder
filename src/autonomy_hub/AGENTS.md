# Backend Agent Guide

## Scope

These instructions apply to `src/autonomy_hub`.

## Layering

- `main.py` wires the app, settings, services, and dashboard mount points.
- `api/routes.py` should stay thin and delegate orchestration to services.
- `services/*` own planning, graph resolution, mission lifecycle, runner orchestration, and project context.
- `adapters/*` isolate external integrations and shell/runtime execution details.
- `domain/models.py` is the shared contract surface for mission, policy, task, and artifact shapes.
- `db.py` owns persistence primitives and record mappings.

## Guardrails

- Preserve the planner-led architecture: planning and policy constraints should remain explicit, not implicit side effects.
- Keep versioned config loading in `config/` and operational state in DB plus `var/`.
- When touching `runner.py`, `planner.py`, or `graph.py`, verify that mission status transitions, policy gates, and artifact persistence still line up.
- Prefer adding behavior in services or adapters rather than bloating routes or app startup.
- Treat `config/runner_prompts/*` as contract-adjacent inputs for execution behavior; do not casually diverge from their intended profile boundaries.

## Validation

- Run `.venv/bin/pytest`, or a focused subset when the change is narrow.
