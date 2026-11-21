// LogIT 2.2 — interactions. Tout fonctionne sans JavaScript ; ce fichier ajoute la fluidité.
"use strict";
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// ── Surbrillance glissante : barre du haut et groupes segmentés ─────────────────────────
function slider(container, itemSelector, isActive, classes = "slider") {
  const items = Array.from(container.querySelectorAll(itemSelector));
  if (!items.length) return null;
  const bar = document.createElement("span");
  bar.className = classes;
  bar.setAttribute("aria-hidden", "true");
  container.appendChild(bar);
  container.classList.add("js");
  const moveTo = (item) => {
    if (!item) { bar.classList.remove("ready"); return; }
    bar.style.width = `${item.offsetWidth}px`;
    bar.style.transform = `translateX(${item.offsetLeft}px)`;
    if (container.classList.contains("segmented")) {  // un groupe peut passer sur plusieurs lignes
      bar.style.top = `${item.offsetTop}px`;
      bar.style.height = `${item.offsetHeight}px`;
    }
    bar.classList.add("ready");
  };
  const reset = () => moveTo(items.find(isActive));
  // Premier placement sans animation : l'indicateur apparaît directement sous l'élément actif.
  const place = () => {
    bar.style.transition = "none";
    reset();
    bar.getBoundingClientRect();
    requestAnimationFrame(() => { bar.style.transition = ""; });
  };
  return { bar, items, moveTo, reset, place };
}

function initNav() {
  const nav = document.querySelector(".nav");
  if (!nav) return;
  const active = (a) => a.classList.contains("active");
  const hover = slider(nav, "a", active, "slider slider-bg");
  const line = slider(nav, "a", active, "slider");
  hover.bar.classList.remove("ready");
  line.place();
  hover.items.forEach((a) => {
    a.addEventListener("mouseenter", () => { hover.moveTo(a); line.moveTo(a); });
    a.addEventListener("focus", () => { hover.moveTo(a); line.moveTo(a); });
  });
  nav.addEventListener("mouseleave", () => { hover.bar.classList.remove("ready"); line.reset(); });
  window.addEventListener("resize", () => line.reset());
}

function initSegmented(root = document) {
  root.querySelectorAll(".segmented").forEach((group) => {
    if (group.dataset.ready) return;
    group.dataset.ready = "1";
    const s = slider(group, "label", (label) => label.querySelector("input")?.checked);
    if (!s) return;
    s.place();
    group.addEventListener("change", () => s.reset());
    window.addEventListener("resize", () => s.reset());
  });
}

// ── Registre : filtrage dynamique sans rechargement ───────────────────────────────────
function initLiveFilters() {
  const form = document.getElementById("filters");
  const results = document.getElementById("results");
  if (!form || !results) return;
  let controller = null;
  let timer = null;

  const load = (url, push = true) => {
    controller?.abort();
    controller = new AbortController();
    results.classList.add("loading");
    const fragmentUrl = url + (url.includes("?") ? "&" : "?") + "fragment=1";
    fetch(fragmentUrl, { signal: controller.signal, headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then((html) => {
        results.innerHTML = html;
        results.classList.remove("loading");
        if (!reduceMotion) {
          results.querySelectorAll(".entry").forEach((entry, i) => {
            entry.style.animationDelay = `${Math.min(i, 8) * 25}ms`;
            entry.classList.add("enter");
          });
        }
        initEntries(results);
        if (push) history.replaceState(null, "", url);
      })
      .catch((error) => { if (error.name !== "AbortError") window.location.href = url; });
  };
  const fromForm = () => {
    const params = new URLSearchParams(new FormData(form));
    for (const [key, value] of Array.from(params.entries())) if (!value) params.delete(key);
    const query = params.toString();
    return window.location.pathname + (query ? `?${query}` : "");
  };

  form.addEventListener("input", (event) => {
    if (event.target.type === "search") {
      clearTimeout(timer);
      timer = setTimeout(() => load(fromForm()), 250);
    }
  });
  form.addEventListener("change", (event) => { if (event.target.type !== "search") load(fromForm()); });
  form.addEventListener("submit", (event) => { event.preventDefault(); load(fromForm()); });
  form.querySelector("[data-reset]")?.addEventListener("click", (event) => {
    event.preventDefault();
    form.reset();
    form.querySelectorAll("input[type=search]").forEach((i) => { i.value = ""; });
    form.querySelectorAll(".segmented input[value='']").forEach((i) => { i.checked = true; });
    form.querySelectorAll("select").forEach((s) => { s.selectedIndex = 0; });
    form.querySelectorAll(".segmented").forEach((g) => g.dispatchEvent(new Event("change")));
    load(window.location.pathname);
  });
  results.addEventListener("click", (event) => {
    const link = event.target.closest(".pager a");
    if (!link) return;
    event.preventDefault();
    load(link.getAttribute("href"));
    document.querySelector(".results-anchor")?.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth" });
  });
  // « / » place le curseur dans la recherche, comme dans la plupart des outils d'administration.
  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) {
      event.preventDefault();
      form.querySelector("input[type=search]")?.focus();
    }
  });
}

// ── Détail déployable d'une intervention ─────────────────────────────────────────────
function initEntries(root = document) {
  root.querySelectorAll(".entry [data-preview]").forEach((button) => {
    if (button.dataset.ready) return;
    button.dataset.ready = "1";
    const entry = button.closest(".entry");
    const target = entry.querySelector(".detail-inner");
    button.addEventListener("click", () => {
      const open = !entry.classList.contains("open");
      entry.classList.toggle("open", open);
      button.setAttribute("aria-expanded", String(open));
      button.firstChild.textContent = open ? "Masquer le détail " : "Voir le détail ";
      if (open && !target.dataset.loaded) {
        target.dataset.loaded = "1";
        fetch(button.dataset.preview, { credentials: "same-origin" })
          .then((r) => { if (!r.ok) throw new Error(r.status); return r.text(); })
          .then((html) => { target.innerHTML = html; })
          .catch(() => { target.dataset.loaded = ""; target.innerHTML = '<p class="notice danger">Détail indisponible. Ouvre la fiche complète.</p>'; });
      }
    });
  });
}

// ── Formulaire : filtre des éléments, rappel urgence, captures Ctrl+V ────────────────────
function initForm() {
  document.querySelectorAll("[data-filter-for]").forEach((input) => {
    const list = document.getElementById(input.dataset.filterFor);
    input.addEventListener("input", () => {
      const term = input.value.trim().toLowerCase();
      list.querySelectorAll(".chip").forEach((chip) => {
        chip.hidden = term !== "" && !chip.textContent.toLowerCase().includes(term) && !chip.querySelector("input").checked;
      });
      list.querySelectorAll(".chip-group").forEach((group) => {
        group.hidden = !group.querySelector(".chip:not([hidden])");
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
      files.push(file.name && file.name !== "image.png" ? file : new File([file], `capture-${stamp}.png`, { type: file.type }));
    }
    sync();
  };
  input.addEventListener("change", () => add(Array.from(input.files)));
  document.addEventListener("paste", (event) => {
    const images = Array.from(event.clipboardData?.files || []).filter((f) => accepted.includes(f.type));
    if (!images.length) return;
    event.preventDefault();
    const details = box.closest("details");
    if (details) details.open = true;
    add(images);
    box.classList.add("paste-flash");
    setTimeout(() => box.classList.remove("paste-flash"), 450);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initNav();
  initSegmented();
  initLiveFilters();
  initEntries();
  initForm();
});
