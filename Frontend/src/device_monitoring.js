(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const POLL_MS = 5000;

  let pollTimer = null;
  let lastError = "";

  function apiBase() {
    const cfg = window.platformConfig || {};
    if (cfg.monitorApiBaseUrl) return String(cfg.monitorApiBaseUrl).replace(/\/$/, "");
    const mode = String(cfg.monitorMode || "cloud").toLowerCase();
    if (mode === "wifi" || mode === "lan" || mode === "local") {
      return String(cfg.monitorWifiBaseUrl || cfg.apiBaseUrl || "http://127.0.0.1:8000").replace(
        /\/$/,
        ""
      );
    }
    return String(
      cfg.monitorCloudBaseUrl ||
        "https://device-monitor-50047269636.development.catalystappsail.in"
    ).replace(/\/$/, "");
  }

  function transportLabel() {
    const cfg = window.platformConfig || {};
    const mode = String(cfg.monitorMode || "cloud").toLowerCase();
    return mode === "wifi" || mode === "lan" || mode === "local" ? "wifi" : "cloud";
  }

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  function formatAgo(sec) {
    if (sec == null || Number.isNaN(Number(sec))) return "—";
    const s = Math.max(0, Math.round(Number(sec)));
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    return `${h}h ${m % 60}m ago`;
  }

  function formatBytes(bytes) {
    if (bytes == null || Number.isNaN(Number(bytes))) return "—";
    const n = Number(bytes);
    const units = ["B", "KB", "MB", "GB", "TB"];
    let v = n;
    let i = 0;
    while (v >= 1024 && i < units.length - 1) {
      v /= 1024;
      i += 1;
    }
    return `${v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
  }

  function batteryLabel(device) {
    if (device.battery_percent == null) return "—";
    const pct = Math.round(Number(device.battery_percent));
    const charge = device.charging === true ? " · charging" : "";
    return `${pct}%${charge}`;
  }

  function statusPill(device) {
    if (device.online) return `<span class="status-pill is-success">Online</span>`;
    return `<span class="status-pill is-failed">Offline</span>`;
  }

  function warnPill(text) {
    return `<span class="status-pill is-manual">${esc(text)}</span>`;
  }

  function okPill(text) {
    return `<span class="status-pill is-success">${esc(text)}</span>`;
  }

  function failPill(text) {
    return `<span class="status-pill is-failed">${esc(text)}</span>`;
  }

  function networkCell(n) {
    if (!n) return "—";
    const transport = (n.transport || "none").toUpperCase();
    const connected = n.connected === true;
    const validated = n.validated_internet === true;
    const pill = !connected ? failPill("Down") : validated ? okPill("OK") : warnPill("No net");
    return `<div class="dm-cell-main">${esc(transport)}</div><div class="dm-meta">${pill}</div>`;
  }

  function storageCell(s) {
    if (!s) return "—";
    const free = formatBytes(s.free_bytes);
    const total = formatBytes(s.total_bytes);
    const pct = s.free_percent != null ? `${Math.round(Number(s.free_percent))}% free` : "";
    const pill = s.low_storage ? warnPill("Low") : okPill("OK");
    return `<div class="dm-cell-main">${esc(free)} / ${esc(total)}</div><div class="dm-meta">${pill} ${esc(pct)}</div>`;
  }

  function memoryCell(m) {
    if (!m) return "—";
    const avail = formatBytes(m.available_bytes);
    const pct = m.available_percent != null ? `${Math.round(Number(m.available_percent))}% avail` : "";
    const app = m.app_used_bytes != null ? `app ${formatBytes(m.app_used_bytes)}` : "";
    const pill = m.low_memory ? warnPill("Low") : okPill("OK");
    return `<div class="dm-cell-main">${esc(avail)}</div><div class="dm-meta">${pill} ${esc(pct)}</div><div class="dm-meta muted">${esc(app)}</div>`;
  }

  function thermalCell(t) {
    if (!t) return "—";
    const temp = t.battery_temp_c != null ? `${Number(t.battery_temp_c).toFixed(1)}°C` : "—";
    const status = t.thermal_status && t.thermal_status !== "unsupported" ? t.thermal_status : "";
    const pill = t.overheating ? failPill("Hot") : okPill("OK");
    return `<div class="dm-cell-main">${esc(temp)}</div><div class="dm-meta">${pill} ${esc(status)}</div>`;
  }

  function testCell(te) {
    if (!te) return "—";
    const state = te.state || "idle";
    const pill = state === "running" ? warnPill("Running") : okPill("Idle");
    const current = te.current_test || te.current_suite || "—";
    const fails = te.failures != null ? `${te.failures} fail` : "";
    const dur =
      state === "running" && te.duration_sec != null
        ? `${Math.round(Number(te.duration_sec))}s`
        : "";
    return `<div class="dm-cell-main">${pill}</div><div class="dm-meta">${esc(current)}</div><div class="dm-meta muted">${esc([fails, dur].filter(Boolean).join(" · "))}</div>`;
  }

  function renderEmpty(message) {
    return `<div class="dm-empty muted">${esc(message)}</div>`;
  }

  function renderTable(devices) {
    if (!devices.length) {
      return renderEmpty(
        "No devices have reported yet. Open the Device Testing app on a phone connected to the same Wi‑Fi."
      );
    }

    const rows = devices
      .map(
        (d) => `<tr class="${d.online ? "" : "dm-row-offline"}">
        <td>
          <div class="dm-name">${esc(d.device_name || d.device_id)}</div>
          <div class="dm-meta muted">${esc(d.model || d.device_id)}</div>
        </td>
        <td>
          <div>${statusPill(d)}</div>
          <div class="dm-meta muted">${esc(formatAgo(d.last_seen_ago_sec))}</div>
        </td>
        <td>${networkCell(d.network)}</td>
        <td>${storageCell(d.storage)}</td>
        <td>${memoryCell(d.memory)}</td>
        <td>${thermalCell(d.thermal)}</td>
        <td>${testCell(d.test_execution)}</td>
        <td>
          <div class="dm-cell-main">${esc(batteryLabel(d))}</div>
          <div class="dm-meta muted">hb ${esc(d.heartbeat_count ?? 0)}</div>
        </td>
      </tr>`
      )
      .join("");

    return `<div class="tex-table-wrap dm-table-wrap">
      <table class="spec-table fl-table dm-table">
        <thead>
          <tr>
            <th>Device</th>
            <th>Status</th>
            <th>Network</th>
            <th>Storage</th>
            <th>Memory</th>
            <th>Thermal</th>
            <th>Test execution</th>
            <th>Battery</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  }

  function renderShell({ onlineCount = 0, count = 0, devices = [], loading = false } = {}) {
    const root = $("device-monitoring-root");
    if (!root) return;
    const P = window.pipeline;
    const head =
      P && P.headPanel
        ? P.headPanel({
            title: "Device Monitoring",
          desc: "Live device health from phones via Catalyst AppSail (any network). Local FastAPI is unchanged for other pipeline features.",
          side: `<div class="fl-progress-label">${onlineCount} online · ${count} total</div>`
        })
      : `<section class="panel fl-head"><div class="fl-head-main"><h2 class="fl-title">Device Monitoring</h2></div></section>`;

    root.innerHTML = `${head}
      <section class="panel fl-section dm-panel">
        <div class="panel-head-row">
          <h3>Connected devices</h3>
          <span class="muted dm-refresh">${loading ? "Refreshing…" : "Auto-refresh 5s"}</span>
        </div>
        <div class="dm-meta muted" style="margin-bottom:10px;">Monitor API: ${esc(apiBase())}</div>
        ${lastError ? `<div class="callout warn dm-error">${esc(lastError)}</div>` : ""}
        ${renderTable(devices)}
      </section>`;
  }

  async function refresh() {
    const root = $("device-monitoring-root");
    if (!root) return;
    try {
      const resp = await fetch(`${apiBase()}/api/monitor/devices`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      lastError = "";
      renderShell({
        devices: data.devices || [],
        count: data.count || 0,
        onlineCount: data.online_count || 0,
        loading: false
      });
    } catch (err) {
      lastError = `Could not reach the monitor API (${err.message}). Mode=${transportLabel()} URL=${apiBase()}.`;
      renderShell({ devices: [], count: 0, onlineCount: 0, loading: false });
    }
  }

  function startPolling() {
    stopPolling();
    refresh();
    pollTimer = setInterval(refresh, POLL_MS);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function onView(view) {
    if (view === "device-monitoring") startPolling();
    else stopPolling();
  }

  document.addEventListener("workbench:view", (e) => {
    onView(e.detail && e.detail.view);
  });

  document.addEventListener("DOMContentLoaded", () => {
    const active = document.querySelector(".view.active");
    if (active && active.id === "view-device-monitoring") startPolling();
  });

  window.deviceMonitoring = { refresh, startPolling, stopPolling };
})();
