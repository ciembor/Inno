window.addEventListener("DOMContentLoaded", () => {
  const counters = [...document.querySelectorAll("[data-counter]")];
  let countersStarted = false;
  const shouldReduceMotion = () =>
    document.body.classList.contains("reduce-motion") ||
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const showFinalCounterValues = () => {
    counters.forEach((counter) => {
      counter.textContent = counter.dataset.count;
      counter.style.visibility = "visible";
    });
  };

  const animateCounters = () => {
    if (countersStarted || shouldReduceMotion()) {
      showFinalCounterValues();
      return;
    }

    countersStarted = true;
    counters.forEach((counter) => {
      counter.textContent = "0";
      counter.style.visibility = "visible";
    });
    const startedAt = performance.now();
    const duration = 900;
    const formatter = new Intl.NumberFormat("pl-PL");
    let lastPaintedAt = 0;

    const update = (now) => {
      const progress = Math.min((now - startedAt) / duration, 1);
      if (progress < 1 && now - lastPaintedAt < 50) {
        window.requestAnimationFrame(update);
        return;
      }

      lastPaintedAt = now;
      const easedProgress = 1 - (1 - progress) ** 3;
      counters.forEach((counter) => {
        counter.textContent = formatter.format(
          Math.round(Number(counter.dataset.count) * easedProgress),
        );
      });
      if (progress < 1) {
        window.requestAnimationFrame(update);
      }
    };
    window.requestAnimationFrame(update);
  };

  if (shouldReduceMotion()) {
    showFinalCounterValues();
  } else if (counters.length && "IntersectionObserver" in window) {
    const counterSection = counters[0].closest(".cards");
    const observer = new IntersectionObserver(
      (entries) => {
        const cardsAreFullyVisible = entries.some((entry) => {
          const viewportHeight =
            window.visualViewport?.height ?? window.innerHeight;
          return (
            entry.intersectionRatio === 1 &&
            entry.boundingClientRect.top >= 0 &&
            entry.boundingClientRect.bottom <= viewportHeight
          );
        });
        if (cardsAreFullyVisible) {
          animateCounters();
          observer.disconnect();
        }
      },
      { threshold: 1 },
    );
    observer.observe(counterSection);
  } else {
    showFinalCounterValues();
  }

  window.addEventListener("motionchange", () => {
    if (shouldReduceMotion()) {
      showFinalCounterValues();
    }
  });

  const cloudsLayer = document.querySelector(".hero__clouds");
  const cloudBaseUrl = cloudsLayer?.dataset.cloudBaseUrl;
  if (!cloudBaseUrl) {
    return;
  }

  const clouds = {
    1: {
      image: `${cloudBaseUrl}cloud-1.webp`,
      ratio: "1344 / 366",
      width: "22vw",
    },
    2: {
      image: `${cloudBaseUrl}cloud-2.webp`,
      ratio: "525 / 261",
      width: "9vw",
    },
    3: {
      image: `${cloudBaseUrl}cloud-3.webp`,
      ratio: "1113 / 315",
      width: "18vw",
    },
    4: {
      image: `${cloudBaseUrl}cloud-4.webp`,
      ratio: "810 / 285",
      width: "14vw",
    },
    5: {
      image: `${cloudBaseUrl}cloud-5.webp`,
      ratio: "462 / 216",
      width: "8vw",
    },
    6: {
      image: `${cloudBaseUrl}cloud-6.webp`,
      ratio: "1734 / 444",
      width: "25vw",
    },
    7: {
      image: `${cloudBaseUrl}cloud-7.webp`,
      ratio: "621 / 309",
      width: "12vw",
    },
    8: {
      image: `${cloudBaseUrl}cloud-8.webp`,
      ratio: "1323 / 429",
      width: "20vw",
    },
  };
  document.querySelectorAll(".hero__cloud").forEach((cloud, index) => {
    const definition = clouds[cloud.dataset.cloud];
    const duration = 54 + index * 16 + Math.random() * 14;
    cloud.style.setProperty("--cloud-image", `url("${definition.image}")`);
    cloud.style.setProperty("--cloud-ratio", definition.ratio);
    cloud.style.setProperty("--cloud-bottom", "calc(78% - 55px)");
    cloud.style.setProperty("--cloud-width", definition.width);
    cloud.style.setProperty("--cloud-duration", `${duration}s`);
    cloud.style.setProperty("--cloud-delay", `${-Math.random() * duration}s`);
  });

  const alignCloudsWithHeroBackground = () => {
    const scrollOffset = window.scrollY;
    document.querySelectorAll(".hero__cloud").forEach((cloud) => {
      cloud.style.setProperty("--cloud-scroll-offset", `${scrollOffset}px`);
    });
  };
  alignCloudsWithHeroBackground();
  window.addEventListener("scroll", alignCloudsWithHeroBackground, {
    passive: true,
  });
  window.addEventListener("resize", alignCloudsWithHeroBackground);
});
