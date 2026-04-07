# Ciclos de Trabajo Cerrables en lugar de Pipeline Secuencial

## Resumen

- Hacer que el primitivo principal de ejecución pase de `execution_tasks` planificadas de punta a punta a `work_cycles` materializados de forma incremental.
- Mantener un bootstrap de misión único (`context-map`, `product-spec`, arquitectura global) y mover toda la generación de código a ciclos acotados.
- Aceptar un número opcional de ciclos por misión; si no viene, el sistema sigue creando ciclos hasta que el cierre de ciclo marque la misión como completa.
- En `autopilot`, cada ciclo aceptado mergea a `merge_target`; el deploy corre una sola vez, al final del ciclo terminal.

## APIs, Contratos y Tipos Públicos

- Reemplazar `MissionView.execution_tasks` por:
  - `bootstrap_steps`: pasos globales de misión.
  - `work_cycles`: lista de ciclos realizados o activos.
- Agregar a `MissionCreateRequest` y `MissionSpec`:
  - `target_cycle_count: Optional[int]`
  - `cycle_budget_mode: "bounded" | "until_complete"`
- Introducir tipos nuevos:
  - `WorkCycleSpec`
  - `CycleStageSpec`
  - `CycleReviewDecision`
  - `CycleStatus`
- Cambiar vistas de runtime para dejar de usar una sola task activa:
  - `MissionRunView` debe exponer `cycle_key` y `stage_key`.
  - `CommandExecutionView` debe exponer `cycle_key` y `stage_key` en lugar de sólo `task_key`.
- Agregar un estado de misión terminal no-exitoso para presupuesto agotado:
  - `awaiting_replan` cuando `target_cycle_count` se consume y todavía queda scope.

## Cambios de Implementación

- Bootstrap de misión:
  - Mantener `context-map`, `product-spec` y una arquitectura global única como pasos previos a cualquier ciclo.
  - El artifact `execution_graph` sigue existiendo, pero pasa a representar `bootstrap + cycles + stages`, no una lista plana de tasks.
- Planeamiento de ciclos:
  - En creación de misión sólo se materializa `cycle-1`.
  - Cada ciclo tiene stages fijos: `cycle-plan`, `implement-*`, `verify`, `cycle-review`, `release`, `deploy?`.
  - `cycle-plan` usa el perfil `architect` para definir un slice acotado y generar sólo los stages de implementación de ese ciclo.
  - `implement-*` puede seguir teniendo varios stages hermanos por repo/surface, pero ya no se preplanifican todos los cortes de la misión completa.
  - `cycle-review` produce una decisión estructurada con `mission_complete`, `remaining_scope_summary`, `next_cycle_goal` y `next_cycle_repo_slices`.
- Progresión y presupuesto:
  - Si `target_cycle_count` existe, el runner puede crear ciclos nuevos sólo hasta alcanzar ese límite.
  - Si no existe, el runner sigue creando `cycle-(n+1)` mientras `cycle-review` diga que la misión no terminó.
  - Si se agota el presupuesto explícito y queda trabajo, la misión pasa a `awaiting_replan` y persiste el residual scope como artifact.
- Runner y persistencia:
  - Agregar tablas o records para `work_cycles` y `cycle_stages`.
  - Vincular runs, commands y artifacts a `cycle_key` y `stage_key`.
  - Usar branch y worktree frescos por ciclo, siempre recreados desde el `merge_target` ya actualizado.
  - El loop del runner opera por ciclo: ejecuta stages del ciclo actual, corre release, decide si crear el siguiente ciclo, y continúa automáticamente hasta completar misión o agotar presupuesto.
  - `interrupt` pausa el stage actual y deja el ciclo reanudable; `resume` retoma el ciclo activo o arranca el próximo ciclo ya materializado.
- Release y deploy:
  - `safe`: sigue sin merge ni deploy, pero ahora el release artifact queda asociado al ciclo.
  - `delivery` y `prod`: mantienen sus gates actuales, aplicados por ciclo.
  - `autopilot`: merge en cada ciclo aceptado; deploy sólo cuando `cycle-review` marque el ciclo como terminal.
- Dashboard:
  - Reemplazar el tablero de tasks por una vista de `bootstrap_steps` + historial de ciclos.
  - Mostrar `ciclo activo`, `objetivo del ciclo`, `stage activo`, `budget de ciclos` y `scope residual` si existe.
  - El grafo runtime debe resaltar el ciclo activo y sus stages, no una cadena lineal única.
- Migración de datos:
  - Backfill de misiones existentes a:
    - `bootstrap_steps`: `context-map`, `product-spec`, `architect-plan`.
    - `work_cycles[0]`: todos los `implement-*`, `verify`, `release` y `deploy` existentes.
  - Preservar status, artifacts, commands y timestamps ya persistidos.
  - Misiones legacy sin presupuesto explícito migran con `cycle_budget_mode="until_complete"`.

## Casos de Prueba

- Planner:
  - misión con `target_cycle_count=3` crea bootstrap + `cycle-1`, no una cadena completa de implementación.
  - misión sin `target_cycle_count` queda en modo `until_complete`.
  - `cycle-review` genera el siguiente ciclo con el objetivo y slices declarados.
- Runner:
  - progresión automática `cycle-1 -> cycle-2 -> ...` mientras no se complete la misión.
  - `autopilot` mergea en cada ciclo y deploya sólo en el ciclo final.
  - agotamiento de presupuesto con trabajo restante termina en `awaiting_replan`.
  - `interrupt` y `resume` funcionan dentro de un stage y entre ciclos.
- API y dashboard:
  - `POST /api/missions` devuelve `bootstrap_steps` y `work_cycles`.
  - `/api/dashboard` muestra ciclo y stage activos.
  - `/api/missions/{id}/runs` refleja `cycle_key` y `stage_key`.
- Migración:
  - una misión legacy con `execution_tasks` se convierte en bootstrap + `cycle-1` sin perder artifacts ni logs.

## Supuestos y Defaults

- La migración es directa: no se mantiene compatibilidad transitoria con `execution_tasks`.
- El runner sigue siendo single-worker en este slice; el cambio es de unidad de planeamiento y cierre, no de paralelismo real del runtime.
- El primer ciclo de greenfield toma `first_cycle_goal` como objetivo inicial cuando esté disponible.
- La creación de ciclos futuros es lazy: sólo se materializan cuando el ciclo previo cierra y corresponde seguir.
- Si un ciclo mergeó correctamente, el siguiente siempre nace desde la rama principal ya integrada.
