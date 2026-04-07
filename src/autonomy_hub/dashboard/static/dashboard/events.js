export function installEventHandlers({
  onCreateDemoMission,
  onDiscoverLocal,
  onRefreshDashboard,
  onSelectMission,
  onSelectSection,
  onRetryFocused,
  onSaveMissionControls,
  onPostMissionAction,
  onToggleQueue,
  onShowMore,
  onDismissBanner,
  onPopState,
  onError,
}) {
  document.addEventListener("click", (event) => {
    const dismissButton = event.target.closest("[data-dismiss-banner]");
    if (dismissButton) {
      onDismissBanner();
      return;
    }

    const queueToggle = event.target.closest("#queue-toggle");
    if (queueToggle) {
      onToggleQueue();
      return;
    }

    const createDemoButton = event.target.closest("#seed-demo");
    if (createDemoButton) {
      onCreateDemoMission().catch(onError);
      return;
    }

    const discoverButton = event.target.closest("#discover-local");
    if (discoverButton) {
      onDiscoverLocal().catch(onError);
      return;
    }

    const refreshButton = event.target.closest("#refresh-dashboard");
    if (refreshButton) {
      onRefreshDashboard({ announceRefresh: true }).catch(onError);
      return;
    }

    const manualRefreshButton = event.target.closest("[data-manual-refresh]");
    if (manualRefreshButton) {
      onRefreshDashboard({ announceRefresh: true }).catch(onError);
      return;
    }

    const missionButton = event.target.closest("[data-select-mission]");
    if (missionButton) {
      onSelectMission(missionButton.dataset.selectMission).catch(onError);
      return;
    }

    const sectionButton = event.target.closest("[data-section-link]");
    if (sectionButton) {
      onSelectSection(sectionButton.dataset.sectionLink);
      return;
    }

    const retryButton = event.target.closest("[data-retry-focused]");
    if (retryButton) {
      onRetryFocused().catch(onError);
      return;
    }

    const saveControlsButton = event.target.closest("[data-save-controls]");
    if (saveControlsButton) {
      onSaveMissionControls(saveControlsButton.dataset.saveControls).catch(onError);
      return;
    }

    const showMoreButton = event.target.closest("[data-show-more]");
    if (showMoreButton) {
      onShowMore(showMoreButton.dataset.showMore);
      return;
    }

    const actionButton = event.target.closest("[data-action]");
    if (!actionButton) {
      return;
    }

    const { action, missionId } = actionButton.dataset;
    if (action === "interrupt") {
      const confirmed = window.confirm("Esto va a interrumpir el runtime activo. ¿Querés seguir?");
      if (!confirmed) {
        return;
      }
    }

    onPostMissionAction(missionId, action).catch(onError);
  });

  window.addEventListener("popstate", onPopState);
}
