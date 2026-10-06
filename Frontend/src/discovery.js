(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const api = () =>
    (window.platformConfig && window.platformConfig.apiBaseUrl) || "http://127.0.0.1:8000";

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }

  async function getJSON(path) {
    const resp = await fetch(`${api()}${path}`);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
    return data;
  }

  const TABS = {
    system: { label: "System apps", command: "pm list packages -s", desc: "Preinstalled apps with an icon in the app drawer" },
    third_party: { label: "Third-party apps", command: "pm list packages -3", desc: "Installed later by the user or an app store" }
  };

  const AVATAR_COLORS = ["#2563eb", "#0891b2", "#059669", "#7c3aed", "#db2777", "#ea580c", "#4f46e5", "#0d9488"];

  const INSTALLERS = {
    "com.android.vending": "Play Store",
    "com.google.android.packageinstaller": "Package installer",
    "com.android.packageinstaller": "Package installer",
    "com.android.shell": "adb"
  };

  const st = {
    mode: null,
    devices: [],
    devicesError: "",
    serial: "",
    scanning: false,
    scan: null,
    error: "",
    tab: "system",
    query: "",
    selected: new Set()
  };

  // ── Feature Extraction / Installed Apps switch ──────

  const MODES = ["features", "apps"];

  function setMode(mode) {
    st.mode = mode;
    document.querySelectorAll(".disc-switch").forEach((el) => {
      const on = el.dataset.disc === mode;
      el.classList.toggle("is-active", on);
      el.setAttribute("aria-selected", String(on));
      el.tabIndex = on ? 0 : -1;
    });
    $("disc-pane-features").classList.toggle("hidden", mode !== "features");
    $("disc-pane-apps").classList.toggle("hidden", mode !== "apps");
    if (mode === "apps" && !st.devices.length && !st.devicesError) loadDevices();
  }

  // ── Devices ─────────────────────────────────────────

  function deviceName(d) {
    const name = [d.manufacturer, d.model].filter(Boolean).join(" ");
    return name || d.serial;
  }

  async function loadDevices() {
    st.devicesError = "";
    const select = $("apps-device");
    select.innerHTML = "<option>Looking for devices…</option>";
    try {
      const data = await getJSON("/api/execution/devices");
      st.devices = (data.devices || []).filter((d) => d.state === "device");
      if (!data.adb_available) st.devicesError = "adb is not available on this computer.";
    } catch (err) {
      st.devices = [];
      st.devicesError = `Could not reach the backend: ${err.message}`;
    }
    if (!st.devices.some((d) => d.serial === st.serial)) st.serial = st.devices[0]?.serial || "";
    select.innerHTML = st.devices.length
      ? st.devices.map((d) => `<option value="${esc(d.serial)}" ${d.serial === st.serial ? "selected" : ""}>
          ${esc(deviceName(d))} · Android ${esc(d.android_version || "?")} (${esc(d.serial)})</option>`).join("")
      : "<option value=\"\">No device connected</option>";
    select.disabled = !st.devices.length;
    renderBody();
  }

  // ── Scan ────────────────────────────────────────────

  async function scan() {
    if (!st.serial || st.scanning) return;
    st.scanning = true;
    st.error = "";
    renderBody();
    try {
      st.scan = await getJSON(`/api/execution/devices/${encodeURIComponent(st.serial)}/packages`);
      st.scan.scannedAt = new Date();
      st.selected = new Set();
      st.tab = tabApps("third_party").length && !tabApps("system").length ? "third_party" : st.tab;
    } catch (err) {
      st.error = err.message;
    }
    st.scanning = false;
    renderBody();
  }

  // System tab: only apps with a launcher icon (background components are hidden). Third-party: all.
  function tabApps(tab) {
    const apps = (st.scan && st.scan[tab]) || [];
    return tab === "system" ? apps.filter((a) => a.launcher) : apps;
  }

  function visibleApps() {
    const q = st.query.trim().toLowerCase();
    const apps = tabApps(st.tab);
    return q ? apps.filter((a) => [a.name, a.package, a.location, a.installer, a.path].some((v) => String(v || "").toLowerCase().includes(q))) : apps;
  }

  function appName(a) {
    return a.name || a.package;
  }

  function avatar(a) {
    const name = appName(a);
    const hash = [...a.package].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
    return `<span class="apps-avatar" style="background:${AVATAR_COLORS[hash % AVATAR_COLORS.length]}" aria-hidden="true">${esc(name.charAt(0).toUpperCase())}</span>`;
  }

  function versionText(a) {
    if (a.version_name && a.version_code != null) return `${a.version_name} (${a.version_code})`;
    return a.version_name || (a.version_code != null ? String(a.version_code) : "—");
  }

  function installerText(a) {
    if (!a.installer) return a.type === "system" ? "Preinstalled" : "Unknown";
    return INSTALLERS[a.installer] || a.installer;
  }

  // ── Rendering ───────────────────────────────────────

  function emptyState(title, text, tone) {
    return `
      <section class="panel apps-empty ${tone || ""}">
        <div class="apps-empty-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/></svg>
        </div>
        <div class="apps-empty-title">${title}</div>
        <p>${text}</p>
      </section>`;
  }

  function renderBody() {
    $("apps-scan-btn").disabled = !st.serial || st.scanning;
    $("apps-scan-btn").textContent = st.scanning ? "Scanning…" : st.scan ? "Scan again" : "Scan device";
    const body = $("apps-body");

    if (st.scanning) {
      body.innerHTML = `
        <section class="panel apps-empty">
          <span class="running-spinner apps-spinner" aria-hidden="true"></span>
          <div class="apps-empty-title">Scanning the phone…</div>
          <p>Running <code>pm list packages -s</code> and <code>pm list packages -3</code>. This takes a few seconds.</p>
        </section>`;
      return;
    }
    if (st.error) {
      body.innerHTML = emptyState("Scan failed", esc(st.error), "is-error");
      return;
    }
    if (!st.scan) {
      body.innerHTML = st.devices.length
        ? emptyState("Ready to scan", "Pick the phone above and press <b>Scan device</b> to list all of its apps.")
        : emptyState("No phone connected",
          esc(st.devicesError || "Connect a phone with USB debugging enabled (or start an emulator), then press Refresh (↻)."));
      return;
    }

    const s = st.scan;
    const d = s.device || {};
    const apps = visibleApps();
    const allIds = apps.map((a) => a.package);
    const allSelected = allIds.length && allIds.every((id) => st.selected.has(id));

    body.innerHTML = `
      <div class="apps-meta">
        Scanned <b>${esc(deviceName({ ...d, serial: s.serial }))}</b> · Android ${esc(d.android_version || "?")}
        · ${esc(s.scannedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }))}
        ${s.counts.disabled ? ` · ${s.counts.disabled} disabled` : ""}
      </div>

      <div class="apps-tabs" role="tablist" aria-label="App type">
        ${Object.entries(TABS).map(([key, t]) => `
          <button type="button" role="tab" class="apps-tab ${st.tab === key ? "is-active" : ""}" data-apps-tab="${key}"
            aria-selected="${st.tab === key}">
            <span class="apps-tab-count">${tabApps(key).length}</span>
            <span class="apps-tab-text">
              <span class="apps-tab-name">${t.label}</span>
              <span class="apps-tab-desc">${t.desc}</span>
              <code class="apps-tab-cmd">${t.command}</code>
            </span>
          </button>`).join("")}
      </div>

      <section class="panel apps-list">
        <div class="apps-toolbar">
          <input type="search" class="input" id="apps-search" placeholder="Search name, package, location or installer"
            aria-label="Search apps" value="${esc(st.query)}" />
          <span class="apps-count">${apps.length} of ${tabApps(st.tab).length} shown · <b>${st.selected.size}</b> selected for testing</span>
        </div>
        ${apps.length ? `
          <div class="apps-table-wrap">
            <table class="apps-table">
              <thead><tr>
                <th class="apps-col-check"><input type="checkbox" id="apps-select-all" aria-label="Select all shown" ${allSelected ? "checked" : ""} /></th>
                <th>App</th><th>Location</th><th>Version</th><th>Installed by</th><th>Status</th>
              </tr></thead>
              <tbody>
                ${apps.map((a) => `
                  <tr class="${a.enabled ? "" : "is-disabled"} ${st.selected.has(a.package) ? "is-selected" : ""}">
                    <td class="apps-col-check"><input type="checkbox" data-app="${esc(a.package)}" aria-label="Include ${esc(appName(a))}" ${st.selected.has(a.package) ? "checked" : ""} /></td>
                    <td>
                      <div class="apps-app">
                        ${avatar(a)}
                        <div class="apps-app-text">
                          <div class="apps-name" ${a.name_source === "package" ? 'title="Name derived from the package name"' : ""}>${esc(appName(a))}</div>
                          <div class="apps-pkg" ${a.path ? `title="${esc(a.path)}"` : ""}>${esc(a.package)}</div>
                        </div>
                      </div>
                    </td>
                    <td>${esc(a.location || "—")}</td>
                    <td class="apps-num">${esc(versionText(a))}</td>
                    <td>${esc(installerText(a))}</td>
                    <td>
                      <span class="apps-status ${a.enabled ? "is-on" : "is-off"}">${a.enabled ? "Enabled" : "Disabled"}</span>
                      ${a.updated ? '<span class="apps-badge" title="A newer version was installed over the preinstalled one">Updated</span>' : ""}
                    </td>
                  </tr>`).join("")}
              </tbody>
            </table>
          </div>`
          : `<div class="apps-none">No apps match “${esc(st.query)}”.</div>`}
      </section>`;
  }

  // ── Events ──────────────────────────────────────────

  document.querySelectorAll(".disc-switch").forEach((btn) => {
    btn.addEventListener("click", () => setMode(btn.dataset.disc));
    btn.addEventListener("keydown", (e) => {
      if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
      const i = MODES.indexOf(btn.dataset.disc);
      const next = MODES[(i + (e.key === "ArrowRight" ? 1 : -1) + MODES.length) % MODES.length];
      setMode(next);
      document.querySelector(`.disc-switch[data-disc="${next}"]`)?.focus();
    });
  });

  $("apps-device").addEventListener("change", (e) => {
    st.serial = e.target.value;
    renderBody();
  });
  $("apps-refresh-devices").addEventListener("click", loadDevices);
  $("apps-scan-btn").addEventListener("click", scan);

  $("apps-body").addEventListener("click", (e) => {
    const tab = e.target.closest("[data-apps-tab]");
    if (tab) {
      st.tab = tab.dataset.appsTab;
      st.query = "";
      renderBody();
    }
  });

  $("apps-body").addEventListener("input", (e) => {
    if (e.target.id !== "apps-search") return;
    st.query = e.target.value;
    const caret = e.target.selectionStart;
    renderBody();
    const input = $("apps-search");
    input.focus();
    input.setSelectionRange(caret, caret);
  });

  $("apps-body").addEventListener("change", (e) => {
    if (e.target.id === "apps-select-all") {
      visibleApps().forEach((a) => (e.target.checked ? st.selected.add(a.package) : st.selected.delete(a.package)));
    } else if (e.target.dataset.app) {
      if (e.target.checked) st.selected.add(e.target.dataset.app);
      else st.selected.delete(e.target.dataset.app);
    } else {
      return;
    }
    renderBody();
  });

  setMode("features");
  renderBody();
})();
