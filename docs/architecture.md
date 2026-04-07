# Architecture

## Core stance

`autonomy-hub` is planner-led, mission-centric, and local-first.

- The unit of work is a `Mission`, not a repository.
- A mission must have a `Mission Spec` and `Execution Graph` before code edits begin.
- The `Planner` always keeps global control; specialist agents only receive bounded repo/surface ownership.
- Local interactive execution is the default mode. Remote state and runners are optional support systems, not the primary workflow.

## Runtime shape

### App layer

- `FastAPI` serves both JSON APIs and the lightweight dashboard.
- The dashboard is operational observability, not a PM suite:
  - `cola`: mission queue, owner, next step
  - `estado`: artifacts, summaries, permissions, result
  - `mapa`: graph nodes/edges across products, repos, environments

### Persistence

- Versioned in Git:
  - agent profiles
  - mission policies
  - greenfield intake questionnaire
  - template catalog
  - architecture and migration docs
- Persisted in DB:
  - missions
  - execution tasks
  - artifacts
  - graph nodes and edges

SQLite is the default local backing store. `AUTONOMY_DATABASE_URL` allows switching the same code to Railway Postgres.

The local runner persists execution state in DB and full logs under `var/runs/<mission_id>/...`.

## Core contracts

### Mission

- `id`
- `type`
- `brief`
- `desired_outcome`
- `linked_products`
- `linked_repositories`
- `linked_documents`
- `policy`
- `merge_target`
- `deploy_targets`
- `status`
- `spec`
- `artifacts`
- `execution_tasks`

### MissionPolicy

Closed set:

- `safe`
- `delivery`
- `prod`
- `autopilot`

Each policy also expands to explicit capability flags: `can_push`, `can_open_pr`, `can_merge`, `can_deploy`, `can_migrate`, and the lower-level read/write/worktree/commit gates.

`autopilot` is meant for closed-loop delivery missions where the cycle is allowed to merge back to a declared mainline target and execute an explicitly declared non-production or mobile distribution deploy target.

### AgentProfile

Profiles are fixed by function:

- Planner
- Context Mapper
- Product/Spec
- Architect
- Backend Implementer
- Frontend Implementer
- Data/Infra Implementer
- Verifier/Reviewer
- Release/Deploy

Parallelism happens by instantiating multiple copies of a fixed profile, never by inventing new agent roles ad hoc.

### Context Graph

Minimum node kinds already modeled:

- `Product`
- `Project`
- `Repository`
- `Environment`
- `Document`
- `Mission`
- `Artifact`
- `AgentProfile`
- `CapabilityPolicy`

Current relation families:

- `contains_project`
- `owns_repository`
- `hosts_repository`
- `targets_product`
- `targets_repository`
- `references_document`
- `governed_by`
- `produces_artifact`
- `creates_project_shell`

## Planning flow

1. Intake enters as mission brief.
2. Planner classifies it into `fix | feature | refactor | greenfield`.
3. Context graph is resolved/enriched.
4. Planner writes initial spec + execution graph artifacts.
5. Architect is the first ready owner.
6. Implementers are queued per repo/surface.
7. Verifier gates release actions.
8. Release/Deploy acts only within the mission policy.

For full-UI polish missions, the planner cuts the work by dependency and leverage, not by route importance:

- foundation first
- full user-facing surface sweep second
- coherence hardening and release readiness last

## Greenfield behavior

Greenfield is native, not exceptional.

Current bootstrap behavior:

- create a `Project Shell`
- select a template from versioned config
- derive starter repo map
- emit a first execution wave with architect + implementers + verifier + release gates

## Runner behavior

The runner is local-first and process-hosted by the hub app.

- missions do not auto-start on creation
- `run`, `resume`, and `interrupt` are explicit API actions
- each mission run persists branch, worktree, heartbeat, current task, command executions, and errors
- specialist execution uses `codex exec`
- verify and release steps use deterministic repo commands

For `autopilot`, the initial supported closed loop is:

- isolated mission branch + worktree
- sequential execution of the mission DAG
- final verify gate
- merge back into the declared mainline target
- Android Firebase App Distribution when that target is declared and resolved from project context

The intake questionnaire and template selection logic are designed to absorb useful ideas from `../spec-forge` without depending on that repo at runtime.
