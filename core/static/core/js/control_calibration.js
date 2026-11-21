const calibrationSelect = document.querySelector("[data-calibration-select]");
const calibrationEditors = document.querySelectorAll(
  "[data-calibration-editor]",
);

if (calibrationSelect && calibrationEditors.length) {
  calibrationSelect.addEventListener("change", () => {
    calibrationEditors.forEach((editor) => {
      editor.hidden =
        editor.dataset.calibrationEditor !== calibrationSelect.value;
    });
  });
}
