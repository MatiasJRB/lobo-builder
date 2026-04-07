import {
  createDemoMission,
  discoverLocal,
  loadDashboardSnapshot,
  loadGraphSnapshot,
  loadMission,
  loadMissionLogs,
  patchMissionControls,
  postMissionAction,
} from "./dashboard/api.js";
import { installEventHandlers } from "./dashboard/events.js";
import { renderGraphPanel } from "./dashboard/render-graph.js";
import { renderLogsPanel } from "./dashboard/render-logs.js";
import { renderQueueRail } from "./dashboard/render-queue.js";
import { centerActiveFlowCard, renderRuntimePanel } from "./dashboard/render-runtime.js";
import { renderWorkspaceHeader, renderWorkspaceTabs } from "./dashboard/render-workspace.js";
import {
  APP_STATE,
  REFRESH_INTERVAL_MS,
  clearBanner,
  collapseQueueOnSmallScreens,
  initializeResponsiveState,
  resetMissionScopedUiState,
  setBanner,
  showMoreCommands,
  showMoreGraphEdges,
  showMoreGraphNodes,
  showMoreRuns,
  toggleQueueExpanded,
} from "./dashboard/state.js";
import {
  ensureIconSprite,
  escapeHtml,
  filteredGraphForMission,
  parseAppError,
  resolveSelectedMissionId,
  safeStatusClass,
} from "./dashboard/shared.js";
import { readUrlState, syncUrlState } from "./dashboard/url-state.js";

let refreshInFlight = false;
let refreshTimerId = null;

function announce(message) {
  const target = document.getElementById("status-live-region");
  if (!target) {
    return;
  }

  target.textContent = "";
  window.requestAnimationFrame(() => {
    target.textContent = message;
  });
}

function renderBanner() {
  const banner = document.getElementById("status-banner");
  if (!banner) {
    return;
  }

  if (!APP_STATE.flash?.message) {
    banner.hidden = true;
    banner.className = "status-banner";
    banner.innerHTML = "";
    return;
  }

  banner.hidden = false;
  banner.className = `status-banner tone-${safeStatusClass(APP_STATE.flash.tone || "neutral")}`;
  banner.innerHTML = `
    <div class="status-banner-copy">
      <strong>${escapeHtml({
        success: "Listo",
        warning: "Atención",
        error: "Error",
        neutral: "Info",
      }[APP_STATE.flash.tone] || "Info")}</strong>
      <p>${escapeHtml(APP_STATE.flash.message)}</p>
    </div>
    <button type="button" class="ghost" data-dismiss-banner data-focus-id="dismiss-banner">Cerrar</button>
  `;
}

function captureFocusToken() {
  const active = document.activeElement;

  if (!active || active === document.body) {
    return null;
  }

  if (active.dataset?.focusId) {
    return { kind: "focus-id", value: active.dataset.focusId };
  }

  if (active.id) {
    return { kind: "id", value: active.id };
  }

  return null;
}

function restoreFocusToken(token) {
  if (!token) {
    return;
  }

  let nextTarget = null;
  if (token.kind === "id") {
    nextTarget = document.getElementById(token.value);
  } else {
    nextTarget = [...document.querySelectorAll("[data-focus-id]")].find((node) => {
      return node.dataset.focusId === token.value;
    });
  }

  if (nextTarget instanceof HTMLElement && !nextTarget.hasAttribute("disabled")) {
    nextTarget.focus({ preventScroll: true });
  }
}

function setPanelVisibility(panelId, selected) {
  const panel = document.getElementById(panelId);
  if (!panel) {
    return;
  }

  panel.hidden = !selected;
  panel.setAttribute("aria-hidden", selected ? "false" : "true");
}

function renderDashboard() {
  const focusToken = captureFocusToken();
  const graph = filteredGraphForMission(APP_STATE.fullGraph, APP_STATE.focusedMission);

  renderBanner();
  document.getElementById("mission-queue").innerHTML = renderQueueRail({
    snapshot: APP_STATE.snapshot,
    fullGraph: APP_STATE.fullGraph,
    selectedMissionId: APP_STATE.selectedMissionId,
    isRefreshing: APP_STATE.isRefreshing,
    queueExpanded: APP_STATE.queueExpanded,
  });
  document.getElementById("dashboard-header").innerHTML = renderWorkspaceHeader({ state: APP_STATE });
  document.getElementById("workspace-tabs").innerHTML = renderWorkspaceTabs({
    selectedSection: APP_STATE.selectedSection,
    disabled: !APP_STATE.selectedMissionId,
  });
  document.getElementById("workspace-panel-runtime").innerHTML = renderRuntimePanel({
    mission: APP_STATE.focusedMission,
    missionError: APP_STATE.missionError,
    isLoadingMission: APP_STATE.isLoadingMission,
  });
  document.getElementById("workspace-panel-logs").innerHTML = renderLogsPanel({
    mission: APP_STATE.focusedMission,
    logsView: APP_STATE.logsView,
    missionError: APP_STATE.missionError,
    isLoadingMission: APP_STATE.isLoadingMission,
    visibleRuns: APP_STATE.visibleRuns,
    visibleCommands: APP_STATE.visibleCommands,
  });
  document.getElementById("workspace-panel-graph").innerHTML = renderGraphPanel({
    mission: APP_STATE.focusedMission,
    graph,
    graphError: APP_STATE.graphError,
    visibleGraphNodes: APP_STATE.visibleGraphNodes,
    visibleGraphEdges: APP_STATE.visibleGraphEdges,
  });

  setPanelVisibility("workspace-panel-runtime", APP_STATE.selectedSection === "runtime");
  setPanelVisibility("workspace-panel-logs", APP_STATE.selectedSection === "logs");
  setPanelVisibility("workspace-panel-graph", APP_STATE.selectedSection === "graph");

  restoreFocusToken(focusToken);

  if (APP_STATE.selectedSection === "runtime" && APP_STATE.focusedMission) {
    centerActiveFlowCard(APP_STATE);
  }
}

function handleError(error) {
  setBanner("error", parseAppError(error));
  renderDashboard();
}

async function loadFocusedMission(missionId) {
  if (!missionId) {
    APP_STATE.focusedMission = null;
    APP_STATE.logsView = null;
    APP_STATE.missionError = null;
    renderDashboard();
    return;
  }

  APP_STATE.isLoadingMission = true;
  APP_STATE.missionError = null;
  renderDashboard();

  try {
    const [mission, logsView] = await Promise.all([loadMission(missionId), loadMissionLogs(missionId)]);

    if (APP_STATE.selectedMissionId !== missionId) {
      return;
    }

    APP_STATE.focusedMission = mission;
    APP_STATE.logsView = logsView;
  } catch (error) {
    if (APP_STATE.selectedMissionId !== missionId) {
      return;
    }

    APP_STATE.focusedMission = null;
    APP_STATE.logsView = null;
    APP_STATE.missionError = parseAppError(error);
    setBanner("error", `No pude cargar la misión seleccionada. ${APP_STATE.missionError}`);
  } finally {
    if (APP_STATE.selectedMissionId === missionId) {
      APP_STATE.isLoadingMission = false;
    }
    renderDashboard();
  }
}

async function refreshDashboard(options = {}) {
  const { announceRefresh = false } = options;
  if (refreshInFlight) {
    return;
  }

  refreshInFlight = true;
  APP_STATE.isRefreshing = true;
  APP_STATE.lastError = null;
  renderDashboard();

  try {
    await ensureIconSprite();

    const snapshotPromise = loadDashboardSnapshot();
    const graphPromise = loadGraphSnapshot().catch((error) => {
      APP_STATE.graphError = parseAppError(error);
      return null;
    });

    const [snapshot, fullGraph] = await Promise.all([snapshotPromise, graphPromise]);
    APP_STATE.snapshot = snapshot;

    if (fullGraph) {
      APP_STATE.fullGraph = fullGraph;
      APP_STATE.graphError = null;
    }

    const selectedMissionId = resolveSelectedMissionId(
      snapshot.queue,
      snapshot.focused_mission_id,
      APP_STATE.selectedMissionId
    );
    const missionChanged = APP_STATE.selectedMissionId !== selectedMissionId;

    APP_STATE.selectedMissionId = selectedMissionId;
    if (missionChanged) {
      resetMissionScopedUiState();
      APP_STATE.focusedMission = null;
      APP_STATE.logsView = null;
      APP_STATE.missionError = null;
    }

    syncUrlState(
      {
        selectedMissionId: APP_STATE.selectedMissionId,
        selectedSection: APP_STATE.selectedSection,
      },
      { replace: true }
    );
    renderDashboard();

    if (selectedMissionId) {
      await loadFocusedMission(selectedMissionId);
    } else {
      APP_STATE.focusedMission = null;
      APP_STATE.logsView = null;
      APP_STATE.missionError = null;
    }

    APP_STATE.lastRefreshAt = new Date().toISOString();

    if (APP_STATE.graphError && APP_STATE.flash?.tone !== "success") {
      setBanner(
        "warning",
        `Actualicé misiones y runtime, pero el grafo global no se pudo refrescar. ${APP_STATE.graphError}`
      );
    } else if (announceRefresh) {
      clearBanner();
      announce("Dashboard actualizado.");
    }
  } catch (error) {
    APP_STATE.lastError = parseAppError(error);
    setBanner("error", `No pude actualizar el dashboard. ${APP_STATE.lastError}`);
  } finally {
    APP_STATE.isRefreshing = false;
    refreshInFlight = false;
    renderDashboard();
  }
}

async function withPendingAction(key, action) {
  if (APP_STATE.pendingAction) {
    return;
  }

  APP_STATE.pendingAction = key;
  renderDashboard();

  try {
    await action();
  } finally {
    APP_STATE.pendingAction = null;
    renderDashboard();
  }
}

async function runMissionAction(missionId, action) {
  await withPendingAction(`${action}:${missionId}`, async () => {
    await postMissionAction(missionId, action);
    setBanner("success", `Acción "${action}" enviada para la misión ${missionId.slice(0, 8)}.`);
    await refreshDashboard();
  });
}

async function saveMissionControls(missionId) {
  const form = document.querySelector(`[data-controls-form][data-mission-id="${missionId}"]`);
  if (!form) {
    return;
  }

  const payload = {
    verify_enabled: form.querySelector('[data-control-field="verify_enabled"]')?.checked ?? true,
    release_enabled: form.querySelector('[data-control-field="release_enabled"]')?.checked ?? true,
    max_runtime_hours: null,
  };

  const deployToggle = form.querySelector('[data-control-field="deploy_enabled"]');
  if (deployToggle) {
    payload.deploy_enabled = deployToggle.checked;
  }

  const hoursInput = form.querySelector('[data-control-field="max_runtime_hours"]');
  const rawHours = hoursInput?.value?.trim?.() || "";
  const parsedHours = rawHours ? Number.parseInt(rawHours, 10) : null;
  payload.max_runtime_hours = Number.isNaN(parsedHours) ? null : parsedHours;

  await withPendingAction(`controls:${missionId}`, async () => {
    await patchMissionControls(missionId, payload);
    setBanner("success", `Guardé los controles de la misión ${missionId.slice(0, 8)}.`);
    await refreshDashboard();
  });
}

async function seedDemoMission() {
  await withPendingAction("seed-demo", async () => {
    const mission = await createDemoMission();
    APP_STATE.selectedMissionId = mission.id;
    collapseQueueOnSmallScreens();
    syncUrlState(
      {
        selectedMissionId: APP_STATE.selectedMissionId,
        selectedSection: APP_STATE.selectedSection,
      },
      { replace: false }
    );
    setBanner("success", `Creé la misión demo ${mission.id.slice(0, 8)} y la dejé como foco actual.`);
    await refreshDashboard();
  });
}

async function refreshLocalDiscovery() {
  await withPendingAction("discover-local", async () => {
    await discoverLocal();
    setBanner("success", "Actualicé el descubrimiento local y refresqué el contexto del workspace.");
    await refreshDashboard();
  });
}

async function selectMission(missionId, options = {}) {
  const { pushHistory = true } = options;

  if (!missionId || missionId === APP_STATE.selectedMissionId) {
    if (pushHistory) {
      syncUrlState(
        {
          selectedMissionId: APP_STATE.selectedMissionId,
          selectedSection: APP_STATE.selectedSection,
        },
        { replace: false }
      );
    }
    renderDashboard();
    return;
  }

  APP_STATE.selectedMissionId = missionId;
  APP_STATE.focusedMission = null;
  APP_STATE.logsView = null;
  APP_STATE.missionError = null;
  resetMissionScopedUiState();
  collapseQueueOnSmallScreens();
  syncUrlState(
    {
      selectedMissionId: APP_STATE.selectedMissionId,
      selectedSection: APP_STATE.selectedSection,
    },
    { replace: !pushHistory }
  );
  renderDashboard();
  await loadFocusedMission(missionId);
}

function selectSection(section, options = {}) {
  const { pushHistory = true } = options;
  if (!section || APP_STATE.selectedSection === section) {
    return;
  }

  APP_STATE.selectedSection = section;
  syncUrlState(
    {
      selectedMissionId: APP_STATE.selectedMissionId,
      selectedSection: APP_STATE.selectedSection,
    },
    { replace: !pushHistory }
  );
  renderDashboard();
}

function handleShowMore(kind) {
  if (kind === "runs") {
    showMoreRuns();
  } else if (kind === "commands") {
    showMoreCommands();
  } else if (kind === "nodes") {
    showMoreGraphNodes();
  } else if (kind === "edges") {
    showMoreGraphEdges();
  }

  renderDashboard();
}

function startRefreshLoop() {
  if (refreshTimerId) {
    window.clearInterval(refreshTimerId);
  }

  refreshTimerId = window.setInterval(() => {
    refreshDashboard().catch(handleError);
  }, REFRESH_INTERVAL_MS);
}

function handlePopState() {
  const nextState = readUrlState();
  APP_STATE.selectedSection = nextState.section;

  if (nextState.missionId && nextState.missionId !== APP_STATE.selectedMissionId) {
    selectMission(nextState.missionId, { pushHistory: false }).catch(handleError);
    return;
  }

  if (!nextState.missionId && APP_STATE.selectedMissionId) {
    APP_STATE.selectedMissionId = null;
    APP_STATE.focusedMission = null;
    APP_STATE.logsView = null;
    APP_STATE.missionError = null;
    resetMissionScopedUiState();
  }

  renderDashboard();
}

document.addEventListener("DOMContentLoaded", () => {
  const urlState = readUrlState();
  APP_STATE.selectedMissionId = urlState.missionId;
  APP_STATE.selectedSection = urlState.section;
  initializeResponsiveState();

  installEventHandlers({
    onCreateDemoMission: seedDemoMission,
    onDiscoverLocal: refreshLocalDiscovery,
    onRefreshDashboard: refreshDashboard,
    onSelectMission: selectMission,
    onSelectSection: selectSection,
    onRetryFocused: async () => {
      if (APP_STATE.selectedMissionId) {
        await loadFocusedMission(APP_STATE.selectedMissionId);
      }
    },
    onSaveMissionControls: saveMissionControls,
    onPostMissionAction: runMissionAction,
    onToggleQueue: () => {
      toggleQueueExpanded();
      renderDashboard();
    },
    onShowMore: handleShowMore,
    onDismissBanner: () => {
      clearBanner();
      renderDashboard();
    },
    onPopState: handlePopState,
    onError: handleError,
  });

  renderDashboard();
  refreshDashboard().catch(handleError);
  startRefreshLoop();
});
