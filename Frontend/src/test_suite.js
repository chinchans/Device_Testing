(() => {
  "use strict";

  const P = window.pipeline;
  const { esc, pill } = P;
  const $ = (id) => document.getElementById(id);
  const SUITE_STAGES = ["pat"];
  const SUITE_EXTENSIONS = ["xlsx", "xlsm"];

  /** stageId → { record, extraction, busy, error }; record is the upload summary, extraction the last extract report. */
  const st = {};

  function stateOf(stageId) {
    if (!st[stageId]) st[stageId] = { record: null, extraction: null, busy: "", error: "" };
    return st[stageId];
  }

  function stageName(stageId) {
    const stage = P.STAGES.find((s) => s.id === stageId);
    return stage ? stage.name : stageId;
  }

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

  // ── Actions ─────────────────────────────────────────

  async function runBusy(stageId, label, fn) {
    const s = stateOf(stageId);
    s.busy = label;
    s.error = "";
    P.refresh();
    try {
      await fn(s);
    } catch (err) {
      s.error = err.message || String(err);
    } finally {
      s.busy = "";
      P.refresh();
    }
  }

  async function pick(stageId) {
    const dlg = window.deviceTestingAPI;
    if (!dlg || !dlg.openFileDialog) {
      stateOf(stageId).error = "File selection is only available in the desktop app.";
      P.refresh();
      return;
    }
    const file = await dlg.openFileDialog({
      title: `Select the ${stageName(stageId)} test suite`,
      filters: [
        { name: "Excel workbook", extensions: SUITE_EXTENSIONS },
        { name: "All Files", extensions: ["*"] }
      ]
    });
    if (!file) return;
    await runBusy(stageId, "Reading workbook…", async (s) => {
      const record = await api(`/api/test-suites/${encodeURIComponent(stageId)}/upload`, {
        method: "POST",
        body: JSON.stringify({ file_path: file.path })
      });
      s.record = record;
      s.extraction = null;
      const n = record.summary.sheets;
      P.log(`${stageName(stageId)} test suite uploaded: ${record.file_name} (${n} sheet${n === 1 ? "" : "s"}).`, "info");
    });
  }

  async function remove(stageId) {
    await runBusy(stageId, "Removing…", async (s) => {
      await api(`/api/test-suites/${encodeURIComponent(stageId)}`, { method: "DELETE" });
      s.record = null;
      s.extraction = null;
      P.log(`${stageName(stageId)} test suite removed.`, "info");
    });
  }

  async function extract(stageId) {
    stateOf(stageId).extraction = null;
    await runBusy(stageId, "Extracting test cases…", async (s) => {
      s.extraction = await api(`/api/test-suites/${encodeURIComponent(stageId)}/extract`, { method: "POST" });
      const r = s.extraction.report;
      P.log(`${stageName(stageId)} test suite extracted: ${r.unique_test_cases} test cases.`, "info");
    });
  }

  async function download(stageId) {
    await runBusy(stageId, "Preparing JSON…", async () => {
      const data = await api(`/api/test-suites/${encodeURIComponent(stageId)}/extracted`);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${data.source.file_name.replace(/\.[^.]+$/, "")}_test_cases.json`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    });
  }

  // ── Rendering ───────────────────────────────────────

  function fmtSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function sheetStatus(info) {
    if (!info) return '<span class="fl-muted-small">Not extracted</span>';
    if (info.status === "extracted") {
      return `${pill("done", "Extracted")}<span class="ct-file-note">Header row ${info.header_row} · ${info.test_rows} test rows</span>`;
    }
    return `${pill("todo", "Skipped")}<span class="ct-file-note">${esc(info.reason)}</span>`;
  }

  function sheetsHtml(record, extraction) {
    const infoByName = new Map(((extraction && extraction.sheets) || []).map((sh) => [sh.name, sh]));
    const rows = record.sheets
      .map(
        (sh) => `<tr class="${sh.visible ? "" : "ts-sheet-hidden"}">
        <td class="ct-file-cell"><span class="ct-file-name">${esc(sh.name)}</span></td>
        <td>${sh.rows}</td>
        <td>${sh.columns}</td>
        <td>${sh.visible ? "Visible" : "Hidden"}</td>
        <td>${sheetStatus(infoByName.get(sh.name))}</td>
      </tr>`
      )
      .join("");
    const sum = record.summary;
    return `<table class="ct-files">
        <thead><tr><th>Sheet</th><th>Rows with data</th><th>Columns</th><th>Visibility</th><th>Extraction</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="ct-files-foot">
        <span class="fl-muted-small">${sum.sheets} sheet${sum.sheets === 1 ? "" : "s"}${sum.hidden_sheets ? ` · ${sum.hidden_sheets} hidden` : ""} · ${sum.rows} rows on visible sheets</span>
      </div>`;
  }

  function extractionHtml(stageId, x, busy) {
    const r = x.report;
    const kpis = [
      ["Unique test cases", r.unique_test_cases],
      ["Test rows read", r.rows_read],
      ["Duplicate IDs merged", r.duplicate_ids]
    ]
      .map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`)
      .join("");
    const notes = [];
    if (r.duplicate_ids) {
      notes.push(
        `${r.duplicate_ids} test IDs appear on more than one row (${r.identical_duplicates} identical, ${r.conflicting_duplicates} with different values). Each is one test case; differing values are listed under <code>conflicts</code>.`
      );
    }
    if (r.totals_rows) notes.push(`${r.totals_rows} totals row${r.totals_rows === 1 ? "" : "s"} used for the count checks, not extracted.`);
    if (r.skipped_rows.length) {
      notes.push(
        `${r.skipped_rows.length} row${r.skipped_rows.length === 1 ? "" : "s"} without a test ID skipped: ${esc(
          r.skipped_rows.slice(0, 5).map((s) => `${s.sheet}!${s.row}`).join(", ")
        )}${r.skipped_rows.length > 5 ? "…" : ""}`
      );
    }
    if (r.test_cases_with_warnings) {
      notes.push(`${r.test_cases_with_warnings} test case${r.test_cases_with_warnings === 1 ? " has" : "s have"} data warnings (empty or unexpected values).`);
    }
    return `<h4 class="ct-sub-title">Extraction</h4>
      <dl class="ct-fields">${kpis}</dl>
      ${notes.length ? `<ul class="ts-list ts-notes">${notes.map((n) => `<li>${n}</li>`).join("")}</ul>` : ""}
      <div class="ct-files-foot">
        <span class="fl-muted-small" title="${esc(x.output_path)}">Saved ${esc(x.extracted_at.replace("T", " "))} · ${esc(x.output_path)}</span>
        <button type="button" class="secondary tsg-small-btn" data-ts-action="download" data-ts-stage="${esc(stageId)}" ${busy ? "disabled" : ""}>Download JSON</button>
      </div>`;
  }

  function sectionHtml(stage) {
    const s = stateOf(stage.id);
    const r = s.record;
    const busy = Boolean(s.busy);
    const status = r ? pill("done", "Uploaded") : pill("todo", "Not uploaded");
    const blurb = r
      ? `${fmtSize(r.size)} · uploaded ${esc(r.uploaded_at.replace("T", " "))}`
      : "Excel workbook (.xlsx) with the test cases, one or more sheets. Each sheet is read as-is.";
    return `<section class="panel fl-section ts-intake">
      <div class="panel-head-row"><h3>${esc(stage.name)} test suite</h3>${status}</div>
      <div class="upload-zone compact ct-bulk ${r ? "has-file" : ""}">
        <div class="upload-icon">XLSX</div>
        <h4 title="${r ? esc(r.source_path) : ""}">${r ? esc(r.file_name) : `Upload the ${esc(stage.name)} test suite`}</h4>
        <p>${blurb}</p>
        <div class="btn-row ct-bulk-btns">
          <button type="button" class="secondary" data-ts-action="pick" data-ts-stage="${esc(stage.id)}" ${busy ? "disabled" : ""}>${r ? "Replace workbook" : "Select workbook"}</button>
          ${r ? `<button type="button" class="secondary" data-ts-action="remove" data-ts-stage="${esc(stage.id)}" ${busy ? "disabled" : ""}>Remove</button>` : ""}
        </div>
      </div>
      ${busy ? `<div class="ct-validate-row"><span class="running-indicator"><span class="running-spinner" aria-hidden="true"></span><span>${esc(s.busy)}</span></span></div>` : ""}
      ${s.error ? `<div class="callout warn ct-callout">${esc(s.error)}</div>` : ""}
      ${r ? sheetsHtml(r, s.extraction) : ""}
      ${r ? `<div class="ct-validate-row">
          <button type="button" class="primary" data-ts-action="extract" data-ts-stage="${esc(stage.id)}" ${busy ? "disabled" : ""}>${s.extraction ? "Re-extract test cases" : "Extract test cases"}</button>
          <span class="fl-muted-small">Reads every test case sheet row by row into JSON, one entry per unique test ID.</span>
        </div>` : ""}
      ${r && s.extraction ? extractionHtml(stage.id, s.extraction, busy) : ""}
    </section>`;
  }

  SUITE_STAGES.forEach((id) => {
    P.stageSections[id] = sectionHtml;
  });

  document.addEventListener("click", (e) => {
    const root = $("view-flow");
    if (!root || !root.contains(e.target)) return;
    const action = e.target.closest("[data-ts-action]");
    if (!action || action.disabled) return;
    const stageId = action.dataset.tsStage;
    if (action.dataset.tsAction === "pick") pick(stageId);
    else if (action.dataset.tsAction === "remove") remove(stageId);
    else if (action.dataset.tsAction === "extract") extract(stageId);
    else if (action.dataset.tsAction === "download") download(stageId);
  });
})();
