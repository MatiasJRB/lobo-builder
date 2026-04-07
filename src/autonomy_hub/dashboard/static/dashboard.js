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
  skipped: "omitida",
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

const SECTION_LABELS = {
  runtime: "Runtime",
  logs: "Logs",
  graph: "Grafo",
};

const SECTION_DESCRIPTIONS = {
  runtime: "Controles, board, worktree y camino de ejecución.",
  logs: "Runs recientes y comandos del runtime enfocado.",
  graph: "Contexto filtrado de la misión y sus relaciones.",
};

const VALID_SECTIONS = new Set(Object.keys(SECTION_LABELS));
const REFRESH_INTERVAL_MS = 15000;

const APP_STATE = {
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
};

let iconSpritePromise = null;
let refreshInFlight = false;
let refreshTimerId = null;

async function fetchJson(path, options) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  let payload = null;

  if (contentType.includes("application/json")) {
    payload = await response.json().catch(() => null);
  } else {
    payload = await response.text().catch(() => null);
  }

  if (!response.ok) {
    const message =
      payload?.detail ||
      payload?.message ||
      (typeof payload === "string" && payload.trim()) ||
      `Request failed: ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return payload;
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
    label: String(value || "Perfil desconocido"),
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
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

function formatClock(value) {
  if (!value) {
    return "sin dato";
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

function formatBudgetLabel(mission) {
  const limit = mission?.execution_controls?.max_runtime_hours;
  const elapsed = Number(mission?.runtime_budget_elapsed_hours || 0);
  if (!limit) {
    return "Sin límite";
  }
  return `${elapsed.toFixed(1)}h / ${limit}h`;
}

function canToggleDeploy(mission) {
  return Boolean(mission?.execution_tasks?.some((task) => task.key === "deploy"));
}

function relativeTimeFromNow(value) {
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

function activityAgeMs(value) {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return Math.max(0, Date.now() - date.getTime());
}

function taskScope(task) {
  return task?.repo_scope?.length ? task.repo_scope.join(", ") : task?.surface || "sin alcance";
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

function renderDisclosure(title, indicator, body, options = {}) {
  const { open = false } = options;
  return `
    <details class="runtime-disclosure" ${open ? "open" : ""}>
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

function parseAppError(error) {
  if (!error) {
    return "Error desconocido.";
  }
  return error.message || String(error);
}

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

function setBanner(tone, message) {
  APP_STATE.flash = { tone, message };
  announce(message);
}

function clearBanner() {
  APP_STATE.flash = null;
}

function actionKey(kind, missionId = "") {
  return missionId ? `${kind}:${missionId}` : kind;
}

function isPending(key) {
  return APP_STATE.pendingAction === key;
}

function isValidSection(section) {
  return VALID_SECTIONS.has(section);
}

function readUrlState() {
  const params = new URLSearchParams(window.location.search);
  const missionId = params.get("mission");
  const section = params.get("section");
  return {
    missionId: missionId || null,
    section: isValidSection(section) ? section : "runtime",
  };
}

function syncUrlState({ replace = true } = {}) {
  const params = new URLSearchParams(window.location.search);
  if (APP_STATE.selectedMissionId) {
    params.set("mission", APP_STATE.selectedMissionId);
  } else {
    params.delete("mission");
  }

  if (APP_STATE.selectedSection && APP_STATE.selectedSection !== "runtime") {
    params.set("section", APP_STATE.selectedSection);
  } else {
    params.delete("section");
  }

  const nextUrl = `${window.location.pathname}${params.toString() ? `?${params}` : ""}`;
  const method = replace ? "replaceState" : "pushState";
  window.history[method]({}, "", nextUrl);
}

function missionPulseState(mission) {
  if (!mission) {
    return {
      tone: "neutral",
      label: "Sin foco",
      title: "Todavía no hay una misión enfocada",
      body: "Cuando el planner seleccione una misión, este bloque va a resumir si está sana, bloqueada o fallida.",
      activityLabel: "sin señales",
      activityDetail: "Esperando una misión activa.",
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
  const defaultDetail = `Tarea actual: ${currentTaskLabel}.`;

  if (mission.status === "failed" || run?.status === "failed" || command?.status === "failed" || failedTask) {
    return {
      tone: "danger",
      label: "Fallida",
      title: "La misión quedó fallida",
      body:
        run?.last_error ||
        command?.summary ||
        (failedTask ? `Falló la tarea ${failedTask.title}.` : "Revisá logs y artifacts para retomar."),
      activityLabel: activityAt ? relativeTimeFromNow(activityAt) : "sin señal",
      activityDetail: "Necesita intervención manual antes de seguir.",
    };
  }

  if (mission.status === "interrupted" || run?.status === "interrupted") {
    return {
      tone: "warning",
      label: "Interrumpida",
      title: "La misión se interrumpió",
      body: run?.last_error || "El runtime quedó pausado y necesita un resume manual.",
      activityLabel: activityAt ? relativeTimeFromNow(activityAt) : "sin señal",
      activityDetail: "No está avanzando hasta que la reanudes.",
    };
  }

  if (mission.runtime_budget_reached) {
    return {
      tone: "warning",
      label: "Límite alcanzado",
      title: "La misión consumió el budget configurado",
      body: "Quedó detenida de forma controlada. Ajustá los controles o relanzala cuando quieras seguir.",
      activityLabel: activityAt ? relativeTimeFromNow(activityAt) : "sin señal",
      activityDetail: "El freno vino por controls, no por un fallo técnico.",
    };
  }

  if (mission.status === "completed") {
    return {
      tone: "success",
      label: "Completada",
      title: "La misión terminó bien",
      body: "Verify, release y deploy ya cerraron su tramo o quedaron resueltos según la policy.",
      activityLabel: activityAt ? relativeTimeFromNow(activityAt) : "sin señal",
      activityDetail: "Podés revisar artifacts y el estado final del worktree.",
    };
  }

  if (run && ["running", "verifying", "releasing"].includes(run.status)) {
    if (command?.status === "running") {
      if (!command?.activity_at) {
        return {
          tone: "success",
          label: "Trabajando",
          title: "La misión tiene un comando activo",
          body: defaultDetail,
          activityLabel: "comando en curso",
          activityDetail: "Mientras el run siga vivo, este pulso lo considera sano salvo que cambie a failed o interrupted.",
        };
      }
      if (ageMs !== null && ageMs <= 3 * 60 * 1000) {
        return {
          tone: "success",
          label: "Trabajando",
          title: "La misión está avanzando bien",
          body: defaultDetail,
          activityLabel: relativeTimeFromNow(activityAt),
          activityDetail: "Hay actividad reciente en el comando activo.",
        };
      }
      if (ageMs !== null && ageMs <= 12 * 60 * 1000) {
        return {
          tone: "warning",
          label: "Silenciosa",
          title: "La misión sigue corriendo, pero viene quieta",
          body: defaultDetail,
          activityLabel: relativeTimeFromNow(activityAt),
          activityDetail: "Todavía no parece fallida, pero conviene vigilarla.",
        };
      }
      return {
        tone: "danger",
        label: "Sin señales",
        title: "Posible cuelgue o comando estancado",
        body: defaultDetail,
        activityLabel: activityAt ? relativeTimeFromNow(activityAt) : "sin señal",
        activityDetail: "Si este estado no cambia por varios minutos, revisá el log del task activo.",
      };
    }

    return {
      tone: "neutral",
      label: "Preparando",
      title: "La misión está inicializando o cambiando de etapa",
      body: defaultDetail,
      activityLabel: activityAt ? relativeTimeFromNow(activityAt) : "sin señal",
      activityDetail: "El runtime sigue abierto aunque todavía no haya un comando vivo claro.",
    };
  }

  if (!run && currentTask?.status === "blocked") {
    return {
      tone: "warning",
      label: "Bloqueada",
      title: "La misión quedó bloqueada antes de correr",
      body: currentTask.title,
      activityLabel: activityAt ? relativeTimeFromNow(activityAt) : "sin señal",
      activityDetail: "Necesita destrabar dependencias o relanzar el runtime.",
    };
  }

  return {
    tone: "neutral",
    label: mission.status === "planned" ? "Planificada" : "En espera",
    title: mission.status === "planned" ? "La misión está lista para correr" : "La misión está en espera",
    body: defaultDetail,
    activityLabel: activityAt ? relativeTimeFromNow(activityAt) : "sin señal",
    activityDetail: "Todavía no hay una señal fuerte de ejecución activa.",
  };
}

function missionQueueItem(missionId) {
  return APP_STATE.snapshot?.queue?.find((item) => item.mission_id === missionId) || null;
}

function resolveSelectedMissionId(queue, snapshotFocusedId) {
  const missionIds = new Set((queue || []).map((item) => item.mission_id));
  if (APP_STATE.selectedMissionId && missionIds.has(APP_STATE.selectedMissionId)) {
    return APP_STATE.selectedMissionId;
  }
  if (snapshotFocusedId && missionIds.has(snapshotFocusedId)) {
    return snapshotFocusedId;
  }
  return queue?.[0]?.mission_id || null;
}

function filteredGraphForMission(graph, mission) {
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

function repositoryCount(graph) {
  return (graph?.nodes || []).filter((node) => node.kind.toLowerCase() === "repository").length;
}

function renderPanelState(type, title, body, actions = "") {
  return `
    <article class="panel-state panel-state-${safeStatusClass(type)}">
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(body)}</p>
      ${actions}
    </article>
  `;
}

function renderActionButton(action, missionId, label, className = "") {
  const key = actionKey(action, missionId);
  const busy = isPending(key);
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
      ${busy ? 'aria-busy="true" disabled' : ""}
    >
      ${escapeHtml(busy ? busyLabel : label)}
    </button>
  `;
}

function renderMissionPulseCard(mission) {
  const pulse = missionPulseState(mission);
  const currentTask = findCurrentTask(mission);
  const owner = resolveProfile(currentTask?.agent_profile_slug || "planner");
  const run = mission?.active_run;
  const command = run?.last_command;
  const tone = safeStatusClass(pulse.tone);

  return `
    <article class="mission-pulse tone-${tone}" tabindex="0">
      <div class="mission-pulse-compact">
        <span class="pulse-led tone-${tone}" aria-hidden="true"></span>
        <span class="pulse-short">${escapeHtml(pulse.label)}</span>
        <span class="pulse-compact-task">${escapeHtml(truncate(currentTask?.title || pulse.title, 46))}</span>
      </div>
      <div class="mission-pulse-detail">
        <div class="mission-pulse-main">
          <div class="mission-pulse-head">
            <span class="pulse-kicker">Pulso de la misión</span>
            <span class="pulse-badge tone-${tone}">${escapeHtml(pulse.label)}</span>
          </div>
          <h2>${escapeHtml(pulse.title)}</h2>
          <p class="mission-pulse-copy">${escapeHtml(pulse.body)}</p>
          <p class="mission-pulse-copy">${escapeHtml(pulse.activityDetail)}</p>
        </div>
        <div class="mission-pulse-meta">
          <div class="pulse-meta-row">
            <span>Misión</span>
            <strong>${escapeHtml(mission?.id ? mission.id.slice(0, 8) : "n/a")}</strong>
          </div>
          <div class="pulse-meta-row">
            <span>Etapa</span>
            <strong>${escapeHtml(currentTask?.key || "sin tarea")}</strong>
          </div>
          <div class="pulse-meta-row">
            <span>Owner</span>
            <strong>${escapeHtml(owner.label)}</strong>
          </div>
          <div class="pulse-meta-row">
            <span>Run</span>
            <strong>${escapeHtml(STATUS_LABELS[safeStatusClass(run?.status || mission?.status)] || run?.status || mission?.status || "sin run")}</strong>
          </div>
          <div class="pulse-meta-row">
            <span>Última señal</span>
            <strong>${escapeHtml(pulse.activityLabel)}</strong>
          </div>
          <div class="pulse-meta-row">
            <span>Comando</span>
            <strong>${escapeHtml(command ? commandKindLabel(command.kind) : "sin comando")}</strong>
          </div>
        </div>
      </div>
    </article>
  `;
}

function renderMissionSummaryCard(mission, graph) {
  const queueItem = missionQueueItem(mission.id);
  const currentTask = findCurrentTask(mission);
  const currentProfile = resolveProfile(currentTask?.agent_profile_slug || queueItem?.current_owner || "planner");
  const worktree = mission.worktree_snapshot;
  const lastBatch = worktree?.last_committed_batch;
  const lastCommand = mission.active_run?.last_command;
  const closedTasks = mission.execution_tasks.filter((task) => ["completed", "failed", "skipped"].includes(task.status)).length;
  const activeTasks = mission.execution_tasks.filter((task) => task.status === "running").length;
  const remainingTasks = mission.execution_tasks.filter((task) => ["ready", "queued", "blocked"].includes(task.status)).length;
  const missionStatus = mission.active_run?.status || mission.status;
  const actionBusy = APP_STATE.isLoadingMission ? '<span class="chip subtle-chip">Actualizando foco…</span>' : "";

  return `
    <article class="card focus-summary-card">
      <div class="focus-summary-head">
        <div class="identity-row identity-row-large">
          ${iconMarkup(currentProfile, { className: "agent-icon agent-icon-large" })}
          <div class="title-stack">
            <strong>${escapeHtml(currentTask?.title || mission.spec.summary || mission.brief)}</strong>
            <span class="card-kicker">Owner activo: ${escapeHtml(currentProfile.label)}</span>
          </div>
        </div>
        <div class="focus-summary-pill-row">
          <span class="chip policy-chip">${escapeHtml(mission.policy.slug)}</span>
          ${statusPill(missionStatus)}
        </div>
      </div>

      <p class="focus-copy">${escapeHtml(mission.brief)}</p>

      <div class="focus-meta-grid">
        <div class="focus-meta-item">
          <span>Próximo paso</span>
          <strong>${escapeHtml(queueItem?.next_step || currentTask?.title || "sin programación")}</strong>
        </div>
        <div class="focus-meta-item">
          <span>Budget</span>
          <strong>${escapeHtml(formatBudgetLabel(mission))}${mission.runtime_budget_reached ? " · límite alcanzado" : ""}</strong>
        </div>
        <div class="focus-meta-item">
          <span>Rama</span>
          <strong>${escapeHtml(worktree?.branch_name || mission.active_run?.branch_name || "todavía no creada")}</strong>
        </div>
        <div class="focus-meta-item">
          <span>Worktree</span>
          <strong>${escapeHtml(worktree?.worktree_path || mission.active_run?.worktree_path || "todavía no creado")}</strong>
        </div>
        <div class="focus-meta-item">
          <span>Último comando</span>
          <strong>${escapeHtml(lastCommand ? truncate(lastCommand.command, 64) : "sin comandos todavía")}</strong>
        </div>
        <div class="focus-meta-item">
          <span>HEAD</span>
          <strong>${escapeHtml(worktree?.head_summary || lastBatch?.commit_subject || "todavía sin commit")}</strong>
        </div>
        <div class="focus-meta-item">
          <span>Merge target</span>
          <strong>${escapeHtml(mission.spec.merge_target || "sin declarar")}</strong>
        </div>
        <div class="focus-meta-item">
          <span>Deploy targets</span>
          <strong>${escapeHtml(formatList(mission.spec.deploy_targets, "ninguno"))}</strong>
        </div>
        <div class="focus-meta-item">
          <span>Repos</span>
          <strong>${escapeHtml(formatList(mission.linked_repositories, "greenfield"))}</strong>
        </div>
        <div class="focus-meta-item">
          <span>Nodos del contexto</span>
          <strong>${escapeHtml(graph ? graph.nodes.length : 0)}</strong>
        </div>
      </div>

      <div class="focus-actions">
        ${renderActionButton("run", mission.id, "Correr")}
        ${renderActionButton("resume", mission.id, "Reanudar", "secondary")}
        ${renderActionButton("interrupt", mission.id, "Interrumpir", "ghost")}
        ${actionBusy}
      </div>

      <div class="progress-strip">
        <div class="progress-metric">
          <strong>${escapeHtml(closedTasks)}</strong>
          <span>Cerradas</span>
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
    </article>
  `;
}

function renderExecutionControls(mission) {
  const controls = mission?.execution_controls || {};
  const locked = Boolean(mission?.controls_locked);
  const showDeploy = canToggleDeploy(mission);
  const saveKey = actionKey("controls", mission.id);
  const saveBusy = isPending(saveKey);
  const helper = locked
    ? "Los controles quedan bloqueados después del primer run para no desalinear el runtime."
    : "Estos controles restringen etapas, pero la policy sigue siendo el gate final.";

  return `
    <section class="controls-card">
      <div class="subpanel-head">
        <h3>Controles de ejecución</h3>
        <span class="card-kicker">${escapeHtml(helper)}</span>
      </div>
      <form class="controls-grid" data-controls-form data-mission-id="${escapeHtml(mission.id)}">
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
                  <span>Dispara sólo los targets explícitos de deploy después de release.</span>
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
            <span>Corta de forma controlada y deja la misión lista para reanudar manualmente.</span>
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
          <span class="card-meta">Budget: ${escapeHtml(formatBudgetLabel(mission))}${mission.runtime_budget_reached ? " · límite alcanzado" : ""}</span>
          <button
            type="button"
            class="secondary"
            data-save-controls="${escapeHtml(mission.id)}"
            ${locked || saveBusy ? 'aria-busy="true" disabled' : ""}
          >
            ${escapeHtml(saveBusy ? "Guardando…" : "Guardar Controles")}
          </button>
        </div>
      </form>
    </section>
  `;
}

function renderTaskBoard(tasks) {
  const working = (tasks || []).filter((task) => ["running", "ready", "queued"].includes(task.status));
  const closed = (tasks || []).filter((task) => ["blocked", "completed", "failed", "skipped"].includes(task.status));

  function taskCard(task) {
    const profile = resolveProfile(task.agent_profile_slug);
    const dependencies = (task.depends_on || []).length
      ? `Depende de: ${task.depends_on.join(", ")}`
      : (task.notes ? truncate(task.notes, 120) : "Sin dependencias bloqueantes.");
    return `
      <article class="task-card status-${safeStatusClass(task.status)}">
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
        <p class="task-scope">Alcance: ${escapeHtml(taskScope(task))}</p>
        <p class="task-note">${escapeHtml(dependencies)}</p>
      </article>
    `;
  }

  function column(title, subtitle, items) {
    return `
      <section class="task-column">
        <div class="flow-step-head">
          <span class="flow-stage-label">${escapeHtml(title)}</span>
          <span class="flow-stage-meta">${escapeHtml(items.length)} ${pluralize(items.length, "tarea")}</span>
        </div>
        <p class="card-kicker">${escapeHtml(subtitle)}</p>
        <div class="task-column-body">
          ${
            items.length
              ? items.map(taskCard).join("")
              : '<p class="empty">No hay tareas en esta columna ahora mismo.</p>'
          }
        </div>
      </section>
    `;
  }

  return `
    <div class="task-board">
      ${column("En curso y próximas", "running, ready y queued", working)}
      ${column("Bloqueadas y cerradas", "blocked, completed, failed y skipped", closed)}
    </div>
  `;
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
                <article class="flow-card status-${statusClass}${activeClass}" data-flow-task-key="${escapeHtml(task.key)}" ${task.key === activeTaskKey ? 'data-flow-active="true"' : ""}>
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

function centerActiveFlowCard() {
  const container = document.querySelector(".graph-scroll");
  const activeCard = container?.querySelector("[data-flow-active='true']");
  const missionId = APP_STATE.focusedMission?.id || "";
  const taskKey = APP_STATE.focusedMission ? findCurrentTask(APP_STATE.focusedMission)?.key || "" : "";
  const nextCenterKey = missionId && taskKey ? `${missionId}:${taskKey}` : null;

  if (!container || !activeCard || !nextCenterKey) {
    return;
  }

  if (APP_STATE.lastCenteredFlowKey === nextCenterKey) {
    return;
  }

  APP_STATE.lastCenteredFlowKey = nextCenterKey;
  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      const containerRect = container.getBoundingClientRect();
      const activeRect = activeCard.getBoundingClientRect();
      const delta = (activeRect.left - containerRect.left) - ((container.clientWidth - activeCard.clientWidth) / 2);
      const maxScrollLeft = Math.max(0, container.scrollWidth - container.clientWidth);
      const nextScrollLeft = Math.max(0, Math.min(maxScrollLeft, container.scrollLeft + delta));
      container.scrollTo({
        left: nextScrollLeft,
        behavior: "smooth",
      });
    });
  });
}

function renderRunsMarkup(mission, logsView) {
  if (!mission || !logsView?.runs?.length) {
    return '<p class="empty">Todavía no hay runs para la misión enfocada.</p>';
  }

  const taskMap = buildTaskMap(mission.execution_tasks);
  return logsView.runs.slice(0, 4).map((run) => {
    const task = representativeTaskForRun(taskMap, run, logsView);
    const profile = resolveProfile(task?.agent_profile_slug || "");
    const summary = task?.title || run.current_task_key || "Shell del runtime";
    return `
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
    `;
  }).join("");
}

function renderCommandsMarkup(mission, logsView) {
  if (!mission || !logsView?.commands?.length) {
    return '<p class="empty">Todavía no hay comandos ejecutados para la misión enfocada.</p>';
  }

  const taskMap = buildTaskMap(mission.execution_tasks);
  return logsView.commands.slice(0, 6).map((item) => {
    const task = taskMap.get(item.task_key);
    const profile = resolveProfile(task?.agent_profile_slug || "");
    const commandLabel = truncate(item.command, 96);
    return `
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
    `;
  }).join("");
}

function renderRuntimeSection(mission) {
  if (!mission) {
    return renderPanelState(
      "empty",
      "Sin misión enfocada",
      "Seleccioná una misión de la cola para abrir el runtime operativo."
    );
  }

  const currentTask = findCurrentTask(mission);
  const worktree = mission.worktree_snapshot;
  const lastBatch = worktree?.last_committed_batch;
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

  return `
    <section class="section-shell">
      <div class="runtime-panels">
        <section class="runtime-subpanel">
          <div class="subpanel-head">
            <h3>Controles y progreso</h3>
            <span class="card-kicker">Límites, toggles y board de tareas de la misión.</span>
          </div>
          ${renderExecutionControls(mission)}
          ${renderTaskBoard(mission.execution_tasks)}
        </section>

        <section class="runtime-subpanel">
          <div class="subpanel-head">
            <h3>Worktree visible</h3>
            <span class="card-kicker">${escapeHtml(worktree?.note || "Cambios visibles ahora mismo para la misión enfocada.")}</span>
          </div>
          <div class="stack">
            <div class="runtime-subpanel runtime-subpanel-nested">
              ${renderDisclosure("Archivos cambiados", buildChangedFilesIndicator(worktree), changedFilesMarkup, { open: true })}
            </div>
            <div class="runtime-subpanel runtime-subpanel-nested">
              ${renderDisclosure("Diff actual", buildCurrentDiffIndicator(worktree), diffStatMarkup)}
            </div>
          </div>
        </section>
      </div>
    </section>
  `;
}

function renderLogsSection(mission, logsView) {
  if (!mission) {
    return renderPanelState(
      "empty",
      "Sin misión enfocada",
      "Cuando elijas una misión, acá vas a ver los runs recientes y los comandos del runtime."
    );
  }

  if (APP_STATE.missionError) {
    return renderPanelState(
      "error",
      "No pude cargar los logs",
      APP_STATE.missionError,
      '<div class="button-row"><button type="button" data-retry-focused class="secondary">Reintentar</button></div>'
    );
  }

  return `
    <section class="section-shell">
      <div class="runtime-feed">
        <section class="runtime-subpanel">
          <div class="subpanel-head">
            <h3>Runs recientes</h3>
            <span class="card-kicker">Hasta cuatro runs para entender la secuencia del runtime.</span>
          </div>
          <div class="stack">${renderRunsMarkup(mission, logsView)}</div>
        </section>

        <section class="runtime-subpanel">
          <div class="subpanel-head">
            <h3>Comandos recientes</h3>
            <span class="card-kicker">Últimos comandos relevantes de la misión enfocada.</span>
          </div>
          <div class="stack">${renderCommandsMarkup(mission, logsView)}</div>
        </section>
      </div>
    </section>
  `;
}

function renderGraphSection(mission, graph) {
  if (!mission) {
    return renderPanelState(
      "empty",
      "Sin misión enfocada",
      "Seleccioná una misión para bajar a productos, repos, documentos y relaciones."
    );
  }

  if (APP_STATE.graphError) {
    return renderPanelState(
      "warning",
      "El grafo no se pudo refrescar",
      APP_STATE.graphError,
      '<div class="button-row"><button type="button" data-manual-refresh class="secondary">Actualizar Ahora</button></div>'
    );
  }

  if (!graph?.nodes?.length) {
    return renderPanelState(
      "empty",
      "Contexto vacío",
      "La misión no tiene nodos relacionados visibles en el grafo local todavía."
    );
  }

  const nodeMap = new Map(graph.nodes.map((node) => [node.node_key, node]));
  const countMarkup = Object.entries(graph.counts)
    .sort((left, right) => left[0].localeCompare(right[0]))
    .map(([key, value]) => `<span class="chip">${escapeHtml(key)}: ${escapeHtml(value)}</span>`)
    .join("");
  const nodesMarkup = graph.nodes
    .slice(0, 24)
    .map((node) => {
      return `<div class="list-item"><strong>${escapeHtml(node.kind)}</strong><span>${escapeHtml(node.name)}</span></div>`;
    })
    .join("");
  const edgesMarkup = graph.edges
    .slice(0, 24)
    .map((edge) => {
      const source = nodeMap.get(edge.source_key)?.name || edge.source_key;
      const target = nodeMap.get(edge.target_key)?.name || edge.target_key;
      return `<div class="list-item"><strong>${escapeHtml(edge.relation)}</strong><span>${escapeHtml(source)} → ${escapeHtml(target)}</span></div>`;
    })
    .join("");

  return `
    <section class="section-shell">
      <section class="runtime-subpanel runtime-subpanel-wide">
        <div class="subpanel-head">
          <h3>Contexto filtrado de la misión</h3>
          <span class="card-kicker">Este panel usa el grafo global, filtrado localmente por la misión seleccionada.</span>
        </div>
        <div class="chip-row">${countMarkup}</div>
        <div class="graph-context-grid">
          <div class="context-pill-group">
            <span class="graph-context-label">Productos</span>
            <div class="chip-row compact-row">
              ${mission.linked_products.length ? mission.linked_products.map((item) => `<span class="chip">${escapeHtml(item)}</span>`).join("") : '<span class="card-meta">sin productos declarados</span>'}
            </div>
          </div>
          <div class="context-pill-group">
            <span class="graph-context-label">Repos</span>
            <div class="chip-row compact-row">
              ${mission.linked_repositories.length ? mission.linked_repositories.map((item) => `<span class="chip">${escapeHtml(item)}</span>`).join("") : '<span class="card-meta">greenfield</span>'}
            </div>
          </div>
          <div class="context-pill-group">
            <span class="graph-context-label">Documentos</span>
            <div class="chip-row compact-row">
              ${mission.linked_documents.length ? mission.linked_documents.map((item) => `<span class="chip">${escapeHtml(item)}</span>`).join("") : '<span class="card-meta">sin documentos vinculados</span>'}
            </div>
          </div>
        </div>
      </section>

      <div class="runtime-panels">
        <section class="runtime-subpanel">
          ${renderDisclosure(
            "Nodos del contexto",
            `${graph.nodes.length} ${pluralize(graph.nodes.length, "nodo")}`,
            nodesMarkup || '<p class="empty">No hay nodos visibles.</p>',
            { open: true }
          )}
        </section>

        <section class="runtime-subpanel">
          ${renderDisclosure(
            "Relaciones",
            `${graph.edges.length} ${pluralize(graph.edges.length, "relación", "relaciones")}`,
            edgesMarkup || '<p class="empty">No hay relaciones visibles.</p>',
            { open: true }
          )}
        </section>
      </div>
    </section>
  `;
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
      <strong>${escapeHtml(
        {
          success: "Listo",
          warning: "Atención",
          error: "Error",
          neutral: "Info",
        }[APP_STATE.flash.tone] || "Info"
      )}</strong>
      <p>${escapeHtml(APP_STATE.flash.message)}</p>
    </div>
    <button type="button" class="ghost status-banner-close" data-dismiss-banner aria-label="Cerrar mensaje">Cerrar</button>
  `;
}

function renderRefreshStatus() {
  const target = document.getElementById("refresh-status");
  if (!target) {
    return;
  }

  if (APP_STATE.isRefreshing) {
    target.textContent = "Actualizando dashboard…";
    return;
  }

  if (APP_STATE.lastRefreshAt) {
    target.textContent = `Última actualización: ${formatClock(APP_STATE.lastRefreshAt)} · polling cada 15 s`;
    return;
  }

  target.textContent = "Sincronización inicial pendiente.";
}

function renderMetrics(graph) {
  document.getElementById("metric-missions").textContent = APP_STATE.snapshot?.queue?.length || 0;
  document.getElementById("metric-repositories").textContent = repositoryCount(graph);
  document.getElementById("metric-nodes").textContent = graph?.nodes?.length || 0;
}

function renderSectionNav() {
  const target = document.getElementById("section-nav");
  if (!target) {
    return;
  }

  const disabled = !APP_STATE.selectedMissionId;
  target.innerHTML = Object.entries(SECTION_LABELS)
    .map(([section, label]) => {
      const selected = APP_STATE.selectedSection === section;
      return `
        <button
          type="button"
          class="section-link ${selected ? "is-selected" : ""}"
          data-section-link="${escapeHtml(section)}"
          aria-pressed="${selected ? "true" : "false"}"
          ${disabled ? "disabled" : ""}
        >
          ${escapeHtml(label)}
        </button>
      `;
    })
    .join("");
}

function renderQueue() {
  const target = document.getElementById("queue-list");
  if (!target) {
    return;
  }

  const items = APP_STATE.snapshot?.queue || [];
  if (!APP_STATE.snapshot && APP_STATE.isRefreshing) {
    target.innerHTML = renderPanelState(
      "loading",
      "Cargando misiones…",
      "Armando la cola inicial del planner."
    );
    return;
  }

  if (!items.length) {
    target.innerHTML = renderPanelState(
      "empty",
      "Todavía no hay misiones",
      "Podés crear una demo o disparar una misión desde la API cuando quieras empezar."
    );
    return;
  }

  target.innerHTML = items
    .map((item) => {
      const owner = resolveProfile(item.current_owner || "planner");
      const selected = APP_STATE.selectedMissionId === item.mission_id;
      const repoScope = item.linked_repositories.length ? item.linked_repositories.join(", ") : "greenfield";
      const runtime = item.runtime_state
        ? STATUS_LABELS[safeStatusClass(item.runtime_state)] || item.runtime_state
        : "inactiva";
      return `
        <button
          type="button"
          class="mission-selector ${selected ? "is-selected" : ""}"
          data-select-mission="${escapeHtml(item.mission_id)}"
          aria-pressed="${selected ? "true" : "false"}"
        >
          <div class="mission-selector-top">
            <span class="mission-selector-type">${escapeHtml(item.mission_type)}</span>
            ${statusPill(item.runtime_state || item.status)}
          </div>
          <div class="identity-row">
            ${iconMarkup(owner)}
            <div class="title-stack">
              <strong>${escapeHtml(item.next_step)}</strong>
              <span class="card-kicker">Owner actual: ${escapeHtml(owner.label)}</span>
            </div>
          </div>
          <div class="mission-selector-meta">
            <span>Policy: ${escapeHtml(item.policy)}</span>
            <span>Repos: ${escapeHtml(repoScope)}</span>
            <span>Runtime: ${escapeHtml(runtime)}</span>
            <span>Archivos: ${escapeHtml(item.changed_files_count)}</span>
          </div>
        </button>
      `;
    })
    .join("");
}

function renderFocusedMission() {
  const target = document.getElementById("focused-mission");
  const pulseTarget = document.getElementById("mission-pulse");
  if (!target) {
    return;
  }

  if (APP_STATE.isLoadingMission && !APP_STATE.focusedMission) {
    target.innerHTML = renderPanelState(
      "loading",
      "Cargando misión…",
      "Estoy trayendo el runtime y los logs de la misión seleccionada."
    );
    if (pulseTarget) {
      pulseTarget.innerHTML = "";
    }
    return;
  }

  if (APP_STATE.missionError && !APP_STATE.focusedMission) {
    target.innerHTML = renderPanelState(
      "error",
      "No pude abrir la misión",
      APP_STATE.missionError,
      '<div class="button-row"><button type="button" data-retry-focused class="secondary">Reintentar</button></div>'
    );
    if (pulseTarget) {
      pulseTarget.innerHTML = "";
    }
    return;
  }

  if (!APP_STATE.focusedMission) {
    target.innerHTML = renderPanelState(
      "empty",
      "Sin misión enfocada",
      "Elegí una misión de la cola para activar el panel operativo."
    );
    if (pulseTarget) {
      pulseTarget.innerHTML = "";
    }
    return;
  }

  const graph = filteredGraphForMission(APP_STATE.fullGraph, APP_STATE.focusedMission);
  const currentTask = findCurrentTask(APP_STATE.focusedMission);
  target.innerHTML = `
    <div class="stack">
      ${renderMissionSummaryCard(APP_STATE.focusedMission, graph)}
      <section class="runtime-subpanel runtime-subpanel-wide execution-band">
        <div class="subpanel-head">
          <h3>Camino de ejecución</h3>
          <span class="card-kicker">Ocupa todo el ancho disponible, con scroll lateral y foco centrado en la tarea en curso.</span>
        </div>
        <div class="graph-scroll">
          ${buildRuntimeGraph(APP_STATE.focusedMission.execution_tasks, currentTask?.key)}
        </div>
      </section>
    </div>
  `;
  if (pulseTarget) {
    pulseTarget.innerHTML = renderMissionPulseCard(APP_STATE.focusedMission);
  }
  centerActiveFlowCard();
}

function renderSectionContent() {
  const target = document.getElementById("section-content");
  if (!target) {
    return;
  }

  if (APP_STATE.isLoadingMission && !APP_STATE.focusedMission) {
    target.innerHTML = renderPanelState(
      "loading",
      "Cargando panel…",
      "Esperando los datos del runtime para abrir la sección activa."
    );
    return;
  }

  const mission = APP_STATE.focusedMission;
  const filteredGraph = filteredGraphForMission(APP_STATE.fullGraph, mission);
  const description = SECTION_DESCRIPTIONS[APP_STATE.selectedSection];

  let sectionMarkup = "";
  if (APP_STATE.selectedSection === "runtime") {
    sectionMarkup = renderRuntimeSection(mission);
  } else if (APP_STATE.selectedSection === "logs") {
    sectionMarkup = renderLogsSection(mission, APP_STATE.logsView);
  } else {
    sectionMarkup = renderGraphSection(mission, filteredGraph);
  }

  target.innerHTML = `
    <section id="section-anchor-${escapeHtml(APP_STATE.selectedSection)}" class="section-stage">
      <div class="section-stage-header">
        <span class="flow-stage-label">${escapeHtml(SECTION_LABELS[APP_STATE.selectedSection])}</span>
        <span class="card-kicker">${escapeHtml(description)}</span>
      </div>
      ${sectionMarkup}
    </section>
  `;
}

function renderDashboard() {
  renderBanner();
  renderRefreshStatus();
  renderSectionNav();
  renderQueue();
  renderFocusedMission();
  renderSectionContent();
  renderMetrics(filteredGraphForMission(APP_STATE.fullGraph, APP_STATE.focusedMission));

  const refreshButton = document.getElementById("refresh-dashboard");
  if (refreshButton) {
    refreshButton.disabled = APP_STATE.isRefreshing;
    refreshButton.setAttribute("aria-busy", APP_STATE.isRefreshing ? "true" : "false");
    refreshButton.textContent = APP_STATE.isRefreshing ? "Actualizando…" : "Actualizar Ahora";
  }
}

function scrollActiveSectionIntoView() {
  const target = document.getElementById(`section-anchor-${APP_STATE.selectedSection}`);
  target?.scrollIntoView({ block: "start", behavior: "smooth" });
}

async function loadFocusedMission(missionId, options = {}) {
  const { scroll = false } = options;
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
    const [mission, logsView] = await Promise.all([
      fetchJson(`/api/missions/${missionId}`),
      fetchJson(`/api/missions/${missionId}/logs`),
    ]);

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
    if (scroll) {
      scrollActiveSectionIntoView();
    }
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

    const snapshotPromise = fetchJson("/api/dashboard");
    const graphPromise = fetchJson("/api/graph").catch((error) => {
      APP_STATE.graphError = parseAppError(error);
      return null;
    });

    const [snapshot, fullGraph] = await Promise.all([snapshotPromise, graphPromise]);
    APP_STATE.snapshot = snapshot;
    if (fullGraph) {
      APP_STATE.fullGraph = fullGraph;
    }
    if (fullGraph) {
      APP_STATE.graphError = null;
    }

    const selectedMissionId = resolveSelectedMissionId(snapshot.queue, snapshot.focused_mission_id);
    const missionChanged = APP_STATE.selectedMissionId !== selectedMissionId;
    APP_STATE.selectedMissionId = selectedMissionId;
    if (missionChanged) {
      APP_STATE.lastCenteredFlowKey = null;
    }
    syncUrlState({ replace: true });
    renderDashboard();

    if (selectedMissionId) {
      if (missionChanged) {
        APP_STATE.focusedMission = null;
        APP_STATE.logsView = null;
      }
      await loadFocusedMission(selectedMissionId);
    } else {
      APP_STATE.focusedMission = null;
      APP_STATE.logsView = null;
      APP_STATE.missionError = null;
    }

    APP_STATE.lastRefreshAt = new Date().toISOString();
    if (APP_STATE.graphError && APP_STATE.flash?.tone !== "success") {
      setBanner("warning", `Actualicé misiones y runtime, pero el grafo global no se pudo refrescar. ${APP_STATE.graphError}`);
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

async function postMissionAction(missionId, action) {
  await withPendingAction(actionKey(action, missionId), async () => {
    await fetchJson(`/api/missions/${missionId}/${action}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
    });
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
  payload.max_runtime_hours = rawHours ? Number.parseInt(rawHours, 10) : null;

  await withPendingAction(actionKey("controls", missionId), async () => {
    await fetchJson(`/api/missions/${missionId}/controls`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    setBanner("success", `Guardé los controles de la misión ${missionId.slice(0, 8)}.`);
    await refreshDashboard();
  });
}

async function createDemoMission() {
  await withPendingAction("seed-demo", async () => {
    const mission = await fetchJson("/api/missions", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        brief: "Dashboard interno greenfield que coordina repos frontend y backend para una nueva iniciativa operativa.",
        desired_outcome: "Bootstrapear un shell inicial del proyecto, elegir un template de stack y preparar la primera ola de implementación.",
        linked_products: ["Demo de Autonomía"],
        policy: "safe",
      }),
    });
    APP_STATE.selectedMissionId = mission.id;
    syncUrlState({ replace: false });
    setBanner("success", `Creé la misión demo ${mission.id.slice(0, 8)} y la dejé como foco actual.`);
    await refreshDashboard();
  });
}

async function discoverLocal() {
  await withPendingAction("discover-local", async () => {
    await fetchJson("/api/discovery/local", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ max_depth: 1 }),
    });
    setBanner("success", "Actualicé el descubrimiento local y refresqué el contexto del workspace.");
    await refreshDashboard();
  });
}

async function selectMission(missionId, options = {}) {
  const { scroll = false, pushHistory = true } = options;
  if (!missionId || missionId === APP_STATE.selectedMissionId) {
    if (pushHistory) {
      syncUrlState({ replace: false });
    }
    renderDashboard();
    if (scroll) {
      scrollActiveSectionIntoView();
    }
    return;
  }

  APP_STATE.selectedMissionId = missionId;
  APP_STATE.focusedMission = null;
  APP_STATE.logsView = null;
  APP_STATE.missionError = null;
  APP_STATE.lastCenteredFlowKey = null;
  syncUrlState({ replace: !pushHistory });
  renderDashboard();
  await loadFocusedMission(missionId, { scroll });
}

function selectSection(section, options = {}) {
  const { pushHistory = true, scroll = true } = options;
  if (!isValidSection(section)) {
    return;
  }
  APP_STATE.selectedSection = section;
  syncUrlState({ replace: !pushHistory });
  renderDashboard();
  if (scroll) {
    scrollActiveSectionIntoView();
  }
}

function installEventHandlers() {
  document.getElementById("seed-demo").addEventListener("click", () => {
    createDemoMission().catch((error) => {
      setBanner("error", parseAppError(error));
      renderDashboard();
    });
  });

  document.getElementById("discover-local").addEventListener("click", () => {
    discoverLocal().catch((error) => {
      setBanner("error", parseAppError(error));
      renderDashboard();
    });
  });

  document.getElementById("refresh-dashboard").addEventListener("click", () => {
    refreshDashboard({ announceRefresh: true }).catch((error) => {
      setBanner("error", parseAppError(error));
      renderDashboard();
    });
  });

  document.addEventListener("click", (event) => {
    const dismissButton = event.target.closest("[data-dismiss-banner]");
    if (dismissButton) {
      clearBanner();
      renderDashboard();
      return;
    }

    const missionButton = event.target.closest("[data-select-mission]");
    if (missionButton) {
      selectMission(missionButton.dataset.selectMission).catch((error) => {
        setBanner("error", parseAppError(error));
        renderDashboard();
      });
      return;
    }

    const sectionButton = event.target.closest("[data-section-link]");
    if (sectionButton) {
      selectSection(sectionButton.dataset.sectionLink);
      return;
    }

    const retryButton = event.target.closest("[data-retry-focused]");
    if (retryButton && APP_STATE.selectedMissionId) {
      loadFocusedMission(APP_STATE.selectedMissionId, { scroll: true }).catch((error) => {
        setBanner("error", parseAppError(error));
        renderDashboard();
      });
      return;
    }

    const manualRefresh = event.target.closest("[data-manual-refresh]");
    if (manualRefresh) {
      refreshDashboard({ announceRefresh: true }).catch((error) => {
        setBanner("error", parseAppError(error));
        renderDashboard();
      });
      return;
    }

    const saveControlsButton = event.target.closest("[data-save-controls]");
    if (saveControlsButton) {
      saveMissionControls(saveControlsButton.dataset.saveControls).catch((error) => {
        setBanner("error", parseAppError(error));
        renderDashboard();
      });
      return;
    }

    const actionButton = event.target.closest("[data-action]");
    if (!actionButton) {
      return;
    }

    const { missionId, action } = actionButton.dataset;
    if (action === "interrupt") {
      const confirmed = window.confirm("Esto va a interrumpir el runtime activo. ¿Querés seguir?");
      if (!confirmed) {
        return;
      }
    }

    postMissionAction(missionId, action).catch((error) => {
      setBanner("error", parseAppError(error));
      renderDashboard();
    });
  });

  window.addEventListener("popstate", () => {
    const nextState = readUrlState();
    APP_STATE.selectedSection = nextState.section;
    renderDashboard();
    if (nextState.missionId && nextState.missionId !== APP_STATE.selectedMissionId) {
      selectMission(nextState.missionId, { pushHistory: false, scroll: false }).catch((error) => {
        setBanner("error", parseAppError(error));
        renderDashboard();
      });
      return;
    }
    scrollActiveSectionIntoView();
  });
}

function startRefreshLoop() {
  if (refreshTimerId) {
    window.clearInterval(refreshTimerId);
  }
  refreshTimerId = window.setInterval(() => {
    refreshDashboard().catch((error) => {
      setBanner("error", parseAppError(error));
      renderDashboard();
    });
  }, REFRESH_INTERVAL_MS);
}

document.addEventListener("DOMContentLoaded", () => {
  const urlState = readUrlState();
  APP_STATE.selectedMissionId = urlState.missionId;
  APP_STATE.selectedSection = urlState.section;

  installEventHandlers();
  renderDashboard();
  refreshDashboard().catch((error) => {
    setBanner("error", parseAppError(error));
    renderDashboard();
  });
  startRefreshLoop();
});
