# Misiones Multi-Repo v1 sobre el runtime actual

## Resumen
- Objetivo: permitir que una sola misión ejecute trabajo real sobre varios repos, sin romper el camino single-repo que hoy ya funciona.
- Decisiones cerradas para esta v1:
  - mantener worktrees
  - ejecución `safe parallel`: un task activo por repo, varios repos en paralelo si sus dependencias ya están resueltas
  - gate global: ningún `release` ni `deploy` corre hasta que todos los repos pasen verify
  - soporte de overrides por repo para `merge_target` y `deploy_targets`
- Estrategia de compatibilidad:
  - single-repo sigue siendo el fast path actual
  - endpoints actuales se mantienen
  - los cambios son aditivos en tipos, DB y dashboard

## Cambios de implementación
- **Contexto multi-repo**: reemplazar el uso operativo de `ResolvedProjectContext` único por un `ResolvedMissionContext` con `repositories: dict[str, ResolvedProjectContext]`. Mantener `resolve()` single-repo como helper legacy y agregar `resolve_mission()` para multi-repo.
- **Overrides por repo**: agregar `MissionRepositoryOverride` y `repository_overrides: dict[str, MissionRepositoryOverride]` en `MissionCreateRequest` y `MissionSpec`. Regla de precedencia por repo: override de misión > manifest del hub > `context/project.json` del repo.
- **Persistencia de runtime**: mantener `MissionRunRecord` como supervisor run y agregar tabla hija `MissionRepoRunRecord` con `mission_run_id`, `repository`, `status`, `current_task_key`, `branch_name`, `worktree_path`, `merge_target`, `deploy_targets`, `last_heartbeat_at`, `last_error`, timestamps. Agregar `repository` opcional a `CommandExecutionRecord` para filtrar logs por repo.
- **Locks de repos**: al iniciar una misión multi-repo, el runner debe reclamar locks sobre todos los repos linkeados. Si cualquier repo ya está ocupado por otra misión activa, `POST /run` devuelve `409` con la lista de repos en conflicto. El lock se libera al completar, fallar o interrumpir.
- **Worktrees y branches por repo**: crear un worktree y branch por repo, por ejemplo `codex/mission-<id>/<repo-slug>` y `var/runs/<mission_id>/worktrees/<repo>`. Reusar worktrees existentes en `resume`.
- **DAG de tareas**: mantener el modelo actual de `ExecutionTaskSpec`, pero materializar tareas por repo más una capa global:
  - globales seriales: `context-map`, `product-spec`, `architect-plan`
  - repo-scoped paralelizables: `implement-<repo>` y `verify-<repo>`
  - gate global serial: `verify-global`
  - cierre por repo, después del gate: `release-<repo>` y `deploy-<repo>` cuando aplique
- **Scheduler del runner**: un supervisor de misión promueve tasks según `depends_on`; global tasks corren en el hilo supervisor; repo tasks corren con workers por repo. Regla: máximo un task activo por repo. Cap de concurrencia por default: `min(3, cantidad_de_repos)`.
- **Release/deploy multi-repo**: aunque implementación y verify por repo pueden correr en paralelo, `release` y `deploy` deben ejecutarse en orden determinístico por repo después de `verify-global`, para simplificar trazabilidad y recuperación. Si un repo falla en release/deploy, la misión completa falla y los repos restantes no cierran.
- **Budget y controles existentes**: los `execution_controls` actuales siguen aplicando a toda la misión. Semántica:
  - `verify_enabled=false` salta `verify-<repo>` y `verify-global`
  - `release_enabled=false` salta todos los `release-<repo>` y `deploy-<repo>`
  - `deploy_enabled=false` permite `release-<repo>` y salta `deploy-<repo>`
  - `max_runtime_hours` sigue siendo acumulado a nivel misión, sumando el tiempo del supervisor run y sus repo workers
- **Recovery y stale runs**: `resume` debe rehidratar el supervisor run y todos los `MissionRepoRunRecord`. Si un worker quedó stale, sólo ese repo vuelve a `ready`; no se descarta el progreso de otros repos ya completados. El gate global debe recalcularse desde estados persistidos, no desde memoria.
- **Dashboard y misión enfocada**: mantener el panel actual, pero cuando la misión sea multi-repo mostrar:
  - una grilla de repo cards con `repo`, `owner activo`, `task actual`, `branch`, `worktree`, `status`
  - snapshots de dirty files por repo
  - tasks agrupadas por repo y estado
  - un bloque de “gate global” que deje claro cuándo falta verify cruzado antes de release
  Single-repo sigue usando la vista actual.
- **Graph**: no hace falta un nuevo tipo de nodo permanente. La misión ya enlaza varios repos; para v1 alcanza con enriquecer metadata y la vista enfocada. Los repo runs son runtime state, no graph state.

## APIs, tipos e interfaces
- **Nuevos tipos**:
  - `MissionRepositoryOverride`
  - `ResolvedMissionContext`
  - `MissionRepoRunView`
  - `MissionRepoSnapshotView`
- **Tipos extendidos de forma aditiva**:
  - `MissionCreateRequest.repository_overrides?`
  - `MissionSpec.repository_overrides`
  - `MissionView.repo_runs`
  - `MissionView.repo_snapshots`
  - `MissionRunView` sigue existiendo como supervisor run
  - `CommandExecutionView.repository?`
- **Endpoints**:
  - mantener `POST /api/missions`, `POST /run`, `POST /resume`, `POST /interrupt`, `GET /api/missions/{id}`, `GET /api/dashboard`
  - agregar sólo campos nuevos en respuesta; no romper shape actual
  - `POST /run` y `POST /resume` deben devolver también `repo_runs` cuando la misión sea multi-repo
- **Compatibilidad**:
  - misiones legacy sin `repository_overrides` siguen usando el comportamiento actual
  - single-repo no crea `MissionRepoRunRecord` extra o, si los crea, deben ser transparentes para la API actual
  - `release` legacy de single-repo no cambia de semantics

## Plan de pruebas
- **Resolver/contexto**:
  - misión con 3 repos resuelve contextos independientes
  - overrides por repo ganan sobre manifest y `context/project.json`
  - instrucciones repo-locales (`AGENTS`/`skills`) se mantienen separadas por repo
- **Planner**:
  - crea `implement-<repo>` y `verify-<repo>` por cada repo
  - crea `verify-global` dependiente de todos los verify por repo
  - crea `release-<repo>` y `deploy-<repo>` en orden correcto
  - single-repo sigue generando el DAG actual
- **Runner**:
  - repos independientes implementan en paralelo
  - un repo no corre dos tasks a la vez
  - gate global bloquea release si un repo falla verify
  - release/deploy avanzan repo por repo en orden determinístico
  - `interrupt` y `resume` preservan progreso parcial por repo
  - lock de repo devuelve `409` si otra misión activa ya lo usa
  - límite de horas interrumpe la misión multi-repo sin perder tasks ya completados
- **API/dashboard**:
  - misión multi-repo expone `repo_runs` y snapshots por repo
  - la vista enfocada no colapsa ni mezcla diffs entre repos
  - single-repo sigue renderizando sin cambios regresivos
- **Compatibilidad**:
  - suite actual single-repo debe seguir verde
  - tests explícitos para misiones legacy y misiones nuevas multi-repo

## Supuestos y defaults
- Esta v1 preserva worktrees; no mezcla multi-repo con cambio de sustrato operativo.
- La paralelización es sólo para tasks repo-scoped; tasks globales siguen seriales.
- El cierre final usa gate global y después release/deploy secuencial por repo.
- Cap de paralelismo por default: 3 repos activos como máximo.
- Si una misión multi-repo requiere políticas o despliegues muy distintos por repo, se usa `repository_overrides`; si no, los defaults globales siguen siendo válidos.
