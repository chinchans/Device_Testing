(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const POLL_MS = 5000;
  const POLL_FAST_MS = 3000;

  let pollTimer = null;
  let currentPollMs = POLL_MS;
  let lastError = "";
  /** Open cases popup for this device_id (or null). */
  let popupDeviceId = null;
  /** Open suite-log popup for this device_id (or null). */
  let logPopupDeviceId = null;
  let logPopupLogId = null;
  let latestDevices = [];
  /** Suite logs collected while this desktop app is open. Cleared when npm start stops. */
  const SESSION_LOG_KEY = "dm-suite-logs-v1";

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
    return device.charging === true ? `${pct}% ▮` : `${pct}%`;
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

  function softFlag(ok, badLabel) {
    return ok ? "" : ` <span class="dm-flag">${esc(badLabel)}</span>`;
  }

  function networkCell(n) {
    if (!n) return "—";
    const transport = (n.transport || "none").toUpperCase();
    const connected = n.connected === true;
    const validated = n.validated_internet === true;
    const flag = !connected ? softFlag(false, "down") : softFlag(validated, "no net");
    return `<div class="dm-cell-main">${esc(transport)}${flag}</div>`;
  }

  function storageCell(s) {
    if (!s) return "—";
    const pct = s.free_percent != null ? `${Math.round(Number(s.free_percent))}% free` : formatBytes(s.free_bytes);
    return `<div class="dm-cell-main">${esc(pct)}${softFlag(!s.low_storage, "low")}</div>`;
  }

  function memoryCell(m) {
    if (!m) return "—";
    const pct = m.available_percent != null ? `${Math.round(Number(m.available_percent))}% free` : formatBytes(m.available_bytes);
    return `<div class="dm-cell-main">${esc(pct)}${softFlag(!m.low_memory, "low")}</div>`;
  }

  function thermalCell(t) {
    if (!t) return "—";
    const temp = t.battery_temp_c != null ? `${Number(t.battery_temp_c).toFixed(1)}°C` : "—";
    return `<div class="dm-cell-main">${esc(temp)}${softFlag(!t.overheating, "hot")}</div>`;
  }

  function isLiveRunning(device) {
    const te = device && device.test_execution;
    return !!(device && device.online && te && te.state === "running");
  }

  function runningPill(text) {
    return `<span class="status-pill is-running">${esc(text)}</span>`;
  }

  function featureLabel(te) {
    const raw = String((te && te.feature) || "").toLowerCase();
    if (raw === "camera") return "Camera";
    if (raw === "calls") return "Calls";
    if (raw === "sms") return "SMS";
    if (raw) return raw.charAt(0).toUpperCase() + raw.slice(1);
    return "";
  }

  function caseStatusLabel(status) {
    switch (String(status || "").toUpperCase()) {
      case "PASS":
        return "Pass";
      case "FAIL":
        return "Fail";
      case "RUNNING":
        return "Running";
      case "PENDING":
        return "Pending";
      case "BLOCKED":
        return "Blocked";
      case "NOT_APPLICABLE":
        return "N/A";
      case "NOT_VERIFIED":
        return "Unverified";
      default:
        return status || "—";
    }
  }

  function caseStatusPill(status) {
    const s = String(status || "").toUpperCase();
    if (s === "PASS") return okPill(caseStatusLabel(s));
    if (s === "FAIL") return failPill(caseStatusLabel(s));
    if (s === "RUNNING") return runningPill(caseStatusLabel(s));
    if (s === "PENDING") return warnPill(caseStatusLabel(s));
    return `<span class="status-pill is-muted">${esc(caseStatusLabel(s))}</span>`;
  }

  function casesTable(te) {
    const cases = Array.isArray(te && te.cases) ? te.cases : [];
    if (!cases.length) {
      return `<div class="dm-empty-cases">No cases reported yet</div>`;
    }
    const rows = cases
      .map(
        (c) => `<tr class="${String(c.status).toUpperCase() === "RUNNING" ? "is-current" : ""}">
        <td class="dm-case-id">${esc(c.id || "—")}</td>
        <td class="dm-case-title">${esc(c.title || "—")}</td>
        <td class="dm-case-status">${caseStatusPill(c.status)}</td>
      </tr>`
      )
      .join("");
    return `<table class="dm-cases-table">
      <thead><tr><th>ID</th><th>Name</th><th>Status</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  }

  function testCell(te, live, deviceId) {
    if (!te) return `<div class="dm-exec"><div class="dm-exec-top">${okPill("Idle")}</div></div>`;
    const state = te.state || "idle";
    const running = live && state === "running";
    // Only show suite / cases while a live run is in progress; idle = pill only.
    if (!running) {
      const pill = state === "running" ? warnPill("Stale") : okPill("Idle");
      return `<div class="dm-exec"><div class="dm-exec-top">${pill}</div></div>`;
    }
    const feature = featureLabel(te);
    const suite = te.current_suite ? String(te.current_suite) : "";
    const test = te.current_test ? String(te.current_test) : "";
    const caseCount = Array.isArray(te.cases) ? te.cases.length : Number(te.case_count || 0);
    const doneCount = Array.isArray(te.cases)
      ? te.cases.filter((c) => !["pending", "running", ""].includes(String(c.status || "").toLowerCase())).length
      : 0;
    const progress = caseCount ? `${doneCount}/${caseCount}` : "";
    const dur = te.duration_sec != null ? `${Math.round(Number(te.duration_sec))}s` : "";
    const fails = Number(te.failures || 0);
    const open = popupDeviceId === deviceId;
    const headline = [feature, suite].filter(Boolean).join(" · ") || "Suite running";
    const sub = [test, progress, dur, fails ? `${fails} fail` : ""]
      .filter(Boolean)
      .join(" · ");

    return `<div class="dm-exec">
      <div class="dm-exec-top">${runningPill("Running")}<span class="dm-exec-headline">${esc(headline)}</span></div>
      ${sub ? `<div class="dm-exec-sub">${esc(sub)}</div>` : ""}
      <button type="button" class="dm-exec-toggle" data-dm-toggle="${esc(deviceId)}" aria-expanded="${open ? "true" : "false"}">
        Cases
      </button>
    </div>`;
  }

  function logStamp(item) {
    const started = Number(item && item.started_at_ms);
    if (started) return started;
    const saved = Number(item && item.saved_at);
    return saved ? saved * 1000 : 0;
  }

  function readSessionLogs() {
    try {
      const parsed = JSON.parse(sessionStorage.getItem(SESSION_LOG_KEY) || "{}");
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (err) {
      return {};
    }
  }

  function writeSessionLogs(book) {
    try {
      sessionStorage.setItem(SESSION_LOG_KEY, JSON.stringify(book));
    } catch (err) {
      /* the in-memory copy still covers this page */
    }
  }

  function logFeature(item) {
    const named = featureLabel({ feature: item && item.feature });
    if (named) return named;
    const file = String((item && item.file_name) || "");
    const match = /^(camera|calls|sms)_/i.exec(file);
    return match ? featureLabel({ feature: match[1] }) : "";
  }

  function rememberDeviceLogs(device) {
    if (!device || !device.device_id) return [];
    const book = readSessionLogs();
    const prev = Array.isArray(book[device.device_id]) ? book[device.device_id] : [];
    const incoming = [];
    if (Array.isArray(device.suite_logs)) incoming.push(...device.suite_logs);
    if (device.suite_log && device.suite_log.id) incoming.push(device.suite_log);
    const byId = new Map();
    prev.forEach((item) => {
      if (item && item.id) byId.set(item.id, item);
    });
    incoming.forEach((item) => {
      if (!item || !item.id) return;
      const older = byId.get(item.id);
      if (!older) {
        byId.set(item.id, item);
        return;
      }
      const merged = { ...older, ...item };
      if (!item.feature && older.feature) merged.feature = older.feature;
      if (!item.file_name && older.file_name) merged.file_name = older.file_name;
      byId.set(item.id, merged);
    });
    const merged = [...byId.values()].sort((a, b) => logStamp(b) - logStamp(a)).slice(0, 30);
    book[device.device_id] = merged;
    writeSessionLogs(book);
    return merged;
  }

  function suiteLogsOf(device) {
    if (!device) return [];
    const book = readSessionLogs();
    const cached = book[device.device_id];
    if (Array.isArray(cached) && cached.length) return cached.filter((item) => item && item.id);
    const logs = device.suite_logs;
    if (Array.isArray(logs) && logs.length) return logs.filter((item) => item && item.id);
    if (device.suite_log && device.suite_log.id) return [device.suite_log];
    return [];
  }

  function formatLogTime(ms) {
    const n = Number(ms);
    if (!n) return "";
    const when = new Date(n);
    if (Number.isNaN(when.getTime())) return "";
    return when.toLocaleString();
  }

  function logCell(device) {
    const logs = suiteLogsOf(device);
    if (!logs.length) return `<div class="dm-cell-main">—</div>`;
    const open = logPopupDeviceId === device.device_id;
    const newest = logs[0];
    const headline = [logFeature(newest), newest.suite].filter(Boolean).join(" · ");
    const extra = logs.length > 1 ? `${logs.length} logs` : "";
    return `<div class="dm-exec">
      <button type="button" class="dm-exec-toggle" data-dm-log="${esc(device.device_id)}" aria-expanded="${open ? "true" : "false"}">View log</button>
      <div class="dm-exec-sub">${esc([headline || "Suite log", extra].filter(Boolean).join(" · "))}</div>
    </div>`;
  }

  function closeLogPopup() {
    logPopupDeviceId = null;
    logPopupLogId = null;
    const host = document.getElementById("dm-log-popup");
    if (host) host.remove();
  }

  function renderLogPopup() {
    if (!logPopupDeviceId) {
      closeLogPopup();
      return;
    }
    const device = latestDevices.find((d) => d.device_id === logPopupDeviceId);
    const logs = suiteLogsOf(device);
    if (!device || !logs.length) {
      closeLogPopup();
      return;
    }
    const selected = logs.find((item) => item.id === logPopupLogId) || null;
    const titleBits = [device.device_name || device.device_id];
    if (selected) {
      titleBits.push(logFeature(selected), selected.suite);
    }
    let host = document.getElementById("dm-log-popup");
    if (!host) {
      host = document.createElement("div");
      host.id = "dm-log-popup";
      host.className = "dm-cases-popup";
      document.body.appendChild(host);
    }
    const rows = logs
      .map((item) => {
        const when = formatLogTime(item.started_at_ms);
        return `<tr class="dm-log-row" data-dm-open-log="${esc(item.id)}">
          <td>${esc(logFeature(item) || "—")}</td>
          <td>${esc(item.suite || "Suite")}</td>
          <td class="dm-log-when">${esc(when || "—")}</td>
        </tr>`;
      })
      .join("");
    const body = selected
      ? `<button type="button" class="dm-exec-toggle dm-log-back" data-dm-log-back="1">All suite logs</button>
         <pre class="dm-log-view" id="dm-log-text">Loading…</pre>`
      : `<table class="dm-cases-table">
          <thead><tr><th>Feature</th><th>Suite</th><th>Started</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>`;
    host.innerHTML = `
      <div class="modal-backdrop" data-dm-log-close="1"></div>
      <div class="modal-panel wide dm-cases-panel" role="dialog" aria-modal="true" aria-label="Suite log">
        <div class="modal-header">
          <div>
            <h4>Suite log</h4>
            <div class="dm-cases-dialog-sub">${esc(titleBits.filter(Boolean).join(" · "))}</div>
          </div>
          <button type="button" class="modal-close" data-dm-log-close="1">Close</button>
        </div>
        <div class="modal-body dm-cases-dialog-body">
          ${body}
        </div>
      </div>`;
    host.querySelectorAll("[data-dm-log-close]").forEach((el) => {
      el.addEventListener("click", (ev) => {
        ev.preventDefault();
        closeLogPopup();
      });
    });
    host.querySelectorAll("[data-dm-log-back]").forEach((el) => {
      el.addEventListener("click", (ev) => {
        ev.preventDefault();
        logPopupLogId = null;
        renderLogPopup();
      });
    });
    host.querySelectorAll("[data-dm-open-log]").forEach((row) => {
      row.addEventListener("click", () => {
        logPopupLogId = row.getAttribute("data-dm-open-log");
        renderLogPopup();
      });
    });
    if (!selected) return;
    const logId = selected.id;
    fetch(`${apiBase()}/api/monitor/logs/${encodeURIComponent(logId)}`)
      .then(async (resp) => {
        const text = await resp.text();
        if (!resp.ok) throw new Error(text || `HTTP ${resp.status}`);
        return text;
      })
      .then((text) => {
        const node = document.getElementById("dm-log-text");
        if (node && logPopupDeviceId === device.device_id && logPopupLogId === logId) {
          node.textContent = text || "Log is empty";
        }
      })
      .catch((err) => {
        const node = document.getElementById("dm-log-text");
        if (node && logPopupDeviceId === device.device_id && logPopupLogId === logId) {
          node.textContent = `Could not load the log. ${err.message || err}`;
        }
      });
  }

  function closeCasesPopup() {
    popupDeviceId = null;
    const host = document.getElementById("dm-cases-popup");
    if (host) host.remove();
  }

  function renderCasesPopup() {
    if (!popupDeviceId) {
      closeCasesPopup();
      return;
    }
    const device = latestDevices.find((d) => d.device_id === popupDeviceId);
    if (!device || !isLiveRunning(device)) {
      closeCasesPopup();
      return;
    }
    const te = device.test_execution || {};
    const feature = featureLabel(te);
    const suite = te.current_suite ? String(te.current_suite) : "";
    const titleBits = [device.device_name || device.device_id, feature, suite].filter(Boolean);
    let host = document.getElementById("dm-cases-popup");
    if (!host) {
      host = document.createElement("div");
      host.id = "dm-cases-popup";
      host.className = "dm-cases-popup";
      document.body.appendChild(host);
    }
    host.innerHTML = `
      <div class="modal-backdrop" data-dm-close="1"></div>
      <div class="modal-panel wide dm-cases-panel" role="dialog" aria-modal="true" aria-label="Test cases">
        <div class="modal-header">
          <div>
            <h4>Test cases</h4>
            <div class="dm-cases-dialog-sub">${esc(titleBits.join(" · "))}</div>
          </div>
          <button type="button" class="modal-close" data-dm-close="1">Close</button>
        </div>
        <div class="modal-body dm-cases-dialog-body">
          ${casesTable(te)}
        </div>
      </div>`;
    host.querySelectorAll("[data-dm-close]").forEach((el) => {
      el.addEventListener("click", (ev) => {
        ev.preventDefault();
        closeCasesPopup();
      });
    });
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
      .map((d) => {
        const live = isLiveRunning(d);
        const rowClass = [
          d.online ? "" : "dm-row-offline",
          live ? "dm-row-running" : "",
        ]
          .filter(Boolean)
          .join(" ");
        return `<tr class="${rowClass}">
        <td>
          <div class="dm-name">${esc(d.device_name || d.device_id)}</div>
          <div class="dm-meta muted">${esc(d.model || "")}</div>
        </td>
        <td>
          <div class="dm-status-line">${statusPill(d)}</div>
          <div class="dm-meta muted">${esc(formatAgo(d.last_seen_ago_sec))}</div>
        </td>
        <td>${networkCell(d.network)}</td>
        <td>${storageCell(d.storage)}</td>
        <td>${memoryCell(d.memory)}</td>
        <td>${thermalCell(d.thermal)}</td>
        <td>${testCell(d.test_execution, live, d.device_id)}</td>
        <td>${logCell(d)}</td>
        <td><div class="dm-cell-main">—</div></td>
        <td><div class="dm-cell-main">${esc(batteryLabel(d))}</div></td>
      </tr>`;
      })
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
            <th>Suite log</th>
            <th>Phone casting</th>
            <th>Battery</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  }

  function renderShell({ onlineCount = 0, count = 0, devices = [], loading = false, pollMs = POLL_MS } = {}) {
    const root = $("device-monitoring-root");
    if (!root) return;
    const runningCount = (devices || []).filter(isLiveRunning).length;
    const P = window.pipeline;
    const head =
      P && P.headPanel
        ? P.headPanel({
            title: "Device Monitoring",
          desc: "Live device health from phones via Catalyst AppSail (any network). Local FastAPI is unchanged for other pipeline features.",
          side: `<div class="fl-progress-label">${onlineCount} online · ${count} total${runningCount ? ` · ${runningCount} running` : ""}</div>`
        })
      : `<section class="panel fl-head"><div class="fl-head-main"><h2 class="fl-title">Device Monitoring</h2></div></section>`;

    root.innerHTML = `${head}
      <section class="panel fl-section dm-panel">
        <div class="panel-head-row">
          <h3>Connected devices</h3>
          <span class="muted dm-refresh">${loading ? "Refreshing…" : `Auto-refresh ${Math.round(pollMs / 1000)}s`}</span>
        </div>
        <div class="dm-meta muted" style="margin-bottom:10px;">Monitor API: ${esc(apiBase())}</div>
        ${lastError ? `<div class="callout warn dm-error">${esc(lastError)}</div>` : ""}
        ${renderTable(devices)}
      </section>`;

    root.querySelectorAll("[data-dm-toggle]").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const id = btn.getAttribute("data-dm-toggle");
        if (!id) return;
        closeLogPopup();
        if (popupDeviceId === id) {
          closeCasesPopup();
          btn.setAttribute("aria-expanded", "false");
          return;
        }
        popupDeviceId = id;
        btn.setAttribute("aria-expanded", "true");
        renderCasesPopup();
      });
    });

    root.querySelectorAll("[data-dm-log]").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const id = btn.getAttribute("data-dm-log");
        if (!id) return;
        closeCasesPopup();
        if (logPopupDeviceId === id) {
          closeLogPopup();
          btn.setAttribute("aria-expanded", "false");
          return;
        }
        logPopupDeviceId = id;
        logPopupLogId = null;
        btn.setAttribute("aria-expanded", "true");
        renderLogPopup();
      });
    });

    if (popupDeviceId) {
      const openDev = (devices || []).find((d) => d.device_id === popupDeviceId);
      if (!openDev || !isLiveRunning(openDev)) closeCasesPopup();
      else renderCasesPopup();
    }
    if (logPopupDeviceId && !logPopupLogId) renderLogPopup();
  }

  async function refresh() {
    const root = $("device-monitoring-root");
    if (!root) return;
    try {
      const resp = await fetch(`${apiBase()}/api/monitor/devices`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      lastError = "";
      const devices = data.devices || [];
      devices.forEach((device) => {
        device.suite_logs = rememberDeviceLogs(device);
        device.suite_log = device.suite_logs[0] || null;
      });
      latestDevices = devices;
      const anyRunning = devices.some(isLiveRunning);
      const nextPoll = anyRunning ? POLL_FAST_MS : POLL_MS;
      renderShell({
        devices,
        count: data.count || 0,
        onlineCount: data.online_count || 0,
        loading: false,
        pollMs: nextPoll
      });
      if (pollTimer && currentPollMs !== nextPoll) {
        currentPollMs = nextPoll;
        clearInterval(pollTimer);
        pollTimer = setInterval(refresh, currentPollMs);
      }
    } catch (err) {
      lastError = `Could not reach the monitor API (${err.message}). Mode=${transportLabel()} URL=${apiBase()}.`;
      renderShell({
        devices: latestDevices,
        count: latestDevices.length,
        onlineCount: latestDevices.filter((d) => d.online).length,
        loading: false,
        pollMs: POLL_MS,
      });
    }
  }

  function startPolling() {
    stopPolling();
    currentPollMs = POLL_MS;
    refresh();
    pollTimer = setInterval(refresh, currentPollMs);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function onView(view) {
    if (view === "device-monitoring") {
      if (!pollTimer) startPolling();
      else refresh();
      return;
    }
    closeCasesPopup();
    closeLogPopup();
  }

  document.addEventListener("workbench:view", (e) => {
    onView(e.detail && e.detail.view);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (logPopupDeviceId) closeLogPopup();
      else if (popupDeviceId) closeCasesPopup();
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    startPolling();
  });

  window.deviceMonitoring = { refresh, startPolling, stopPolling, closeCasesPopup };
})();
