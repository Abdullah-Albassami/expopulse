/* Live cameras page: plays each simulated CCTV HLS stream and keeps the
   "live / offline" badge and the last alert up to date. Read-only. */
(function () {
    "use strict";
    const grid = document.getElementById("cam-grid");
    if (!grid) return;
    const RETRY_MS = 5000;
    const players = new Map(); // camera id -> { hls, retry }

    const norm = value => String(value || "").trim().toLowerCase().replace(/[\s_]+/g, "-");

    function tile(id) { return grid.querySelector(`[data-camera="${id}"]`); }

    function setLive(el, live) {
        el.dataset.live = live ? "1" : "0";
        const badge = el.querySelector(".cam-badge");
        badge.dataset.state = live ? "live" : "offline";
        badge.querySelector(".cam-badge-text").textContent = live ? "LIVE" : "Offline";
        el.querySelector(".cam-offline").hidden = live;
    }

    function stop(id) {
        const p = players.get(id);
        if (!p) return;
        // Defer: destroying hls.js inside its own error callback breaks its internals.
        if (p.hls) { const h = p.hls; setTimeout(() => h.destroy(), 0); }
        clearTimeout(p.retry);
        players.delete(id);
        const video = tile(id).querySelector("video");
        video.removeAttribute("src");
        video.load();
    }

    function start(id) {
        if (players.has(id)) return;
        const el = tile(id);
        const video = el.querySelector("video");
        const url = el.dataset.playlist;
        const entry = { hls: null, retry: null };
        players.set(id, entry);

        const fail = () => {
            stop(id);
            setLive(el, false);
            players.set(id, { hls: null, retry: setTimeout(() => { players.delete(id); refresh(); }, RETRY_MS) });
        };

        if (window.Hls && window.Hls.isSupported()) {
            const hls = new window.Hls({ liveSyncDurationCount: 2, manifestLoadingMaxRetry: 2, levelLoadingMaxRetry: 2 });
            entry.hls = hls;
            hls.on(window.Hls.Events.ERROR, (_, data) => { if (data.fatal) fail(); });
            hls.loadSource(url);
            hls.attachMedia(video);
        } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
            video.src = url; // Safari plays HLS natively
            video.addEventListener("error", fail, { once: true });
        } else {
            setLive(el, false);
            return;
        }
        video.play().catch(() => { /* autoplay blocked: user can press play */ });
    }

    function renderAlert(el, alert) {
        const body = el.querySelector(".cam-alert-body");
        body.replaceChildren();
        if (!alert) {
            const none = document.createElement("span");
            none.className = "cam-alert-none";
            none.textContent = "No alerts from this camera yet.";
            body.appendChild(none);
            return;
        }
        const link = document.createElement("a");
        link.href = alert.url;
        link.textContent = `#${alert.id} ${alert.title}`;
        const tags = document.createElement("span");
        tags.className = "cam-alert-tags";
        const pill = document.createElement("span");
        pill.className = "pill";
        pill.dataset.priority = norm(alert.priority);
        pill.textContent = alert.priority_label;
        const state = document.createElement("span");
        state.className = "status-dot";
        state.dataset.status = norm(alert.status);
        state.textContent = alert.status_label;
        const time = document.createElement("time");
        time.textContent = alert.time;
        tags.append(pill, state, time);
        body.append(link, tags);
    }

    let busy = false;
    async function refresh() {
        if (busy || document.hidden) return;
        busy = true;
        try {
            const response = await fetch(grid.dataset.statusUrl, { headers: { Accept: "application/json" }, cache: "no-store" });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            data.cameras.forEach(cam => {
                const el = tile(cam.id);
                if (!el) return;
                const lastAlert = el.dataset.alertKey;
                const alertKey = cam.alert ? `${cam.alert.id}:${cam.alert.status}` : "";
                if (lastAlert !== alertKey) { renderAlert(el, cam.alert); el.dataset.alertKey = alertKey; }
                const waiting = players.get(cam.id) && !players.get(cam.id).hls && players.get(cam.id).retry;
                if (cam.live && !waiting) { setLive(el, true); start(cam.id); }
                if (!cam.live) { stop(cam.id); setLive(el, false); }
            });
        } catch (error) {
            console.warn("Live camera status failed:", error);
        } finally {
            busy = false;
        }
    }

    grid.querySelectorAll(".cam").forEach(el => {
        el.querySelector(".cam-full").addEventListener("click", () => {
            const screen = el.querySelector(".cam-screen");
            if (document.fullscreenElement) document.exitFullscreen();
            else if (screen.requestFullscreen) screen.requestFullscreen();
        });
        if (el.dataset.live === "1") start(el.dataset.camera);
    });

    setInterval(refresh, RETRY_MS);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
})();
