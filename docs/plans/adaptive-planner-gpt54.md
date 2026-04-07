# Planner Adaptativo Por Olas y Model-Aware

## Resumen

- Pasar del planner actual, que corta por heurísticas fijas de `repo/surface`, a un planner de `rolling wave`: primero arma el DAG macro y después expande automáticamente la ola de implementación cuando ya tiene contexto técnico real.
- Mantener la regla central del sistema: el `Planner` sigue siendo el único dueño del grafo y de la cola. El `Architect` propone estructura y cortes, pero no muta la cola directamente.
- Hacer que el sizing de tareas sea explícitamente "balanced for GPT-5.4": tareas lo bastante grandes para aprovechar el modelo, pero no tan grandes como para mezclar demasiadas decisiones, superficies o dependencias.

## Cambios De Implementación

- Introducir un `PlanningContext` interno que el planner construya antes de cortar tareas. Debe leer `linked_repositories`, `linked_documents` y paths locales como `../app`, inspeccionando sólo señales estructurales: árbol de rutas, manifests, `context/project.json`, docs de producto, entidades, integraciones, auth y deploy hints.
- Tratar `linked_documents` como entradas inspeccionables cuando sean archivos o directorios locales. Hoy sólo se pasan como strings al prompt; con este cambio el planner podrá entender de verdad "esta app definida en ../app".
- Extender el catálogo de perfiles para que el planner conozca capacidad real por agente: `owned_surfaces`, `preferred_task_size`, `max_repo_scope`, `can_parallelize`, `model`, `reasoning_effort`. La fuente principal debe seguir siendo `config/agent_profiles/catalog.yaml`, no lógica hardcodeada.
- Conectar el runtime de `codex exec` con esa configuración para que la selección de modelo/esfuerzo sea efectiva. El planner no debe asumir GPT-5.4 si después el runner no lo materializa.
- Reemplazar el corte fijo de implementación por un pipeline de 2 fases:
  - Fase 1: `context-map`, `product-spec`, `architect-discovery`, `planner-expand-wave-1`, `verify`, `release`, `deploy?`
  - Fase 2: después del `architect-discovery`, el planner consume el contexto + propuesta técnica y genera `N` tasks implementables con dependencias explícitas.
- Cambiar la salida del arquitecto para que produzca dos artefactos:
  - `decision_log` humano
  - `decomposition_proposal` estructurado con workstreams, dependencias, riesgos, owners sugeridos y cortes recomendados
- Agregar una operación de replan interno en el planner que:
  - inserte tareas nuevas
  - actualice `verify.depends_on`
  - preserve tareas ya completadas
  - rechace expansiones que rompan policy o introduzcan owners no soportados
- Definir `WorkUnit` como unidad previa a task. El planner primero descompone la misión en work units y luego los empaqueta en tareas según budget de perfil/modelo.
- Usar reglas de split/merge explícitas para el budget "balanced":
  - una task = un owner profile, una repo/surface primaria, un outcome cohesivo
  - split obligatorio si cruza repo boundary, mezcla schema/auth/integration con UI, o requiere decisiones de arquitectura que exceden un sólo resultado verificable
  - merge obligatorio si el work unit aislado no justifica una ejecución separada y sólo añade overhead
- Reglas de corte por perfil:
  - `frontend-implementer`: una flow family o component family por task; no mezclar sweep visual amplio con cambios de API
  - `backend-implementer`: una capacidad o vertical backend por task; separar migraciones no triviales del resto si condicionan otras tareas
  - `data-infra-implementer`: una topología o capability operacional por task
- Para misiones simples, mantener fast path: el planner puede seguir emitiendo tareas implementables upfront sin pasar por expansión dinámica si el contexto ya es suficientemente pequeño y claro.

## Interfaces y Contratos

- Extender `ExecutionTaskSpec` con:
  - `wave: int`
  - `planning_source: str`
  - `size_hint: str`
  - `work_unit_ids: list[str]`
- Agregar modelos internos:
  - `PlanningContext`
  - `WorkUnit`
  - `DecompositionProposal`
- Agregar artefactos versionados/persistidos:
  - `planning_context`
  - `decomposition_proposal`
- Mantener `MissionCreateRequest` sin romper compatibilidad. El cambio es semántico: `linked_documents` puede incluir archivos/directorios locales que el planner inspecciona durante planning.
- Mantener el set fijo de agent profiles. El paralelismo sigue viniendo de múltiples instancias de roles conocidos, no de inventar roles nuevos.

## Casos De Prueba

- Greenfield definido por un path local tipo `../app`: el planner inspecciona esa app, detecta superficies reales y genera varias tasks balanceadas en lugar de 1-3 tareas genéricas.
- Misión simple de bugfix en un repo: el planner no sobre-fragmenta y deja una sola task implementable.
- Misión fullstack con auth + schema + API + UI: el planner separa foundation/data/auth de slices dependientes y deja paralelismo sólo donde realmente existe.
- Tras completar `architect-discovery`, el planner expande la ola 1 y `verify` queda dependiendo de las nuevas tareas, no del placeholder original.
- El planner nunca asigna una task a un agent profile no disponible en catálogo.
- El runner ejecuta el modelo/esfuerzo configurado para cada perfil; el planner y el runtime quedan alineados.
- Si el contexto es pobre o ambiguo, el planner cae al modo conservador y no inventa un DAG detallado sin evidencia suficiente.

## Supuestos y Defaults

- Default de producto: `rolling wave`.
- Default de sizing: `balanced` para GPT-5.4.
- El planner sigue siendo determinista en el control del DAG; las salidas LLM son propuestas, no autoridad final.
- La heurística de budget debe optimizar coherencia y throughput juntos, no máximo paralelismo.
- El foco inicial es mejorar planning para greenfield y misiones complejas; no hace falta reescribir primero todo el runtime de ejecución.
