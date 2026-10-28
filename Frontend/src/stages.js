(() => {
  "use strict";

  const P = window.pipeline;
  const { esc, dot, pill, STATUS, GATE } = P;
  const $ = (id) => document.getElementById(id);

  const MODE = {
    auto: { label: "Automated", cls: "is-auto" },
    semi: { label: "Semi-auto", cls: "is-semi" },
    manual: { label: "Manual", cls: "is-manual" }
  };

  const view = { stage: null, sub: null };

  function findStage(id) {
    return P.STAGES.find((s) => s.id === id);
  }

  function nextRouteAfter(stage) {
    const i = P.STAGES.indexOf(stage);
    const next = P.STAGES[i + 1];
    return next ? { route: P.routeOfStage(next), label: next.name } : { route: "reports", label: "Reports" };
  }

  function cursorKey(stage, sub) {
    return `${stage.id}.${sub.id}`;
  }

  function firstPending(stage, sub) {
    const items = P.itemsOf(sub);
    const i = items.findIndex((_, idx) => !(P.result(P.resultKey(stage.id, sub.id, idx)) || {}).verdict);
    return i === -1 ? 0 : i;
  }

  function cursor(stage, sub) {
    const k = cursorKey(stage, sub);
    if (P.store.cursor[k] == null) P.store.cursor[k] = firstPending(stage, sub);
    return P.store.cursor[k];
  }

  function tally(c) {
    return `<span class="fl-tally"><i class="hm-tone is-pass"></i>${c.pass} passed</span>
      <span class="fl-tally"><i class="hm-tone is-fail"></i>${c.fail} failed${c.critical ? ` (${c.critical} critical)` : ""}</span>
      ${c.skip ? `<span class="fl-tally"><i class="hm-tone is-info"></i>${c.skip} skipped</span>` : ""}
      <span class="fl-tally"><i class="hm-tone is-muted"></i>${c.pending} pending</span>`;
  }

  // ── Gate banner ─────────────────────────────────────

  function gateBanner(stage, summary) {
    if (!summary.critical) return "";
    const n = summary.critical;
    const plural = n > 1 ? "s" : "";
    const next = P.store.round + 1;
    if (stage.gate === "reject") {
      return `<section class="fl-gate is-reject">
        <div>
          <div class="fl-gate-title">Device rejected at ${esc(stage.name)}</div>
          <p>${n} critical failure${plural}. Under the CSP gate policy the device returns to the OEM, and a new submission round restarts at Regulatory Certifications.</p>
        </div>
        <div class="btn-row">
          <button type="button" class="primary" data-new-round="Rejected at ${esc(stage.name)}">Start round ${next} (OEM resubmission)</button>
          <button type="button" class="secondary" data-route="oem:rca">Send to RCA</button>
        </div>
      </section>`;
    }
    if (stage.gate === "fix") {
      return `<section class="fl-gate is-fix">
        <div>
          <div class="fl-gate-title">Needs fix: ${n} critical issue${plural}</div>
          <p>The device stays in the cycle, but approval is held until the OEM delivers a fix. The fixed build restarts at Regulatory Certifications.</p>
        </div>
        <div class="btn-row">
          <button type="button" class="primary" data-new-round="Needs fix at ${esc(stage.name)}">Start round ${next} (OEM fix)</button>
        </div>
      </section>`;
    }
    return `<section class="fl-gate is-report">
      <div>
        <div class="fl-gate-title">${n} critical finding${plural}</div>
        <p>Findings at this stage do not block approval. They are included in the consolidated report.</p>
      </div>
      <div class="btn-row"><button type="button" class="secondary" data-route="reports:consolidated">Open report</button></div>
    </section>`;
  }

  // ── Stage overview ──────────────────────────────────

  function extraSections(stage) {
    const section = P.stageSections[stage.id];
    return section ? section(stage) : "";
  }

  function renderEmptyStage(stage) {
    const next = nextRouteAfter(stage);
    $("flow-root").innerHTML = `
      ${P.headPanel({
        title: `${esc(stage.name)} · ${esc(stage.title)}`,
        desc: stage.desc,
        env: stage.env,
        gate: stage.gate,
        status: "todo"
      })}
      ${extraSections(stage)}
      <section class="panel fl-section">
        <div class="fl-placeholder">The ${esc(stage.name)} substages will be added here.</div>
      </section>
      <div class="panel fl-footer">
        <div class="fl-tallies"></div>
        <button type="button" class="primary" data-route="${esc(next.route)}">Next: ${esc(next.label)} →</button>
      </div>`;
  }

  function renderStage(stage) {
    if (!P.hasSubs(stage)) {
      renderEmptyStage(stage);
      return;
    }
    const s = P.stageSummary(stage);
    const unit = stage.template === "measure" ? "KPIs" : "scenarios";
    const cards = stage.substages.map((sub, i) => {
      const c = P.substageCounts(stage, sub);
      const status = P.statusFromCounts(c);
      return `<button type="button" class="fl-sub-card is-${status}" data-route="stage:${stage.id}:${sub.id}">
        <span class="fl-sub-top">
          <span class="fl-sub-num">${String(i + 1).padStart(2, "0")}</span>
          ${dot(status)}
        </span>
        <span class="fl-sub-name">${esc(sub.name)}</span>
        <span class="fl-sub-count">${c.total} ${unit}</span>
        <span class="fl-sub-foot">
          <span>${esc(STATUS[status].label)}</span>
          <span>${c.pass + c.skip}/${c.total}${c.critical ? ` · ${c.critical} critical` : ""}</span>
        </span>
      </button>`;
    }).join("");
    const next = nextRouteAfter(stage);

    $("flow-root").innerHTML = `
      ${P.headPanel({
        title: `${esc(stage.name)} · ${esc(stage.title)}`,
        desc: stage.desc,
        env: stage.env,
        gate: stage.gate,
        status: s.status,
        side: P.progressSide(`${s.subsDone} of ${s.subsTotal} substages complete`, s.subsDone, s.subsTotal)
      })}
      ${gateBanner(stage, s)}
      ${extraSections(stage)}
      <div class="fl-section-title">Substages</div>
      <div class="fl-sub-grid">${cards}</div>
      <div class="panel fl-footer">
        <div class="fl-tallies">${tally(s)}</div>
        <button type="button" class="primary" data-route="${esc(next.route)}">Next: ${esc(next.label)} →</button>
      </div>`;
  }

  // ── Substage page ───────────────────────────────────

  function stepper(stage, sub) {
    return `<div class="fl-stepper" role="tablist" aria-label="${esc(stage.name)} substages">
      ${stage.substages.map((s, i) => {
        const status = P.statusFromCounts(P.substageCounts(stage, s));
        const current = s.id === sub.id;
        const mark = status === "done" ? P.svg("check") : status === "failed" ? P.svg("cross") : String(i + 1);
        return `<button type="button" class="fl-step ${current ? "is-current" : ""} is-${status}" role="tab" aria-selected="${current}"
            data-route="stage:${stage.id}:${s.id}" title="${esc(s.name)}">
          <span class="fl-step-circle">${mark}</span>
          <span class="fl-step-label">${esc(s.name)}</span>
        </button>`;
      }).join('<span class="fl-step-line" aria-hidden="true"></span>')}
    </div>`;
  }

  function checklistBody(stage, sub) {
    const idx = cursor(stage, sub);
    const items = sub.scenarios;
    const sc = items[idx];
    const r = P.result(P.resultKey(stage.id, sub.id, idx)) || {};
    const mode = MODE[sc.mode] || MODE.manual;
    const verdictPill = r.verdict
      ? pill(r.verdict === "pass" ? "done" : r.verdict === "fail" ? "failed" : "progress", r.verdict === "pass" ? "Passed" : r.verdict === "fail" ? (r.critical ? "Failed · critical" : "Failed") : "Skipped")
      : "";

    const list = items.map((item, i) => {
      const ir = P.result(P.resultKey(stage.id, sub.id, i)) || {};
      const status = ir.verdict === "pass" ? "done" : ir.verdict === "fail" ? "failed" : ir.verdict === "skip" ? "progress" : i === idx ? "progress" : "todo";
      const label = ir.verdict === "pass" ? "Pass" : ir.verdict === "fail" ? "Fail" : ir.verdict === "skip" ? "Skipped" : i === idx ? "Current" : "Pending";
      return `<button type="button" class="fl-scn-row ${i === idx ? "is-current" : ""}" data-scn="${i}">
        ${dot(i === idx && !ir.verdict ? "progress" : status)}
        <span class="fl-scn-code">S${i + 1}</span>
        <span class="fl-scn-name">${esc(item.name)}</span>
        ${ir.verdict === "fail" && ir.critical ? '<span class="fl-crit">Critical</span>' : ""}
        <span class="fl-scn-state is-${status}">${label}</span>
      </button>`;
    }).join("");

    return `<div class="fl-run-grid">
      <section class="panel fl-scn-list">
        <div class="panel-head-row"><h3>Scenarios</h3><span class="fl-muted-small">${items.length}</span></div>
        <div class="fl-scn-rows">${list}</div>
      </section>
      <section class="panel fl-scn-detail" data-stage="${stage.id}" data-sub="${sub.id}" data-idx="${idx}">
        <div class="fl-scn-head">
          <div>
            <div class="fl-scn-kicker">Scenario ${idx + 1} of ${items.length}</div>
            <h3 class="fl-scn-title">S${idx + 1} · ${esc(sc.name)}</h3>
          </div>
          <div class="btn-row">${verdictPill}<span class="status-pill ${mode.cls}">${mode.label}</span></div>
        </div>
        <div class="fl-label">Steps</div>
        <ol class="fl-steps">${sc.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>
        <div class="fl-label">Expected result</div>
        <p class="fl-expected">${esc(sc.expected)}</p>
        <label class="fl-label" for="fl-actual">Actual result</label>
        <textarea id="fl-actual" class="input" rows="2" data-field="actual" placeholder="What you observed on the device">${esc(r.actual || "")}</textarea>
        <label class="fl-label" for="fl-notes">Evidence / notes</label>
        <input id="fl-notes" class="input" data-field="notes" placeholder="Log file, screenshot path or a note" value="${esc(r.notes || "")}" />
        <label class="fl-check"><input type="checkbox" data-field="critical" ${r.critical ? "checked" : ""} /> Mark as critical (applies the ${esc(GATE[stage.gate].label.replace("Gate: ", ""))} gate)</label>
        <div class="fl-verdict-row">
          <button type="button" class="soft-danger" data-verdict="fail">Fail</button>
          <button type="button" class="secondary" data-verdict="skip">Skip</button>
          <button type="button" class="soft-success" data-verdict="pass">Pass</button>
          ${r.verdict ? '<button type="button" class="secondary" data-verdict="clear">Clear</button>' : ""}
          <span class="fl-spacer"></span>
          <button type="button" class="secondary" data-step="-1" ${idx === 0 ? "disabled" : ""}>← Previous</button>
          <button type="button" class="secondary" data-step="1" ${idx === items.length - 1 ? "disabled" : ""}>Next →</button>
        </div>
        <p class="fl-kbd">Keyboard: P pass · F fail · S skip · ← → move between scenarios</p>
      </section>
    </div>`;
  }

  function fmtThreshold(k) {
    return `${k.op === ">=" ? "≥" : "≤"} ${k.target}${k.unit ? ` ${k.unit}` : ""}`;
  }

  function measureBody(stage, sub) {
    const rows = sub.kpis.map((k, i) => {
      const r = P.result(P.resultKey(stage.id, sub.id, i)) || {};
      const status = r.verdict === "pass" ? "done" : r.verdict === "fail" ? "failed" : "todo";
      return `<tr>
        <td><div class="fl-kpi-name">${esc(k.name)}</div></td>
        <td class="fl-mono">${esc(fmtThreshold(k))}</td>
        <td><div class="fl-measure">
          <input class="input fl-measure-input" type="number" step="any" data-kpi="${i}" value="${r.measured ?? ""}" placeholder="—" aria-label="Measured ${esc(k.name)}" />
          ${k.unit ? `<span class="fl-unit">${esc(k.unit)}</span>` : ""}
        </div></td>
        <td>${r.verdict ? pill(status, r.verdict === "pass" ? "Pass" : "Fail") : '<span class="fl-muted-small">Not measured</span>'}</td>
        <td><label class="fl-check fl-check-inline"><input type="checkbox" data-kpi-critical="${i}" ${r.critical ? "checked" : ""} /> Critical</label></td>
      </tr>`;
    }).join("");

    return `<section class="panel fl-section">
      <div class="panel-head-row"><h3>Measurements</h3><span class="fl-muted-small">Enter the measured value; the verdict is computed against the threshold.</span></div>
      <table class="spec-table fl-table fl-kpi-table">
        <thead><tr><th>KPI</th><th>Threshold</th><th>Measured</th><th>Result</th><th>Severity</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </section>`;
  }

  function renderSubstage(stage, sub) {
    const c = P.substageCounts(stage, sub);
    const status = P.statusFromCounts(c);
    const i = stage.substages.indexOf(sub);
    const nextSub = stage.substages[i + 1];
    const next = nextSub
      ? { route: `stage:${stage.id}:${nextSub.id}`, label: nextSub.name }
      : nextRouteAfter(stage);
    const done = c.pass + c.skip;
    const unit = stage.template === "measure" ? "KPIs" : "scenarios";

    $("flow-root").innerHTML = `
      ${stepper(stage, sub)}
      ${P.headPanel({
        title: `${String(i + 1).padStart(2, "0")} · ${esc(sub.name)}`,
        desc: `${stage.name} · ${c.total} ${unit}`,
        env: stage.env,
        gate: stage.gate,
        status,
        side: P.progressSide(`${done} of ${c.total} complete`, done, c.total)
      })}
      ${stage.template === "measure" ? measureBody(stage, sub) : checklistBody(stage, sub)}
      <div class="panel fl-footer">
        <div class="fl-tallies">${tally(c)}</div>
        <div class="btn-row">
          <button type="button" class="secondary" data-route="stage:${stage.id}">${esc(stage.name)} overview</button>
          <button type="button" class="primary" data-route="${esc(next.route)}">Next: ${esc(next.label)} →</button>
        </div>
      </div>`;
  }

  P.renderers.stage = (stageId, subId) => {
    const stage = findStage(stageId);
    if (!stage) return;
    const sub = subId && P.hasSubs(stage) ? stage.substages.find((s) => s.id === subId) : null;
    view.stage = stage;
    view.sub = sub;
    if (sub) renderSubstage(stage, sub);
    else renderStage(stage);
  };

  // ── Actions ─────────────────────────────────────────

  function onSubstagePage() {
    return Boolean(view.stage && view.sub && P.store.route === `stage:${view.stage.id}:${view.sub.id}`);
  }

  function logTransition(stage, sub, before) {
    const after = P.statusFromCounts(P.substageCounts(stage, sub));
    if (after === before) return;
    if (after === "done") P.log(`${stage.name} · ${sub.name} passed.`, "pass");
    if (after === "failed") P.log(`${stage.name} · ${sub.name} has a failure.`, "fail");
    const s = P.stageSummary(stage);
    if (after === "done" && s.status === "done") P.log(`${stage.name} completed: all ${s.subsTotal} substages passed.`, "pass");
  }

  function setVerdict(verdict) {
    if (!onSubstagePage() || view.stage.template === "measure") return;
    const { stage, sub } = view;
    const idx = cursor(stage, sub);
    const key = P.resultKey(stage.id, sub.id, idx);
    const before = P.statusFromCounts(P.substageCounts(stage, sub));
    if (verdict === "clear") {
      P.setResult(key, { verdict: null, at: null });
    } else {
      P.setResult(key, {
        verdict,
        actual: $("fl-actual")?.value || "",
        notes: $("fl-notes")?.value || "",
        at: new Date()
      });
      const r = P.result(key);
      if (verdict === "fail" && r.critical) P.log(`${stage.name} · ${sub.name} · S${idx + 1} failed (critical).`, "fail");
      const nextPending = sub.scenarios.findIndex((_, i) => i > idx && !(P.result(P.resultKey(stage.id, sub.id, i)) || {}).verdict);
      if (nextPending !== -1) P.store.cursor[cursorKey(stage, sub)] = nextPending;
    }
    logTransition(stage, sub, before);
    P.refresh();
  }

  function step(delta) {
    if (!onSubstagePage() || view.stage.template === "measure") return;
    const { stage, sub } = view;
    const idx = cursor(stage, sub) + delta;
    if (idx < 0 || idx >= sub.scenarios.length) return;
    P.store.cursor[cursorKey(stage, sub)] = idx;
    P.refresh();
  }

  document.addEventListener("click", (e) => {
    const root = $("view-flow");
    if (!root || !root.contains(e.target)) return;
    const v = e.target.closest("[data-verdict]");
    if (v) return setVerdict(v.dataset.verdict);
    const s = e.target.closest("[data-step]");
    if (s && !s.disabled) return step(Number(s.dataset.step));
    const row = e.target.closest("[data-scn]");
    if (row && onSubstagePage()) {
      P.store.cursor[cursorKey(view.stage, view.sub)] = Number(row.dataset.scn);
      P.refresh();
      return;
    }
    const nr = e.target.closest("[data-new-round]");
    if (nr) P.startNewRound(nr.dataset.newRound);
  });

  document.addEventListener("input", (e) => {
    if (!onSubstagePage()) return;
    const field = e.target.dataset && e.target.dataset.field;
    if (field !== "actual" && field !== "notes") return;
    const { stage, sub } = view;
    P.setResult(P.resultKey(stage.id, sub.id, cursor(stage, sub)), { [field]: e.target.value });
  });

  document.addEventListener("change", (e) => {
    if (!onSubstagePage()) return;
    const { stage, sub } = view;
    const t = e.target;
    const before = P.statusFromCounts(P.substageCounts(stage, sub));

    if (t.dataset.field === "critical") {
      P.setResult(P.resultKey(stage.id, sub.id, cursor(stage, sub)), { critical: t.checked });
    } else if (t.dataset.kpi != null) {
      const i = Number(t.dataset.kpi);
      const k = sub.kpis[i];
      const raw = t.value.trim();
      const value = raw === "" ? NaN : Number(raw);
      const key = P.resultKey(stage.id, sub.id, i);
      if (Number.isNaN(value)) {
        P.setResult(key, { measured: null, verdict: null, at: null });
      } else {
        const ok = k.op === ">=" ? value >= k.target : value <= k.target;
        P.setResult(key, { measured: value, verdict: ok ? "pass" : "fail", at: new Date() });
        if (!ok && P.result(key).critical) P.log(`${stage.name} · ${k.name} out of threshold (critical).`, "fail");
      }
    } else if (t.dataset.kpiCritical != null) {
      P.setResult(P.resultKey(stage.id, sub.id, Number(t.dataset.kpiCritical)), { critical: t.checked });
    } else {
      return;
    }
    logTransition(stage, sub, before);
    P.refresh();
  });

  document.addEventListener("keydown", (e) => {
    if (!onSubstagePage() || view.stage.template === "measure") return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (["input", "textarea", "select"].includes(tag) || e.metaKey || e.ctrlKey || e.altKey) return;
    if (!$("view-flow").classList.contains("active")) return;
    const key = e.key.toLowerCase();
    if (key === "p") setVerdict("pass");
    else if (key === "f") setVerdict("fail");
    else if (key === "s") setVerdict("skip");
    else if (e.key === "ArrowRight") step(1);
    else if (e.key === "ArrowLeft") step(-1);
    else return;
    e.preventDefault();
  });
})();
