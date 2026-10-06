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
  const pill = (text, cls) => `<span class="status-pill ${cls || ""}">${esc(text)}</span>`;

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
  const verdictPill = (v) => pill(VERDICT_LABEL[v] || v || "Not run", VERDICT_CLASS[v] || "");
  const effectiveVerdict = (c) => (c.review && c.review.decision) || c.verdict;

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
  const ACTIVE_STATES = new Set(["queued", "running", "pausing", "paused", "stopping"]);
  const THERMAL = ["None", "Light", "Moderate", "Severe", "Critical", "Emergency", "Shutdown"];
  const LONG_RUN_S = 30 * 60;
  const MAX_LOG_LINES = 4000;

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
    elapsedTimer: null,
    screenTimer: null,
    results: null,
    causes: {},
    causeFilter: null,
    detail: null,
    history: [],
    compareSel: new Set(),
    fileDownload: null
  };

  // ── Tabs ────────────────────────────────────────────

  function showTab(tab) {
    st.tab = tab;
    document.querySelectorAll(".tex-tab").forEach((b) =>
      b.classList.toggle("is-active", b.dataset.texTab === tab));
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
    const name = [d.manufacturer, d.model].filter(Boolean).join(" ") || d.serial;
    if (d.state !== "device") return `${d.serial} · ${d.state}`;
    return `${d.serial} · ${name} · ${d.is_emulator ? "Emulator" : "Phone"} · Android ${d.android_version || "?"}`;
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
      <div class="tex-kv">
        <div class="tex-kv-row"><span>Model</span><span>${esc([d.manufacturer, d.model].filter(Boolean).join(" ") || "–")}</span></div>
        <div class="tex-kv-row"><span>Android</span><span>${esc(d.android_version || "–")} (API ${esc(d.sdk_int ?? "?")})</span></div>
        <div class="tex-kv-row"><span>Type</span><span>${d.is_emulator ? "Emulator" : "Physical device"}</span></div>
        ${healthRows(h)}
      </div>
      <div class="tex-subhead">Harness packages</div>
      <div class="tex-kv">${pkgs || '<span class="muted">None</span>'}</div>
      ${busy ? `<div class="callout info">Busy: execution ${esc(st.exec.id)} is running on this device.</div>` : ""}`;
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
          ${esc(fmtTime(s.created_at))} · ${esc(s.feature)} · ${s.script_count} script(s)${s.product_name ? ` · ${esc(s.product_name)}` : ""}${s.execution_count ? ` · ${s.execution_count} run(s)` : ""}
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
    const spec = Object.entries(s.spec_applied || {})
      .map(([k, v]) => `<span class="tex-chip" title="${esc(v.source || "")}">${esc(k)} = ${esc(v.value)}</span>`)
      .join("");
    $("tex-set-info").innerHTML = `
      <div class="tex-kv">
        <div class="tex-kv-row"><span>Generated</span><span>${esc(fmtTime(s.created_at))}</span></div>
        <div class="tex-kv-row"><span>Feature</span><span>${esc(s.feature)}</span></div>
        <div class="tex-kv-row"><span>Product spec</span><span>${esc(s.product_name || "None (placeholders from device)")}</span></div>
        <div class="tex-kv-row"><span>Runtime</span><span>${esc(s.runtime || "–")} ${esc(s.runtime_version || "")}</span></div>
        <div class="tex-kv-row"><span>Harness</span><span>${esc(s.harness_version ? `v${s.harness_version}` : "–")}</span></div>
      </div>
      ${spec ? `<div class="tex-subhead">Spec values in these scripts</div><div class="tex-chips">${spec}</div>` : ""}`;
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
        ${changes.length ? `<span class="tex-warn-icon" title="Changes the device: ${esc(changes.join(", "))}">⚠</span>` : ""}
        <span title="${esc(tip)}">${pill(label, cls)}</span>
        ${issues.length ? `<div class="tex-case-issues">${esc(issues.join(" · "))}</div>` : ""}
      </div>`;
  }

  function selectedCases() {
    return st.set ? st.set.cases.filter((c) => st.selected.has(c.case_id)) : [];
  }

  function renderStartSummary() {
    const cases = selectedCases();
    const total = cases.reduce((sum, c) => sum + caseEstimate(c).s, 0);
    const busy = st.exec && ACTIVE_STATES.has(st.exec.state) && st.exec.serial === st.serial;
    $("tex-start-summary").textContent = cases.length
      ? `${cases.length} case(s) selected · estimated ${fmtDuration(total)}`
      : "No cases selected";
    const btn = $("tex-start-btn");
    btn.disabled = !st.serial || !cases.length || busy;
    btn.title = !st.serial ? "Select a device" : busy ? "The device is busy with another execution" : "";

    const warnings = [];
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
    $("tex-warnings").innerHTML = warnings.length
      ? `<div class="callout warn tex-warn-list">${warnings.map((w) => `<div>${w}</div>`).join("")}</div>`
      : "";
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
            <input class="input" list="tex-var-names" placeholder="VARIABLE" data-ov-index="${i}" data-ov-field="name" value="${esc(o.name)}" />
            <input class="input" placeholder="value" data-ov-index="${i}" data-ov-field="value" value="${esc(o.value)}" />
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
      alert("The selected cases have no cycle, iteration or duration variables to shorten.");
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
  }

  async function startExecution() {
    const cases = selectedCases();
    if (!cases.length || !st.serial) return;
    const total = cases.reduce((sum, c) => sum + caseEstimate(c).s, 0);
    const changes = [...new Set(cases.flatMap((c) => c.device_changes || []))];
    const notes = [];
    if (changes.length) notes.push(`These cases change the device: ${changes.join(", ")}.`);
    if (total > LONG_RUN_S) notes.push(`Estimated run time is ${fmtDuration(total)}.`);
    if (notes.length && !confirm(`${notes.join("\n")}\n\nStart the execution?`)) return;

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
      alert(`Could not start the execution: ${err.message}`);
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
          text: `■ ${ev.case_id} → ${VERDICT_LABEL[ev.verdict] || ev.verdict} (${fmtDuration(ev.duration_s)})${ev.reason ? ` · ${ev.reason}` : ""}`
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

  async function onExecutionFinished() {
    stopElapsedTimer();
    try {
      st.exec = await getJSON(`/api/executions/${st.exec.id}`);
    } catch (err) {
      /* keep the streamed state */
    }
    renderLive();
    renderDeviceInfo();
    renderStartSummary();
    if (st.set && st.set.run_id === st.exec.run_id) loadSetDetail(false);
  }

  function renderLive() {
    const ex = st.exec;
    $("tex-live-empty").classList.toggle("hidden", !!ex);
    $("tex-live").classList.toggle("hidden", !ex);
    if (!ex) return;
    renderLiveHead();
    renderQueue();
    renderMetrics();
    renderManual();
    renderHealth();
    renderLog();
  }

  function renderLiveHead() {
    const ex = st.exec;
    if (!ex) return;
    const active = ACTIVE_STATES.has(ex.state);
    const done = ex.cases.filter((c) => c.status === "done").length;
    const device = ex.device || {};
    $("tex-live-title").textContent = `Execution ${ex.id}`;
    $("tex-live-meta").textContent = [
      `${ex.feature} · script set ${ex.run_id}`,
      `${[device.manufacturer, device.model].filter(Boolean).join(" ") || ex.serial} (${ex.serial})`,
      ex.started_at ? `started ${clock(ex.started_at)}` : "queued",
      `elapsed ${fmtDuration(elapsedSeconds())}`
    ].join(" · ");
    const stateCls = { running: "is-running", pausing: "is-running", paused: "is-manual", stopping: "is-failed",
      finished: "is-success", stopped: "is-muted", interrupted: "is-failed", queued: "is-ready" }[ex.state] || "";
    const pillEl = $("tex-live-state");
    pillEl.textContent = ex.state;
    pillEl.className = `status-pill ${stateCls}`;
    $("tex-progress-bar").style.width = `${ex.cases.length ? (100 * done) / ex.cases.length : 0}%`;
    const pause = $("tex-pause-btn");
    pause.textContent = ex.state === "paused" || ex.state === "pausing" ? "Resume" : "Pause";
    pause.disabled = !active || ex.state === "stopping";
    $("tex-skip-btn").disabled = !active || !ex.current_case || ex.state === "stopping";
    $("tex-stop-btn").disabled = !active || ex.state === "stopping";
    $("tex-view-results-btn").classList.toggle("hidden", active);
    $("tex-live-dot").classList.toggle("hidden", !active);

    const cur = currentCase();
    let text;
    if (cur) {
      const est = cur.estimate_s ? ` · estimate ≈ ${fmtDuration(cur.estimate_s)}` : "";
      text = `Running <b>${esc(cur.case_id)}</b> · ${esc(cur.name)} · ${fmtDuration(secondsSince(cur.started_at))}${est}`;
    } else if (ex.state === "paused") {
      text = "Paused. The next case starts when you resume.";
    } else if (ex.state === "pausing") {
      text = "Pausing after the current case…";
    } else if (!active) {
      const s = ex.summary || {};
      const counts = Object.entries(s.by_verdict || {}).map(([v, n]) => `${VERDICT_LABEL[v] || v}: ${n}`).join(" · ");
      text = `Run ${esc(ex.state)} · ${done}/${ex.cases.length} case(s) finished${counts ? ` · ${esc(counts)}` : ""}`;
    } else {
      text = "Starting…";
    }
    $("tex-live-current").innerHTML = `${text} <span class="muted">· ${done}/${ex.cases.length} done</span>`;
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
      if (st.exec && ACTIVE_STATES.has(st.exec.state)) renderLiveHead();
    }, 1000);
  }

  function stopElapsedTimer() {
    if (st.elapsedTimer) clearInterval(st.elapsedTimer);
    st.elapsedTimer = null;
  }

  function renderQueue() {
    const ex = st.exec;
    if (!ex) return;
    $("tex-queue").innerHTML = ex.cases.map((c) => {
      let status;
      if (c.status === "done") status = verdictPill(effectiveVerdict(c));
      else if (c.status === "running") status = pill("Running", "is-running");
      else if (c.status === "cancelled") status = pill("Not run", "is-muted");
      else status = pill("Queued", "");
      const time = c.status === "done" ? fmtDuration(c.duration_s)
        : c.status === "running" ? fmtDuration(secondsSince(c.started_at)) : c.estimate_s ? `≈ ${fmtDuration(c.estimate_s)}` : "";
      return `
        <button type="button" class="tex-queue-row ${c.status === "running" ? "is-running" : ""}" data-queue-case="${esc(c.case_id)}"
          ${c.status === "done" ? "" : "disabled"} title="${c.status === "done" ? "Open result" : ""}">
          <span class="tex-case-id">${esc(c.case_id)}</span>
          <span class="tex-case-name">${esc(c.name)}</span>
          <span class="tex-case-est">${esc(time)}</span>
          ${status}
        </button>`;
    }).join("");
  }

  function logVisible(entry) {
    const filter = $("tex-log-filter").value;
    if (filter === "current") return st.exec && entry.case_id === (st.exec.current_case || lastCaseId());
    if (filter === "important") return ["op", "op_fail", "metric", "error", "manual", "case", "case_bad"].includes(entry.level);
    return true;
  }

  function lastCaseId() {
    const done = (st.exec ? st.exec.cases : []).filter((c) => c.status !== "pending");
    return done.length ? done[done.length - 1].case_id : null;
  }

  function logLine(entry) {
    return `<span class="tex-log-line lvl-${esc(entry.level || "info")}"><span class="tex-log-meta">${esc(entry.time || "")} ${esc(entry.case_id || "")}</span> ${esc(entry.text)}</span>\n`;
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
    log.innerHTML = st.logs.filter(logVisible).map(logLine).join("");
    if ($("tex-autoscroll").checked) log.scrollTop = log.scrollHeight;
  }

  function renderMetrics() {
    const ex = st.exec;
    const caseId = (ex && (ex.current_case || lastCaseId())) || null;
    const list = st.metrics.filter((m) => m.case_id === caseId);
    $("tex-metrics").innerHTML = list.length
      ? `<div class="tex-muted-small">${esc(caseId)}</div>
         <table class="tex-table tex-table-compact"><tbody>${list.map((m) => `
          <tr><td>${m.passed == null ? "" : m.passed ? '<span class="tex-ok">✔</span>' : '<span class="tex-bad">✘</span>'}</td>
          <td>${esc(m.key)}</td><td><b>${esc(m.actual)}</b></td>
          <td class="muted">${m.operator ? `${esc(m.operator)} ${esc(m.target)}` : ""}</td></tr>`).join("")}</tbody></table>`
      : `<div class="muted tex-small">Metrics appear here as each case checks its SLAs.</div>`;
  }

  function renderManual() {
    $("tex-manual").innerHTML = st.manual.length
      ? st.manual.map((m) => `<div class="tex-manual-item"><span class="tex-case-id">${esc(m.case_id)}</span> ${esc(m.text)}</div>`).join("") +
        `<div class="muted tex-small">Decide these on the Results tab once the case finishes.</div>`
      : `<div class="muted tex-small">No tester checkpoints so far.</div>`;
  }

  function renderHealth() {
    $("tex-health").innerHTML = `<div class="tex-kv">${healthRows(st.health || {})}</div>`;
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
    if (action === "stop" && !confirm("Stop the execution? The current case is interrupted; its teardown still restores the device.")) return;
    try {
      const rec = await postJSON(`/api/executions/${st.exec.id}/control`, { action });
      st.exec.state = rec.state;
      renderLiveHead();
    } catch (err) {
      alert(err.message);
    }
  }

  // ── Results ─────────────────────────────────────────

  async function openResults(execId, caseId) {
    try {
      st.results = await getJSON(`/api/executions/${execId}`);
    } catch (err) {
      alert(`Could not load execution ${execId}: ${err.message}`);
      return;
    }
    st.causes = st.results.causes || {};
    st.causeFilter = null;
    st.detail = null;
    renderResults();
    showTab("results");
    const cases = st.results.cases;
    const first = caseId || (cases.find((c) => c.cause !== "passed" && c.cause !== "not_run") || cases[0] || {}).case_id;
    if (first) openCaseDetail(first);
  }

  function renderResults() {
    const r = st.results;
    $("tex-results-empty").classList.toggle("hidden", !!r);
    $("tex-results").classList.toggle("hidden", !r);
    if (!r) return;
    const s = r.summary || {};
    const device = r.device || {};
    const overrides = Object.entries(r.overrides || {}).map(([k, v]) => `${k}=${v}`).join(", ");
    const chips = Object.entries(s.by_verdict || {})
      .map(([v, n]) => `<span class="tex-count-chip ${VERDICT_CLASS[v] || ""}">${esc(VERDICT_LABEL[v] || v.replace("_", " "))} <b>${n}</b></span>`)
      .join("");
    const cats = Object.entries(s.by_category || {}).map(([cat, counts]) => {
      const total = Object.values(counts).reduce((a, b) => a + b, 0);
      return `<span class="tex-chip">${esc(cat)}: ${counts.PASS || 0}/${total} pass</span>`;
    }).join("");
    const active = ACTIVE_STATES.has(r.state);
    $("tex-results-head").innerHTML = `
      <div class="tex-live-title-row">
        <div>
          <div class="tex-live-title">Execution ${esc(r.id)} ${pill(r.state, r.state === "finished" ? "is-success" : active ? "is-running" : "is-muted")}</div>
          <div class="muted tex-live-meta">
            ${esc(r.feature)} · script set ${esc(r.run_id)}${r.product_name ? ` · spec: ${esc(r.product_name)}` : ""} ·
            ${esc([device.manufacturer, device.model].filter(Boolean).join(" ") || r.serial)} (${esc(r.serial)}, Android ${esc(device.android_version || "?")}) ·
            ${esc(fmtTime(r.started_at))} → ${esc(r.finished_at ? clock(r.finished_at) : "…")} · ${fmtDuration(s.duration_s)}
            ${overrides ? `<br>Overrides: ${esc(overrides)}` : ""}
          </div>
        </div>
        <div class="btn-row">
          <button type="button" class="secondary tsg-small-btn" data-res-action="rerun-failed">Rerun failed &amp; blocked</button>
          <button type="button" class="secondary tsg-small-btn" data-res-action="rerun-all">Rerun all</button>
          <button type="button" class="secondary tsg-small-btn" data-res-action="export-html">Export HTML</button>
          <button type="button" class="secondary tsg-small-btn" data-res-action="export-junit">JUnit XML</button>
          <button type="button" class="secondary tsg-small-btn" data-res-action="export-json">JSON</button>
        </div>
      </div>
      <div class="tex-chips tex-verdict-chips">${chips}
        <span class="tex-count-chip">Pass rate <b>${s.pass_rate != null ? `${s.pass_rate}%` : "–"}</b></span>
      </div>
      <div class="tex-chips">${cats}</div>`;

    const byCause = s.by_cause || {};
    $("tex-causes").innerHTML = CAUSE_ORDER.filter((k) => byCause[k]).map((k) => {
      const meta = st.causes[k] || { label: k, description: "", action: "" };
      return `
        <button type="button" class="tex-cause-card cause-${esc(k)} ${st.causeFilter === k ? "is-active" : ""}" data-cause="${esc(k)}">
          <div class="tex-cause-top"><span>${esc(meta.label)}</span><b>${byCause[k]}</b></div>
          <div class="tex-cause-desc">${esc(meta.description)}</div>
          ${meta.action ? `<div class="tex-cause-action">${esc(meta.action)}</div>` : ""}
        </button>`;
    }).join("");
    renderResultsTable();
  }

  function renderResultsTable() {
    const r = st.results;
    const rows = r.cases.filter((c) => !st.causeFilter || c.cause === st.causeFilter);
    $("tex-results-filter").textContent = st.causeFilter ? (st.causes[st.causeFilter] || {}).label || st.causeFilter : "All";
    $("tex-results-table").innerHTML = `
      <table class="tex-table">
        <thead><tr><th>Verdict</th><th>Case</th><th>Name</th><th>Cause</th><th>Reason</th><th>Time</th></tr></thead>
        <tbody>${rows.map((c) => `
          <tr class="tex-row ${st.detail && st.detail.case.case_id === c.case_id ? "is-selected" : ""}" data-case-id="${esc(c.case_id)}">
            <td>${verdictPill(effectiveVerdict(c))}${c.review ? ' <span class="tex-muted-small">reviewed</span>' : ""}</td>
            <td class="tex-case-id">${esc(c.case_id)}</td>
            <td class="tex-name-cell">${esc(c.name)}</td>
            <td>${esc((st.causes[c.cause] || {}).label || c.cause || "")}</td>
            <td class="tex-reason" title="${esc(c.reason)}">${esc(c.reason)}</td>
            <td>${fmtDuration(c.duration_s)}</td>
          </tr>`).join("")}</tbody>
      </table>`;
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

  function section(title, body, open) {
    return `<details class="tex-section" ${open ? "open" : ""}><summary>${title}</summary><div class="tex-section-body">${body}</div></details>`;
  }

  function renderCaseDetail() {
    const d = st.detail;
    const c = d.case;
    const r = d.result || {};
    const cause = st.causes[c.cause] || {};
    const spec = r.spec_values || c.spec_values || {};
    const parts = [];

    parts.push(`
      <div class="tex-detail-head">
        <div>
          <div class="tex-detail-title"><span class="tex-case-id">${esc(c.case_id)}</span> ${esc(c.name)}</div>
          <div class="tex-chips">${verdictPill(c.verdict)}
            ${c.review ? pill(`Reviewed: ${c.review.decision}`, VERDICT_CLASS[c.review.decision]) : ""}
            <span class="tex-chip">${esc(cause.label || c.cause || "")}</span>
            <span class="tex-chip">${fmtDuration(c.duration_s)}</span>
          </div>
        </div>
        <div class="btn-row">
          <button type="button" class="secondary tsg-small-btn" data-detail-action="script">View script</button>
          <button type="button" class="secondary tsg-small-btn" data-detail-action="rerun">Rerun this case</button>
        </div>
      </div>`);
    if (c.reason) parts.push(`<div class="tex-reason-box">${esc(c.reason)}</div>`);

    let explain = cause.action || "";
    if (d.blocked_hint) explain = d.blocked_hint;
    if (c.cause === "spec_mismatch" && Object.keys(spec).length) {
      explain += ` Spec values used: ${Object.entries(spec).map(([k, v]) => `${k}=${v}`).join(", ")}${r.spec_source ? ` (from ${r.spec_source})` : ""}.`;
    }
    if (explain) parts.push(`<div class="callout ${c.cause === "passed" ? "success" : "info"}">${esc(explain)}</div>`);

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

    if (c.verdict === "MANUAL_REVIEW") {
      const steps = (r.manual_steps || []).map((s) => `<li>${esc(s)}</li>`).join("");
      parts.push(`
        <div class="tex-review">
          <div class="tex-subhead">Manual review</div>
          ${steps ? `<ol class="tex-review-steps">${steps}</ol>` : ""}
          ${gallery ? `<div class="tex-small">Captured by this case (click to enlarge):</div>${gallery}` : ""}
          ${c.review ? `<div class="tex-small">Decided <b>${esc(c.review.decision)}</b> at ${esc(fmtTime(c.review.at))}${c.review.note ? ` · ${esc(c.review.note)}` : ""}</div>` : ""}
          <textarea class="input tex-review-note" id="tex-review-note" rows="2" placeholder="Note (optional)">${esc((c.review && c.review.note) || "")}</textarea>
          <div class="btn-row">
            <button type="button" class="soft-danger tsg-small-btn" data-review="FAIL">Mark Fail</button>
            <button type="button" class="soft-success tsg-small-btn" data-review="PASS">Mark Pass</button>
          </div>
        </div>`);
    }

    if (gallery && c.verdict !== "MANUAL_REVIEW") parts.push(section(`Captured media (${media.length})`, gallery, true));

    const checks = r.checks || [];
    if (checks.length) {
      const failed = checks.filter((k) => !k.passed).length;
      parts.push(section(`Checks (${failed} failed of ${checks.length})`, `
        <table class="tex-table tex-table-compact"><thead><tr><th></th><th>Check</th><th>Expected</th><th>Actual</th></tr></thead>
        <tbody>${checks.map((k) => `<tr class="${k.passed ? "" : "tex-row-bad"}">
          <td>${k.passed ? '<span class="tex-ok">✔</span>' : '<span class="tex-bad">✘</span>'}</td>
          <td>${esc(k.description)}${k.failure_classification ? `<div class="tex-muted-small">${esc(k.failure_classification)}</div>` : ""}</td>
          <td>${k.operator ? `${esc(k.operator)} ${esc(k.target)}` : ""}</td>
          <td><b>${esc(k.actual)}</b></td></tr>`).join("")}</tbody></table>`, true));
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
    parts.push(section(`Script log${d.log_truncated ? " (last part)" : ""}`, `<pre class="tex-log tex-log-static">${esc(d.log || "(empty)")}</pre>`));

    $("tex-case-detail").innerHTML = parts.join("");
  }

  async function submitReview(decision) {
    const d = st.detail;
    if (!d) return;
    try {
      await postJSON(`/api/executions/${d.execution_id}/cases/${d.case.case_id}/review`, {
        decision,
        note: ($("tex-review-note") || {}).value || ""
      });
      await openResults(d.execution_id, d.case.case_id);
    } catch (err) {
      alert(err.message);
    }
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
  }

  function rerun(kind) {
    const r = st.results;
    if (!r) return;
    const again = new Set(["failure", "spec_mismatch", "blocked", "script_error", "stopped", "not_run"]);
    const ids = kind === "all" ? r.cases.map((c) => c.case_id) : r.cases.filter((c) => again.has(c.cause)).map((c) => c.case_id);
    if (!ids.length) {
      alert("Nothing to rerun: no failed, blocked, errored or stopped cases.");
      return;
    }
    prefillSetup(r.run_id, ids, r.overrides, r.case_timeout_min);
  }

  async function exportReport(format) {
    const r = st.results;
    const ext = { html: "html", junit: "xml", json: "json" }[format];
    try {
      await download(`/api/executions/${r.id}/report?format=${format}`, `test_execution_${r.id}.${ext}`);
    } catch (err) {
      alert(err.message);
    }
  }

  // ── History ─────────────────────────────────────────

  async function loadHistory() {
    const scoped = $("tex-history-scope").value === "set" && st.runId;
    try {
      st.history = (await getJSON(`/api/executions${scoped ? `?run_id=${st.runId}` : ""}`)).executions || [];
    } catch (err) {
      $("tex-history").innerHTML = `<div class="callout warn">${esc(err.message)}</div>`;
      return;
    }
    const ids = new Set(st.history.map((h) => h.id));
    st.compareSel = new Set([...st.compareSel].filter((id) => ids.has(id)));
    renderHistory();
  }

  function renderHistory() {
    $("tex-compare-btn").disabled = st.compareSel.size !== 2;
    if (!st.history.length) {
      $("tex-history").innerHTML = `<div class="muted tex-small">No executions yet.</div>`;
      return;
    }
    $("tex-history").innerHTML = `
      <table class="tex-table">
        <thead><tr><th title="Pick two to compare">Compare</th><th>Started</th><th>Script set</th><th>Device</th><th>Cases</th><th>Verdicts</th><th>Pass rate</th><th>State</th></tr></thead>
        <tbody>${st.history.map((h) => {
          const s = h.summary || {};
          const device = h.device || {};
          const chips = Object.entries(s.by_verdict || {})
            .map(([v, n]) => `<span class="tex-count-chip ${VERDICT_CLASS[v] || ""}">${esc(VERDICT_LABEL[v] || v)} <b>${n}</b></span>`).join("");
          return `<tr class="tex-row" data-exec-id="${esc(h.id)}">
            <td><input type="checkbox" class="tex-cmp-check" data-exec-id="${esc(h.id)}" ${st.compareSel.has(h.id) ? "checked" : ""} /></td>
            <td>${esc(fmtTime(h.started_at || h.created_at))}</td>
            <td><span class="tex-mono">${esc(h.run_id)}</span><div class="tex-muted-small">${esc(h.feature)}${h.product_name ? ` · ${esc(h.product_name)}` : ""}</div></td>
            <td>${esc([device.manufacturer, device.model].filter(Boolean).join(" ") || h.serial)}<div class="tex-muted-small">${esc(h.serial)}</div></td>
            <td>${s.total ?? "–"}</td>
            <td><div class="tex-chips">${chips}</div></td>
            <td>${s.pass_rate != null ? `${s.pass_rate}%` : "–"}</td>
            <td>${pill(h.state, h.state === "finished" ? "is-success" : ACTIVE_STATES.has(h.state) ? "is-running" : "is-muted")}</td>
          </tr>`;
        }).join("")}</tbody>
      </table>`;
  }

  async function compareSelected() {
    const [a, b] = [...st.compareSel].sort();
    try {
      const data = await getJSON(`/api/executions/compare?a=${a}&b=${b}`);
      const label = (x) => `${x.id} · ${[x.device && x.device.model, x.serial].filter(Boolean).join(" · ")}`;
      $("tex-compare-card").classList.remove("hidden");
      $("tex-compare").innerHTML = `
        <div class="tex-small"><b>A</b> ${esc(label(data.a))} &nbsp; <b>B</b> ${esc(label(data.b))} · ${data.changed} case(s) changed verdict</div>
        <table class="tex-table">
          <thead><tr><th>Case</th><th>Name</th><th>A</th><th>B</th><th>A time</th><th>B time</th></tr></thead>
          <tbody>${data.rows.map((row) => `<tr class="${row.changed ? "tex-row-changed" : ""}">
            <td class="tex-case-id">${esc(row.case_id)}</td><td>${esc(row.name)}</td>
            <td>${row.a ? verdictPill(row.a) : '<span class="muted">–</span>'}</td>
            <td>${row.b ? verdictPill(row.b) : '<span class="muted">–</span>'}</td>
            <td>${fmtDuration(row.a_duration_s)}</td><td>${fmtDuration(row.b_duration_s)}</td></tr>`).join("")}</tbody>
        </table>`;
    } catch (err) {
      alert(err.message);
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

    document.querySelectorAll(".tex-tab").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.texTab)));

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

    $("tex-pause-btn").addEventListener("click", () =>
      control(st.exec && (st.exec.state === "paused" || st.exec.state === "pausing") ? "resume" : "pause"));
    $("tex-skip-btn").addEventListener("click", () => control("skip"));
    $("tex-stop-btn").addEventListener("click", () => control("stop"));
    $("tex-view-results-btn").addEventListener("click", () => st.exec && openResults(st.exec.id));
    $("tex-log-filter").addEventListener("change", renderLog);
    $("tex-screen-toggle").addEventListener("change", syncScreenPolling);
    $("tex-queue").addEventListener("click", (e) => {
      const row = e.target.closest("[data-queue-case]");
      if (row && !row.disabled && st.exec) openResults(st.exec.id, row.dataset.queueCase);
    });

    $("tex-results-head").addEventListener("click", (e) => {
      const action = e.target.dataset.resAction;
      if (action === "rerun-failed") rerun("failed");
      else if (action === "rerun-all") rerun("all");
      else if (action && action.startsWith("export-")) exportReport(action.slice(7));
    });
    $("tex-causes").addEventListener("click", (e) => {
      const card = e.target.closest("[data-cause]");
      if (!card) return;
      st.causeFilter = st.causeFilter === card.dataset.cause ? null : card.dataset.cause;
      renderResults();
    });
    $("tex-results-table").addEventListener("click", (e) => {
      const row = e.target.closest("[data-case-id]");
      if (row) openCaseDetail(row.dataset.caseId);
    });
    $("tex-case-detail").addEventListener("click", (e) => {
      const t = e.target.closest("[data-review],[data-file-view],[data-file-download],[data-detail-action]");
      if (!t) return;
      if (t.dataset.review) submitReview(t.dataset.review);
      else if (t.dataset.fileView) openFile(t.dataset.fileView);
      else if (t.dataset.fileDownload) {
        const d = st.detail;
        download(`/api/executions/${d.execution_id}/cases/${d.case.case_id}/files/${encodeURIComponent(t.dataset.fileDownload)}?download=true`,
          t.dataset.fileDownload).catch((err) => alert(err.message));
      } else if (t.dataset.detailAction === "script") openScript();
      else if (t.dataset.detailAction === "rerun") {
        const d = st.detail;
        prefillSetup(d.run_id, [d.case.case_id], d.overrides, st.results && st.results.case_timeout_min);
      }
    });
    document.querySelectorAll('[data-close-modal="tex-file-modal"]').forEach((el) =>
      el.addEventListener("click", () => $("tex-file-video").pause()));
    $("tex-file-download").addEventListener("click", () => {
      if (st.fileDownload) download(st.fileDownload.path, st.fileDownload.name).catch((err) => alert(err.message));
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
      const row = e.target.closest("tr[data-exec-id]");
      if (row) openResults(row.dataset.execId);
    });
    $("tex-compare-btn").addEventListener("click", compareSelected);
  }

  bind();
})();
