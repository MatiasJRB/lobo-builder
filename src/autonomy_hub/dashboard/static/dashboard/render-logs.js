import {
  basenamePath,
  buildTaskMap,
  commandKindLabel,
  escapeHtml,
  formatDateTime,
  iconMarkup,
  latestCommandForRun,
  renderPanelState,
  representativeTaskForRun,
  resolveProfile,
  statusPill,
  truncate,
} from "./shared.js";

function renderRunsMarkup(mission, logsView, visibleRuns) {
  if (!mission || !logsView?.runs?.length) {
    return '<p class="empty-copy">Todavía no hay runs para la misión enfocada.</p>';
  }

  const taskMap = buildTaskMap(mission.execution_tasks);

  return logsView.runs.slice(0, visibleRuns).map((run) => {
    const task = representativeTaskForRun(taskMap, run, logsView) || latestCommandForRun(logsView, run.id);
    const profile = resolveProfile(task?.agent_profile_slug || "");
    const summary = task?.title || run.current_task_key || "Runtime shell";

    return `
      <article class="log-card">
        <div class="task-card-head">
          <div class="identity-row">
            ${iconMarkup(profile)}
            <div class="title-stack">
              <strong>${escapeHtml(summary)}</strong>
              <span class="card-kicker">${escapeHtml(profile.label)}</span>
            </div>
          </div>
          ${statusPill(run.status)}
        </div>
        <div class="log-meta-list">
          <span translate="no">Run ${escapeHtml(run.id.slice(0, 8))}</span>
          <span>Inicio: ${escapeHtml(formatDateTime(run.started_at || run.created_at))}</span>
          <span>Fin: ${escapeHtml(formatDateTime(run.completed_at))}</span>
          ${
            run.last_error
              ? `<span class="tone-danger">${escapeHtml(truncate(run.last_error, 120))}</span>`
              : ""
          }
        </div>
      </article>
    `;
  }).join("");
}

function renderCommandsMarkup(mission, logsView, visibleCommands) {
  if (!mission || !logsView?.commands?.length) {
    return '<p class="empty-copy">Todavía no hay comandos ejecutados para la misión enfocada.</p>';
  }

  const taskMap = buildTaskMap(mission.execution_tasks);

  return logsView.commands.slice(0, visibleCommands).map((command) => {
    const task = taskMap.get(command.task_key);
    const profile = resolveProfile(task?.agent_profile_slug || "");

    return `
      <article class="log-card">
        <div class="task-card-head">
          <div class="identity-row">
            ${iconMarkup(profile)}
            <div class="title-stack">
              <strong>${escapeHtml(task?.title || command.task_key)}</strong>
              <span class="card-kicker">${escapeHtml(profile.label)}</span>
            </div>
          </div>
          ${statusPill(command.status)}
        </div>
        <p class="command-line" title="${escapeHtml(command.command)}" translate="no">${escapeHtml(
          truncate(command.command, 110)
        )}</p>
        <div class="log-meta-list">
          <span>${escapeHtml(commandKindLabel(command.kind))}</span>
          <span>Exit: ${escapeHtml(command.exit_code ?? "en curso")}</span>
          <span>Log: ${escapeHtml(basenamePath(command.log_path))}</span>
          <span>CWD: ${escapeHtml(basenamePath(command.cwd))}</span>
        </div>
      </article>
    `;
  }).join("");
}

function renderShowMore(kind, remaining) {
  if (remaining <= 0) {
    return "";
  }

  return `
    <button
      type="button"
      class="ghost show-more-button"
      data-show-more="${escapeHtml(kind)}"
      data-focus-id="show-more:${escapeHtml(kind)}"
    >
      ${escapeHtml(`Mostrar ${remaining} más`)}
    </button>
  `;
}

export function renderLogsPanel({ mission, logsView, missionError, isLoadingMission, visibleRuns, visibleCommands }) {
  if (isLoadingMission && !mission) {
    return renderPanelState(
      "loading",
      "Cargando logs…",
      "Esperando runs y comandos del runtime seleccionado."
    );
  }

  if (missionError && !mission) {
    return renderPanelState(
      "error",
      "No pude cargar los logs",
      missionError,
      '<div class="button-row"><button type="button" data-retry-focused class="secondary" data-focus-id="retry-focused">Reintentar</button></div>'
    );
  }

  if (!mission) {
    return renderPanelState(
      "empty",
      "Sin misión enfocada",
      "Cuando elijas una misión, acá vas a ver runs y comandos recientes."
    );
  }

  const runsRemaining = Math.max(0, (logsView?.runs?.length || 0) - visibleRuns);
  const commandsRemaining = Math.max(0, (logsView?.commands?.length || 0) - visibleCommands);

  return `
    <div class="panel-grid panel-grid-2">
      <section class="panel">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Runs</p>
            <h2>Secuencia reciente</h2>
          </div>
          <p class="body-muted">Hasta dónde llegó el runtime en sus últimas ejecuciones.</p>
        </div>
        <div class="section-stack">
          ${renderRunsMarkup(mission, logsView, visibleRuns)}
          ${renderShowMore("runs", runsRemaining)}
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Comandos</p>
            <h2>Última actividad</h2>
          </div>
          <p class="body-muted">Comandos del runtime enfocando la señal más reciente.</p>
        </div>
        <div class="section-stack">
          ${renderCommandsMarkup(mission, logsView, visibleCommands)}
          ${renderShowMore("commands", commandsRemaining)}
        </div>
      </section>
    </div>
  `;
}
