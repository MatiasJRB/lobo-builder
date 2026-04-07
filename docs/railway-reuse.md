# Railway reuse plan

Verified on **2026-04-06** through the local Railway CLI.

## Current projects found

Relevant entries:

- `ops-codex-mvp`
  - project id: `1db7b0a2-744c-4a0c-87b6-e8aff83bcb31`
  - services: `Postgres`, `codex-runner`, `control-plane`
  - environment: `production`
- `ops-codex-mvp`
  - project id: `a4688fb3-f926-4615-9166-04d4c67a4e52`
  - services: none
  - environment: `production`

## Recommended interpretation

The first project looks like the real one to reuse because it already has the expected services. The second one appears to be a duplicate shell and should be reviewed before any rename or migration work to avoid ambiguity.

## Target naming

- Project identity: `autonomy-hub`
- Service `control-plane` -> `autonomy-control-plane`
- Service `codex-runner` -> `autonomy-runner`
- Service `Postgres` -> `autonomy-db`

## Suggested sequence

1. Confirm which `ops-codex-mvp` project is canonical.
2. Point `AUTONOMY_DATABASE_URL` at the canonical Postgres.
3. Rename services/resources to the neutral autonomy naming.
4. Keep local-first execution as the default even after remote state is connected.
5. Add runner behavior only after dashboard + graph + mission model stabilize locally.

## Important constraint

Railway is support infrastructure for state, dashboard hosting, and optional runners. It should not pull the system toward a cloud queue-first architecture.

