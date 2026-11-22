window.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector("#main-content");
  if (!document.querySelector("#interactive-map")) return;
  Vue.createApp({
    delimiters: ["[[", "]]"],
    data: () => ({
      innovations: [],
      boundary: null,
      map: null,
      boundaryLayer: null,
      markers: [],
      error: "",
    }),
    async mounted() {
      this.onContrastChange = () => this.applyContrast();
      window.addEventListener("contrastchange", this.onContrastChange);
      try {
        const [innovations, boundary] = await Promise.all([
          fetch(root.dataset.innovationsUrl),
          fetch(root.dataset.boundaryUrl),
        ]);
        if (!innovations.ok || !boundary.ok)
          throw new Error("Nie udało się pobrać danych mapy.");
        this.innovations = (await innovations.json()).innovations;
        this.boundary = await boundary.json();
        await this.$nextTick();
        this.renderMap();
      } catch (error) {
        this.error =
          "Mapa jest chwilowo niedostępna. Odśwież stronę za moment.";
      }
    },
    unmounted() {
      window.removeEventListener("contrastchange", this.onContrastChange);
    },
    methods: {
      isHighContrast() {
        return document.body.classList.contains("high-contrast");
      },
      boundaryStyle() {
        return this.isHighContrast()
          ? {
              color: "#ffffff",
              weight: 2,
              fillColor: "#000000",
              fillOpacity: 1,
            }
          : {
              color: "#102b4d",
              weight: 2,
              fillColor: "#e3f5f1",
              fillOpacity: 0.75,
            };
      },
      markerStyle() {
        return this.isHighContrast()
          ? {
              radius: 8,
              color: "#ffffff",
              weight: 2,
              fillColor: "#ffff00",
              fillOpacity: 1,
            }
          : {
              radius: 8,
              color: "#0c796e",
              weight: 2,
              fillColor: "#11bca7",
              fillOpacity: 0.95,
            };
      },
      applyContrast() {
        if (!this.map) return;
        this.boundaryLayer.setStyle(this.boundaryStyle());
      },
      renderMap() {
        if (!this.innovations.length || !this.boundary) return;
        this.map = L.map(this.$refs.map, {
          zoomControl: false,
          attributionControl: true,
          maxZoom: 18,
        });
        L.control.zoom({ position: "bottomright" }).addTo(this.map);
        this.map.attributionControl.setPrefix(false);
        this.boundaryLayer = L.geoJSON(this.boundary, {
          style: this.boundaryStyle(),
        }).addTo(this.map);
        const bounds = this.boundaryLayer.getBounds();
        this.map.fitBounds(bounds, { padding: [10, 10] });
        this.map.setMinZoom(this.map.getZoom());
        this.map.setMaxBounds(bounds);
        this.map.options.maxBoundsViscosity = 1;
        this.map.attributionControl.addAttribution("Granice Polski: GADM 4.1");
        const clusters = L.markerClusterGroup({
          maxClusterRadius: 55,
          showCoverageOnHover: false,
          zoomToBoundsOnClick: true,
          spiderfyOnMaxZoom: true,
          animate: !window.matchMedia("(prefers-reduced-motion: reduce)")
            .matches,
          iconCreateFunction(cluster) {
            const count = cluster.getChildCount();
            const label = document.createElement("span");
            label.textContent = count;
            label.setAttribute(
              "aria-label",
              "Liczba innowacji: " + count + ". Rozwiń grupę",
            );
            return L.divIcon({
              html: label,
              className: "innovation-cluster",
              iconSize: [44, 44],
            });
          },
        });
        const icon = L.divIcon({
          className: "innovation-point",
          iconSize: [18, 18],
        });
        this.markers = this.innovations.map((innovation) => {
          const popup = document.createElement("div");
          const heading = document.createElement("strong");
          heading.textContent = innovation.name;
          popup.appendChild(heading);
          const description = document.createElement("p");
          description.textContent =
            innovation.locality +
            (innovation.score === null
              ? ""
              : " · " + innovation.score.toFixed(1));
          popup.appendChild(description);
          const link = document.createElement("a");
          link.href = innovation.url;
          link.textContent = "Zobacz innowację";
          popup.appendChild(link);
          return L.marker([innovation.latitude, innovation.longitude], {
            icon,
            title: innovation.name,
            alt: innovation.name,
            keyboard: true,
          }).bindPopup(popup);
        });
        clusters.addLayers(this.markers);
        clusters.addTo(this.map);
      },
    },
  }).mount("#interactive-map");
});
