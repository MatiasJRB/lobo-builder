# Lobo Builder Agent Guide

## Core stance

Lobo Builder is planner-led, mission-centric, and local-first.

- The unit of work is a `Mission`, not a repository.
- A mission should have a `Mission Spec` and `Execution Graph` before implementation starts.
- The `Planner` keeps global control; specialists only own bounded repo or surface work.
- Local execution is the default. Remote state and remote runners are optional extensions.

## Project map

- `src/autonomy_hub`: FastAPI app, dashboard, domain models, services, adapters, and DB wiring.
- `config/`: versioned policies, agent profiles, prompt templates, project context, and template catalog.
- `docs/`: architecture and migration/reference documents.
- `apps/site`: public Astro landing, separate from the backend dashboard and APIs.
- `tests/`: backend verification.
- `var/`: operational runtime state and logs. Treat as mutable data, not as source of truth.

## Non-negotiable rules

- Keep planner-led flow intact. Do not bypass mission planning or policy gates with ad hoc execution paths.
- Respect the fixed profile set in `config/agent_profiles/catalog.yaml`; parallelism comes from multiple instances of known roles, not improvised role sprawl.
- Treat `config/` and `docs/` as versioned contracts, and `var/` plus the database as operational state.
- Policy slugs in `config/policies/catalog.yaml` are hard gates for push, PR, merge, deploy, and migrate behavior.
- Keep the public Astro site isolated from `src/autonomy_hub` backend/runtime concerns unless a task explicitly bridges them.

## Validation defaults

- Backend: `.venv/bin/pytest`
- App startup spot-check: `.venv/bin/python -m autonomy_hub.main`
- Astro site: `cd apps/site && npm run check`
- Astro build: `cd apps/site && npm run build`

## Skills to prefer

- `.agents/skills/autonomy-hub-mission-runtime/SKILL.md`
- `.agents/skills/autonomy-hub-fastapi-backend/SKILL.md`
- `.agents/skills/autonomy-hub-astro-site/SKILL.md`
- `.agents/skills/deploy-to-vercel/SKILL.md`
- `.agents/skills/web-design-guidelines/SKILL.md`

## Custom agents

- `.codex/agents/planner.toml`
- `.codex/agents/context-mapper.toml`
- `.codex/agents/product-spec.toml`
- `.codex/agents/architect.toml`
- `.codex/agents/backend-implementer.toml`
- `.codex/agents/frontend-implementer.toml`
- `.codex/agents/data-infra-implementer.toml`
- `.codex/agents/verifier-reviewer.toml`
- `.codex/agents/release-deploy.toml`
