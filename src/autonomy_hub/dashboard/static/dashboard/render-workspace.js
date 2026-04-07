import { SECTION_CONFIG, actionKey, isPending } from "./state.js";
import {
  describeMissionHealth,
  escapeHtml,
  filteredGraphForMission,
  findCurrentTask,
  formatBudgetLabel,
  formatClock,
  formatList,
  iconMarkup,
  missionProgress,
  missionQueueItem,
  renderActionButton,
  renderPanelState,
  resolveProfile,
  statusPill,
  truncate,
} from "./shared.js";

function renderSignalCard(label, value, options = {}) {
  const { wide = false, code = false } = options;
  return `
    <article class="signal-card ${wide ? "is-wide" : ""}">
      <span>${escapeHtml(label)}</span>
      <strong class="${code ? "is-code" : ""}" ${code ? 'translate="no"' : ""}>${escapeHtml(value)}</strong>
    </article>
  `;
}

function renderDetailRows(rows) {
  return `
    <dl class="detail-list">
      ${rows
        .map(
          (row) => `
            <div class="detail-list-row">
              <dt>${escapeHtml(row.label)}</dt>
              <dd class="${row.code ? "is-code" : ""}" ${row.code ? 'translate="no"' : ""}>${escapeHtml(row.value)}</dd>
            </div>
          `
        )
        .join("")}
    </dl>
  `;
}

function renderDetailCard(title, indicator, rows, options = {}) {
  const { open = false } = options;
  return `
    <details class="detail-card" ${open ? "open" : ""}>
      <summary>
        <span>${escapeHtml(title)}</span>
        <span class="summary-indicator">${escapeHtml(indicator)}</span>
      </summary>
      ${renderDetailRows(rows)}
    </details>
  `;
}

function renderControlsSummary(mission) {
  const controls = mission?.execution_controls || {};
  return [
    `verify ${controls.verify_enabled === false ? "off" : "on"}`,
    `release ${controls.release_enabled === false ? "off" : "on"}`,
    `deploy ${controls.deploy_enabled === false ? "off" : "on"}`,
  ].join(" · ");
}

export function renderWorkspaceTabs({ selectedSection, disabled }) {
  return `
    <div class="workspace-tabs-inner" role="tablist" aria-label="Secciones del workspace">
      ${Object.entries(SECTION_CONFIG)
        .map(([section, config]) => {
          const selected = selectedSection === section;
          return `
            <button
              type="button"
              id="workspace-tab-${escapeHtml(section)}"
              class="tab-button ${selected ? "is-selected" : ""}"
              role="tab"
              aria-selected="${selected ? "true" : "false"}"
              aria-controls="workspace-panel-${escapeHtml(section)}"
              data-section-link="${escapeHtml(section)}"
              data-focus-id="section:${escapeHtml(section)}"
              ${disabled ? "disabled" : ""}
            >
              <span>${escapeHtml(config.label)}</span>
              <small>${escapeHtml(config.description)}</small>
            </button>
          `;
        })
        .join("")}
    </div>
  `;
}

export function renderWorkspaceHeader({ state }) {
  const mission = state.focusedMission;

  if (state.isLoadingMission && !mission) {
    return renderPanelState(
      "loading",
      "Cargando misión…",
      "Estoy trayendo runtime, logs y resumen operativo de la misión seleccionada."
    );
  }

  if (state.missionError && !mission) {
    return renderPanelState(
      "error",
      "No pude abrir la misión",
      state.missionError,
      '<div class="button-row"><button type="button" data-retry-focused class="secondary" data-focus-id="retry-focused">Reintentar</button></div>'
    );
  }

  if (!mission) {
    return renderPanelState(
      "empty",
      "Sin misión enfocada",
      "Elegí una misión de la cola para ver el workspace operativo."
    );
  }

  const queueItem = missionQueueItem(state.snapshot?.queue, mission.id);
  const graph = filteredGraphForMission(state.fullGraph, mission);
  const currentTask = findCurrentTask(mission);
  const currentProfile = resolveProfile(currentTask?.agent_profile_slug || queueItem?.current_owner || "planner");
  const health = describeMissionHealth(mission);
  const progress = missionProgress(mission);
  const lastCommand = mission.active_run?.last_command;
  const worktree = mission.worktree_snapshot;
  const nextStep = queueItem?.next_step || currentTask?.title || "sin programación";
  const refreshLabel = state.isRefreshing
    ? "Actualizando…"
    : state.lastRefreshAt
      ? `${formatClock(state.lastRefreshAt)} · polling 15s`
      : "pendiente";
  const artifactSummary = mission.artifacts.length
    ? mission.artifacts
        .slice(0, 4)
        .map((artifact) => artifact.title)
        .join(", ")
    : "sin artifacts todavía";

  return `
    <div class="workspace-hero">
      <div class="workspace-hero-copy">
        <p class="eyebrow">Misión Activa</p>
        <h1 id="workspace-heading">${escapeHtml(mission.spec.summary || mission.brief)}</h1>
        <p class="workspace-lede">${escapeHtml(mission.desired_outcome || mission.brief)}</p>
        <div class="inline-chip-row">
          <span class="chip">${escapeHtml(mission.policy.label || mission.policy.slug)}</span>
          ${statusPill(mission.active_run?.status || mission.status)}
          <span class="chip subtle-chip" translate="no">Mission ${escapeHtml(mission.id.slice(0, 8))}</span>
        </div>
      </div>

      <article class="health-card tone-${escapeHtml(health.tone)}">
        <div class="health-card-head">
          <span class="pulse-led tone-${escapeHtml(health.tone)}" aria-hidden="true"></span>
          <div>
            <span class="card-kicker">Estado general</span>
            <strong>${escapeHtml(health.title)}</strong>
          </div>
        </div>
        <p>${escapeHtml(health.body)}</p>
        <div class="health-card-meta">
          <span>${escapeHtml(health.detail)}</span>
          <strong>${escapeHtml(health.activityLabel)}</strong>
        </div>
      </article>
    </div>

    <div class="workspace-actions">
      ${renderActionButton({
        action: "run",
        missionId: mission.id,
        label: "Correr",
        busy: isPending(actionKey("run", mission.id)),
      })}
      ${renderActionButton({
        action: "resume",
        missionId: mission.id,
        label: "Reanudar",
        busy: isPending(actionKey("resume", mission.id)),
        className: "secondary",
      })}
      ${renderActionButton({
        action: "interrupt",
        missionId: mission.id,
        label: "Interrumpir",
        busy: isPending(actionKey("interrupt", mission.id)),
        className: "ghost",
      })}
    </div>

    <div class="signal-grid">
      ${renderSignalCard("Owner activo", currentProfile.label)}
      ${renderSignalCard("Próximo paso", nextStep, { wide: true })}
      ${renderSignalCard("Progreso", `${progress.closed}/${progress.total || 0} cerradas`)}
      ${renderSignalCard("Budget", `${formatBudgetLabel(mission)}${mission.runtime_budget_reached ? " · límite" : ""}`)}
      ${renderSignalCard("Última sincronización", refreshLabel)}
      ${renderSignalCard("Último comando", truncate(lastCommand?.command || "sin comandos todavía", 56), {
        wide: true,
        code: Boolean(lastCommand?.command),
      })}
    </div>

    <div class="detail-grid">
      ${renderDetailCard(
        "Branch & Worktree",
        worktree?.branch_name || "sin worktree",
        [
          { label: "Branch", value: worktree?.branch_name || mission.active_run?.branch_name || "todavía no creada", code: true },
          { label: "Worktree", value: worktree?.worktree_path || mission.active_run?.worktree_path || "todavía no creado", code: true },
          { label: "HEAD", value: worktree?.head_summary || worktree?.last_committed_batch?.commit_subject || "todavía sin commit" },
          { label: "Cambios", value: `${worktree?.dirty_files_count || 0} archivos` },
        ],
        { open: true }
      )}
      ${renderDetailCard(
        "Release & Deploy",
        mission.policy.slug,
        [
          { label: "Merge target", value: mission.spec.merge_target || "sin declarar" },
          { label: "Deploy targets", value: formatList(mission.spec.deploy_targets, "ninguno") },
          { label: "Controles", value: renderControlsSummary(mission) },
          { label: "Policy", value: mission.policy.description || mission.policy.slug },
        ]
      )}
      ${renderDetailCard(
        "Contexto Relacionado",
        `${graph?.nodes?.length || 0} nodos`,
        [
          { label: "Repos", value: formatList(mission.linked_repositories, "greenfield"), code: true },
          { label: "Productos", value: formatList(mission.linked_products, "sin productos") },
          { label: "Documentos", value: formatList(mission.linked_documents, "sin documentos") },
          { label: "Artifacts", value: artifactSummary },
        ]
      )}
    </div>
  `;
}
