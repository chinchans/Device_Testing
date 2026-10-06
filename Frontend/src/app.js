(() => {
  "use strict";

  const state = {
    deviceType: "",
    testArea: "",
    productSpec: null,
    testSuite: null,
    documentId: null,
    featureChecklist: null,
    features: [],
    selectedFeatureId: null,
    categoryFilter: "all",
    extracting: false,
    extractionRegistered: false,
    bulkRunning: false,
    pendingManualFeatureId: null,
    pendingSemiFeatureId: null,
    deviceClassification: {
      category: "",
      os: "",
      manufacturer: "",
      model: "",
      storage: "",
      cpu: "",
      ram: ""
    },
    tcSelectedFeatureId: null,
    tcSelectedCategoryId: null,
    tcSelectedCaseId: null,
    tsgOpenFeatureId: null,
    tsgOpenCategoryId: null,
    /** Test case ids ticked on the Test Script Generation page. */
    tsgSelectedIds: new Set(),
    tsgGenerating: false,
    /** Responses of POST /api/test-scripts/generate (one per feature). */
    tsgResults: [],
    tsgActiveFile: "",
    tsgShowDetails: false,
    /** featureId → { categories: { functionality: [...], ... } } */
    tcCatalogs: {},
    /** Empty until user clicks Framework Selection (then ADB/Appium/UiAutomator2). */
    selectedFrameworks: [],
    frameworksConfirmed: false
  };

  const RECOMMENDED_FRAMEWORKS = ["adb", "appium", "uiautomator2"];

  const FRAMEWORKS = [
    {
      id: "adb",
      name: "ADB",
      desc: "Device/system-level automation",
      recommended: true
    },
    {
      id: "appium",
      name: "Appium",
      desc: "Cross-platform UI automation",
      recommended: true
    },
    {
      id: "uiautomator2",
      name: "UI Automator / UiAutomator2",
      desc: "Android system UI automation",
      recommended: true
    },
    {
      id: "espresso",
      name: "Espresso",
      desc: "Native Android application UI testing",
      recommended: false
    },
    {
      id: "mobly",
      name: "Mobly",
      desc: "Device/connectivity-oriented testing",
      recommended: false
    },
    {
      id: "maestro",
      name: "Maestro",
      desc: "Simple UI workflow automation",
      recommended: false
    }
  ];

  const TC_CATEGORIES = [
    {
      id: "functionality",
      name: "Functionality",
      blurb: "Validate core capability behavior against the specification."
    },
    {
      id: "performance",
      name: "Performance",
      blurb: "Measure speed, latency, throughput, and resource use."
    },
    {
      id: "reliability",
      name: "Reliability",
      blurb: "Stability, recovery, and repeatability under stress."
    },
    {
      id: "security",
      name: "Security",
      blurb: "Permissions, privacy, and abuse / hardening checks."
    }
  ];

  const MOCK_FEATURES = {
    /* Reserved for later demo seeding only — Extract Features must NOT invent these.
       Real cards will come from Agentic RAG over the uploaded Product Spec / Test Suite. */
    mobile: [],
    laptop: [],
    tablet: [],
    wearable: []
  };

  const STATUS = {
    EXTRACTED: "extracted",
    NOT_FOUND: "not_found",
    GENERATING: "generating",
    SCRIPTS_READY: "scripts_ready",
    EXECUTING: "executing",
    SCORED: "scored",
    FAILED: "failed"
  };

  // ── DOM helpers ─────────────────────────────────────

  const $ = (id) => document.getElementById(id);

  function showScreen(id) {
    document.querySelectorAll(".screen").forEach((el) => el.classList.remove("active"));
    $(id).classList.add("active");
  }

  function showView(view) {
    const target = $(`view-${view}`);
    if (!target) return;
    document.querySelectorAll(".view").forEach((el) => el.classList.remove("active"));
    document.querySelectorAll(".nav-item[data-view]").forEach((el) => el.classList.remove("active"));
    target.classList.add("active");
    const nav = document.querySelector(`.nav-item[data-view="${view}"]`);
    if (nav) nav.classList.add("active");
    if (view === "test-case-generation") {
      renderTestCaseGeneration();
    }
    if (view === "framework-selection") {
      renderFrameworkSelection();
    }
    if (view === "test-script-generation") {
      renderTestScriptGeneration();
    }
    document.dispatchEvent(new CustomEvent("workbench:view", { detail: { view } }));
  }

  function openModal(id) {
    $(id).classList.remove("hidden");
  }

  function closeModal(id) {
    $(id).classList.add("hidden");
  }

  function setPill(el, text, cls) {
    if (!el) return;
    el.textContent = text;
    el.className = "status-pill" + (cls ? ` ${cls}` : "");
  }

  function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function modeClass(mode) {
    if (mode === "automated") return "is-auto";
    if (mode === "semi") return "is-semi";
    return "is-manual";
  }

  function modeLabel(mode) {
    if (mode === "automated") return "Automated";
    if (mode === "semi") return "Semi-automated";
    return "Manual";
  }

  function statusLabel(status) {
    const map = {
      [STATUS.EXTRACTED]: "Found",
      [STATUS.NOT_FOUND]: "Not in spec",
      [STATUS.GENERATING]: "Generating",
      [STATUS.SCRIPTS_READY]: "Scripts ready",
      [STATUS.EXECUTING]: "Executing",
      [STATUS.SCORED]: "Scored",
      [STATUS.FAILED]: "Failed"
    };
    return map[status] || status;
  }

  function statusClass(status) {
    if (status === STATUS.SCRIPTS_READY || status === STATUS.EXTRACTED) return "is-ready";
    if (status === STATUS.NOT_FOUND) return "is-missing";
    if (status === STATUS.GENERATING || status === STATUS.EXECUTING) return "is-running";
    if (status === STATUS.SCORED) return "is-success";
    if (status === STATUS.FAILED) return "is-failed";
    return "";
  }

  function isFeatureActionable(feature) {
    return Boolean(feature && feature.found !== false && feature.status !== STATUS.NOT_FOUND);
  }

  // Non-testable marketing / TOC / footnote sections — hide in UI (frontend gate).
  // Stand-in until a dedicated testability LLM endpoint exists; backend unchanged.
  const NON_TESTABLE_FEATURE_RE = new RegExp(
    [
      "^design$",
      "physical\\s*specifications?",
      "services?\\s*(and|&)\\s*applications?",
      "software\\s*support",
      "document\\s*root",
      "general\\s*information",
      "^overview$",
      "^introduction$",
      "^about$",
      "^warranty$",
      "^legal$",
      "^disclaimer",
      "^contents?$",
      "table\\s*of\\s*contents",
      "^toc$",
      "^summary$",
      "^price$",
      "^pricing$",
      "^reviews?$",
      "buy\\s*now",
      "^compare$",
      "manufactured\\s*by",
      "^support$",
      "^contact$",
      "product\\s*name",
      "model\\s*name",
      "launch\\s*date",
      "^announced$",
      "^availability$",
      "additional\\s*information",
      "^notes?$",
      "important\\s*notes?",
      "^footnote",
      "^appearance$",
      "^colors?$",
      "form\\s*factor",
      "^dimensions?$",
      "^weight$",
      "^packaging$",
      "^accessories$"
    ].join("|"),
    "i"
  );

  // Capability domains that are typically device-testable (standard or additional).
  const TESTABLE_DOMAIN_RE = new RegExp(
    [
      "wi-?fi",
      "wlan",
      "bluetooth",
      "nfc",
      "cellular",
      "network",
      "sim",
      "5g",
      "4g",
      "lte",
      "camera",
      "display",
      "screen",
      "battery",
      "charging",
      "processor",
      "chipset",
      "cpu",
      "gpu",
      "memory",
      "ram",
      "storage",
      "audio",
      "speaker",
      "microphone",
      "sensor",
      "gps",
      "location",
      "biometric",
      "fingerprint",
      "face\\s*unlock",
      "usb",
      "port",
      "connectivity",
      "wireless",
      "os\\b",
      "operating\\s*system",
      "android",
      "kernel",
      "driver",
      "touch",
      "haptic",
      "thermal",
      "power"
    ].join("|"),
    "i"
  );

  // Former default checklist items — hide even if returned as extras.
  const HIDDEN_FEATURE_RE = new RegExp(
    [
      "operating\\s*system",
      "^os$",
      "throughput",
      "processor(\\s*(&|and)?\\s*performance)?",
      "memory(\\s*(&|and)?\\s*storage)?",
      "storage(\\s*(&|and)?\\s*ram)?",
      "^capacity$",
      "^chipset$"
    ].join("|"),
    "i"
  );

  function isHiddenFeatureName(name) {
    const n = String(name || "").trim();
    if (!n) return true;
    return HIDDEN_FEATURE_RE.test(n);
  }

  function isNonTestableName(name) {
    const n = String(name || "").trim();
    if (!n) return true;
    if (isHiddenFeatureName(n)) return true;
    return NON_TESTABLE_FEATURE_RE.test(n);
  }

  function looksTestableByDomain(feature) {
    const blob = [
      feature.name,
      feature.capability,
      ...(feature.sourceNames || []),
      ...((feature.parameters || []).map((p) => `${p.name} ${p.value}`))
    ]
      .join(" ")
      .toLowerCase();
    return TESTABLE_DOMAIN_RE.test(blob);
  }

  /**
   * Frontend-only testability gate: keep standard/additional features that can
   * reasonably be validated on-device; drop Design / Physical / Soft-support style rows.
   * Also drop retired defaults (Processor, Memory & Storage, OS, Throughput).
   */
  function isTestableFeature(feature) {
    if (!feature) return false;
    if (isHiddenFeatureName(feature.name)) return false;
    if (isNonTestableName(feature.name)) return false;
    const sources = feature.sourceNames || [];
    if (sources.length && sources.every((s) => isNonTestableName(s)) && feature.kind !== "standard") {
      return false;
    }
    // Taxonomy standards are treated as testable when not name-blocked.
    if (feature.kind === "standard") return true;
    // Extras: must look like a device capability domain.
    return looksTestableByDomain(feature);
  }

  function keepTestableFeatures(features) {
    return (features || []).filter(isTestableFeature);
  }

  // ── Setup readiness / panes ─────────────────────────

  const TEST_AREA_LABELS = {
    operator_testing: "Operator Testing",
    module_peripheral: "Module / Peripheral Testing",
    protocol_testing: "Protocol Testing",
    security_testing: "Security Testing",
    connectivity_testing: "Connectivity Testing"
  };

  function updateSetupPanes() {
    const areaBlock = $("test-area-block");
    if (!areaBlock) return;
    areaBlock.classList.toggle("hidden", !state.deviceType);
  }

  function updateExtractedFeaturesVisibility() {
    const section = $("extracted-features-section");
    if (!section) return;
    section.classList.toggle("hidden", !state.extractionRegistered);
  }

  function updateSetupReadiness() {
    const deviceOk = Boolean(state.deviceType);
    const areaOk = Boolean(state.testArea);
    const specOk = Boolean(state.productSpec);
    const suiteOk = Boolean(state.testSuite);

    setPill($("device-status-pill"), deviceOk ? "Selected" : "Required", deviceOk ? "is-ready" : "");
    $("device-type-select")?.classList.toggle("is-ready", deviceOk);

    $("source-chip-spec")?.classList.toggle("is-on", specOk);
    $("source-chip-spec")?.classList.toggle("is-off", !specOk);
    $("source-chip-suite")?.classList.toggle("is-on", suiteOk);
    $("source-chip-suite")?.classList.toggle("is-off", !suiteOk);

    const hint = $("extract-hint");
    if (hint) {
      if (specOk && suiteOk) {
        hint.textContent = "Both documents attached. Ready to extract.";
      } else if (specOk) {
        hint.textContent = "Product specification attached. Ready to extract.";
      } else if (suiteOk) {
        hint.textContent = "Product specification is still required.";
      } else if (!deviceOk) {
        hint.textContent = "Select a device type on Device Selection to continue.";
      } else if (!areaOk) {
        hint.textContent = "Select a test focus on Device Selection to continue.";
      } else {
        hint.textContent = "Upload a product specification to continue.";
      }
    }

    const extractBtn = $("extract-features-btn");
    if (extractBtn) {
      extractBtn.disabled = !(deviceOk && areaOk && specOk) || state.extracting;
    }

    $("ds-actions-row")?.classList.toggle("hidden", !deviceOk);
    $("ds-next-nav")?.classList.toggle("hidden", !deviceOk);

    updateTestAreaNav();
    updateSetupPanes();
    updateExtractedFeaturesVisibility();
    updateHomeStats();
  }

  async function pickDocument(kind) {
    let file = null;
    if (window.deviceTestingAPI && window.deviceTestingAPI.openFileDialog) {
      file = await window.deviceTestingAPI.openFileDialog({
        title: kind === "spec" ? "Select product specification" : "Select test suite document",
        filters: [
          { name: "PDF", extensions: ["pdf"] },
          { name: "All Files", extensions: ["*"] }
        ]
      });
    }

    // No fake upload on cancel — user must actually pick a file
    if (!file) return;

    // Extensionless downloads are still PDFs — normalize name for the API
    if (file.name && !/\.[a-z0-9]+$/i.test(file.name)) {
      file = { ...file, name: `${file.name}.pdf` };
    }

    if (kind === "spec") {
      state.productSpec = file;
      state.extractionRegistered = false;
      $("extract-pending-callout")?.classList.add("hidden");
      $("spec-file-name").textContent = file.name;
      $("spec-file-name").classList.remove("hidden");
      $("spec-upload-zone").classList.add("has-file");
      setPill($("spec-pill"), "Uploaded", "is-success");
    } else {
      state.testSuite = file;
      $("suite-file-name").textContent = file.name;
      $("suite-file-name").classList.remove("hidden");
      $("suite-upload-zone").classList.add("has-file");
      setPill($("suite-pill"), "Uploaded", "is-success");
    }
    updateSetupReadiness();
  }

  function selectTestArea(area) {
    if (!area || !TEST_AREA_LABELS[area]) return;
    state.testArea = area;
    document.querySelectorAll(".test-area-option").forEach((el) => {
      el.classList.toggle("is-selected", el.dataset.area === area);
    });
    const deviceLabel = $("device-type-select")?.selectedOptions[0]?.text || state.deviceType;
    $("shell-context").textContent = `${deviceLabel} · ${TEST_AREA_LABELS[area]}`;
    updateSetupReadiness();
    if (area === "operator_testing") document.dispatchEvent(new CustomEvent("operator:home"));
    showView(testAreaStartView());
  }

  /** Operator Testing has its own page; every other focus starts at Device Inventory. */
  function testAreaStartView() {
    return state.testArea === "operator_testing" ? "operator-testing" : "feature-extraction";
  }

  function updateTestAreaNav() {
    const operator = state.testArea === "operator_testing";
    $("nav-operator-testing")?.classList.toggle("hidden", !operator);
    const next = $("goto-feature-extraction-btn");
    if (next) {
      const label = operator ? "Go to Operator Testing" : "Go to Device Inventory";
      next.title = label;
      next.setAttribute("aria-label", label);
    }
  }

  function resetSetup() {
    state.deviceType = "";
    state.testArea = "";
    state.productSpec = null;
    state.testSuite = null;
    state.features = [];
    state.selectedFeatureId = null;
    state.categoryFilter = "all";
    state.extractionRegistered = false;
    state.selectedFrameworks = [];
    state.frameworksConfirmed = false;
    state.tcSelectedFeatureId = null;
    state.tcSelectedCategoryId = null;
    state.tcSelectedCaseId = null;
    resetTestScriptSelection();

    $("device-type-select").value = "";
    $("spec-file-name")?.classList.add("hidden");
    $("suite-file-name")?.classList.add("hidden");
    $("spec-upload-zone")?.classList.remove("has-file");
    $("suite-upload-zone")?.classList.remove("has-file");
    setPill($("spec-pill"), "Not uploaded", "");
    setPill($("suite-pill"), "Optional", "");
    setPill($("workspace-status-pill"), "Idle", "");
    $("project-score-chip").textContent = "Score —";
    $("shell-context").textContent = "Bring-up to Release Validation";
    $("extract-pending-callout")?.classList.add("hidden");
    document.querySelectorAll(".test-area-option").forEach((el) => el.classList.remove("is-selected"));
    clearDeviceClassificationFields();
    updateSetupReadiness();
    updateHomeStats();
    showView("device-selection");
  }

  const DC_PARAM_ROWS = [
    { key: "category", label: "Device category" },
    { key: "os", label: "OS" },
    { key: "manufacturer", label: "Manufacturer" },
    { key: "model", label: "Model" },
    { key: "storage", label: "Storage" },
    { key: "cpu", label: "CPU" },
    { key: "ram", label: "RAM" }
  ];

  const DC_CATEGORY_LABELS = {
    mobile: "Mobile",
    laptop: "Laptop",
    tablet: "Tablet",
    wearable: "Wearable"
  };

  function dcDisplayValue(key, value) {
    const raw = String(value || "").trim();
    if (!raw) return "Not identified";
    if (key === "category") return DC_CATEGORY_LABELS[raw] || raw;
    return raw;
  }

  function renderDeviceClassificationTable() {
    const tbody = $("dc-spec-body");
    if (!tbody) return;
    const profile = state.deviceClassification || {};
    tbody.innerHTML = DC_PARAM_ROWS.map(({ key, label }) => {
      const display = dcDisplayValue(key, profile[key]);
      const missing = display === "Not identified";
      return `<tr>
        <td>${escapeHtml(label)}</td>
        <td class="${missing ? "is-missing-value" : ""}">${escapeHtml(display)}</td>
      </tr>`;
    }).join("");
  }

  function updateDeviceClassificationStatus() {
    const profile = state.deviceClassification || {};
    const filled = DC_PARAM_ROWS.filter(({ key }) => Boolean(String(profile[key] || "").trim())).length;
    const pill = $("dc-status-pill");
    if (!state.extractionRegistered) {
      setPill(pill, "Awaiting extract", "");
      return;
    }
    if (filled === DC_PARAM_ROWS.length) {
      setPill(pill, "Complete", "is-ready");
    } else if (filled > 0) {
      setPill(pill, `${filled}/${DC_PARAM_ROWS.length} identified`, "is-ready");
    } else {
      setPill(pill, "Not identified", "is-missing");
    }
  }

  function clearDeviceClassificationFields() {
    state.deviceClassification = {
      category: "",
      os: "",
      manufacturer: "",
      model: "",
      storage: "",
      cpu: "",
      ram: ""
    };
    renderDeviceClassificationTable();
    const intro = $("dc-intro");
    if (intro) {
      intro.textContent =
        "Values are filled from the extracted product specification after Feature Extraction.";
    }
    updateDeviceClassificationStatus();
  }

  function collectSpecRowsFromExtract(data) {
    const rows = [];
    const push = (name, value) => {
      const n = String(name || "").trim();
      const v = String(value ?? "").trim();
      if (!n || !v) return;
      rows.push({ name: n, value: v, nameL: n.toLowerCase() });
    };

    for (const f of data.features || []) {
      for (const p of f.parameters || []) {
        push(p.name, p.value);
      }
    }

    const extraction = data.extraction || {};
    for (const f of extraction.features || []) {
      for (const s of f.specifications || []) {
        const raw = s.value == null ? "" : String(s.value);
        const val = s.unit ? `${raw} ${s.unit}`.trim() : raw;
        push(s.parameter, val);
      }
    }

    return rows;
  }

  function brandFromText(text) {
    const t = String(text || "");
    const known = [
      "Samsung",
      "Apple",
      "Google",
      "Xiaomi",
      "OnePlus",
      "OPPO",
      "Vivo",
      "realme",
      "Motorola",
      "Nokia",
      "Sony",
      "Huawei",
      "Honor",
      "Nothing",
      "ASUS",
      "Lenovo",
      "HP",
      "Dell",
      "Microsoft",
      "LG",
      "Tecno",
      "Infinix"
    ];
    for (const brand of known) {
      if (new RegExp(`\\b${brand.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i").test(t)) {
        return brand === "realme" ? "realme" : brand;
      }
    }
    const first = t.match(/^([A-Za-z][A-Za-z0-9+.-]*)/);
    return first ? first[1] : "";
  }

  function withUnit(value) {
    const v = String(value || "").trim();
    if (!v) return "";
    if (/\b(gb|tb|mb|ghz|mhz)\b/i.test(v)) return v;
    if (/^\d+(\.\d+)?$/.test(v)) return `${v} GB`;
    return v;
  }

  function pickBestSpec(rows, scoreFn) {
    let best = null;
    let bestScore = 0;
    for (const row of rows) {
      const score = scoreFn(row);
      if (score > bestScore) {
        bestScore = score;
        best = row;
      }
    }
    return bestScore > 0 ? best : null;
  }

  function deriveDeviceClassification(data) {
    const rows = collectSpecRowsFromExtract(data);
    const productName = String(data.product_name || "").trim();
    const productType = String(data.product_type || "").trim().toLowerCase();
    const deviceType = String(data.device_type || state.deviceType || "").trim().toLowerCase();

    const osRow = pickBestSpec(rows, (row) => {
      const n = row.nameL;
      if (/^os$/.test(n) || n === "operating system") return 100;
      if (/\bos\s*version\b/.test(n) || /\bandroid\s*version\b/.test(n)) return 90;
      if (/\boperating\s*system\b/.test(n) || /\bos\b/.test(n)) return 70;
      if (/\bandroid\b|\bios\b|\bharmonyos\b|\bone\s*ui\b/.test(n)) return 50;
      return 0;
    });

    const mfrRow = pickBestSpec(rows, (row) => {
      const n = row.nameL;
      if (/manufactured\s*by|manufacturer/.test(n)) return 100;
      if (/\bbrand\b/.test(n) || /\boe\s*m\b/.test(n)) return 80;
      return 0;
    });

    const modelRow = pickBestSpec(rows, (row) => {
      const n = row.nameL;
      if (/^model(\s*name)?$/.test(n) || n === "product name" || n === "device name") return 100;
      if (/\bmodel\s*(name|number|no\.?)\b/.test(n)) return 85;
      if (/\bmodel\b/.test(n) && !/form\s*factor/.test(n)) return 60;
      return 0;
    });

    const ramRow = pickBestSpec(rows, (row) => {
      const n = row.nameL;
      if (/storage\s*memory/.test(n)) return 100; // Samsung naming: RAM
      if (/\bram\b/.test(n) && !/program/.test(n)) return 95;
      if (/^memory$/.test(n) || n === "system memory") return 70;
      return 0;
    });

    const storageRow = pickBestSpec(rows, (row) => {
      const n = row.nameL;
      if (/storage\s*memory|available\s*storage|expandable|microsd|micro\s*sd/.test(n)) return 0;
      if (/^storage(\s*\(gb\))?$/.test(n) || n === "internal storage" || n === "rom") return 100;
      if (/\bstorage\b/.test(n) && !/\bmemory\b/.test(n)) return 80;
      if (/\brom\b/.test(n)) return 70;
      return 0;
    });

    const chipsetRow = pickBestSpec(rows, (row) => {
      const n = row.nameL;
      const v = row.value.toLowerCase();
      if (/\bchipset\b|\bsoc\b|\bprocessor\s*name\b/.test(n)) return 100;
      if (/snapdragon|dimensity|exynos|tensor|mediatek|helio|apple\s*a\d/.test(v)) return 90;
      if (/processor/.test(n) && /type|name|model/.test(n)) return 75;
      return 0;
    });

    const cpuType = pickBestSpec(rows, (row) => {
      const n = row.nameL;
      if (/cpu\s*type|processor\s*cpu\s*type/.test(n)) return 80;
      if (/^cpu$/.test(n)) return 60;
      return 0;
    });
    const cpuSpeed = pickBestSpec(rows, (row) => {
      const n = row.nameL;
      if (/cpu\s*speed|processor\s*cpu\s*speed|clock/.test(n)) return 80;
      return 0;
    });

    let cpu = "";
    if (chipsetRow) {
      cpu = chipsetRow.value;
      if (cpuSpeed && !/ghz|mhz/i.test(cpu)) {
        cpu = `${cpu} (${cpuSpeed.value})`;
      }
    } else if (cpuType && cpuSpeed) {
      cpu = `${cpuType.value}, ${cpuSpeed.value}`;
    } else if (cpuType) {
      cpu = cpuType.value;
    } else if (cpuSpeed) {
      cpu = cpuSpeed.value;
    }

    let manufacturer = "";
    if (mfrRow) manufacturer = brandFromText(mfrRow.value) || mfrRow.value.split(/[.,]/)[0].trim();
    if (!manufacturer && productName) manufacturer = brandFromText(productName);

    let model = productName;
    if (modelRow) model = modelRow.value;
    if (!model && data.document_name) {
      model = String(data.document_name)
        .replace(/\.pdf$/i, "")
        .replace(/[_-]+/g, " ")
        .trim();
    }

    let category = deviceType;
    if (!category && productType) {
      if (/phone|mobile|smartphone/.test(productType)) category = "mobile";
      else if (/tablet/.test(productType)) category = "tablet";
      else if (/laptop|notebook/.test(productType)) category = "laptop";
      else if (/watch|wearable/.test(productType)) category = "wearable";
    }
    if (!category) category = "mobile";

    return {
      category,
      os: osRow ? osRow.value : "",
      manufacturer,
      model,
      storage: storageRow ? withUnit(storageRow.value) : "",
      cpu,
      ram: ramRow ? withUnit(ramRow.value) : ""
    };
  }

  function applyDeviceClassification(profile) {
    const allowed = ["mobile", "laptop", "tablet", "wearable"];
    state.deviceClassification = {
      category: allowed.includes(profile.category) ? profile.category : "",
      os: profile.os || "",
      manufacturer: profile.manufacturer || "",
      model: profile.model || "",
      storage: profile.storage || "",
      cpu: profile.cpu || "",
      ram: profile.ram || ""
    };
    renderDeviceClassificationTable();

    const intro = $("dc-intro");
    if (intro) {
      const bits = [];
      if (profile.manufacturer && profile.model) {
        const modelHasBrand = String(profile.model)
          .toLowerCase()
          .startsWith(String(profile.manufacturer).toLowerCase());
        bits.push(modelHasBrand ? profile.model : `${profile.manufacturer} ${profile.model}`);
      } else if (profile.model) {
        bits.push(profile.model);
      } else if (profile.manufacturer) {
        bits.push(profile.manufacturer);
      }
      intro.textContent = bits.length
        ? `Extracted from product specification · ${bits.join(" · ")}.`
        : "Values are filled from the extracted product specification after Feature Extraction.";
    }
    updateDeviceClassificationStatus();
  }

  // ── Extraction via Agentic RAG backend ──

  function apiBase() {
    return (
      (window.platformConfig && window.platformConfig.apiBaseUrl) ||
      "http://127.0.0.1:8000"
    );
  }

  async function extractFeatures() {
    if (state.extracting) return;
    if (!state.productSpec) return;

    state.extracting = true;
    updateSetupReadiness();
    $("extract-running").classList.remove("hidden");
    setPill($("workspace-status-pill"), "Extracting", "is-running");

    const deviceLabel = $("device-type-select").selectedOptions[0]?.text || state.deviceType;
    const base = apiBase();

    try {
      let data;
      if (state.productSpec.path) {
        // Electron dialog returns { path, name }
        const resp = await fetch(`${base}/api/extract-from-path`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            file_path: state.productSpec.path,
            query: "Extract all features and specifications",
            device_type: state.deviceType || null
          })
        });
        if (!resp.ok) throw new Error((await resp.text()) || `HTTP ${resp.status}`);
        data = await resp.json();
      } else {
        const form = new FormData();
        const blob = state.productSpec.file || state.productSpec;
        form.append("file", blob, state.productSpec.name || "spec.pdf");
        form.append("query", "Extract all features and specifications");
        if (state.deviceType) form.append("device_type", state.deviceType);
        const resp = await fetch(`${base}/api/extract-features`, { method: "POST", body: form });
        if (!resp.ok) throw new Error((await resp.text()) || `HTTP ${resp.status}`);
        data = await resp.json();
      }

      const features = keepTestableFeatures(
        (data.features || []).map((f) => {
          const found = f.found !== false && f.status !== "not_found";
          return {
            id: f.id,
            name: f.name,
            category: f.category || (f.kind === "extra" ? "Extra" : "Standard"),
            kind: f.kind || "standard",
            order: typeof f.order === "number" ? f.order : 999,
            found,
            sourceNames: f.source_names || [],
            capability: f.capability || "",
            automationMode: f.automationMode || "manual",
            status: found ? STATUS.EXTRACTED : STATUS.NOT_FOUND,
            parameters: dedupeParameters(f.parameters || []),
            testCases: f.testCases || [],
            script: f.script || null,
            score: f.score ?? null,
            scoreDetail: null,
            sources: f.sources || []
          };
        })
      );

      // Prefer first found feature for detail view
      const firstFound = features.find((f) => f.found) || features[0];

      state.features = features;
      state.selectedFeatureId = firstFound?.id || null;
      state.categoryFilter = "all";
      state.extractionRegistered = true;
      state.documentId = data.document_id || null;
      state.featureChecklist = data.feature_checklist || null;

      applyDeviceClassification(
        data.device_classification && typeof data.device_classification === "object"
          ? {
              category: data.device_classification.category || state.deviceType || "mobile",
              os: data.device_classification.os || "",
              manufacturer: data.device_classification.manufacturer || "",
              model: data.device_classification.model || "",
              storage: data.device_classification.storage || "",
              cpu: data.device_classification.cpu || "",
              ram: data.device_classification.ram || ""
            }
          : deriveDeviceClassification(data)
      );

      $("shell-context").textContent = `${deviceLabel} · ${TEST_AREA_LABELS[state.testArea] || "Module / Peripheral Testing"}`;
      const coverage = data.coverage || (data.extraction && data.extraction.coverage) || {};
      const foundN = features.filter((f) => f.found && f.kind === "standard").length;
      const totalN = features.filter((f) => f.kind === "standard").length;
      setPill(
        $("workspace-status-pill"),
        totalN ? `${foundN}/${totalN} found` : features.length ? "Extracted" : "No features",
        foundN ? "is-ready" : "is-failed"
      );
      $("extract-pending-callout")?.classList.add("hidden");

      if (!features.length) {
        $("features-empty-copy").textContent =
          `No grounded features returned. Coverage: ${coverage.status || "unknown"}. ` +
          `Missed sections: ${(coverage.missed_sections || []).join(", ") || "none"}.`;
      }

      state.tcSelectedFeatureId = null;
      state.tcSelectedCategoryId = null;
      state.tcSelectedCaseId = null;
      resetTestScriptSelection();
      state.tcCatalogs = {};
      renderFeaturesWorkspace();
      updateExtractedFeaturesVisibility();
      renderTestCaseGeneration();
      updateHomeStats();
      showView("feature-extraction");
    } catch (err) {
      console.error(err);
      setPill($("workspace-status-pill"), "Extraction failed", "is-failed");
      $("extract-pending-callout")?.classList.remove("hidden");
      $("features-empty-copy").textContent =
        `Agentic RAG extraction failed: ${err.message || err}. Is the backend running on ${base}?`;
      state.features = [];
      state.extractionRegistered = true;
      renderFeaturesWorkspace();
      updateExtractedFeaturesVisibility();
      updateHomeStats();
      showView("feature-extraction");
    } finally {
      state.extracting = false;
      $("extract-running").classList.add("hidden");
      updateSetupReadiness();
    }
  }

  // ── Feature rendering ───────────────────────────────

  function normalizeParamName(name) {
    return String(name || "")
      .toLowerCase()
      .replace(/\([^)]*\)/g, " ")
      .replace(/[^a-z0-9]+/g, " ")
      .trim()
      .replace(/\s+/g, " ");
  }

  function normalizeParamValue(value) {
    let v = String(value || "")
      .toLowerCase()
      .replace(/\b(inches|inch|in\.)\b/g, "inch")
      .replace(/\bpixels?\b/g, "pixel")
      .replace(/×/g, "x")
      .replace(/[^a-z0-9.x]+/g, " ")
      .trim()
      .replace(/\s+/g, " ");
    const tokens = v.split(" ").filter(Boolean);
    const collapsed = [];
    for (const t of tokens) {
      if (collapsed[collapsed.length - 1] !== t) collapsed.push(t);
    }
    return collapsed.join(" ");
  }

  function cleanParamValue(value) {
    let v = String(value || "").trim().replace(/\s+/g, " ");
    // Drop accidental doubled words: "pixels pixels" → "pixels"
    v = v.replace(/\b([A-Za-z0-9.+-]+)\s+\1\b/gi, "$1");
    return v;
  }

  function preferParamRow(a, b) {
    const score = (p) => {
      let s = 0;
      if (!/\([^)]*\)/.test(p.name)) s += 3;
      if (!/\b([A-Za-z0-9.+-]+)\s+\1\b/i.test(p.value)) s += 2;
      s -= p.name.length * 0.01;
      s -= p.value.length * 0.001;
      return s;
    };
    return score(a) >= score(b) ? a : b;
  }

  /** Remove exact and near-duplicate parameter rows before UI display. */
  function dedupeParameters(parameters) {
    const best = new Map();
    const order = [];
    for (const raw of parameters || []) {
      const name = String(raw?.name || "").trim();
      const value = cleanParamValue(raw?.value ?? "");
      if (!name || !value) continue;
      const key = `${normalizeParamName(name)}::${normalizeParamValue(value)}`;
      if (!key || key === "::") continue;
      const row = { name, value };
      if (!best.has(key)) {
        best.set(key, row);
        order.push(key);
      } else {
        best.set(key, preferParamRow(best.get(key), row));
      }
    }
    return order.map((k) => best.get(k));
  }

  function totalSpecsIdentified(features) {
    return (features || []).reduce((sum, f) => {
      if (!f.found) return sum;
      return sum + ((f.parameters && f.parameters.length) || 0);
    }, 0);
  }

  function filteredFeatures() {
    return state.features
      .slice()
      .sort((a, b) => (a.order || 0) - (b.order || 0));
  }

  function projectScore() {
    const scored = state.features.filter((f) => f.found && typeof f.score === "number");
    if (!scored.length) return null;
    const avg = scored.reduce((sum, f) => sum + f.score, 0) / scored.length;
    return Math.round(avg);
  }

  function updateHomeStats() {
    const features = state.features || [];
    const found = features.filter((f) => f.found !== false && f.status !== STATUS.NOT_FOUND);
    const caseCount = found.reduce((sum, f) => {
      const buckets = f.testCaseBuckets || {};
      const fromBuckets = TC_CATEGORIES.reduce(
        (n, cat) => n + ((buckets[cat.id] && buckets[cat.id].length) || 0),
        0
      );
      return sum + fromBuckets + ((f.testCases && f.testCases.length) || 0);
    }, 0);
    const scriptCount = found.filter(
      (f) =>
        f.script ||
        [STATUS.SCRIPTS_READY, STATUS.EXECUTING, STATUS.SCORED].includes(f.status)
    ).length;
    const scored = found.filter((f) => typeof f.score === "number");
    const avg = scored.length
      ? Math.round(scored.reduce((sum, f) => sum + f.score, 0) / scored.length)
      : null;
    const coverage = found.length ? 100 : 0;
    const docs = (state.productSpec ? 1 : 0) + (state.testSuite ? 1 : 0);
    const deviceEl = $("device-type-select");
    const deviceLabel =
      (deviceEl && deviceEl.value && deviceEl.selectedOptions[0]?.text) || "—";

    const setText = (id, value) => {
      const el = $(id);
      if (el) el.textContent = value;
    };

    setText("home-stat-features", String(found.length));
    setText("home-stat-cases", String(caseCount));
    setText("home-stat-scripts", String(scriptCount));
    setText("home-stat-coverage", `${coverage}%`);
    setText("home-stat-executions", String(scored.length));
    setText("home-stat-score", avg == null ? "—" : `${avg}%`);
    setText("home-stat-docs", String(docs));
    setText("home-stat-device", deviceLabel);
  }

  function updateProjectScoreChip() {
    const score = projectScore();
    const chip = $("project-score-chip");
    if (chip) chip.textContent = score == null ? "Score —" : `Score ${score}%`;
    updateHomeStats();
  }

  function renderFeatureList() {
    const list = $("feature-list");
    if (!list) return;
    list.innerHTML = "";
    const features = filteredFeatures();
    const specsN = totalSpecsIdentified(state.features);
    const countPill = $("feature-count-pill");
    if (countPill) {
      countPill.textContent = `${specsN} spec${specsN === 1 ? "" : "s"}`;
    }
    const summary = $("features-summary");
    if (summary) {
      summary.textContent =
        specsN === 1
          ? "1 spec identified from the product specification"
          : `${specsN} specs identified from the product specification`;
    }

    if (!features.length) {
      const msg = state.extractionRegistered
        ? "No testable features to show."
        : "No features yet. Complete Device Selection → Module / Peripheral Testing → upload Product Spec → Extract Features.";
      list.innerHTML = `<div class="empty-inline">${msg}</div>`;
      return;
    }

    features.forEach((feature) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className =
        "feature-list-item" +
        (feature.id === state.selectedFeatureId ? " active" : "") +
        (feature.found ? " is-found" : " is-missing");
      btn.innerHTML = `
        <div class="feature-list-item-top">
          <div class="feature-list-item-title">
            <span>${escapeHtml(feature.name)}</span>
          </div>
        </div>
      `;
      btn.addEventListener("click", () => {
        state.selectedFeatureId = feature.id;
        renderFeaturesWorkspace();
      });
      list.appendChild(btn);
    });
  }

  function getSelectedFeature() {
    return state.features.find((f) => f.id === state.selectedFeatureId) || null;
  }

  function renderFeatureDetail() {
    const feature = getSelectedFeature();
    const empty = $("feature-detail-empty");
    const content = $("feature-detail-content");
    if (!empty || !content) return;

    if (!feature) {
      empty.classList.remove("hidden");
      content.classList.add("hidden");
      return;
    }

    empty.classList.add("hidden");
    content.classList.remove("hidden");

    const title = $("detail-title");
    if (title) title.textContent = feature.name;

    const tbody = $("detail-spec-body");
    if (!tbody) return;
    const params = dedupeParameters(feature.parameters || []);
    if (!feature.found || !params.length) {
      tbody.innerHTML = `<tr><td colspan="2">${
        feature.found
          ? "No parameters extracted for this feature."
          : "This feature was not found in the uploaded product specification."
      }</td></tr>`;
    } else {
      tbody.innerHTML = params
        .map(
          (p) => `
      <tr>
        <td>${escapeHtml(p.name)}</td>
        <td>${escapeHtml(p.value)}</td>
      </tr>`
        )
        .join("");
    }
  }

  function tcgFeatures() {
    return (state.features || [])
      .filter((f) => f.found !== false && f.status !== STATUS.NOT_FOUND)
      .slice()
      .sort((a, b) => (a.order || 0) - (b.order || 0));
  }

  function tcgFeatureKey(feature) {
    if (!feature) return "";
    const raw = String(feature.id || feature.name || "")
      .trim()
      .toLowerCase()
      .replace(/[\s-]+/g, "_");
    if (raw === "cam" || raw.startsWith("camera")) return "camera";
    return raw;
  }

  function tcgBriefsFor(feature, categoryId) {
    const all = window.TEST_CASE_BRIEFS || {};
    const entry = all[tcgFeatureKey(feature)];
    const list = entry && entry.categories && entry.categories[categoryId];
    return Array.isArray(list) ? list : [];
  }

  function tcgCasesFor(feature, categoryId) {
    const briefs = tcgBriefsFor(feature, categoryId);
    if (briefs.length) return briefs;
    const buckets = (feature && feature.testCaseBuckets) || {};
    if (Array.isArray(buckets[categoryId]) && buckets[categoryId].length) {
      return buckets[categoryId];
    }
    const key = tcgFeatureKey(feature);
    const catalog = state.tcCatalogs[key];
    const list = catalog && catalog.categories && catalog.categories[categoryId];
    return Array.isArray(list) ? list : [];
  }

  async function ensureTestCaseCatalog(feature) {
    const key = tcgFeatureKey(feature);
    if (!key) return null;
    if (Object.prototype.hasOwnProperty.call(state.tcCatalogs, key)) {
      return state.tcCatalogs[key];
    }
    try {
      const resp = await fetch(`${apiBase()}/api/test-cases/${encodeURIComponent(key)}`);
      if (!resp.ok) {
        state.tcCatalogs[key] = null;
        return null;
      }
      const catalog = await resp.json();
      state.tcCatalogs[key] = catalog;
      if (feature) {
        feature.testCaseBuckets = catalog.categories || {};
      }
      return catalog;
    } catch {
      state.tcCatalogs[key] = null;
      return null;
    }
  }

  async function hydrateTestCaseCatalogs(features) {
    const list = features || tcgFeatures();
    await Promise.all(list.map((f) => ensureTestCaseCatalog(f)));
  }

  function renderTestCaseGeneration() {
    const features = tcgFeatures();
    const hint = $("tcg-rail-hint");
    if (hint) {
      hint.textContent = features.length
        ? "Select a feature → category → test case to view its details."
        : "Run Feature Extraction first to populate features.";
    }

    const pending = features.filter(
      (f) => !Object.prototype.hasOwnProperty.call(state.tcCatalogs, tcgFeatureKey(f))
    );
    if (pending.length) {
      hydrateTestCaseCatalogs(pending).then(() => {
        renderTestCaseGenerationPaint();
        updateHomeStats();
      });
    }

    renderTestCaseGenerationPaint();
  }

  function tcgSelectedCase() {
    if (!state.tcSelectedCaseId) return null;
    const feature = tcgFeatures().find((f) => f.id === state.tcSelectedFeatureId);
    if (!feature || !state.tcSelectedCategoryId) return null;
    return (
      tcgCasesFor(feature, state.tcSelectedCategoryId).find(
        (c) => c.id === state.tcSelectedCaseId
      ) || null
    );
  }

  function tcgLine(text) {
    return String(text || "").trim().replace(/\.+$/, "");
  }

  function renderTestCaseDetail() {
    const box = $("tcg-detail");
    if (!box) return;
    const tc = tcgSelectedCase();
    if (!tc) {
      box.innerHTML = `<div class="tcg-detail-empty">
        <div class="tcg-detail-empty-icon" aria-hidden="true">☰</div>
        <p>Select a test case from the left panel to view its details.</p>
      </div>`;
      return;
    }

    const feature = tcgFeatures().find((f) => f.id === state.tcSelectedFeatureId);
    const category = TC_CATEGORIES.find((c) => c.id === state.tcSelectedCategoryId);
    const prerequisites = Array.isArray(tc.prerequisites) ? tc.prerequisites : [];
    const steps = Array.isArray(tc.steps) ? tc.steps : [];
    const expected = Array.isArray(tc.expected_results) ? tc.expected_results : [];
    const checks = Array.isArray(tc.verification) ? tc.verification : [];
    const description = tc.description || tc.brief || tc.title || "";

    const metaRows = [
      ["Feature", tc.feature || (feature && feature.name) || "—"],
      ["Category", tc.category || (category && category.name) || "—"],
      ["Execution", tc.execution || "—"]
    ]
      .map(
        ([k, v]) => `<div class="tcg-meta-item">
          <span class="tcg-meta-key">${escapeHtml(k)}</span>
          <span class="tcg-meta-val">${escapeHtml(v)}</span>
        </div>`
      )
      .join("");

    box.innerHTML = `
      <div class="tcg-detail-head">
        <span class="tcg-detail-id">${escapeHtml(tc.id)}</span>
        <h4 class="tcg-detail-title">${escapeHtml(tc.title || tc.id)}</h4>
        <p class="tcg-detail-desc">${escapeHtml(description)}</p>
      </div>
      <div class="tcg-meta">${metaRows}</div>
      <section class="tcg-section">
        <h5>Objective</h5>
        <p>${escapeHtml(tc.objective || "—")}</p>
      </section>
      <section class="tcg-section">
        <h5>Prerequisites</h5>
        ${
          prerequisites.length
            ? `<ol class="tcg-list">${prerequisites
                .map((s) => `<li>${escapeHtml(tcgLine(s))}</li>`)
                .join("")}</ol>`
            : `<p class="muted">No prerequisites listed.</p>`
        }
      </section>
      <section class="tcg-section">
        <h5>Test Steps</h5>
        ${
          steps.length
            ? `<ol class="tcg-list">${steps
                .map((s) => `<li>${escapeHtml(tcgLine(s))}</li>`)
                .join("")}</ol>`
            : `<p class="muted">No test steps available.</p>`
        }
      </section>
      <section class="tcg-section">
        <h5>Expected Results</h5>
        ${
          expected.length
            ? `<ol class="tcg-list">${expected
                .map((s) => `<li>${escapeHtml(tcgLine(s))}</li>`)
                .join("")}</ol>`
            : `<p class="muted">No expected results listed.</p>`
        }
      </section>
      <section class="tcg-section">
        <h5>Test Verification</h5>
        ${
          checks.length
            ? `<ol class="tcg-list">${checks
                .map((s) => `<li>${escapeHtml(tcgLine(s))}</li>`)
                .join("")}</ol>`
            : `<p class="muted">No verification checks available.</p>`
        }
      </section>`;
    box.scrollTop = 0;
  }

  function markSelectedTestCase() {
    const tree = $("tcg-tree");
    if (!tree) return;
    tree.querySelectorAll(".tcg-case").forEach((el) => {
      const on = el.getAttribute("data-case-id") === state.tcSelectedCaseId;
      el.classList.toggle("is-selected", on);
      el.setAttribute("aria-pressed", String(on));
    });
  }

  function renderTestCaseGenerationPaint() {
    const features = tcgFeatures();
    const countPill = $("tcg-feature-count");
    if (countPill) countPill.textContent = String(features.length);

    if (
      state.tcSelectedFeatureId &&
      !features.some((f) => f.id === state.tcSelectedFeatureId)
    ) {
      state.tcSelectedFeatureId = null;
      state.tcSelectedCategoryId = null;
      state.tcSelectedCaseId = null;
    }

    const empty = $("tcg-empty");
    const tree = $("tcg-tree");
    if (!features.length) {
      empty?.classList.remove("hidden");
      if (tree) tree.innerHTML = "";
      renderTestCaseDetail();
      return;
    }
    empty?.classList.add("hidden");

    if (!tree) return;

    const prevScroll = tree.scrollTop;
    tree.innerHTML = features
      .map((f) => {
        const featureOpen = state.tcSelectedFeatureId === f.id;
        const caseTotal = TC_CATEGORIES.reduce(
          (n, cat) => n + tcgCasesFor(f, cat.id).length,
          0
        );
        const catsHtml = TC_CATEGORIES.map((cat) => {
          const cases = tcgCasesFor(f, cat.id);
          const catOpen =
            featureOpen && state.tcSelectedCategoryId === cat.id;
          let bodyHtml = "";
          if (catOpen) {
            bodyHtml = cases.length
              ? `<div class="tcg-cases">${cases
                  .map((c) => {
                    const on = state.tcSelectedCaseId === c.id;
                    return `<button type="button" class="tcg-case${
                      on ? " is-selected" : ""
                    }" data-case-id="${escapeHtml(c.id)}" aria-pressed="${on}">
                      <span class="tcg-case-id">${escapeHtml(c.id)}</span>
                      <span class="tcg-case-desc">${escapeHtml(
                        c.description || c.brief || c.title || ""
                      )}</span>
                    </button>`;
                  })
                  .join("")}</div>`
              : `<div class="tcg-cases-empty muted">No test cases for this category.</div>`;
          }
          return `<div class="tcg-cat${catOpen ? " is-open" : ""}">
            <button type="button" class="tcg-cat-btn" data-feature-id="${escapeHtml(
              f.id
            )}" data-category-id="${cat.id}" aria-expanded="${catOpen}">
              <span class="tcg-chevron" aria-hidden="true">${
                catOpen ? "▾" : "▸"
              }</span>
              <span class="tcg-cat-name">${escapeHtml(cat.name)}</span>
              <span class="tcg-cat-meta">${cases.length}</span>
            </button>
            ${bodyHtml}
          </div>`;
        }).join("");

        return `<div class="tcg-feature${featureOpen ? " is-open" : ""}">
          <button type="button" class="tcg-feature-btn" data-feature-id="${escapeHtml(
            f.id
          )}" aria-expanded="${featureOpen}">
            <span class="tcg-chevron" aria-hidden="true">${
              featureOpen ? "▾" : "▸"
            }</span>
            <span class="tcg-feature-name">${escapeHtml(f.name)}</span>
            <span class="tcg-feature-meta">${
              caseTotal ? `${caseTotal} cases` : ""
            }</span>
          </button>
          <div class="tcg-categories">${catsHtml}</div>
        </div>`;
      })
      .join("");
    fitCaseListsToVisibleRows(tree);
    tree.scrollTop = prevScroll;

    renderTestCaseDetail();
  }

  const TCG_VISIBLE_CASES = 5;

  function fitCaseListsToVisibleRows(root) {
    root.querySelectorAll(".tcg-cases").forEach((list) => {
      const rows = list.querySelectorAll(".tcg-case, .tsg-case");
      if (rows.length <= TCG_VISIBLE_CASES) {
        list.style.maxHeight = "none";
        return;
      }
      const top = rows[0].getBoundingClientRect().top;
      const bottom = rows[TCG_VISIBLE_CASES - 1].getBoundingClientRect().bottom;
      const height = Math.ceil(bottom - top);
      // Hidden view reports 0; keep the CSS fallback height.
      if (height > 0) list.style.maxHeight = `${height}px`;
    });
  }

  function resetTestScriptSelection() {
    state.tsgOpenFeatureId = null;
    state.tsgOpenCategoryId = null;
    state.tsgSelectedIds = new Set();
    state.tsgResults = [];
    state.tsgActiveFile = "";
    state.tsgShowDetails = false;
    renderScriptSelect();
    const preview = $("tsg-script-preview");
    if (preview) preview.value = 'Select test cases and click "Generate Test Scripts".';
    const suite = $("tsg-suite-output");
    if (suite) suite.value = "Generated scripts and their status will appear here.";
    const detailsBtn = $("tsg-full-output-btn");
    if (detailsBtn) detailsBtn.disabled = true;
  }

  function tsgFeatureCaseIds(feature) {
    return TC_CATEGORIES.flatMap((cat) => tcgCasesFor(feature, cat.id).map((c) => c.id));
  }

  function tsgSelectedFrameworkNames() {
    return FRAMEWORKS.filter((f) => (state.selectedFrameworks || []).includes(f.id)).map(
      (f) => f.name
    );
  }

  function tsgCheckState(ids) {
    const picked = ids.filter((id) => state.tsgSelectedIds.has(id)).length;
    return { picked, total: ids.length, all: ids.length > 0 && picked === ids.length };
  }

  function renderTestScriptGeneration() {
    const features = tcgFeatures();
    const pending = features.filter(
      (f) => !Object.prototype.hasOwnProperty.call(state.tcCatalogs, tcgFeatureKey(f))
    );
    if (pending.length) {
      hydrateTestCaseCatalogs(pending).then(() => renderTestScriptGenerationPaint());
    }
    renderTestScriptGenerationPaint();
  }

  function renderTestScriptGenerationPaint() {
    const features = tcgFeatures();
    const tree = $("tsg-tree");
    const empty = $("tsg-empty");

    const frameworks = tsgSelectedFrameworkNames();
    const sub = $("tsg-preview-sub");
    if (sub) {
      sub.textContent = frameworks.length
        ? `Frameworks: ${frameworks.join(" · ")}`
        : "No frameworks selected yet";
    }

    if (!features.length) {
      empty?.classList.remove("hidden");
      if (tree) tree.innerHTML = "";
      syncTestScriptChecks();
      return;
    }
    empty?.classList.add("hidden");
    if (!tree) return;

    const prevScroll = tree.scrollTop;
    tree.innerHTML = features
      .map((f) => {
        const featureOpen = state.tsgOpenFeatureId === f.id;
        const catsHtml = TC_CATEGORIES.map((cat) => {
          const cases = tcgCasesFor(f, cat.id);
          const catOpen = featureOpen && state.tsgOpenCategoryId === cat.id;
          const casesHtml = !catOpen
            ? ""
            : cases.length
              ? `<div class="tcg-cases">${cases
                  .map(
                    (c) => `<label class="tsg-case">
                      <input type="checkbox" class="tsg-check" data-scope="case" data-case-id="${escapeHtml(
                        c.id
                      )}" ${state.tsgSelectedIds.has(c.id) ? "checked" : ""} />
                      <span class="tsg-case-text">
                        <span class="tcg-case-id">${escapeHtml(c.id)}</span>
                        <span class="tcg-case-desc">${escapeHtml(
                          c.description || c.brief || c.title || ""
                        )}</span>
                      </span>
                    </label>`
                  )
                  .join("")}</div>`
              : `<div class="tcg-cases-empty muted">No test cases for this category.</div>`;
          return `<div class="tsg-cat${catOpen ? " is-open" : ""}">
            <div class="tsg-row tsg-cat-row">
              <input type="checkbox" class="tsg-check" data-scope="category" data-feature-id="${escapeHtml(
                f.id
              )}" data-category-id="${cat.id}" aria-label="Select all ${escapeHtml(
                cat.name
              )} test cases" ${cases.length ? "" : "disabled"} />
              <button type="button" class="tsg-toggle" data-toggle="category" data-feature-id="${escapeHtml(
                f.id
              )}" data-category-id="${cat.id}" aria-expanded="${catOpen}">
                <span class="tcg-chevron" aria-hidden="true">${catOpen ? "▾" : "▸"}</span>
                <span class="tcg-cat-name">${escapeHtml(cat.name)}</span>
                <span class="tcg-cat-meta" data-count-for="category" data-feature-id="${escapeHtml(
                  f.id
                )}" data-category-id="${cat.id}"></span>
              </button>
            </div>
            ${casesHtml}
          </div>`;
        }).join("");

        return `<div class="tsg-feature${featureOpen ? " is-open" : ""}">
          <div class="tsg-row tsg-feature-row">
            <button type="button" class="tsg-toggle" data-toggle="feature" data-feature-id="${escapeHtml(
              f.id
            )}" aria-expanded="${featureOpen}">
              <span class="tcg-chevron" aria-hidden="true">${featureOpen ? "▾" : "▸"}</span>
              <span class="tcg-feature-name">${escapeHtml(f.name)}</span>
              <span class="tcg-feature-meta" data-count-for="feature" data-feature-id="${escapeHtml(
                f.id
              )}"></span>
            </button>
          </div>
          <div class="tsg-categories">${catsHtml}</div>
        </div>`;
      })
      .join("");
    fitCaseListsToVisibleRows(tree);
    tree.scrollTop = prevScroll;
    syncTestScriptChecks();
  }

  /** Update feature/category checkboxes, counts and the Generate button without re-rendering. */
  function syncTestScriptChecks() {
    const features = tcgFeatures();
    const tree = $("tsg-tree");
    const byId = new Map(features.map((f) => [f.id, f]));

    tree?.querySelectorAll('.tsg-check[data-scope="category"]').forEach((el) => {
      const f = byId.get(el.getAttribute("data-feature-id"));
      const ids = f ? tcgCasesFor(f, el.getAttribute("data-category-id")).map((c) => c.id) : [];
      const s = tsgCheckState(ids);
      el.checked = s.all;
      el.indeterminate = s.picked > 0 && !s.all;
    });
    tree?.querySelectorAll("[data-count-for]").forEach((el) => {
      const f = byId.get(el.getAttribute("data-feature-id"));
      if (!f) return;
      const ids =
        el.getAttribute("data-count-for") === "feature"
          ? tsgFeatureCaseIds(f)
          : tcgCasesFor(f, el.getAttribute("data-category-id")).map((c) => c.id);
      const s = tsgCheckState(ids);
      el.textContent = s.total ? `${s.picked}/${s.total}` : "";
    });
    tree?.querySelectorAll('.tsg-check[data-scope="case"]').forEach((el) => {
      el.checked = state.tsgSelectedIds.has(el.getAttribute("data-case-id"));
      el.closest(".tsg-case")?.classList.toggle("is-selected", el.checked);
    });

    const count = state.tsgSelectedIds.size;
    const pill = $("tsg-selected-count");
    if (pill) {
      pill.textContent = `${count} selected`;
      pill.classList.toggle("is-ready", count > 0);
    }
    const btn = $("tsg-generate-btn");
    if (btn) btn.disabled = count === 0 || state.tsgGenerating;
  }

  function setTestScriptSelection(ids, selected) {
    ids.forEach((id) => {
      if (selected) state.tsgSelectedIds.add(id);
      else state.tsgSelectedIds.delete(id);
    });
    syncTestScriptChecks();
  }

  function tsgSelectedCases() {
    return tcgFeatures().flatMap((f) =>
      TC_CATEGORIES.flatMap((cat) =>
        tcgCasesFor(f, cat.id)
          .filter((c) => state.tsgSelectedIds.has(c.id))
          .map((c) => ({ ...c, featureName: f.name, categoryName: cat.name }))
      )
    );
  }

  async function generateTestScripts() {
    const cases = tsgSelectedCases();
    if (!cases.length || state.tsgGenerating) return;
    const preview = $("tsg-script-preview");
    const suite = $("tsg-suite-output");
    const btn = $("tsg-generate-btn");

    const byFeature = new Map();
    cases.forEach((c) => {
      const f = tcgFeatures().find((x) => x.name === c.featureName);
      const key = tcgFeatureKey(f) || "camera";
      if (!byFeature.has(key)) byFeature.set(key, []);
      byFeature.get(key).push(c.id);
    });

    state.tsgGenerating = true;
    state.tsgResults = [];
    state.tsgShowDetails = false;
    syncRunOnDeviceButton();
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Generating…";
    }
    if (preview) preview.value = `# Generating ${cases.length} test script(s)…`;
    if (suite) suite.value = "Sending test cases and harness operations to the LLM…";
    renderScriptSelect();

    // Values from the current extraction fill ${VAR} placeholders in these scripts only;
    // the catalog files keep their placeholders.
    const specFeatures = tcgFeatures().map((f) => ({ name: f.name, parameters: f.parameters || [] }));
    const dc = state.deviceClassification || {};
    const maker = String(dc.manufacturer || "").trim();
    const model = String(dc.model || "").trim();
    const productName =
      (maker && model.toLowerCase().startsWith(maker.toLowerCase()) ? model : [maker, model].filter(Boolean).join(" ")) || null;

    try {
      for (const [feature, ids] of byFeature) {
        const resp = await fetch(`${apiBase()}/api/test-scripts/generate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            feature,
            case_ids: ids,
            frameworks: state.selectedFrameworks || [],
            spec_features: specFeatures,
            product_name: productName
          })
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
        state.tsgResults.push(data);
      }
      const first = tsgGeneratedFiles()[0];
      state.tsgActiveFile = first ? first.key : "";
      renderScriptSelect();
      showActiveScript();
      renderGenerationSummary();
      syncRunOnDeviceButton();
    } catch (err) {
      if (preview) preview.value = `# Script generation failed\n# ${err.message || err}`;
      if (suite) suite.value = `Script generation failed: ${err.message || err}`;
    } finally {
      state.tsgGenerating = false;
      if (btn) btn.textContent = "Generate Test Scripts";
      syncTestScriptChecks();
    }
  }

  /** Latest generation bundle with at least one script, for the "Run on Device" hand-off. */
  function runnableGeneration() {
    return (state.tsgResults || [])
      .slice()
      .reverse()
      .find((r) => r.summary && r.summary.generated > 0);
  }

  function syncRunOnDeviceButton() {
    $("tsg-run-btn")?.classList.toggle("hidden", !runnableGeneration());
  }

  /** Flat list of generated files (scripts + shared runtime) across all result bundles. */
  function tsgGeneratedFiles() {
    const files = [];
    (state.tsgResults || []).forEach((res, i) => {
      (res.scripts || []).forEach((s) => {
        files.push({
          key: `${i}:${s.case_id}`,
          label: `${s.filename || s.case_id}${s.status === "ok" ? "" : " (failed)"}`,
          code: s.code || `# ${s.case_id}: generation failed\n# ${(s.errors || []).join("\n# ")}`
        });
      });
      if (res.runtime) {
        files.push({
          key: `${i}:runtime`,
          label: `${res.runtime.filename} (shared runtime)`,
          code: res.runtime.code
        });
      }
    });
    return files;
  }

  function renderScriptSelect() {
    const select = $("tsg-script-select");
    if (!select) return;
    const files = tsgGeneratedFiles();
    select.innerHTML = files.length
      ? files
          .map(
            (f) =>
              `<option value="${escapeHtml(f.key)}"${
                f.key === state.tsgActiveFile ? " selected" : ""
              }>${escapeHtml(f.label)}</option>`
          )
          .join("")
      : `<option value="">No scripts yet</option>`;
    select.disabled = !files.length;
  }

  function showActiveScript() {
    const preview = $("tsg-script-preview");
    const file = tsgGeneratedFiles().find((f) => f.key === state.tsgActiveFile);
    if (preview && file) {
      preview.value = file.code;
      preview.scrollTop = 0;
    }
  }

  function renderGenerationSummary() {
    const suite = $("tsg-suite-output");
    const detailsBtn = $("tsg-full-output-btn");
    const results = state.tsgResults || [];
    if (detailsBtn) {
      detailsBtn.disabled = !results.length;
      detailsBtn.textContent = state.tsgShowDetails ? "Show Summary" : "Show Complete Output";
    }
    if (!suite) return;
    const lines = [];
    results.forEach((res) => {
      const sm = res.summary || {};
      const gen = sm.by_generator || {};
      lines.push(
        `Run ${res.run_id}`,
        `Generated ${sm.generated}/${sm.requested} script(s) · LLM ${gen.llm || 0} · template ${
          gen.template || 0
        }${sm.failed ? ` · failed ${sm.failed}` : ""}`,
        res.llm_used ? "" : "LLM not configured: scripts were built from the fixed template.",
        `Output folder: ${res.output_dir}`,
        `Run one:  python3 test_<case_id>.py [--serial SERIAL]`,
        `Run all:  python3 run_suite.py`,
        ""
      );
      const applied = (res.spec_profile && res.spec_profile.applied) || {};
      const appliedKeys = Object.keys(applied);
      if (appliedKeys.length) {
        const from = (res.spec_profile && res.spec_profile.product_name) || "the product spec";
        lines.push(`Spec values from ${from} (${appliedKeys.length} placeholder(s) filled):`);
        appliedKeys.forEach((k) => {
          const item = applied[k] || {};
          lines.push(
            `  ${k} = ${item.value}${state.tsgShowDetails && item.source ? `   ← ${item.source}` : ""}`
          );
        });
        lines.push("");
      } else {
        lines.push("Spec values: none applied (placeholders resolved from the device at runtime).", "");
      }
      (res.scripts || []).forEach((s) => {
        const flag = s.status === "ok" ? "OK  " : "FAIL";
        lines.push(
          `${flag} ${String(s.case_id).padEnd(12)} ${String(s.generator || "-").padEnd(9)} ${
            s.name || ""
          }`
        );
        if (!state.tsgShowDetails) return;
        const cls = s.harness_class ? s.harness_class.split(".").pop() : "";
        if (cls) lines.push(`       harness: ${cls} · ${s.execution || ""}`);
        const sv = Object.entries(s.spec_values || {});
        if (sv.length) lines.push(`       spec: ${sv.map(([k, v]) => `${k}=${v}`).join(", ")}`);
        (s.errors || []).forEach((e) => lines.push(`       error: ${e}`));
        (s.warnings || []).forEach((w) => lines.push(`       warning: ${w}`));
        (s.manual_steps || []).forEach((m) => lines.push(`       manual: ${m}`));
        (s.notes || []).forEach((n) => lines.push(`       note: ${n}`));
      });
      lines.push("");
    });
    suite.value = lines.filter((l, i, a) => l !== "" || a[i - 1] !== "").join("\n");
    suite.scrollTop = 0;
  }

  function renderFeaturesWorkspace() {
    renderFeatureList();
    renderFeatureDetail();
    updateProjectScoreChip();
  }

  function deviceTypeLabel() {
    const el = $("device-type-select");
    if (el && el.selectedOptions && el.selectedOptions[0] && el.value) {
      return el.selectedOptions[0].text;
    }
    return state.deviceType || "";
  }

  function renderFrameworkSelection() {
    const dc = state.deviceClassification || {};
    const typeLabel = deviceTypeLabel();
    const focusLabel = (TEST_AREA_LABELS && TEST_AREA_LABELS[state.testArea]) || "";
    const modelBits = [dc.manufacturer, dc.model].filter(Boolean).join(" ");
    const hasDevice = Boolean(state.deviceType);

    const title = $("fw-device-title");
    const meta = $("fw-device-meta");
    const pill = $("fw-device-pill");

    if (title) {
      title.textContent = hasDevice
        ? modelBits || typeLabel || "Device selected"
        : "No device selected";
    }
    if (meta) {
      meta.textContent = hasDevice
        ? [typeLabel, focusLabel].filter(Boolean).join(" · ") || "Device type selected"
        : "Complete Device Selection to continue.";
    }
    if (pill) {
      setPill(pill, hasDevice ? "Selected" : "Pending", hasDevice ? "is-ready" : "");
    }

    const selected = new Set(state.selectedFrameworks || []);
    const countPill = $("fw-selected-count");
    if (countPill) {
      countPill.textContent = `${selected.size} selected`;
    }

    const grid = $("fw-card-grid");
    if (grid) {
      grid.innerHTML = FRAMEWORKS.map((fw, i) => {
        const isSel = selected.has(fw.id);
        const classes = [
          "fw-card",
          fw.recommended ? "is-recommended" : "",
          isSel ? "is-selected" : ""
        ]
          .filter(Boolean)
          .join(" ");
        return `<button type="button" class="${classes}" data-framework-id="${fw.id}" role="option" aria-selected="${isSel}">
          ${
            fw.recommended && !state.frameworksConfirmed
              ? `<span class="fw-card-badge">Recommended</span>`
              : isSel
                ? `<span class="fw-card-badge">Selected</span>`
                : ""
          }
          <span class="fw-card-index">${String(i + 1).padStart(2, "0")}</span>
          <span class="fw-card-name">${escapeHtml(fw.name)}</span>
          <p class="fw-card-desc">${escapeHtml(fw.desc)}</p>
        </button>`;
      }).join("");
    }

    const genBtn = $("generate-test-scripts-btn");
    if (genBtn) {
      const ready = hasDevice && selected.size > 0 && state.frameworksConfirmed;
      genBtn.disabled = !ready;
    }
  }

  function toggleFramework(id) {
    if (!state.frameworksConfirmed) return;
    const set = new Set(state.selectedFrameworks || []);
    if (set.has(id)) set.delete(id);
    else set.add(id);
    state.selectedFrameworks = Array.from(set);
    renderFrameworkSelection();
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ── Script generation ───────────────────────────────

  function buildMockCases(feature) {
    const mode = feature.automationMode;
    return [
      {
        id: "TC-01",
        title: `Verify ${feature.name} baseline`,
        steps: [
          "Prepare device under test per setup checklist",
          `Exercise ${feature.name} using documented procedure`,
          "Capture logs / evidence"
        ],
        expected: feature.parameters.map((p) => `${p.name}=${p.value}`).join("; "),
        result: null
      },
      {
        id: "TC-02",
        title: `Negative / edge path for ${feature.name}`,
        steps: [
          "Apply constrained condition (signal/power/permission)",
          "Retry feature operation",
          "Confirm graceful handling"
        ],
        expected: "No crash; recoverable error path observed",
        result: null
      },
      {
        id: "TC-03",
        title: `${modeLabel(mode)} execution path`,
        steps:
          mode === "manual"
            ? ["Follow operator checklist", "Record Pass/Fail in UI"]
            : mode === "semi"
              ? ["Run automated probe", "Confirm human checkpoint", "Finalize result"]
              : ["Launch runner", "Collect metrics", "Assert against specification"],
        expected: "All assertions match product specification",
        result: null
      }
    ];
  }

  function buildMockScript(feature) {
    return `# Auto-generated stub for: ${feature.name}
# Device type: ${state.deviceType}
# Mode: ${feature.automationMode}
# NOTE: UI mock only — backend LLM generation will replace this.

def test_${feature.id}_baseline():
    """Validate capability: ${feature.capability}"""
    params = {
${feature.parameters.map((p) => `        "${p.name}": "${p.value}",`).join("\n")}
    }
    # TODO: bind to ${feature.automationMode} runner
    assert params, "specification parameters must be present"
    return {"status": "PASS", "feature": "${feature.name}"}
`;
  }

  async function generateScriptsForFeature(feature, { silent } = {}) {
    if (!isFeatureActionable(feature)) return;
    feature.status = STATUS.GENERATING;
    if (!silent) {
      $("feature-running").classList.remove("hidden");
      $("feature-running-text").textContent = "Generating scripts…";
      setPill($("workspace-status-pill"), "Generating", "is-running");
      renderFeaturesWorkspace();
    }
    await delay(silent ? 250 : 700);
    feature.testCases = buildMockCases(feature);
    feature.script = buildMockScript(feature);
    feature.status = STATUS.SCRIPTS_READY;
    feature.score = null;
    feature.scoreDetail = "";
    if (!silent) {
      $("feature-running").classList.add("hidden");
      setPill($("workspace-status-pill"), "Scripts ready", "is-ready");
      renderFeaturesWorkspace();
    }
  }

  async function generateSelectedScripts() {
    const feature = getSelectedFeature();
    if (!feature || !isFeatureActionable(feature)) return;
    await generateScriptsForFeature(feature);
  }

  async function generateAllScripts() {
    if (state.bulkRunning) return;
    const actionable = state.features.filter((f) => isFeatureActionable(f));
    if (!actionable.length) return;
    state.bulkRunning = true;
    $("bulk-running").classList.remove("hidden");
    $("generate-all-btn").disabled = true;
    $("execute-all-btn").disabled = true;

    for (let i = 0; i < actionable.length; i += 1) {
      const feature = actionable[i];
      $("bulk-running-text").textContent = `Generating ${i + 1}/${actionable.length}: ${feature.name}`;
      setPill($("workspace-status-pill"), `Gen ${i + 1}/${actionable.length}`, "is-running");
      await generateScriptsForFeature(feature, { silent: true });
      renderFeaturesWorkspace();
    }

    state.bulkRunning = false;
    $("bulk-running").classList.add("hidden");
    $("generate-all-btn").disabled = false;
    setPill($("workspace-status-pill"), "All scripts ready", "is-success");
    updateProjectScoreChip();
    renderFeaturesWorkspace();
  }

  // ── Execution ───────────────────────────────────────

  function applyScore(feature, score, detail, caseResults) {
    feature.score = score;
    feature.scoreDetail = detail;
    feature.status = score >= 70 ? STATUS.SCORED : STATUS.FAILED;
    feature.testCases = feature.testCases.map((tc, idx) => ({
      ...tc,
      result: caseResults[idx] || (score >= 70 ? "pass" : "fail")
    }));
  }

  async function runAutomated(feature) {
    feature.status = STATUS.EXECUTING;
    $("feature-running").classList.remove("hidden");
    $("feature-running-text").textContent = "Executing automated tests…";
    setPill($("workspace-status-pill"), "Executing", "is-running");
    renderFeaturesWorkspace();
    await delay(900);
    const score = 78 + Math.floor(Math.random() * 18);
    applyScore(feature, score, `${feature.testCases.length} automated cases completed`, [
      "pass",
      "pass",
      score >= 85 ? "pass" : "fail"
    ]);
    $("feature-running").classList.add("hidden");
    setPill($("workspace-status-pill"), "Feature scored", "is-success");
    renderFeaturesWorkspace();
  }

  function openManualModal(feature) {
    state.pendingManualFeatureId = feature.id;
    $("manual-modal-title").textContent = `Manual — ${feature.name}`;
    $("manual-modal-desc").textContent =
      "Execute the following steps on the device, then mark Pass or Fail.";
    const steps = feature.testCases.length
      ? feature.testCases.flatMap((tc) => tc.steps)
      : [
          "Power on device and unlock",
          `Validate: ${feature.capability}`,
          "Capture screenshot / notes as evidence"
        ];
    $("manual-steps-list").innerHTML = steps.map((s) => `<li>${escapeHtml(s)}</li>`).join("");
    openModal("manual-modal");
  }

  function finishManual(result) {
    const feature = state.features.find((f) => f.id === state.pendingManualFeatureId);
    closeModal("manual-modal");
    state.pendingManualFeatureId = null;
    if (!feature) return;
    const score = result === "pass" ? 100 : 40;
    applyScore(
      feature,
      score,
      result === "pass" ? "Operator marked all manual steps Pass" : "Operator marked Fail",
      feature.testCases.map(() => result)
    );
    setPill($("workspace-status-pill"), "Feature scored", result === "pass" ? "is-success" : "is-failed");
    renderFeaturesWorkspace();
  }

  function openSemiModal(feature) {
    state.pendingSemiFeatureId = feature.id;
    $("semi-modal-title").textContent = `Semi-automated — ${feature.name}`;
    $("semi-modal-desc").textContent =
      "Automated probe finished. Confirm the remaining manual checkpoint.";
    $("semi-checkpoint-box").innerHTML = `
      <div style="font-size: 12px; font-weight: 700; color: #0f2f7a; margin-bottom: 6px;">CHECKPOINT</div>
      <div style="font-size: 13px; color: var(--text-strong); line-height: 1.45;">
        Confirm on-device result for <strong>${escapeHtml(feature.name)}</strong> matches:
        <br/><span style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px;">
          ${escapeHtml(feature.parameters.map((p) => `${p.name}=${p.value}`).join(" · "))}
        </span>
      </div>`;
    openModal("semi-modal");
  }

  async function startSemi(feature) {
    feature.status = STATUS.EXECUTING;
    $("feature-running").classList.remove("hidden");
    $("feature-running-text").textContent = "Running automated portion…";
    setPill($("workspace-status-pill"), "Semi-auto", "is-running");
    renderFeaturesWorkspace();
    await delay(700);
    $("feature-running").classList.add("hidden");
    openSemiModal(feature);
  }

  function finishSemi() {
    const feature = state.features.find((f) => f.id === state.pendingSemiFeatureId);
    closeModal("semi-modal");
    state.pendingSemiFeatureId = null;
    if (!feature) return;
    const score = 82 + Math.floor(Math.random() * 14);
    applyScore(feature, score, "Automated portion + operator checkpoint confirmed", [
      "pass",
      "pass",
      "pass"
    ]);
    setPill($("workspace-status-pill"), "Feature scored", "is-success");
    renderFeaturesWorkspace();
  }

  async function executeSelectedFeature() {
    const feature = getSelectedFeature();
    if (!feature || !isFeatureActionable(feature) || !feature.testCases.length) return;

    if (feature.automationMode === "manual") {
      openManualModal(feature);
      return;
    }
    if (feature.automationMode === "semi") {
      await startSemi(feature);
      return;
    }
    await runAutomated(feature);
  }

  async function executeAllFeatures() {
    if (state.bulkRunning) return;
    const runnable = state.features.filter(
      (f) =>
        isFeatureActionable(f) &&
        [STATUS.SCRIPTS_READY, STATUS.SCORED, STATUS.FAILED].includes(f.status)
    );
    if (!runnable.length) return;

    state.bulkRunning = true;
    $("bulk-running").classList.remove("hidden");
    $("generate-all-btn").disabled = true;
    $("execute-all-btn").disabled = true;

    for (let i = 0; i < runnable.length; i += 1) {
      const feature = runnable[i];
      state.selectedFeatureId = feature.id;
      $("bulk-running-text").textContent = `Executing ${i + 1}/${runnable.length}: ${feature.name}`;
      renderFeaturesWorkspace();

      if (feature.automationMode === "manual") {
        // In bulk mode, auto-skip interactive manual with a placeholder blocked score
        applyScore(feature, 0, "Skipped in bulk — requires manual popup execution", feature.testCases.map(() => "fail"));
        feature.status = STATUS.FAILED;
        continue;
      }
      if (feature.automationMode === "semi") {
        // Bulk: assume checkpoint confirmed for demo
        await delay(400);
        applyScore(feature, 88, "Bulk semi-auto run (checkpoint assumed for UI demo)", [
          "pass",
          "pass",
          "pass"
        ]);
        continue;
      }
      await delay(450);
      const score = 80 + Math.floor(Math.random() * 16);
      applyScore(feature, score, "Bulk automated execution", ["pass", "pass", "pass"]);
    }

    state.bulkRunning = false;
    $("bulk-running").classList.add("hidden");
    $("generate-all-btn").disabled = false;
    setPill($("workspace-status-pill"), "Bulk execution done", "is-success");
    renderFeaturesWorkspace();
  }

  function selectAdjacentFeature(delta) {
    const idx = state.features.findIndex((f) => f.id === state.selectedFeatureId);
    const next = state.features[idx + delta];
    if (!next) return;
    state.selectedFeatureId = next.id;
    renderFeaturesWorkspace();
  }

  // ── Events ──────────────────────────────────────────

  function bindEvents() {
    $("enter-platform-btn").addEventListener("click", () => {
      showScreen("main-screen");
      showView("home");
    });

    document.querySelectorAll(".nav-item[data-view]").forEach((item) => {
      item.addEventListener("click", () => {
        if (item.disabled) return;
        showView(item.dataset.view);
      });
    });

    $("goto-feature-extraction-btn")?.addEventListener("click", () => {
      showView(testAreaStartView());
    });

    $("goto-device-classification-btn")?.addEventListener("click", () => {
      showView("device-classification");
    });

    $("goto-framework-selection-btn")?.addEventListener("click", () => {
      state.selectedFrameworks = RECOMMENDED_FRAMEWORKS.slice();
      state.frameworksConfirmed = true;
      showView("framework-selection");
    });

    const setSidebarCollapsed = (collapsed) => {
      const layout = document.querySelector(".wb-layout");
      const expandBtn = $("sidebar-expand-btn");
      const collapseBtn = $("sidebar-collapse-btn");
      layout?.classList.toggle("sidebar-collapsed", collapsed);
      expandBtn?.classList.toggle("hidden", !collapsed);
      if (collapseBtn) collapseBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    };

    $("sidebar-collapse-btn")?.addEventListener("click", () => {
      setSidebarCollapsed(true);
    });

    $("sidebar-expand-btn")?.addEventListener("click", () => {
      setSidebarCollapsed(false);
    });

    $("fw-card-grid")?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-framework-id]");
      if (!btn) return;
      toggleFramework(btn.getAttribute("data-framework-id"));
    });

    $("generate-test-scripts-btn")?.addEventListener("click", () => {
      if ($("generate-test-scripts-btn")?.disabled) return;
      showView("test-script-generation");
    });

    $("tsg-tree")?.addEventListener("change", (e) => {
      const box = e.target.closest(".tsg-check");
      if (!box) return;
      const scope = box.getAttribute("data-scope");
      if (scope === "case") {
        setTestScriptSelection([box.getAttribute("data-case-id")], box.checked);
        return;
      }
      const feature = tcgFeatures().find((f) => f.id === box.getAttribute("data-feature-id"));
      if (!feature) return;
      const ids = tcgCasesFor(feature, box.getAttribute("data-category-id")).map((c) => c.id);
      setTestScriptSelection(ids, box.checked);
    });

    $("tsg-tree")?.addEventListener("click", (e) => {
      const toggle = e.target.closest(".tsg-toggle");
      if (!toggle) return;
      const featureId = toggle.getAttribute("data-feature-id");
      if (toggle.getAttribute("data-toggle") === "feature") {
        const closing = state.tsgOpenFeatureId === featureId;
        state.tsgOpenFeatureId = closing ? null : featureId;
        state.tsgOpenCategoryId = null;
      } else {
        const catId = toggle.getAttribute("data-category-id");
        state.tsgOpenFeatureId = featureId;
        state.tsgOpenCategoryId = state.tsgOpenCategoryId === catId ? null : catId;
      }
      renderTestScriptGenerationPaint();
    });

    $("tsg-generate-btn")?.addEventListener("click", () => {
      if ($("tsg-generate-btn")?.disabled) return;
      generateTestScripts();
    });

    $("tsg-run-btn")?.addEventListener("click", () => {
      const bundle = runnableGeneration();
      if (!bundle) return;
      showView("test-execution");
      document.dispatchEvent(new CustomEvent("execution:open-set", { detail: { runId: bundle.run_id } }));
    });

    $("tsg-script-select")?.addEventListener("change", (e) => {
      state.tsgActiveFile = e.target.value;
      showActiveScript();
    });

    $("tsg-full-output-btn")?.addEventListener("click", () => {
      state.tsgShowDetails = !state.tsgShowDetails;
      renderGenerationSummary();
    });

    window.addEventListener("resize", () => {
      ["tcg-tree", "tsg-tree"].forEach((id) => {
        const tree = $(id);
        if (tree) fitCaseListsToVisibleRows(tree);
      });
    });

    $("tcg-tree")?.addEventListener("click", (e) => {
      const caseBtn = e.target.closest(".tcg-case");
      if (caseBtn) {
        state.tcSelectedCaseId = caseBtn.getAttribute("data-case-id");
        markSelectedTestCase();
        renderTestCaseDetail();
        return;
      }
      const catBtn = e.target.closest(".tcg-cat-btn");
      if (catBtn) {
        const featureId = catBtn.getAttribute("data-feature-id");
        const catId = catBtn.getAttribute("data-category-id");
        if (state.tcSelectedFeatureId !== featureId) {
          state.tcSelectedFeatureId = featureId;
          state.tcSelectedCategoryId = catId;
        } else if (state.tcSelectedCategoryId === catId) {
          state.tcSelectedCategoryId = null;
        } else {
          state.tcSelectedCategoryId = catId;
        }
        state.tcSelectedCaseId = null;
        renderTestCaseGeneration();
        return;
      }
      const featBtn = e.target.closest(".tcg-feature-btn");
      if (featBtn) {
        const featureId = featBtn.getAttribute("data-feature-id");
        if (state.tcSelectedFeatureId === featureId) {
          state.tcSelectedFeatureId = null;
          state.tcSelectedCategoryId = null;
        } else {
          state.tcSelectedFeatureId = featureId;
          state.tcSelectedCategoryId = null;
        }
        state.tcSelectedCaseId = null;
        renderTestCaseGeneration();
      }
    });

    $("device-type-select").addEventListener("change", (e) => {
      state.deviceType = e.target.value;
      state.testArea = "";
      state.productSpec = null;
      state.testSuite = null;
      state.features = [];
      state.selectedFeatureId = null;
      state.tcSelectedFeatureId = null;
      state.tcSelectedCategoryId = null;
      state.tcSelectedCaseId = null;
      resetTestScriptSelection();
      state.extractionRegistered = false;
      document.querySelectorAll(".test-area-option").forEach((el) => el.classList.remove("is-selected"));
      $("spec-file-name")?.classList.add("hidden");
      $("suite-file-name")?.classList.add("hidden");
      $("spec-upload-zone")?.classList.remove("has-file");
      $("suite-upload-zone")?.classList.remove("has-file");
      setPill($("spec-pill"), "Not uploaded", "");
      setPill($("suite-pill"), "Optional", "");
      $("extract-pending-callout")?.classList.add("hidden");
      clearDeviceClassificationFields();
      if (state.deviceType) {
        state.deviceClassification.category = state.deviceType;
        renderDeviceClassificationTable();
        updateDeviceClassificationStatus();
      }
      updateSetupReadiness();
    });

    document.querySelectorAll(".test-area-option").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (btn.disabled) return;
        selectTestArea(btn.dataset.area);
      });
    });

    renderDeviceClassificationTable();
    updateDeviceClassificationStatus();

    const bindUpload = (zoneId, btnId, kind) => {
      const zone = $(zoneId);
      const btn = $(btnId);
      if (!zone || !btn) return;
      const handler = (e) => {
        e.preventDefault();
        e.stopPropagation();
        pickDocument(kind);
      };
      zone.addEventListener("click", handler);
      zone.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") handler(e);
      });
      btn.addEventListener("click", handler);
    };
    bindUpload("spec-upload-zone", "spec-browse-btn", "spec");
    bindUpload("suite-upload-zone", "suite-browse-btn", "suite");

    $("extract-features-btn").addEventListener("click", extractFeatures);
    $("reset-setup-btn").addEventListener("click", resetSetup);

    $("manual-pass-btn")?.addEventListener("click", () => finishManual("pass"));
    $("manual-fail-btn")?.addEventListener("click", () => finishManual("fail"));
    $("semi-confirm-btn")?.addEventListener("click", finishSemi);

    const settingsBtn = $("settings-btn");
    if (settingsBtn) {
      settingsBtn.addEventListener("click", () => {
        const base =
          (window.platformConfig && window.platformConfig.apiBaseUrl) ||
          "http://127.0.0.1:8000";
        $("api-base-display").value = base;
        openModal("settings-modal");
      });
    }

    document.querySelectorAll("[data-close-modal]").forEach((el) => {
      el.addEventListener("click", () => closeModal(el.getAttribute("data-close-modal")));
    });
  }

  // ── Init ────────────────────────────────────────────

  bindEvents();
  updateSetupReadiness();
  updateHomeStats();
})();
