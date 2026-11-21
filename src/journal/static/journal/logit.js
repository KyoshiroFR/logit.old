// Filtre de la liste des éléments et rappel des champs facultatifs en urgence.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-filter-for]").forEach((input) => {
    const list = document.getElementById(input.dataset.filterFor);
    input.addEventListener("input", () => {
      const term = input.value.trim().toLowerCase();
      list.querySelectorAll("li").forEach((li) => {
        li.hidden = term !== "" && !li.textContent.toLowerCase().includes(term);
      });
    });
  });
  const hint = document.getElementById("urgent-hint");
  if (hint) {
    const update = () => {
      const checked = document.querySelector("input[name=kind]:checked");
      hint.hidden = !checked || checked.value !== "urgent";
    };
    document.querySelectorAll("input[name=kind]").forEach((r) => r.addEventListener("change", update));
    update();
  }
});
