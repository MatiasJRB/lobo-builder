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
      "Lobo Builder es un control plane planner-led y local-first para misiones de software, con Mission Spec, Execution Graph, policies y runtime verificable.",
  },
  hero: {
    eyebrow: "Planner-led. Mission-centric. Local-first.",
    title: "Lobo Builder es un control plane para planear, ejecutar y gobernar trabajo autónomo de software.",
    summary:
      "Recibe un brief, lo convierte en una misión con Mission Spec y Execution Graph, asigna ownership a perfiles fijos y ejecuta el trabajo con policies, trazabilidad y control explícito.",
    supporting:
      "No intenta ser otro gestor de tickets ni una caja negra de agentes. Su foco es dar una forma estable de modelar misiones, correrlas sobre repositorios reales y dejar evidencia suficiente para entender qué se decidió, qué se ejecutó y bajo qué permisos.",
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
      label: "perfiles fijos",
      description: "Planner, context mapper, product/spec, architect, implementers, verifier y release/deploy trabajan con ownership acotado.",
    },
    {
      value: "4",
      label: "políticas cerradas",
      description: "safe, delivery, prod y autopilot definen permisos reales para escritura, push, merge, deploy y migraciones.",
    },
    {
      value: "6",
      label: "adapters v1",
      description: "Filesystem local, Git, GitHub, Railway, Vercel y Firebase App Distribution forman parte de la capa de integración.",
    },
  ],
  workflow: [
    {
      title: "1. La misión es la unidad de trabajo",
      description:
        "Lobo Builder trabaja sobre misiones, no sobre prompts sueltos ni sobre un repositorio aislado. Cada misión tiene brief, outcome, policy y referencias a productos, repositorios y documentos.",
      footer: "Eso permite tratar el trabajo como una unidad operable y no sólo como una lista de tareas.",
    },
    {
      title: "2. El planeamiento queda persistido",
      description:
        "Antes de ejecutar cambios, el sistema escribe un Mission Spec con done definition, riesgos y supuestos, y arma un Execution Graph que define orden, dependencias y ownership.",
      footer: "La misión no arranca improvisada: arranca con contratos explícitos.",
    },
    {
      title: "3. El planner mantiene el control global",
      description:
        "Los especialistas no reciben autonomía ilimitada. Cada perfil opera dentro de superficies y herramientas acotadas, mientras el planner conserva la coordinación general de la misión.",
      footer: "La paralelización se logra repitiendo perfiles conocidos, no inventando roles ad hoc.",
    },
    {
      title: "4. La ejecución es explícita y local-first",
      description:
        "La ejecución vive en el runtime del hub: `run`, `resume` e `interrupt` son acciones explícitas, el runner prepara branch y worktree, y cada run conserva heartbeat, logs, comandos, errores y artefactos.",
      footer: "Local-first no es una limitación accidental: es parte del diseño operativo.",
    },
    {
      title: "5. Verify, release y deploy siguen policies",
      description:
        "Las policies no son etiquetas. Expanden permisos concretos para write, push, merge, deploy y migrate, y definen hasta dónde puede llegar la misión durante verify, release y deploy.",
      footer: "La idea es que el sistema sea gobernable, no simplemente automático.",
    },
  ] satisfies CardItem[],
  capabilities: [
    {
      title: "Modelo de misión",
      description:
        "La misión reúne el contexto de negocio y el contexto técnico en una sola entidad que después usa el runtime.",
      items: [
        "brief, desired outcome, policy y execution controls",
        "linked_products, linked_repositories y linked_documents",
        "Mission Spec, Execution Graph y artifacts asociados",
      ],
    },
    {
      title: "Runtime operativo",
      description:
        "El runtime está pensado para que una misión pueda correrse, inspeccionarse, pausarse y retomarse sin perder contexto operativo.",
      items: [
        "runs persistidos con branch, worktree y current task",
        "command logs y errores guardados por misión",
        "verify y release resueltos con comandos determinísticos",
      ],
    },
    {
      title: "Gobierno y permisos",
      description:
        "Lobo Builder hace explícito qué está permitido en cada misión y qué gates deben cumplirse antes de avanzar.",
      items: [
        "policies cerradas: safe, delivery, prod y autopilot",
        "capability flags para read, write, branch, worktree, commit y release",
        "merge, deploy y migraciones sólo cuando la policy lo habilita",
      ],
    },
    {
      title: "Contexto y observabilidad",
      description:
        "El sistema mantiene una vista operativa del trabajo y una vista estructural del entorno en el que corre.",
      items: [
        "dashboard FastAPI con cola, estado y grafo",
        "graph central con nodos de producto, repo, entorno, documento y misión",
        "descubrimiento de instrucciones repo-locales para respetar contratos existentes",
      ],
    },
  ] satisfies CardItem[],
  systemHighlights: {
    title: "Capas que sostienen el sistema",
    description:
      "La arquitectura separa contratos versionados, estado operativo y superficies de ejecución para que el planeamiento y el runtime hablen el mismo idioma.",
    items: [
      "config/ y docs/ como contratos versionados del sistema",
      "DB y var/ como estado operativo, runs y logs",
      "FastAPI como app host para APIs JSON y dashboard",
    ],
  },
  systemSurfaces: [
    {
      title: "Planner y perfiles",
      description:
        "El planner clasifica la misión, selecciona estrategia, define ownership y coordina el orden de ejecución. Los demás perfiles existen para tareas concretas, no para reemplazar esa autoridad.",
      footer: "El catálogo de perfiles es fijo y forma parte del contrato del sistema.",
    },
    {
      title: "Runner y ejecución",
      description:
        "El runner toma la misión planeada y la lleva al trabajo concreto sobre el repositorio resuelto, con worktree, branch, logs y recuperación de estado.",
      footer: "La ejecución usa `codex exec` para especialistas y comandos determinísticos para gates.",
    },
    {
      title: "Dashboard y API",
      description:
        "La misma app expone las APIs y la interfaz operativa. No hay una separación entre “sitio de control” y “backend oculto”: el hub sirve ambas superficies.",
      footer: "La landing pública explica el sistema; el dashboard opera la misión.",
    },
    {
      title: "Integraciones y destinos",
      description:
        "El sistema modela integraciones de repositorios, deploy y distribución sin convertirlas en side effects implícitos. Git, GitHub, Railway, Vercel y Firebase App Distribution forman parte de esa capa.",
      footer: "Las integraciones se usan como extensiones del runtime, no como centro del producto.",
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
      description: "Quick start, variables útiles, API principal y layout del repo.",
      href: `${repoBase}#readme`,
      label: "Ver README",
    },
    {
      title: "Arquitectura",
      description: "Modelo de misión, grafo, policies y forma del runtime.",
      href: `${repoBase}/blob/main/docs/architecture.md`,
      label: "Leer arquitectura",
    },
    {
      title: "Quick start",
      description: "Cómo levantar el hub local, probar la API y recorrer el layout principal del repo.",
      href: `${repoBase}#quick-start`,
      label: "Ver quick start",
    },
  ],
  runtimePointers: [
    {
      title: "Dashboard operativo",
      description:
        "La UI operativa vive en FastAPI y sirve para inspeccionar misiones, estado, artefactos y grafo.",
      value: "http://127.0.0.1:8042/",
    },
    {
      title: "API de control",
      description:
        "El control plane se opera por endpoints concretos; la landing sólo explica el sistema.",
      value: "GET /api/dashboard · POST /api/missions · /run · /resume · /interrupt",
    },
  ],
  closing: {
    eyebrow: "Dónde seguir",
    title: "La landing funciona como mapa del producto; el repo y el hub local muestran el sistema en operación.",
    description:
      "Si querés entender Lobo Builder en detalle, esta página te da el marco conceptual y el repositorio te lleva al contrato técnico completo: arquitectura, quick start, APIs, policies, perfiles e implementación del runtime.",
  },
};
