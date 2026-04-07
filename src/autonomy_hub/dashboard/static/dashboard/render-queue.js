import { isPending } from "./state.js";
import {
  escapeHtml,
  iconMarkup,
  renderPanelState,
  repositoryCount,
  resolveProfile,
  statusPill,
  truncate,
} from "./shared.js";

function renderMissionCard(item, selectedMissionId) {
  const owner = resolveProfile(item.current_owner || "planner");
  const selected = selectedMissionId === item.mission_id;
  const repoSummary = item.linked_repositories.length
    ? item.linked_repositories.join(", ")
    : "greenfield";
  const status = item.runtime_state || item.status;

  return `
    <button
      type="button"
      class="mission-card ${selected ? "is-selected" : ""}"
      data-select-mission="${escapeHtml(item.mission_id)}"
      data-focus-id="mission:${escapeHtml(item.mission_id)}"
      aria-pressed="${selected ? "true" : "false"}"
    >
      <div class="mission-card-top">
        <span class="mission-card-type">${escapeHtml(item.mission_type)}</span>
        ${statusPill(status)}
      </div>
      <strong class="mission-card-title">${escapeHtml(truncate(item.next_step, 92))}</strong>
      <p class="mission-card-owner">Owner activo: ${escapeHtml(owner.label)}</p>
      <div class="mission-card-meta">
        <span translate="no">${escapeHtml(item.mission_id.slice(0, 8))}</span>
        <span>${escapeHtml(truncate(repoSummary, 28))}</span>
        <span>${escapeHtml(`${item.changed_files_count} archivos`)}</span>
      </div>
    </button>
  `;
}

function renderGlobalButton({ id, focusId, label, busyLabel, busy, className = "" }) {
  return `
    <button
      type="button"
      id="${id}"
      class="${className}"
      data-focus-id="${focusId}"
      ${busy ? 'aria-busy="true" disabled' : ""}
    >
      ${escapeHtml(busy ? busyLabel : label)}
    </button>
  `;
}

export function renderQueueRail({
  snapshot,
  fullGraph,
  selectedMissionId,
  isRefreshing,
  queueExpanded,
}) {
  const items = snapshot?.queue || [];
  const graph = fullGraph || snapshot?.map || null;
  const metrics = [
    { label: "Misiones", value: items.length },
    { label: "Repos", value: repositoryCount(graph) },
    { label: "Nodos", value: graph?.nodes?.length || 0 },
  ];

  return `
    <div class="rail-shell">
      <div class="rail-header">
        <div>
          <p class="eyebrow">Planner Queue</p>
          <h2 id="mission-queue-title">Misiones</h2>
          <p class="body-muted">Escaneá rápido, cambiá de foco y mantené el workspace operativo en contexto.</p>
        </div>
        <button
          type="button"
          id="queue-toggle"
          class="ghost queue-toggle"
          data-focus-id="queue-toggle"
          aria-controls="mission-queue-list"
          aria-expanded="${queueExpanded ? "true" : "false"}"
        >
          ${queueExpanded ? "Ocultar Cola" : "Mostrar Cola"}
        </button>
      </div>

      <div class="rail-metrics">
        ${metrics
          .map(
            (item) => `
              <article class="metric-card">
                <span>${escapeHtml(item.label)}</span>
                <strong>${escapeHtml(item.value)}</strong>
              </article>
            `
          )
          .join("")}
      </div>

      <div class="rail-actions">
        ${renderGlobalButton({
          id: "seed-demo",
          focusId: "seed-demo",
          label: "Crear Demo",
          busyLabel: "Creando…",
          busy: isPending("seed-demo"),
        })}
        ${renderGlobalButton({
          id: "discover-local",
          focusId: "discover-local",
          label: "Descubrir Repos",
          busyLabel: "Descubriendo…",
          busy: isPending("discover-local"),
          className: "secondary",
        })}
        ${renderGlobalButton({
          id: "refresh-dashboard",
          focusId: "refresh-dashboard",
          label: "Actualizar",
          busyLabel: "Actualizando…",
          busy: isRefreshing,
          className: "ghost",
        })}
      </div>

      <div id="mission-queue-list" class="mission-queue-list ${queueExpanded ? "is-expanded" : "is-collapsed"}">
        ${
          items.length
            ? items.map((item) => renderMissionCard(item, selectedMissionId)).join("")
            : renderPanelState(
                "empty",
                "Todavía no hay misiones",
                "Podés crear una demo o disparar una misión desde la API para poblar la cola."
              )
        }
      </div>
    </div>
  `;
}
