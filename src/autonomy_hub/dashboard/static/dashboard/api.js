export async function fetchJson(path, options) {
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

export function loadDashboardSnapshot() {
  return fetchJson("/api/dashboard");
}

export function loadGraphSnapshot() {
  return fetchJson("/api/graph");
}

export function loadMission(missionId) {
  return fetchJson(`/api/missions/${missionId}`);
}

export function loadMissionLogs(missionId) {
  return fetchJson(`/api/missions/${missionId}/logs`);
}

export function postMissionAction(missionId, action) {
  return fetchJson(`/api/missions/${missionId}/${action}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
  });
}

export function patchMissionControls(missionId, payload) {
  return fetchJson(`/api/missions/${missionId}/controls`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function createDemoMission() {
  return fetchJson("/api/missions", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      brief: "Dashboard interno greenfield que coordina repos frontend y backend para una nueva iniciativa operativa.",
      desired_outcome:
        "Bootstrapear un shell inicial del proyecto, elegir un template de stack y preparar la primera ola de implementación.",
      linked_products: ["Demo de Autonomía"],
      policy: "safe",
    }),
  });
}

export function discoverLocal() {
  return fetchJson("/api/discovery/local", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ max_depth: 1 }),
  });
}
