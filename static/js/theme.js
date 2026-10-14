/* ExpoPulse visual preference only. No incident or dashboard state is modified. */
(function () {
    "use strict";
    const key = "expopulse-theme";
    const root = document.documentElement;
    const toggle = document.getElementById("theme-toggle");
    const menu = document.getElementById("theme-menu");
    const media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
    let preference = "system";

    try {
        const saved = localStorage.getItem(key);
        if (saved === "dark" || saved === "light") preference = saved;
    } catch (_) { /* Private browsing/storage-disabled: use system preference. */ }

    function apply() {
        const resolved = preference === "system" ? (media ? (media.matches ? "dark" : "light") : "dark") : preference;
        root.dataset.theme = resolved;
        root.style.colorScheme = resolved;
        if (toggle) {
            toggle.querySelector(".theme-icon").textContent = resolved === "dark" ? "☾" : "☀";
            toggle.setAttribute("aria-label", "Color theme: " + preference + ". Change color theme");
        }
        if (menu) menu.querySelectorAll("[data-theme-choice]").forEach(button => {
            const active = button.dataset.themeChoice === preference;
            button.setAttribute("aria-pressed", String(active));
        });
    }

    function closeMenu() {
        if (!menu || !toggle) return;
        menu.hidden = true;
        toggle.setAttribute("aria-expanded", "false");
    }

    if (toggle && menu) {
        toggle.addEventListener("click", () => {
            const opening = menu.hidden;
            menu.hidden = !opening;
            toggle.setAttribute("aria-expanded", String(opening));
            if (opening) menu.querySelector('[aria-pressed="true"]')?.focus();
        });
        menu.querySelectorAll("[data-theme-choice]").forEach(button => button.addEventListener("click", () => {
            preference = button.dataset.themeChoice;
            try {
                if (preference === "system") localStorage.removeItem(key);
                else localStorage.setItem(key, preference);
            } catch (_) { /* Theme remains active until this page is reloaded. */ }
            apply();
            closeMenu();
            toggle.focus();
        }));
        document.addEventListener("pointerdown", event => {
            if (!menu.hidden && !event.target.closest(".theme-control")) closeMenu();
        });
        document.addEventListener("keydown", event => {
            if (event.key === "Escape" && !menu.hidden) { closeMenu(); toggle.focus(); }
        });
    }
    if (media) {
        if (media.addEventListener) media.addEventListener("change", () => { if (preference === "system") apply(); });
        else if (media.addListener) media.addListener(() => { if (preference === "system") apply(); });
    }
    apply();
})();
