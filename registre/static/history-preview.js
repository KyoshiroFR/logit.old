const workspace = document.querySelector(".history-workspace");
const panel = document.querySelector("#history-preview-content");
const status = document.querySelector("#history-preview-status");
const wideHistory = window.matchMedia("(min-width: 1100px)");
const originalPanel = "<p class=\"preview-placeholder\">Sélectionne une intervention pour lire sa fiche ici.</p>";
let previewRequest;

function markSelection(url) {
    const id = url.searchParams.get("fiche");
    for (const row of workspace.querySelectorAll(".history-row")) {
        if (id && new URL(row.dataset.previewUrl, url).searchParams.get("fiche") === id) {
            row.setAttribute("aria-current", "true");
        } else {
            row.removeAttribute("aria-current");
        }
    }
}

async function openPreview(url, addHistory, direction) {
    previewRequest?.abort();
    const controller = new AbortController();
    previewRequest = controller;
    if (!url.searchParams.has("fiche")) {
        panel.innerHTML = originalPanel;
        panel.removeAttribute("aria-busy");
        status.textContent = "";
        markSelection(url);
        return;
    }
    panel.setAttribute("aria-busy", "true");
    try {
        const response = await fetch(url, {headers: {"X-LogIT-Preview": "1"}, signal: controller.signal});
        if (!response.ok || response.redirected) throw new Error("Fiche indisponible");
        const markup = await response.text();
        if (controller.signal.aborted) return;
        panel.innerHTML = markup;
        panel.closest("aside").scrollTop = 0;
        markSelection(url);
        if (addHistory && location.href !== url.href) history.pushState(null, "", url);
        const title = panel.querySelector("h2");
        status.textContent = "Fiche ouverte : " + title.textContent;
        if (addHistory) {
            const nextFocus = direction ? panel.querySelector('[data-direction="' + direction + '"]') : null;
            (nextFocus || title).focus({preventScroll: true});
        }
    } catch (error) {
        if (!controller.signal.aborted) location.assign(url);
    } finally {
        if (previewRequest === controller) panel.removeAttribute("aria-busy");
    }
}

workspace.addEventListener("click", event => {
    const link = event.target.closest("a[data-preview-url]");
    if (!link || !wideHistory.matches || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    openPreview(new URL(link.dataset.previewUrl, location.href), true, link.dataset.direction);
});
window.addEventListener("popstate", () => openPreview(new URL(location.href), false));
