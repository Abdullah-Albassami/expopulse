/* ExpoPulse — interface behaviour only.
   Priority, duplicates and team assignment are decided by the Django
   backend. This file only draws and filters what the page already has. */

(function () {
    "use strict";

    /* ---------- clock (every page) ---------- */
    var clock = document.getElementById("live-clock");
    if (clock) {
        var tick = function () { clock.textContent = new Date().toLocaleTimeString("en-GB"); };
        tick();
        setInterval(tick, 1000);
    }

    /* "In Progress", "in_progress" and "IN-PROGRESS" all become "in-progress",
       so the styling works whichever way the backend stores the value. */
    var norm = function (value) { return String(value || "").trim().toLowerCase().replace(/[\s_]+/g, "-"); };
    var ORDER = ["new", "assigned", "in-progress", "resolved"];

    document.querySelectorAll("[data-priority]").forEach(function (el) { el.dataset.priority = norm(el.dataset.priority); });
    document.querySelectorAll("[data-status]").forEach(function (el) { el.dataset.status = norm(el.dataset.status); });

    /* ---------- incident detail: mark where the incident is in its steps ---------- */
    document.querySelectorAll("ol.steps[data-status]").forEach(function (list) {
        var at = ORDER.indexOf(list.dataset.status);
        list.querySelectorAll("li").forEach(function (li, i) {
            li.className = at < 0 ? "" : i < at ? "is-done" : i === at ? "is-current" : "";
            if (i === at) { li.setAttribute("aria-current", "step"); }
        });
    });

    /* ---------- incident list: reload as soon as a filter changes ---------- */
    document.querySelectorAll("form[data-auto-submit] select").forEach(function (select) {
        select.addEventListener("change", function () { select.form.submit(); });
    });

    /* ---------- ask before important actions: add data-confirm="Question?" ---------- */
    document.addEventListener("submit", function (event) {
        var question = event.target.getAttribute("data-confirm");
        if (question && !window.confirm(question)) { event.preventDefault(); }
    });

    /* ---------- create form: point at the first empty required field ---------- */
    document.querySelectorAll("form[data-validate]").forEach(function (form) {
        form.setAttribute("novalidate", "");
        form.addEventListener("submit", function (event) {
            var first = null;
            form.querySelectorAll("[required]").forEach(function (input) {
                var field = input.closest(".field");
                var bad = !input.value.trim() || (input.type === "number" && Number(input.value) < 0);
                if (!field) { return; }
                field.classList.toggle("has-error", bad);
                var old = field.querySelector(".js-error");
                if (old) { old.remove(); }
                if (bad) {
                    var msg = document.createElement("span");
                    msg.className = "error js-error";
                    msg.textContent = input.value.trim() ? "Enter zero or more." : "Fill this in before sending.";
                    field.appendChild(msg);
                    first = first || input;
                }
            });
            if (first) { event.preventDefault(); first.focus(); }
        });
    });

    /* ---------- dashboard: tiles, charts and table ---------- */
    var table = document.getElementById("dash-list");
    if (!table) { return; }                        // not on the dashboard

    var byId = function (id) { return document.getElementById(id); };
    var dash = byId("dash");
    var rows = Array.prototype.slice.call(table.querySelectorAll("tbody tr"));
    var open = rows.filter(function (r) { return r.dataset.status !== "resolved"; });
    var count = function (list, key, value) { return list.filter(function (r) { return r.dataset[key] === value; }).length; };

    /* a whole row opens its incident */
    rows.forEach(function (row) {
        row.addEventListener("click", function (event) {
            if (!event.target.closest("a")) { window.location.href = row.dataset.url; }
        });
    });

    /* bars: open incidents by priority */
    var bars = Array.prototype.slice.call(document.querySelectorAll(".vbar"));
    var tallest = Math.max.apply(null, bars.map(function (b) { return count(open, "priority", b.dataset.priority); }).concat(1));
    bars.forEach(function (bar) {
        var n = count(open, "priority", bar.dataset.priority);
        bar.querySelector(".vbar-num").textContent = n;
        bar.querySelector(".vbar-fill").style.height = (n / tallest * 100) + "%";
        bar.setAttribute("aria-label", bar.querySelector(".vbar-name").textContent + ": " + n + " open. Show only these.");
        bar.addEventListener("click", function () { toggle("priority", bar.dataset.priority, bar); });
    });

    /* donut: every incident by status */
    var legend = Array.prototype.slice.call(document.querySelectorAll(".legend-btn"));
    var svg = document.querySelector(".donut svg");
    var R = 40, around = 2 * Math.PI * R, used = 0, total = rows.length;
    legend.forEach(function (btn) {
        var status = btn.dataset.status, n = count(rows, "status", status);
        btn.querySelector("b").textContent = n;
        btn.addEventListener("click", function () { toggle("status", status, btn); });
        if (!n || !svg) { return; }
        var arc = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        var length = n / total * around, gap = total > n ? 1.5 : 0;
        arc.setAttribute("cx", 50); arc.setAttribute("cy", 50); arc.setAttribute("r", R);
        arc.setAttribute("stroke-dasharray", Math.max(length - gap, 0.5) + " " + around);
        arc.setAttribute("stroke-dashoffset", -used);
        arc.dataset.status = status;
        arc.addEventListener("click", function () { toggle("status", status, btn); });
        var tip = document.createElementNS("http://www.w3.org/2000/svg", "title");
        tip.textContent = btn.querySelector(".legend-name").textContent + ": " + n;
        arc.appendChild(tip);
        svg.appendChild(arc);
        used += length;
    });
    var centerNum = byId("donut-num"), centerText = byId("donut-text");
    if (centerNum) { centerNum.textContent = total; }

    /* tiles */
    document.querySelectorAll("button.tile").forEach(function (tile) {
        tile.addEventListener("click", function () {
            if (tile.dataset.priority) { toggle("priority", tile.dataset.priority, tile); } else { filter(null); }
        });
    });

    function toggle(key, value, control) {
        var same = current.key === key && current.value === value;
        filter(same ? null : key, value);
    }

    /* One filter at a time: key is "priority" or "status"; null shows everything.
       Tiles, bars, the donut and its legend all go through here, so they stay in step. */
    var current = {};
    function filter(key, value) {
        var on = !!key;
        current = on ? { key: key, value: value } : {};
        dash.classList.toggle("is-filtering", on);

        document.querySelectorAll(".vbar, button.tile[data-priority]").forEach(function (el) {
            el.setAttribute("aria-pressed", on && key === "priority" && el.dataset.priority === value ? "true" : "false");
        });
        legend.forEach(function (btn) {
            btn.setAttribute("aria-pressed", on && key === "status" && btn.dataset.status === value ? "true" : "false");
        });
        document.querySelectorAll(".donut circle").forEach(function (arc) {
            arc.classList.toggle("is-on", on && key === "status" && arc.dataset.status === value);
        });

        var shown = 0;
        rows.forEach(function (row) {
            /* a priority filter looks at open incidents only, like the bars do */
            var match = !on || (row.dataset[key] === value && (key !== "priority" || row.dataset.status !== "resolved"));
            row.hidden = !match;
            if (match) { shown += 1; }
        });

        var name = "";
        if (on) {
            var source = key === "status"
                ? document.querySelector('.legend-btn[data-status="' + value + '"] .legend-name')
                : document.querySelector('.vbar[data-priority="' + value + '"] .vbar-name');
            name = source ? source.textContent : value;
        }
        byId("list-title").textContent = on ? name + ": " + shown + (shown === 1 ? " incident" : " incidents") : "Most urgent first";
        byId("clear-filter").hidden = !on;
        byId("none-match").hidden = shown > 0;
        if (centerNum) {
            centerNum.textContent = on && key === "status" ? shown : total;
            centerText.textContent = on && key === "status" ? name.toLowerCase() : "today";
        }
        if (on) { byId("list-card").scrollIntoView({ block: "nearest", behavior: "smooth" }); }
    }

    byId("clear-filter").addEventListener("click", function () { filter(null); });
})();
