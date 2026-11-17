const input = document.querySelector("#id_attachments");
const form = input.form;
const list = document.querySelector("#pending-captures");
const status = document.querySelector("#capture-status");
let pending = [];
let previews = [];

function update(files) {
    input.closest("details").open = true;
    if (files.length > 10) {
        status.textContent = "Tu peux ajouter jusqu’à 10 captures.";
        return;
    }
    const transfer = new DataTransfer();
    list.replaceChildren();
    for (const preview of previews) URL.revokeObjectURL(preview);
    previews = [];
    pending = files;

    for (const [index, file] of pending.entries()) {
        transfer.items.add(file);
        const row = document.createElement("li");
        const label = document.createElement("span");
        label.textContent = file.name;
        const thumbnail = document.createElement("img");
        const preview = URL.createObjectURL(file);
        previews.push(preview);
        thumbnail.src = preview;
        thumbnail.alt = "";
        thumbnail.addEventListener("error", () => { thumbnail.hidden = true; }, { once: true });
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "Retirer";
        remove.setAttribute("aria-label", "Retirer " + file.name);
        remove.addEventListener("click", () => {
            update(pending.filter((_, position) => position !== index));
            list.children[index]?.querySelector("button")?.focus();
            if (!list.children[index]) input.focus();
        });
        row.append(thumbnail, label, remove);
        list.append(row);
    }
    input.files = transfer.files;
    status.textContent = pending.length ? pending.length + " capture(s) à enregistrer." : "";
}

input.addEventListener("change", () => {
    const chosen = [...input.files];
    if (pending.length + chosen.length > 10) {
        update(pending);
        status.textContent = "Tu peux ajouter jusqu’à 10 captures.";
        return;
    }
    update([...pending, ...chosen]);
});

form.addEventListener("paste", event => {
    const images = [...(event.clipboardData?.files ?? [])].filter(file => file.type.startsWith("image/"));
    if (!images.length) return;
    event.preventDefault();
    update([...pending, ...images]);
});
