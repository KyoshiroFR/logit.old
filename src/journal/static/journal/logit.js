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

// Captures : collage Ctrl+V, choix de fichiers, aperçu et retrait avant envoi.
document.addEventListener("DOMContentLoaded", () => {
  const input = document.getElementById("attachments");
  const box = document.getElementById("attachment-previews");
  if (!input || !box || typeof DataTransfer === "undefined") return;
  const accepted = ["image/png", "image/jpeg", "image/webp"];
  let files = [];
  const sync = () => {
    const dt = new DataTransfer();
    files.forEach((f) => dt.items.add(f));
    input.files = dt.files;
    box.replaceChildren(...files.map((file, index) => {
      const fig = document.createElement("figure");
      const img = document.createElement("img");
      img.src = URL.createObjectURL(file);
      img.alt = file.name;
      const cap = document.createElement("figcaption");
      cap.className = "small muted";
      cap.textContent = `${file.name} · ${Math.ceil(file.size / 1024)} Ko`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Retirer";
      remove.addEventListener("click", () => { files.splice(index, 1); sync(); });
      fig.append(img, cap, remove);
      return fig;
    }));
  };
  const add = (list) => {
    for (const file of list) {
      if (!accepted.includes(file.type)) continue;
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      const named = file.name && file.name !== "image.png" ? file : new File([file], `capture-${stamp}.png`, { type: file.type });
      files.push(named);
    }
    sync();
  };
  input.addEventListener("change", () => add(Array.from(input.files)));
  document.addEventListener("paste", (event) => {
    const images = Array.from(event.clipboardData?.files || []).filter((f) => accepted.includes(f.type));
    if (!images.length) return;
    event.preventDefault();
    add(images);
    box.classList.add("paste-flash");
    setTimeout(() => box.classList.remove("paste-flash"), 400);
  });
});
