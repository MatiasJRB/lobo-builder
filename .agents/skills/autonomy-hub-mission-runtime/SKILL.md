---
name: autonomy-hub-mission-runtime
description: Use when changing mission planning, execution graphs, runner behavior, policy gating, graph resolution, or agent-profile orchestration in Lobo Builder. Covers the planner-led and local-first architecture of autonomy-hub.
---

# Autonomy Hub Mission Runtime

Use this skill for the core autonomy-hub runtime, especially when a change affects mission lifecycle or the rules by which specialist agents operate.

## Read first

- `docs/architecture.md`
- `config/agent_profiles/catalog.yaml`
- `config/policies/catalog.yaml`
- `config/runner_prompts/*`
- `src/autonomy_hub/services/planner.py`
- `src/autonomy_hub/services/runner.py`
- `src/autonomy_hub/services/graph.py`

## Hard rules

- The unit of work is a mission, not a repository.
- A mission should have a spec and execution graph before implementation begins.
- The planner keeps global control and delegates only bounded repo or surface work.
- Policies are hard gates, not hints. `safe`, `delivery`, `prod`, and `autopilot` must preserve their capabilities.
- Keep versioned contracts in Git (`config/`, `docs/`) and operational state in the DB plus `var/`.

## Change checklist

1. Check whether the change alters mission classification, task generation, policy expansion, or run-state transitions.
2. Confirm the fixed profile set still matches the intended execution flow.
3. Update tests when planning or runner behavior changes.
4. Prefer targeted inspection over broad repo sweeps; this code is orchestration-sensitive.
