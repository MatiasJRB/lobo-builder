import { isValidSection } from "./state.js";

export function readUrlState() {
  const params = new URLSearchParams(window.location.search);
  const missionId = params.get("mission");
  const section = params.get("section");

  return {
    missionId: missionId || null,
    section: isValidSection(section) ? section : "runtime",
  };
}

export function syncUrlState({ selectedMissionId, selectedSection }, { replace = true } = {}) {
  const params = new URLSearchParams(window.location.search);

  if (selectedMissionId) {
    params.set("mission", selectedMissionId);
  } else {
    params.delete("mission");
  }

  if (selectedSection && selectedSection !== "runtime") {
    params.set("section", selectedSection);
  } else {
    params.delete("section");
  }

  const nextUrl = `${window.location.pathname}${params.toString() ? `?${params}` : ""}`;
  const method = replace ? "replaceState" : "pushState";
  window.history[method]({}, "", nextUrl);
}
