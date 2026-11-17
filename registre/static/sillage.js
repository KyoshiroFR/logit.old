const sectionNavigation = document.querySelector(".fiche-tabs");
const sectionButtons = [...sectionNavigation.querySelectorAll("button")];

function selectSection(selected) {
    for (const button of sectionButtons) {
        const active = button === selected;
        button.setAttribute("aria-pressed", String(active));
        document.getElementById(button.dataset.panel).hidden = !active;
    }
}

for (const button of sectionButtons) {
    button.addEventListener("click", () => selectSection(button));
}
selectSection(sectionButtons[0]);
sectionNavigation.hidden = false;
document.querySelector("[data-show-detail]")?.addEventListener("click", () => {
    selectSection(sectionButtons[0]);
});
