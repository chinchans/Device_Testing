(() => {
  "use strict";

  const P = window.pipeline;
  const { esc, dot, pill } = P;
  const $ = (id) => document.getElementById(id);
  const EXPIRY_WARN_DAYS = 60;
  const CERT_EXTENSIONS = ["pdf", "docx", "png", "jpg", "jpeg", "tif", "tiff", "bmp", "txt"];

  const st = {
    /** Definitions come from the backend once loaded; the static flow list is the offline fallback. */
    defs: P.FLOW.certificates.map((d) => ({ ...d })),
    selected: P.FLOW.certificates[0].id,
    /** Uploaded files: { path, name, size, supported, cert_id, detected_by, error } */
    files: [],
    device: { manufacturer: "", model: "" },
    /** certId → backend result ({ status, file, fields, checks, other_files }) from the last validation. */
    results: null,
    validatedAt: "",
    stale: false,
    busy: "",
    error: "",
    gateWarning: false,
    verdicts: {}
  };

  function apiBase() {
    return (window.platformConfig && window.platformConfig.apiBaseUrl) || "http://127.0.0.1:8000";
  }

  async function api(path, options = {}) {
    const resp = await fetch(`${apiBase()}${path}`, {
      ...options,
      headers: options.body ? { "Content-Type": "application/json" } : undefined
    });
    if (!resp.ok) {
      let detail = "";
      try {
        detail = (await resp.json()).detail;
      } catch {
        detail = "";
      }
      throw new Error(detail || `HTTP ${resp.status}`);
    }
    return resp.json();
  }

  function today() {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d;
  }

  function parseDate(v) {
    if (!v) return null;
    const d = new Date(`${v}T00:00:00`);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  function deviceProfile() {
    const s = (window.workbench && window.workbench.getState && window.workbench.getState()) || {};
    return s.deviceClassification || {};
  }

  function defOf(id) {
    return st.defs.find((d) => d.id === id);
  }

  function resultOf(id) {
    return (st.results && st.results[id]) || null;
  }

  /** Page state: done | failed | missing (validated, no file) | todo (not validated yet). */
  function stateOf(id) {
    const r = resultOf(id);
    if (!r) return "todo";
    return { passed: "done", failed: "failed", not_available: "missing" }[r.status] || "todo";
  }

  /** Pipeline verdict (home, reports): only done / failed / todo exist there. */
  function verdictOf(id) {
    const s = stateOf(id);
    return s === "missing" ? "todo" : s;
  }

  function stateLabel(s) {
    return { todo: "Not validated", done: "Pass", failed: "Fail", missing: "Not available" }[s];
  }

  // ── pipeline integration ────────────────────────────

  P.certApi.summary = () =>
    st.defs.map((def) => {
      const r = resultOf(def.id);
      const f = (r && r.fields) || {};
      return {
        id: def.id,
        name: def.name,
        verdict: verdictOf(def.id),
        file: r && r.file ? r.file.name : "",
        issuer: f.issuer || "",
        certId: f.certificate_id || "",
        expires: f.expiry_date || "",
        failedRules: ((r && r.checks) || []).filter((c) => c.ok === false).map((c) => c.label)
      };
    });

  P.certApi.attention = () => {
    const items = [];
    st.defs.forEach((def) => {
      const r = resultOf(def.id);
      const exp = parseDate(r && r.fields && r.fields.expiry_date);
      if (!exp) return;
      const days = Math.round((exp - today()) / 86400000);
      if (days < 0) items.push({ tone: "fail", text: `${def.name} expired ${-days} day${days === -1 ? "" : "s"} ago.`, route: "certifications" });
      else if (days <= EXPIRY_WARN_DAYS) items.push({ tone: "warn", text: `${def.name} expires in ${days} day${days === 1 ? "" : "s"}.`, route: "certifications" });
    });
    return items;
  };

  function recordTransitions() {
    st.defs.forEach((def) => {
      const v = verdictOf(def.id);
      const prev = st.verdicts[def.id] || "todo";
      if (v !== prev && (v === "done" || v === "failed")) {
        P.log(`${def.name}: ${v === "done" ? "passed validation" : "failed validation"}.`, v === "done" ? "pass" : "fail");
      }
      st.verdicts[def.id] = v;
    });
    const all = st.defs.every((d) => st.verdicts[d.id] === "done");
    if (all && !st.allPassedLogged) {
      st.allPassedLogged = true;
      P.log("Regulatory Certifications approved: all certificates passed.", "pass");
    } else if (!all) {
      st.allPassedLogged = false;
    }
  }

  // ── Loading and saving ──────────────────────────────

  function applyRecord(record) {
    if (!record) return;
    st.results = record.results || null;
    st.validatedAt = record.validated_at || "";
    st.files = record.files || [];
    if (record.device && (record.device.manufacturer || record.device.model)) {
      st.device = { manufacturer: record.device.manufacturer || "", model: record.device.model || "" };
    }
    st.stale = false;
  }

  function prefillDevice() {
    const dc = deviceProfile();
    if (!st.device.manufacturer && dc.manufacturer) st.device.manufacturer = dc.manufacturer;
    if (!st.device.model && dc.model) st.device.model = dc.model;
  }

  async function loadInitial() {
    // Start each app session clean: load certificate definitions only, discard last session's results.
    st.results = null;
    st.validatedAt = "";
    st.files = [];
    st.stale = false;
    st.verdicts = {};
    st.allPassedLogged = false;
    try {
      const defs = await api("/api/certifications");
      if (defs.certificates && defs.certificates.length) st.defs = defs.certificates;
      await api("/api/certifications/results", { method: "DELETE" });
      st.error = "";
    } catch (err) {
      st.error = `Could not reach the backend (${err.message}). Start it on ${apiBase()} to upload and validate certificates.`;
    }
    if (!defOf(st.selected)) st.selected = st.defs[0].id;
    P.refresh();
  }

  // ── Actions ─────────────────────────────────────────

  function markStale() {
    if (st.results) st.stale = true;
  }

  function mergeFiles(scanned) {
    const byPath = new Map(st.files.map((f) => [f.path, f]));
    scanned.forEach((f) => byPath.set(f.path, f));
    st.files = [...byPath.values()];
    markStale();
  }

  async function runBusy(label, fn) {
    st.busy = label;
    st.error = "";
    render();
    try {
      await fn();
    } catch (err) {
      st.error = err.message || String(err);
    } finally {
      st.busy = "";
      P.refresh();
    }
  }

  async function pickFiles() {
    const dlg = window.deviceTestingAPI;
    if (!dlg || !dlg.openFilesDialog) return;
    const picked = await dlg.openFilesDialog({
      title: "Select certificate documents",
      filters: [
        { name: "Certificates", extensions: CERT_EXTENSIONS },
        { name: "All Files", extensions: ["*"] }
      ]
    });
    if (!picked || !picked.length) return;
    await runBusy("Reading files…", async () => {
      const res = await api("/api/certifications/scan", {
        method: "POST",
        body: JSON.stringify({ file_paths: picked.map((f) => f.path) })
      });
      mergeFiles(res.files);
      P.log(`Certificates: ${res.files.length} file${res.files.length === 1 ? "" : "s"} added.`, "info");
    });
  }

  async function pickFolder() {
    const dlg = window.deviceTestingAPI;
    if (!dlg || !dlg.openFolderDialog) return;
    const folder = await dlg.openFolderDialog({ title: "Select the folder with certificate documents" });
    if (!folder) return;
    await runBusy("Reading folder…", async () => {
      const res = await api("/api/certifications/scan", {
        method: "POST",
        body: JSON.stringify({ folder_paths: [folder.path] })
      });
      mergeFiles(res.files);
      P.log(`Certificates: ${res.files.length} file${res.files.length === 1 ? "" : "s"} added from ${folder.name}.`, "info");
    });
  }

  async function validateAll() {
    await runBusy("Validating certificates…", async () => {
      const record = await api("/api/certifications/validate", {
        method: "POST",
        body: JSON.stringify({ files: st.files, device: st.device })
      });
      applyRecord(record);
      st.gateWarning = false;
      const s = record.summary || {};
      P.log(
        `Certificates validated: ${s.passed || 0} passed, ${s.failed || 0} failed, ${s.not_available || 0} not available.`,
        s.failed ? "fail" : "info"
      );
      recordTransitions();
    });
  }

  async function clearAll() {
    st.files = [];
    st.results = null;
    st.validatedAt = "";
    st.stale = false;
    st.gateWarning = false;
    recordTransitions();
    try {
      await api("/api/certifications/results", { method: "DELETE" });
    } catch (err) {
      st.error = err.message || String(err);
    }
    P.refresh();
  }

  function goNext() {
    const notPassed = st.defs.filter((d) => stateOf(d.id) !== "done");
    if (notPassed.length) {
      st.gateWarning = true;
      render();
      return;
    }
    P.navigate("stage:pat");
  }

  // ── Rendering ───────────────────────────────────────

  function listHtml() {
    return st.defs
      .map((def) => {
        const s = stateOf(def.id);
        return `<button type="button" class="ct-row ${def.id === st.selected ? "is-selected" : ""}" data-cert="${esc(def.id)}">
        ${dot(s === "missing" ? "todo" : s)}
        <span class="ct-row-text">
          <span class="ct-row-name">${esc(def.name)}</span>
          <span class="ct-row-desc">${esc(def.desc)}</span>
        </span>
        <span class="ct-row-state is-${s}">${stateLabel(s)}</span>
      </button>`;
      })
      .join("");
  }

  function certOptions(selectedId) {
    const opts = st.defs
      .map((d) => `<option value="${esc(d.id)}" ${d.id === selectedId ? "selected" : ""}>${esc(d.name)}</option>`)
      .join("");
    return `<option value="" ${selectedId ? "" : "selected"}>Not a certificate (ignore)</option>${opts}`;
  }

  function detectedLabel(f) {
    if (f.error) return `<span class="ct-file-note is-error">${esc(f.error)}</span>`;
    const by = { filename: "from file name", content: "from document content", manual: "set manually" }[f.detected_by];
    return f.cert_id && by
      ? `<span class="ct-file-note">${esc(by)}</span>`
      : '<span class="ct-file-note is-warn">Not recognised. Choose the certificate</span>';
  }

  function filesHtml() {
    if (!st.files.length) return "";
    const matched = st.files.filter((f) => f.cert_id).length;
    const rows = st.files
      .map(
        (f, i) => `<tr>
        <td class="ct-file-cell" title="${esc(f.path)}">
          <span class="ct-file-icon">${esc((f.name.split(".").pop() || "DOC").toUpperCase().slice(0, 4))}</span>
          <span class="ct-file-name">${esc(f.name)}</span>
        </td>
        <td>
          <select class="select ct-assign" data-ct-assign="${i}" aria-label="Certificate for ${esc(f.name)}">${certOptions(f.cert_id)}</select>
          ${detectedLabel(f)}
        </td>
        <td class="ct-file-actions"><button type="button" class="secondary tsg-small-btn" data-ct-action="remove-file" data-index="${i}" title="Remove">Remove</button></td>
      </tr>`
      )
      .join("");
    return `<table class="ct-files">
        <thead><tr><th>File</th><th>Certificate</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="ct-files-foot">
        <span class="fl-muted-small">${st.files.length} file${st.files.length === 1 ? "" : "s"} · ${matched} matched to a certificate</span>
        <button type="button" class="secondary tsg-small-btn" data-ct-action="clear-files" ${st.busy ? "disabled" : ""}>Clear all</button>
      </div>`;
  }

  function intakeHtml() {
    const busy = Boolean(st.busy);
    const validatedText = st.validatedAt
      ? `Last validated ${esc(st.validatedAt.replace("T", " "))}`
      : "Not validated yet";
    return `<section class="panel ct-intake">
      <div class="panel-head-row"><h3>Certificate documents</h3><span class="fl-muted-small">${st.files.length} uploaded</span></div>
      <div class="upload-zone compact ct-bulk ${st.files.length ? "has-file" : ""}">
        <div class="upload-icon">CERT</div>
        <h4>Upload all certificate documents at once</h4>
        <p>Select several files, or a whole folder. PDF, DOCX, images or text. Each file is matched to its certificate automatically.</p>
        <div class="btn-row ct-bulk-btns">
          <button type="button" class="secondary" data-ct-action="pick-files" ${busy ? "disabled" : ""}>Select files</button>
          <button type="button" class="secondary" data-ct-action="pick-folder" ${busy ? "disabled" : ""}>Select folder</button>
        </div>
      </div>
      ${filesHtml()}
      <div class="ct-validate-row">
        <button type="button" class="primary" data-ct-action="validate" ${busy || !st.files.length ? "disabled" : ""}>Validate certificates</button>
        ${busy ? `<span class="running-indicator"><span class="running-spinner" aria-hidden="true"></span><span>${esc(st.busy)}</span></span>` : `<span class="fl-muted-small">${validatedText}</span>`}
      </div>
      ${st.error ? `<div class="callout warn ct-callout">${esc(st.error)}</div>` : ""}
      ${st.stale ? '<div class="callout info ct-callout">Files changed since the last validation. Click Validate certificates to refresh the results.</div>' : ""}
    </section>`;
  }

  function fieldsHtml(def, fields) {
    const rows = [
      ["Issuer", fields.issuer],
      [def.id_label || "Certificate ID", fields.certificate_id],
      ["Manufacturer", fields.manufacturer],
      ["Model", fields.model],
      ["Issue date", fields.issue_date],
      ["Expiry date", fields.expiry_date],
      ["Scheme", fields.scheme],
      ["Evidence status", fields.evidence_status],
      ["Document status", fields.document_status],
      ["Test results", fields.tests],
      ["Public reference", fields.public_reference]
    ].filter(([, value]) => value);
    return `<dl class="ct-fields">${rows
      .map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${v ? esc(v) : '<span class="muted">Not found</span>'}</dd></div>`)
      .join("")}</dl>`;
  }

  function checksHtml(checks) {
    return `<ul class="ct-checks">${checks
      .map((c) => {
        const s = c.ok === true ? "done" : c.ok === false ? "failed" : "none";
        const note = c.ok === null ? "Not checked: value not found in the document" : c.detail;
        return `<li class="is-${s}">${dot(s)}<span class="ct-check-label">${esc(c.label)}</span>${note ? `<span class="ct-check-detail">${esc(note)}</span>` : ""}</li>`;
      })
      .join("")}</ul>`;
  }

  function detailHtml(def) {
    const s = stateOf(def.id);
    const r = resultOf(def.id);
    const head = `<div class="ct-detail-head">
        <div>
          <h3 class="ct-detail-title">${esc(def.name)}</h3>
          <p class="fl-desc">${esc(def.desc)}</p>
        </div>
        ${pill(s === "missing" ? "todo" : s, stateLabel(s))}
      </div>`;

    if (s === "todo") {
      const queued = st.files.filter((f) => f.cert_id === def.id);
      const text = queued.length
        ? `${queued.map((f) => f.name).join(", ")} will be checked when you click Validate certificates.`
        : "No uploaded file is matched to this certificate yet. Upload the documents above, then click Validate certificates.";
      return `${head}<div class="ct-verdict is-todo">${dot("todo")}<span>${esc(text)}</span></div>`;
    }
    if (s === "missing") {
      return `${head}<div class="ct-verdict is-missing">${dot("todo")}<span>Not available: none of the uploaded files is a ${esc(def.name)} document.</span></div>`;
    }

    const failed = (r.checks || []).filter((c) => c.ok === false);
    const verdictText =
      s === "done"
        ? "Pass: the certificate passed all available checks."
        : `Fail: ${failed.map((c) => c.label).join("; ")}.`;
    const others = (r.other_files || []).map((f) => f.name);
    return `${head}
      <div class="ct-file">
        <span class="ct-file-icon">${esc((r.file.name.split(".").pop() || "DOC").toUpperCase().slice(0, 4))}</span>
        <span class="ct-file-name" title="${esc(r.file.path)}">${esc(r.file.name)}</span>
        ${r.text_method === "ocr" ? '<span class="fl-muted-small">read with OCR</span>' : ""}
      </div>
      ${others.length ? `<p class="ct-device-hint">Also uploaded for this certificate: ${esc(others.join(", "))}. The best-scoring file is shown.</p>` : ""}
      <div class="ct-verdict is-${s}">${dot(s)}<span>${esc(verdictText)}</span></div>
      <h4 class="ct-sub-title">Extracted details</h4>
      ${fieldsHtml(def, r.fields || {})}
      <h4 class="ct-sub-title">Checks</h4>
      ${checksHtml(r.checks || [])}`;
  }

  function counts() {
    const v = st.defs.map((d) => stateOf(d.id));
    return {
      pass: v.filter((x) => x === "done").length,
      fail: v.filter((x) => x === "failed").length,
      missing: v.filter((x) => x === "missing" || x === "todo").length
    };
  }

  function footerHtml() {
    const c = counts();
    return `<span class="fl-tally"><i class="hm-tone is-pass"></i>${c.pass} passed</span>
      <span class="fl-tally"><i class="hm-tone is-fail"></i>${c.fail} failed</span>
      <span class="fl-tally"><i class="hm-tone is-todo"></i>${c.missing} not available</span>`;
  }

  function gateWarningHtml() {
    if (!st.gateWarning) return "";
    const notPassed = st.defs.filter((d) => stateOf(d.id) !== "done");
    if (!notPassed.length) return "";
    const items = notPassed.map((d) => `<li><b>${esc(d.name)}</b>: ${esc(stateLabel(stateOf(d.id)))}</li>`).join("");
    return `<div class="callout warn ct-gate">
      <p><b>${notPassed.length} of ${st.defs.length} certificates have not passed.</b> You can still continue to Operator Testing, but the device is not certification-ready.</p>
      <ul>${items}</ul>
      <div class="btn-row">
        <button type="button" class="primary" data-ct-action="continue">Continue anyway →</button>
        <button type="button" class="secondary" data-ct-action="stay">Stay and fix</button>
      </div>
    </div>`;
  }

  function overallStatus() {
    const c = counts();
    return c.fail ? "failed" : c.pass === st.defs.length ? "done" : c.pass ? "progress" : "todo";
  }

  function render() {
    const root = $("cert-root");
    if (!root) return;
    prefillDevice();
    const def = defOf(st.selected) || st.defs[0];
    const c = counts();
    root.innerHTML = `
      ${P.headPanel({
        title: "Regulatory Certifications",
        desc: "Upload all certificate documents at once and validate them together. Each certificate is checked for type, issuer, ID format, device match and validity dates. Certificates without a document are reported as not available.",
        status: overallStatus(),
        side: P.progressSide(`${c.pass} of ${st.defs.length} certificates passed`, c.pass, st.defs.length)
      })}
      <div class="ct-grid">
        <section class="panel ct-list">
          <div class="panel-head-row"><h3>Certificates</h3><span class="fl-muted-small">${st.defs.length}</span></div>
          <div class="ct-rows" id="ct-rows">${listHtml()}</div>
        </section>
        <div class="ct-right">
          ${intakeHtml()}
          <section class="panel ct-detail" id="ct-detail">${detailHtml(def)}</section>
        </div>
      </div>
      ${gateWarningHtml()}
      <div class="panel fl-footer">
        <div class="fl-tallies">${footerHtml()}</div>
        <button type="button" class="primary" data-ct-action="next">Next: PAT →</button>
      </div>`;
  }

  P.renderers.certifications = render;

  document.addEventListener("click", (e) => {
    const root = $("view-certifications");
    if (!root || !root.contains(e.target)) return;
    const row = e.target.closest("[data-cert]");
    if (row) {
      st.selected = row.dataset.cert;
      render();
      return;
    }
    const action = e.target.closest("[data-ct-action]");
    if (!action || action.disabled) return;
    e.stopPropagation();
    const kind = action.dataset.ctAction;
    if (kind === "pick-files") pickFiles();
    else if (kind === "pick-folder") pickFolder();
    else if (kind === "validate") validateAll();
    else if (kind === "clear-files") clearAll();
    else if (kind === "next") goNext();
    else if (kind === "continue") {
      st.gateWarning = false;
      P.navigate("stage:pat");
    } else if (kind === "stay") {
      st.gateWarning = false;
      render();
    } else if (kind === "remove-file") {
      st.files.splice(Number(action.dataset.index), 1);
      markStale();
      render();
    }
  });

  document.addEventListener("change", (e) => {
    const sel = e.target.closest && e.target.closest("[data-ct-assign]");
    if (sel) {
      const f = st.files[Number(sel.dataset.ctAssign)];
      if (!f) return;
      f.cert_id = sel.value || null;
      f.detected_by = sel.value ? "manual" : "none";
      markStale();
      render();
    }
  });

  loadInitial();
})();
