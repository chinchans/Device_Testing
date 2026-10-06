# No functional changes — Test Execution visual refactor

## Files changed

| File | Kind of change |
|---|---|
| `Frontend/src/styles.css` | The Test Execution block was rewritten (it starts at `/* ── Test Execution ─` and runs to the end of the file). Every rule before it is byte-for-byte identical to `baseline/styles.css`. Every selector in the block is page-specific: `.tex-*`, `#tex-*`, `.view-tex …`, `#view-test-execution`, plus the two existing `.status-pill.is-blocked` / `.is-muted` modifiers, which are unchanged. |
| `Frontend/src/index.html` | Setup markup reordered (Test cases card first, configuration column second). Warnings and the Start row moved into a new wrapper card at the bottom of the configuration column. The two Refresh buttons show ↻ and gained `aria-label` and `title`. "Add override" became "+ Add override". |
| `Frontend/src/execution.js` | Only HTML inside five template strings: `renderDeviceInfo`, `renderSetInfo`, `caseRow`, `logLine`, and the pass-rate chip in `renderResults`. See the diff below. |
| `Frontend/src/app.js`, `preload.js`, `main.js`, backend | Not touched. |

Compare against the originals with `diff -u docs/ui-refactor/baseline/<file> src/<file>`.

## Confirmations

- **Props, state and hooks:** this app has no components, props or hooks. The state object
  `st` is untouched: no new keys and no changed keys.
- **API calls:** there are no new, removed or changed `fetch`, `getJSON`, `postJSON`,
  `download` or `EventSource` calls. Endpoints, query strings and payloads are identical.
- **Event handling:**
  - `bind()` is unchanged.
  - All 59 element IDs in the Test Execution markup are still present (59 before, 59 after).
  - All `data-*` attributes used by handlers are kept, including `data-case-id`,
    `data-category`, `data-ov-index`, `data-ov-field`, `data-ov-remove`, `data-queue-case`,
    `data-res-action`, `data-cause`, `data-review`, `data-file-view`, `data-file-download`,
    `data-detail-action`, `data-exec-id` and `data-close-modal`.
  - Handlers that read `e.target` directly (Results header buttons, override ×, Compare
    tick boxes) still receive the same element, because no wrappers were added inside them.
- **Class names:** none renamed or removed. New classes were only added:
  - `tex-device-summary`, `tex-device-name`
  - `tex-health-inline`, `tex-divided`
  - `tex-spec-row`, `tex-disclosure`, `tex-disclosure-body`
  - `tex-case-ready`
  - `tex-log-time`, `tex-log-case`, `tex-log-msg`
  - `tex-pass-rate`
  - `tex-start-card`, `tex-icon-btn`
- **Behaviour:** tab switching, selection logic, readiness, estimates, overrides, smoke
  preset, warnings computation, Start confirmation, pause/resume/skip/stop, log
  filter/auto-scroll/retention, metric and health updates, screenshot polling, cause
  filtering, review submission, file viewer, rerun/export, history scope and Compare are
  unchanged.
- **Confirmation dialogs, error handling, loading states, storage:** unchanged. There is
  no localStorage/sessionStorage use and no routing on this page.
- **Accessibility:**
  - `role`, `aria-label` and `aria-modal` attributes are preserved.
  - The Refresh buttons gained `aria-label`s because their visible text is now a glyph.
  - Keyboard tab order on Setup now follows the new visual order (cases first). This was
    agreed before the change.
- **Dependencies:** none added (`package.json` unchanged).
- **Colours and fonts:** no new colour values or CSS variables. Every colour in the block
  already appears in `styles.css`. No new font families.
- **Breakpoints:** the page's existing breakpoints are kept (1280px and 960px). No new
  media queries. The ≤1280px query gained a two-line case-row layout so names stay
  visible at that width.

## Verification performed

1. **Functional trace.** `/tmp/tex_capture.js` drives the real Electron UI against a test
   backend (port 8010) and the emulator. It records 54 observations covering:
   - device and set selection, Clear, Select runnable, category toggle;
   - add, edit and remove override, smoke preset;
   - selecting three cases, Start (with confirmation);
   - Live state, queue, log filter, finished state and button states, metrics, checkpoints;
   - View results, verdicts, cause filter on and off, case detail sections;
   - review buttons, image thumbnail, image viewer, script viewer, closing the dialog;
   - Mark Pass (verdict becomes "Pass reviewed", pass rate becomes 100%);
   - History rows, Compare, opening an older execution.

   Before and after traces are in `before/trace.json` and `after/trace.json`. Every
   difference is data or timing, not UI behaviour:
   - duration estimates are 1s higher, because the capture runs added to the
     median-of-past-runs history;
   - History has more rows, and Compare paired different runs;
   - the device card's model, Android and type moved from label/value rows into the new
     summary block, with the same text.

   Neither run logged a console error.
2. **Syntax:** `node --check src/execution.js` passes.
3. **Backend tests:** `pytest -q tests` gives 37 passed.
4. **Lints:** no linter errors in the three files.
5. **Screenshots:** before and after at 1366×768, and at the existing 1200px and 900px
   breakpoints (see `UI_CHANGES.md`).

The executions created by the capture runs were deleted afterwards.

## `execution.js` diff (complete)

```diff
@@ renderDeviceInfo
-      <div class="tex-kv">
-        <div class="tex-kv-row"><span>Model</span><span>${…model…}</span></div>
-        <div class="tex-kv-row"><span>Android</span><span>${…} (API ${…})</span></div>
-        <div class="tex-kv-row"><span>Type</span><span>${emulator ? "Emulator" : "Physical device"}</span></div>
-        ${healthRows(h)}
-      </div>
-      <div class="tex-subhead">Harness packages</div>
-      <div class="tex-kv">${pkgs || '<span class="muted">None</span>'}</div>
+      <div class="tex-device-summary">
+        <div class="tex-device-name">${…model…}</div>
+        <div class="tex-muted-small">Android ${…} (API ${…}) · ${emulator ? "Emulator" : "Physical device"}</div>
+      </div>
+      <div class="tex-kv tex-health-inline tex-divided">${healthRows(h)}</div>
+      <div class="tex-kv tex-divided">
+        <div class="tex-subhead">Harness packages</div>
+        ${pkgs || '<span class="muted">None</span>'}
+      </div>
@@ renderSetInfo
-    const spec = Object.entries(s.spec_applied || {})
-      .map(([k, v]) => `<span class="tex-chip" title="…">${k} = ${v.value}</span>`)
+    const specEntries = Object.entries(s.spec_applied || {});
+    const spec = specEntries
+      .map(([k, v]) => `<div class="tex-spec-row" title="…"><span class="tex-mono">${k}</span><span>${v.value}</span></div>`)
 …
-      ${spec ? `<div class="tex-subhead">Spec values in these scripts</div><div class="tex-chips">${spec}</div>` : ""}
+      ${spec ? `<div class="tex-divided"><div class="tex-subhead">Spec values in these scripts</div>
+        ${specEntries.length > 5 ? `<details class="tex-disclosure"><summary>${n} spec values</summary>
+          <div class="tex-disclosure-body">${spec}</div></details>` : `<div class="tex-disclosure-body">${spec}</div>`}
+      </div>` : ""}
@@ caseRow
-        ${changes.length ? `<span class="tex-warn-icon" …>⚠</span>` : ""}
-        <span title="${tip}">${pill(label, cls)}</span>
+        <span class="tex-case-ready">
+          ${changes.length ? `<span class="tex-warn-icon" …>⚠</span>` : ""}
+          <span title="${tip}">${pill(label, cls)}</span>
+        </span>
@@ logLine
-  <span class="tex-log-meta">${time} ${case_id}</span> ${text}
+  <span class="tex-log-meta"><span class="tex-log-time">${time}</span> <span class="tex-log-case">${case_id}</span></span> <span class="tex-log-msg">${text}</span>
@@ renderResults
-        <span class="tex-count-chip">Pass rate <b>…</b></span>
+        <span class="tex-count-chip tex-pass-rate">Pass rate <b>…</b></span>
```
