import { actionKey, isPending } from "./state.js";
import {
  buildChangedFilesIndicator,
  buildCurrentDiffIndicator,
  buildTaskMap,
  canToggleDeploy,
  escapeHtml,
  findCurrentTask,
  formatBudgetLabel,
  iconMarkup,
  pluralize,
  renderChangeList,
  renderDisclosure,
  renderPanelState,
  resolveProfile,
  safeStatusClass,
  statusLabel,
  statusPill,
  taskScope,
  truncate,
} from "./shared.js";

function renderExecutionControls(mission) {
  const controls = mission?.execution_controls || {};
  const locked = Boolean(mission?.controls_locked);
  const saveBusy = isPending(actionKey("controls", mission.id));
  const showDeploy = canToggleDeploy(mission);

  return `
    <form class="controls-form" data-controls-form data-mission-id="${escapeHtml(mission.id)}">
      <label class="control-row">
        <span class="control-copy">
          <strong>Verify</strong>
          <span>Corre validaciones técnicas y review final.</span>
        </span>
        <input
          type="checkbox"
          name="verify_enabled"
          aria-label="Habilitar verify"
          data-control-field="verify_enabled"
          ${controls.verify_enabled !== false ? "checked" : ""}
          ${locked || saveBusy ? "disabled" : ""}
        />
      </label>

      <label class="control-row">
        <span class="control-copy">
          <strong>Release</strong>
          <span>Ejecuta merge, push y artifacts de cierre permitidos por la policy.</span>
        </span>
        <input
          type="checkbox"
          name="release_enabled"
          aria-label="Habilitar release"
          data-control-field="release_enabled"
          ${controls.release_enabled !== false ? "checked" : ""}
          ${locked || saveBusy ? "disabled" : ""}
        />
      </label>

      ${
        showDeploy
          ? `
            <label class="control-row">
              <span class="control-copy">
                <strong>Deploy</strong>
                <span>Dispara targets explícitos después del release.</span>
              </span>
              <input
                type="checkbox"
                name="deploy_enabled"
                aria-label="Habilitar deploy"
                data-control-field="deploy_enabled"
                ${controls.deploy_enabled !== false ? "checked" : ""}
                ${locked || saveBusy ? "disabled" : ""}
              />
            </label>
          `
          : ""
      }

      <label class="control-row control-row-wide">
        <span class="control-copy">
          <strong>Límite de horas</strong>
          <span>Corta de forma controlada y deja la misión lista para reanudar.</span>
        </span>
        <input
          type="number"
          name="max_runtime_hours"
          min="1"
          step="1"
          inputmode="numeric"
          autocomplete="off"
          aria-label="Límite máximo de horas"
          data-control-field="max_runtime_hours"
          value="${controls.max_runtime_hours ?? ""}"
          placeholder="Sin límite…"
          ${locked || saveBusy ? "disabled" : ""}
        />
      </label>

      <div class="control-footer">
        <span class="body-muted">
          ${escapeHtml(
            locked
              ? "Los controles se bloquearon después del primer run."
              : "La policy sigue siendo el gate final, aunque cambies estos toggles."
          )}
        </span>
        <button
          type="button"
          class="secondary"
          data-save-controls="${escapeHtml(mission.id)}"
          data-focus-id="controls:save:${escapeHtml(mission.id)}"
          ${locked || saveBusy ? 'aria-busy="true" disabled' : ""}
        >
          ${escapeHtml(saveBusy ? "Guardando…" : "Guardar Controles")}
        </button>
      </div>
    </form>
  `;
}

function renderTaskCard(task) {
  const profile = resolveProfile(task.agent_profile_slug);
  const dependencies = (task.depends_on || []).length
    ? `Depende de: ${task.depends_on.join(", ")}`
    : task.notes
      ? truncate(task.notes, 120)
      : "Sin dependencias bloqueantes.";

  return `
    <article class="task-card status-${escapeHtml(safeStatusClass(task.status))}">
      <div class="task-card-head">
        <div class="identity-row">
          ${iconMarkup(profile)}
          <div class="title-stack">
            <strong>${escapeHtml(task.title)}</strong>
            <span class="card-kicker">${escapeHtml(profile.label)}</span>
          </div>
        </div>
        ${statusPill(task.status)}
      </div>
      <p class="task-card-meta">Alcance: ${escapeHtml(taskScope(task))}</p>
      <p class="task-card-note">${escapeHtml(dependencies)}</p>
    </article>
  `;
}

function renderTaskColumn(title, subtitle, items) {
  return `
    <section class="task-column">
      <div class="task-column-head">
        <div>
          <h3>${escapeHtml(title)}</h3>
          <p class="body-muted">${escapeHtml(subtitle)}</p>
        </div>
        <span class="summary-indicator">${escapeHtml(items.length)} ${escapeHtml(pluralize(items.length, "tarea"))}</span>
      </div>
      <div class="task-column-body">
        ${
          items.length
            ? items.map((task) => renderTaskCard(task)).join("")
            : '<p class="empty-copy">No hay tareas en esta columna ahora mismo.</p>'
        }
      </div>
    </section>
  `;
}

function renderTaskBoard(tasks) {
  const working = (tasks || []).filter((task) => task.status === "running");
  const upcoming = (tasks || []).filter((task) => ["ready", "queued"].includes(task.status));
  const blocked = (tasks || []).filter((task) => task.status === "blocked");
  const closed = (tasks || []).filter((task) => ["completed", "failed", "skipped"].includes(task.status));

  return `
    <div class="task-board">
      ${renderTaskColumn("En Curso", "Lo que está ejecutándose ahora mismo.", working)}
      ${renderTaskColumn("Próximas", "Ready y queued, listas para entrar.", upcoming)}
      ${renderTaskColumn("Bloqueadas", "Esperan dependencias o decisiones.", blocked)}
      ${renderTaskColumn("Cerradas", "Completed, failed y skipped.", closed)}
    </div>
  `;
}

function buildRuntimeGraph(tasks, activeTaskKey) {
  if (!tasks?.length) {
    return '<p class="empty-copy">No hay tareas de ejecución planificadas para esta misión.</p>';
  }

  const taskMap = new Map(tasks.map((task, index) => [task.key, { ...task, order: index }]));
  const levelCache = new Map();

  function levelFor(taskKey, trail = new Set()) {
    if (levelCache.has(taskKey)) {
      return levelCache.get(taskKey);
    }

    const task = taskMap.get(taskKey);
    if (!task || trail.has(taskKey)) {
      return 0;
    }

    const nextTrail = new Set(trail);
    nextTrail.add(taskKey);
    const dependencies = (task.depends_on || []).filter((dependency) => taskMap.has(dependency));
    const level = dependencies.length
      ? Math.max(...dependencies.map((dependency) => levelFor(dependency, nextTrail))) + 1
      : 0;
    levelCache.set(taskKey, level);
    return level;
  }

  tasks.forEach((task) => levelFor(task.key));

  const columns = [];
  tasks.forEach((task) => {
    const columnIndex = levelCache.get(task.key) || 0;
    if (!columns[columnIndex]) {
      columns[columnIndex] = [];
    }
    columns[columnIndex].push(task);
  });
  columns.forEach((column) => column.sort((left, right) => taskMap.get(left.key).order - taskMap.get(right.key).order));

  return `
    <div class="flow-board" role="img" aria-label="Camino de ejecución distribuido por etapas">
      ${columns
        .map((column, columnIndex) => {
          const activeStage = column.some((task) => task.key === activeTaskKey);
          const cards = column
            .map((task) => {
              const profile = resolveProfile(task.agent_profile_slug);
              const dependencies = (task.depends_on || [])
                .filter((dependency) => taskMap.has(dependency))
                .map((dependency) => `<span class="flow-chip">${escapeHtml(truncate(taskMap.get(dependency)?.title || dependency, 26))}</span>`)
                .join("");
              const activeClass = task.key === activeTaskKey ? " flow-card-active" : "";

              return `
                <article
                  class="flow-card status-${escapeHtml(safeStatusClass(task.status))}${activeClass}"
                  data-flow-task-key="${escapeHtml(task.key)}"
                  ${task.key === activeTaskKey ? 'data-flow-active="true"' : ""}
                >
                  <div class="task-card-head">
                    <div class="identity-row">
                      ${iconMarkup(profile)}
                      <div class="title-stack">
                        <strong>${escapeHtml(task.title)}</strong>
                        <span class="card-kicker">${escapeHtml(profile.label)}</span>
                      </div>
                    </div>
                    ${statusPill(task.status)}
                  </div>
                  <p class="task-card-meta">Alcance: ${escapeHtml(taskScope(task))}</p>
                  ${
                    dependencies
                      ? `<div class="flow-chip-row">${dependencies}</div>`
                      : '<p class="empty-copy">Inicia este tramo de la ejecución.</p>'
                  }
                </article>
              `;
            })
            .join("");

          return `
            <div class="flow-step${activeStage ? " flow-step-active" : ""}" ${activeStage ? 'data-flow-stage-active="true"' : ""}>
              <div class="task-column-head">
                <div>
                  <h3>Etapa ${escapeHtml(columnIndex + 1)}</h3>
                  <p class="body-muted">${escapeHtml(column.length)} ${escapeHtml(pluralize(column.length, "tarea"))}</p>
                </div>
              </div>
              <div class="flow-step-body">${cards}</div>
            </div>
            ${
              columnIndex < columns.length - 1
                ? '<div class="flow-arrow" aria-hidden="true"><span></span></div>'
                : ""
            }
          `;
        })
        .join("")}
    </div>
  `;
}

function renderWorktreeSnapshot(mission) {
  const worktree = mission?.worktree_snapshot;
  const lastBatch = worktree?.last_committed_batch;
  const changedFilesMarkup = worktree?.dirty_files_count
    ? renderChangeList(worktree.changed_files, "Todavía no hay cambios de archivos.")
    : lastBatch
      ? renderChangeList(lastBatch.changed_files, "El último batch commiteado no trae nombres de archivo.")
      : renderChangeList([], "Todavía no hay cambios de archivos.");
  const diffStat = worktree?.dirty_files_count ? worktree?.diff_stat : lastBatch?.diff_stat;
  const diffMarkup = diffStat
    ? `<pre class="log-block">${escapeHtml(diffStat)}</pre>`
    : '<p class="empty-copy">Todavía no hay diff disponible.</p>';

  return `
    <section class="panel">
      <div class="panel-head">
        <div>
          <p class="eyebrow">Worktree Snapshot</p>
          <h2>Estado visible del checkout</h2>
        </div>
        <p class="body-muted">${escapeHtml(worktree?.note || "Señal del worktree y del último batch conocido.")}</p>
      </div>

      <div class="worktree-summary-grid">
        <article class="signal-card">
          <span>Branch</span>
          <strong class="is-code" translate="no">${escapeHtml(worktree?.branch_name || mission.active_run?.branch_name || "todavía no creada")}</strong>
        </article>
        <article class="signal-card">
          <span>HEAD</span>
          <strong>${escapeHtml(worktree?.head_summary || lastBatch?.commit_subject || "todavía sin commit")}</strong>
        </article>
        <article class="signal-card">
          <span>Budget</span>
          <strong>${escapeHtml(formatBudgetLabel(mission))}</strong>
        </article>
        <article class="signal-card">
          <span>Cambios visibles</span>
          <strong>${escapeHtml(buildChangedFilesIndicator(worktree))}</strong>
        </article>
      </div>

      <div class="panel-grid panel-grid-2">
        <section class="subpanel">
          ${renderDisclosure("Archivos cambiados", buildChangedFilesIndicator(worktree), changedFilesMarkup, {
            open: true,
          })}
        </section>
        <section class="subpanel">
          ${renderDisclosure("Diff actual", buildCurrentDiffIndicator(worktree), diffMarkup)}
        </section>
      </div>
    </section>
  `;
}

export function renderRuntimePanel({ mission, missionError, isLoadingMission }) {
  if (isLoadingMission && !mission) {
    return renderPanelState(
      "loading",
      "Cargando runtime…",
      "Esperando el detalle de la misión para abrir controles, progreso y worktree."
    );
  }

  if (missionError && !mission) {
    return renderPanelState(
      "error",
      "No pude cargar el runtime",
      missionError,
      '<div class="button-row"><button type="button" data-retry-focused class="secondary" data-focus-id="retry-focused">Reintentar</button></div>'
    );
  }

  if (!mission) {
    return renderPanelState(
      "empty",
      "Sin misión enfocada",
      "Seleccioná una misión para abrir controles, board y worktree."
    );
  }

  const currentTask = findCurrentTask(mission);
  const progress = mission.execution_tasks.length
    ? `${mission.execution_tasks.filter((task) => ["completed", "failed", "skipped"].includes(task.status)).length}/${mission.execution_tasks.length}`
    : "0/0";

  return `
    <div class="section-stack">
      <section class="panel">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Execution Flow</p>
            <h2>Camino de ejecución</h2>
          </div>
          <p class="body-muted">Secuencia de etapas y dependencias, con foco centrado en la etapa activa.</p>
        </div>
        <div class="graph-scroll">
          ${buildRuntimeGraph(mission.execution_tasks, currentTask?.key)}
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <p class="eyebrow">Task Progress</p>
            <h2>Board operativo</h2>
          </div>
          <p class="body-muted">Progreso actual: ${escapeHtml(progress)} · foco actual: ${escapeHtml(statusLabel(currentTask?.status || mission.status))}.</p>
        </div>
        ${renderTaskBoard(mission.execution_tasks)}
      </section>

      <div class="panel-grid panel-grid-2">
        <section class="panel">
          <div class="panel-head">
            <div>
              <p class="eyebrow">Execution Controls</p>
              <h2>Gates y límites</h2>
            </div>
            <p class="body-muted">Ajustá verify, release, deploy y budget antes del primer run.</p>
          </div>
          ${renderExecutionControls(mission)}
        </section>
        ${renderWorktreeSnapshot(mission)}
      </div>
    </div>
  `;
}

export function centerActiveFlowCard(state) {
  const container = document.querySelector("#workspace-panel-runtime .graph-scroll");
  const activeStage = container?.querySelector("[data-flow-stage-active='true']");
  const missionId = state.focusedMission?.id || "";
  const taskKey = state.focusedMission ? findCurrentTask(state.focusedMission)?.key || "" : "";
  const nextCenterKey = missionId && taskKey ? `${missionId}:${taskKey}` : null;

  if (!container || !activeStage || !nextCenterKey) {
    return;
  }

  if (state.lastCenteredFlowKey === nextCenterKey) {
    return;
  }

  state.lastCenteredFlowKey = nextCenterKey;
  window.requestAnimationFrame(() => {
    const containerRect = container.getBoundingClientRect();
    const activeRect = activeStage.getBoundingClientRect();
    const delta = (activeRect.left - containerRect.left) - ((container.clientWidth - activeRect.width) / 2);
    const maxScrollLeft = Math.max(0, container.scrollWidth - container.clientWidth);
    const nextScrollLeft = Math.max(0, Math.min(maxScrollLeft, container.scrollLeft + delta));
    container.scrollTo({
      left: nextScrollLeft,
      behavior: "smooth",
    });
  });
}
