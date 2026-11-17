const picker = document.querySelector(".service-picker");
const serviceDisclosure = picker.querySelector(".services-disclosure");
const serviceSummary = serviceDisclosure.querySelector("summary");
const serviceSearch = picker.querySelector(".services-search");
const selectedServices = picker.querySelector(".services-selected");
const serviceCount = picker.querySelector(".services-count");
const noServices = picker.querySelector(".services-empty");

function normalizeService(value) {
    return value.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("fr").trim();
}

const serviceOptions = [...picker.querySelectorAll(".services-options label")].map(label => ({
    label,
    checkbox: label.querySelector("input"),
    name: label.querySelector("span").textContent,
    searchValue: normalizeService(label.querySelector("span").textContent),
}));

function filterServices() {
    const query = normalizeService(serviceSearch.value);
    for (const { label, searchValue } of serviceOptions) {
        label.hidden = !searchValue.includes(query);
    }
    noServices.hidden = !query || serviceOptions.some(({ label }) => !label.hidden);
}

function showSelectedServices() {
    selectedServices.replaceChildren();
    for (const { checkbox, name } of serviceOptions) {
        if (!checkbox.checked) continue;
        const item = document.createElement("li");
        const chip = document.createElement("button");
        chip.type = "button";
        chip.append(name, " ×");
        chip.setAttribute("aria-label", "Retirer " + name);
        chip.addEventListener("click", () => {
            checkbox.checked = false;
            showSelectedServices();
            (serviceDisclosure.open ? serviceSearch : serviceSummary).focus();
        });
        item.append(chip);
        selectedServices.append(item);
    }
    const count = selectedServices.childElementCount;
    selectedServices.hidden = count === 0;
    serviceCount.hidden = count === 0;
    serviceCount.textContent = count === 1 ? "1 sélectionné" : count + " sélectionnés";
}

serviceSearch.hidden = !serviceOptions.length;
serviceSearch.addEventListener("input", filterServices);
serviceSearch.addEventListener("keydown", event => {
    if (event.key === "Enter") event.preventDefault();
});
serviceDisclosure.addEventListener("keydown", event => {
    if (event.key === "Escape" && serviceDisclosure.open) {
        serviceDisclosure.open = false;
        event.preventDefault();
        serviceSummary.focus();
    }
});
picker.addEventListener("change", event => {
    if (event.target.matches(".services-options input")) showSelectedServices();
});
window.addEventListener("pageshow", () => {
    showSelectedServices();
    filterServices();
});
showSelectedServices();
