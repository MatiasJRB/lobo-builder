# autonomy-hub

Hub planner-led y local-first para trabajo autónomo multi-repo. El repo está pensado como control plane personal, pero con modelo de misión transversal: puede coordinar un repo, varios repos relacionados o un proyecto greenfield que todavía no existe.

## Qué incluye esta v1

- backend `FastAPI` con dashboard servido por la misma app
- persistencia híbrida:
  - config y contratos versionados en Git (`config/`, `docs/`)
  - estado operativo en DB (`SQLite` local por default, `Postgres` remoto opcional)
- graph central con nodos mínimos para `Product`, `Project`, `Repository`, `Environment`, `Document`, `Mission`, `Artifact`, `AgentProfile` y `CapabilityPolicy`
- planner heurístico inicial que:
  - clasifica la misión en `fix | feature | refactor | greenfield`
  - genera `Mission Spec`
  - genera `Execution Graph`
  - aplica el gate de política `safe | delivery | prod | autopilot`
- runner local persistido que:
  - ejecuta tasks por DAG
  - usa `codex exec` como runtime de agentes
  - corre verify/release con comandos determinísticos
  - persiste runs, command logs, branch y worktree
- adapters v1 para filesystem/workspace local, Git, GitHub, Railway, Vercel y Firebase App Distribution

## Quick start

```bash
cd /Users/matiasrios/Documents/GitHub/lobo-builder
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
autonomy-hub
```

La app levanta por default en [http://127.0.0.1:8042](http://127.0.0.1:8042).

## Variables útiles

- `AUTONOMY_DATABASE_URL`
  - default local: `sqlite+pysqlite:///.../autonomy-hub/var/autonomy-hub.db`
  - remoto: usar el Postgres reutilizado desde Railway cuando quieras persistencia compartida
- `AUTONOMY_WORKSPACE_ROOT`
  - root para autodiscovery de repos locales
- `AUTONOMY_AUTO_DISCOVER_LOCAL`
  - `true` por default
- `AUTONOMY_DISCOVER_MAX_DEPTH`
  - profundidad máxima de scan local

## API principal

- `GET /health`
- `GET /api/dashboard`
- `GET /api/graph`
- `GET /api/missions`
- `POST /api/missions`
- `POST /api/missions/{id}/run`
- `POST /api/missions/{id}/resume`
- `POST /api/missions/{id}/interrupt`
- `GET /api/missions/{id}/runs`
- `GET /api/missions/{id}/logs`
- `POST /api/discovery/local`

Ejemplo mínimo:

```bash
curl -X POST http://127.0.0.1:8042/api/missions \
  -H 'content-type: application/json' \
  -d '{
    "brief": "Polish every user-facing screen and component in the Android app",
    "desired_outcome": "Close each accepted cycle in main and ship Android tester builds",
    "mission_type": "refactor",
    "linked_repositories": ["asiento-libre"],
    "linked_products": ["Asiento Libre"],
    "policy": "autopilot",
    "merge_target": "main",
    "deploy_targets": ["android-firebase-app-distribution"]
  }'
```

## Layout

- `src/autonomy_hub/main.py`
  app factory + dashboard
- `src/autonomy_hub/services/planner.py`
  misión -> spec + execution graph
- `src/autonomy_hub/services/graph.py`
  graph central + autodiscovery local
- `src/autonomy_hub/services/missions.py`
  persistencia y vistas operativas
- `config/`
  perfiles, policies, intake greenfield y template catalog
- `docs/architecture.md`
  decisiones de arquitectura
- `docs/spec-forge-audit.md`
  qué absorber de `../spec-forge`
- `docs/railway-reuse.md`
  plan para reutilizar y renombrar el proyecto Railway existente

## Estado actual

Esta base ya materializa el modelo central de misión y también un runner local real para el slice `autopilot` inicial. Hoy el hub puede persistir runs, crear worktrees/branches, ejecutar perfiles vía `codex exec`, correr verify, mergear localmente a `main` y disparar Android Firebase App Distribution cuando el proyecto resuelve ese target.

Todavía faltan paralelismo real multi-repo, runners remotos, migraciones DB formales y soporte de más targets de release, pero el sistema ya dejó de ser sólo un planner/control plane.
