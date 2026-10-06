"""Generate UI briefs for the default Camera test cases (one-off, offline).

Reads Backend/data/test_cases/camera/{category}.json (80 cases), asks the LLM
for a short description, objective, 5-6 one-line test steps and verification
checks per case, validates the output against the source case, and writes
Frontend/src/data/test_case_briefs.js for the Test Case Generation page.

Run from Backend/:  python scripts/generate_test_case_briefs.py
Refresh only execution / prerequisites / expected results (no LLM, keeps
existing briefs):   python scripts/generate_test_case_briefs.py --static-only
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from llm.azure_client import chat_completion, parse_json_content  # noqa: E402

FEATURE = "camera"
FEATURE_NAME = "Camera"
CATEGORIES = [
    ("functionality", "Functionality"),
    ("performance", "Performance"),
    ("reliability", "Reliability"),
    ("security", "Security"),
]
SOURCE_DIR = BACKEND_ROOT / "data" / "test_cases" / FEATURE
OUTPUT_PATH = BACKEND_ROOT.parent / "Frontend" / "src" / "data" / "test_case_briefs.js"

MAX_STEP_WORDS = 16
MAX_ATTEMPTS = 3
PLACEHOLDER_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

SYSTEM_PROMPT = """You turn a structured device test case into a short brief for a test engineer UI.

Return JSON only:
{
  "description": "one short, meaningful sentence (8-14 words) starting with a verb",
  "objective": "one sentence stating what the test proves",
  "steps": ["5 or 6 steps"],
  "verification": ["3 to 5 checks"]
}

Rules for "steps":
- Exactly 5 or 6 steps, in execution order.
- Each step is ONE simple line, imperative, at most 14 words.
- Describe how the test is executed on the device in plain English.
- No shell commands, package names, regexes, file paths or code.

Rules for "verification":
- Each check is ONE simple line that states a pass condition.
- Copy every numeric threshold, unit and count exactly as given in the source.

General rules:
- Use only facts present in the source test case. Do not invent features, values or tools.
- Never output ${...} placeholders; describe them in plain words
  (e.g. ${REAR_PRIMARY_PHOTO_RESOLUTION} -> "the supported rear photo resolution").
- Do not mention test IDs."""


def _resolve_constants(value, constants: dict):
    """Replace ${CONST} with suite constant values so counts/durations are concrete."""
    text = json.dumps(value)

    def sub(m: re.Match) -> str:
        key = m.group(1)
        return str(constants[key]) if key in constants else m.group(0)

    return json.loads(PLACEHOLDER_RE.sub(sub, text))


def _case_source(tc: dict, constants: dict) -> dict:
    """Compact, resolved view of the case that the LLM is allowed to use."""
    tc = _resolve_constants(tc, constants)
    if "test_metadata" in tc:
        meta = tc["test_metadata"]
        return {
            "test_name": meta.get("test_name"),
            "target_scenario": meta.get("target_scenario"),
            "feasibility": meta.get("feasibility"),
            "prerequisites": tc.get("prerequisites"),
            "setup": [s.get("description") for s in tc.get("setup_commands") or []],
            "execution_procedure": [
                {
                    "step_name": s.get("step_name"),
                    "command": (s.get("payload") or {}).get("command"),
                    "metric": (s.get("validation_checkpoint") or {}).get("metric_key"),
                    "hint": s.get("code_gen_hint"),
                }
                for s in tc.get("execution_procedure") or []
            ],
            "verification_slas": tc.get("verification_slas"),
            "evidence": tc.get("evidence_collection"),
            "teardown": [s.get("description") for s in tc.get("teardown_commands") or []],
        }
    return {
        "test_name": tc.get("test_name"),
        "objective": tc.get("objective"),
        "execution": tc.get("execution"),
        "prerequisites": tc.get("prerequisites"),
        "steps": [s.get("action") for s in tc.get("steps") or []],
        "expected_results": tc.get("expected_results"),
        "evidence": tc.get("evidence"),
    }


def _validate(brief, source_text: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(brief, dict):
        return ["Output is not a JSON object."]
    for key in ("description", "objective"):
        if not isinstance(brief.get(key), str) or not brief[key].strip():
            errors.append(f'"{key}" must be a non-empty string.')
    steps = brief.get("steps")
    if not isinstance(steps, list) or not 5 <= len(steps) <= 6:
        errors.append('"steps" must contain 5 or 6 items.')
    else:
        for i, s in enumerate(steps, 1):
            if not isinstance(s, str) or not s.strip():
                errors.append(f"Step {i} is empty.")
            elif len(s.split()) > MAX_STEP_WORDS:
                errors.append(f"Step {i} is too long; keep it to one short line.")
    checks = brief.get("verification")
    if not isinstance(checks, list) or not 3 <= len(checks) <= 5:
        errors.append('"verification" must contain 3 to 5 items.')

    output_text = json.dumps(brief)
    if "${" in output_text:
        errors.append("Remove ${...} placeholders and use plain words.")
    source_numbers = set(NUMBER_RE.findall(source_text))
    unknown = sorted(
        n for n in set(NUMBER_RE.findall(output_text)) if n not in source_numbers
    )
    if unknown:
        errors.append(
            f"These numbers are not in the source test case: {', '.join(unknown)}. "
            "Use only values from the source."
        )
    return errors


def _generate_brief(tc: dict, constants: dict) -> dict:
    source = _case_source(tc, constants)
    source_text = json.dumps(source, ensure_ascii=False)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Source test case:\n{source_text}"},
    ]
    errors: list[str] = []
    for _ in range(MAX_ATTEMPTS):
        content, _usage = chat_completion(
            messages, temperature=0.0, response_format={"type": "json_object"}
        )
        brief = parse_json_content(content)
        errors = _validate(brief, source_text)
        if not errors:
            return {
                "description": brief["description"].strip(),
                "objective": brief["objective"].strip(),
                "steps": [s.strip() for s in brief["steps"]],
                "verification": [v.strip() for v in brief["verification"]],
            }
        messages += [
            {"role": "assistant", "content": content},
            {"role": "user", "content": "Fix these problems and return the full JSON again:\n- " + "\n- ".join(errors)},
        ]
    raise RuntimeError(f"{tc.get('ui_id')}: invalid brief after retries: {errors}")


EXECUTION_LABELS = {
    "AUTO": "Automated",
    "FULLY_AUTOMATED": "Automated",
    "SEMI": "Semi-Automated",
    "SEMI_AUTOMATED": "Semi-Automated",
    "AUTO_SEMI": "Automated / Semi-Automated",
    "SEMI_AUTO": "Automated / Semi-Automated",
    "SEMI_LAB": "Semi-Automated (Lab Setup)",
}

# Phrases whose placeholder value is device-specific and not in the suite.
PLACEHOLDER_PHRASES = [
    (re.compile(r"greater than \$\{MIN_FREE_STORAGE_MB\} MB"), "above the minimum required"),
    (re.compile(r"greater than \$\{MIN_BATTERY_PERCENT\}%"), "above the minimum required"),
    (re.compile(r"on \$\{FLASH_SUPPORTED_CAMERA\}"), "on the test camera"),
    (re.compile(r"at \$\{PORTRAIT_SUBJECT_DISTANCE\}"), "at the required portrait distance"),
    (re.compile(r"under \$\{LIGHT_CONDITION\}"), "under the test lighting condition"),
    (re.compile(r"for \$\{RECORDING_DURATION_SEC\} seconds"), "for the configured recording duration"),
]
PLACEHOLDER_WORDS = {
    "REAR_PRIMARY_CAMERA": "rear primary camera",
    "FRONT_PRIMARY_CAMERA": "front primary camera",
    "FOCUS_TEST_TARGET": "focus test target",
    "LIGHT_CONDITION": "lighting condition",
    "HDR_TEST_SCENE": "HDR test scene",
    "PORTRAIT_TEST_SCENE": "portrait test scene",
    "LOW_LIGHT_TEST_SCENE": "low-light test scene",
    "REAR_PRIMARY_PHOTO_RESOLUTION": "the configured rear photo resolution",
    "FRONT_PRIMARY_PHOTO_RESOLUTION": "the configured front photo resolution",
    "DEFAULT_IMAGE_FORMAT": "the default image format",
    "REAR_PRIMARY_CAMERA_ID": "the rear primary camera ID",
    "ULTRAWIDE_CAMERA": "the ultrawide camera",
    "VIDEO_RESOLUTION": "the configured video resolution",
    "VIDEO_FPS": "the configured frame rate",
    "FPS_TOLERANCE": "the allowed tolerance",
    "SUPPORTED_HDR_MODE": "the supported HDR mode",
    "HDR_CAPTURE_TYPE": "the HDR capture",
    "NIGHT_MODE": "night mode",
}
SLA_UNITS = {"ms": "ms", "MB": "MB", "percent": "%", "fps": "fps", "sec": "seconds"}


def _plain_line(line: str) -> str:
    for pattern, words in PLACEHOLDER_PHRASES:
        line = pattern.sub(words, line)

    def sub(m: re.Match) -> str:
        key = m.group(1)
        return PLACEHOLDER_WORDS.get(key, key.lower().replace("_", " "))

    line = PLACEHOLDER_RE.sub(sub, line).strip()
    return line[:1].upper() + line[1:]


def _execution_label(tc: dict) -> str:
    meta = tc.get("test_metadata") or {}
    code = str(tc.get("execution") or meta.get("feasibility") or "").strip().upper()
    return EXECUTION_LABELS.get(code, code.replace("_", " ").title())


def _number(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


def _sla_line(sla: dict) -> str:
    name = sla.get("metric_name") or sla.get("metric_key", "")
    if str(sla.get("metric_key", "")).startswith("p95_"):
        name += " (95th percentile)"
    op, unit, target = sla.get("operator"), sla.get("unit"), sla.get("target_value")
    if unit == "boolean":
        return f"{name}: {'passes' if target else 'fails'}"
    value = _number(target)
    suffix = SLA_UNITS.get(unit, "")
    if suffix == "%":
        value += "%"
    elif suffix:
        value += f" {suffix}"
    condition = {
        "<=": "at most",
        ">=": "at least",
        "<": "below",
        ">": "above",
        "==": "exactly",
    }.get(op, op or "")
    return f"{name}: {condition} {value}".strip()


def _expected_results(tc: dict, constants: dict) -> list[str]:
    tc = _resolve_constants(tc, constants)
    if "verification_slas" in tc:
        return [_sla_line(s) for s in tc.get("verification_slas") or []]
    return [_plain_line(str(r)) for r in tc.get("expected_results") or [] if str(r).strip()]


def _structured_prerequisites(pre: dict) -> list[str]:
    """Plain lines for Performance / Reliability / Security prerequisite objects."""
    lines: list[str] = []
    battery = pre.get("battery_state") or {}
    display = pre.get("display_state") or {}
    hygiene = pre.get("environment_hygiene") or {}
    thermal = pre.get("thermal_limits") or {}

    if pre.get("device_scope"):
        lines.append("Use a dedicated test device only")
    if pre.get("camera_test_app_installed"):
        lines.append("Camera test app is installed")
    if pre.get("helper_apps_required"):
        lines.append("Helper test apps are installed")
    if pre.get("secure_lock_required"):
        lines.append("A secure screen lock is set on the device")
    if pre.get("ota_baseline_required"):
        lines.append("Pre-update baseline state is recorded before the OTA update")

    if battery.get("min_charge_pct") is not None:
        lines.append(f"Battery charge is at least {battery['min_charge_pct']}%")
    if display.get("screen_on"):
        orientation = display.get("initial_orientation")
        lines.append(
            f"Screen is on in {orientation} orientation" if orientation else "Screen is on"
        )
    if hygiene.get("min_free_storage_gb") is not None:
        lines.append(f"At least {hygiene['min_free_storage_gb']} GB of free storage is available")
    if hygiene.get("force_stop_packages"):
        lines.append("Other camera apps are force-stopped")
    if hygiene.get("background_workload_policy"):
        lines.append("Background workloads are minimized")
    if thermal.get("battery_temp_max_c") is not None:
        lines.append(f"Battery temperature is at most {thermal['battery_temp_max_c']} °C")
    if thermal.get("soc_temp_max_c") is not None:
        lines.append(f"SoC temperature is at most {thermal['soc_temp_max_c']} °C")
    if thermal.get("abort_on_critical_thermal_status"):
        lines.append("Test stops if the device reaches a critical thermal state")

    if pre.get("user_data_protection"):
        lines.append("Do not access unrelated user media, credentials or private app data")
    return lines


def _prerequisites(tc: dict) -> list[str]:
    pre = tc.get("prerequisites")
    if isinstance(pre, list):
        return [_plain_line(str(p)) for p in pre if str(p).strip()]
    if isinstance(pre, dict):
        return _structured_prerequisites(pre)
    return []


def _entry(tc: dict, constants: dict, category_name: str, brief: dict) -> dict:
    meta = tc.get("test_metadata") or {}
    return {
        "id": tc["ui_id"],
        "source_id": tc.get("source_id"),
        "title": meta.get("test_name") or tc.get("test_name"),
        "feature": FEATURE_NAME,
        "category": category_name,
        "execution": _execution_label(tc),
        "priority": meta.get("priority"),
        "description": brief["description"],
        "objective": brief["objective"],
        "prerequisites": _prerequisites(tc),
        "steps": brief["steps"],
        "expected_results": _expected_results(tc, constants),
        "verification": brief["verification"],
    }


def _build_entry(tc: dict, constants: dict, category_name: str) -> dict:
    return _entry(tc, constants, category_name, _generate_brief(tc, constants))


def _load_suites() -> list[tuple[str, str, dict, dict]]:
    jobs = []
    for cat_id, cat_name in CATEGORIES:
        suite = json.loads((SOURCE_DIR / f"{cat_id}.json").read_text(encoding="utf-8"))
        constants = (suite.get("suite_metadata") or {}).get("suite_constants") or {}
        for tc in suite["test_cases"]:
            jobs.append((cat_id, cat_name, tc, constants))
    return jobs


def _write_output(categories: dict[str, list[dict]]) -> None:
    payload = {FEATURE: {"feature_name": FEATURE_NAME, "categories": categories}}
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        "// Generated by Backend/scripts/generate_test_case_briefs.py — do not edit by hand.\n"
        "window.TEST_CASE_BRIEFS = "
        + json.dumps(payload, indent=2, ensure_ascii=False)
        + ";\n",
        encoding="utf-8",
    )


def _read_output() -> dict[str, list[dict]]:
    text = OUTPUT_PATH.read_text(encoding="utf-8")
    body = text.split("window.TEST_CASE_BRIEFS = ", 1)[1].rstrip().rstrip(";")
    return json.loads(body)[FEATURE]["categories"]


def _refresh_static_fields() -> None:
    categories = _read_output()
    by_id = {e["id"]: e for entries in categories.values() for e in entries}
    updated = 0
    for _cat_id, cat_name, tc, constants in _load_suites():
        entry = by_id.get(tc["ui_id"])
        if entry is None:
            continue
        rebuilt = _entry(tc, constants, cat_name, entry)
        entry.clear()
        entry.update(rebuilt)
        updated += 1
    _write_output(categories)
    print(f"Refreshed execution, prerequisites and expected results for {updated} briefs")


def main() -> None:
    args = sys.argv[1:]
    if "--static-only" in args or "--prerequisites-only" in args:
        _refresh_static_fields()
        return

    jobs = _load_suites()
    with ThreadPoolExecutor(max_workers=6) as pool:
        entries = list(
            pool.map(lambda j: (j[0], _build_entry(j[2], j[3], j[1])), jobs)
        )

    categories: dict[str, list[dict]] = {cat_id: [] for cat_id, _ in CATEGORIES}
    for cat_id, entry in entries:
        categories[cat_id].append(entry)

    _write_output(categories)
    total = sum(len(v) for v in categories.values())
    print(f"Wrote {total} briefs to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
