"""Generate display test scripts straight from the curated display test cases.

Display cases carry their own ADB steps, capability probes, SLAs and harness
requirements, so there is no operation map: the backend builds the CASE dict
deterministically and the LLM writes the body of run(h) against the dispharness
runtime API. Bodies are validated; a deterministic step-by-step template is used
when the LLM is unavailable or its output is rejected.
"""

from __future__ import annotations

import ast
import json
import re
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any

from llm.azure_client import chat_completion, parse_json_content
from observability.logging import logger
from services.test_cases import fill_placeholders, get_full_suite, get_test_case, placeholders_in

RUNTIME_PATH = Path(__file__).parent / "runtime" / "dispharness.py"
RUNTIME_MODULE = "dispharness"
HARNESS_PKG = "com.example.displaytest"
CATEGORIES = ("functionality", "performance", "reliability", "security")
CATEGORY_NAMES = {c: c.title() for c in CATEGORIES}
EXECUTION_LABELS = {
    "AUTO": "Automated",
    "FULLY_AUTOMATED": "Automated",
    "SEMI": "Semi Automated",
    "SEMI_AUTOMATED": "Semi Automated",
    "SEMI_LAB": "Semi Automated (Lab)",
}
H_API = {
    "sh", "extract", "extract_all", "poll", "now_ms", "sleep", "percentile", "mean",
    "metric", "expect", "check_slas", "instrument", "require_helper", "lab_value",
    "manual", "not_applicable", "blocked", "resolve", "resolve_soft", "display_info",
    "crash_counts", "sf_modes", "screen_luma",
}
H_ATTRS = {"vars", "metrics", "case", "last_rc"}
FORBIDDEN_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "globals", "locals", "print",
    "subprocess", "os", "sys", "shutil", "input", "breakpoint", "setattr", "delattr", "getattr",
}


def runtime_source() -> str:
    return RUNTIME_PATH.read_text(encoding="utf-8")


def _find_case(ui_id: str) -> tuple[str, dict[str, Any]] | None:
    for category in CATEGORIES:
        tc = get_test_case("display", category, ui_id)
        if tc is not None:
            return category, tc
    return None


def _py(value: Any, indent: int = 0) -> str:
    flat = repr(value)
    if not isinstance(value, (dict, list)) or len(flat) + indent <= 88 or not value:
        return flat
    pad = " " * (indent + 4)
    if isinstance(value, dict):
        items = [f"{pad}{k!r}: {_py(v, indent + 4)}," for k, v in value.items()]
        return "{\n" + "\n".join(items) + "\n" + " " * indent + "}"
    items = [f"{pad}{_py(v, indent + 4)}," for v in value]
    return "[\n" + "\n".join(items) + "\n" + " " * indent + "]"


# ------------------------------------------------------------------ CASE


def _harness(tc: dict[str, Any]) -> dict[str, Any]:
    meta = tc.get("test_metadata") or {}
    return tc.get("harness_requirement") or meta.get("harness_requirement") or {}


def harness_classes(tc: dict[str, Any]) -> list[str]:
    found = set(re.findall(rf"{re.escape(HARNESS_PKG)}(?:\.[a-z]\w*)*\.[A-Z]\w+", json.dumps(tc)))
    cls = _harness(tc).get("harness_class")
    if cls:
        found.add(cls)
    return sorted(found)


def build_case_spec(ui_id: str, category: str, tc: dict[str, Any], suite_meta: dict[str, Any]) -> dict[str, Any]:
    """The CASE dict embedded in the generated script (runtime-readable, no LLM)."""
    meta = tc.get("test_metadata") or {}
    hreq = _harness(tc)
    constants = {k: v for k, v in (suite_meta.get("suite_constants") or {}).items()
                 if not k.startswith("SPEC_") and v is not None}
    constants.update(meta.get("case_constants") or {})
    if tc.get("verification_slas"):
        slas = [{k: s.get(k) for k in ("metric_key", "metric_name", "operator", "target_value",
                                         "critical_threshold", "unit", "failure_classification")
                 if s.get(k) is not None} for s in tc["verification_slas"]]
    else:
        slas = [{"metric_key": c["metric"], "operator": c["operator"], "target_value": c["target"]}
                for c in tc.get("pass_criteria") or [] if c.get("metric")]
    raw_exec = tc.get("execution") or meta.get("feasibility") or ""
    ev = tc.get("evidence_collection") or {}
    spec: dict[str, Any] = {
        "ui_id": ui_id,
        "source_id": tc.get("source_id"),
        "name": tc.get("test_name") or meta.get("test_name"),
        "category": category,
        "execution": EXECUTION_LABELS.get(raw_exec, raw_exec.replace("_", " ").title()),
        "priority": tc.get("priority") or meta.get("priority"),
        "objective": tc.get("objective") or meta.get("target_scenario"),
        "harness": {
            "required": bool(hreq.get("required")),
            "package": hreq.get("harness_package"),
            "classes": harness_classes(tc),
            "helper_apks": list(hreq.get("helper_apks") or []),
            "lab_equipment": list(hreq.get("lab_equipment") or []),
            "status": hreq.get("harness_status"),
            "reason": hreq.get("reason"),
        },
        "constants": constants,
        "capability_discovery": [
            {k: c.get(k) for k in ("variable", "command", "extraction_regex")}
            for c in tc.get("capability_discovery") or []
        ],
        "setup_commands": [
            {"command": s["command"], "description": s.get("description", ""),
             "ignore_failure": bool(s.get("ignore_failure", True))}
            for s in tc.get("setup_commands") or []
        ],
        "teardown_commands": [{"command": s["command"]} for s in tc.get("teardown_commands") or []],
        "evidence": {
            "logcat": (ev.get("logcat_config") or {}).get("dump_command"),
            "dumps": [d.get("command") for d in ev.get("subsystem_dumps") or [] if d.get("command")],
        },
    }
    if isinstance(tc.get("prerequisites"), dict):
        spec["prerequisites"] = {k: tc["prerequisites"][k] for k in ("thermal_limits", "battery_state")
                                 if k in tc["prerequisites"]}
    if isinstance(tc.get("parameters"), dict):
        spec["parameters"] = tc["parameters"]
    if tc.get("expected_results"):
        spec["expected_results"] = list(tc["expected_results"])
    if slas:
        spec["slas"] = slas
    return spec


# ------------------------------------------------------------ template body


def _instr_call(command: str) -> tuple[str, dict[str, str]] | None:
    m = re.search(r"-e class (\S+)", command)
    if not m:
        return None
    args = {k: v for k, v in re.findall(r"-e (\w+) (\S+)", command) if k != "class"}
    return m.group(1), args


def template_body(spec: dict[str, Any], tc: dict[str, Any]) -> str:
    """Run every concrete step, record regex-extracted metrics, hand the rest to the tester."""
    lines: list[str] = []
    for i, step in enumerate(tc.get("steps") or [], 1):
        cmd = step.get("command") or ""
        label = f"Step {step.get('step', i)}: {step.get('action', '')}".strip()
        if cmd.startswith("adb ") and "<" not in cmd:
            lines.append(f"out = h.sh({cmd!r})")
            lines.append(f"h.expect(h.last_rc == 0, {label + ' (command ran)'!r}, "
                         "actual=f'exit code {h.last_rc}: ' + out.strip()[-300:], expected='exit code 0')")
            if step.get("expect"):
                lines.append(f"h.manual({label + ' - check: ' + str(step['expect'])!r})")
        else:
            lines.append(f"h.manual({label + ' - ' + str(step.get('expect') or '')!r})")
    for step in tc.get("execution_procedure") or []:
        payload = step.get("payload") or {}
        cmd = str(payload.get("command") or "")
        chk = step.get("validation_checkpoint") or {}
        name = f"{step.get('step_name', 'step')}"
        instr = _instr_call(cmd) if step.get("action_type") == "instrumentation" else None
        if instr:
            lines.append(f"res = h.instrument({instr[0]!r}, {_py(instr[1])})")
            for sla in spec.get("slas") or []:
                key = sla["metric_key"]
                lines.append(f"if {key!r} in res:\n    h.metric({key!r}, res[{key!r}])")
        elif step.get("action_type") == "shell_command" and cmd.startswith("adb ") and "<" not in cmd:
            lines.append(f"out = h.sh({cmd!r})")
            key, regex = chk.get("metric_key"), chk.get("extraction_regex")
            if key and regex and regex != "(.*)":
                lines.append(f"val = h.extract(out, {regex!r})")
                lines.append(f"if val is not None:\n    h.metric({key!r}, val)")
            else:
                lines.append(f"h.expect(h.last_rc == 0, {name + ' (command ran)'!r}, "
                             "actual=f'exit code {h.last_rc}: ' + out.strip()[-300:], expected='exit code 0')")
        else:
            hint = step.get("code_gen_hint") or ""
            lines.append(f"h.manual({(name + ': ' + hint).strip(': ')!r})")
    for item in spec.get("expected_results") or []:
        lines.append(f"h.manual({'Verify: ' + item!r})")
    lines.append("h.check_slas(missing='manual')" if spec.get("slas") else
                 "h.expect(True, 'Template script executed all concrete steps', actual='all steps ran', "
                 "expected='all steps run')")
    return "\n".join(lines)


# ------------------------------------------------------------- assembly


def _header(spec: dict[str, Any], generator: str, run_id: str) -> str:
    title = f"{spec['ui_id']} · {spec['source_id']} · {spec['name']}"
    objective = textwrap.fill(spec.get("objective") or "", width=88)
    harness = spec.get("harness") or {}
    needs = []
    if harness.get("required"):
        needs.append("harness " + ", ".join(c.rsplit(".", 1)[-1] for c in harness.get("classes") or [])
                     or harness.get("package") or "harness")
        needs += harness.get("helper_apks") or []
    needs += harness.get("lab_equipment") or []
    spec_values = spec.get("spec_values") or {}
    spec_line = (
        f"Spec     : {len(spec_values)} value(s) from {spec.get('spec_source') or 'the product spec'}: "
        + ", ".join(f"{k}={v}" for k, v in spec_values.items())
        if spec_values else "Spec     : none (SPEC_* must come from --var or the case is NOT_APPLICABLE)"
    )
    return (
        '#!/usr/bin/env python3\n'
        f'"""{title}\n\n'
        f"Category : {CATEGORY_NAMES.get(spec['category'], spec['category'])}\n"
        f"Execution: {spec['execution']}\n"
        f"Requires : {textwrap.fill('; '.join(needs) or 'ADB only', width=78, subsequent_indent='           ')}\n"
        f"Objective: {objective}\n"
        f"{textwrap.fill(spec_line, width=88, subsequent_indent='           ')}\n\n"
        f"Generated by Device Testing Workbench ({generator}) · run {run_id} · "
        f"{datetime.now():%Y-%m-%d %H:%M}\n"
        f"Run: python3 test_{spec['ui_id']}.py [--serial SERIAL] [--var NAME=VALUE]\n"
        '"""\n'
    )


def assemble_script(spec: dict[str, Any], body: str, generator: str, run_id: str) -> str:
    return (
        _header(spec, generator, run_id)
        + f"\nfrom {RUNTIME_MODULE} import Harness, main\n\n"
        + f"CASE = {_py(spec)}\n\n\n"
        + "def run(h: Harness) -> None:\n"
        + textwrap.indent(body.strip("\n"), "    ")
        + "\n\n\nif __name__ == \"__main__\":\n"
        + "    raise SystemExit(main(CASE, run))\n"
    )


# ----------------------------------------------------------- validation


def _str_prefix(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
        return str(node.values[0].value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _str_prefix(node.left)
    return None


def validate_script(code: str, spec: dict[str, Any], *, strict: bool = True) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors reject the script.

    strict (LLM bodies): every SLA metric must be computed. The template instead hands
    unmeasured metrics to the tester via check_slas(missing='manual').
    """
    errors: list[str] = []
    warnings: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"syntax error line {exc.lineno}: {exc.msg}"], warnings
    run_fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run"), None)
    if run_fn is None:
        return ["run(h) function missing"], warnings

    classes = set((spec.get("harness") or {}).get("classes") or [])
    called: set[str] = set()
    metric_keys: set[str] = set()
    instrumented = False
    for node in ast.walk(run_fn):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            errors.append("imports are not allowed inside run()")
        elif (strict and isinstance(node, ast.Constant) and isinstance(node.value, str)
              and "DisplayDeviceInfo" in node.value):
            errors.append("do not parse DisplayDeviceInfo text; use h.display_info()")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            errors.append("global/nonlocal are not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            errors.append(f"forbidden name '{node.id}'")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "h":
            if node.attr not in H_API | H_ATTRS:
                errors.append(f"unknown runtime API h.{node.attr}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            errors.append(f"dunder access '{node.attr}'")

        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "h"):
            continue
        name = node.func.attr
        called.add(name)
        first = node.args[0] if node.args else None
        if name in ("sh", "poll") and first is not None:
            prefix = _str_prefix(first)
            if prefix is not None and not prefix.startswith("adb "):
                errors.append(f"h.{name}() command must start with 'adb ': {prefix[:60]}")
        elif name == "instrument":
            instrumented = True
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                errors.append("h.instrument() class must be a string literal")
            elif first.value not in classes:
                errors.append(f"harness class {first.value} is not named by this test case")
        elif name == "metric" and isinstance(first, ast.Constant) and isinstance(first.value, str):
            metric_keys.add(first.value)
        elif name == "expect":
            if len(node.args) > 3:
                errors.append("h.expect() takes (condition, description, actual=None, expected=None)")
            if {kw.arg for kw in node.keywords} - {"actual", "expected"}:
                errors.append("h.expect() only accepts the keywords actual= and expected=")

    slas = spec.get("slas") or []
    if slas:
        if "check_slas" not in called:
            errors.append("run() must call h.check_slas() for this case")
        missing = sorted({s["metric_key"] for s in slas} - metric_keys)
        if missing and strict:
            errors.append(f"SLA metric(s) never recorded with h.metric('<key>', ...): {', '.join(missing)}")
        elif missing:
            warnings.append(f"template leaves {len(missing)} SLA metric(s) to the tester: {', '.join(missing)}")
    elif not called & {"expect", "manual"}:
        errors.append("functional case must record results (h.expect / h.manual)")
    if strict and "lab_value" in called and not (spec.get("harness") or {}).get("lab_equipment"):
        errors.append("h.lab_value() is only for cases with lab_equipment; measure this over adb "
                      "(h.screen_luma, h.display_info, dumpsys thermalservice, ...)")
    if classes and (spec.get("harness") or {}).get("required") and not instrumented:
        warnings.append("case requires the display harness but run() never calls h.instrument()")
    return sorted(set(errors)), warnings


# ------------------------------------------------------------------ LLM

SYSTEM_PROMPT = """You write the body of `def run(h: Harness) -> None:` for an Android DISPLAY test script.
The header, CASE dict, imports and main() are fixed and written by the platform; you return only the
statements inside run(h). Before run(h) starts, the runtime has already checked the device, stopped the
case (BLOCKED_PRECONDITION) if a required harness/helper APK is missing, run capability discovery, and
run CASE setup (settings snapshot stored as BASELINE_* variables). After run(h) it collects evidence and
restores settings. Runtime API:

  h.sh(cmd, timeout=120, check=False) -> str   Host command starting with "adb " (shell syntax allowed:
                                               quotes, pipes, &&, "> file"). "${VAR}" placeholders are
                                               resolved; an unknown one ends the case as NOT_APPLICABLE.
                                               Returns stdout; h.last_rc holds the exit code.
  h.extract(text, regex, group=1, cast=float, default=None) -> value   First match (cast=None for str;
                                               group=None returns a tuple of all groups).
  h.extract_all(text, regex, cast=float) -> list
  h.poll(cmd, regex, interval_ms=100, timeout_s=10, until=None, cast=float) -> [(t_ms, value), ...]
                                               until = lambda v: <condition> stops early.
  h.display_info() -> dict                     Built-in display from `dumpsys display`: name, type, width,
                                               height, density, xdpi, ydpi, refresh_hz,
                                               supported_refresh_hz (list), modes (list of {id, width,
                                               height, fps}), active_mode_id, default_mode_id,
                                               hdr_types (list),
                                               max_luminance, has_cutout, state. Values may be None.
                                               ALWAYS use it for these fields; never split/regex the
                                               DisplayDeviceInfo text yourself (nested braces, and it
                                               says "type INTERNAL", not "type=INTERNAL").
  h.sf_modes() -> list                         SurfaceFlinger modes [{id, width, height, fps}]. Its ids differ
                                               from DisplayManager ids: match modes by width/height/fps.
  h.screen_luma(step=16, settle_s=2.0) -> float Mean luma 0-255 of the screen after waiting settle_s for
                                               animations / theme recreation (raw screencap); use it for
                                               black-screen / dark-vs-light / brightness checks.
  h.crash_counts() -> dict                     Events since the case started only: app_crash,
                                               native_crash, anr, tombstone, systemui_crash,
                                               systemui_restarts, surfaceflinger_restarts. Use it for all
                                               crash/ANR/restart metrics; dumpsys dropbox and the crash
                                               buffer also contain older history.
  h.now_ms() -> float (monotonic ms)           h.sleep(seconds)
  h.percentile(values, p) / h.mean(values)     None when values is empty.
  h.metric(key, value)                         Record a measured metric for the SLA check.
  h.expect(condition, description, actual=None, expected=None)
                                               Record one expected-result check; pass the measured value as
                                               actual= and the value it must have as expected= (both shown in
                                               the report).
  h.check_slas()                               Evaluate every CASE["slas"] entry against recorded metrics.
  h.instrument(cls, args) -> dict              Display-harness operation (class = full name string literal
                                               from CASE["harness"]["classes"]); returns its JSON result
                                               ("result" plus metric fields).
  h.require_helper(pkg)                        Blocks the case if a helper APK is missing.
  h.lab_value(name, description) -> float      Reading from lab equipment, supplied by the tester via --var.
  h.manual(message)                            Tester checkpoint for what the host cannot observe.
  h.not_applicable(reason) / h.blocked(reason) Stop the case with that verdict.
  h.vars                                       Resolved variables (str values; list/dict parameters keep
                                               their JSON type, e.g. iterate h.vars["surfaces"]): constants, discovered
                                               capabilities, product-spec values, BASELINE_*, and every
                                               CASE "parameters" entry by its own name (e.g.
                                               h.vars["expected_resolution"]). Reading an unknown name
                                               with h.vars[...] ends the case as NOT_APPLICABLE; use
                                               h.vars.get(name) for optional values.

Rules:
- Implement the case's steps / execution_procedure in order and follow every code_gen_hint. Translate
  pseudo commands such as "<poll dumpsys SurfaceFlinger every 100 ms for 10 s>" into h.poll / loops.
- CASE has "slas": compute EVERY listed metric_key and record it with h.metric("<metric_key>", value)
  using exactly those literal keys, then call h.check_slas() once at the end.
- No "slas": record each expected result with h.expect(...) on values you actually measured.
- Use h.lab_value only when CASE["harness"]["lab_equipment"] is non-empty, and only for readings that
  instrument provides; anything readable over adb (thermal, screen content, modes) must be measured; h.manual for purely visual/human judgements.
- Keep "${VAR}" placeholders inside command strings; read numbers with float(h.vars["NAME"]) /
  int(h.vars["NAME"]). Loop counts come from variables, never hard-code smaller numbers.
- Gate capabilities on discovered variables (e.g. SUPPORTED_REFRESH_RATES is a comma-separated list
  of Hz values) and call h.not_applicable(...) when the capability is absent. BASELINE_* values are
  raw `settings get` output used for restore and may be the string "null"; never gate on them.
- Guard every numeric conversion of device output (values may be None) so a missing reading becomes
  an explicit h.expect(False, ...) or an unmeasured metric, not an exception.
- Use only harness classes, packages, settings keys and commands that appear in the case.
- Android output facts: `settings put`, `input`, `wm size WxH` and `cmd` setters print nothing on
  success (check h.last_rc == 0 and read back with `settings get` / `wm size`). Wakefulness is
  `mWakefulness=(Awake|Asleep|Dozing)` in `dumpsys power` (screen off = Asleep OR Dozing). The screen
  state is `mScreenState=(ON|OFF|DOZE)` in `dumpsys display`; `dumpsys power` has no display state.
  UI changes (uimode, font/density, activity launch, rotation) apply asynchronously: wait >= 2 s
  before reading the result from the screen or dumpsys.
  Thermal status is `Thermal Status: (\\d+)` in `adb shell dumpsys thermalservice`.
  Android ignores a power key press while the screen is still turning on: after the screen reaches
  ON, wait at least 2 s before the next KEYCODE_POWER / KEYCODE_SLEEP.
  Metrics counting completed iterations must use the number actually completed.
- There is no `re` or `math` module: parse text with h.extract / h.extract_all (they take regexes)
  and use x ** 0.5 for square roots.
- Do not restore settings, collect evidence, import, print, or touch files/network/processes except
  through h. Allowed builtins: len, range, min, max, sum, abs, round, int, float, str, bool, sorted,
  enumerate, zip, any, all, list, dict, set, tuple, isinstance, lambda.
- Plain Python 3, 4-space indentation, short comments only where a step is non-obvious.

Return JSON only: {"body": "<statements of run(h), not indented, no def line>", "notes": ["..."]}"""

EXAMPLE = """Example (a different case: SLA metrics p95_wake_ms, max_wake_ms) - body:
samples = []
for _ in range(int(h.vars["PERF_ITERATIONS"])):
    h.sh("adb shell input keyevent KEYCODE_SLEEP")
    h.sleep(2)
    t0 = h.now_ms()
    h.sh("adb shell input keyevent KEYCODE_WAKEUP")
    trace = h.poll("adb shell dumpsys power", r"mWakefulness=(\\w+)", interval_ms=20, timeout_s=3,
                   cast=str, until=lambda v: v == "Awake")
    awake = [t for t, v in trace if v == "Awake"]
    if awake:
        samples.append(awake[0] - t0)
h.expect(len(samples) >= int(h.vars["PERF_ITERATIONS"]) - 1, "Display woke on every iteration",
         actual=len(samples), expected=f">= {int(h.vars['PERF_ITERATIONS']) - 1} wakes")
h.metric("p95_wake_ms", h.percentile(samples, 95))
h.metric("max_wake_ms", max(samples) if samples else None)
h.check_slas()"""


def _llm_context(spec: dict[str, Any], tc: dict[str, Any], known_vars: list[str]) -> str:
    meta = tc.get("test_metadata") or {}
    ctx = {
        "case": {
            "ui_id": spec["ui_id"],
            "name": spec["name"],
            "category": spec["category"],
            "execution": spec["execution"],
            "objective": spec.get("objective"),
            "real_world_reference": tc.get("real_world_reference") or meta.get("real_world_reference"),
            "harness": spec.get("harness"),
            "parameters": tc.get("parameters"),
            "applicability": tc.get("applicability"),
            "steps": tc.get("steps"),
            "execution_procedure": tc.get("execution_procedure"),
            "expected_results": spec.get("expected_results"),
            "slas": spec.get("slas"),
            "notes": tc.get("notes"),
        },
        "known_variables": known_vars,
    }
    return json.dumps({k: v for k, v in ctx.items() if v is not None}, indent=1, default=str)


def llm_body(spec: dict[str, Any], tc: dict[str, Any]) -> tuple[str | None, list[str], list[str]]:
    """Return (body, notes, errors) from up to three LLM attempts."""
    known = sorted(set(spec.get("constants") or {}) | set(spec.get("spec_values") or {})
                   | set(spec.get("parameters") or {})
                   | {c["variable"].strip("${}") for c in spec.get("capability_discovery") or [] if c.get("variable")}
                   | {"ANDROID_SDK_INT", "DISPLAY_HARNESS_INSTALLED"}
                   | {v for v in placeholders_in(tc) if v.startswith("BASELINE_")})
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": EXAMPLE + "\n\nNow write the body for this case:\n" + _llm_context(spec, tc, known)},
    ]
    errors: list[str] = []
    for _attempt in range(3):
        content, _usage = chat_completion(
            messages, temperature=0.0, response_format={"type": "json_object"}, max_tokens=4000,
        )
        data = parse_json_content(content) or {}
        body = data.get("body") if isinstance(data, dict) else None
        if not isinstance(body, str) or not body.strip():
            errors = ["LLM returned no body"]
        else:
            body = textwrap.dedent(body).strip("\n")
            errors, _warnings = validate_script(assemble_script(spec, body, "llm", "check"), spec)
            if not errors:
                return body, [str(n) for n in data.get("notes") or []][:5], []
        messages += [
            {"role": "assistant", "content": content},
            {"role": "user", "content": "The body was rejected: " + "; ".join(errors) + ". Return corrected JSON only."},
        ]
    return None, [], errors


# ---------------------------------------------------------------- driver


def generate_one(ui_id: str, use_llm: bool, run_id: str,
                 spec_values: dict[str, str] | None = None, spec_source: str | None = None) -> dict[str, Any]:
    found = _find_case(ui_id)
    if found is None:
        return {"case_id": ui_id, "status": "error", "errors": [f"{ui_id}: test case not found"]}
    category, tc = found
    suite_meta = (get_full_suite("display", category) or {}).get("suite_metadata") or {}
    used = {k: v for k, v in (spec_values or {}).items() if k in placeholders_in(tc)}
    if used:
        tc = fill_placeholders(tc, used)
    spec = build_case_spec(ui_id, category, tc, suite_meta)
    if used:
        spec["spec_values"] = used
        spec["spec_source"] = spec_source or "product spec"

    generator, notes, fallback_reason, body = "template", [], None, None
    if use_llm:
        try:
            body, notes, llm_errors = llm_body(spec, tc)
            if body is not None:
                generator = "llm"
            else:
                fallback_reason = "LLM output rejected: " + "; ".join(llm_errors)
        except Exception as exc:
            logger.exception("LLM display script generation failed for %s", ui_id)
            fallback_reason = f"LLM call failed: {exc}"
    if body is None:
        body = template_body(spec, tc)

    code = assemble_script(spec, body, generator, run_id)
    errors, warnings = validate_script(code, spec, strict=generator == "llm")
    if fallback_reason:
        warnings.insert(0, fallback_reason + " (template used)")
    harness = spec["harness"]
    return {
        "case_id": ui_id,
        "source_id": spec["source_id"],
        "name": spec["name"],
        "category": category,
        "execution": spec["execution"],
        "harness_class": ", ".join(harness["classes"]) if harness["required"] else None,
        "harness_required": harness["required"],
        "lab_equipment": harness["lab_equipment"],
        "filename": f"test_{ui_id}.py",
        "generator": generator,
        "status": "error" if errors else "ok",
        "errors": errors,
        "warnings": warnings,
        "notes": notes,
        "manual_steps": [],
        "spec_values": used,
        "code": code,
    }
