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

export const STATUS_LABELS = {
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
  skipped: "omitida",
  idle: "inactiva",
};

export const COMMAND_KIND_LABELS = {
  codex: "Codex",
  git: "Git",
  verify: "Chequeo",
  shell: "Shell",
  firebase: "Firebase",
  "android-build": "Android",
};

let iconSpritePromise = null;

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function truncate(value, maxLength = 48) {
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

export function resolveProfile(value) {
  const normalized = normalizeProfileKey(value);
  const canonical = PROFILE_ALIASES[normalized] || normalized;
  const profile = PROFILE_DEFINITIONS[canonical];

  if (profile) {
    return { slug: canonical, ...profile };
  }

  return {
    slug: canonical || "unknown",
    label: String(value || "Perfil desconocido"),
    icon: "placeholder",
  };
}

export async function ensureIconSprite() {
  if (!iconSpritePromise) {
    iconSpritePromise = (async () => {
      if (document.getElementById("icon-sprite-store")) {
        return;
      }

      const response = await fetch("/static/lucide-sprite.svg");
      if (!response.ok) {
        throw new Error("No pude cargar el set de íconos del dashboard.");
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

export function iconMarkup(profileValue, options = {}) {
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

export function safeStatusClass(value) {
  return String(value ?? "unknown").toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

export function statusLabel(value) {
  const normalized = safeStatusClass(value);
  return STATUS_LABELS[normalized] || String(value || "sin dato");
}

export function statusPill(status) {
  const normalized = safeStatusClass(status);
  return `<span class="status-pill status-${normalized}">${escapeHtml(statusLabel(status))}</span>`;
}

export function formatDateTime(value) {
  if (!value) {
    return "sin dato";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

export function formatClock(value) {
  if (!value) {
    return "pendiente";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

export function formatList(values, fallback = "ninguno") {
  return values?.length ? values.join(", ") : fallback;
}

export function pluralize(value, singular, plural = `${singular}s`) {
  return value === 1 ? singular : plural;
}

export function commandKindLabel(value) {
  return COMMAND_KIND_LABELS[value] || String(value || "Shell");
}

export function basenamePath(value) {
  const text = String(value || "");
  if (!text) {
    return "n/a";
  }

  const pieces = text.split("/");
  return pieces[pieces.length - 1] || text;
}

export function formatDiffIndicator(insertions = 0, deletions = 0, prefix = "") {
  const label = `+${insertions || 0} / -${deletions || 0}`;
  return prefix ? `${prefix} ${label}` : label;
}

export function buildChangedFilesIndicator(worktree) {
  const dirtyCount = Number(worktree?.dirty_files_count || worktree?.changed_files?.length || 0);
  const lastBatchCount = Number(worktree?.last_committed_batch?.files_count || 0);

  if (dirtyCount > 0) {
    return String(dirtyCount);
  }

  if (lastBatchCount > 0) {
    return `último batch ${lastBatchCount}`;
  }

  return "0";
}

export function buildCurrentDiffIndicator(worktree) {
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

export function formatBudgetLabel(mission) {
  const limit = mission?.execution_controls?.max_runtime_hours;
  const elapsed = Number(mission?.runtime_budget_elapsed_hours || 0);

  if (!limit) {
    return "Sin límite";
  }

  return `${elapsed.toFixed(1)}h / ${limit}h`;
}

export function canToggleDeploy(mission) {
  return Boolean(mission?.execution_tasks?.some((task) => task.key === "deploy"));
}

export function relativeTimeFromNow(value) {
  if (!value) {
    return "sin señal";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  const diffMs = Math.max(0, Date.now() - date.getTime());
  const diffSeconds = Math.round(diffMs / 1000);

  if (diffSeconds < 60) {
    return `hace ${diffSeconds}s`;
  }

  const diffMinutes = Math.round(diffSeconds / 60);
  if (diffMinutes < 60) {
    return `hace ${diffMinutes}m`;
  }

  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) {
    return `hace ${diffHours}h`;
  }

  const diffDays = Math.round(diffHours / 24);
  return `hace ${diffDays}d`;
}

export function activityAgeMs(value) {
  if (!value) {
    return null;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return Math.max(0, Date.now() - date.getTime());
}

export function taskScope(task) {
  return task?.repo_scope?.length ? task.repo_scope.join(", ") : task?.surface || "sin alcance";
}

export function renderChangeList(items, emptyLabel) {
  if (!items?.length) {
    return `<ul class="plain-list"><li>${escapeHtml(emptyLabel)}</li></ul>`;
  }

  return `
    <ul class="plain-list">
      ${items
        .map((file) => `<li><code translate="no">${escapeHtml(file.status)}</code> ${escapeHtml(file.path)}</li>`)
        .join("")}
    </ul>
  `;
}

export function renderDisclosure(title, indicator, body, options = {}) {
  const { open = false } = options;

  return `
    <details class="detail-disclosure" ${open ? "open" : ""}>
      <summary>
        <span>${escapeHtml(title)}</span>
        <span class="summary-indicator">${escapeHtml(indicator)}</span>
      </summary>
      <div class="detail-disclosure-body">${body}</div>
    </details>
  `;
}

export function renderPanelState(type, title, body, actions = "") {
  return `
    <article class="panel-state panel-state-${safeStatusClass(type)}">
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(body)}</p>
      ${actions}
    </article>
  `;
}

export function renderActionButton({ action, missionId, label, busy = false, className = "" }) {
  const busyLabel = {
    run: "Corriendo…",
    resume: "Reanudando…",
    interrupt: "Interrumpiendo…",
  }[action] || label;

  return `
    <button
      type="button"
      class="${className}"
      data-action="${escapeHtml(action)}"
      data-mission-id="${escapeHtml(missionId)}"
      data-focus-id="action:${escapeHtml(action)}:${escapeHtml(missionId)}"
      ${busy ? 'aria-busy="true" disabled' : ""}
    >
      ${escapeHtml(busy ? busyLabel : label)}
    </button>
  `;
}

export function buildTaskMap(tasks) {
  return new Map((tasks || []).map((task) => [task.key, task]));
}

export function findCurrentTask(mission) {
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

export function latestCommandForRun(logsView, runId) {
  return logsView?.commands?.find((command) => command.run_id === runId) || null;
}

export function representativeTaskForRun(taskMap, run, logsView) {
  if (run?.current_task_key && taskMap.has(run.current_task_key)) {
    return taskMap.get(run.current_task_key);
  }

  const command = latestCommandForRun(logsView, run?.id);
  if (command?.task_key && taskMap.has(command.task_key)) {
    return taskMap.get(command.task_key);
  }

  return null;
}

export function parseAppError(error) {
  if (!error) {
    return "Error desconocido.";
  }

  return error.message || String(error);
}

export function filteredGraphForMission(graph, mission) {
  if (!graph || !mission) {
    return null;
  }

  const missionKey = `mission:${mission.id}`;
  const relevantKeys = new Set([missionKey]);
  let expanded = true;

  while (expanded) {
    expanded = false;

    for (const edge of graph.edges || []) {
      if (edge.source_key === missionKey || edge.target_key === missionKey) {
        relevantKeys.add(edge.source_key);
        relevantKeys.add(edge.target_key);
      }

      if (relevantKeys.has(edge.source_key) || relevantKeys.has(edge.target_key)) {
        const before = relevantKeys.size;
        relevantKeys.add(edge.source_key);
        relevantKeys.add(edge.target_key);
        if (relevantKeys.size !== before) {
          expanded = true;
        }
      }
    }
  }

  const nodes = (graph.nodes || []).filter((node) => {
    return relevantKeys.has(node.node_key) && node.kind.toLowerCase() !== "agentprofile";
  });
  const edges = (graph.edges || []).filter((edge) => {
    return relevantKeys.has(edge.source_key) && relevantKeys.has(edge.target_key);
  });
  const counts = {};

  for (const node of nodes) {
    counts[node.kind] = (counts[node.kind] || 0) + 1;
  }

  return { counts, nodes, edges };
}

export function repositoryCount(graph) {
  return (graph?.nodes || []).filter((node) => node.kind.toLowerCase() === "repository").length;
}

export function missionQueueItem(queue, missionId) {
  return queue?.find((item) => item.mission_id === missionId) || null;
}

export function resolveSelectedMissionId(queue, snapshotFocusedId, currentMissionId) {
  const missionIds = new Set((queue || []).map((item) => item.mission_id));

  if (currentMissionId && missionIds.has(currentMissionId)) {
    return currentMissionId;
  }

  if (snapshotFocusedId && missionIds.has(snapshotFocusedId)) {
    return snapshotFocusedId;
  }

  return queue?.[0]?.mission_id || null;
}

export function missionProgress(mission) {
  const tasks = mission?.execution_tasks || [];
  return {
    total: tasks.length,
    active: tasks.filter((task) => task.status === "running").length,
    closed: tasks.filter((task) => ["completed", "failed", "skipped"].includes(task.status)).length,
    remaining: tasks.filter((task) => ["ready", "queued", "blocked"].includes(task.status)).length,
  };
}

export function describeMissionHealth(mission) {
  if (!mission) {
    return {
      tone: "neutral",
      label: "Sin foco",
      title: "Esperando una misión activa",
      body: "Elegí una misión de la cola para ver el pulso operativo.",
      detail: "Sin señales todavía.",
      activityLabel: "sin señal",
    };
  }

  const run = mission.active_run;
  const currentTask = findCurrentTask(mission);
  const failedTask = (mission.execution_tasks || []).find((task) => task.status === "failed");
  const command = run?.last_command || null;
  const activityAt =
    command?.activity_at ||
    command?.updated_at ||
    run?.last_heartbeat_at ||
    run?.updated_at ||
    mission.updated_at;
  const ageMs = activityAgeMs(activityAt);
  const currentTaskLabel = currentTask?.title || mission.spec?.summary || "Sin tarea activa";

  if (mission.status === "failed" || run?.status === "failed" || command?.status === "failed" || failedTask) {
    return {
      tone: "danger",
      label: "Fallida",
      title: "Requiere intervención",
      body:
        run?.last_error ||
        command?.summary ||
        (failedTask ? `Falló la tarea ${failedTask.title}.` : "El runtime terminó con error."),
      detail: "Revisá logs y estado del worktree antes de reanudar.",
      activityLabel: activityAt ? relativeTimeFromNow(activityAt) : "sin señal",
    };
  }

  if (mission.status === "interrupted" || run?.status === "interrupted") {
    return {
      tone: "warning",
      label: "Interrumpida",
      title: "Pausa manual requerida",
      body: run?.last_error || "El runtime quedó detenido y necesita un resume explícito.",
      detail: "No va a avanzar hasta que alguien lo reanude.",
      activityLabel: activityAt ? relativeTimeFromNow(activityAt) : "sin señal",
    };
  }

  if (mission.runtime_budget_reached) {
    return {
      tone: "warning",
      label: "Límite alcanzado",
      title: "Freno por budget",
      body: "La misión consumió el límite horario configurado.",
      detail: "Ajustá controles o relanzala cuando quieras continuar.",
      activityLabel: activityAt ? relativeTimeFromNow(activityAt) : "sin señal",
    };
  }

  if (mission.status === "completed") {
    return {
      tone: "success",
      label: "Completada",
      title: "Cierre operativo correcto",
      body: "La misión terminó según la policy configurada.",
      detail: "Podés revisar artifacts, branch y estado final del worktree.",
      activityLabel: activityAt ? relativeTimeFromNow(activityAt) : "sin señal",
    };
  }

  if (run && ["running", "verifying", "releasing"].includes(run.status)) {
    if (command?.status === "running" && ageMs !== null && ageMs <= 3 * 60 * 1000) {
      return {
        tone: "success",
        label: "Trabajando",
        title: "El runtime viene sano",
        body: `Tarea actual: ${currentTaskLabel}.`,
        detail: "Hay actividad reciente en el comando activo.",
        activityLabel: relativeTimeFromNow(activityAt),
      };
    }

    if (command?.status === "running" && ageMs !== null && ageMs <= 12 * 60 * 1000) {
      return {
        tone: "warning",
        label: "Silenciosa",
        title: "Sigue corriendo, pero quieta",
        body: `Tarea actual: ${currentTaskLabel}.`,
        detail: "Conviene vigilar el log antes de asumir que falló.",
        activityLabel: relativeTimeFromNow(activityAt),
      };
    }

    return {
      tone: "neutral",
      label: "Preparando",
      title: "Transición de etapa",
      body: `Tarea actual: ${currentTaskLabel}.`,
      detail: "El run sigue abierto aunque todavía no haya una señal fuerte.",
      activityLabel: activityAt ? relativeTimeFromNow(activityAt) : "sin señal",
    };
  }

  if (!run && currentTask?.status === "blocked") {
    return {
      tone: "warning",
      label: "Bloqueada",
      title: "Pendiente de destrabar",
      body: currentTask.title,
      detail: "Hay dependencias o criterios pendientes antes de correr.",
      activityLabel: activityAt ? relativeTimeFromNow(activityAt) : "sin señal",
    };
  }

  return {
    tone: "neutral",
    label: mission.status === "planned" ? "Planificada" : "En espera",
    title: "Lista para tomar acción",
    body: `Próximo foco: ${currentTaskLabel}.`,
    detail: "Todavía no hay ejecución activa.",
    activityLabel: activityAt ? relativeTimeFromNow(activityAt) : "sin señal",
  };
}
