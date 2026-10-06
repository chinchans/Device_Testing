(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }

  const ICONS = {
    signal: '<path d="M5 12.5a7 7 0 0 1 14 0"/><path d="M8.5 12.5a3.5 3.5 0 0 1 7 0"/><path d="M12 12.5V21M9 21h6"/>',
    badge: '<circle cx="12" cy="9" r="6"/><path d="m9 9 2 2 4-4"/><path d="M8.5 14 7 22l5-3 5 3-1.5-8"/>',
    clipboard: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1"/><path d="m9 12 2 2 4-4"/>',
    wrench: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4 2.5-2.5z"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    pin: '<path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
    users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6.5 6.5 0 0 1 3.5 6"/>'
  };

  /** Operator test programs. Each one gets its own page; workflows are added per program. */
  const OPERATOR_TESTS = [
    { id: "sfn", code: "SFN", name: "SFN", desc: "SFN test program on the operator network.", icon: "signal" },
    { id: "pat", code: "PAT", name: "PAT", desc: "Product acceptance against the operator's requirements.", icon: "badge" },
    { id: "apt", code: "APT", name: "APT", desc: "APT test program for operator approval.", icon: "clipboard" },
    { id: "maintenance", code: "MNT", name: "Maintenance", desc: "Regression checks for maintenance releases and patches.", icon: "wrench" },
    { id: "idot", code: "IDOT", name: "IDOT", desc: "IDOT test program with the operator.", icon: "link" },
    { id: "bespoke", code: "BSP", name: "Bespoke", desc: "Custom test plans for operator-specific requirements.", icon: "sliders" },
    { id: "field", code: "FLD", name: "Field Testing", desc: "Live-network testing in real locations and conditions.", icon: "pin" },
    { id: "fut", code: "FUT", name: "FUT", desc: "Field user trials with real users on the operator network.", icon: "users" }
  ];

  const st = { current: null };

  const icon = (name) =>
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;

  function deviceLabel() {
    const sel = $("device-type-select");
    return sel && sel.value ? sel.selectedOptions[0].text : "";
  }

  function setBreadcrumb(test) {
    $("op-breadcrumb").innerHTML = test
      ? `Workbench <span>/</span> <button type="button" class="op-crumb" data-op-home>Operator Testing</button> <span>/</span> ${esc(test.name)}`
      : "Workbench <span>/</span> Operator Testing";
  }

  function renderHub() {
    const device = deviceLabel();
    $("op-root").innerHTML = `
      <section class="panel op-hero">
        <div>
          <h2 class="op-hero-title">Operator Testing</h2>
          <p class="op-hero-sub">Choose an operator test program. Each program has its own page, workflow and results.</p>
        </div>
        ${device ? `<span class="status-pill is-ready">${esc(device)}</span>` : ""}
      </section>
      <div class="op-grid" role="list">
        ${OPERATOR_TESTS.map((t) => `
          <button type="button" class="op-card" data-op-test="${t.id}" role="listitem">
            <span class="op-card-top">
              <span class="op-tile">${icon(t.icon)}</span>
              <span class="op-code">${esc(t.code)}</span>
            </span>
            <span class="op-card-name">${esc(t.name)}</span>
            <span class="op-card-desc">${esc(t.desc)}</span>
            <span class="op-card-foot">
              <span class="op-arrow" aria-hidden="true">→</span>
            </span>
          </button>`).join("")}
      </div>`;
  }

  function renderTest(test) {
    $("op-root").innerHTML = `
      <div class="op-switcher" role="tablist" aria-label="Operator test programs">
        ${OPERATOR_TESTS.map((t) => `
          <button type="button" role="tab" class="op-switch ${t.id === test.id ? "is-active" : ""}"
            aria-selected="${t.id === test.id}" data-op-test="${t.id}">${esc(t.name)}</button>`).join("")}
      </div>

      <section class="panel op-detail-head">
        <span class="op-tile op-tile-lg">${icon(test.icon)}</span>
        <div class="op-detail-text">
          <div class="op-detail-title">${esc(test.name)} <span class="op-code">${esc(test.code)}</span></div>
          <p class="op-hero-sub">${esc(test.desc)}</p>
        </div>
        <span class="status-pill">Not configured</span>
      </section>

      <div class="op-detail-grid">
        <section class="panel op-empty">
          <span class="op-tile op-tile-lg">${icon(test.icon)}</span>
          <h3>The ${esc(test.name)} workflow will live here</h3>
          <p>This page will hold the ${esc(test.name)} configuration, execution and results.
            It works independently of Device Inventory.</p>
          <button type="button" class="primary" disabled title="Available once the ${esc(test.name)} workflow is added">Start ${esc(test.name)} run</button>
        </section>

        <aside class="panel op-side">
          <h3 class="op-side-title">Program</h3>
          <dl class="op-facts">
            <div><dt>Test type</dt><dd>${esc(test.name)}</dd></div>
            <div><dt>Device</dt><dd>${esc(deviceLabel() || "Not selected")}</dd></div>
            <div><dt>Status</dt><dd>Not configured</dd></div>
            <div><dt>Last run</dt><dd>—</dd></div>
          </dl>
          <button type="button" class="secondary op-back" data-op-home>← All operator tests</button>
        </aside>
      </div>`;
  }

  function render() {
    const test = OPERATOR_TESTS.find((t) => t.id === st.current) || null;
    setBreadcrumb(test);
    if (test) renderTest(test);
    else renderHub();
    $("view-operator-testing").scrollTop = 0;
  }

  function open(id) {
    st.current = id;
    render();
  }

  document.addEventListener("click", (e) => {
    const view = $("view-operator-testing");
    if (!view || !view.contains(e.target)) return;
    const card = e.target.closest("[data-op-test]");
    if (card) return open(card.dataset.opTest);
    if (e.target.closest("[data-op-home]")) open(null);
  });

  document.addEventListener("keydown", (e) => {
    const tab = e.target.closest && e.target.closest(".op-switch");
    if (!tab || !["ArrowLeft", "ArrowRight"].includes(e.key)) return;
    const i = OPERATOR_TESTS.findIndex((t) => t.id === tab.dataset.opTest);
    const next = OPERATOR_TESTS[(i + (e.key === "ArrowRight" ? 1 : -1) + OPERATOR_TESTS.length) % OPERATOR_TESTS.length];
    open(next.id);
    document.querySelector(`.op-switch[data-op-test="${next.id}"]`)?.focus();
  });

  document.addEventListener("operator:home", () => open(null));

  document.addEventListener("workbench:view", (e) => {
    if (e.detail && e.detail.view === "operator-testing") render();
  });
})();
