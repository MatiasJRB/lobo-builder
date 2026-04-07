# Lobo Builder

Lobo Builder es un control plane planner-led y local-first para misiones de software.

Recibe un brief, lo convierte en una misión con `Mission Spec` y `Execution Graph`, asigna ownership a perfiles fijos y ejecuta el trabajo con policies, trazabilidad y control explícito.

No intenta ser otro gestor de tickets ni una caja negra de agentes. Su foco es dar una forma estable de modelar misiones, correrlas sobre repositorios reales y dejar evidencia suficiente para entender qué se decidió, qué se ejecutó y bajo qué permisos.

Sitio público: [lobo-builder.vercel.app](https://lobo-builder.vercel.app)  
Dashboard local: [http://127.0.0.1:8042](http://127.0.0.1:8042)

## Qué es Lobo Builder

Lobo Builder trabaja sobre misiones, no sobre prompts sueltos ni sobre un repositorio aislado. Cada misión puede reunir contexto de producto y contexto técnico en una sola unidad operable:

- `brief`
- `desired_outcome`
- `policy`
- `execution_controls`
- `linked_products`
- `linked_repositories`
- `linked_documents`

Sobre esa base, el sistema persiste:

- `Mission Spec`
- `Execution Graph`
- artifacts asociados a la misión
- runs, logs, errores y estado operativo

## Principios

- Planner-led: el planner mantiene el control global de la misión.
- Mission-centric: la unidad de trabajo es la misión, no el repo.
- Local-first: la ejecución corre localmente por defecto.
- Governed execution: verify, release y deploy siguen policies explícitas.
- Fixed profiles: la paralelización viene de repetir perfiles conocidos, no de inventar roles ad hoc.

## Cómo funciona

### 1. La misión entra al sistema

El brief se clasifica como `fix`, `feature`, `refactor` o `greenfield`, y queda asociado a productos, repositorios y documentos relevantes.

### 2. El planeamiento queda persistido

Antes de ejecutar cambios, Lobo Builder escribe un `Mission Spec` con outcome, done definition, supuestos y riesgos, y arma un `Execution Graph` que define orden, dependencias y ownership.

### 3. El planner coordina

Los especialistas no reciben autonomía ilimitada. Cada perfil opera dentro de superficies y herramientas acotadas, mientras el planner conserva la coordinación general de la misión.

### 4. El runtime ejecuta

La ejecución vive en el hub:

- `run`, `resume` e `interrupt` son acciones explícitas
- el runner prepara `branch` y `worktree`
- cada run conserva heartbeat, logs, comandos, errores y artifacts
- los especialistas ejecutan vía `codex exec`
- verify y release usan comandos determinísticos

### 5. Las policies gobiernan el cierre

Las policies no son etiquetas. Expanden permisos concretos para:

- `read`
- `write`
- `branch`
- `worktree`
- `commit`
- `push`
- `open_pr`
- `merge`
- `deploy`
- `migrate`

Las policies cerradas del sistema son:

- `safe`
- `delivery`
- `prod`
- `autopilot`

## Qué incluye

### Modelo de misión

- `Mission Spec`, `Execution Graph` y artifacts asociados
- contexto transversal por producto, repositorio, documento y entorno
- policies y execution controls como parte del contrato de la misión

### Runtime operativo

- runs persistidos con `branch`, `worktree` y `current_task`
- command logs y errores guardados por misión
- recuperación de estado para inspeccionar, pausar y retomar trabajo

### Gobierno y permisos

- policies cerradas con capability flags explícitos
- verify, release y deploy gobernados por esas flags
- merge, deploy y migraciones sólo cuando la misión lo habilita

### Contexto y observabilidad

- dashboard FastAPI con cola, estado y grafo
- graph central con nodos de producto, proyecto, repositorio, entorno, documento, misión y artifact
- descubrimiento de instrucciones repo-locales para respetar contratos existentes

## Capas del sistema

### Planner y perfiles

El planner clasifica la misión, selecciona estrategia, define ownership y coordina el orden de ejecución. Los demás perfiles existen para tareas concretas, no para reemplazar esa autoridad.

Perfiles fijos:

- Planner
- Context Mapper
- Product/Spec
- Architect
- Backend Implementer
- Frontend Implementer
- Data/Infra Implementer
- Verifier/Reviewer
- Release/Deploy

### Runner y ejecución

El runner toma la misión planeada y la lleva al trabajo concreto sobre el repositorio resuelto, con `worktree`, `branch`, logs y recuperación de estado.

### Dashboard y API

La misma app expone las APIs JSON y la interfaz operativa. La landing pública explica el sistema; el dashboard opera la misión.

### Integraciones y destinos

Lobo Builder modela integraciones sin convertirlas en side effects implícitos. La capa actual incluye:

- Filesystem local
- Git
- GitHub
- Railway
- Vercel
- Firebase App Distribution

## Arquitectura y persistencia

La arquitectura separa contratos versionados, estado operativo y superficies de ejecución para que el planeamiento y el runtime hablen el mismo idioma.

Versionado en Git:

- `config/`
- `docs/`
- catálogos de policies, perfiles y templates
- documentación de arquitectura y migraciones

Persistido como estado operativo:

- base de datos (`SQLite` local por defecto, `Postgres` opcional)
- `var/` para runs y logs
- estado de misión, tasks y artifacts

## Quick start

```bash
cd /Users/matiasrios/Documents/GitHub/lobo-builder
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
autonomy-hub
```

La app levanta por defecto en [http://127.0.0.1:8042](http://127.0.0.1:8042).

## Sitio Astro

El repo incluye una landing pública en Astro bajo `apps/site`.

```bash
cd /Users/matiasrios/Documents/GitHub/lobo-builder/apps/site
npm install
npm run dev
```

Checks útiles:

```bash
npm run check
npm run build
```

Deploy recomendado en Vercel:

- framework: `Astro`
- root directory: `apps/site`
- build command: `npm run build`
- output directory: `dist`

## Variables útiles

- `AUTONOMY_DATABASE_URL`
  - local: `sqlite+pysqlite:///.../autonomy-hub/var/autonomy-hub.db`
  - remoto: `Postgres` cuando se quiera persistencia compartida
- `AUTONOMY_WORKSPACE_ROOT`
  - root para autodiscovery de repos locales
- `AUTONOMY_AUTO_DISCOVER_LOCAL`
  - `true` por defecto
- `AUTONOMY_DISCOVER_MAX_DEPTH`
  - profundidad máxima de scan local
- `AUTONOMY_DISCORD_WEBHOOK_URL`
  - webhook para notificar runs `completed`, `failed` o `interrupted`

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

## Layout del repo

- `src/autonomy_hub/main.py`
  - app factory y dashboard
- `src/autonomy_hub/services/planner.py`
  - misión -> spec + execution graph
- `src/autonomy_hub/services/graph.py`
  - graph central + autodiscovery local
- `src/autonomy_hub/services/missions.py`
  - persistencia y vistas operativas
- `src/autonomy_hub/services/runner.py`
  - ejecución de runs y control del runtime
- `config/`
  - perfiles, policies, intake greenfield y template catalog
- `docs/architecture.md`
  - decisiones de arquitectura
- `docs/`
  - contratos, planes y referencias del sistema

## Para seguir

- [Repositorio](https://github.com/MatiasJRB/lobo-builder)
- [Arquitectura](https://github.com/MatiasJRB/lobo-builder/blob/main/docs/architecture.md)
- [Quick start](https://github.com/MatiasJRB/lobo-builder#quick-start)
- [Landing pública](https://lobo-builder.vercel.app)
