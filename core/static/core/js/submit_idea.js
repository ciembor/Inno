window.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector("#idea-app");
  Vue.createApp({
    delimiters: ["[[", "]]"],
    data: () => ({
      name: "",
      submitterName: "",
      email: "",
      localityQuery: "",
      localityId: "",
      localities: [],
      activeLocalityIndex: -1,
      localityTimer: null,
      content: "",
      submitting: false,
      error: "",
      privacyAccepted: false,
    }),
    computed: {
      activeLocalityId() {
        const locality = this.localities[this.activeLocalityIndex];
        return locality ? `locality-option-${locality.id}` : null;
      },
    },
    methods: {
      format(command, value = null) {
        this.$refs.editor.focus();
        document.execCommand(command, false, value);
        this.content = this.$refs.editor.innerHTML;
      },
      findLocalities() {
        this.localityId = "";
        this.activeLocalityIndex = -1;
        clearTimeout(this.localityTimer);
        if (this.localityQuery.length < 2) {
          this.localities = [];
          return;
        }
        this.localityTimer = setTimeout(async () => {
          const response = await fetch(
            root.dataset.localityUrl +
              "?q=" +
              encodeURIComponent(this.localityQuery),
          );
          this.localities = (await response.json()).results;
        }, 180);
      },
      moveLocality(direction) {
        if (!this.localities.length) return;
        this.activeLocalityIndex =
          (this.activeLocalityIndex + direction + this.localities.length) %
          this.localities.length;
      },
      selectActiveLocality() {
        if (this.activeLocalityIndex >= 0)
          this.selectLocality(this.localities[this.activeLocalityIndex]);
      },
      closeLocalities() {
        this.localities = [];
        this.activeLocalityIndex = -1;
      },
      selectLocality(locality) {
        this.localityId = locality.id;
        this.localityQuery = `${locality.name}, ${locality.county}`;
        this.closeLocalities();
      },
      async submitIdea() {
        this.error = "";
        if (
          !this.name ||
          !this.submitterName ||
          !this.email ||
          !this.localityId ||
          !this.content.trim() ||
          !this.privacyAccepted
        ) {
          this.error =
            "Uzupełnij wszystkie wymagane pola i wybierz miejscowość z listy.";
          return;
        }
        this.submitting = true;
        const body = new URLSearchParams({
          name: this.name,
          submitter_name: this.submitterName,
          email: this.email,
          locality: this.localityId,
          content: this.content,
          privacy_accepted: this.privacyAccepted ? "on" : "",
        });
        const token = document.querySelector(
          "[name=csrfmiddlewaretoken]",
        ).value;
        try {
          const response = await fetch(root.dataset.submitUrl, {
            method: "POST",
            headers: { "X-CSRFToken": token, Accept: "application/json" },
            body,
          });
          const data = await response.json();
          if (!response.ok) {
            this.error = Object.values(data.errors).flat().join(" ");
            this.submitting = false;
            return;
          }
          window.location.assign(data.redirect_url);
        } catch {
          this.error =
            "Nie udało się ocenić pomysłu. Spróbuj ponownie za chwilę.";
          this.submitting = false;
        }
      },
    },
  }).mount("#idea-app");
});
