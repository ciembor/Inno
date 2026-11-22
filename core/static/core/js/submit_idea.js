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
      workflow: null,
      privacyAccepted: false,
      steps: [
        {
          action: "score",
          label: "Oceniamy potencjał innowacji",
          status: "waiting",
          message: "czeka",
        },
        {
          action: "recommend",
          label: "Przygotowujemy ścieżkę rozwoju i partnerów",
          status: "waiting",
          message: "czeka",
        },
        {
          action: "classify",
          label: "Szukamy podobnych inicjatyw",
          status: "waiting",
          message: "czeka",
        },
      ],
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
      wait(milliseconds) {
        return new Promise((resolve) => setTimeout(resolve, milliseconds));
      },
      async completeStep(step, token) {
        let lastError = "";
        for (let attempt = 1; attempt <= 3; attempt += 1) {
          step.status = "active";
          step.message =
            attempt === 1 ? "w toku…" : `ponawiamy — próba ${attempt} z 3…`;
          try {
            const response = await fetch(
              `${root.dataset.submitUrl}${this.workflow.id}/etap/`,
              {
                method: "POST",
                headers: { "X-CSRFToken": token, Accept: "application/json" },
                body: new URLSearchParams({
                  action: step.action,
                  workflow_token: this.workflow.workflow_token,
                }),
              },
            );
            const data = await response.json();
            if (response.ok) return true;
            lastError = data.error || "Etap nie został ukończony.";
          } catch {
            lastError = "Połączenie z usługą przetwarzania zostało przerwane.";
          }
          if (attempt < 3) {
            const delay = attempt * 2000;
            step.message = `ponowimy za ${delay / 1000} s — próba ${attempt + 1} z 3`;
            await this.wait(delay);
          }
        }
        step.status = "waiting";
        step.message = "wymaga wznowienia";
        this.error = `${lastError} Możesz wznowić ocenę — gotowe etapy nie zostaną powtórzone.`;
        return false;
      },
      async submitIdea() {
        if (this.submitting) return;
        this.error = "";
        if (
          !this.workflow &&
          (!this.name ||
            !this.submitterName ||
            !this.email ||
            !this.localityId ||
            !this.content.trim() ||
            !this.privacyAccepted)
        ) {
          this.error =
            "Uzupełnij wszystkie wymagane pola i wybierz miejscowość z listy.";
          return;
        }
        this.submitting = true;
        const token = document.querySelector(
          "[name=csrfmiddlewaretoken]",
        ).value;
        try {
          if (!this.workflow) {
            const response = await fetch(root.dataset.submitUrl, {
              method: "POST",
              headers: { "X-CSRFToken": token, Accept: "application/json" },
              body: new URLSearchParams({
                name: this.name,
                submitter_name: this.submitterName,
                email: this.email,
                locality: this.localityId,
                content: this.content,
                privacy_accepted: this.privacyAccepted ? "on" : "",
              }),
            });
            const data = await response.json();
            if (!response.ok) {
              this.error = Object.values(data.errors).flat().join(" ");
              return;
            }
            this.workflow = data;
          }
          for (const step of this.steps) {
            if (step.status === "completed") continue;
            if (!(await this.completeStep(step, token))) return;
            step.status = "completed";
            step.message = "gotowe";
          }
          window.location.assign(this.workflow.redirect_url);
        } catch {
          this.error = this.workflow
            ? "Zgłoszenie zapisano, ale połączenie podczas przetwarzania zostało przerwane. Wznów ocenę, aby kontynuować od bieżącego etapu."
            : "Nie można było zapisać zgłoszenia — sprawdź połączenie z internetem i wyślij formularz ponownie.";
        } finally {
          this.submitting = false;
        }
      },
    },
  }).mount("#idea-app");
});
