# Work Cycles sobre el runtime adaptativo actual

> Nota de baseline:
> este plan parte de la versión vigente de Lobo Builder descrita en `docs/architecture.md`
> y `docs/plans/adaptive-planner-gpt54.md`. Hoy el runtime operativo sigue modelado
> con `Mission` + `Execution Graph` + `execution_tasks` + `PlanningContext` +
> expansión `planner-expand-wave-n`. Este documento ya no propone reemplazar ese
> contrato, sino agregar `work_cycles` como una capa superior de agrupación, cierre
> y replan.

## Resumen

- El primitivo ejecutable sigue siendo `execution_tasks`.
- `work_cycles` pasa a ser un contrato aditivo para:
  - agrupar bootstrap y olas de implementación en unidades cerrables;
  - dar observabilidad de ciclo, presupuesto y scope residual;
  - permitir que el `Planner` abra y cierre ciclos sin romper el scheduler actual.
- El bootstrap de misión sigue siendo global y queda fuera de los ciclos:
  - `project-shell?`
  - `context-map`
  - `product-spec`
  - `architect-plan`
- Cada `work_cycle` agrupa una expansión y su cierre:
  - `planner-expand-wave-n`
  - `implement-*`
  - `verify-cycle-n`
  - `release-cycle-n`
  - `deploy-cycle-n?`
  - `cycle-close-n`
- La tesis cambia de "migrar desde `execution_tasks` a `work_cycles`" a
  "superponer `work_cycles` sobre el DAG actual para darle estructura de continuidad".

## Estado actual que este plan preserva

- `MissionView.execution_tasks` sigue siendo el contrato canónico del DAG operativo.
- `MissionRunView.current_task_key` y `CommandExecutionView.task_key` siguen siendo
  la forma principal de ubicar progreso de runtime.
- El `Planner` hoy:
  - crea bootstrap global;
  - materializa `planner-expand-wave-1` cuando `PlanningContext.planning_mode == "adaptive"`;
  - genera `DecompositionProposal` y `WorkUnit`;
  - expande `implement-*` a partir de esa propuesta.
- El `Runner` hoy ejecuta tareas por `depends_on`, persiste artifacts y actualiza el
  `execution_graph` sin noción nativa de ciclo.
- El dashboard hoy renderiza board y grafo a nivel task; esa vista se conserva.

## Cambios de implementación propuestos

### Modelado de `work_cycles`

- Introducir `work_cycles` como estructura persistida y observable, sin reemplazar
  `execution_tasks`.
- `bootstrap` queda explícitamente fuera de `work_cycles`; representa preparación
  global de la misión, no un ciclo cerrable.
- Cada `work_cycle` representa una iteración completa de entrega sobre el DAG actual:
  - abre con `planner-expand-wave-n`;
  - ejecuta los `implement-*` que correspondan a ese corte;
  - corre gates de validación y release del ciclo;
  - termina con `cycle-close-n`, ownership del `Planner`.
- `cycle-close-n` es la pieza que decide una de dos salidas:
  - `mission_complete=true`, con cierre terminal de misión;
  - `mission_complete=false`, con `remaining_scope_summary` y materialización de
    `planner-expand-wave-(n+1)`.

### Planner-led flow

- Se mantiene la regla central del sistema: sólo el `Planner` puede abrir, cerrar y
  replanificar ciclos.
- `architect-plan` sigue siendo bootstrap global. No pasa a ser un stage interno de
  cada ciclo.
- El `Planner` usa como insumos reales del runtime actual:
  - `PlanningContext`
  - `DecompositionProposal`
  - `WorkUnit`
  - artifact `planning_context`
  - artifact `decomposition_proposal`
  - artifact `execution_graph`
- La expansión sigue siendo lazy:
  - en misiones fast-path puede existir sólo `cycle-1`;
  - en misiones adaptativas el siguiente ciclo nace recién desde `cycle-close-n`.

### Runner y scheduler

- El scheduler actual por `execution_tasks` y `depends_on` se mantiene.
- `work_cycles` no cambia la unidad ejecutable del runner; agrega agrupación y reglas
  de cierre encima del DAG.
- `MissionRunView.current_task_key` sigue apuntando a una task concreta, no a un ciclo.
- La integración propuesta es:
  - `planner-expand-wave-n` sigue materializando `implement-*` concretos;
  - `verify-cycle-n`, `release-cycle-n` y `deploy-cycle-n?` se modelan como tasks
    reales del DAG y quedan asociadas a `cycle_key`;
  - `cycle-close-n` evalúa artifacts, estado de verify/release y residual scope;
  - si la misión continúa, el runner encola la siguiente expansión sin resetear el
    runtime base.

### Policy gates por ciclo

- `safe`:
  - cierra cada ciclo sin merge ni deploy;
  - el cierre deja artifacts y residual scope asociados al ciclo.
- `delivery` y `prod`:
  - mantienen sus gates actuales;
  - esos gates pasan a registrarse por ciclo en lugar de quedar implícitos sólo a
    nivel misión.
- `autopilot`:
  - puede mergear al `merge_target` en cada ciclo aceptado;
  - sólo deploya cuando `cycle-close-n` marque el ciclo terminal de la misión.

### Dashboard y observabilidad

- Se conserva la vista task-level actual como fuente principal de progreso.
- Se agrega agrupación visual por:
  - `bootstrap`
  - `cycle-1`
  - `cycle-2`
  - `cycle-n`
- La UI propuesta debe mostrar:
  - `active_cycle_key`
  - objetivo o resumen del ciclo
  - scope residual del último cierre
  - estado del gate del ciclo
- El board actual no se reemplaza; se enriquece con headers, filtros o badges de
  ciclo sobre `execution_tasks`.

## APIs, contratos públicos y persistencia

### Contratos canónicos que se preservan

- `MissionView.execution_tasks`
- `MissionRunView.current_task_key`
- `CommandExecutionView.task_key`

### Extensiones aditivas propuestas

- `MissionView.work_cycles?`
- `MissionView.active_cycle_key?`
- `ExecutionTaskSpec.cycle_key?`
- `MissionRunView.current_cycle_key?`
- `CommandExecutionView.cycle_key?`
- `ArtifactPayload.metadata.cycle_key?`

### Regla de compatibilidad

- Ninguna API existente deja de exponer `execution_tasks`.
- Ningún endpoint actual se rompe por introducir `work_cycles`.
- La lectura principal del runtime puede seguir siendo task-level aunque exista
  metadata adicional de ciclo.

### Persistencia y migración

- La migración debe ser aditiva, no destructiva.
- Agregar estructura persistida para `work_cycles`.
- Agregar `cycle_key` en:
  - tasks
  - runs
  - commands
  - artifacts
- Backfill de misiones existentes:
  - `bootstrap`: `project-shell?`, `context-map`, `product-spec`, `architect-plan`
  - `cycle-1`: `planner-expand-wave-*`, `implement-*`, `verify`, `release`, `deploy`
- El documento elimina cualquier premisa de migración directa que quite
  `execution_tasks` del contrato.

## Escenarios y casos de prueba

- Misión fast-path single-repo:
  - sigue funcionando sólo con `execution_tasks`;
  - `cycle-1` agrupa verify, release y deploy sin cambiar el scheduler base.
- Misión adaptativa:
  - `planner-expand-wave-1` abre `cycle-1`;
  - `cycle-close-1` decide si se materializa `planner-expand-wave-2`.
- Misión greenfield:
  - `project-shell` permanece en bootstrap;
  - el ciclo de implementación empieza después del bootstrap global.
- Misión `autopilot`:
  - merge por ciclo aceptado;
  - deploy sólo cuando el cierre del ciclo declare misión terminada.
- Compatibilidad API/dashboard:
  - el documento debe seguir siendo consistente con `MissionView.execution_tasks`,
    `MissionRunView.current_task_key` y `CommandExecutionView.task_key`;
  - cualquier campo de ciclo nuevo debe quedar marcado como propuesta futura y
    extensión aditiva.

## Supuestos y defaults

- `work_cycles` es una capa aditiva sobre el runtime actual.
- El bootstrap sigue fuera de los ciclos.
- El `Planner` conserva control total del DAG y de la apertura/cierre de ciclos.
- El alcance de este documento es sólo este plan; no reescribe el resto de `docs/`.
- Cuando el texto use nombres como `verify-cycle-n`, `release-cycle-n`,
  `deploy-cycle-n` o `cycle-close-n`, debe leerse como propuesta de evolución
  compatible con el scheduler actual, no como descripción del runtime ya implementado.
