export type CardItem = {
  title: string;
  description: string;
  items?: string[];
  footer?: string;
};

const repoBase = "https://github.com/MatiasJRB/lobo-builder";

export const siteContent = {
  metadata: {
    title: "Lobo Builder",
    description:
      "Planner-led autonomy hub para trabajo autónomo multi-repo, con foco local-first, misiones acotadas y ejecución verificable.",
  },
  hero: {
    eyebrow: "Planner-led autonomy hub",
    title: "Lobo Builder coordina trabajo autónomo multi-repo sin convertirlo en una caja negra.",
    summary:
      "Es una capa de control local-first para misiones de software: recibe un brief, arma un Mission Spec, construye un Execution Graph y delega la ejecución a perfiles fijos con ownership acotado.",
    supporting:
      "Hoy el runtime técnico sigue viviendo como autonomy-hub dentro del backend FastAPI, pero esta página presenta el proyecto con una identidad pública más clara y orientada a evaluación.",
    primaryCta: {
      label: "Ver repositorio",
      href: repoBase,
    },
    secondaryCta: {
      label: "Cómo funciona",
      href: "#como-funciona",
    },
  },
  stats: [
    {
      value: "9",
      label: "tipos de nodos",
      description: "Producto, proyecto, repositorio, entorno, documento, misión, artefacto, perfil y policy.",
    },
    {
      value: "4",
      label: "políticas cerradas",
      description: "safe, delivery, prod y autopilot para gobernar hasta dónde puede llegar la ejecución.",
    },
    {
      value: "6",
      label: "adapters v1",
      description: "Filesystem local, Git, GitHub, Railway, Vercel y Firebase App Distribution ya modelados.",
    },
  ],
  workflow: [
    {
      title: "1. Intake de misión",
      description:
        "El trabajo entra como una misión, no como un ticket aislado ni como un repo suelto. El planner clasifica el brief como fix, feature, refactor o greenfield.",
      footer: "El objetivo es empezar con contexto de negocio y no sólo con una tarea técnica.",
    },
    {
      title: "2. Spec y Execution Graph",
      description:
        "Antes de editar código, el sistema genera un Mission Spec y un Execution Graph. Esa dupla define alcance, dependencias, orden de ejecución y ownership por perfil.",
      footer: "La misión queda lista para correr con una estructura explícita y persistida.",
    },
    {
      title: "3. Especialistas con ownership acotado",
      description:
        "El planner mantiene control global y los agentes especialistas reciben superficies concretas: arquitectura, backend, frontend, data/infra, verificación y release.",
      footer: "No se inventan roles ad hoc; se instancian perfiles fijos con límites claros.",
    },
    {
      title: "4. Runner local persistido",
      description:
        "La ejecución corre en modo local-first, con worktree, branch, logs, heartbeat, comandos y errores persistidos. El runtime de agentes actual usa codex exec.",
      footer: "SQLite es el backing store por defecto y Postgres remoto queda como soporte opcional.",
    },
    {
      title: "5. Verificación y release gobernados por policy",
      description:
        "Cada policy expande permisos concretos para push, merge, deploy y migraciones. El release sólo ocurre si la misión lo habilita y pasa por la verificación previa.",
      footer: "En autopilot ya existe un closed loop inicial con verify, merge local y deploy móvil declarado.",
    },
  ] satisfies CardItem[],
  capabilities: [
    {
      title: "Coordinar trabajo más allá de un solo repo",
      description:
        "La unidad operativa es la misión. Eso permite agrupar repositorios, productos, documentos y entornos bajo un mismo objetivo verificable.",
      items: [
        "linked_repositories y linked_products en la creación de la misión",
        "Grafo central con nodos y relaciones persistidas",
        "Autodiscovery local del workspace para enriquecer contexto",
      ],
    },
    {
      title: "Mantener observabilidad operativa",
      description:
        "El dashboard actual muestra cola de misiones, estado de worktrees, comandos recientes y vecindad de contexto para la misión enfocada.",
      items: [
        "GET /api/dashboard",
        "GET /api/missions y runs por misión",
        "GET /api/graph para snapshot del grafo",
      ],
    },
    {
      title: "Ejecutar un DAG real de tareas",
      description:
        "El runner persiste estados, recupera runs stale, ejecuta tareas por secuencia y conserva el detalle operativo necesario para reanudar o interrumpir.",
      items: [
        "run, resume e interrupt como acciones explícitas",
        "Persistencia de logs y artefactos por misión",
        "Verify y release resueltos con comandos determinísticos",
      ],
    },
    {
      title: "Aplicar gobierno sin ambigüedad",
      description:
        "Las policies no son etiquetas decorativas. Definen capacidad de escritura, push, merge, deploy y migración a nivel bajo.",
      items: [
        "safe para ciclos controlados",
        "delivery para entrega con más permisos",
        "prod y autopilot para escenarios más sensibles",
      ],
    },
  ] satisfies CardItem[],
  systemHighlights: {
    title: "Lo que hoy ya está operativo",
    description:
      "La base ya dejó de ser sólo un planner: materializa el modelo central de misión, un runner local real y el slice inicial de autopilot.",
    items: [
      "Mission Spec y Execution Graph generados al crear la misión",
      "SQLite local por default con opción de Postgres en Railway",
      "Integraciones modeladas para GitHub, Railway, Vercel y Firebase App Distribution",
    ],
  },
  nextSteps: [
    {
      title: "Paralelismo real multi-repo",
      description:
        "Expandir la ejecución desde secuencias controladas hacia varias superficies en paralelo sin perder ownership ni orden de dependencia.",
      footer: "Es la siguiente frontera natural del modelo mission-centric.",
    },
    {
      title: "Runners remotos optativos",
      description:
        "Mover parte de la ejecución a infraestructura remota cuando convenga, manteniendo el modo local como default y no como excepción.",
      footer: "Railway queda como soporte, no como arquitectura cloud-first.",
    },
    {
      title: "Migraciones formales de base de datos",
      description:
        "Pasar de la persistencia actual a un flujo explícito y versionado de migraciones para endurecer el control del estado operativo.",
      footer: "Esto habilita crecimiento más seguro de contratos y vistas.",
    },
    {
      title: "Más targets de release y despliegue",
      description:
        "Ampliar el rango de destinos además del loop actual de Android Firebase App Distribution y los adapters ya modelados.",
      footer: "La idea es sumar superficie sin volver el sistema una cola genérica de cloud jobs.",
    },
  ] satisfies CardItem[],
  links: [
    {
      title: "Repositorio",
      description: "Código, historial y contexto general del proyecto en GitHub.",
      href: repoBase,
      label: "Abrir GitHub",
    },
    {
      title: "README",
      description: "Quick start, variables útiles, API principal y layout actual del repo.",
      href: `${repoBase}#readme`,
      label: "Ver README",
    },
    {
      title: "Arquitectura",
      description: "Modelo de misión, grafo, policies y forma del runtime actual.",
      href: `${repoBase}/blob/main/docs/architecture.md`,
      label: "Leer arquitectura",
    },
    {
      title: "Auditoría de spec-forge",
      description: "Qué piezas del flujo greenfield ya se absorbieron y qué quedó diferido.",
      href: `${repoBase}/blob/main/docs/spec-forge-audit.md`,
      label: "Ver auditoría",
    },
  ],
  runtimePointers: [
    {
      title: "Dashboard operativo actual",
      description:
        "La UI operativa sigue en el backend FastAPI. Esta landing no la reemplaza; la complementa.",
      value: "autonomy-hub -> http://127.0.0.1:8042/",
    },
    {
      title: "API activa",
      description:
        "Los endpoints existentes siguen siendo la interfaz del control plane para misiones, graph y estado.",
      value: "/api/dashboard · /api/missions · /api/graph",
    },
  ],
  closing: {
    eyebrow: "Próximo paso",
    title: "Evaluar el concepto, correr el hub local y usar esta base como frente público del proyecto.",
    description:
      "La combinación actual es intencional: Astro para explicar y posicionar Lobo Builder, FastAPI para operar el runtime real de autonomy-hub sin tocar su contrato existente.",
  },
};
