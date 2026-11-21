const editor = document.querySelector("[data-prompt-editor]");
const select = document.querySelector("[data-prompt-select]");
const promptData = document.getElementById("prompt-data");

if (editor && select && promptData) {
  const prompts = JSON.parse(promptData.textContent);
  const promptByKey = new Map(prompts.map((prompt) => [prompt.key, prompt]));
  const description = document.querySelector("[data-prompt-description]");
  const content = editor.querySelector("[data-prompt-content]");
  const button = editor.querySelector('button[type="submit"]');
  const status = editor.querySelector("[data-prompt-status]");
  let selectedKey = select.value;
  let savedContent = content.value;

  const showPrompt = (key) => {
    const prompt = promptByKey.get(key);
    if (!prompt) return;

    selectedKey = key;
    description.textContent = prompt.description;
    content.name = prompt.key;
    content.value = prompt.content;
    editor.action = prompt.update_url;
    savedContent = prompt.content;
    status.dataset.state = "";
    status.textContent = "";
  };

  select.addEventListener("change", () => {
    if (
      content.value !== savedContent &&
      !window.confirm("Masz niezapisane zmiany. Czy chcesz zmienić prompt?")
    ) {
      select.value = selectedKey;
      return;
    }
    showPrompt(select.value);
  });

  editor.addEventListener("submit", async (event) => {
    event.preventDefault();

    const csrfToken = editor.querySelector(
      '[name="csrfmiddlewaretoken"]',
    ).value;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    status.dataset.state = "";
    status.textContent = "Zapisywanie…";

    try {
      const response = await fetch(editor.action, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: new FormData(editor),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.error || "Nie udało się zapisać prompta.");
      }

      const prompt = promptByKey.get(selectedKey);
      prompt.content = content.value;
      savedContent = content.value;
      status.dataset.state = "success";
      status.textContent = result.message;
    } catch (error) {
      status.dataset.state = "error";
      status.textContent = error.message || "Nie udało się zapisać prompta.";
    } finally {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  });
}
