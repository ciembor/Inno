const statusPanels = document.querySelectorAll(".crawl-status");

statusPanels.forEach((statusPanel) => {
  const updateText = (element, value) => {
    const text = String(value ?? "");
    if (element.textContent !== text) element.textContent = text;
  };
  const updateStatus = (run) => {
    const status = statusPanel.querySelector("[data-status]");
    if (!run) {
      updateText(status, "Nie uruchomiono jeszcze crawlera.");
      return;
    }
    const total = run.total || 0;
    const percent = total ? Math.round((run.processed / total) * 100) : 0;
    const eta = Number.isFinite(run.eta_seconds)
      ? ` ETA: ${formatDuration(run.eta_seconds)}.`
      : "";
    updateText(status, `Status: ${run.status}. ${percent}% ukończono.${eta}`);
    const progress = statusPanel.querySelector("[data-progress]");
    progress.max = Math.max(total, 1);
    progress.value = run.processed;
    progress.setAttribute("aria-valuetext", `${percent}% ukończono`);
    updateText(
      statusPanel.querySelector("[data-current]"),
      [run.action, run.institution].filter(Boolean).join(": ") || run.error,
    );
    updateText(
      statusPanel.querySelector("[data-processed]"),
      `${run.processed} / ${total}`,
    );
    updateText(statusPanel.querySelector("[data-created]"), run.created);
    statusPanel.querySelector("[data-events]").replaceChildren(
      ...run.events.map((event) => {
        const item = document.createElement("li");
        const time = document.createElement("time");
        time.textContent = event.time;
        item.append(time, document.createTextNode(event.message));
        return item;
      }),
    );
  };
  const refresh = async () => {
    try {
      const response = await fetch(statusPanel.dataset.statusUrl, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error("Nie udało się pobrać stanu crawlera.");
      updateStatus((await response.json()).run);
    } catch {
      updateText(
        statusPanel.querySelector("[data-status]"),
        "Nie udało się odświeżyć stanu crawlera. Próba zostanie ponowiona.",
      );
    } finally {
      window.setTimeout(refresh, 2000);
    }
  };
  refresh();
});

function formatDuration(seconds) {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `około ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `około ${hours} godz. ${minutes % 60} min`;
}
