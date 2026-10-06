(() => {
  "use strict";

  // ── Helpers ─────────────────────────────────────────

  const $ = (id) => document.getElementById(id);
  const api = () =>
    (window.platformConfig && window.platformConfig.apiBaseUrl) || "http://127.0.0.1:8000";

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }

  async function getJSON(path, options) {
    const resp = await fetch(`${api()}${path}`, options);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
    return data;
  }

  function postJSON(path, body) {
    return getJSON(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
  }

  async function download(path, filename) {
    const resp = await fetch(`${api()}${path}`);
    if (!resp.ok) throw new Error(`Download failed (HTTP ${resp.status})`);
    const blob = await resp.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }

  function fmtDuration(seconds) {
    if (seconds == null || Number.isNaN(Number(seconds))) return "–";
    let s = Math.round(Number(seconds));
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    s %= 60;
    if (m < 60) return s ? `${m}m ${s}s` : `${m}m`;
    return `${Math.floor(m / 60)}h ${m % 60}m`;
  }

  const isImage = (name) => /\.(jpe?g|png|webp)$/i.test(name);
  const isVideo = (name) => /\.(mp4|webm|3gp)$/i.test(name);
  const caseFileUrl = (d, name) =>
    `${api()}/api/executions/${d.execution_id}/cases/${d.case.case_id}/files/${encodeURIComponent(name)}`;

  const fmtTime = (iso) => (iso ? String(iso).replace("T", " ") : "–");
  const clock = (iso) => (iso ? String(iso).slice(11, 19) : "");
  const hhmm = (iso) => (iso ? String(iso).slice(11, 16) : "");
  const pill = (text, cls) => `<span class="status-pill ${cls || ""}">${esc(text)}</span>`;
  const titleCase = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function fmtShort(iso) {
    if (!iso) return "–";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return fmtTime(iso);
    return `${d.getDate()} ${MONTHS[d.getMonth()]}, ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  /** "Samsung Samsung Galaxy S25" → "Samsung Galaxy S25" (older script sets stored the brand twice). */
  const cleanProduct = (name) => String(name || "").trim().replace(/^(\S+)(\s+\1)+(?=\s|$)/i, "$1");
  const cleanReason = (text) => String(text || "").replace(/ from (\S+)(\s+\1)+(?=\s|$)/i, " from $1");

  const VERDICT_LABEL = {
    PASS: "Pass",
    FAIL: "Fail",
    ERROR: "Error",
    MANUAL_REVIEW: "Manual review",
    BLOCKED_PRECONDITION: "Blocked",
    NOT_APPLICABLE: "Not applicable",
    SKIPPED: "Skipped",
    STOPPED: "Stopped",
    NOT_RUN: "Not run"
  };
  const VERDICT_CLASS = {
    PASS: "is-success",
    FAIL: "is-failed",
    ERROR: "is-failed",
    MANUAL_REVIEW: "is-manual",
    BLOCKED_PRECONDITION: "is-blocked",
    NOT_APPLICABLE: "is-muted",
    SKIPPED: "is-muted",
    STOPPED: "is-muted"
  };
  /** Colour family per verdict for the segmented bars. */
  const VERDICT_TONE = {
    PASS: "pass",
    FAIL: "fail",
    ERROR: "error",
    BLOCKED_PRECONDITION: "blocked",
    MANUAL_REVIEW: "manual",
    NOT_APPLICABLE: "muted",
    SKIPPED: "muted",
    STOPPED: "muted",
    NOT_RUN: "none"
  };
  const VERDICT_ORDER = ["PASS", "FAIL", "ERROR", "BLOCKED_PRECONDITION", "MANUAL_REVIEW", "NOT_APPLICABLE",
    "SKIPPED", "STOPPED", "NOT_RUN"];
  const VERDICT_SEVERITY = ["FAIL", "ERROR", "BLOCKED_PRECONDITION", "MANUAL_REVIEW", "STOPPED", "NOT_RUN",
    "NOT_APPLICABLE", "SKIPPED", "PASS"];
  const verdictPill = (v) => pill(VERDICT_LABEL[v] || v || "Not run", VERDICT_CLASS[v] || "");
  const effectiveVerdict = (c) => (c.review && c.review.decision) || c.verdict;

  const STATE_LABEL = {
    queued: "Queued",
    running: "Running",
    pausing: "Pausing…",
    paused: "Paused",
    stopping: "Stopping…",
    finished: "Finished",
    stopped: "Stopped",
    interrupted: "Interrupted"
  };
  const STATE_CLASS = {
    running: "is-running", pausing: "is-running", paused: "is-manual", stopping: "is-failed",
    finished: "is-success", stopped: "is-muted", interrupted: "is-failed", queued: "is-ready"
  };
  const statePill = (s) => pill(STATE_LABEL[s] || titleCase(s || "–"), STATE_CLASS[s] || "");

  const CAUSE_ICON = {
    failure: "✘", spec_mismatch: "≠", capability_missing: "⊘", blocked: "⛔", needs_review: "?",
    script_error: "⚠", stopped: "■", not_run: "–", passed: "✔"
  };

  const READINESS = {
    ready: ["Ready", "is-success", "Everything this case needs is on the device."],
    install: ["Installs harness", "is-ready", "The harness APK is installed automatically before the case runs."],
    manual: ["Partly manual", "is-manual", "Includes tester checkpoints; ends as Manual review until you decide."],
    lab: ["Needs lab values", "is-manual", "Needs readings from lab equipment; enter them as variable overrides."],
    blocked: ["Will be blocked", "is-failed", "A required package is missing; the case will end as Blocked."],
    unknown: ["Select a device", "", "Pick a device to check readiness."]
  };
  const RUNNABLE = new Set(["ready", "install", "manual", "unknown"]);
  const CATEGORY_ORDER = ["functionality", "performance", "reliability", "security"];
  const CAUSE_ORDER = ["failure", "spec_mismatch", "blocked", "needs_review", "script_error",
    "capability_missing", "stopped", "not_run", "passed"];
  const RERUN_CAUSES = new Set(["failure", "spec_mismatch", "blocked", "script_error", "stopped", "not_run"]);
  const ACTIVE_STATES = new Set(["queued", "running", "pausing", "paused", "stopping"]);
  const THERMAL = ["None", "Light", "Moderate", "Severe", "Critical", "Emergency", "Shutdown"];
  const LONG_RUN_S = 30 * 60;
  const MAX_LOG_LINES = 4000;
  const SCRIPT_BUG = /\b(TypeError|NameError|AttributeError|SyntaxError|IndentationError|KeyError|IndexError|ImportError|ModuleNotFoundError|UnboundLocalError)\b/;

  const st = {
    init: null,
    viewVisible: false,
    tab: "setup",
    adbAvailable: true,
    devices: [],
    serial: "",
    sets: [],
    runId: "",
    set: null,
    selected: new Set(),
    pendingSelection: null,
    overrides: [],
    exec: null,
    source: null,
    logs: [],
    metrics: [],
    manual: [],
    health: null,
    focusCase: null,
    progressSig: "",
    liveCurrentHtml: "",
    elapsedTimer: null,
    screenTimer: null,
    results: null,
    causes: {},
    causeFilter: null,
    filters: { q: "", verdict: "", sort: "default" },
    reviewMode: false,
    reviewQueue: [],
    prevExec: null,
    detail: null,
    history: [],
    compareSel: new Set(),
    fileDownload: null
  };

  function isEmulator(d, serial) {
    d = d || {};
    serial = serial || d.serial || "";
    return !!(d.is_emulator || serial.startsWith("emulator-") || /^sdk_g?phone/i.test(d.model || ""));
  }

  function deviceName(d, serial) {
    d = d || {};
    serial = serial || d.serial || "";
    if (isEmulator(d, serial)) {
      const port = (serial.match(/^emulator-(\d+)$/) || [])[1];
      return port ? `Emulator ${port}` : "Emulator";
    }
    const maker = d.manufacturer ? d.manufacturer[0].toUpperCase() + d.manufacturer.slice(1) : "";
    const model = d.model || "";
    const name = maker && model.toLowerCase().startsWith(maker.toLowerCase()) ? model : [maker, model].filter(Boolean).join(" ");
    return name || serial || "–";
  }

  /** "Camera · Samsung Galaxy S25 spec · Emulator 5554 · 1 Oct, 10:29" */
  function execTitle(r) {
    return [
      titleCase(r.feature || "Execution"),
      r.product_name ? `${cleanProduct(r.product_name)} spec` : "no product spec",
      deviceName(r.device, r.serial),
      fmtShort(r.started_at || r.created_at)
    ].join(" · ");
  }

  function isScriptBug(c) {
    return effectiveVerdict(c) === "ERROR" && SCRIPT_BUG.test(c.reason || "");
  }

  // ── Dialogs and toasts ──────────────────────────────

  /** In-app replacement for confirm()/alert(); resolves true when confirmed. bodyHtml must be escaped. */
  function uiDialog({ title, bodyHtml = "", okLabel = "OK", cancelLabel = "Cancel", danger = false, alertOnly = false }) {
    return new Promise((resolve) => {
      const modal = $("tex-dialog");
      const ok = $("tex-dialog-ok");
      const cancel = $("tex-dialog-cancel");
      const backdrop = $("tex-dialog-backdrop");
      const previous = document.activeElement;
      $("tex-dialog-title").textContent = title;
      $("tex-dialog-body").innerHTML = bodyHtml;
      ok.textContent = okLabel;
      ok.className = danger ? "soft-danger" : "primary";
      cancel.textContent = cancelLabel;
      cancel.classList.toggle("hidden", alertOnly);

      const close = (value) => {
        modal.classList.add("hidden");
        document.removeEventListener("keydown", onKey, true);
        ok.onclick = cancel.onclick = backdrop.onclick = null;
        if (previous && typeof previous.focus === "function") previous.focus();
        resolve(value);
      };
      const onKey = (e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          close(false);
        } else if (e.key === "Tab") {
          const focusable = [cancel, ok].filter((b) => !b.classList.contains("hidden"));
          const i = focusable.indexOf(document.activeElement);
          e.preventDefault();
          focusable[(i + (e.shiftKey ? -1 : 1) + focusable.length) % focusable.length].focus();
        }
      };
      ok.onclick = () => close(true);
      cancel.onclick = () => close(false);
      backdrop.onclick = () => close(false);
      document.addEventListener("keydown", onKey, true);
      modal.classList.remove("hidden");
      (danger ? cancel : ok).focus();
    });
  }

  function toast(message, kind = "info", action) {
    const box = $("tex-toasts");
    const el = document.createElement("div");
    el.className = `tex-toast is-${kind}`;
    el.setAttribute("role", kind === "error" ? "alert" : "status");
    el.innerHTML = `<span class="tex-toast-msg">${esc(message)}</span>
      ${action ? `<button type="button" class="tex-toast-action">${esc(action.label)}</button>` : ""}
      <button type="button" class="tex-toast-close" aria-label="Dismiss">✕</button>`;
    const remove = () => el.remove();
    el.querySelector(".tex-toast-close").addEventListener("click", remove);
    if (action) {
      el.querySelector(".tex-toast-action").addEventListener("click", () => {
        remove();
        action.onClick();
      });
    }
    box.appendChild(el);
    setTimeout(remove, kind === "error" ? 9000 : action ? 8000 : 5000);
  }

  // ── Tabs ────────────────────────────────────────────

  const TABS = ["setup", "live", "results", "history"];

  function showTab(tab, focus) {
    st.tab = tab;
    document.querySelectorAll(".tex-tab").forEach((b) => {
      const on = b.dataset.texTab === tab;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
      if (on && focus) b.focus();
    });
    document.querySelectorAll(".tex-pane").forEach((p) =>
      p.classList.toggle("is-active", p.dataset.texPane === tab));
    if (tab === "history") loadHistory();
    syncScreenPolling();
  }

  // ── Setup: devices ──────────────────────────────────

  async function loadDevices() {
    try {
      const data = await getJSON("/api/execution/devices");
      st.adbAvailable = data.adb_available !== false;
      st.devices = data.devices || [];
    } catch (err) {
      st.devices = [];
      st.adbAvailable = true;
      $("tex-device-info").innerHTML = `<div class="callout warn">Backend not reachable: ${esc(err.message)}</div>`;
      return;
    }
    const online = st.devices.filter((d) => d.state === "device");
    if (!online.some((d) => d.serial === st.serial)) st.serial = online[0] ? online[0].serial : "";
    renderDevices();
  }

  function deviceLabel(d) {
    if (d.state !== "device") return `${d.serial} · ${d.state}`;
    return `${deviceName(d)} · Android ${d.android_version || "?"}`;
  }

  function renderDevices() {
    const select = $("tex-device-select");
    if (!st.devices.length) {
      select.innerHTML = `<option value="">No device connected</option>`;
      select.disabled = true;
      $("tex-device-info").innerHTML = st.adbAvailable
        ? `<div class="callout warn">No device found. Start the emulator or connect a phone, then Refresh.</div>`
        : `<div class="callout warn">adb is not available on the backend host.</div>`;
    } else {
      select.disabled = false;
      select.innerHTML = st.devices
        .map((d) => `<option value="${esc(d.serial)}" ${d.state !== "device" ? "disabled" : ""}
          ${d.serial === st.serial ? "selected" : ""}>${esc(deviceLabel(d))}</option>`)
        .join("");
      renderDeviceInfo();
    }
    renderStartSummary();
  }

  function renderDeviceInfo() {
    const d = st.devices.find((x) => x.serial === st.serial);
    if (!d) {
      $("tex-device-info").innerHTML = "";
      return;
    }
    const h = d.health || {};
    const pkgs = Object.entries(d.packages || {})
      .filter(([pkg]) => !st.set || !st.set.feature || pkg.includes(st.set.feature))
      .map(([pkg, p]) => `<div class="tex-kv-row"><span>${esc(p.label)}</span>
        <span>${p.installed ? pill(`v${p.version || "?"}`, "is-success") : pill("Not installed", "is-muted")}</span></div>`)
      .join("");
    const busy = st.exec && ACTIVE_STATES.has(st.exec.state) && st.exec.serial === d.serial;
    $("tex-device-info").innerHTML = `
      <div class="tex-device-summary">
        <div class="tex-device-name">${esc(deviceName(d))}</div>
        <div class="tex-muted-small">Android ${esc(d.android_version || "–")} (API ${esc(d.sdk_int ?? "?")}) · ${esc(d.serial)}</div>
      </div>
      <div class="tex-kv tex-health-inline tex-divided">${healthRows(h)}</div>
      <div class="tex-kv tex-divided">
        <div class="tex-subhead">Harness packages</div>
        ${pkgs || '<span class="muted">None</span>'}
      </div>
      ${busy ? `<div class="callout info">Busy: ${esc(execTitle(st.exec))} is running on this device.</div>` : ""}`;
  }

  function healthRows(h) {
    const battery = h.battery_pct == null ? "–" : `${h.battery_pct}%${h.charging ? " · charging" : ""}`;
    const temp = h.battery_temp_c == null ? "–" : `${h.battery_temp_c.toFixed(1)} °C`;
    const thermal = h.thermal_status == null ? "–" : THERMAL[h.thermal_status] || h.thermal_status;
    const warn = (cond) => (cond ? ' class="tex-warn-text"' : "");
    return `
      <div class="tex-kv-row"><span>Battery</span><span${warn(h.battery_pct != null && h.battery_pct < 20)}>${esc(battery)}</span></div>
      <div class="tex-kv-row"><span>Temperature</span><span${warn(h.battery_temp_c > 40)}>${esc(temp)}</span></div>
      <div class="tex-kv-row"><span>Thermal status</span><span${warn(h.thermal_status >= 3)}>${esc(thermal)}</span></div>`;
  }

  // ── Setup: script sets ──────────────────────────────

  async function loadSets(preferRunId) {
    try {
      st.sets = (await getJSON("/api/execution/script-sets")).script_sets || [];
    } catch (err) {
      st.sets = [];
      $("tex-set-info").innerHTML = `<div class="callout warn">${esc(err.message)}</div>`;
    }
    const want = preferRunId || st.runId;
    st.runId = st.sets.some((s) => s.run_id === want) ? want : st.sets[0] ? st.sets[0].run_id : "";
    const select = $("tex-set-select");
    select.disabled = !st.sets.length;
    select.innerHTML = st.sets.length
      ? st.sets.map((s) => `<option value="${esc(s.run_id)}" ${s.run_id === st.runId ? "selected" : ""}>
          ${esc(fmtShort(s.created_at))} · ${esc(titleCase(s.feature))} · ${s.script_count} script(s)${s.product_name ? ` · ${esc(cleanProduct(s.product_name))}` : ""}${s.execution_count ? ` · ${s.execution_count} run(s)` : ""}
        </option>`).join("")
      : `<option value="">No generated scripts yet</option>`;
    await loadSetDetail(true);
  }

  async function loadSetDetail(resetSelection) {
    if (!st.runId) {
      st.set = null;
      $("tex-set-info").innerHTML = `<div class="callout info">Generate scripts on the Test Script Generation page first.</div>`;
      renderCases();
      return;
    }
    const query = st.serial ? `?serial=${encodeURIComponent(st.serial)}` : "";
    try {
      st.set = await getJSON(`/api/execution/script-sets/${st.runId}${query}`);
    } catch (err) {
      st.set = null;
      $("tex-set-info").innerHTML = `<div class="callout warn">${esc(err.message)}</div>`;
      renderCases();
      return;
    }
    const ids = new Set(st.set.cases.map((c) => c.case_id));
    if (st.pendingSelection) {
      st.selected = new Set(st.pendingSelection.filter((id) => ids.has(id)));
      st.pendingSelection = null;
    } else if (resetSelection) {
      st.selected = new Set(st.set.cases.filter((c) => RUNNABLE.has(c.status)).map((c) => c.case_id));
    } else {
      st.selected = new Set([...st.selected].filter((id) => ids.has(id)));
    }
    renderSetInfo();
    renderCases();
    renderDeviceInfo();
  }

  function renderSetInfo() {
    const s = st.set;
    const specEntries = Object.entries(s.spec_applied || {});
    const spec = specEntries
      .map(([k, v]) => `<div class="tex-spec-row" title="${esc(v.source || "")}"><span class="tex-mono">${esc(k)}</span><span>${esc(v.value)}</span></div>`)
      .join("");
    $("tex-set-info").innerHTML = `
      <div class="tex-kv">
        <div class="tex-kv-row"><span>Generated</span><span>${esc(fmtShort(s.created_at))}</span></div>
        <div class="tex-kv-row"><span>Feature</span><span>${esc(titleCase(s.feature))}</span></div>
        <div class="tex-kv-row"><span>Product spec</span><span>${esc(s.product_name ? cleanProduct(s.product_name) : "None (placeholders from device)")}</span></div>
        <div class="tex-kv-row"><span>Runtime</span><span>${esc(s.runtime || "–")} ${esc(s.runtime_version || "")}</span></div>
        <div class="tex-kv-row"><span>Harness</span><span>${esc(s.harness_version ? `v${s.harness_version}` : "–")}</span></div>
      </div>
      ${spec ? `<div class="tex-divided">
        <div class="tex-subhead">Spec values in these scripts</div>
        ${specEntries.length > 5
          ? `<details class="tex-disclosure"><summary>${specEntries.length} spec values</summary><div class="tex-disclosure-body">${spec}</div></details>`
          : `<div class="tex-disclosure-body">${spec}</div>`}
      </div>` : ""}`;
  }

  function overrideMap() {
    const out = {};
    st.overrides.forEach((o) => {
      const name = (o.name || "").trim();
      if (name) out[name] = String(o.value ?? "").trim();
    });
    return out;
  }

  function caseEstimate(c) {
    const ov = overrideMap();
    const touched = (c.variables || []).some((v) => v.name in ov);
    if (!touched && c.history_s != null) return { s: c.history_s, src: "median of past runs" };
    let total = 15;
    (c.variables || []).forEach((v) => {
      const n = parseFloat(v.name in ov ? ov[v.name] : v.default);
      if (Number.isNaN(n)) return;
      if (v.kind === "seconds") total += n;
      else if (v.kind === "count") total += n * 1.5;
    });
    return { s: total, src: "estimate from cycle / duration variables" };
  }

  function renderCases() {
    const box = $("tex-cases");
    if (!st.set) {
      box.innerHTML = "";
      $("tex-cases-sub").textContent = "Select a script set";
      renderStartSummary();
      return;
    }
    const groups = {};
    st.set.cases.forEach((c) => (groups[c.category || "other"] = groups[c.category || "other"] || []).push(c));
    const order = Object.keys(groups).sort((a, b) =>
      (CATEGORY_ORDER.indexOf(a) + 99) % 99 - (CATEGORY_ORDER.indexOf(b) + 99) % 99);
    box.innerHTML = order.map((cat) => {
      const list = groups[cat];
      const picked = list.filter((c) => st.selected.has(c.case_id)).length;
      return `
        <div class="tex-cat">
          <label class="tex-cat-head">
            <input type="checkbox" class="tex-cat-check" data-category="${esc(cat)}"
              ${picked === list.length ? "checked" : ""} />
            <span class="tex-cat-name">${esc(cat)}</span>
            <span class="muted">${picked}/${list.length} selected</span>
          </label>
          ${list.map(caseRow).join("")}
        </div>`;
    }).join("");
    box.querySelectorAll(".tex-cat-check").forEach((el) => {
      const list = groups[el.dataset.category];
      const picked = list.filter((c) => st.selected.has(c.case_id)).length;
      el.indeterminate = picked > 0 && picked < list.length;
    });
    $("tex-cases-sub").textContent =
      `${st.set.cases.length} script(s) · ${st.set.cases.filter((c) => RUNNABLE.has(c.status)).length} runnable`;
    renderVarNames();
    renderStartSummary();
  }

  function caseRow(c) {
    const [label, cls, tip] = READINESS[c.status] || READINESS.unknown;
    const est = caseEstimate(c);
    const issues = (c.issues || []).filter((i) => i.level !== "manual").map((i) => i.text);
    const changes = c.device_changes || [];
    return `
      <div class="tex-case-row ${st.selected.has(c.case_id) ? "is-selected" : ""}">
        <label class="tex-case-main">
          <input type="checkbox" class="tex-case-check" data-case-id="${esc(c.case_id)}"
            ${st.selected.has(c.case_id) ? "checked" : ""} />
          <span class="tex-case-id">${esc(c.case_id)}</span>
          <span class="tex-case-name" title="${esc(c.objective || c.name)}">${esc(c.name)}</span>
        </label>
        <span class="tex-case-est" title="${esc(est.src)}">≈ ${fmtDuration(est.s)}</span>
        <span class="tex-case-ready">
          ${changes.length ? `<span class="tex-warn-icon" title="Changes the device: ${esc(changes.join(", "))}" aria-label="Changes the device">⚠</span>` : ""}
          <span title="${esc(tip)}">${pill(label, cls)}</span>
        </span>
        ${issues.length ? `<div class="tex-case-issues">${esc(issues.join(" · "))}</div>` : ""}
      </div>`;
  }

  function selectedCases() {
    return st.set ? st.set.cases.filter((c) => st.selected.has(c.case_id)) : [];
  }

  const usesSpecValues = (c) =>
    Object.values(c.spec_values || {}).some((v) => !["true", "false", ""].includes(String(v).trim().toLowerCase()));

  /** Warning when the script set's product spec clearly is not the selected device. */
  function specDeviceMismatch(cases) {
    const s = st.set;
    const d = st.devices.find((x) => x.serial === st.serial);
    if (!s || !d || !s.product_name) return null;
    const specCases = cases.filter(usesSpecValues);
    if (!specCases.length) return null;
    const product = cleanProduct(s.product_name);
    const emulator = isEmulator(d);
    const maker = String(d.manufacturer || "").toLowerCase();
    if (!emulator && (!maker || product.toLowerCase().includes(maker))) return null;
    return {
      product,
      device: emulator ? "an Android emulator" : deviceName(d),
      count: specCases.length,
      ids: specCases.map((c) => c.case_id)
    };
  }

  function renderStartSummary() {
    const cases = selectedCases();
    const total = cases.reduce((sum, c) => sum + caseEstimate(c).s, 0);
    const busy = st.exec && ACTIVE_STATES.has(st.exec.state) && st.exec.serial === st.serial;
    const device = st.devices.find((x) => x.serial === st.serial);
    $("tex-start-summary").innerHTML = cases.length
      ? `<b>${cases.length}</b> case(s) · ≈ ${esc(fmtDuration(total))}${device ? ` · on ${esc(deviceName(device))}` : ""}`
      : "No cases selected";
    const btn = $("tex-start-btn");
    btn.disabled = !st.serial || !cases.length || busy;
    btn.title = !st.serial ? "Select a device" : busy ? "The device is busy with another execution" : !cases.length ? "Select at least one case" : "";

    const warnings = [];
    const mismatch = specDeviceMismatch(cases);
    if (mismatch) {
      warnings.push(`<b>Spec is for ${esc(mismatch.product)}, but the device is ${esc(mismatch.device)}.</b>
        ${mismatch.count} selected case(s) check product-spec values and will likely end as <i>Spec mismatch</i>
        (${esc(mismatch.ids.join(", "))}). That is expected here; run on the target phone for real findings.`);
    }
    const changes = {};
    cases.forEach((c) => (c.device_changes || []).forEach((label) => (changes[label] = changes[label] || []).push(c.case_id)));
    Object.entries(changes).forEach(([label, ids]) =>
      warnings.push(`<b>${esc(label[0].toUpperCase() + label.slice(1))}</b>: ${esc(ids.join(", "))}. Settings are restored afterwards, but check this is acceptable on this device.`));
    const blocked = cases.filter((c) => c.status === "blocked");
    if (blocked.length) {
      warnings.push(`<b>${blocked.length} selected case(s) will be blocked</b>: ${esc(blocked.map((c) => c.case_id).join(", "))}.`);
    }
    const lab = cases.filter((c) => c.status === "lab");
    if (lab.length) {
      warnings.push(`<b>${lab.length} case(s) need lab values</b> (${esc(lab.map((c) => c.case_id).join(", "))}); add them as variable overrides.`);
    }
    if (total > LONG_RUN_S) {
      warnings.push(`<b>Long run: about ${fmtDuration(total)}</b>. Use the smoke-run preset for a quick check.`);
    }
    $("tex-warnings").innerHTML = warnings.map((w) => `<div class="callout warn">${w}</div>`).join("");
    $("tex-warn-card").classList.toggle("hidden", !warnings.length);
    const badge = $("tex-warn-badge");
    badge.classList.toggle("hidden", !warnings.length);
    badge.textContent = `⚠ ${warnings.length} warning${warnings.length === 1 ? "" : "s"}`;
    badge.title = "Show the warnings";
  }

  function renderVarNames() {
    const vars = {};
    (st.set ? st.set.cases : []).forEach((c) => (c.variables || []).forEach((v) => (vars[v.name] = v)));
    $("tex-var-names").innerHTML = Object.values(vars)
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((v) => `<option value="${esc(v.name)}">${esc(v.default != null ? `${v.default} (${v.source})` : v.source)}</option>`)
      .join("");
  }

  function renderOverrides() {
    const box = $("tex-overrides");
    box.innerHTML = st.overrides.length
      ? st.overrides.map((o, i) => `
          <div class="tex-override-row">
            <input class="input" list="tex-var-names" placeholder="VARIABLE" aria-label="Variable name" data-ov-index="${i}" data-ov-field="name" value="${esc(o.name)}" />
            <input class="input" placeholder="value" aria-label="Variable value" data-ov-index="${i}" data-ov-field="value" value="${esc(o.value)}" />
            <button type="button" class="secondary tsg-small-btn" data-ov-remove="${i}" aria-label="Remove override">✕</button>
          </div>`).join("")
      : `<div class="muted tex-small">None. Scripts use product-spec values, case defaults and values read from the device.</div>`;
  }

  function applySmokePreset() {
    const vars = {};
    selectedCases().forEach((c) => (c.variables || []).forEach((v) => {
      if (v.kind) vars[v.name] = v;
    }));
    const names = Object.keys(vars);
    if (!names.length) {
      toast("The selected cases have no cycle, iteration or duration variables to shorten.");
      return;
    }
    const current = overrideMap();
    names.forEach((name) => {
      const v = vars[name];
      const small = v.kind === "count" ? "3" : "10";
      const def = parseFloat(v.default);
      current[name] = !Number.isNaN(def) && def < Number(small) ? String(v.default) : small;
    });
    st.overrides = Object.entries(current).map(([name, value]) => ({ name, value }));
    renderOverrides();
    renderCases();
    toast(`Smoke-run preset applied to ${names.length} variable(s).`, "success");
  }

  async function startExecution() {
    const cases = selectedCases();
    if (!cases.length || !st.serial) return;
    const total = cases.reduce((sum, c) => sum + caseEstimate(c).s, 0);
    const changes = [...new Set(cases.flatMap((c) => c.device_changes || []))];
    const mismatch = specDeviceMismatch(cases);
    const notes = [];
    if (mismatch) notes.push(`The spec is for ${esc(mismatch.product)} but the device is ${esc(mismatch.device)}; ${mismatch.count} case(s) will likely end as spec mismatches.`);
    if (changes.length) notes.push(`These cases change the device: ${esc(changes.join(", "))}.`);
    if (total > LONG_RUN_S) notes.push(`Estimated run time is ${esc(fmtDuration(total))}.`);
    if (notes.length) {
      const go = await uiDialog({
        title: `Start ${cases.length} case(s)?`,
        bodyHtml: `<ul class="tex-dialog-list">${notes.map((n) => `<li>${n}</li>`).join("")}</ul>`,
        okLabel: "Start execution"
      });
      if (!go) return;
    }

    const btn = $("tex-start-btn");
    btn.disabled = true;
    btn.textContent = "Starting…";
    try {
      const rec = await postJSON("/api/executions", {
        run_id: st.runId,
        case_ids: cases.map((c) => c.case_id),
        serial: st.serial,
        overrides: overrideMap(),
        case_timeout_min: Math.max(1, Number($("tex-timeout").value) || 60)
      });
      connect(rec.id, rec);
      showTab("live");
    } catch (err) {
      toast(`Could not start the execution: ${err.message}`, "error");
    } finally {
      btn.textContent = "Start execution";
      renderStartSummary();
    }
  }

  // ── Live run ────────────────────────────────────────

  async function connect(execId, record) {
    if (st.source) st.source.close();
    st.logs = [];
    st.metrics = [];
    st.manual = [];
    st.health = null;
    st.focusCase = null;
    st.progressSig = "";
    try {
      st.exec = record && record.cases ? record : await getJSON(`/api/executions/${execId}`);
    } catch (err) {
      return;
    }
    st.health = st.exec.health || null;
    $("tex-log").innerHTML = "";
    renderLive();
    const source = new EventSource(`${api()}/api/executions/${execId}/events?after=0`);
    st.source = source;
    source.onmessage = (e) => handleEvent(JSON.parse(e.data));
    source.addEventListener("end", () => {
      source.close();
      if (st.source === source) st.source = null;
    });
    source.onerror = () => {
      if (st.exec && !ACTIVE_STATES.has(st.exec.state)) source.close();
    };
    startElapsedTimer();
  }

  function currentCase() {
    const ex = st.exec;
    return ex && ex.cases.find((c) => c.case_id === ex.current_case);
  }

  /** The case the log filter, metrics and header follow: the selected one, else the running/last one. */
  function focusCaseId() {
    const ex = st.exec;
    if (!ex) return null;
    return st.focusCase || ex.current_case || lastCaseId();
  }

  function handleEvent(ev) {
    const ex = st.exec;
    if (!ex) return;
    const find = (id) => ex.cases.find((c) => c.case_id === id);
    switch (ev.type) {
      case "state":
        ex.state = ev.state;
        break;
      case "execution_start":
        ex.started_at = ex.started_at || ev.t;
        break;
      case "case_start": {
        const c = find(ev.case_id);
        if (c) Object.assign(c, { status: "running", started_at: ev.t });
        ex.current_case = ev.case_id;
        pushLog({ case_id: ev.case_id, time: clock(ev.t), level: "case", text: `▶ ${ev.case_id} · ${ev.name}` });
        if (!st.focusCase && $("tex-log-filter").value === "current") renderLog();
        renderMetrics();
        break;
      }
      case "log":
        pushLog(ev);
        return;
      case "metric":
        st.metrics.push(ev);
        renderMetrics();
        return;
      case "manual":
        st.manual.push(ev);
        renderManual();
        return;
      case "health":
        st.health = ev;
        renderHealth();
        return;
      case "case_end": {
        const c = find(ev.case_id);
        if (c) Object.assign(c, { status: "done", verdict: ev.verdict, reason: ev.reason, cause: ev.cause, duration_s: ev.duration_s });
        if (ex.current_case === ev.case_id) ex.current_case = null;
        pushLog({
          case_id: ev.case_id, time: clock(ev.t), level: ev.verdict === "PASS" ? "case" : "case_bad",
          text: `■ ${ev.case_id} → ${VERDICT_LABEL[ev.verdict] || ev.verdict} (${fmtDuration(ev.duration_s)})${ev.reason ? ` · ${cleanReason(ev.reason)}` : ""}`
        });
        break;
      }
      case "execution_end":
        ex.state = ev.state;
        ex.summary = ev.summary;
        ex.current_case = null;
        ex.cases.forEach((c) => {
          if (c.status === "pending" || c.status === "running") c.status = "cancelled";
        });
        onExecutionFinished();
        break;
      default:
        return;
    }
    renderLiveHead();
    renderQueue();
  }

  function summaryText(s) {
    const v = (s && s.by_verdict) || {};
    return VERDICT_ORDER.filter((k) => v[k]).map((k) => `${v[k]} ${(VERDICT_LABEL[k] || k).toLowerCase()}`).join(", ");
  }

  async function onExecutionFinished() {
    stopElapsedTimer();
    try {
      st.exec = await getJSON(`/api/executions/${st.exec.id}`);
    } catch (err) {
      /* keep the streamed state */
    }
    const ex = st.exec;
    renderLive();
    renderDeviceInfo();
    renderStartSummary();
    if (st.set && st.set.run_id === ex.run_id) loadSetDetail(false);
    const message = `Execution ${STATE_LABEL[ex.state] ? STATE_LABEL[ex.state].toLowerCase() : ex.state}: ${summaryText(ex.summary) || "no cases finished"}.`;
    if (st.viewVisible && st.tab === "live") {
      toast(message, ex.state === "finished" ? "success" : "info");
      openResults(ex.id);
    } else {
      toast(message, ex.state === "finished" ? "success" : "info", { label: "View results", onClick: () => openResults(ex.id) });
    }
  }

  function renderLive() {
    const ex = st.exec;
    $("tex-live-empty").classList.toggle("hidden", !!ex);
    $("tex-live").classList.toggle("hidden", !ex);
    if (!ex) return;
    st.progressSig = "";
    st.liveCurrentHtml = "";
    renderLiveHead();
    renderQueue();
    renderMetrics();
    renderManual();
    renderHealth();
    renderLog();
  }

  function caseTone(c) {
    if (c.status === "running") return "tone-running";
    if (c.status === "done") return `tone-${VERDICT_TONE[effectiveVerdict(c)] || "none"}`;
    if (c.status === "cancelled") return "tone-muted";
    return "tone-queued";
  }

  function caseStatusText(c) {
    if (c.status === "done") return `${VERDICT_LABEL[effectiveVerdict(c)] || effectiveVerdict(c)} · ${fmtDuration(c.duration_s)}`;
    if (c.status === "running") return `running · ${fmtDuration(secondsSince(c.started_at))}`;
    if (c.status === "cancelled") return "not run";
    return c.estimate_s ? `queued · ≈ ${fmtDuration(c.estimate_s)}` : "queued";
  }

  function remainingSeconds(ex) {
    return ex.cases.reduce((sum, c) => {
      if (c.status === "pending") return sum + (c.estimate_s || 15);
      if (c.status === "running") return sum + Math.max(0, (c.estimate_s || 15) - secondsSince(c.started_at));
      return sum;
    }, 0);
  }

  function renderProgress(ex, done) {
    const sig = ex.cases.map((c) => `${c.status}:${effectiveVerdict(c) || ""}`).join("|");
    const bar = $("tex-progress");
    bar.setAttribute("aria-valuemax", String(ex.cases.length));
    bar.setAttribute("aria-valuenow", String(done));
    bar.setAttribute("aria-valuetext", `${done} of ${ex.cases.length} cases finished`);
    if (sig === st.progressSig) return;
    st.progressSig = sig;
    bar.innerHTML = ex.cases.map((c) =>
      `<span class="tex-seg ${caseTone(c)}" title="${esc(`${c.case_id} · ${c.name} · ${caseStatusText(c)}`)}"></span>`).join("");
  }

  function renderLiveHead() {
    const ex = st.exec;
    if (!ex) return;
    const active = ACTIVE_STATES.has(ex.state);
    const done = ex.cases.filter((c) => c.status === "done").length;
    $("tex-live-title").textContent = execTitle(ex);
    $("tex-live-meta").innerHTML = [
      `<span class="tex-mono">${esc(ex.id)}</span>`,
      `script set <span class="tex-mono">${esc(ex.run_id)}</span>`,
      ex.started_at ? `started ${esc(clock(ex.started_at))}` : "queued",
      `elapsed ${esc(fmtDuration(elapsedSeconds()))}`,
      active && ex.state !== "stopping" ? `<b>≈ ${esc(fmtDuration(remainingSeconds(ex)))} left</b>` : ""
    ].filter(Boolean).join(" · ");
    const pillEl = $("tex-live-state");
    pillEl.textContent = STATE_LABEL[ex.state] || ex.state;
    pillEl.className = `status-pill ${STATE_CLASS[ex.state] || ""}`;
    renderProgress(ex, done);
    const pause = $("tex-pause-btn");
    pause.textContent = ex.state === "paused" || ex.state === "pausing" ? "Resume" : "Pause";
    pause.disabled = !active || ex.state === "stopping";
    $("tex-skip-btn").disabled = !active || !ex.current_case || ex.state === "stopping";
    $("tex-stop-btn").disabled = !active || ex.state === "stopping";
    $("tex-view-results-btn").classList.toggle("hidden", active);
    $("tex-live-dot").classList.toggle("hidden", !active);

    const cur = currentCase();
    const focus = st.focusCase && ex.cases.find((c) => c.case_id === st.focusCase);
    let text;
    if (focus) {
      text = `Viewing <b>${esc(focus.case_id)}</b> · ${esc(focus.name)} · ${esc(caseStatusText(focus))}
        ${focus.status === "done" ? ' <button type="button" class="tex-link-btn" data-live-action="open-result">Open result</button>' : ""}
        <button type="button" class="tex-link-btn" data-live-action="follow">${active ? "Follow the running case" : "Show the last case"}</button>`;
    } else if (cur) {
      const est = cur.estimate_s ? ` · estimate ≈ ${fmtDuration(cur.estimate_s)}` : "";
      text = `Running <b>${esc(cur.case_id)}</b> · ${esc(cur.name)} · ${fmtDuration(secondsSince(cur.started_at))}${est}`;
    } else if (ex.state === "paused") {
      text = "Paused. The next case starts when you resume.";
    } else if (ex.state === "pausing") {
      text = "Pausing after the current case…";
    } else if (!active) {
      text = `Run ${esc((STATE_LABEL[ex.state] || ex.state).toLowerCase())} · ${esc(summaryText(ex.summary) || "no cases finished")}`;
    } else {
      text = "Starting…";
    }
    const html = `${text} <span class="muted">· ${done}/${ex.cases.length} done</span>`;
    if (html !== st.liveCurrentHtml) {
      st.liveCurrentHtml = html;
      $("tex-live-current").innerHTML = html;
    }
  }

  function secondsSince(iso) {
    if (!iso) return 0;
    return Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  }

  function elapsedSeconds() {
    const ex = st.exec;
    if (!ex || !ex.started_at) return 0;
    const end = ex.finished_at && !ACTIVE_STATES.has(ex.state) ? new Date(ex.finished_at).getTime() : Date.now();
    return Math.max(0, (end - new Date(ex.started_at).getTime()) / 1000);
  }

  function startElapsedTimer() {
    stopElapsedTimer();
    st.elapsedTimer = setInterval(() => {
      if (st.exec && ACTIVE_STATES.has(st.exec.state)) {
        renderLiveHead();
        const cur = currentCase();
        if (cur) {
          const row = document.querySelector(`[data-queue-case="${CSS.escape(cur.case_id)}"] .tex-case-est`);
          if (row) row.textContent = fmtDuration(secondsSince(cur.started_at));
        }
      }
    }, 1000);
  }

  function stopElapsedTimer() {
    if (st.elapsedTimer) clearInterval(st.elapsedTimer);
    st.elapsedTimer = null;
  }

  function renderQueue() {
    const ex = st.exec;
    if (!ex) return;
    const focus = focusCaseId();
    $("tex-queue").innerHTML = ex.cases.map((c) => {
      let status;
      if (c.status === "done") status = verdictPill(effectiveVerdict(c));
      else if (c.status === "running") status = pill("Running", "is-running");
      else if (c.status === "cancelled") status = pill("Not run", "is-muted");
      else status = pill("Queued", "");
      const time = c.status === "done" ? fmtDuration(c.duration_s)
        : c.status === "running" ? fmtDuration(secondsSince(c.started_at)) : c.estimate_s ? `≈ ${fmtDuration(c.estimate_s)}` : "";
      const selected = c.case_id === focus;
      return `
        <button type="button" class="tex-queue-row ${c.status === "running" ? "is-running" : ""} ${selected ? "is-focus" : ""}"
          data-queue-case="${esc(c.case_id)}" aria-pressed="${selected ? "true" : "false"}"
          title="Show this case's log and metrics">
          <span class="tex-case-id">${esc(c.case_id)}</span>
          <span class="tex-case-name">${esc(c.name)}</span>
          <span class="tex-case-est">${esc(time)}</span>
          ${status}
        </button>`;
    }).join("");
  }

  function setFocusCase(caseId) {
    const ex = st.exec;
    st.focusCase = caseId && ex && caseId !== ex.current_case ? caseId : null;
    renderLiveHead();
    renderQueue();
    renderMetrics();
    if ($("tex-log-filter").value === "current") renderLog();
  }

  function logVisible(entry) {
    const filter = $("tex-log-filter").value;
    if (filter === "current") return st.exec && entry.case_id === focusCaseId();
    if (filter === "important") return ["op", "op_fail", "metric", "error", "manual", "case", "case_bad"].includes(entry.level);
    return true;
  }

  function lastCaseId() {
    const started = (st.exec ? st.exec.cases : []).filter((c) => c.status === "done" || c.status === "running");
    return started.length ? started[started.length - 1].case_id : null;
  }

  function logLine(entry) {
    return `<span class="tex-log-line lvl-${esc(entry.level || "info")}"><span class="tex-log-meta"><span class="tex-log-time">${esc(entry.time || "")}</span> <span class="tex-log-case">${esc(entry.case_id || "")}</span></span> <span class="tex-log-msg">${esc(entry.text)}</span></span>\n`;
  }

  function pushLog(entry) {
    st.logs.push(entry);
    if (st.logs.length > MAX_LOG_LINES) {
      st.logs = st.logs.slice(-Math.floor(MAX_LOG_LINES * 0.8));
      renderLog();
      return;
    }
    if (logVisible(entry)) {
      const log = $("tex-log");
      log.insertAdjacentHTML("beforeend", logLine(entry));
      if ($("tex-autoscroll").checked) log.scrollTop = log.scrollHeight;
    }
  }

  function renderLog() {
    const log = $("tex-log");
    const lines = st.logs.filter(logVisible);
    log.innerHTML = lines.length
      ? lines.map(logLine).join("")
      : `<span class="tex-log-line lvl-cmd"><span class="tex-log-msg">${$("tex-log-filter").value === "current" ? "No log lines for this case yet." : "Waiting for output…"}</span></span>`;
    if ($("tex-autoscroll").checked) log.scrollTop = log.scrollHeight;
  }

  function renderMetrics() {
    const caseId = focusCaseId();
    const list = st.metrics.filter((m) => m.case_id === caseId);
    $("tex-metrics").innerHTML = list.length
      ? `<div class="tex-muted-small">${esc(caseId)}</div>
         <table class="tex-table tex-table-compact"><tbody>${list.map((m) => `
          <tr><td>${m.passed == null ? "" : m.passed ? '<span class="tex-ok" aria-label="passed">✔</span>' : '<span class="tex-bad" aria-label="failed">✘</span>'}</td>
          <td>${esc(m.key)}</td><td><b>${esc(m.actual)}</b></td>
          <td class="muted">${m.operator ? `${esc(m.operator)} ${esc(m.target)}` : ""}</td></tr>`).join("")}</tbody></table>`
      : `<div class="muted tex-small">${caseId ? `No metrics for ${esc(caseId)}. ` : ""}Metrics appear here as each case checks its SLAs.</div>`;
  }

  function renderManual() {
    $("tex-manual").innerHTML = st.manual.length
      ? st.manual.map((m) => `<div class="tex-manual-item"><span class="tex-case-id">${esc(m.case_id)}</span> ${esc(m.text)}</div>`).join("") +
        `<div class="muted tex-small">Decide these on the Results tab once the case finishes.</div>`
      : `<div class="muted tex-small">No tester checkpoints so far.</div>`;
  }

  function renderHealth() {
    $("tex-health").innerHTML = `<div class="tex-kv tex-health-inline">${healthRows(st.health || {})}</div>`;
  }

  function syncScreenPolling() {
    const on = $("tex-screen-toggle").checked && st.viewVisible && st.tab === "live" && st.exec;
    const img = $("tex-screen");
    img.classList.toggle("hidden", !on);
    if (on && !st.screenTimer) {
      const refresh = () => {
        img.src = `${api()}/api/execution/devices/${encodeURIComponent(st.exec.serial)}/screenshot?t=${Date.now()}`;
      };
      refresh();
      st.screenTimer = setInterval(refresh, 3000);
    } else if (!on && st.screenTimer) {
      clearInterval(st.screenTimer);
      st.screenTimer = null;
    }
  }

  async function control(action) {
    if (!st.exec) return;
    if (action === "stop") {
      const go = await uiDialog({
        title: "Stop the execution?",
        bodyHtml: "The current case is interrupted; its teardown still restores the device. Cases that have not started are marked Not run.",
        okLabel: "Stop execution",
        cancelLabel: "Keep running",
        danger: true
      });
      if (!go) return;
    }
    try {
      const rec = await postJSON(`/api/executions/${st.exec.id}/control`, { action });
      st.exec.state = rec.state;
      renderLiveHead();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  // ── Results ─────────────────────────────────────────

  async function openResults(execId, caseId) {
    let rec;
    try {
      rec = await getJSON(`/api/executions/${execId}`);
    } catch (err) {
      toast(`Could not load execution ${execId}: ${err.message}`, "error");
      return;
    }
    if (!st.results || st.results.id !== execId) {
      st.causeFilter = null;
      st.filters = { q: "", verdict: "", sort: "default" };
      st.reviewMode = false;
      st.reviewQueue = [];
      st.prevExec = null;
      $("tex-results-search").value = "";
      $("tex-results-sort").value = "default";
    }
    st.results = rec;
    st.causes = rec.causes || {};
    st.detail = null;
    renderResults();
    showTab("results");
    loadPrevious(rec);
    const cases = rec.cases;
    const first = caseId || (cases.find((c) => c.cause !== "passed" && c.cause !== "not_run") || cases[0] || {}).case_id;
    if (first) openCaseDetail(first);
    else $("tex-case-detail").innerHTML = "";
  }

  const pendingReviewIds = () =>
    (st.results ? st.results.cases : []).filter((c) => c.verdict === "MANUAL_REVIEW" && !c.review).map((c) => c.case_id);

  function passRateHtml(s) {
    const v = s.by_verdict || {};
    const pass = v.PASS || 0;
    const decided = pass + (v.FAIL || 0) + (v.ERROR || 0);
    const excluded = VERDICT_ORDER.filter((k) => !["PASS", "FAIL", "ERROR"].includes(k) && v[k])
      .map((k) => `${v[k]} ${(VERDICT_LABEL[k] || k).toLowerCase()}`);
    const tip = `Pass rate = Pass ÷ (Pass + Fail + Error) = ${pass} ÷ ${decided}.` +
      (excluded.length ? ` Not counted: ${excluded.join(", ")}.` : "");
    return `
      <div class="tex-pass-rate" title="${esc(tip)}">
        <b>${s.pass_rate != null ? `${s.pass_rate}%` : "–"}</b>
        <span>Pass rate <span class="tex-info-dot" aria-hidden="true">i</span></span>
        <span class="tex-muted-small">${decided ? `${pass} of ${decided} decided` : "no decided cases"}${excluded.length ? ` · ${esc(excluded.join(", "))} not counted` : ""}</span>
      </div>`;
  }

  function verdictBarHtml(byVerdict, total, compact) {
    const entries = VERDICT_ORDER.filter((k) => byVerdict[k]);
    const bar = entries.map((k) =>
      `<span class="tex-seg tone-${VERDICT_TONE[k]}" style="flex-grow:${byVerdict[k]}" title="${esc(`${VERDICT_LABEL[k] || k}: ${byVerdict[k]}`)}"></span>`).join("");
    const label = entries.map((k) => `${VERDICT_LABEL[k] || k}: ${byVerdict[k]}`).join(", ");
    if (compact) return `<div class="tex-verdict-bar is-compact" role="img" aria-label="${esc(label)}">${bar}</div>`;
    const legend = entries.map((k) =>
      `<span class="tex-legend-item"><span class="tex-legend-swatch tone-${VERDICT_TONE[k]}"></span>${esc(VERDICT_LABEL[k] || k)} <b>${byVerdict[k]}</b></span>`).join("");
    return `
      <div class="tex-verdict-summary">
        <div class="tex-verdict-bar" role="img" aria-label="${esc(`${total} cases: ${label}`)}">${bar}</div>
        <div class="tex-legend">${legend}</div>
      </div>`;
  }

  function renderResults() {
    const r = st.results;
    $("tex-results-empty").classList.toggle("hidden", !!r);
    $("tex-results").classList.toggle("hidden", !r);
    if (!r) {
      $("tex-review-badge").classList.add("hidden");
      return;
    }
    const s = r.summary || {};
    const device = r.device || {};
    const overrides = Object.entries(r.overrides || {}).map(([k, v]) => `${k}=${v}`).join(", ");
    const categories = Object.entries(s.by_category || {});
    const cats = categories.length > 1 ? categories.map(([cat, counts]) => {
      const total = Object.values(counts).reduce((a, b) => a + b, 0);
      return `<span class="tex-chip">${esc(cat)}: ${counts.PASS || 0}/${total} pass</span>`;
    }).join("") : "";
    const rerunCount = r.cases.filter((c) => RERUN_CAUSES.has(c.cause)).length;
    const active = ACTIVE_STATES.has(r.state);
    $("tex-results-head").innerHTML = `
      <div class="tex-live-title-row">
        <div>
          <div class="tex-live-title">${esc(execTitle(r))} ${statePill(r.state)}</div>
          <div class="muted tex-live-meta">
            <span class="tex-mono">${esc(r.id)}</span> · script set <span class="tex-mono">${esc(r.run_id)}</span> ·
            ${esc(deviceName(device, r.serial))} (Android ${esc(device.android_version || "?")}) ·
            ${esc(fmtShort(r.started_at))} → ${esc(r.finished_at ? hhmm(r.finished_at) : "…")} · ${fmtDuration(s.duration_s)}
            ${overrides ? `<br>Overrides: ${esc(overrides)}` : ""}
          </div>
        </div>
        ${passRateHtml(s)}
      </div>
      ${verdictBarHtml(s.by_verdict || {}, s.total || r.cases.length)}
      ${cats ? `<div class="tex-chips">${cats}</div>` : ""}
      <div class="tex-results-bar">
        <div class="btn-row">
          <button type="button" class="primary tsg-small-btn" data-res-action="rerun-failed" ${rerunCount && !active ? "" : "disabled"}
            title="${rerunCount ? "Failed, spec-mismatch, blocked, errored, stopped and not-run cases" : "Nothing to rerun"}">
            Rerun failed &amp; blocked${rerunCount ? ` (${rerunCount})` : ""}</button>
          <button type="button" class="secondary tsg-small-btn" data-res-action="rerun-all" ${active ? "disabled" : ""}>Rerun all</button>
          <button type="button" class="secondary tsg-small-btn" data-res-action="compare-prev" disabled
            title="Looking for an earlier run of this script set…">Compare with previous run</button>
        </div>
        <details class="tex-menu">
          <summary class="secondary tsg-small-btn" aria-haspopup="menu">Export ▾</summary>
          <div class="tex-menu-list" role="menu">
            <button type="button" role="menuitem" data-res-action="export-html">HTML report</button>
            <button type="button" role="menuitem" data-res-action="export-junit">JUnit XML</button>
            <button type="button" role="menuitem" data-res-action="export-json">JSON (full results)</button>
          </div>
        </details>
      </div>`;
    syncCompareButton();

    const byCause = s.by_cause || {};
    $("tex-causes").innerHTML = CAUSE_ORDER.filter((k) => byCause[k]).map((k) => {
      const meta = st.causes[k] || { label: k, description: "", action: "" };
      const on = st.causeFilter === k;
      return `
        <button type="button" class="tex-cause-card cause-${esc(k)} ${on ? "is-active" : ""}" data-cause="${esc(k)}"
          aria-pressed="${on ? "true" : "false"}" title="${on ? "Show all cases" : `Show only: ${esc(meta.label)}`}">
          <div class="tex-cause-top"><span><span class="tex-cause-icon" aria-hidden="true">${CAUSE_ICON[k] || "•"}</span>${esc(meta.label)}</span><b>${byCause[k]}</b></div>
          <div class="tex-cause-desc">${esc(meta.description)}</div>
          ${meta.action ? `<div class="tex-cause-action">${esc(meta.action)}</div>` : ""}
        </button>`;
    }).join("");

    const present = VERDICT_ORDER.filter((k) => r.cases.some((c) => (effectiveVerdict(c) || "NOT_RUN") === k));
    if (st.filters.verdict && !present.includes(st.filters.verdict)) st.filters.verdict = "";
    $("tex-results-verdict").innerHTML = `<option value="">All verdicts</option>` +
      present.map((k) => `<option value="${k}" ${st.filters.verdict === k ? "selected" : ""}>${esc(VERDICT_LABEL[k] || k)}</option>`).join("");

    renderReviewBanner();
    renderResultsTable();
  }

  function renderReviewBanner() {
    const pending = pendingReviewIds();
    const badge = $("tex-review-badge");
    badge.textContent = String(pending.length);
    badge.classList.toggle("hidden", !pending.length);
    const box = $("tex-review-banner");
    if (!pending.length && !st.reviewMode) {
      box.innerHTML = "";
      return;
    }
    if (st.reviewMode) {
      const total = st.reviewQueue.length;
      const decided = total - st.reviewQueue.filter((id) => pending.includes(id)).length;
      box.innerHTML = `
        <div class="tex-review-banner is-active" role="region" aria-label="Manual review">
          <div>
            <b>Reviewing manual checkpoints · ${decided} of ${total} decided</b>
            <div class="tex-muted-small">Check the device or the captured media, then mark Pass or Fail. Keys: <kbd>P</kbd> pass · <kbd>F</kbd> fail · <kbd>J</kbd>/<kbd>K</kbd> next/previous.</div>
          </div>
          <button type="button" class="secondary tsg-small-btn" data-review-action="exit">Exit review</button>
        </div>`;
      return;
    }
    box.innerHTML = `
      <div class="tex-review-banner" role="region" aria-label="Manual review">
        <div>
          <b>${pending.length} case${pending.length === 1 ? " needs" : "s need"} your review</b>
          <div class="tex-muted-small">Manual checkpoints wait for a Pass/Fail decision; until then they are not counted in the pass rate.</div>
        </div>
        <button type="button" class="primary tsg-small-btn" data-review-action="start">Start review</button>
      </div>`;
  }

  function startReview() {
    const pending = pendingReviewIds();
    if (!pending.length) return;
    st.reviewMode = true;
    st.reviewQueue = pending;
    renderReviewBanner();
    openCaseDetail(pending[0]);
  }

  function exitReview() {
    st.reviewMode = false;
    st.reviewQueue = [];
    renderReviewBanner();
    if (st.detail) renderCaseDetail();
  }

  /** Root failure in a few words: the spec value for spec mismatches, else the first non-consequential part. */
  function shortReason(c) {
    const reason = cleanReason(c.reason);
    if (!reason) return "";
    const spec = reason.match(/^Spec mismatch: device does not support ([A-Z0-9_]+)=(.*?) from /);
    if (spec) return `${spec[1]} = ${spec[2]} not supported by the device`;
    const parts = reason.split(/;\s+/).map((p) => p.replace(/^main:\s*/, ""));
    const primary = parts.filter((p) => !/^verify: previous result has no/i.test(p) && !/\(actual SKIPPED: missing /i.test(p));
    const first = primary[0] || parts[0];
    return parts.length > 1 ? `${first} (+${parts.length - 1} more)` : first;
  }

  function filteredCases() {
    const r = st.results;
    const q = st.filters.q.trim().toLowerCase();
    let rows = r.cases.filter((c) =>
      (!st.causeFilter || c.cause === st.causeFilter) &&
      (!st.filters.verdict || (effectiveVerdict(c) || "NOT_RUN") === st.filters.verdict) &&
      (!q || `${c.case_id} ${c.name} ${c.reason}`.toLowerCase().includes(q)));
    const sort = st.filters.sort;
    if (sort === "severity") {
      const rank = (c) => VERDICT_SEVERITY.indexOf(effectiveVerdict(c) || "NOT_RUN");
      rows = [...rows].sort((a, b) => rank(a) - rank(b));
    } else if (sort === "duration") {
      rows = [...rows].sort((a, b) => (b.duration_s || 0) - (a.duration_s || 0));
    } else if (sort === "name") {
      rows = [...rows].sort((a, b) => String(a.name).localeCompare(String(b.name)));
    }
    return rows;
  }

  function renderResultsTable() {
    const r = st.results;
    const rows = filteredCases();
    const filtered = !!(st.causeFilter || st.filters.verdict || st.filters.q.trim());
    const causeLabel = st.causeFilter ? (st.causes[st.causeFilter] || {}).label || st.causeFilter : "";
    $("tex-results-count").textContent = filtered
      ? `Showing ${rows.length} of ${r.cases.length}${causeLabel ? ` · ${causeLabel}` : ""}`
      : `${r.cases.length} cases`;
    $("tex-results-clear").classList.toggle("hidden", !filtered);
    const selectedId = st.detail && st.detail.case.case_id;
    $("tex-results-table").innerHTML = rows.length ? `
      <table class="tex-table">
        <thead><tr><th>Verdict</th><th>Case</th><th>Name</th><th>Cause</th><th>Reason</th><th>Time</th></tr></thead>
        <tbody>${rows.map((c) => {
          const selected = selectedId === c.case_id;
          const bug = isScriptBug(c);
          return `
          <tr class="tex-row ${selected ? "is-selected" : ""}" data-case-id="${esc(c.case_id)}" tabindex="0"
            aria-selected="${selected ? "true" : "false"}">
            <td>${verdictPill(effectiveVerdict(c))}${c.review ? ' <span class="tex-muted-small">reviewed</span>' : ""}</td>
            <td class="tex-case-id">${esc(c.case_id)}</td>
            <td class="tex-name-cell">${esc(c.name)}</td>
            <td>${bug ? '<span class="tex-chip is-bug" title="Bug in the generated script, not a device failure">Script bug</span>'
              : esc((st.causes[c.cause] || {}).label || c.cause || "")}</td>
            <td class="tex-reason" title="${esc(cleanReason(c.reason))}">${esc(shortReason(c))}</td>
            <td>${fmtDuration(c.duration_s)}</td>
          </tr>`;
        }).join("")}</tbody>
      </table>` : `<div class="muted tex-small tex-empty-inline">No cases match these filters.
        <button type="button" class="tex-link-btn" data-res-clear>Clear filters</button></div>`;
    const row = selectedId && $("tex-results-table").querySelector(`tr[data-case-id="${CSS.escape(selectedId)}"]`);
    if (row) row.scrollIntoView({ block: "nearest" });
  }

  function clearResultFilters() {
    st.causeFilter = null;
    st.filters = { q: "", verdict: "", sort: st.filters.sort };
    $("tex-results-search").value = "";
    renderResults();
  }

  async function loadPrevious(r) {
    try {
      const list = (await getJSON(`/api/executions?run_id=${encodeURIComponent(r.run_id)}`)).executions || [];
      st.prevExec = list.find((h) => h.id < r.id && !ACTIVE_STATES.has(h.state)) || null;
    } catch (err) {
      st.prevExec = null;
    }
    if (st.results && st.results.id === r.id) syncCompareButton();
  }

  function syncCompareButton() {
    const btn = $("tex-results-head").querySelector('[data-res-action="compare-prev"]');
    if (!btn) return;
    const prev = st.prevExec;
    btn.disabled = !prev;
    btn.title = prev ? `Compare with ${execTitle(prev)} (${prev.id})` : "No earlier finished run of this script set";
  }

  async function compareWithPrevious() {
    const r = st.results;
    const prev = st.prevExec;
    if (!r || !prev) return;
    $("tex-history-scope").value = "all";
    st.compareSel = new Set([prev.id, r.id]);
    showTab("history");
    await loadHistory();
    await compareSelected();
    $("tex-compare-card").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function openCaseDetail(caseId) {
    if (!st.results) return;
    try {
      st.detail = await getJSON(`/api/executions/${st.results.id}/cases/${caseId}`);
    } catch (err) {
      $("tex-case-detail").innerHTML = `<div class="callout warn">${esc(err.message)}</div>`;
      return;
    }
    renderCaseDetail();
    renderResultsTable();
  }

  function stepCase(dir) {
    if (!st.results) return;
    const list = st.reviewMode ? st.reviewQueue : filteredCases().map((c) => c.case_id);
    if (!list.length) return;
    const cur = st.detail ? list.indexOf(st.detail.case.case_id) : -1;
    const next = cur === -1 ? list[0] : list[Math.min(list.length - 1, Math.max(0, cur + dir))];
    if (next && (!st.detail || next !== st.detail.case.case_id)) openCaseDetail(next);
  }

  function section(title, body, open) {
    return `<details class="tex-section" ${open ? "open" : ""}><summary>${title}</summary><div class="tex-section-body">${body}</div></details>`;
  }

  /** Splits failed checks into the root failure, other independent failures and follow-on failures. */
  function analyzeChecks(checks) {
    const failed = checks.filter((k) => !k.passed);
    const isFollowOn = (k) =>
      /^verify: previous result has no/i.test(k.description || "") || /^SKIPPED: missing /i.test(String(k.actual ?? ""));
    const message = (k) => String(k.actual ?? "").replace(/^(FAIL|SKIPPED|NOT_APPLICABLE|ERROR):\s*/i, "").trim();
    const primary = failed.filter((k) => !isFollowOn(k));
    const root = primary[0] || null;
    const rootMsg = root ? message(root) || root.description : "";
    return {
      failed,
      root,
      rootMsg,
      sameRoot: root ? primary.filter((k) => (message(k) || k.description) === rootMsg) : [],
      otherFailed: root ? primary.filter((k) => (message(k) || k.description) !== rootMsg) : [],
      followOn: failed.filter(isFollowOn),
      passed: checks.filter((k) => k.passed)
    };
  }

  const RESULT_STATUS = /^(PASS|FAIL|SKIPPED|NOT_APPLICABLE|ERROR|HARNESS_ERROR|BLOCKED_PRECONDITION)\b:?\s*/;
  const STATUS_TEXT = {
    PASS: "Pass",
    FAIL: "Fail",
    SKIPPED: "Skipped",
    NOT_APPLICABLE: "Not applicable",
    ERROR: "Error",
    HARNESS_ERROR: "Harness error",
    BLOCKED_PRECONDITION: "Blocked"
  };

  /** What the check required; inferred for results recorded before checks carried "expected". */
  function checkExpected(k) {
    if (k.expected != null && k.expected !== "") return String(k.expected);
    if (k.operator) return `${k.operator} ${k.target ?? ""}`.trim();
    const desc = String(k.description || "");
    const missing = desc.match(/previous result has no '([^']+)'/i);
    if (missing) return `'${missing[1]}' from the previous step`;
    if (/\(command ran\)$/i.test(desc)) return "exit code 0";
    const inText = desc.match(/\b(?:matches|equals|is at least|is at most|within)\s+(.+?)\.?$/i);
    if (inText) return inText[1];
    return RESULT_STATUS.test(String(k.actual ?? "")) ? "PASS" : "condition holds";
  }

  function checkActual(k) {
    if (k.actual == null || k.actual === "") {
      return /previous result has no/i.test(k.description || "")
        ? "<b>not returned</b>"
        : '<span class="muted">not recorded</span>';
    }
    const text = String(k.actual);
    const status = text.match(RESULT_STATUS);
    if (!status) return `<b>${esc(text)}</b>`;
    const detail = text.slice(status[0].length).trim();
    return `<b>${esc(STATUS_TEXT[status[1]] || status[1])}</b>${detail ? `<div class="tex-check-detail">${esc(detail)}</div>` : ""}`;
  }

  function checkRows(list) {
    return list.map((k) => {
      const expected = checkExpected(k);
      return `<tr class="${k.passed ? "" : "tex-row-bad"}">
      <td>${k.passed ? '<span class="tex-ok" aria-label="passed">✔</span>' : '<span class="tex-bad" aria-label="failed">✘</span>'}</td>
      <td>${esc(k.description)}${k.failure_classification ? `<div class="tex-muted-small">${esc(k.failure_classification)}</div>` : ""}</td>
      <td>${expected === "PASS" ? esc(STATUS_TEXT.PASS) : esc(expected)}</td>
      <td>${checkActual(k)}</td></tr>`;
    }).join("");
  }

  const checkTable = (list) => `<table class="tex-table tex-table-compact"><thead><tr><th></th><th>Check</th><th>Expected</th><th>Actual</th></tr></thead>
    <tbody>${checkRows(list)}</tbody></table>`;

  const splitList = (v) => String(v ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  const humanName = (name) => {
    const text = String(name || "").toLowerCase().replace(/_/g, " ");
    return text.charAt(0).toUpperCase() + text.slice(1);
  };

  /** Reduces one spec-vs-device row to: what is missing, the device's best value and its other values. */
  function mismatchFacts(row) {
    const zoom = /ZOOM/i.test(row.name);
    const fmt = (v) => (zoom && /^[\d.]+$/.test(v) ? `${v}x` : v);
    const related = Object.fromEntries(row.related.map((x) => [x.name, x.value]));
    const minKey = Object.keys(related).find((k) => /^MIN_/.test(k));
    const maxKey = Object.keys(related).find((k) => /^MAX_/.test(k));
    const listKeys = Object.keys(related).filter((k) => /^SUPPORTED_/.test(k));
    const supported = [...new Set([...splitList(row.device), ...listKeys.flatMap((k) => splitList(related[k]))])];
    const spec = splitList(row.spec);
    const missing = spec.filter((v) => !supported.some((s) => s.toLowerCase() === v.toLowerCase()));

    let bestLabel = "Device reports";
    let best = null;
    if (minKey && maxKey) {
      const lo = related[minKey];
      const hi = related[maxKey];
      bestLabel = "Device range";
      best = lo === hi ? `${fmt(hi)} only` : `${fmt(lo)} – ${fmt(hi)}`;
    } else if (maxKey) {
      bestLabel = "Device maximum";
      best = fmt(related[maxKey]);
    } else if (supported.length) {
      bestLabel = supported.length > 1 ? "Device best" : "Device reports";
      best = fmt(supported[0]);
    }
    const others = supported.map(fmt).filter((v) => v !== best);
    return { spec: spec.map(fmt), missing: (missing.length ? missing : spec).map(fmt), best, bestLabel, others };
  }

  function specCompareHtml(sc, cause) {
    const rows = sc.rows.map((row) => {
      const f = mismatchFacts(row);
      const verb = f.missing.length > 1 ? "are" : "is";
      return `
        <div class="tex-mm-row">
          <div class="tex-mm-what" title="${esc(row.name)}">${esc(humanName(row.name))}</div>
          <div class="tex-mm-headline"><span class="tex-mm-bad">${esc(f.missing.join(", "))}</span> ${verb} not supported on this device</div>
          <div class="tex-mm-grid">
            <div class="tex-mm-box is-spec">
              <div class="tex-mm-label">Spec requires</div>
              <div class="tex-mm-value">${esc(f.spec.join(", "))}</div>
            </div>
            <div class="tex-mm-vs" aria-hidden="true">≠</div>
            <div class="tex-mm-box is-device">
              <div class="tex-mm-label">${esc(f.bestLabel)}</div>
              <div class="tex-mm-value">${f.best ? esc(f.best) : '<span class="muted">Not reported</span>'}</div>
              ${f.others.length ? `<div class="tex-mm-others">Also supports ${f.others.map((v) => `<b>${esc(v)}</b>`).join(" · ")}</div>` : ""}
            </div>
          </div>
        </div>`;
    }).join("");
    const foot = [sc.source ? `Spec from ${esc(sc.source)}` : "", sc.harness ? `Harness: ${esc(sc.harness)}` : ""].filter(Boolean);
    return `
      <div class="tex-spec-compare">
        <div class="tex-subhead">Spec mismatch</div>
        ${rows}
        ${foot.length ? `<div class="tex-mm-meta">${foot.join(" · ")}</div>` : ""}
        ${cause.action ? `<div class="tex-mm-note">ⓘ ${esc(cause.action)}</div>` : ""}
      </div>`;
  }

  function renderCaseDetail() {
    const d = st.detail;
    const c = d.case;
    const r = d.result || {};
    const cause = st.causes[c.cause] || {};
    const verdict = effectiveVerdict(c);
    const bug = isScriptBug(c);
    const manual = c.verdict === "MANUAL_REVIEW";
    const parts = [];

    if (st.reviewMode && st.reviewQueue.includes(c.case_id)) {
      const i = st.reviewQueue.indexOf(c.case_id);
      parts.push(`
        <div class="tex-review-nav">
          <span>Review <b>${i + 1}</b> of ${st.reviewQueue.length}</span>
          <div class="btn-row">
            <button type="button" class="secondary tsg-small-btn" data-step="-1" ${i === 0 ? "disabled" : ""}>‹ Previous</button>
            <button type="button" class="secondary tsg-small-btn" data-step="1" ${i === st.reviewQueue.length - 1 ? "disabled" : ""}>Next ›</button>
          </div>
        </div>`);
    }

    parts.push(`
      <div class="tex-detail-head">
        <div>
          <div class="tex-detail-title"><span class="tex-case-id">${esc(c.case_id)}</span> ${esc(c.name)}</div>
          <div class="tex-chips">${verdictPill(verdict)}
            ${c.review ? `<span class="tex-muted-small">Reviewed ${esc(fmtShort(c.review.at))} · originally ${esc(VERDICT_LABEL[c.verdict] || c.verdict)}</span>` : ""}
            ${bug ? '<span class="tex-chip is-bug">Script bug</span>' : `<span class="tex-chip">${esc(cause.label || c.cause || "")}</span>`}
            <span class="tex-chip">${fmtDuration(c.duration_s)}</span>
          </div>
        </div>
        <div class="btn-row">
          <button type="button" class="${bug ? "primary" : "secondary"} tsg-small-btn" data-detail-action="script">View script</button>
          <button type="button" class="secondary tsg-small-btn" data-detail-action="rerun">Rerun this case</button>
        </div>
      </div>`);

    const checks = r.checks || [];
    const analysis = analyzeChecks(checks);
    const reason = cleanReason(c.reason);

    if (bug) {
      parts.push(`<div class="callout warn"><b>This is a bug in the generated script, not a device failure.</b>
        Open the script to see the faulty call, then regenerate the script set on the Test Script Generation page and rerun.</div>`);
      if (reason) parts.push(`<div class="tex-reason-box tex-mono">${esc(reason)}</div>`);
    } else if (c.cause === "spec_mismatch" && d.spec_check) {
      parts.push(specCompareHtml(d.spec_check, cause));
    } else if (analysis.root && (verdict === "FAIL" || verdict === "ERROR")) {
      const affected = analysis.sameRoot.length;
      const follow = analysis.followOn.length;
      const others = analysis.otherFailed.length;
      parts.push(`
        <div class="tex-root">
          <div class="tex-subhead">Root failure</div>
          <div class="tex-root-msg">${esc(analysis.rootMsg)}</div>
          <div class="tex-muted-small">First failed at “${esc(analysis.root.description)}”${affected > 1 ? ` · same cause in ${affected} checks` : ""}${others ? ` · ${others} other failed check(s)` : ""}${follow ? ` · ${follow} more failed as a consequence` : ""}.</div>
        </div>`);
      if (cause.action) parts.push(`<div class="callout info">${esc(cause.action)}</div>`);
    } else {
      if (reason) parts.push(`<div class="tex-reason-box">${esc(reason)}</div>`);
      const explain = d.blocked_hint || cause.action || "";
      if (explain) parts.push(`<div class="callout ${c.cause === "passed" ? "success" : "info"}">${esc(explain)}</div>`);
    }

    const media = d.files.filter((f) => isImage(f.name) || isVideo(f.name));
    const gallery = media.length
      ? `<div class="tex-media-strip">${media.map((f) => `
          <button type="button" class="tex-media-thumb" data-file-view="${esc(f.name)}" title="${esc(f.name)}">
            ${isImage(f.name)
              ? `<img src="${esc(caseFileUrl(d, f.name))}" alt="${esc(f.name)}" loading="lazy" />`
              : `<span class="tex-media-video">▶ Video</span>`}
            <span class="tex-media-name">${esc(f.name)}</span>
          </button>`).join("")}</div>`
      : "";

    if (manual) {
      const steps = (r.manual_steps || []).map((s) => `<li>${esc(s)}</li>`).join("");
      parts.push(`
        <div class="tex-review ${c.review ? "is-decided" : ""}">
          <div class="tex-subhead">Manual review</div>
          ${steps ? `<ol class="tex-review-steps">${steps}</ol>` : ""}
          ${gallery ? `<div class="tex-small">Captured by this case (click to enlarge):</div>${gallery}` : ""}
          ${c.review ? `<div class="tex-small">Decided <b>${esc(VERDICT_LABEL[c.review.decision] || c.review.decision)}</b> at ${esc(fmtShort(c.review.at))}${c.review.note ? ` · ${esc(c.review.note)}` : ""}. You can change the decision below.</div>` : ""}
          <textarea class="input tex-review-note" id="tex-review-note" rows="2" placeholder="Note (optional)" aria-label="Review note">${esc((c.review && c.review.note) || "")}</textarea>
          <div class="btn-row">
            <button type="button" class="soft-danger tsg-small-btn" data-review="FAIL">Mark Fail <kbd>F</kbd></button>
            <button type="button" class="soft-success tsg-small-btn" data-review="PASS">Mark Pass <kbd>P</kbd></button>
          </div>
        </div>`);
    }

    if (gallery && !manual) parts.push(section(`Captured media (${media.length})`, gallery, true));

    if (checks.length) {
      const failedCount = analysis.failed.length;
      const main = checks.filter((k) => !analysis.followOn.includes(k));
      const follow = analysis.followOn.length
        ? `<details class="tex-disclosure"><summary>${analysis.followOn.length} follow-on failure(s): could not run because an earlier step failed</summary>
            <div class="tex-disclosure-body">${checkTable(analysis.followOn)}</div></details>`
        : "";
      parts.push(section(`Checks (${failedCount} failed of ${checks.length})`, `${checkTable(main)}${follow}`, !manual));
    }

    if (reason && (c.cause === "spec_mismatch" || (analysis.root && reason.length > 120))) {
      parts.push(section("Full reason", `<div class="tex-reason-box">${esc(reason)}</div>`));
    }

    const ops = r.operations || r.instrumentations || [];
    if (ops.length) {
      parts.push(section(`Harness operations (${ops.length})`, ops.map((o) => {
        const res = o.result || {};
        const metrics = Object.fromEntries(Object.entries(res).filter(([k]) => !["result", "error", "reason"].includes(k)));
        return `<div class="tex-op">
          <div class="tex-op-head"><b>${esc(o.label || "")}</b> ${esc((o.class || o.cls || "").split(".").pop())}
            ${verdictPill(res.result === "HARNESS_ERROR" ? "ERROR" : res.result)} <span class="muted">${o.duration_s != null ? `${o.duration_s}s` : ""}</span></div>
          ${o.args && Object.keys(o.args).length ? `<div class="tex-muted-small">args ${esc(JSON.stringify(o.args))}</div>` : ""}
          ${res.error || res.reason ? `<div class="tex-bad tex-small">${esc(res.error || res.reason)}</div>` : ""}
          ${Object.keys(metrics).length ? `<pre class="tex-json">${esc(JSON.stringify(metrics, null, 1))}</pre>` : ""}
        </div>`;
      }).join("")));
    }

    const metrics = { ...(r.derived || {}), ...(r.metrics || {}) };
    if (Object.keys(metrics).length) {
      parts.push(section("Metrics", `<table class="tex-table tex-table-compact"><tbody>${Object.entries(metrics)
        .map(([k, v]) => `<tr><td>${esc(k)}</td><td><b>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</b></td></tr>`).join("")}</tbody></table>`));
    }

    const spec = r.spec_values || c.spec_values || {};
    const vars = r.variables || {};
    if (Object.keys(vars).length) {
      const source = (k) => (k in (d.overrides || {}) ? "override" : k in spec ? "product spec" : "device / default");
      parts.push(section(`Variables (${Object.keys(vars).length})`, `<table class="tex-table tex-table-compact">
        <thead><tr><th>Name</th><th>Value</th><th>Source</th></tr></thead><tbody>${Object.entries(vars)
        .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td><td class="muted">${esc(source(k))}</td></tr>`).join("")}</tbody></table>`));
    }

    const steps = r.host_steps || [];
    if (steps.length) {
      parts.push(section(`Commands (${steps.length})`, `<table class="tex-table tex-table-compact"><tbody>${steps
        .map((s) => `<tr class="${s.rc ? "tex-row-bad" : ""}"><td class="tex-mono">${esc(s.command)}</td><td>rc ${esc(s.rc)}</td></tr>`).join("")}</tbody></table>`));
    }

    if (d.files.length) {
      parts.push(section(`Evidence files (${d.files.length})`, d.files.map((f) => `
        <div class="tex-file-row"><span class="tex-mono">${esc(f.name)}</span><span class="muted">${(f.size / 1024).toFixed(1)} KB</span>
          <button type="button" class="secondary tsg-small-btn" data-file-view="${esc(f.name)}">View</button>
          <button type="button" class="secondary tsg-small-btn" data-file-download="${esc(f.name)}">Download</button></div>`).join(""), true));
    }

    const notes = r.notes || [];
    if (notes.length) parts.push(section(`Notes (${notes.length})`, `<ul class="tex-notes">${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>`));
    parts.push(section(`Script log${d.log_truncated ? " (last part)" : ""}`, `<pre class="tex-log tex-log-static">${esc(d.log || "(empty)")}</pre>`, bug));

    $("tex-case-detail").innerHTML = parts.join("");
  }

  async function submitReview(decision) {
    const d = st.detail;
    if (!d) return;
    const caseId = d.case.case_id;
    try {
      await postJSON(`/api/executions/${d.execution_id}/cases/${caseId}/review`, {
        decision,
        note: ($("tex-review-note") || {}).value || ""
      });
      st.results = await getJSON(`/api/executions/${d.execution_id}`);
      st.causes = st.results.causes || st.causes;
    } catch (err) {
      toast(err.message, "error");
      return;
    }
    let next = caseId;
    if (st.reviewMode) {
      const pending = pendingReviewIds();
      const i = st.reviewQueue.indexOf(caseId);
      const upcoming = st.reviewQueue.slice(i + 1).concat(st.reviewQueue.slice(0, i + 1)).find((id) => pending.includes(id));
      if (upcoming) {
        next = upcoming;
      } else {
        st.reviewMode = false;
        st.reviewQueue = [];
        toast("All manual reviews are decided.", "success");
      }
    } else {
      toast(`${caseId} marked ${VERDICT_LABEL[decision]}.`, "success");
    }
    renderResults();
    await openCaseDetail(next);
  }

  function showFileModal(title, download, mode) {
    const img = $("tex-file-image");
    const video = $("tex-file-video");
    video.pause();
    $("tex-file-title").textContent = title;
    $("tex-file-body").classList.toggle("hidden", mode !== "text");
    img.classList.toggle("hidden", mode !== "image");
    video.classList.toggle("hidden", mode !== "video");
    if (mode !== "image") img.removeAttribute("src");
    if (mode !== "video") video.removeAttribute("src");
    st.fileDownload = download;
    $("tex-file-modal").classList.remove("hidden");
  }

  async function openFile(name) {
    const d = st.detail;
    const base = `/api/executions/${d.execution_id}/cases/${d.case.case_id}/files/${encodeURIComponent(name)}`;
    const download = { path: `${base}?download=true`, name };
    if (isImage(name) || isVideo(name)) {
      const mode = isImage(name) ? "image" : "video";
      showFileModal(name, download, mode);
      $(mode === "image" ? "tex-file-image" : "tex-file-video").src = caseFileUrl(d, name);
      return;
    }
    showFileModal(name, download, "text");
    $("tex-file-body").textContent = "Loading…";
    try {
      const resp = await fetch(`${api()}${base}`);
      const text = await resp.text();
      $("tex-file-body").textContent = text.length > 400000
        ? `${text.slice(0, 400000)}\n\n… truncated; download the file for the full content.` : text;
    } catch (err) {
      $("tex-file-body").textContent = `Could not load the file: ${err.message}`;
    }
  }

  async function openScript() {
    const d = st.detail;
    const filename = d.case.filename;
    const path = `/api/execution/script-sets/${d.run_id}/scripts/${encodeURIComponent(filename)}`;
    showFileModal(filename, { path, name: filename }, "text");
    $("tex-file-body").textContent = "Loading…";
    try {
      const resp = await fetch(`${api()}${path}`);
      $("tex-file-body").textContent = resp.ok ? await resp.text() : `Script not found (HTTP ${resp.status}).`;
    } catch (err) {
      $("tex-file-body").textContent = `Could not load the script: ${err.message}`;
    }
  }

  async function prefillSetup(runId, caseIds, overrides, timeoutMin) {
    st.pendingSelection = caseIds;
    st.overrides = Object.entries(overrides || {}).map(([name, value]) => ({ name, value }));
    if (timeoutMin) $("tex-timeout").value = timeoutMin;
    renderOverrides();
    showTab("setup");
    await loadSets(runId);
    toast(`${caseIds.length} case(s) selected for a rerun. Review the setup, then start.`, "info");
  }

  function rerun(kind) {
    const r = st.results;
    if (!r) return;
    const ids = kind === "all" ? r.cases.map((c) => c.case_id) : r.cases.filter((c) => RERUN_CAUSES.has(c.cause)).map((c) => c.case_id);
    if (!ids.length) {
      toast("Nothing to rerun: no failed, blocked, errored or stopped cases.");
      return;
    }
    prefillSetup(r.run_id, ids, r.overrides, r.case_timeout_min);
  }

  async function exportReport(format) {
    const r = st.results;
    const ext = { html: "html", junit: "xml", json: "json" }[format];
    try {
      await download(`/api/executions/${r.id}/report?format=${format}`, `test_execution_${r.id}.${ext}`);
      toast(`Exported test_execution_${r.id}.${ext}`, "success");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  // ── History ─────────────────────────────────────────

  async function loadHistory() {
    const scoped = $("tex-history-scope").value === "set" && st.runId;
    try {
      st.history = (await getJSON(`/api/executions${scoped ? `?run_id=${st.runId}` : ""}`)).executions || [];
    } catch (err) {
      $("tex-history").innerHTML = `<div class="callout warn">${esc(err.message)}</div>`;
      $("tex-trend").classList.add("hidden");
      return;
    }
    const ids = new Set(st.history.map((h) => h.id));
    st.compareSel = new Set([...st.compareSel].filter((id) => ids.has(id)));
    renderHistory();
  }

  const passRateOf = (h) => (h.summary && h.summary.pass_rate != null ? h.summary.pass_rate : null);

  /** The previous run (older) of the same script set that has a pass rate. */
  function previousRun(h) {
    const i = st.history.indexOf(h);
    return st.history.slice(i + 1).find((x) => x.run_id === h.run_id && passRateOf(x) != null) || null;
  }

  function deltaHtml(h) {
    const prev = previousRun(h);
    const now = passRateOf(h);
    if (!prev || now == null) return "";
    const diff = Math.round((now - passRateOf(prev)) * 10) / 10;
    const tip = `vs ${passRateOf(prev)}% in the previous run of this script set (${prev.id})`;
    if (diff === 0) return `<span class="tex-delta" title="${esc(tip)}">= 0</span>`;
    return `<span class="tex-delta ${diff > 0 ? "is-up" : "is-down"}" title="${esc(tip)}">${diff > 0 ? "▲" : "▼"} ${Math.abs(diff)}</span>`;
  }

  function sparkline(values) {
    const w = 120;
    const h = 30;
    const pad = 4;
    const pts = values.map((v, i) => [
      pad + (i * (w - 2 * pad)) / Math.max(1, values.length - 1),
      h - pad - (v / 100) * (h - 2 * pad)
    ]);
    const last = pts[pts.length - 1];
    return `<svg class="tex-spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true">
      <line x1="${pad}" x2="${w - pad}" y1="${h - pad}" y2="${h - pad}" class="tex-spark-base" />
      <polyline points="${pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ")}" />
      <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="3" />
    </svg>`;
  }

  function renderTrend() {
    const groups = new Map();
    st.history.forEach((h) => {
      if (passRateOf(h) == null || ACTIVE_STATES.has(h.state)) return;
      if (!groups.has(h.run_id)) groups.set(h.run_id, []);
      groups.get(h.run_id).push(h);
    });
    const sets = [...groups.values()].filter((runs) => runs.length >= 2).slice(0, 4);
    const box = $("tex-trend");
    box.classList.toggle("hidden", !sets.length);
    box.innerHTML = sets.map((runs) => {
      const chrono = [...runs].reverse();
      const values = chrono.map(passRateOf);
      const latest = runs[0];
      return `
        <div class="tex-trend-item" title="${esc(values.map((v, i) => `${fmtShort(chrono[i].started_at || chrono[i].created_at)}: ${v}%`).join("\n"))}">
          <div class="tex-trend-label">
            <b>${esc(titleCase(latest.feature))}</b> · ${esc(latest.product_name ? cleanProduct(latest.product_name) : "no product spec")}
            <div class="tex-muted-small">script set <span class="tex-mono">${esc(latest.run_id)}</span> · ${runs.length} runs</div>
          </div>
          ${sparkline(values)}
          <div class="tex-trend-value"><b>${passRateOf(latest)}%</b> ${deltaHtml(latest)}</div>
        </div>`;
    }).join("");
  }

  function renderHistory() {
    $("tex-compare-btn").disabled = st.compareSel.size !== 2;
    renderTrend();
    if (!st.history.length) {
      $("tex-history").innerHTML = `<div class="muted tex-small">No executions yet.</div>`;
      return;
    }
    $("tex-history").innerHTML = `
      <table class="tex-table">
        <thead><tr><th title="Pick two to compare">Compare</th><th>Execution</th><th>Device</th><th>Verdicts</th><th>Pass rate</th><th>State</th><th><span class="sr-only">Actions</span></th></tr></thead>
        <tbody>${st.history.map((h) => {
          const s = h.summary || {};
          const device = h.device || {};
          const v = s.by_verdict || {};
          const failN = (v.FAIL || 0) + (v.ERROR || 0);
          return `<tr class="tex-row" data-exec-id="${esc(h.id)}" tabindex="0" title="Open results">
            <td><input type="checkbox" class="tex-cmp-check" data-exec-id="${esc(h.id)}" aria-label="Select for comparison" ${st.compareSel.has(h.id) ? "checked" : ""} /></td>
            <td><div class="tex-history-title">${esc(titleCase(h.feature))} · ${esc(h.product_name ? `${cleanProduct(h.product_name)} spec` : "no product spec")}</div>
              <div class="tex-muted-small">${esc(fmtShort(h.started_at || h.created_at))} · <span class="tex-mono">${esc(h.id)}</span></div></td>
            <td>${esc(deviceName(device, h.serial))}<div class="tex-muted-small">Android ${esc(device.android_version || "?")}</div></td>
            <td class="tex-history-verdicts">${verdictBarHtml(v, s.total || 0, true)}
              <div class="tex-muted-small">${s.total ?? "–"} cases · ${v.PASS || 0} pass · ${failN} fail</div></td>
            <td><b>${s.pass_rate != null ? `${s.pass_rate}%` : "–"}</b> ${deltaHtml(h)}</td>
            <td>${statePill(h.state)}</td>
            <td><button type="button" class="tex-link-btn tex-danger-link" data-del-exec="${esc(h.id)}"
              ${ACTIVE_STATES.has(h.state) ? "disabled title=\"Stop the execution first\"" : ""} aria-label="${esc(`Delete ${h.id}`)}">Delete</button></td>
          </tr>`;
        }).join("")}</tbody>
      </table>`;
  }

  async function deleteExecution(id) {
    const h = st.history.find((x) => x.id === id);
    const go = await uiDialog({
      title: "Delete this execution?",
      bodyHtml: `<p>${esc(h ? execTitle(h) : id)}</p><p class="muted">Its results, logs and evidence files are removed permanently. Exported reports are not affected.</p>`,
      okLabel: "Delete",
      danger: true
    });
    if (!go) return;
    try {
      await getJSON(`/api/executions/${id}`, { method: "DELETE" });
    } catch (err) {
      toast(`Could not delete: ${err.message}`, "error");
      return;
    }
    st.compareSel.delete(id);
    if (st.results && st.results.id === id) {
      st.results = null;
      st.detail = null;
      renderResults();
    }
    if (st.exec && st.exec.id === id) {
      if (st.source) st.source.close();
      st.source = null;
      st.exec = null;
      renderLive();
    }
    $("tex-compare-card").classList.add("hidden");
    toast("Execution deleted.", "success");
    loadHistory();
  }

  async function compareSelected() {
    const [a, b] = [...st.compareSel].sort();
    try {
      const data = await getJSON(`/api/executions/compare?a=${a}&b=${b}`);
      const label = (x) => `${execTitle(x)} (${x.id})`;
      $("tex-compare-card").classList.remove("hidden");
      $("tex-compare").innerHTML = `
        <div class="tex-small"><b>A</b> ${esc(label(data.a))}<br><b>B</b> ${esc(label(data.b))}<br>${data.changed} case(s) changed verdict</div>
        <table class="tex-table">
          <thead><tr><th>Case</th><th>Name</th><th>A</th><th>B</th><th>A time</th><th>B time</th></tr></thead>
          <tbody>${data.rows.map((row) => `<tr class="${row.changed ? "tex-row-changed" : ""}">
            <td class="tex-case-id">${esc(row.case_id)}</td><td>${esc(row.name)}</td>
            <td>${row.a ? verdictPill(row.a) : '<span class="muted">–</span>'}</td>
            <td>${row.b ? verdictPill(row.b) : '<span class="muted">–</span>'}</td>
            <td>${fmtDuration(row.a_duration_s)}</td><td>${fmtDuration(row.b_duration_s)}</td></tr>`).join("")}</tbody>
        </table>`;
    } catch (err) {
      toast(err.message, "error");
    }
  }

  // ── Init / events ───────────────────────────────────

  async function resumeActiveExecution() {
    try {
      const list = (await getJSON("/api/executions?limit=20")).executions || [];
      const active = list.find((e) => ACTIVE_STATES.has(e.state));
      if (active && (!st.exec || st.exec.id !== active.id)) connect(active.id);
    } catch (err) {
      /* backend offline; Setup shows the error */
    }
  }

  async function onViewShown() {
    st.viewVisible = true;
    if (!st.init) {
      st.init = (async () => {
        renderOverrides();
        await loadDevices();
        await loadSets(st.runId);
        resumeActiveExecution();
      })();
    } else {
      loadDevices();
    }
    syncScreenPolling();
  }

  /** Enter / Space on a focusable table row acts like a click. */
  function bindRowKeys(container, selector, onActivate) {
    container.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const row = e.target.closest(selector);
      if (!row || e.target !== row) return;
      e.preventDefault();
      onActivate(row);
    });
  }

  function onResultsKey(e) {
    if (!st.viewVisible || st.tab !== "results" || !st.results) return;
    if (!$("tex-dialog").classList.contains("hidden") || !$("tex-file-modal").classList.contains("hidden")) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.target.closest && e.target.closest("input, textarea, select, [contenteditable='true']")) return;
    const key = e.key.toLowerCase();
    if (key === "j") {
      e.preventDefault();
      stepCase(1);
    } else if (key === "k") {
      e.preventDefault();
      stepCase(-1);
    } else if ((key === "p" || key === "f") && st.detail && st.detail.case.verdict === "MANUAL_REVIEW") {
      e.preventDefault();
      submitReview(key === "p" ? "PASS" : "FAIL");
    }
  }

  function bind() {
    document.addEventListener("workbench:view", (e) => {
      if (e.detail.view === "test-execution") onViewShown();
      else {
        st.viewVisible = false;
        syncScreenPolling();
      }
    });
    document.addEventListener("execution:open-set", async (e) => {
      st.runId = e.detail.runId;
      st.pendingSelection = null;
      showTab("setup");
      if (!st.init) return;
      await st.init;
      await loadSets(e.detail.runId);
    });
    document.addEventListener("keydown", onResultsKey);
    document.addEventListener("click", (e) => {
      document.querySelectorAll(".tex-menu[open]").forEach((menu) => {
        if (!menu.contains(e.target)) menu.removeAttribute("open");
      });
    });

    document.querySelectorAll(".tex-tab").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.texTab)));
    document.querySelector(".tex-tabs").addEventListener("keydown", (e) => {
      const i = TABS.indexOf(st.tab);
      const next = { ArrowRight: TABS[(i + 1) % TABS.length], ArrowLeft: TABS[(i - 1 + TABS.length) % TABS.length],
        Home: TABS[0], End: TABS[TABS.length - 1] }[e.key];
      if (!next) return;
      e.preventDefault();
      showTab(next, true);
    });

    $("tex-refresh-devices").addEventListener("click", async () => {
      await loadDevices();
      loadSetDetail(false);
    });
    $("tex-device-select").addEventListener("change", (e) => {
      st.serial = e.target.value;
      renderDeviceInfo();
      loadSetDetail(false);
    });
    $("tex-refresh-sets").addEventListener("click", () => loadSets(st.runId));
    $("tex-set-select").addEventListener("change", (e) => {
      st.runId = e.target.value;
      loadSetDetail(true);
    });

    $("tex-cases").addEventListener("change", (e) => {
      const box = e.target;
      if (box.classList.contains("tex-case-check")) {
        if (box.checked) st.selected.add(box.dataset.caseId);
        else st.selected.delete(box.dataset.caseId);
      } else if (box.classList.contains("tex-cat-check")) {
        st.set.cases.filter((c) => (c.category || "other") === box.dataset.category)
          .forEach((c) => (box.checked ? st.selected.add(c.case_id) : st.selected.delete(c.case_id)));
      } else {
        return;
      }
      renderCases();
    });
    $("tex-select-ready").addEventListener("click", () => {
      if (!st.set) return;
      st.selected = new Set(st.set.cases.filter((c) => RUNNABLE.has(c.status)).map((c) => c.case_id));
      renderCases();
    });
    $("tex-select-none").addEventListener("click", () => {
      st.selected = new Set();
      renderCases();
    });

    $("tex-add-override").addEventListener("click", () => {
      st.overrides.push({ name: "", value: "" });
      renderOverrides();
    });
    $("tex-overrides").addEventListener("input", (e) => {
      const i = e.target.dataset.ovIndex;
      if (i == null) return;
      st.overrides[Number(i)][e.target.dataset.ovField] = e.target.value;
      renderCases();
    });
    $("tex-overrides").addEventListener("click", (e) => {
      const i = e.target.dataset.ovRemove;
      if (i == null) return;
      st.overrides.splice(Number(i), 1);
      renderOverrides();
      renderCases();
    });
    $("tex-smoke-btn").addEventListener("click", applySmokePreset);
    $("tex-start-btn").addEventListener("click", startExecution);
    $("tex-warn-badge").addEventListener("click", () =>
      $("tex-warn-card").scrollIntoView({ behavior: "smooth", block: "center" }));

    $("tex-pause-btn").addEventListener("click", () =>
      control(st.exec && (st.exec.state === "paused" || st.exec.state === "pausing") ? "resume" : "pause"));
    $("tex-skip-btn").addEventListener("click", () => control("skip"));
    $("tex-stop-btn").addEventListener("click", () => control("stop"));
    $("tex-view-results-btn").addEventListener("click", () => st.exec && openResults(st.exec.id));
    $("tex-log-filter").addEventListener("change", renderLog);
    $("tex-screen-toggle").addEventListener("change", syncScreenPolling);
    $("tex-queue").addEventListener("click", (e) => {
      const row = e.target.closest("[data-queue-case]");
      if (row && st.exec) setFocusCase(row.dataset.queueCase);
    });
    $("tex-live-current").addEventListener("click", (e) => {
      const action = e.target.dataset.liveAction;
      if (action === "follow") setFocusCase(null);
      else if (action === "open-result" && st.exec && st.focusCase) openResults(st.exec.id, st.focusCase);
    });

    $("tex-results-head").addEventListener("click", (e) => {
      const action = e.target.dataset.resAction;
      if (!action) return;
      const menu = e.target.closest(".tex-menu");
      if (menu) menu.removeAttribute("open");
      if (action === "rerun-failed") rerun("failed");
      else if (action === "rerun-all") rerun("all");
      else if (action === "compare-prev") compareWithPrevious();
      else if (action.startsWith("export-")) exportReport(action.slice(7));
    });
    $("tex-review-banner").addEventListener("click", (e) => {
      const action = e.target.dataset.reviewAction;
      if (action === "start") startReview();
      else if (action === "exit") exitReview();
    });
    $("tex-causes").addEventListener("click", (e) => {
      const card = e.target.closest("[data-cause]");
      if (!card) return;
      st.causeFilter = st.causeFilter === card.dataset.cause ? null : card.dataset.cause;
      renderResults();
    });
    $("tex-results-search").addEventListener("input", (e) => {
      st.filters.q = e.target.value;
      renderResultsTable();
    });
    $("tex-results-verdict").addEventListener("change", (e) => {
      st.filters.verdict = e.target.value;
      renderResultsTable();
    });
    $("tex-results-sort").addEventListener("change", (e) => {
      st.filters.sort = e.target.value;
      renderResultsTable();
    });
    $("tex-results-clear").addEventListener("click", clearResultFilters);
    $("tex-results-table").addEventListener("click", (e) => {
      if (e.target.closest("[data-res-clear]")) {
        clearResultFilters();
        return;
      }
      const row = e.target.closest("[data-case-id]");
      if (row) openCaseDetail(row.dataset.caseId);
    });
    bindRowKeys($("tex-results-table"), "tr[data-case-id]", (row) => openCaseDetail(row.dataset.caseId));
    $("tex-case-detail").addEventListener("click", (e) => {
      const t = e.target.closest("[data-review],[data-file-view],[data-file-download],[data-detail-action],[data-step]");
      if (!t) return;
      if (t.dataset.review) submitReview(t.dataset.review);
      else if (t.dataset.step) stepCase(Number(t.dataset.step));
      else if (t.dataset.fileView) openFile(t.dataset.fileView);
      else if (t.dataset.fileDownload) {
        const d = st.detail;
        download(`/api/executions/${d.execution_id}/cases/${d.case.case_id}/files/${encodeURIComponent(t.dataset.fileDownload)}?download=true`,
          t.dataset.fileDownload).catch((err) => toast(err.message, "error"));
      } else if (t.dataset.detailAction === "script") openScript();
      else if (t.dataset.detailAction === "rerun") {
        const d = st.detail;
        prefillSetup(d.run_id, [d.case.case_id], d.overrides, st.results && st.results.case_timeout_min);
      }
    });
    document.querySelectorAll('[data-close-modal="tex-file-modal"]').forEach((el) =>
      el.addEventListener("click", () => $("tex-file-video").pause()));
    $("tex-file-download").addEventListener("click", () => {
      if (st.fileDownload) download(st.fileDownload.path, st.fileDownload.name).catch((err) => toast(err.message, "error"));
    });

    $("tex-history-scope").addEventListener("change", loadHistory);
    $("tex-history-refresh").addEventListener("click", loadHistory);
    $("tex-history").addEventListener("change", (e) => {
      if (!e.target.classList.contains("tex-cmp-check")) return;
      const id = e.target.dataset.execId;
      if (e.target.checked) st.compareSel.add(id);
      else st.compareSel.delete(id);
      if (st.compareSel.size > 2) {
        st.compareSel.delete([...st.compareSel][0]);
        renderHistory();
      }
      $("tex-compare-btn").disabled = st.compareSel.size !== 2;
    });
    $("tex-history").addEventListener("click", (e) => {
      if (e.target.classList.contains("tex-cmp-check")) return;
      const del = e.target.closest("[data-del-exec]");
      if (del) {
        deleteExecution(del.dataset.delExec);
        return;
      }
      const row = e.target.closest("tr[data-exec-id]");
      if (row) openResults(row.dataset.execId);
    });
    bindRowKeys($("tex-history"), "tr[data-exec-id]", (row) => openResults(row.dataset.execId));
    $("tex-compare-btn").addEventListener("click", compareSelected);
  }

  bind();
})();
