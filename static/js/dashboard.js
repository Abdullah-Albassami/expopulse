/* ExpoPulse frontend. Django remains the authority for incidents and teams. */
(function () {
    "use strict";
    const norm = value => String(value || "").trim().toLowerCase().replace(/[\s_]+/g, "-");
    const statusOrder = ["new", "assigned", "in-progress", "resolved"];
    const byId = id => document.getElementById(id);

    const clock = byId("live-clock");
    if (clock) {
        const tick = () => { clock.textContent = new Date().toLocaleTimeString("en-GB"); };
        tick();
        setInterval(tick, 1000);
    }

    document.querySelectorAll("[data-priority]").forEach(el => { el.dataset.priority = norm(el.dataset.priority); });
    document.querySelectorAll("[data-status]").forEach(el => { el.dataset.status = norm(el.dataset.status); });
    document.querySelectorAll("ol.steps[data-status]").forEach(list => {
        const index = statusOrder.indexOf(list.dataset.status);
        list.querySelectorAll("li").forEach((li, i) => {
            li.className = index < 0 ? "" : i < index ? "is-done" : i === index ? "is-current" : "";
            if (i === index) li.setAttribute("aria-current", "step");
        });
    });
    document.querySelectorAll("form[data-auto-submit] select").forEach(select => {
        select.addEventListener("change", () => select.form.submit());
    });
    document.addEventListener("submit", event => {
        const question = event.target.getAttribute("data-confirm");
        if (question && !window.confirm(question)) event.preventDefault();
    });
    document.querySelectorAll("form[data-validate]").forEach(form => {
        form.setAttribute("novalidate", "");
        form.addEventListener("submit", event => {
            let first = null;
            form.querySelectorAll("[required]").forEach(input => {
                const field = input.closest(".field");
                if (!field) return;
                const bad = !input.value.trim() || (input.type === "number" && Number(input.value) < 0);
                field.classList.toggle("has-error", bad);
                const old = field.querySelector(".js-error");
                if (old) old.remove();
                if (bad) {
                    const msg = document.createElement("span");
                    msg.className = "error js-error";
                    msg.textContent = input.value.trim() ? "Enter zero or more." : "Fill this in before sending.";
                    field.appendChild(msg);
                    if (!first) first = input;
                }
            });
            if (first) { event.preventDefault(); first.focus(); }
        });
    });

    const dash = byId("dash");
    const table = byId("dash-list");
    if (!dash || !table) return;
    const tbody = table.querySelector("tbody");
    const bars = [...dash.querySelectorAll(".vbar")];
    const legend = [...dash.querySelectorAll(".legend-btn")];
    const svg = dash.querySelector(".donut svg");
    const state = byId("live-state");
    const toast = byId("live-toast");
    let current = {};
    let rows = [];
    let knownIds = null;
    let newIncidentCount = 0;
    let busy = false;
    const count = (items, key, value) => items.filter(r => r.dataset[key] === value).length;

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function renderRow(item) {
        const tr = el("tr");
        tr.dataset.priority = norm(item.priority);
        tr.dataset.status = norm(item.status);
        tr.dataset.url = item.url;
        tr.appendChild(el("td", "num", `#${item.id}`));
        const titleCell = el("td", "title");
        const link = el("a", "", item.title);
        link.href = item.url;
        titleCell.appendChild(link);
        if (item.duplicate_of) titleCell.appendChild(el("span", "dupe", ` ⚠ Possible duplicate of #${item.duplicate_of}`));
        tr.appendChild(titleCell);
        const typeCell = el("td", "", item.type);
        if (item.module) typeCell.appendChild(el("small", "ops-module", item.module));
        tr.appendChild(typeCell);
        tr.appendChild(el("td", "", item.location));
        const priorityCell = el("td");
        const priorityPill = el("span", "pill", item.priority_label);
        priorityPill.dataset.priority = norm(item.priority);
        priorityCell.appendChild(priorityPill);
        tr.appendChild(priorityCell);
        const statusCell = el("td");
        const statusPill = el("span", "status-dot", item.status_label);
        statusPill.dataset.status = norm(item.status);
        statusCell.appendChild(statusPill);
        tr.appendChild(statusCell);
        tr.appendChild(el("td", "", item.team));
        const timeCell = el("td", "when");
        const time = el("time", "", item.created_time);
        time.dateTime = item.created_at;
        timeCell.appendChild(time);
        tr.appendChild(timeCell);
        tr.addEventListener("click", event => {
            if (!event.target.closest("a")) window.location.href = item.url;
        });
        return tr;
    }

    function refreshCharts() {
        const open = rows.filter(r => r.dataset.status !== "resolved");
        const maximum = Math.max(1, ...bars.map(bar => count(open, "priority", bar.dataset.priority)));
        bars.forEach(bar => {
            const n = count(open, "priority", bar.dataset.priority);
            bar.querySelector(".vbar-num").textContent = n;
            bar.querySelector(".vbar-fill").style.height = `${n / maximum * 100}%`;
            bar.setAttribute("aria-label", `${bar.querySelector(".vbar-name").textContent}: ${n} open incidents`);
        });
        svg.replaceChildren();
        const radius = 40;
        const circumference = 2 * Math.PI * radius;
        let used = 0;
        legend.forEach(button => {
            const n = count(rows, "status", button.dataset.status);
            button.querySelector("b").textContent = n;
            if (!n || !rows.length) return;
            const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
            const length = n / rows.length * circumference;
            circle.setAttribute("cx", "50");
            circle.setAttribute("cy", "50");
            circle.setAttribute("r", String(radius));
            circle.setAttribute("stroke-dasharray", `${Math.max(length - (n < rows.length ? 1.5 : 0), 0.5)} ${circumference}`);
            circle.setAttribute("stroke-dashoffset", String(-used));
            circle.dataset.status = button.dataset.status;
            circle.addEventListener("click", () => toggle("status", button.dataset.status));
            const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
            title.textContent = `${button.querySelector(".legend-name").textContent}: ${n}`;
            circle.appendChild(title);
            svg.appendChild(circle);
            used += length;
        });
        byId("donut-num").textContent = rows.length;
    }

    function applyFilter() {
        const on = !!current.key;
        dash.classList.toggle("is-filtering", on);
        dash.querySelectorAll(".vbar, button.tile[data-priority]").forEach(item => {
            item.setAttribute("aria-pressed", String(on && current.key === "priority" && item.dataset.priority === current.value));
        });
        legend.forEach(item => {
            item.setAttribute("aria-pressed", String(on && current.key === "status" && item.dataset.status === current.value));
        });
        svg.querySelectorAll("circle").forEach(item => {
            item.classList.toggle("is-on", on && current.key === "status" && item.dataset.status === current.value);
        });
        let shown = 0;
        rows.forEach(row => {
            const match = !on || (row.dataset[current.key] === current.value && (current.key !== "priority" || row.dataset.status !== "resolved"));
            row.hidden = !match;
            if (match) shown++;
        });
        let label = "";
        if (on) {
            const control = current.key === "status"
                ? legend.find(item => item.dataset.status === current.value)
                : bars.find(item => item.dataset.priority === current.value);
            label = control ? control.querySelector(current.key === "status" ? ".legend-name" : ".vbar-name").textContent : current.value;
        }
        byId("list-title").textContent = on ? `${label}: ${shown} incident${shown === 1 ? "" : "s"}` : "Most urgent first";
        byId("clear-filter").hidden = !on;
        byId("none-match").hidden = shown > 0;
        byId("donut-num").textContent = on && current.key === "status" ? shown : rows.length;
        byId("donut-text").textContent = on && current.key === "status" ? label.toLowerCase() : "total";
    }

    function toggle(key, value) {
        const same = current.key === key && current.value === value;
        current = same ? {} : { key, value };
        applyFilter();
        if (!same) byId("list-card").scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    bars.forEach(bar => bar.addEventListener("click", () => toggle("priority", bar.dataset.priority)));
    legend.forEach(button => button.addEventListener("click", () => toggle("status", button.dataset.status)));
    dash.querySelectorAll("button.tile").forEach(button => button.addEventListener("click", () => {
        if (button.dataset.priority) toggle("priority", button.dataset.priority);
        else { current = {}; applyFilter(); }
    }));
    byId("clear-filter").addEventListener("click", () => { current = {}; applyFilter(); });

    async function poll() {
        if (busy || document.hidden) return;
        busy = true;
        try {
            const response = await fetch(dash.dataset.feedUrl, {
                headers: { Accept: "application/json" },
                cache: "no-store",
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            const identifiers = new Set(data.incidents.map(item => item.id));
            if (knownIds !== null) {
                const added = data.incidents.filter(item => !knownIds.has(item.id));
                if (added.length) {
                    newIncidentCount += added.length;
                    const latest = added.reduce((a, b) => a.id > b.id ? a : b);
                    toast.replaceChildren();
                    toast.appendChild(document.createTextNode(
                        `${newIncidentCount} new incident${newIncidentCount === 1 ? "" : "s"} since opening this dashboard. Latest: `
                    ));
                    const link = document.createElement("a");
                    link.href = latest.url;
                    link.textContent = `#${latest.id} — ${latest.title}`;
                    toast.appendChild(link);
                    toast.hidden = false;
                }
            }
            knownIds = identifiers;
            const fragment = document.createDocumentFragment();
            data.incidents.forEach(item => fragment.appendChild(renderRow(item)));
            tbody.replaceChildren(fragment);
            rows = [...tbody.querySelectorAll("tr")];
            const ids = {
                critical_count: "critical-count",
                high_count: "high-count",
                active_count: "active-count",
                resolved_today_count: "resolved-count",
                available_team_count: "available-count",
            };
            Object.entries(ids).forEach(([key, id]) => { byId(id).textContent = data.counts[key]; });
            refreshCharts();
            applyFilter();
            state.textContent = `Live updates active · last checked ${new Date().toLocaleTimeString("en-GB")}`;
        } catch (error) {
            state.textContent = "Live update unavailable · retrying…";
            console.warn("ExpoPulse polling failed:", error);
        } finally {
            busy = false;
        }
    }
    poll();
    setInterval(poll, 5000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
})();
