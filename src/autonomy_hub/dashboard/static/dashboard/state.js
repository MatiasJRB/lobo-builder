export const SECTION_CONFIG = {
  runtime: {
    label: "Runtime",
    description: "Controles, progreso, worktree y flujo de ejecución.",
  },
  logs: {
    label: "Logs",
    description: "Runs recientes y comandos del runtime enfocado.",
  },
  graph: {
    label: "Grafo",
    description: "Contexto filtrado y relaciones útiles para la misión activa.",
  },
};

export const VALID_SECTIONS = new Set(Object.keys(SECTION_CONFIG));
export const REFRESH_INTERVAL_MS = 15000;

const BASE_VISIBLE_COUNTS = {
  runs: 4,
  commands: 6,
  nodes: 10,
  edges: 10,
};

export const APP_STATE = {
  snapshot: null,
  fullGraph: null,
  focusedMission: null,
  logsView: null,
  selectedMissionId: null,
  selectedSection: "runtime",
  pendingAction: null,
  lastRefreshAt: null,
  flash: null,
  lastError: null,
  missionError: null,
  graphError: null,
  isRefreshing: false,
  isLoadingMission: false,
  lastCenteredFlowKey: null,
  queueExpanded: true,
  visibleRuns: BASE_VISIBLE_COUNTS.runs,
  visibleCommands: BASE_VISIBLE_COUNTS.commands,
  visibleGraphNodes: BASE_VISIBLE_COUNTS.nodes,
  visibleGraphEdges: BASE_VISIBLE_COUNTS.edges,
};

export function actionKey(kind, missionId = "") {
  return missionId ? `${kind}:${missionId}` : kind;
}

export function isPending(key) {
  return APP_STATE.pendingAction === key;
}

export function isValidSection(section) {
  return VALID_SECTIONS.has(section);
}

export function setBanner(tone, message) {
  APP_STATE.flash = { tone, message };
}

export function clearBanner() {
  APP_STATE.flash = null;
}

export function resetProgressiveDisclosure() {
  APP_STATE.visibleRuns = BASE_VISIBLE_COUNTS.runs;
  APP_STATE.visibleCommands = BASE_VISIBLE_COUNTS.commands;
  APP_STATE.visibleGraphNodes = BASE_VISIBLE_COUNTS.nodes;
  APP_STATE.visibleGraphEdges = BASE_VISIBLE_COUNTS.edges;
}

export function resetMissionScopedUiState() {
  resetProgressiveDisclosure();
  APP_STATE.lastCenteredFlowKey = null;
}

export function initializeResponsiveState() {
  APP_STATE.queueExpanded = !window.matchMedia("(max-width: 960px)").matches;
}

export function collapseQueueOnSmallScreens() {
  if (window.matchMedia("(max-width: 960px)").matches) {
    APP_STATE.queueExpanded = false;
  }
}

export function toggleQueueExpanded() {
  APP_STATE.queueExpanded = !APP_STATE.queueExpanded;
}

export function showMoreRuns() {
  APP_STATE.visibleRuns += BASE_VISIBLE_COUNTS.runs;
}

export function showMoreCommands() {
  APP_STATE.visibleCommands += BASE_VISIBLE_COUNTS.commands;
}

export function showMoreGraphNodes() {
  APP_STATE.visibleGraphNodes += BASE_VISIBLE_COUNTS.nodes;
}

export function showMoreGraphEdges() {
  APP_STATE.visibleGraphEdges += BASE_VISIBLE_COUNTS.edges;
}
