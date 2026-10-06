"""Execution result interpretation: cause groups, summaries, run comparison and exports."""

from __future__ import annotations

import html
import re
from collections import Counter
from typing import Any
from xml.etree import ElementTree as ET

from services.test_execution.script_sets import clean_product_name

VERDICTS = ["PASS", "FAIL", "ERROR", "BLOCKED_PRECONDITION", "NOT_APPLICABLE", "SKIPPED",
            "MANUAL_REVIEW", "STOPPED"]

CAUSES: dict[str, dict[str, str]] = {
    "failure": {
        "label": "Real failure",
        "description": "The device missed an expected result or SLA (crash, ANR, failed transition, slow metric).",
        "action": "Investigate: open the failed checks, the log and the evidence files.",
    },
    "spec_mismatch": {
        "label": "Spec mismatch",
        "description": "The device reports a different value than the product specification.",
        "action": "Expected on an emulator; a real finding on the target phone.",
    },
    "capability_missing": {
        "label": "Capability missing",
        "description": "The device does not have this capability (NOT_APPLICABLE / SKIPPED).",
        "action": "Nothing to fix; test on a device that has the capability.",
    },
    "blocked": {
        "label": "Blocked",
        "description": "A precondition was not met, so the case could not run.",
        "action": "Fix the precondition shown for each case and rerun.",
    },
    "needs_review": {
        "label": "Needs review",
        "description": "Manual checkpoints are waiting for a tester decision.",
        "action": "Open each case, check the device and mark Pass or Fail.",
    },
    "script_error": {
        "label": "Script / runtime error",
        "description": "The script crashed or timed out before reaching a verdict.",
        "action": "Open the log; regenerate the script or report a runtime bug.",
    },
    "stopped": {
        "label": "Stopped",
        "description": "Stopped or skipped by the user before a verdict.",
        "action": "Rerun if the result is needed.",
    },
    "passed": {"label": "Passed", "description": "All checks passed.", "action": ""},
    "not_run": {"label": "Not run", "description": "The run ended before this case started.", "action": ""},
}


def effective_verdict(case: dict[str, Any]) -> str | None:
    review = case.get("review") or {}
    return review.get("decision") or case.get("verdict")


def _spec_related(text: str, spec_values: dict[str, Any]) -> bool:
    return any(len(str(v)) >= 3 and str(v) not in ("true", "false") and str(v) in text
               for v in spec_values.values())


def classify(case: dict[str, Any]) -> str:
    verdict = effective_verdict(case)
    reason = case.get("reason") or ""
    if verdict is None:
        return "not_run"
    if verdict == "PASS":
        return "passed"
    if verdict == "FAIL":
        failed = case.get("failed_checks") or []
        spec = case.get("spec_values") or {}
        if reason.startswith("Spec mismatch") or (
                failed and all(_spec_related(f"{c.get('description')} {c.get('target')}", spec) for c in failed)):
            return "spec_mismatch"
        return "failure"
    return {
        "NOT_APPLICABLE": "capability_missing",
        "SKIPPED": "capability_missing",
        "BLOCKED_PRECONDITION": "blocked",
        "MANUAL_REVIEW": "needs_review",
        "ERROR": "script_error",
        "STOPPED": "stopped",
    }.get(verdict, "script_error")


_SPEC_MISMATCH = re.compile(
    r"device does not support (?P<name>[A-Z][A-Z0-9_]*)=(?P<value>.*?) from (?P<source>.*?)"
    r"(?: \(harness: (?P<harness>.*)\))?$")

# Device-reported variables that put a spec value in context, keyed by a fragment of the spec variable.
_RELATED_DEVICE_VARS = [
    ("PHOTO_RESOLUTION", ("SUPPORTED_PHOTO_RESOLUTIONS", "MAX_SUPPORTED_PHOTO_RESOLUTION")),
    ("VIDEO_RESOLUTION", ("SUPPORTED_VIDEO_RESOLUTIONS",)),
    ("VIDEO_PROFILE", ("SUPPORTED_VIDEO_PROFILES",)),
    ("ZOOM", ("MIN_ZOOM_RATIO", "MAX_ZOOM_RATIO")),
    ("ASPECT_RATIO", ("SUPPORTED_PHOTO_ASPECT_RATIOS",)),
]


def device_values(results: list[dict[str, Any]]) -> dict[str, str]:
    """Variables as discovered on the device: values that no product-spec value replaced."""
    out: dict[str, str] = {}
    for result in results:
        pinned = result.get("spec_values") or {}
        for name, value in (result.get("variables") or {}).items():
            if name not in pinned and name not in out and value not in (None, ""):
                out[name] = str(value)
    return out


def spec_comparison(case: dict[str, Any], result: dict[str, Any],
                    results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Spec value vs what the device reports, for spec-mismatch cases; results are the run's result JSONs."""
    if classify(case) != "spec_mismatch":
        return None
    spec = result.get("spec_values") or case.get("spec_values") or {}
    match = _SPEC_MISMATCH.search(case.get("reason") or "")
    device = device_values(results)
    names = [match.group("name")] if match else [k for k in spec if k in device]
    rows = []
    for name in names:
        related = []
        for fragment, candidates in _RELATED_DEVICE_VARS:
            if fragment in name:
                related += [{"name": c, "value": device[c]} for c in candidates if c != name and c in device]
        rows.append({
            "name": name,
            "spec": str(spec.get(name, match.group("value") if match else "")),
            "device": device.get(name),
            "related": related,
        })
    if not rows:
        return None
    return {
        "rows": rows,
        "source": clean_product_name((match.group("source") if match else None) or result.get("spec_source")),
        "harness": match.group("harness") if match else None,
    }


def blocked_hint(reason: str) -> str:
    text = (reason or "").lower()
    if "not installed" in text or ".apk" in text:
        return "Install the harness APK (check the script set's APK folder) and rerun."
    if "lab measurement" in text or "pass --var" in text:
        return "Enter the missing value under Variable overrides and rerun."
    if "battery" in text and "%" in text:
        return "Charge the device above the required level."
    if "temperature" in text or "thermal" in text:
        return "Let the device cool down, then rerun."
    if "device" in text and ("online" in text or "no adb" in text):
        return "Reconnect the device (check `adb devices`)."
    return "Resolve the precondition in the reason and rerun."


def summarize(execution: dict[str, Any]) -> dict[str, Any]:
    cases = execution.get("cases") or []
    by_verdict = Counter(effective_verdict(c) or "NOT_RUN" for c in cases)
    by_cause = Counter(classify(c) for c in cases)
    by_category: dict[str, Counter] = {}
    for c in cases:
        by_category.setdefault(c.get("category") or "other", Counter())[effective_verdict(c) or "NOT_RUN"] += 1
    decided = by_verdict["PASS"] + by_verdict["FAIL"] + by_verdict["ERROR"]
    return {
        "total": len(cases),
        "finished": sum(1 for c in cases if c.get("verdict")),
        "by_verdict": dict(by_verdict),
        "by_cause": dict(by_cause),
        "by_category": {k: dict(v) for k, v in by_category.items()},
        "pass_rate": round(100 * by_verdict["PASS"] / decided, 1) if decided else None,
        "duration_s": round(sum(c.get("duration_s") or 0 for c in cases), 1),
    }


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    left = {c["case_id"]: c for c in a.get("cases") or []}
    right = {c["case_id"]: c for c in b.get("cases") or []}
    rows = []
    for cid in sorted(set(left) | set(right)):
        va = effective_verdict(left[cid]) if cid in left else None
        vb = effective_verdict(right[cid]) if cid in right else None
        base = left.get(cid) or right.get(cid) or {}
        rows.append({"case_id": cid, "name": base.get("name"), "category": base.get("category"),
                     "a": va, "b": vb, "changed": va != vb,
                     "a_duration_s": (left.get(cid) or {}).get("duration_s"),
                     "b_duration_s": (right.get(cid) or {}).get("duration_s")})
    return {"a": _brief(a), "b": _brief(b), "rows": rows,
            "changed": sum(1 for r in rows if r["changed"])}


def _brief(ex: dict[str, Any]) -> dict[str, Any]:
    return {k: ex.get(k) for k in ("id", "run_id", "feature", "serial", "device", "created_at", "state")}


_RESULT_STATUS = re.compile(r"^(PASS|FAIL|SKIPPED|NOT_APPLICABLE|ERROR|HARNESS_ERROR|BLOCKED_PRECONDITION)\b")
_EXPECTED_IN_TEXT = re.compile(r"\b(?:matches|equals|is at least|is at most|within)\s+(.+?)\.?$", re.IGNORECASE)


def check_expected(check: dict[str, Any]) -> str:
    """What a check required; inferred for results recorded before checks carried "expected"."""
    if check.get("expected") not in (None, ""):
        return str(check["expected"])
    if check.get("operator"):
        return f"{check['operator']} {check.get('target', '')}".strip()
    desc = str(check.get("description") or "")
    missing = re.search(r"previous result has no '([^']+)'", desc, re.IGNORECASE)
    if missing:
        return f"'{missing.group(1)}' from the previous step"
    if re.search(r"\(command ran\)$", desc, re.IGNORECASE):
        return "exit code 0"
    in_text = _EXPECTED_IN_TEXT.search(desc)
    if in_text:
        return in_text.group(1)
    return "PASS" if _RESULT_STATUS.match(str(check.get("actual") or "")) else "condition holds"


def check_actual(check: dict[str, Any]) -> str:
    actual = check.get("actual")
    if actual in (None, ""):
        return "not returned" if "previous result has no" in str(check.get("description") or "") else "not recorded"
    return str(actual)


def junit_xml(execution: dict[str, Any]) -> str:
    cases = execution.get("cases") or []
    root = ET.Element("testsuites", name=f"{execution.get('feature')} {execution.get('id')}")
    for category in sorted({c.get("category") or "other" for c in cases}):
        group = [c for c in cases if (c.get("category") or "other") == category]
        suite = ET.SubElement(root, "testsuite", name=f"{execution.get('feature')}.{category}")
        counts = Counter()
        for c in group:
            verdict = effective_verdict(c)
            tc = ET.SubElement(suite, "testcase", classname=f"{execution.get('feature')}.{category}",
                               name=f"{c['case_id']} {c.get('name') or ''}".strip(),
                               time=str(c.get("duration_s") or 0))
            reason = c.get("reason") or ""
            if verdict == "FAIL":
                failed = "\n".join(
                    f"FAILED {k.get('description')}: expected {check_expected(k)}, actual {check_actual(k)}"
                    for k in c.get("failed_checks") or [])
                ET.SubElement(tc, "failure", message=reason[:500], type=classify(c)).text = \
                    f"{reason}\n\n{failed}" if failed else reason
                counts["failures"] += 1
            elif verdict in ("ERROR", None, "STOPPED"):
                ET.SubElement(tc, "error", message=(reason or verdict or "not run")[:500])
                counts["errors"] += 1
            elif verdict != "PASS":
                ET.SubElement(tc, "skipped", message=f"{verdict}: {reason}"[:500])
                counts["skipped"] += 1
        suite.set("tests", str(len(group)))
        for key in ("failures", "errors", "skipped"):
            suite.set(key, str(counts[key]))
        suite.set("time", str(round(sum(c.get("duration_s") or 0 for c in group), 1)))
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


_VERDICT_COLOR = {"PASS": "#166534", "FAIL": "#b91c1c", "ERROR": "#9a3412", "MANUAL_REVIEW": "#92400e",
                  "BLOCKED_PRECONDITION": "#6b21a8", "NOT_APPLICABLE": "#475569", "SKIPPED": "#475569",
                  "STOPPED": "#475569"}


def html_report(execution: dict[str, Any], details: dict[str, dict[str, Any]]) -> str:
    """Self-contained HTML report; details maps case_id to its result JSON."""
    e = html.escape
    summary = summarize(execution)
    device = execution.get("device") or {}
    rows = []
    for c in execution.get("cases") or []:
        verdict = effective_verdict(c) or "NOT RUN"
        checks = (details.get(c["case_id"]) or {}).get("checks") or []
        check_rows = "".join(
            f"<tr><td>{'✔' if k.get('passed') else '✘'}</td><td>{e(str(k.get('description')))}</td>"
            f"<td>expected <b>{e(check_expected(k))}</b></td><td>actual <b>{e(check_actual(k))}</b></td></tr>"
            for k in checks)
        review = c.get("review") or {}
        rows.append(
            f"<tr><td>{e(c['case_id'])}</td><td>{e(c.get('name') or '')}</td><td>{e(c.get('category') or '')}</td>"
            f"<td style='color:{_VERDICT_COLOR.get(verdict, '#111')};font-weight:600'>{e(verdict)}"
            f"{' (reviewed)' if review else ''}</td><td>{e(CAUSES[classify(c)]['label'])}</td>"
            f"<td>{e(c.get('reason') or '')}{('<br><i>Review: ' + e(review.get('note') or '') + '</i>') if review.get('note') else ''}"
            f"{('<table class=checks>' + check_rows + '</table>') if check_rows else ''}</td>"
            f"<td>{c.get('duration_s') or ''}</td></tr>")
    verdicts = "".join(f"<span class=chip>{e(v)}: {n}</span>" for v, n in summary["by_verdict"].items())
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Test execution {e(execution['id'])}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;color:#0f172a;margin:24px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #e2e8f0;padding:6px 8px;font-size:12px;vertical-align:top;text-align:left}}th{{background:#f8fafc}}
.chip{{display:inline-block;border:1px solid #cbd5e1;border-radius:999px;padding:2px 10px;margin:0 6px 6px 0;font-size:12px}}
table.checks td{{border:none;padding:1px 6px}}</style></head><body>
<h2>Test execution {e(execution['id'])}</h2>
<p>Script set <b>{e(execution.get('run_id') or '')}</b> ({e(str(execution.get('feature')))}) ·
Device <b>{e(' '.join(filter(None, [device.get('manufacturer'), device.get('model')])) or execution.get('serial') or '')}</b>
({e(execution.get('serial') or '')}, Android {e(str(device.get('android_version') or '?'))}) ·
{e(execution.get('started_at') or '')} → {e(execution.get('finished_at') or '')}</p>
<p>{verdicts}<span class=chip>Pass rate: {summary['pass_rate'] if summary['pass_rate'] is not None else '–'}%</span></p>
<table><tr><th>Case</th><th>Name</th><th>Category</th><th>Verdict</th><th>Cause</th><th>Reason / checks</th><th>Seconds</th></tr>
{''.join(rows)}</table></body></html>"""
