(() => {
  "use strict";

  const FLOW = window.OPERATOR_FLOW;
  const STAGES = FLOW.stages;
  const $ = (id) => document.getElementById(id);

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }

  // ── Static definitions ──────────────────────────────

  const OEM_STEPS = [
    { view: "feature-extraction", label: "Device Inventory" },
    { view: "device-classification", label: "Device Classification" },
    { view: "test-case-generation", label: "Test Case Generation" },
    { view: "framework-selection", label: "Framework Selection" },
    { view: "test-script-generation", label: "Test Script Generation" },
    { view: "test-execution", label: "Test Execution" },
    { view: "rca", label: "RCA" }
  ];

  const REPORT_SECTIONS = [
    { id: "consolidated", label: "Consolidated Report" },
    { id: "certification", label: "Certification Report" },
    { id: "stages", label: "Stage Reports" },
    { id: "rounds", label: "Round History" }
  ];

  const ENV = {
    lab: { label: "Lab · Test SIMs · Instrumented", short: "Lab" },
    local: { label: "Local field · Live SIMs · Limited instrumentation", short: "Local field" },
    global: { label: "Global field · Live SIMs · Limited instrumentation", short: "Global field" }
  };

  const GATE = {
    reject: { label: "Gate: critical failure = reject", consequence: "device is rejected" },
    fix: { label: "Gate: critical issue = needs fix", consequence: "approval held until fixed" },
    report: { label: "Gate: findings are reported", consequence: "reported in the consolidated report" }
  };

  const STATUS = {
    todo: { label: "Not started", pill: "" },
    progress: { label: "In progress", pill: "is-running" },
    done: { label: "Passed", pill: "is-success" },
    failed: { label: "Failed", pill: "is-failed" }
  };

  const ICONS = {
    home: '<path d="M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1v-10.5z"/>',
    reports: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 15v-2M12 15V9M17 15v-5"/>',
    phone: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    cross: '<path d="M7 7l10 10M17 7 7 17"/>',
    chevron: '<path d="m9 6 6 6-6 6"/>'
  };

  const svg = (name, cls = "") =>
    `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;

  const NAV_ICONS = {
    home: ICONS.home,
    reports: ICONS.reports,
    "device-selection": ICONS.phone,
    certifications: '<path d="M12 3 5 6v5c0 4.5 3 8.5 7 10 4-1.5 7-5.5 7-10V6l-7-3z"/><path d="m9 12 2 2 4-4"/>',
    operator: '<path d="M5 12.5a7 7 0 0 1 14 0"/><path d="M8.5 12.5a3.5 3.5 0 0 1 7 0"/><path d="M12 12.5V21M9 21h6"/>',
    "feature-extraction": '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/>',
    "device-classification": '<path d="M20.6 13.4 12.9 21a2 2 0 0 1-2.8 0L3 13.9a2 2 0 0 1 0-2.8l7.7-7.7a2 2 0 0 1 2.8 0l7.1 7.1a2 2 0 0 1 0 2.9z"/><circle cx="8.5" cy="8.5" r="1.2"/>',
    "test-case-generation": '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="m8 12 3 3 5-6"/>',
    "framework-selection": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9c.3.6.9 1 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "test-script-generation": '<path d="m8 8-4 4 4 4M16 8l4 4-4 4"/>',
    "test-execution": '<path d="M13 2 4 14h7l-1 8 10-14h-7l1-6z"/>'
  };

  const navIcon = (name) =>
    `<span class="nav-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">${NAV_ICONS[name] || ""}</svg></span>`;

  /** Status marker used in the sidebar, cards and lists. */
  function dot(status) {
    if (status === "done") return `<span class="pl-dot is-done">${svg("check")}</span>`;
    if (status === "failed") return `<span class="pl-dot is-failed">${svg("cross")}</span>`;
    if (status === "progress") return '<span class="pl-dot is-progress"></span>';
    if (status === "none") return '<span class="pl-dot is-none"></span>';
    return '<span class="pl-dot is-todo"></span>';
  }

  function pill(status, label) {
    const meta = STATUS[status] || STATUS.todo;
    return `<span class="status-pill ${meta.pill}">${esc(label || meta.label)}</span>`;
  }

  // ── State ───────────────────────────────────────────

  const store = {
    route: "home",
    round: 1,
    roundStart: null,
    rounds: [],
    cycleStart: null,
    /** "stage.substage.index" → { verdict, actual, notes, critical, measured, at } */
    results: {},
    /** "stage.substage" → index of the open scenario */
    cursor: {},
    approval: null,
    activity: [],
    /** Sidebar dropdowns the user opened or closed by hand: key → open */
    navOpen: {},
    navRoute: null
  };

  const renderers = {};
  /** stageId → () => HTML rendered under the stage header (e.g. test suite intake). */
  const stageSections = {};
  const certApi = {
    summary: () => FLOW.certificates.map((c) => ({ id: c.id, name: c.name, verdict: "todo" })),
    attention: () => []
  };

  function workbench() {
    return window.workbench || null;
  }

  function wbState() {
    const wb = workbench();
    return wb && wb.getState ? wb.getState() : {};
  }

  function deviceSelected() {
    return Boolean(wbState().deviceType);
  }

  function deviceLabel() {
    const wb = workbench();
    return (wb && wb.deviceLabel && wb.deviceLabel()) || "";
  }

  function deviceModel() {
    const dc = wbState().deviceClassification || {};
    return [dc.manufacturer, dc.model].filter(Boolean).join(" ");
  }

  function cycleDay() {
    if (!store.cycleStart) return null;
    return Math.floor((Date.now() - store.cycleStart.getTime()) / 86400000) + 1;
  }

  function log(text, tone = "info") {
    store.activity.unshift({ at: new Date(), text, tone });
    store.activity.length = Math.min(store.activity.length, 50);
  }

  // ── Results and status ──────────────────────────────

  const resultKey = (stageId, subId, index) => `${stageId}.${subId}.${index}`;

  function result(key) {
    return store.results[key] || null;
  }

  function setResult(key, patch) {
    store.results[key] = { ...(store.results[key] || {}), ...patch };
  }

  const hasSubs = (stage) => Boolean(stage.substages && stage.substages.length);

  function itemsOf(sub) {
    return sub.scenarios || sub.kpis || [];
  }

  function substageCounts(stage, sub) {
    const items = itemsOf(sub);
    const c = { total: items.length, pass: 0, fail: 0, skip: 0, critical: 0 };
    items.forEach((_, i) => {
      const r = result(resultKey(stage.id, sub.id, i));
      if (!r || !r.verdict) return;
      if (r.verdict === "pass") c.pass++;
      else if (r.verdict === "skip") c.skip++;
      else if (r.verdict === "fail") {
        c.fail++;
        if (r.critical) c.critical++;
      }
    });
    c.pending = c.total - c.pass - c.fail - c.skip;
    return c;
  }

  function statusFromCounts(c) {
    if (c.fail) return "failed";
    if (!c.total) return "todo";
    if (c.pending === 0) return "done";
    if (c.pass + c.skip > 0) return "progress";
    return "todo";
  }

  function oemStepDone(view) {
    const s = wbState();
    if (view === "feature-extraction") return Boolean(s.extractionRegistered && (s.features || []).length);
    if (view === "device-classification") {
      const dc = s.deviceClassification || {};
      return Boolean(s.extractionRegistered && (dc.manufacturer || dc.model));
    }
    if (view === "test-case-generation") return Object.keys(s.tcCatalogs || {}).length > 0;
    if (view === "framework-selection") return Boolean(s.frameworksConfirmed);
    if (view === "test-script-generation") return (s.tsgResults || []).length > 0;
    if (view === "test-execution") return oemStats().executions > 0;
    return false;
  }

  function futStatus() {
    const steps = OEM_STEPS.filter((s) => s.view !== "rca");
    const done = steps.filter((s) => oemStepDone(s.view)).length;
    return done === steps.length ? "done" : done ? "progress" : "todo";
  }

  function stageSummary(stage) {
    if (stage.template === "fut") {
      const status = futStatus();
      return { status, total: 0, pass: 0, fail: 0, skip: 0, critical: 0, pending: 0, subsDone: status === "done" ? 1 : 0, subsTotal: 1 };
    }
    if (stage.template === "approval") {
      const status = store.approval ? (store.approval.decision === "approved" ? "done" : "failed") : "todo";
      return { status, total: 0, pass: 0, fail: 0, skip: 0, critical: 0, pending: 0, subsDone: status === "done" ? 1 : 0, subsTotal: 1 };
    }
    const totals = { total: 0, pass: 0, fail: 0, skip: 0, critical: 0, pending: 0, subsDone: 0, subsTotal: stage.substages.length };
    stage.substages.forEach((sub) => {
      const c = substageCounts(stage, sub);
      ["total", "pass", "fail", "skip", "critical", "pending"].forEach((k) => (totals[k] += c[k]));
      if (statusFromCounts(c) === "done") totals.subsDone++;
    });
    totals.status = statusFromCounts(totals);
    return totals;
  }

  function certSummary() {
    const list = certApi.summary();
    const passed = list.filter((c) => c.verdict === "done").length;
    const failed = list.filter((c) => c.verdict === "failed").length;
    const started = list.some((c) => c.verdict !== "todo");
    const status = failed ? "failed" : passed === list.length ? "done" : started ? "progress" : "todo";
    return { list, passed, failed, total: list.length, status };
  }

  function operatorStatus() {
    const statuses = STAGES.map((s) => stageSummary(s).status);
    if (statuses.includes("failed")) return "failed";
    if (statuses.every((s) => s === "done")) return "done";
    if (statuses.some((s) => s !== "todo")) return "progress";
    return "todo";
  }

  function totals() {
    const t = { total: 0, pass: 0, fail: 0, skip: 0, critical: 0 };
    STAGES.forEach((stage) => {
      if (!stage.substages) return;
      const s = stageSummary(stage);
      ["total", "pass", "fail", "skip", "critical"].forEach((k) => (t[k] += s[k]));
    });
    return t;
  }

  function routeOfStage(stage) {
    if (stage.template === "fut") return "fut-oem";
    if (stage.template === "approval") return "approval";
    return `stage:${stage.id}`;
  }

  function startNewRound(outcome) {
    const t = totals();
    store.rounds.push({
      no: store.round,
      outcome,
      start: store.roundStart || store.cycleStart,
      end: new Date(),
      pass: t.pass,
      fail: t.fail,
      critical: t.critical
    });
    store.results = {};
    store.cursor = {};
    store.approval = null;
    store.round++;
    store.roundStart = new Date();
    log(`Round ${store.round - 1} closed: ${outcome}. Round ${store.round} started.`, "fail");
    navigate("certifications");
  }

  // ── Routing ─────────────────────────────────────────

  const APP_VIEWS = ["home", "device-selection", "certifications", "device-monitoring"];

  function viewForRoute(route) {
    if (APP_VIEWS.includes(route)) return route;
    if (route.startsWith("oem:")) return route.slice(4);
    if (route.startsWith("reports")) return "reports";
    return "flow";
  }

  function routeForView(view) {
    if (APP_VIEWS.includes(view)) return view;
    if (view === "reports") return "reports";
    if (OEM_STEPS.some((s) => s.view === view)) return `oem:${view}`;
    return null;
  }

  function navigate(route) {
    if (route === "fut" || route === "fut-oem") route = "oem:feature-extraction";
    if (route.startsWith("oem:") && !deviceSelected()) route = "device-selection";
    const changed = route !== store.route;
    store.route = route;
    const view = viewForRoute(route);
    workbench().showView(view);
    if (changed) {
      const el = $(`view-${view}`);
      if (el) el.scrollTop = 0;
    }
  }

  function renderCurrent() {
    const route = store.route;
    const [head, a, b] = route.split(":");
    if (route === "home") renderHome();
    else if (route === "certifications") renderers.certifications && renderers.certifications();
    else if (head === "reports") renderReports(a || "consolidated");
    else if (route === "operator") renderOperator();
    else if (head === "stage") renderers.stage && renderers.stage(a, b || null);
    else if (route === "fut-csp") renderCsp();
    else if (route === "approval") renderApproval();
    renderBreadcrumb();
    renderSidebar();
  }

  // ── Breadcrumbs ─────────────────────────────────────

  function crumbsFor(route) {
    const [head, a, b] = route.split(":");
    const op = ["Operator Testing", "operator"];
    if (route === "home") return [["Home"]];
    if (route === "device-selection") return [["Pipeline"], ["Device Selection"]];
    if (route === "certifications") return [["Pipeline"], ["Regulatory Certifications"]];
    if (route === "device-monitoring") return [["Monitoring"], ["Devices"]];
    if (route === "operator") return [["Pipeline"], ["Operator Testing"]];
    if (head === "stage") {
      const stage = STAGES.find((s) => s.id === a);
      if (!stage) return [["Pipeline"], op];
      const sub = b && stage.substages.find((s) => s.id === b);
      return sub
        ? [["Pipeline"], op, [stage.name, `stage:${stage.id}`], [sub.name]]
        : [["Pipeline"], op, [stage.name]];
    }
    if (route === "fut-csp") return [["Pipeline"], op, ["FUT"], ["CSP"]];
    if (head === "oem") {
      const step = OEM_STEPS.find((s) => s.view === a);
      return [["Pipeline"], op, ["FUT"], ["OEM", "fut-oem"], [step ? step.label : a]];
    }
    if (route === "approval") return [["Pipeline"], op, ["Approval"]];
    if (head === "reports") {
      const sec = REPORT_SECTIONS.find((s) => s.id === (a || "consolidated"));
      return [["Insights"], ["Reports", "reports"], [sec ? sec.label : ""]];
    }
    return [["Home", "home"]];
  }

  function renderBreadcrumb() {
    const view = viewForRoute(store.route);
    const el = document.querySelector(`#view-${view} .wb-breadcrumb`);
    if (!el) return;
    const crumbs = crumbsFor(store.route);
    el.innerHTML = crumbs
      .map(([label, route], i) => {
        const last = i === crumbs.length - 1;
        if (route && !last) return `<button type="button" class="pl-crumb" data-route="${esc(route)}">${esc(label)}</button>`;
        return last ? `<strong>${esc(label)}</strong>` : esc(label);
      })
      .join(" <span>/</span> ");
  }

  // ── Sidebar ─────────────────────────────────────────

  function inBranch(prefixes) {
    return prefixes.some((p) => store.route === p || store.route.startsWith(`${p}:`));
  }

  /** Whether the current route sits inside a sidebar dropdown. */
  function routeInside(key) {
    if (key === "operator") return store.route === "operator" || inBranch(["stage", "fut", "fut-csp", "oem", "approval"]);
    if (key === "fut") return inBranch(["fut", "fut-csp", "oem"]);
    if (key === "oem") return inBranch(["oem"]);
    if (key === "reports") return inBranch(["reports"]);
    return inBranch([key]);
  }

  function isOpen(key) {
    if (key in store.navOpen) return store.navOpen[key];
    return key === "operator" || routeInside(key);
  }

  /** On navigation, re-open any dropdown that contains the new route. */
  function revealRoute() {
    if (store.navRoute === store.route) return;
    store.navRoute = store.route;
    Object.keys(store.navOpen).forEach((key) => {
      if (routeInside(key)) delete store.navOpen[key];
    });
  }

  function caret(toggle) {
    if (!toggle) return "";
    const open = isOpen(toggle);
    return `<span class="pl-caret ${open ? "is-open" : ""}" data-nav-toggle="${esc(toggle)}" role="button"
      aria-label="${open ? "Collapse" : "Expand"}" aria-expanded="${open}">${svg("chevron")}</span>`;
  }

  function navItem({ route, label, icon, active, branch, toggle, children }) {
    return `<button type="button" class="nav-item pl-item ${active ? "active" : ""} ${branch ? "in-branch" : ""}" data-route="${esc(route)}">
        ${navIcon(icon)}
        <span class="pl-label">${esc(label)}</span>
        ${caret(toggle)}
      </button>${children || ""}`;
  }

  function childItem({ route, label, status, meta, level, icon, active, branch, toggle, children }) {
    const cls = ["nav-item", "pl-child", `lvl-${level}`, `is-${status || "none"}`];
    if (active) cls.push("active");
    if (branch) cls.push("in-branch");
    const action = route ? `data-route="${esc(route)}"` : `data-nav-toggle="${esc(toggle)}" aria-expanded="${isOpen(toggle)}"`;
    return `<button type="button" class="${cls.join(" ")}" ${action}>
        ${icon ? navIcon(icon) : ""}
        <span class="pl-label">${esc(label)}</span>
        ${meta ? `<span class="pl-meta">${esc(meta)}</span>` : ""}
        ${caret(toggle)}
      </button>${children || ""}`;
  }

  function stageChildren(stage) {
    const r = store.route;
    if (stage.template === "fut") {
      if (!isOpen("fut")) return "";
      const inOem = r.startsWith("oem:");
      const oemSteps = isOpen("oem")
        ? OEM_STEPS.filter((s) => s.view !== "rca")
            .map((s) =>
              childItem({
                route: `oem:${s.view}`,
                label: s.label,
                icon: s.view,
                level: 4,
                active: r === `oem:${s.view}`
              })
            )
            .join("")
        : "";
      const oemStatus = OEM_STEPS.some((s) => oemStepDone(s.view)) ? "progress" : "todo";
      return (
        childItem({ route: "fut-oem", label: "OEM", status: oemStatus, level: 3, branch: inOem, toggle: "oem", children: oemSteps }) +
        childItem({ route: "fut-csp", label: "CSP", status: "todo", level: 3, active: r === "fut-csp" })
      );
    }
    if (!hasSubs(stage) || !isOpen(`stage:${stage.id}`)) return "";
    return stage.substages
      .map((sub) => {
        const c = substageCounts(stage, sub);
        return childItem({
          route: `stage:${stage.id}:${sub.id}`,
          label: sub.name,
          status: statusFromCounts(c),
          level: 3,
          active: r === `stage:${stage.id}:${sub.id}`
        });
      })
      .join("");
  }

  function renderSidebar() {
    const r = store.route;
    const overview = $("pl-nav-overview");
    const pipeline = $("pl-nav-pipeline");
    const insights = $("pl-nav-insights");
    const monitoring = $("pl-nav-monitoring");
    if (!overview || !pipeline || !insights) return;
    revealRoute();

    overview.innerHTML = navItem({ route: "home", label: "Home", icon: "home", active: r === "home" });

    const stages = STAGES.map((stage) => {
      const route = routeOfStage(stage);
      const s = stageSummary(stage);
      const meta = hasSubs(stage) ? `${s.subsDone}/${s.subsTotal}` : "";
      const branch =
        stage.template === "fut" ? inBranch(["fut", "fut-csp", "oem"]) : inBranch([route]);
      const isFut = stage.template === "fut";
      return childItem({
        route: isFut ? null : route,
        label: stage.name,
        status: s.status,
        meta,
        level: 2,
        active: !isFut && r === route,
        branch: isFut ? branch : branch && r !== route,
        toggle: isFut ? "fut" : hasSubs(stage) ? route : null,
        children: stageChildren(stage)
      });
    }).join("");

    const opBranch = r === "operator" || inBranch(["stage", "fut", "fut-csp", "oem", "approval"]);
    pipeline.innerHTML = [
      navItem({
        route: "device-selection",
        label: "Device Selection",
        icon: "device-selection",
        active: r === "device-selection"
      }),
      navItem({
        route: "certifications",
        label: "Regulatory Certifications",
        icon: "certifications",
        active: r === "certifications"
      }),
      navItem({
        route: "operator",
        label: "Operator Testing",
        icon: "operator",
        active: r === "operator",
        branch: opBranch && r !== "operator",
        toggle: "operator",
        children: isOpen("operator") ? stages : ""
      })
    ].join("");

    const reportChildren = isOpen("reports")
      ? REPORT_SECTIONS.map((s) =>
          childItem({
            route: `reports:${s.id}`,
            label: s.label,
            level: 2,
            active: r === `reports:${s.id}` || (r === "reports" && s.id === "consolidated")
          })
        ).join("")
      : "";
    insights.innerHTML = navItem({
      route: "reports",
      label: "Reports",
      icon: "reports",
      branch: r.startsWith("reports"),
      toggle: "reports",
      children: reportChildren
    });

    if (monitoring) {
      monitoring.innerHTML = navItem({
        route: "device-monitoring",
        label: "Device Monitoring",
        icon: "device-selection",
        active: r === "device-monitoring"
      });
    }

    const activeItems = document.querySelectorAll(
      "#pl-nav-overview .active, #pl-nav-pipeline .active, #pl-nav-insights .active, #pl-nav-monitoring .active"
    );
    const activeItem = activeItems[activeItems.length - 1];
    if (activeItem) activeItem.scrollIntoView({ block: "nearest" });
  }

  // ── Shared page pieces ──────────────────────────────

  function headPanel({ title, desc, env, gate, status, statusLabel, side }) {
    return `<section class="panel fl-head ${env ? `env-${env}` : ""}">
      <div class="fl-head-main">
        <div class="fl-title-row">
          <h2 class="fl-title">${title}</h2>
          ${status ? pill(status, statusLabel) : ""}
        </div>
        ${desc ? `<p class="fl-desc">${esc(desc)}</p>` : ""}
        ${env || gate ? `<div class="fl-chips">
          ${env ? `<span class="fl-chip env-${env}">${esc(ENV[env].label)}</span>` : ""}
          ${gate ? `<span class="fl-chip gate-${gate}">${esc(GATE[gate].label)}</span>` : ""}
        </div>` : ""}
      </div>
      ${side ? `<div class="fl-head-side">${side}</div>` : ""}
    </section>`;
  }

  function progressSide(label, done, total) {
    const pct = total ? Math.round((done / total) * 100) : 0;
    return `<div class="fl-progress-label">${esc(label)}</div>
      <div class="fl-bar"><span style="width:${pct}%"></span></div>`;
  }

  function cycleNode({ route, name, meta, status, env }) {
    return `<button type="button" class="fl-node env-${env} is-${status}" data-route="${esc(route)}">
      ${dot(status)}
      <span class="fl-node-text">
        <span class="fl-node-name">${esc(name)}</span>
        <span class="fl-node-meta">${esc(meta)}</span>
      </span>
    </button>`;
  }

  function stageNode(id) {
    const stage = STAGES.find((s) => s.id === id);
    const s = stageSummary(stage);
    let meta = STATUS[s.status].label;
    if (hasSubs(stage)) meta += ` · ${s.subsDone}/${s.subsTotal}`;
    return cycleNode({ route: routeOfStage(stage), name: stage.name, meta, status: s.status, env: stage.id === "approval" ? "approval" : stage.env });
  }

  function cycleDiagram({ legend = true } = {}) {
    const certs = certSummary();
    const arrow = '<span class="fl-arrow" aria-hidden="true"></span>';
    const certNode = cycleNode({
      route: "certifications",
      name: "Certifications",
      meta: `${STATUS[certs.status].label} · ${certs.passed}/${certs.total}`,
      status: certs.status,
      env: "oem"
    });
    return `<div class="fl-cycle">
      ${certNode}${arrow}${stageNode("pat")}${arrow}${stageNode("sfn")}${arrow}${stageNode("functional")}${arrow}
      <div class="fl-fork">
        <div class="fl-fork-row">${stageNode("field")}${arrow}${stageNode("fut")}</div>
        <div class="fl-fork-row">${stageNode("regional")}${arrow}${stageNode("localization")}</div>
      </div>
      ${arrow}${stageNode("approval")}
    </div>${legend ? legendHtml() : ""}`;
  }

  function legendHtml() {
    return `<div class="fl-legend">
      <span><i class="lg env-lab"></i>Lab · Test SIMs</span>
      <span><i class="lg env-local"></i>Local field · Live SIMs</span>
      <span><i class="lg env-global"></i>Global field · Live SIMs</span>
      <span><i class="lg-line is-reject"></i>Critical → reject</span>
      <span><i class="lg-line is-fix"></i>Critical → needs fix</span>
    </div>`;
  }

  function kpiCard(label, value, hint, tone = "") {
    return `<article class="metric-card hm-kpi ${tone}">
      <div class="metric-card-label">${esc(label)}</div>
      <div class="metric-card-value">${esc(value)}</div>
      <div class="metric-card-hint">${esc(hint)}</div>
    </article>`;
  }

  function fmtTime(d) {
    if (!d) return "—";
    const today = new Date();
    const same = d.toDateString() === today.toDateString();
    const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return same ? time : `${d.toLocaleDateString([], { day: "2-digit", month: "short" })} ${time}`;
  }

  function fmtDate(d) {
    return d ? d.toLocaleDateString([], { day: "2-digit", month: "short", year: "numeric" }) : "—";
  }

  // ── Home ────────────────────────────────────────────

  function attentionItems() {
    const items = [];
    if (!deviceSelected()) items.push({ tone: "warn", text: "No device selected. Start with Device Selection." });
    items.push(...certApi.attention());
    STAGES.forEach((stage) => {
      const s = stageSummary(stage);
      if (s.critical && stage.substages) {
        items.push({
          tone: "fail",
          text: `${stage.name}: ${s.critical} critical failure${s.critical > 1 ? "s" : ""}, ${GATE[stage.gate].consequence}.`,
          route: routeOfStage(stage)
        });
      }
    });
    const day = cycleDay();
    if (day && FLOW.calendarDays - day <= 7) {
      items.push({ tone: "warn", text: `${Math.max(FLOW.calendarDays - day, 0)} calendar days left in this cycle.` });
    }
    return items;
  }

  const RING_R = 26;
  const RING_C = 2 * Math.PI * RING_R;

  function ring(fraction, color) {
    const f = Math.max(0, Math.min(1, fraction || 0));
    return `<svg class="hm-ring" viewBox="0 0 64 64" aria-hidden="true">
      <circle class="hm-ring-track" cx="32" cy="32" r="${RING_R}"/>
      <circle class="hm-ring-value" cx="32" cy="32" r="${RING_R}" stroke="${color}"
        stroke-dasharray="${RING_C.toFixed(2)}" stroke-dashoffset="${(RING_C * (1 - f)).toFixed(2)}" transform="rotate(-90 32 32)"/>
    </svg>`;
  }

  function donut(segments) {
    const total = segments.reduce((n, s) => n + s.value, 0) || 1;
    let offset = 0;
    const arcs = segments
      .filter((s) => s.value > 0)
      .map((s) => {
        const len = (RING_C * s.value) / total;
        const arc = `<circle class="hm-ring-value is-flat" cx="32" cy="32" r="${RING_R}" stroke="${s.color}"
          stroke-dasharray="${len.toFixed(2)} ${(RING_C - len).toFixed(2)}" stroke-dashoffset="${(-offset).toFixed(2)}" transform="rotate(-90 32 32)"/>`;
        offset += len;
        return arc;
      })
      .join("");
    return `<svg class="hm-ring" viewBox="0 0 64 64" aria-hidden="true"><circle class="hm-ring-track" cx="32" cy="32" r="${RING_R}"/>${arcs}</svg>`;
  }

  function gauge(label, value, fraction, color) {
    return `<div class="hm-gauge">
      <div class="hm-gauge-ring">${ring(fraction, color)}<span class="hm-gauge-value">${esc(value)}</span></div>
      <span class="hm-gauge-label">${esc(label)}</span>
    </div>`;
  }

  function oemStats() {
    const wb = workbench();
    return (wb && wb.oemStats && wb.oemStats()) || { features: 0, cases: 0, scripts: 0, executions: 0, avgScore: null, frameworks: 0 };
  }

  function homeHero() {
    const certs = certSummary();
    const stagesDone = STAGES.filter((stage) => stageSummary(stage).status === "done").length;
    const critical = totals().critical;
    const device = deviceSelected();
    const units = 1 + certs.total + STAGES.length;
    const done = (device ? 1 : 0) + certs.passed + stagesDone;
    const pct = Math.round((done / units) * 100);
    const stagesFailed = STAGES.filter((stage) => stageSummary(stage).status === "failed").length;
    const passed = certs.passed + stagesDone;
    const judged = passed + certs.failed + stagesFailed;
    const rate = judged ? passed / judged : null;
    const rateColor = rate == null || rate >= 0.8 ? "#16a34a" : rate >= 0.5 ? "#f59e0b" : "#dc2626";
    const model = deviceModel();

    return `
      <div class="hm-hero-main">
        <div class="hm-hero-kicker">Device under test</div>
        <div class="hm-hero-device">${esc(device ? model || deviceLabel() : "No device selected")}</div>
        ${device && model ? `<div class="hm-hero-chips"><span class="hm-hero-chip">${esc(deviceLabel())}</span></div>` : ""}
        ${device ? "" : '<button type="button" class="primary hm-hero-cta" data-route="device-selection">Select a device →</button>'}
      </div>
      <div class="hm-hero-gauges">
        ${gauge("Pipeline", `${pct}%`, pct / 100, "#1764e8")}
        ${gauge("Pass rate", rate == null ? "—" : `${Math.round(rate * 100)}%`, rate || 0, rateColor)}
        <div class="hm-gauge">
          <div class="hm-gauge-ring hm-gauge-count ${critical ? "is-bad" : ""}"><span class="hm-gauge-value">${critical}</span></div>
          <span class="hm-gauge-label">Critical issues</span>
        </div>
      </div>`;
  }

  function cardHead(title, route, linkLabel = "Open →") {
    return `<div class="panel-head-row"><h3>${esc(title)}</h3><button type="button" class="fl-link" data-route="${esc(route)}">${esc(linkLabel)}</button></div>`;
  }

  function homeCerts() {
    const certs = certSummary();
    const missing = certs.total - certs.passed - certs.failed;
    const label = { todo: "Not available", done: "Pass", failed: "Fail", progress: "Checking" };
    const rows = certs.list
      .map((c) => `<li><span class="hm-tone is-${c.verdict}"></span><span class="hm-row-name">${esc(c.name)}</span><span class="hm-row-state is-${c.verdict}">${label[c.verdict] || ""}</span></li>`)
      .join("");
    return `${cardHead("Regulatory certificates", "certifications")}
      <div class="hm-donut-row">
        <div class="hm-donut">${donut([
          { value: certs.passed, color: "#16a34a" },
          { value: certs.failed, color: "#dc2626" },
          { value: missing, color: "#e2e8f0" }
        ])}<span class="hm-donut-value">${certs.passed}/${certs.total}<small>passed</small></span></div>
        <ul class="hm-legend">
          <li><span class="hm-tone is-done"></span>Passed<b>${certs.passed}</b></li>
          <li><span class="hm-tone is-failed"></span>Failed<b>${certs.failed}</b></li>
          <li><span class="hm-tone is-todo"></span>Missing<b>${missing}</b></li>
        </ul>
      </div>
      <ul class="hm-rows">${rows}</ul>`;
  }

  function homeStages() {
    const oemSteps = OEM_STEPS.filter((s) => s.view !== "rca");
    const oemDone = oemSteps.filter((s) => oemStepDone(s.view)).length;
    const rows = STAGES.map((stage) => {
      const s = stageSummary(stage);
      let detail = ENV[stage.env] ? ENV[stage.env].short : "";
      if (stage.template === "fut") detail = `OEM ${oemDone}/${oemSteps.length}`;
      if (stage.template === "approval") detail = "Sign-off";
      return `<li>
        <button type="button" class="hm-stage-row env-${stage.template === "approval" ? "approval" : stage.env}" data-route="${esc(routeOfStage(stage))}">
          <span class="hm-row-name">${esc(stage.name)}</span>
          <span class="hm-row-detail">${esc(detail)}</span>
          ${pill(s.status)}
        </button>
      </li>`;
    }).join("");
    return `${cardHead("Operator stages", "operator")}<ul class="hm-rows hm-stage-list">${rows}</ul>`;
  }

  function renderHome() {
    $("hm-hero").innerHTML = homeHero();
    $("hm-certs").innerHTML = homeCerts();
    $("hm-stages").innerHTML = homeStages();

    $("hm-activity").innerHTML = store.activity.length
      ? `<ul class="hm-feed">${store.activity
          .slice(0, 6)
          .map((a) => `<li><span class="hm-feed-time">${esc(fmtTime(a.at))}</span><span class="hm-tone is-${a.tone}"></span><span>${esc(a.text)}</span></li>`)
          .join("")}</ul>`
      : '<p class="muted">No activity yet. Actions across the pipeline will appear here.</p>';

    const att = attentionItems();
    $("hm-attention").innerHTML = att.length
      ? `<ul class="hm-feed">${att
          .map((a) => `<li>${a.route ? `<button type="button" class="hm-att-link" data-route="${esc(a.route)}">` : "<span>"}<span class="hm-tone is-${a.tone}"></span><span>${esc(a.text)}</span>${a.route ? "</button>" : "</span>"}</li>`)
          .join("")}</ul>`
      : '<p class="muted">Nothing needs attention right now.</p>';
  }

  // ── Operator Testing overview ───────────────────────

  function roundsTable() {
    const rows = store.rounds.map((r) => `<tr>
        <td>Round ${r.no}</td>
        <td>${pill("failed", r.outcome)}</td>
        <td>${r.pass} passed · ${r.fail} failed · ${r.critical} critical</td>
        <td>${esc(fmtDate(r.start))} – ${esc(fmtDate(r.end))}</td>
      </tr>`);
    const t = totals();
    rows.push(`<tr>
        <td>Round ${store.round}</td>
        <td>${pill(operatorStatus(), operatorStatus() === "todo" ? "Not started" : "Current")}</td>
        <td>${t.pass} passed · ${t.fail} failed · ${t.critical} critical</td>
        <td>${esc(fmtDate(store.roundStart || store.cycleStart))} – now</td>
      </tr>`);
    return `<table class="spec-table fl-table">
      <thead><tr><th>Round</th><th>Outcome</th><th>Results</th><th>Dates</th></tr></thead>
      <tbody>${rows.join("")}</tbody>
    </table>`;
  }

  function renderOperator() {
    const done = STAGES.filter((s) => stageSummary(s).status === "done").length;
    const rows = STAGES.map((stage) => {
      const s = stageSummary(stage);
      const progress = hasSubs(stage)
        ? `${s.subsDone}/${s.subsTotal} substages`
        : stage.template === "fut"
          ? "OEM / CSP"
          : stage.template === "approval"
            ? "Decision"
            : "To be defined";
      return `<tr>
        <td><button type="button" class="fl-link" data-route="${esc(routeOfStage(stage))}">${esc(stage.name)}</button>
          <div class="fl-cell-sub">${esc(stage.title)}</div></td>
        <td><span class="fl-env-dot env-${stage.env}"></span>${esc(ENV[stage.env].short)}</td>
        <td>${esc(GATE[stage.gate].label.replace("Gate: ", ""))}</td>
        <td>${esc(progress)}</td>
        <td>${pill(s.status)}</td>
      </tr>`;
    }).join("");

    $("flow-root").innerHTML = `
      ${headPanel({
        title: "Operator Testing · CSP Test Cycle",
        desc: deviceSelected()
          ? `${deviceModel() || deviceLabel()}. Stages run in order; after Functional / Performance the cycle forks into local and global field testing.`
          : "Select a device first. Stages run in order; after Functional / Performance the cycle forks into local and global field testing.",
        status: operatorStatus(),
        side: progressSide(`${done} of ${STAGES.length} stages passed`, done, STAGES.length)
      })}
      <section class="panel fl-section">
        <div class="panel-head-row"><h3>Cycle progress</h3></div>
        ${cycleDiagram()}
      </section>
      <section class="panel fl-section">
        <div class="panel-head-row"><h3>Stages</h3></div>
        <table class="spec-table fl-table">
          <thead><tr><th>Stage</th><th>Where</th><th>Gate policy</th><th>Progress</th><th>Status</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </section>
      <section class="panel fl-section">
        <div class="panel-head-row"><h3>Submission rounds</h3></div>
        ${roundsTable()}
      </section>`;
  }

  // ── FUT ─────────────────────────────────────────────

  function renderCsp() {
    $("flow-root").innerHTML = `
      ${headPanel({ title: "FUT · CSP", desc: "Friendly user trial run by the operator.", status: "todo", statusLabel: "Coming soon" })}
      <section class="panel fl-empty">
        <h3>The CSP trial flow will live here</h3>
        <p>Participants, issue inbox, trial health and the Needs-fix hand-off to the OEM will be added once the CSP flow is defined.</p>
        <button type="button" class="secondary" data-route="fut-oem">Open the OEM flow →</button>
      </section>`;
  }

  // ── Approval ────────────────────────────────────────

  function renderApproval() {
    const certs = certSummary();
    const t = totals();
    const checks = [
      { label: "Device selected", status: deviceSelected() ? "done" : "todo", detail: deviceSelected() ? deviceLabel() : "Not selected", route: "device-selection" },
      { label: "Regulatory Certifications", status: certs.status, detail: `${certs.passed}/${certs.total} passed`, route: "certifications" },
      ...STAGES.filter((s) => s.template !== "approval").map((stage) => {
        const s = stageSummary(stage);
        return {
          label: stage.name,
          status: s.status,
          detail: hasSubs(stage) ? `${s.subsDone}/${s.subsTotal} substages · ${s.critical} critical` : STATUS[s.status].label,
          route: routeOfStage(stage)
        };
      })
    ];
    const ready = checks.every((c) => c.status === "done") && !t.critical;
    const a = store.approval;

    $("flow-root").innerHTML = `
      ${headPanel({
        title: "Approval",
        desc: "Final sign-off for the device, based on the results of every stage.",
        status: a ? (a.decision === "approved" ? "done" : "failed") : "todo",
        statusLabel: a ? (a.decision === "approved" ? "Approved" : "Rejected") : "Awaiting decision",
        side: progressSide(`${checks.filter((c) => c.status === "done").length} of ${checks.length} checks passed`, checks.filter((c) => c.status === "done").length, checks.length)
      })}
      <div class="fl-approval-grid">
        <section class="panel fl-section">
          <div class="panel-head-row"><h3>Readiness</h3></div>
          <div class="fl-check-list">
            ${checks.map((c) => `<button type="button" class="fl-check-row" data-route="${esc(c.route)}">
                ${dot(c.status)}<span class="fl-check-label">${esc(c.label)}</span>
                <span class="fl-check-detail">${esc(c.detail)}</span>
              </button>`).join("")}
          </div>
        </section>
        <section class="panel fl-section">
          <div class="panel-head-row"><h3>Decision</h3></div>
          ${a
            ? `<div class="callout ${a.decision === "approved" ? "success" : "warn"}">
                ${a.decision === "approved" ? "Device approved" : "Device rejected"} on ${esc(fmtTime(a.at))}.
                ${a.note ? `<div class="fl-note">${esc(a.note)}</div>` : ""}
              </div>
              <div class="btn-row"><button type="button" class="secondary" data-approval="clear">Clear decision</button></div>`
            : `${ready ? "" : '<div class="callout warn">Some checks have not passed yet. For this proof of concept you can still record a decision.</div>'}
              <div class="field fl-field-wide">
                <label for="fl-approval-note">Note</label>
                <textarea id="fl-approval-note" class="input" rows="3" placeholder="Reason or conditions for the decision"></textarea>
              </div>
              <div class="btn-row">
                <button type="button" class="soft-danger" data-approval="rejected">Reject device</button>
                <button type="button" class="primary" data-approval="approved">Approve device</button>
              </div>`}
        </section>
      </div>`;
  }

  // ── Reports ─────────────────────────────────────────

  function renderReports(section) {
    const root = $("reports-root");
    if (!root) return;
    const tabs = REPORT_SECTIONS.map(
      (s) => `<button type="button" class="tex-tab ${s.id === section ? "is-active" : ""}" data-route="reports:${s.id}">${esc(s.label)}</button>`
    ).join("");

    let body = "";
    if (section === "certification") body = reportCertification();
    else if (section === "stages") body = reportStages();
    else if (section === "rounds") body = `<section class="panel fl-section">${roundsTable()}</section>`;
    else body = reportConsolidated();

    root.innerHTML = `
      <section class="panel fl-head">
        <div class="fl-head-main">
          <div class="fl-title-row"><h2 class="fl-title">Reports</h2></div>
          <p class="fl-desc">${esc(deviceSelected() ? deviceModel() || deviceLabel() : "No device selected")}</p>
          <div class="rp-tabs">${tabs}</div>
        </div>
        <div class="fl-head-side"><button type="button" class="secondary" id="rp-export">Export JSON</button></div>
      </section>
      ${body}`;
  }

  function reportConsolidated() {
    const certs = certSummary();
    const t = totals();
    const rate = t.pass + t.fail ? `${Math.round((t.pass / (t.pass + t.fail)) * 100)}%` : "—";
    const rows = [
      `<tr><td>Device Selection</td><td>${pill(deviceSelected() ? "done" : "todo", deviceSelected() ? "Selected" : "Pending")}</td><td colspan="4">${esc(deviceSelected() ? deviceLabel() : "—")}</td></tr>`,
      `<tr><td>Regulatory Certifications</td><td>${pill(certs.status)}</td><td>${certs.passed}</td><td>${certs.failed}</td><td>${certs.total - certs.passed - certs.failed}</td><td>—</td></tr>`,
      ...STAGES.map((stage) => {
        const s = stageSummary(stage);
        if (hasSubs(stage)) {
          return `<tr><td>${esc(stage.name)}</td><td>${pill(s.status)}</td><td>${s.pass}</td><td>${s.fail}</td><td>${s.pending}</td><td>${s.critical}</td></tr>`;
        }
        let note = "Substages not defined yet";
        if (stage.template === "fut") {
          const steps = OEM_STEPS.filter((st) => st.view !== "rca");
          note = `OEM ${steps.filter((st) => oemStepDone(st.view)).length} of ${steps.length} steps done`;
        }
        if (stage.template === "approval") note = store.approval ? `Decision: ${store.approval.decision}` : "Awaiting decision";
        return `<tr><td>${esc(stage.name)}</td><td>${pill(s.status)}</td><td colspan="4">${esc(note)}</td></tr>`;
      })
    ].join("");
    return `
      <div class="home-metrics hm-kpis">
        ${kpiCard("Overall", STATUS[operatorStatus()].label, "Operator testing")}
        ${kpiCard("Certificates", `${certs.passed}/${certs.total}`, "Passed")}
        ${kpiCard("Pass rate", rate, `${t.pass} passed · ${t.fail} failed`)}
        ${kpiCard("Critical issues", String(t.critical), "Open in this round", t.critical ? "is-bad" : "")}
      </div>
      <section class="panel fl-section">
        <div class="panel-head-row"><h3>Pipeline summary</h3></div>
        <table class="spec-table fl-table">
          <thead><tr><th>Item</th><th>Status</th><th>Passed</th><th>Failed</th><th>Pending</th><th>Critical</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </section>`;
  }

  function reportCertification() {
    const list = certApi.summary();
    const rows = list.map((c) => `<tr>
        <td>${esc(c.name)}</td>
        <td>${esc(c.file || "—")}</td>
        <td>${esc(c.issuer || "—")}</td>
        <td>${esc(c.certId || "—")}</td>
        <td>${esc(c.expires || "—")}</td>
        <td>${pill(c.verdict)}</td>
        <td>${esc((c.failedRules || []).join("; ") || "—")}</td>
      </tr>`).join("");
    return `<section class="panel fl-section">
      <table class="spec-table fl-table">
        <thead><tr><th>Certificate</th><th>File</th><th>Issuer</th><th>Certificate ID</th><th>Expiry</th><th>Verdict</th><th>Failed rules</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </section>`;
  }

  function reportStages() {
    const defined = STAGES.filter(hasSubs);
    if (!defined.length) {
      return '<section class="panel fl-section"><p class="muted">Stage substages have not been defined yet. Results per substage will appear here.</p></section>';
    }
    return defined.map((stage) => {
      const rows = stage.substages.map((sub) => {
        const c = substageCounts(stage, sub);
        return `<tr>
          <td><button type="button" class="fl-link" data-route="stage:${stage.id}:${sub.id}">${esc(sub.name)}</button></td>
          <td>${c.pass}</td><td>${c.fail}</td><td>${c.skip}</td><td>${c.pending}</td><td>${c.critical}</td>
          <td>${pill(statusFromCounts(c))}</td>
        </tr>`;
      }).join("");
      return `<section class="panel fl-section">
        <div class="panel-head-row"><h3>${esc(stage.name)} · ${esc(stage.title)}</h3>${pill(stageSummary(stage).status)}</div>
        <table class="spec-table fl-table">
          <thead><tr><th>Substage</th><th>Passed</th><th>Failed</th><th>Skipped</th><th>Pending</th><th>Critical</th><th>Status</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </section>`;
    }).join("");
  }

  function exportReport() {
    const data = {
      generatedAt: new Date().toISOString(),
      device: { type: deviceLabel(), model: deviceModel() },
      round: store.round,
      certificates: certApi.summary(),
      stages: STAGES.map((stage) => ({
        id: stage.id,
        name: stage.name,
        status: stageSummary(stage).status,
        substages: (stage.substages || []).map((sub) => ({
          id: sub.id,
          name: sub.name,
          status: statusFromCounts(substageCounts(stage, sub)),
          items: itemsOf(sub).map((item, i) => ({ name: item.name, ...(result(resultKey(stage.id, sub.id, i)) || {}) }))
        }))
      })),
      approval: store.approval,
      rounds: store.rounds
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `csp_cycle_report_round${store.round}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ── Events ──────────────────────────────────────────

  document.addEventListener("click", (e) => {
    const toggle = e.target.closest("[data-nav-toggle]");
    if (toggle) {
      const key = toggle.dataset.navToggle;
      store.navOpen[key] = !isOpen(key);
      renderSidebar();
      return;
    }
    const routeEl = e.target.closest("[data-route]");
    if (routeEl && !routeEl.disabled) {
      navigate(routeEl.dataset.route);
      return;
    }
    const appr = e.target.closest("[data-approval]");
    if (appr) {
      const v = appr.dataset.approval;
      if (v === "clear") store.approval = null;
      else {
        store.approval = { decision: v, note: ($("fl-approval-note")?.value || "").trim(), at: new Date() };
        log(`Device ${v}.`, v === "approved" ? "pass" : "fail");
      }
      renderCurrent();
      return;
    }
    if (e.target.closest("#rp-export")) exportReport();
  });

  document.addEventListener("workbench:view", (e) => {
    const view = e.detail.view;
    if (viewForRoute(store.route) !== view) store.route = routeForView(view) || store.route;
    renderCurrent();
  });

  document.addEventListener("workbench:device", (e) => {
    if (e.detail && e.detail.deviceType) {
      if (!store.cycleStart) {
        store.cycleStart = new Date();
        store.roundStart = store.cycleStart;
      }
      log(`Device selected: ${deviceLabel()}.`, "info");
    }
    renderSidebar();
  });

  window.pipeline = {
    FLOW,
    STAGES,
    ENV,
    GATE,
    STATUS,
    store,
    renderers,
    stageSections,
    certApi,
    esc,
    svg,
    dot,
    pill,
    log,
    navigate,
    refresh: renderCurrent,
    renderSidebar,
    headPanel,
    progressSide,
    resultKey,
    result,
    setResult,
    itemsOf,
    hasSubs,
    substageCounts,
    statusFromCounts,
    stageSummary,
    routeOfStage,
    startNewRound,
    deviceModel,
    deviceSelected
  };

  document.addEventListener("DOMContentLoaded", () => {
    renderSidebar();
    renderBreadcrumb();
  });
})();
