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

// ── Signaler un bug ──────────────────────────────────────────────────────────────────
async function detectBrowser() {
  const ua = navigator.userAgent;
  let browser = /Edg\/(\d+)/.test(ua) ? `Edge ${RegExp.$1}` : /Firefox\/(\d+)/.test(ua) ? `Firefox ${RegExp.$1}`
    : /Chrome\/(\d+)/.test(ua) ? `Chrome ${RegExp.$1}` : /Version\/(\d+).*Safari/.test(ua) ? `Safari ${RegExp.$1}` : "Navigateur inconnu";
  if (navigator.brave) browser = browser.replace("Chrome", "Brave");
  let system = /Windows/.test(ua) ? "Windows" : /Mac OS X/.test(ua) ? "macOS" : /Android/.test(ua) ? "Android" : /Linux/.test(ua) ? "Linux" : "";
  try {
    if (system === "Windows" && navigator.userAgentData?.getHighEntropyValues) {
      const { platformVersion } = await navigator.userAgentData.getHighEntropyValues(["platformVersion"]);
      system = parseInt(platformVersion, 10) >= 13 ? "Windows 11" : "Windows 10";
    }
  } catch (_) { /* détection facultative */ }
  return [browser, system, `${window.screen.width}×${window.screen.height}`].filter(Boolean).join(", ");
}

function initBugForm(form) {
  const zone = form.querySelector(".dropzone");
  const input = form.querySelector("input[type=file][name=screenshot]");
  const title = zone.querySelector("[data-dz-title]");
  const sub = zone.querySelector("[data-dz-sub]");
  const thumb = zone.querySelector(".dz-thumb");
  const remove = zone.querySelector(".dz-remove");
  const accepted = ["image/png", "image/jpeg", "image/webp"];
  const show = () => {
    const file = input.files[0];
    zone.classList.toggle("has-file", Boolean(file));
    title.textContent = file ? file.name : "Joindre une capture";
    sub.textContent = file ? "Capture jointe" : "Clique, glisse une image ou colle-la avec Ctrl+V";
    thumb.hidden = remove.hidden = !file;
    if (file) thumb.src = URL.createObjectURL(file);
  };
  const setFile = (file) => {
    if (!file || !accepted.includes(file.type)) return;
    const named = file.name && file.name !== "image.png" ? file
      : new File([file], `capture-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.png`, { type: file.type });
    const dt = new DataTransfer(); dt.items.add(named); input.files = dt.files; show();
  };
  form.setFile = setFile;
  input.addEventListener("change", show);
  remove.addEventListener("click", (e) => { e.preventDefault(); input.value = ""; show(); });
  ["dragenter", "dragover"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach((t) => zone.addEventListener(t, () => zone.classList.remove("dragging")));
  zone.addEventListener("drop", (e) => { e.preventDefault(); setFile(e.dataTransfer.files[0]); });
  const env = form.querySelector("[data-detect-browser]");
  if (env && !env.value) detectBrowser().then((v) => { if (!env.value) env.value = v; });
  return { show };
}

function initBugReport() {
  document.querySelectorAll(".bug-form").forEach((form) => { form.bug = initBugForm(form); });
  const dialog = document.getElementById("bug-dialog");
  if (!dialog || typeof dialog.showModal !== "function") return;
  const form = dialog.querySelector("form");
  const body = dialog.querySelector(".bug-body");
  const done = dialog.querySelector(".bug-done");
  const errors = dialog.querySelector(".bug-errors");
  const submit = dialog.querySelector(".bug-submit");

  const open = () => {
    body.hidden = false; done.hidden = true; errors.hidden = true;
    form.querySelector("input[name=page]").value = window.location.pathname + window.location.search;
    dialog.showModal();
    form.querySelector("input[name=title]").focus();
  };
  document.querySelectorAll("[data-open-bug]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); open(); }));
  dialog.querySelectorAll("[data-bug-close]").forEach((b) => b.addEventListener("click", () => dialog.close()));
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });  // clic sur le fond
  // Coller une capture quand la fenêtre est ouverte : elle va au signalement, pas à la fiche derrière.
  document.addEventListener("paste", (e) => {
    if (!dialog.open) return;
    const file = Array.from(e.clipboardData?.files || [])[0];
    if (!file) return;
    e.preventDefault(); e.stopImmediatePropagation();
    form.setFile(file);
  }, true);

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    submit.classList.add("loading");
    errors.hidden = true;
    fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
      .then(async (r) => ({ status: r.status, data: await r.json().catch(() => null) }))
      .then(({ status, data }) => {
        submit.classList.remove("loading");
        if (data?.ok) {
          dialog.querySelector("[data-bug-id]").textContent = `n° ${data.id}`;
          body.hidden = true; done.hidden = false;
          form.reset(); form.bug.show();
          const env = form.querySelector("[data-detect-browser]");
          detectBrowser().then((v) => { env.value = v; });
          return;
        }
        if (status === 400 && data?.errors) {
          errors.textContent = Object.values(data.errors).flat().join(" ");
          errors.hidden = false;
          return;
        }
        form.submit();  // repli : envoi classique
      })
      .catch(() => { submit.classList.remove("loading"); form.submit(); });
  });
}

// Liens portés par des boutons radio (filtres de la liste des bugs).
document.addEventListener("change", (e) => {
  if (e.target.matches("input[data-href]")) window.location.search = e.target.dataset.href.slice(1);
});
document.addEventListener("DOMContentLoaded", initBugReport);
