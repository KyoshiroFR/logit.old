const search = document.querySelector("#id_q");
if (search) {
    const shortcut = document.querySelector(".search-shortcut");
    if (shortcut) shortcut.hidden = false;
    search.setAttribute("aria-keyshortcuts", "Control+K Meta+K");
    document.addEventListener("keydown", event => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k" && !document.querySelector("dialog[open]")) {
            event.preventDefault();
            search.focus();
            search.select();
        }
    });
}

const sectionNavigation = document.querySelector(".fiche-tabs");
if (sectionNavigation) {
    const tabs = [...sectionNavigation.querySelectorAll("button")];

    function selectSection(tab) {
        for (const button of tabs) {
            const active = button === tab;
            button.setAttribute("aria-selected", String(active));
            button.tabIndex = active ? 0 : -1;
            document.getElementById(button.dataset.panel).hidden = !active;
        }
    }

    sectionNavigation.setAttribute("role", "tablist");
    for (const tab of tabs) {
        const panel = document.getElementById(tab.dataset.panel);
        tab.id = "tab-" + panel.id;
        tab.setAttribute("role", "tab");
        panel.setAttribute("role", "tabpanel");
        panel.setAttribute("aria-labelledby", tab.id);
        panel.tabIndex = 0;
        tab.addEventListener("click", () => selectSection(tab));
    }
    sectionNavigation.addEventListener("keydown", event => {
        const current = tabs.indexOf(event.target);
        const next = {
            ArrowRight: (current + 1) % tabs.length,
            ArrowLeft: (current - 1 + tabs.length) % tabs.length,
            Home: 0, End: tabs.length - 1,
        }[event.key];
        if (current < 0 || next === undefined) return;
        event.preventDefault();
        selectSection(tabs[next]);
        tabs[next].focus();
    });
    selectSection(tabs[0]);
    sectionNavigation.hidden = false;
    document.querySelector("[data-show-detail]")?.addEventListener("click", () => {
        selectSection(tabs[0]);
        document.querySelector(".sillage-description").open = true;
    });
}

const map = document.querySelector(".clair-map");
if (map) {
    const graph = map.querySelector(".prisme-graph");
    const source = graph.querySelector(".prisme-node");
    const equipment = graph.querySelector(".prisme-equipment");
    const services = [...graph.querySelectorAll(".prisme-services li")];
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "prisme-links");
    svg.setAttribute("aria-hidden", "true");
    graph.prepend(svg);
    graph.classList.add("prisme-enhanced");

    function drawLinks() {
        const rect = graph.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        svg.setAttribute("viewBox", `0 0 ${rect.width} ${rect.height}`);
        svg.replaceChildren();

        const first = source.getBoundingClientRect();
        const second = equipment.getBoundingClientRect();
        const vertical = second.top >= first.bottom;
        function point(node, outgoing) {
            const box = node.getBoundingClientRect();
            return vertical
                ? [box.left - rect.left + box.width / 2, (outgoing ? box.bottom : box.top) - rect.top]
                : [(outgoing ? box.right : box.left) - rect.left, box.top - rect.top + box.height / 2];
        }

        function connect(start, finish) {
            const [x1, y1] = start;
            const [x2, y2] = finish;
            const mx = (x1 + x2) / 2;
            const my = (y1 + y2) / 2;
            const path = document.createElementNS(svg.namespaceURI, "path");
            path.setAttribute("d", vertical
                ? `M ${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${y2}`
                : `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`);
            svg.append(path);
            const dot = document.createElementNS(svg.namespaceURI, "circle");
            dot.setAttribute("cx", x2);
            dot.setAttribute("cy", y2);
            dot.setAttribute("r", 3);
            svg.append(dot);
        }
        connect(point(source, true), point(equipment, false));
        if (vertical && services.length) {
            connect(point(equipment, true), point(graph.querySelector(".prisme-services"), false));
        } else {
            for (const service of services) connect(point(equipment, true), point(service, false));
        }
    }

    const observer = new ResizeObserver(drawLinks);
    for (const node of [graph, source, equipment, ...services]) observer.observe(node);
    const expand = document.querySelector("[data-expand-map]");
    const dialog = document.querySelector(".prisme-dialog");
    const anchor = document.createComment("Emplacement de la carte");
    map.before(anchor);
    expand.addEventListener("click", () => {
        dialog.append(map);
        dialog.showModal();
    });
    dialog.addEventListener("close", () => {
        anchor.after(map);
        expand.focus();
    });
    expand.hidden = false;
}
const profileMenu = document.querySelector(".account-menu");
if (profileMenu) {
    document.addEventListener("click", event => {
        if (profileMenu.open && !profileMenu.contains(event.target)) profileMenu.open = false;
    });
    profileMenu.addEventListener("keydown", event => {
        if (event.key === "Escape" && profileMenu.open) {
            profileMenu.open = false;
            profileMenu.querySelector("summary").focus();
        }
    });
}
