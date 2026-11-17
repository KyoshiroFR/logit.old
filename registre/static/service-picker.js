const picker = document.querySelector(".service-picker");
const serviceSearch = picker.querySelector(".services-search");
const selectedServices = picker.querySelector(".services-selected");
const serviceOptions = [...picker.querySelectorAll(".services-options label")];
const noServices = picker.querySelector(".services-empty");

function normalizeService(value) {
    return value.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("fr").trim();
}

function filterServices() {
    const query = normalizeService(serviceSearch.value);
    for (const option of serviceOptions) {
        option.hidden = !normalizeService(option.textContent).includes(query);
    }
    noServices.hidden = !query || serviceOptions.some(option => !option.hidden);
}

function showSelectedServices() {
    selectedServices.replaceChildren();
    for (const option of serviceOptions) {
        const checkbox = option.querySelector("input");
        if (!checkbox.checked) continue;
        const name = option.querySelector("span").textContent;
        const chip = document.createElement("button");
        chip.type = "button";
        chip.textContent = name + " ×";
        chip.setAttribute("aria-label", "Retirer " + name);
        chip.addEventListener("click", () => {
            checkbox.checked = false;
            showSelectedServices();
            serviceSearch.focus();
        });
        selectedServices.append(chip);
    }
    selectedServices.hidden = !selectedServices.childElementCount;
}

serviceSearch.hidden = !serviceOptions.length;
serviceSearch.addEventListener("input", filterServices);
serviceSearch.addEventListener("keydown", event => {
    if (event.key === "Enter") event.preventDefault();
});
picker.addEventListener("change", showSelectedServices);
window.addEventListener("pageshow", showSelectedServices);
showSelectedServices();
