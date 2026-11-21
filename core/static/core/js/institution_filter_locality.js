window.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector("#institution-filter-locality");
  if (!root) return;

  const query = root.querySelector("#institution-filter-locality-query");
  const value = root.querySelector("#id_locality");
  const results = root.querySelector("#institution-filter-locality-results");
  let timer;
  let activeIndex = -1;
  let displayedLocalities = [];

  const close = () => {
    results.replaceChildren();
    results.hidden = true;
    activeIndex = -1;
    displayedLocalities = [];
    query.setAttribute("aria-expanded", "false");
    query.removeAttribute("aria-activedescendant");
  };
  const select = (locality) => {
    value.value = locality.id;
    query.value = `${locality.name}, ${locality.county}`;
    close();
  };
  const activate = (index) => {
    activeIndex = index;
    [...results.children].forEach((option, optionIndex) => {
      const isActive = optionIndex === activeIndex;
      option.setAttribute("aria-selected", String(isActive));
      if (isActive) {
        query.setAttribute("aria-activedescendant", option.id);
        option.scrollIntoView({ block: "nearest" });
      }
    });
  };
  const show = (localities) => {
    activeIndex = -1;
    displayedLocalities = localities;
    query.removeAttribute("aria-activedescendant");
    results.replaceChildren(
      ...localities.map((locality, index) => {
        const option = document.createElement("li");
        option.id = `${results.id}-option-${index}`;
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", "false");
        option.textContent = `${locality.name}, ${locality.county}`;
        option.addEventListener("mousedown", (event) => {
          event.preventDefault();
          select(locality);
        });
        return option;
      }),
    );
    results.hidden = !localities.length;
    query.setAttribute("aria-expanded", String(localities.length > 0));
  };
  query.addEventListener("keydown", (event) => {
    if (!displayedLocalities.length) {
      if (event.key === "Escape") close();
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      activate(Math.min(activeIndex + 1, displayedLocalities.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      activate(Math.max(activeIndex - 1, 0));
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      select(displayedLocalities[activeIndex]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
  });

  query.addEventListener("input", () => {
    value.value = "";
    window.clearTimeout(timer);
    close();
    if (query.value.trim().length < 2) return close();
    timer = window.setTimeout(async () => {
      const response = await fetch(
        `${root.dataset.localityUrl}?q=${encodeURIComponent(query.value)}`,
      );
      show((await response.json()).results);
    }, 180);
  });
  query.addEventListener("blur", () => window.setTimeout(close, 150));
});
