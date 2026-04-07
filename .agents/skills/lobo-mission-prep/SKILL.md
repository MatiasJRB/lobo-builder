---
name: lobo-mission-prep
description: Use when asked how to prepare, scope, intake, or refine a mission in Lobo Builder, including requests like "prepare a mission", "mission setup", or "preparar una mision". Explains what inputs to collect, how to choose policy and context links, and what artifacts must exist before implementation starts.
---

# Lobo Mission Prep

Use this skill when the task is to explain or perform mission preparation before any implementation work starts.

## Read first

- `docs/architecture.md`
- `src/autonomy_hub/domain/models.py`
- `src/autonomy_hub/services/planner.py`
- `config/agent_profiles/catalog.yaml`
- `config/policies/catalog.yaml`
- `config/intake/greenfield-questionnaire.yaml`
- `config/templates/catalog.yaml`

## Hard rules

- A mission is the unit of work, not a repository.
- No implementation starts before both `Mission Spec` and `Execution Graph` exist.
- The planner keeps global control and delegates only bounded repo or surface work.
- Parallelism comes from multiple instances of the fixed profile set, never from inventing new roles.
- Mission policy is a hard gate for push, PR, merge, deploy, and migrate behavior.
- Keep `apps/site` isolated from `src/autonomy_hub` runtime concerns unless the mission explicitly bridges them.
- Keep versioned intent in `config/` and `docs/`; treat DB plus `var/` as operational state.

## Intake fields to collect

Base intake maps to `MissionCreateRequest`.

- `brief`: one short description of the problem or change.
- `desired_outcome`: what "handoff-ready" means for this mission.
- `linked_repositories`: repos that the mission may touch.
- `linked_products`: products or project shells the mission targets.
- `linked_documents`: specs, ADRs, tickets, or local docs worth reading first.
- `policy`: default to `safe` unless the user explicitly needs deploy or merge behavior.
- `merge_target`: only set when integration back to a named branch is part of the mission.
- `deploy_targets`: only set when delivery targets are explicitly declared.
- `execution_controls`: only adjust these when the user asks for runtime limits or stage gating.

If the mission type is unclear, let the planner classify it as `fix`, `feature`, `refactor`, or `greenfield`.

## Greenfield extra intake

For greenfield missions, use `config/intake/greenfield-questionnaire.yaml` as the interview skeleton. Capture at least:

- project name
- one-liner
- target user
- problem
- MVP boundary
- primary flow
- entities
- success definition
- first cycle goal
- final checkpoint

Collect optional but useful details when available:

- frontend surface
- backend needs
- auth needs
- integrations
- notes

## How to prepare the mission

1. Normalize the ask into a crisp `brief` and `desired_outcome`.
2. Link the real context up front: repos, products, and documents.
3. If linked repos are local or inspectable, read their `AGENTS.md` and repo-local skills before deciding scope or handoffs.
4. Choose the narrowest valid policy.
   - `safe`: read, write, branch, worktree, commit, push, and PR only.
   - `delivery`: `safe` plus non-production deploys.
   - `prod`: `delivery` plus merge, production deploy, and migrations.
   - `autopilot`: closed-loop merge and deploy without manual handoff.
5. Declare `merge_target` and `deploy_targets` only when they are explicit mission requirements.
6. For greenfield work, select the closest template from `config/templates/catalog.yaml` and confirm the starter repo map before implementation.
7. Ensure the planner can write the first artifacts:
   - `planning_context`
   - `spec`
   - `execution_graph`
   - `project_shell` for greenfield missions
   - `template_selection` when a template is chosen
8. Ensure the first execution wave makes ownership explicit.
   - `context-map` resolves graph relationships.
   - `product-spec` drafts the Mission Spec.
   - `architect-plan` locks repo boundaries and execution order.
9. Only after that, let implementer, verifier, and release or deploy work enter the graph.

## What a good Mission Spec should make explicit

A prepared mission is not just a brief. The resulting spec should name:

- mission type
- summary
- desired outcome
- merge target
- deploy targets
- definition of done
- assumptions
- risks
- repo strategy
- template slug when greenfield
- execution controls

## Ready-to-implement checklist

Treat the mission as ready only when all of these are true:

- `Mission Spec` exists and is specific enough to guide work.
- `Execution Graph` exists and names owners, scope, and ordering.
- Each task has acceptance criteria and expected artifacts.
- Repo or surface boundaries are explicit.
- Policy matches the actual release or deploy intent.
- Linked documents and repos cover the real working context.
- Greenfield missions have a project shell and a template decision before scaffolding.
- The planner still owns the whole mission; no specialist has cross-cutting control.

## Defaults and fallback behavior

- Default `policy` to `safe`.
- Default `desired_outcome` to a handoff-ready state if the user does not define one.
- Leave `merge_target` and `deploy_targets` empty until they are explicitly declared.
- Prefer asking for the missing blocker with the highest leverage first: `brief`, then `desired_outcome`, then linked context, then policy.
- If the mission is still ambiguous after intake, prepare it conservatively and note open assumptions instead of inventing release authority.

## Response shape

When using this skill, return:

- a short mission summary
- the proposed intake payload
- the likely mission type
- the recommended policy with rationale
- missing inputs or risky assumptions
- the artifacts that must be created before implementation begins
