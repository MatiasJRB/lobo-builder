const PROFILE_DEFINITIONS = {
  planner: { label: "Planner", icon: "workflow" },
  "context-mapper": { label: "Context Mapper", icon: "map" },
  "product-spec": { label: "Product/Spec", icon: "file-text" },
  architect: { label: "Architect", icon: "compass" },
  "backend-implementer": { label: "Backend Implementer", icon: "server" },
  "frontend-implementer": { label: "Frontend Implementer", icon: "monitor-smartphone" },
  "data-infra-implementer": { label: "Data/Infra Implementer", icon: "database" },
  "verifier-reviewer": { label: "Verifier/Reviewer", icon: "shield-check" },
  "release-deploy": { label: "Release/Deploy", icon: "rocket" },
};

const PROFILE_ALIASES = {
  planner: "planner",
  "context mapper": "context-mapper",
  "context-mapper": "context-mapper",
  "product/spec": "product-spec",
  "product spec": "product-spec",
  "product-spec": "product-spec",
  architect: "architect",
  "backend implementer": "backend-implementer",
  "backend-implementer": "backend-implementer",
  "frontend implementer": "frontend-implementer",
  "frontend-implementer": "frontend-implementer",
  "data/infra implementer": "data-infra-implementer",
  "data infra implementer": "data-infra-implementer",
  "data-infra-implementer": "data-infra-implementer",
  "verifier/reviewer": "verifier-reviewer",
  "verifier reviewer": "verifier-reviewer",
  "verifier-reviewer": "verifier-reviewer",
  "release/deploy": "release-deploy",
  "release deploy": "release-deploy",
  "release-deploy": "release-deploy",
};

const STATUS_LABELS = {
  planned: "planificada",
  queued: "en cola",
  ready: "lista",
  running: "en curso",
  verifying: "verificando",
  releasing: "liberando",
  completed: "completada",
  failed: "fallida",
  interrupted: "interrumpida",
  blocked: "bloqueada",
  idle: "inactiva",
};

const COMMAND_KIND_LABELS = {
  codex: "Codex",
  git: "Git",
  verify: "Chequeo",
  shell: "Shell",
  firebase: "Firebase",
  "android-build": "Android",
};

let iconSpritePromise = null;
let refreshInFlight = false;

async function fetchJson(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function truncate(value, maxLength = 32) {
  const text = String(value ?? "");
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, Math.max(0, maxLength - 1))}\u2026`;
}

function normalizeProfileKey(value) {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

function resolveProfile(value) {
  const normalized = normalizeProfileKey(value);
  const canonical = PROFILE_ALIASES[normalized] || normalized;
  const profile = PROFILE_DEFINITIONS[canonical];
  if (profile) {
    return { slug: canonical, ...profile };
  }
  return {
    slug: canonical || "unknown",
    label: String(value || "Unknown Profile"),
    icon: "placeholder",
  };
}

async function ensureIconSprite() {
  if (!iconSpritePromise) {
    iconSpritePromise = (async () => {
      if (document.getElementById("icon-sprite-store")) {
        return;
      }
      const response = await fetch("/static/lucide-sprite.svg");
      if (!response.ok) {
        throw new Error("Unable to load icon sprite.");
      }
      const holder = document.createElement("div");
      holder.id = "icon-sprite-store";
      holder.hidden = true;
      holder.innerHTML = await response.text();
      document.body.prepend(holder);
    })();
  }
  return iconSpritePromise;
}

function iconMarkup(profileValue, options = {}) {
  const { className = "agent-icon" } = options;
  const profile = typeof profileValue === "string" ? resolveProfile(profileValue) : profileValue;
  const iconId = profile?.icon || "placeholder";
  return `
    <span class="icon-shell ${className}" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none">
        <use href="#${iconId}"></use>
      </svg>
    </span>
  `;
}

function safeStatusClass(value) {
  return String(value ?? "unknown").toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

function statusPill(status) {
  const normalized = safeStatusClass(status);
  const label = STATUS_LABELS[normalized] || String(status || "idle");
  return `<span class="pill status-pill status-${normalized}">${escapeHtml(label)}</span>`;
}

function formatDateTime(value) {
  if (!value) {
    return "sin dato";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString();
}

function formatList(values, fallback = "ninguno") {
  return values?.length ? values.join(", ") : fallback;
}

function pluralize(value, singular, plural = `${singular}s`) {
  return value === 1 ? singular : plural;
}

function commandKindLabel(value) {
  return COMMAND_KIND_LABELS[value] || String(value || "Shell");
}

function basenamePath(value) {
  const text = String(value || "");
  if (!text) {
    return "n/a";
  }
  const pieces = text.split("/");
  return pieces[pieces.length - 1] || text;
}

function formatDiffIndicator(insertions = 0, deletions = 0, prefix = "") {
  const label = `+${insertions || 0} / -${deletions || 0}`;
  return prefix ? `${prefix} ${label}` : label;
}

function buildChangedFilesIndicator(worktree) {
  const dirtyCount = Number(worktree?.dirty_files_count || worktree?.changed_files?.length || 0);
  const lastBatchCount = Number(worktree?.last_committed_batch?.files_count || 0);
  if (dirtyCount > 0) {
    return String(dirtyCount);
  }
  if (lastBatchCount > 0) {
    return `0 sucios · último batch ${lastBatchCount}`;
  }
  return "0";
}

function buildCurrentDiffIndicator(worktree) {
  const dirtyCount = Number(worktree?.dirty_files_count || worktree?.changed_files?.length || 0);
  if (dirtyCount > 0) {
    return formatDiffIndicator(worktree?.dirty_insertions, worktree?.dirty_deletions);
  }
  const batch = worktree?.last_committed_batch;
  if (batch) {
    return formatDiffIndicator(batch.insertions, batch.deletions, "último batch");
  }
  return "sin diff";
}

function renderChangeList(items, emptyLabel) {
  if (!items?.length) {
    return `<ul class="plain-list"><li>${escapeHtml(emptyLabel)}</li></ul>`;
  }
  return `
    <ul class="plain-list">
      ${items
        .map((file) => `<li><code>${escapeHtml(file.status)}</code> ${escapeHtml(file.path)}</li>`)
        .join("")}
    </ul>
  `;
}

function renderDisclosure(title, indicator, body) {
  return `
    <details class="runtime-disclosure">
      <summary>
        <div class="disclosure-title-row">
          <span>${escapeHtml(title)}</span>
          <span class="chip disclosure-indicator">${escapeHtml(indicator)}</span>
        </div>
      </summary>
      <div class="disclosure-body">${body}</div>
    </details>
  `;
}

function buildTaskMap(tasks) {
  return new Map((tasks || []).map((task) => [task.key, task]));
}

function findCurrentTask(mission) {
  const taskMap = buildTaskMap(mission?.execution_tasks || []);
  const activeKey = mission?.active_run?.current_task_key;
  if (activeKey && taskMap.has(activeKey)) {
    return taskMap.get(activeKey);
  }
  return (
    mission?.execution_tasks?.find((task) => task.status === "running") ||
    mission?.execution_tasks?.find((task) => task.status === "ready") ||
    mission?.execution_tasks?.find((task) => task.status === "queued") ||
    mission?.execution_tasks?.[0] ||
    null
  );
}

function latestCommandForRun(logsView, runId) {
  return logsView?.commands?.find((command) => command.run_id === runId) || null;
}

function representativeTaskForRun(taskMap, run, logsView) {
  if (run?.current_task_key && taskMap.has(run.current_task_key)) {
    return taskMap.get(run.current_task_key);
  }
  const command = latestCommandForRun(logsView, run?.id);
  if (command?.task_key && taskMap.has(command.task_key)) {
    return taskMap.get(command.task_key);
  }
  return null;
}

function renderQueue(items) {
  const target = document.getElementById("queue-list");
  target.innerHTML = "";
  if (!items.length) {
    target.innerHTML = '<p class="empty">Todavía no hay misiones. Creá una desde la API o usando el botón demo.</p>';
    return;
  }

  items.forEach((item) => {
    const owner = resolveProfile(item.current_owner || "planner");
    const repoScope = item.linked_repositories.length ? item.linked_repositories.join(", ") : "greenfield";
    const runtime = item.runtime_state ? `Ejecución: ${STATUS_LABELS[safeStatusClass(item.runtime_state)] || item.runtime_state}` : "Ejecución: inactiva";
    const branch = item.branch_name ? `Rama: ${item.branch_name}` : "Rama: todavía no creada";
    const task = item.active_task_key ? `Tarea: ${item.active_task_key}` : "Tarea: sin ejecución";
    target.insertAdjacentHTML(
      "beforeend",
      `
        <article class="card">
          <div class="card-head">
            <strong>${escapeHtml(item.mission_type)}</strong>
            <span class="pill">${escapeHtml(item.policy)}</span>
          </div>
          <div class="identity-row">
            ${iconMarkup(owner)}
            <div class="title-stack">
              <strong>${escapeHtml(owner.label)}</strong>
              <span class="card-kicker">Owner actual</span>
            </div>
          </div>
          <p class="card-copy">Siguiente paso: ${escapeHtml(item.next_step)}</p>
          <p class="card-meta">Alcance: ${escapeHtml(repoScope)}</p>
          <p class="card-meta">${escapeHtml(runtime)}</p>
          <p class="card-meta">${escapeHtml(branch)}</p>
          <p class="card-meta">${escapeHtml(task)}</p>
          <p class="card-meta">Archivos cambiados: ${escapeHtml(item.changed_files_count)}</p>
          <p class="card-meta">${escapeHtml(item.worktree_note || "El worktree ya tiene cambios o trabajo previamente commiteado.")}</p>
          <div class="button-row">
            <button data-action="run" data-mission-id="${escapeHtml(item.mission_id)}">Correr</button>
            <button class="secondary" data-action="resume" data-mission-id="${escapeHtml(item.mission_id)}">Reanudar</button>
            <button class="ghost" data-action="interrupt" data-mission-id="${escapeHtml(item.mission_id)}">Interrumpir</button>
          </div>
        </article>
      `
    );
  });
}

function renderRuns(mission, logsView) {
  const target = document.getElementById("run-list");
  target.innerHTML = "";
  if (!mission || !logsView?.runs?.length) {
    target.innerHTML = '<p class="empty">Todavía no hay runs para la misión enfocada.</p>';
    return;
  }

  const taskMap = buildTaskMap(mission.execution_tasks);
  logsView.runs.slice(0, 3).forEach((run) => {
    const task = representativeTaskForRun(taskMap, run, logsView);
    const profile = resolveProfile(task?.agent_profile_slug || "");
    const summary = task?.title || run.current_task_key || "Shell del runtime";
    target.insertAdjacentHTML(
      "beforeend",
      `
        <article class="card runtime-card">
          <div class="card-head">
            <div class="identity-row">
              ${iconMarkup(profile)}
              <div class="title-stack">
                <strong>${escapeHtml(summary)}</strong>
                <span class="card-kicker">${escapeHtml(profile.label)}</span>
              </div>
            </div>
            ${statusPill(run.status)}
          </div>
          <p class="card-meta">Run: ${escapeHtml(run.id.slice(0, 8))}</p>
          <p class="card-meta">Inicio: ${escapeHtml(formatDateTime(run.started_at || run.created_at))}</p>
          <p class="card-meta">Fin: ${escapeHtml(formatDateTime(run.completed_at))}</p>
        </article>
      `
    );
  });
}

function renderLogs(mission, logsView) {
  const target = document.getElementById("logs-list");
  target.innerHTML = "";
  if (!mission || !logsView?.commands?.length) {
    target.innerHTML = '<p class="empty">Todavía no hay comandos ejecutados para la misión enfocada.</p>';
    return;
  }

  const taskMap = buildTaskMap(mission.execution_tasks);
  logsView.commands.slice(0, 4).forEach((item) => {
    const task = taskMap.get(item.task_key);
    const profile = resolveProfile(task?.agent_profile_slug || "");
    const commandLabel = truncate(item.command, 82);
    target.insertAdjacentHTML(
      "beforeend",
      `
        <article class="card runtime-card command-card">
          <div class="command-head">
            <div class="identity-row">
              ${iconMarkup(profile)}
              <div class="title-stack">
                <strong>${escapeHtml(task?.title || item.task_key)}</strong>
                <span class="card-kicker">${escapeHtml(profile.label)}</span>
              </div>
            </div>
            ${statusPill(item.status)}
          </div>
          <p class="command-line" title="${escapeHtml(item.command)}">${escapeHtml(commandLabel)}</p>
          <div class="command-meta-row">
            <span class="command-chip">${escapeHtml(commandKindLabel(item.kind))}</span>
            <span class="command-chip">Exit: ${escapeHtml(item.exit_code ?? "en curso")}</span>
            <span class="command-chip">Log: ${escapeHtml(basenamePath(item.log_path))}</span>
          </div>
        </article>
      `
    );
  });
}

function buildRuntimeGraph(tasks, activeTaskKey) {
  if (!tasks?.length) {
    return '<p class="empty">No hay tareas de ejecución planificadas para esta misión.</p>';
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
    <div class="flow-board" role="img" aria-label="Camino de ejecución del runtime distribuido por etapas">
      ${columns
        .map((column, columnIndex) => {
          const stagesMarkup = column
            .map((task) => {
              const profile = resolveProfile(task.agent_profile_slug);
              const scope = task.repo_scope?.length ? task.repo_scope.join(", ") : task.surface;
              const dependencies = (task.depends_on || [])
                .filter((dependency) => taskMap.has(dependency))
                .map((dependency) => {
                  const relatedTask = taskMap.get(dependency);
                  return `<span class="flow-chip">${escapeHtml(truncate(relatedTask?.title || dependency, 24))}</span>`;
                })
                .join("");
              const statusClass = safeStatusClass(task.status);
              const activeClass = task.key === activeTaskKey ? " flow-card-active" : "";
              return `
                <article class="flow-card status-${statusClass}${activeClass}">
                  <div class="flow-card-head">
                    <div class="identity-row">
                      ${iconMarkup(profile)}
                      <div class="title-stack">
                        <strong>${escapeHtml(task.title)}</strong>
                        <span class="card-kicker">${escapeHtml(profile.label)}</span>
                      </div>
                    </div>
                    ${statusPill(task.status)}
                  </div>
                  <p class="card-meta">Alcance: ${escapeHtml(scope)}</p>
                  ${
                    dependencies
                      ? `<div class="flow-chip-row">${dependencies}</div>`
                      : '<p class="flow-start">Inicia este tramo de la ejecución.</p>'
                  }
                </article>
              `;
            })
            .join("");

          return `
            <div class="flow-step">
              <div class="flow-step-head">
                <span class="flow-stage-label">Etapa ${columnIndex + 1}</span>
                <span class="flow-stage-meta">${escapeHtml(column.length)} ${pluralize(column.length, "tarea")}</span>
              </div>
              <div class="flow-step-body">
                ${stagesMarkup}
              </div>
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

function renderFocusedRuntime(mission) {
  const target = document.getElementById("focused-runtime");
  target.innerHTML = "";
  if (!mission) {
    target.innerHTML = '<p class="empty">Todavía no hay una misión enfocada.</p>';
    return;
  }

  const currentTask = findCurrentTask(mission);
  const currentProfile = resolveProfile(currentTask?.agent_profile_slug || "planner");
  const worktree = mission.worktree_snapshot;
  const lastBatch = worktree?.last_committed_batch;
  const lastCommand = mission.active_run?.last_command;
  const completedTasks = mission.execution_tasks.filter((task) => task.status === "completed").length;
  const activeTasks = mission.execution_tasks.filter((task) => task.status === "running").length;
  const remainingTasks = mission.execution_tasks.length - completedTasks - activeTasks;
  const changedFilesMarkup = worktree?.dirty_files_count
    ? renderChangeList(worktree.changed_files, "Todavía no hay cambios de archivos.")
    : lastBatch
      ? renderChangeList(lastBatch.changed_files, "El último batch commiteado no trajo nombres de archivo.")
      : renderChangeList([], "Todavía no hay cambios de archivos.");
  const diffStat = worktree?.dirty_files_count
    ? worktree?.diff_stat
    : lastBatch?.diff_stat;
  const diffStatMarkup = diffStat
    ? `<pre class="log-block">${escapeHtml(diffStat)}</pre>`
    : '<p class="card-meta">Todavía no hay diff disponible.</p>';
  const changedFilesDisclosure = renderDisclosure(
    "Archivos cambiados",
    buildChangedFilesIndicator(worktree),
    changedFilesMarkup
  );
  const diffDisclosure = renderDisclosure(
    "Diff actual",
    buildCurrentDiffIndicator(worktree),
    diffStatMarkup
  );
  const checklistMarkup = mission.execution_tasks?.length
    ? mission.execution_tasks
        .map((task) => {
          const profile = resolveProfile(task.agent_profile_slug);
          return `
            <li class="task-row">
              <div class="identity-row">
                ${iconMarkup(profile)}
                <div class="title-stack">
                  <strong>${escapeHtml(task.title)}</strong>
                  <span class="card-kicker">${escapeHtml(profile.label)}</span>
                </div>
              </div>
              ${statusPill(task.status)}
            </li>
          `;
        })
        .join("")
    : '<p class="empty">No hay tareas planificadas para la misión enfocada.</p>';

  target.innerHTML = `
    <section class="runtime-subpanel runtime-subpanel-wide">
      <div class="subpanel-head">
        <h3>Camino de ejecución</h3>
        <span class="card-kicker">Cada etapa se lee de arriba hacia abajo. La tarea activa queda resaltada.</span>
      </div>
      <div class="graph-scroll">
        ${buildRuntimeGraph(mission.execution_tasks, currentTask?.key)}
      </div>
    </section>

    <article class="card runtime-focus-card">
      <div class="card-head">
        <div class="identity-row identity-row-large">
          ${iconMarkup(currentProfile, { className: "agent-icon agent-icon-large" })}
          <div class="title-stack">
            <strong>${escapeHtml(currentProfile.label)}</strong>
            <span class="card-kicker">Owner activo</span>
          </div>
        </div>
        ${statusPill(mission.active_run?.status || mission.status)}
      </div>
      <p class="card-copy">${escapeHtml(currentTask?.title || mission.spec.summary)}</p>
      <div class="summary-grid">
        <p class="card-meta">Clave de tarea: ${escapeHtml(currentTask?.key || "sin programar")}</p>
        <p class="card-meta">Misión: ${escapeHtml(mission.id.slice(0, 8))}</p>
        <p class="card-meta">Destino de merge: ${escapeHtml(mission.spec.merge_target || "sin declarar")}</p>
        <p class="card-meta">Destinos de deploy: ${escapeHtml(formatList(mission.spec.deploy_targets, "ninguno"))}</p>
        <p class="card-meta">Rama: ${escapeHtml(worktree?.branch_name || mission.active_run?.branch_name || "todavía no creada")}</p>
        <p class="card-meta">Worktree: ${escapeHtml(worktree?.worktree_path || mission.active_run?.worktree_path || "todavía no creado")}</p>
        <p class="card-meta emphasis">HEAD: ${escapeHtml(worktree?.head_summary || lastBatch?.commit_subject || "todavía sin commit")}</p>
        <p class="card-meta">Último batch: ${escapeHtml(lastBatch?.commit_sha ? `${lastBatch.commit_sha.slice(0, 12)} · ${lastBatch.commit_subject || "commiteado"}` : "todavía no hay")}</p>
        <p class="card-meta summary-row-wide">Comando actual: ${escapeHtml(lastCommand ? truncate(lastCommand.command, 120) : "sin comandos todavía")}</p>
      </div>
    </article>

    <div class="runtime-panels">
      <section class="runtime-subpanel">
        <div class="subpanel-head">
          <h3>Progreso de la misión</h3>
          <span class="card-kicker">Checklist compacto de tareas</span>
        </div>
        <div class="progress-strip">
          <div class="progress-metric">
            <strong>${escapeHtml(completedTasks)}</strong>
            <span>Completadas</span>
          </div>
          <div class="progress-metric">
            <strong>${escapeHtml(activeTasks)}</strong>
            <span>Activas</span>
          </div>
          <div class="progress-metric">
            <strong>${escapeHtml(Math.max(remainingTasks, 0))}</strong>
            <span>Pendientes</span>
          </div>
        </div>
        <ul class="task-checklist">${checklistMarkup}</ul>
      </section>

      <section class="runtime-subpanel">
        <div class="subpanel-head">
          <h3>Qué está cambiando ahora</h3>
          <span class="card-kicker">${escapeHtml(worktree?.note || "Cambios de archivos visibles ahora mismo para el runtime.")}</span>
        </div>
        <div class="stack">
          <div class="runtime-subpanel runtime-subpanel-nested">
            ${changedFilesDisclosure}
          </div>
          <div class="runtime-subpanel runtime-subpanel-nested">
            ${diffDisclosure}
          </div>
        </div>
      </section>
    </div>
  `;
}

function renderMap(graph) {
  document.getElementById("metric-nodes").textContent = graph.nodes.length;
  document.getElementById("metric-repositories").textContent = graph.counts.Repository || 0;

  const countsTarget = document.getElementById("map-counts");
  countsTarget.innerHTML = "";
  Object.entries(graph.counts).forEach(([key, value]) => {
    countsTarget.insertAdjacentHTML(
      "beforeend",
      `<span class="chip">${escapeHtml(key)}: ${escapeHtml(value)}</span>`
    );
  });

  const nodeTarget = document.getElementById("node-list");
  nodeTarget.innerHTML = "";
  graph.nodes.slice(0, 18).forEach((node) => {
    nodeTarget.insertAdjacentHTML(
      "beforeend",
      `<div class="list-item"><strong>${escapeHtml(node.kind)}</strong><span>${escapeHtml(node.name)}</span></div>`
    );
  });

  const edgeTarget = document.getElementById("edge-list");
  edgeTarget.innerHTML = "";
  graph.edges.slice(0, 18).forEach((edge) => {
    edgeTarget.insertAdjacentHTML(
      "beforeend",
      `<div class="list-item"><strong>${escapeHtml(edge.relation)}</strong><span>${escapeHtml(edge.source_key)} → ${escapeHtml(edge.target_key)}</span></div>`
    );
  });
}

async function refreshDashboard() {
  if (refreshInFlight) {
    return;
  }
  refreshInFlight = true;
  try {
    await ensureIconSprite();
    const snapshot = await fetchJson("/api/dashboard");
    document.getElementById("metric-missions").textContent = snapshot.queue.length;
    renderQueue(snapshot.queue);
    renderMap(snapshot.map);

    if (snapshot.focused_mission_id) {
      const [mission, logsView] = await Promise.all([
        fetchJson(`/api/missions/${snapshot.focused_mission_id}`),
        fetchJson(`/api/missions/${snapshot.focused_mission_id}/logs`),
      ]);
      renderFocusedRuntime(mission);
      renderRuns(mission, logsView);
      renderLogs(mission, logsView);
      return;
    }

    renderFocusedRuntime(null);
    renderRuns(null, null);
    renderLogs(null, null);
  } catch (error) {
    console.error(error);
  } finally {
    refreshInFlight = false;
  }
}

async function postMissionAction(missionId, action) {
  await fetchJson(`/api/missions/${missionId}/${action}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
  });
  await refreshDashboard();
}

async function createDemoMission() {
  await fetchJson("/api/missions", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      brief: "Dashboard interno greenfield que coordina repos frontend y backend para una nueva iniciativa operativa.",
      desired_outcome: "Bootstrapear un shell inicial del proyecto, elegir un template de stack y preparar la primera ola de implementación.",
      linked_products: ["Demo de Autonomía"],
      policy: "safe",
    }),
  });
  await refreshDashboard();
}

async function discoverLocal() {
  await fetchJson("/api/discovery/local", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ max_depth: 1 }),
  });
  await refreshDashboard();
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("seed-demo").addEventListener("click", () => {
    createDemoMission().catch(console.error);
  });
  document.getElementById("discover-local").addEventListener("click", () => {
    discoverLocal().catch(console.error);
  });
  document.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) {
      return;
    }
    postMissionAction(button.dataset.missionId, button.dataset.action).catch(console.error);
  });

  refreshDashboard().catch(console.error);
  setInterval(() => {
    refreshDashboard().catch(console.error);
  }, 15000);
});
