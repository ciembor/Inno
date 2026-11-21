window.addEventListener("DOMContentLoaded", () => {
  const innovations = document.querySelector(".innovations");
  const buttons = document.querySelectorAll("[data-view]");
  const sortForm = document.querySelector(".sort");
  if (!innovations) return;
  if (sortForm) {
    sortForm
      .querySelectorAll("select")
      .forEach((select) =>
        select.addEventListener("change", () => sortForm.requestSubmit()),
      );
  }
  if (!buttons.length) return;
  const setView = (view) => {
    innovations.classList.toggle("innovations--list", view === "list");
    buttons.forEach((button) =>
      button.setAttribute("aria-pressed", String(button.dataset.view === view)),
    );
    localStorage.setItem("innoradar-innovations-view", view);
  };
  setView(
    localStorage.getItem("innoradar-innovations-view") === "list"
      ? "list"
      : "grid",
  );
  buttons.forEach((button) =>
    button.addEventListener("click", () => setView(button.dataset.view)),
  );
});
