for (const field of document.querySelectorAll(".auth-card input[type='password']")) {
    const group = document.createElement("div");
    group.className = "password-control";
    field.before(group);
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("aria-controls", field.id);
    group.append(field, button);
    const label = field.labels[0]?.textContent.trim().replace(/\s*:\s*$/, "") || "Mot de passe";
    function setVisible(visible) {
        field.type = visible ? "text" : "password";
        const action = visible ? "Masquer" : "Afficher";
        button.textContent = action;
        button.setAttribute("aria-label", action + " — " + label);
    }
    button.addEventListener("click", () => setVisible(field.type === "password"));
    field.form.addEventListener("submit", () => setVisible(false));
    setVisible(false);
}
