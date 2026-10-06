"""Generate camera test scripts from curated test cases + the harness operation map.

Every script has the same fixed shape (header, CASE dict, run(h), main). The
backend builds the header and CASE deterministically; the LLM writes only the
body of run(h) against the camharness runtime API. Bodies are validated and a
deterministic template body is used when the LLM is unavailable or invalid.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import textwrap
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.config import BACKEND_ROOT, PROJECT_ROOT
from llm.azure_client import chat_completion, is_azure_configured, parse_json_content
from observability.logging import logger
from services.test_cases import (
    derive_spec_values,
    fill_placeholders,
    get_test_case,
    is_feature_enabled,
    placeholders_in,
)

RUNTIME_PATH = Path(__file__).parent / "runtime" / "camharness.py"
OPERATION_MAP_PATH = PROJECT_ROOT / "cameratest-harness" / "operation_map.json"
HARNESS_DIR = PROJECT_ROOT / "cameratest-harness"
OUTPUT_ROOT = BACKEND_ROOT / "data" / "generated_scripts"

CATEGORIES = ("functionality", "performance", "reliability", "security")
CATEGORY_NAMES = {
    "functionality": "Functionality",
    "performance": "Performance",
    "reliability": "Reliability",
    "security": "Security",
}
EXECUTION_LABELS = {
    "AUTO": "Automated",
    "FULLY_AUTOMATED": "Automated",
    "AUTO_SEMI": "Automated with manual checks",
    "SEMI": "Semi Automated",
    "SEMI_AUTOMATED": "Semi Automated",
    "SEMI_LAB": "Semi Automated (Lab)",
}
APK_FLAVORS = {
    "cameratest-unauthorized.apk": "unauthorized",
    "cameratest-secondary.apk": "secondary",
}
FUNCTIONAL_SETUP = [
    {"command": "adb wait-for-device", "ignore_failure": False},
    {"command": "adb shell input keyevent KEYCODE_WAKEUP", "ignore_failure": True},
    {"command": "adb shell wm dismiss-keyguard", "ignore_failure": True},
]
FUNCTIONAL_TEARDOWN = [
    {"command": "adb shell am force-stop com.example.cameratest", "always_execute": True},
    {"command": "adb shell input keyevent KEYCODE_HOME", "always_execute": True},
]
HELPER_CLASSES = {
    "com.example.cameratest.CapabilityTest",
    "com.example.cameratest.HarnessInfoTest",
}
H_API = {
    "op", "verify_op", "host", "expect", "expect_pass", "check_slas", "combine",
    "derive", "manual", "not_applicable", "metric", "resolve", "resolve_soft",
}
H_ATTRS = {"vars", "capabilities", "case"}
FORBIDDEN_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "globals", "locals",
    "subprocess", "os", "sys", "shutil", "input", "breakpoint", "setattr", "delattr",
}
MAX_WORKERS = 4


# ---------------------------------------------------------------- inputs


@lru_cache(maxsize=1)
def load_operation_map() -> dict[str, Any]:
    return json.loads(OPERATION_MAP_PATH.read_text(encoding="utf-8"))


def runtime_source() -> str:
    return RUNTIME_PATH.read_text(encoding="utf-8")


def _find_case(feature: str, ui_id: str) -> tuple[str, dict[str, Any]] | None:
    for category in CATEGORIES:
        tc = get_test_case(feature, category, ui_id)
        if tc is not None:
            return category, tc
    return None


def _variable_defaults(entry: dict[str, Any], slas: list[dict[str, Any]]) -> dict[str, str]:
    """Size cycle / duration variables so the run can actually meet the SLA target."""
    primary = next((s for s in slas if s.get("metric_key") == "primary_reliability_metric"), None)
    if not primary or not primary.get("target_value"):
        return {}
    used = re.findall(r"\$\{([A-Z0-9_]+)\}", json.dumps(entry.get("args") or {}))
    target = str(int(primary["target_value"]))
    if primary.get("operator") == "==":
        keys = [v for v in used if re.search(r"CYCLES|ITERATIONS|COUNT", v)]
    elif primary.get("operator") == ">=":
        keys = [v for v in used if v.endswith("DURATION_SEC")]
    else:
        keys = []
    return {k: target for k in keys}


def build_case_spec(ui_id: str, category: str, tc: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """The CASE dict embedded in the generated script (runtime-readable, no LLM)."""
    meta = tc.get("test_metadata") or {}
    slas = [
        {k: s.get(k) for k in (
            "metric_key", "metric_name", "operator", "target_value",
            "critical_threshold", "unit", "failure_classification",
        ) if s.get(k) is not None}
        for s in tc.get("verification_slas") or []
    ]
    variable_defaults = _variable_defaults(entry, slas)
    if variable_defaults:
        # The primary target follows the sizing variable so overriding it (e.g. a smoke run) stays consistent.
        primary = next(s for s in slas if s.get("metric_key") == "primary_reliability_metric")
        primary["target_value"] = "${" + next(iter(variable_defaults)) + "}"
        primary.pop("critical_threshold", None)
    apks = ["harness"]
    if entry.get("requires_apk") in APK_FLAVORS:
        apks.append(APK_FLAVORS[entry["requires_apk"]])
    raw_exec = entry.get("execution") or tc.get("execution") or meta.get("feasibility") or ""
    spec: dict[str, Any] = {
        "ui_id": ui_id,
        "source_id": entry.get("source_id") or tc.get("source_id"),
        "name": entry.get("name") or tc.get("test_name") or meta.get("test_name"),
        "category": category,
        "execution": EXECUTION_LABELS.get(raw_exec, raw_exec.replace("_", " ").title()),
        "contract": entry.get("contract"),
        "objective": tc.get("objective") or meta.get("target_scenario"),
        "requires_apks": apks,
        "variable_defaults": variable_defaults,
        "setup_commands": [
            {"command": s["command"], "ignore_failure": bool(s.get("ignore_failure", True))}
            for s in tc.get("setup_commands") or FUNCTIONAL_SETUP
        ],
        "teardown_commands": [
            {"command": s["command"]} for s in tc.get("teardown_commands") or FUNCTIONAL_TEARDOWN
        ],
    }
    if isinstance(tc.get("prerequisites"), dict):
        spec["prerequisites"] = {
            k: tc["prerequisites"][k]
            for k in ("thermal_limits", "battery_state")
            if k in tc["prerequisites"]
        }
    if tc.get("expected_results"):
        spec["expected_results"] = list(tc["expected_results"])
    if slas:
        spec["slas"] = slas
    ev = tc.get("evidence_collection") or {}
    if ev:
        spec["evidence"] = {
            "logcat_config": {"dump_command": (ev.get("logcat_config") or {}).get("dump_command")},
            "subsystem_dumps": [
                {"name": d.get("name"), "command": d.get("command")}
                for d in ev.get("subsystem_dumps") or []
            ],
        }
    return spec


def allowed_classes(entry: dict[str, Any]) -> set[str]:
    classes = {entry["class"], *HELPER_CLASSES}
    classes.update(v["class"] for v in entry.get("verify") or [])
    return classes


# -------------------------------------------------------- template body


def _py(value: Any, indent: int = 0) -> str:
    """Python literal, one line when it fits in 88 columns, else one item per line."""
    flat = repr(value)
    if not isinstance(value, (dict, list)) or len(flat) + indent <= 88 or not value:
        return flat
    pad = " " * (indent + 4)
    if isinstance(value, dict):
        items = [f"{pad}{k!r}: {_py(v, indent + 4)}," for k, v in value.items()]
        return "{\n" + "\n".join(items) + "\n" + " " * indent + "}"
    items = [f"{pad}{_py(v, indent + 4)}," for v in value]
    return "[\n" + "\n".join(items) + "\n" + " " * indent + "]"


def _ident(label: str, used: set[str]) -> str:
    name = re.sub(r"\W+", "_", label).strip("_").lower() or "phase"
    if name[0].isdigit():
        name = "p_" + name
    base, n = name, 2
    while name in used or name in {"res", "h", "inspect"}:
        name, n = f"{base}_{n}", n + 1
    used.add(name)
    return name


def _combine_expr(combine: str, phase_vars: list[str]) -> tuple[str, str] | None:
    m = re.match(r"^\s*(\w+)\s*=\s*(.+)$", combine or "")
    if not m:
        return None
    key, expr = m.group(1), m.group(2).strip()
    all_m = re.match(r"^all phases metric_value\s*(==|>=|<=)\s*(\S+)$", expr)
    if all_m:
        return key, (
            f"all(p.get('metric_value') {all_m.group(1)} {all_m.group(2)} "
            f"for p in ({', '.join(phase_vars)},))"
        )
    expr = re.sub(r"\b(\w+)\.metric_value\b", r"\1.get('metric_value')", expr)
    return key, expr


def template_body(spec: dict[str, Any], entry: dict[str, Any]) -> str:
    cls = entry["class"]
    args = entry.get("args") or {}
    lines: list[str] = []
    for cmd in entry.get("host_pre") or []:
        lines.append(f"h.host({cmd!r})")
    if entry.get("manual"):
        lines.append(f"h.manual({entry['manual']!r})")

    phases = entry.get("phases") or []
    body: list[str] = []
    if phases:
        used: set[str] = set()
        phase_vars: list[str] = []
        for i, phase in enumerate(phases, 1):
            if phase.get("manual"):
                body.append(f"h.manual({phase['manual']!r})")
            if "args" in phase:
                label = str(phase["args"].get("phase") or f"phase{i}")
                var = _ident(label, used)
                phase_vars.append(var)
                phase_args = {**args, **phase["args"]}
                body.append(f"{var} = h.op(\n    {cls!r},\n    {_py(phase_args, 4)},\n    label={label!r},\n)")
            for cmd in phase.get("host") or []:
                body.append(f"h.host({cmd!r})")
        combined = _combine_expr(entry.get("combine") or "", phase_vars)
        if combined:
            body.append(f"h.derive({combined[0]!r}, {combined[1]})")
        body.append(f"res = h.combine({', '.join(phase_vars)})")
    else:
        body.append(f"res = h.op(\n    {cls!r},\n    {_py(args, 4)},\n)")

    for i, ver in enumerate(entry.get("verify") or [], 1):
        label = "inspect" if i == 1 else f"inspect_{i}"
        body.append(
            f"{label} = h.verify_op({ver['class']!r}, {_py(ver.get('args') or {}, 4)}, res, label={label!r})"
        )
        body.append(f"h.expect_pass({label}, 'Saved media passes {ver['class'].rsplit('.', 1)[-1]}')")

    if spec.get("slas"):
        body.append("h.check_slas(res)")
    else:
        body.append("h.expect_pass(res, CASE.get('expected_results') or ['Harness operation passes'])")

    host_post = entry.get("host_post") or []
    if host_post:
        lines.append("try:")
        lines += [textwrap.indent(b, "    ") for b in body]
        lines.append("finally:")
        lines += [f"    h.host({cmd!r})" for cmd in host_post]
    else:
        lines += body
    return "\n".join(lines)


# ------------------------------------------------------------- assembly


def _header(spec: dict[str, Any], generator: str, run_id: str) -> str:
    title = f"{spec['ui_id']} · {spec['source_id']} · {spec['name']}"
    objective = textwrap.fill(spec.get("objective") or "", width=88, subsequent_indent="")
    spec_values = spec.get("spec_values") or {}
    spec_line = (
        f"Spec     : {len(spec_values)} value(s) from {spec.get('spec_source') or 'the product spec'}: "
        + ", ".join(f"{k}={v}" for k, v in spec_values.items())
        if spec_values else "Spec     : none (placeholders resolved from the device at runtime)"
    )
    return (
        '#!/usr/bin/env python3\n'
        f'"""{title}\n\n'
        f"Category : {CATEGORY_NAMES.get(spec['category'], spec['category'])}\n"
        f"Execution: {spec['execution']}\n"
        f"Contract : {spec['contract']}\n"
        f"Objective: {objective}\n"
        f"{textwrap.fill(spec_line, width=88, subsequent_indent='           ')}\n\n"
        f"Generated by Device Testing Workbench ({generator}) · run {run_id} · "
        f"{datetime.now():%Y-%m-%d %H:%M}\n"
        f"Run: python3 test_{spec['ui_id']}.py [--serial SERIAL] [--var NAME=VALUE] [--apk-dir DIR]\n"
        '"""\n'
    )


def assemble_script(spec: dict[str, Any], body: str, generator: str, run_id: str) -> str:
    return (
        _header(spec, generator, run_id)
        + "\nfrom camharness import Harness, main\n\n"
        + f"CASE = {_py(spec)}\n\n\n"
        + "def run(h: Harness) -> None:\n"
        + textwrap.indent(body.strip("\n"), "    ")
        + "\n\n\nif __name__ == \"__main__\":\n"
        + "    raise SystemExit(main(CASE, run))\n"
    )


# ------------------------------------------------------------ validation


def validate_script(code: str, spec: dict[str, Any], entry: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors reject the script."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"syntax error line {exc.lineno}: {exc.msg}"], warnings

    run_fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run"), None)
    if run_fn is None:
        return ["run(h) function missing"], warnings

    classes = allowed_classes(entry)
    op_calls: list[str] = []
    main_arg_sets: list[dict[str, str]] = []
    called: set[str] = set()
    for node in ast.walk(run_fn):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            errors.append("imports are not allowed inside run()")
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
        literal = first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None
        if name in ("op", "verify_op"):
            if literal is None:
                errors.append(f"h.{name}() class must be a string literal")
            elif literal not in classes:
                errors.append(f"class {literal} is not mapped to this test case")
            else:
                op_calls.append(literal)
                if name == "op" and literal == entry["class"]:
                    args_node = node.args[1] if len(node.args) > 1 else None
                    try:
                        main_arg_sets.append(ast.literal_eval(args_node) if args_node else {})
                    except (ValueError, SyntaxError):
                        errors.append("h.op() args must be a literal dict of strings")
        elif name == "host" and literal is not None:
            if not re.match(r"^(adb |sleep \d|<)", literal):
                errors.append(f"host step must be an adb/sleep/<manual> command: {literal[:60]}")
        elif name == "expect":
            if len(node.args) > 3:
                errors.append("h.expect() takes (condition, description, actual=None, expected=None)")
            if {kw.arg for kw in node.keywords} - {"actual", "expected"}:
                errors.append("h.expect() only accepts the keywords actual= and expected=")

    if entry["class"] not in op_calls:
        errors.append(f"run() never calls h.op('{entry['class']}')")
    base_args = {k: str(v) for k, v in (entry.get("args") or {}).items()}
    expected_sets = [
        {**base_args, **{k: str(v) for k, v in p["args"].items()}}
        for p in entry.get("phases") or [] if "args" in p
    ] or [base_args]
    for want in expected_sets:
        if not any(all(got.get(k) == v for k, v in want.items()) for got in main_arg_sets):
            errors.append(f"no h.op('{entry['class'].rsplit('.', 1)[-1]}') call with args {want}")
    if spec.get("slas") and "check_slas" not in called:
        errors.append("run() must call h.check_slas(res) for this case")
    if not spec.get("slas") and not called & {"expect", "expect_pass"}:
        errors.append("functional case must record expected results (h.expect / h.expect_pass)")
    for ver in entry.get("verify") or []:
        if ver["class"] not in op_calls:
            warnings.append(f"verification {ver['class'].rsplit('.', 1)[-1]} not executed")
    for cmd in entry.get("host_post") or []:
        if cmd not in code:
            warnings.append(f"host_post step missing: {cmd}")
    return sorted(set(errors)), warnings


# ------------------------------------------------------------------ LLM

SYSTEM_PROMPT = """You write the body of `def run(h: Harness) -> None:` for an Android camera test script.
The script header, CASE dict, imports and main() are fixed and written by the platform; you only
return the statements inside run(h). The device-side work is done by a prebuilt instrumentation
harness APK; the host drives it only through this runtime API:

  h.op(cls, args, label="main") -> dict        Run one harness operation (class = full name string literal,
                                               args = dict of str; literal values (some come from the
                                               product spec) are sent as given, "${VAR}" placeholders are
                                               resolved from device capabilities). Returns the harness JSON result dict
                                               (always has "result": PASS|FAIL|NOT_APPLICABLE|SKIPPED|
                                               BLOCKED_PRECONDITION|HARNESS_ERROR). The FIRST h.op call is the
                                               primary operation used for the verdict.
  h.verify_op(cls, args, source, label="verify") -> dict
                                               Follow-up operation; arg values "<result.key>" are read from source.
  h.host(cmd)                                  Host step: "adb ..." command, "sleep N" or "<manual step>".
  h.expect(condition, description, actual=None, expected=None)
                                               Record one expected-result check; pass the measured value as
                                               actual= and the value it must have as expected= (both shown in
                                               the report).
  h.expect_pass(res, [descriptions])           Mark expected results satisfied when res["result"] == "PASS".
  h.check_slas(res)                            Evaluate every CASE["slas"] entry against res (required when
                                               CASE has "slas").
  h.combine(*results) -> dict                  Merge multi-phase results (worst result, summed *_count fields).
  h.derive(key, value)                         Store a host-computed metric (e.g. combined phases) for SLAs.
  h.manual(message, wait=False)                Record a manual checkpoint for the tester.
  h.not_applicable(reason)                     Stop: capability absent on this device.
  h.vars / h.capabilities / CASE               Read-only resolved variables, CapabilityTest JSON, case data.

Rules:
- Use ONLY the harness class(es) and args given in the operation map entry; never invent classes or args.
- Keep every arg value exactly as given: literal product-spec values stay literal and "${VAR}"
  placeholders stay placeholders (the runtime resolves them).
- Run host_pre steps first, then the operation (or phases in order, with their host steps and manual
  notes), then verify operations, then checks; put host_post steps in a `finally:` block.
- Pass args to h.op as a literal dict containing every mapped arg exactly as given.
- Multi-phase: call h.op once per phase; its literal dict = all mapped args + that phase's args
  (e.g. "phase": "after"), label = phase name. Compute the "combine" rule with
  h.derive(key, <python expression>), then res = h.combine(<phase results>).
- Performance / reliability / security (CASE has "slas"): end with h.check_slas(res).
- Functional: map each CASE["expected_results"] item to h.expect_pass(res, [...]) or to an explicit
  h.expect(...) on a result field you are sure the operation returns; nothing else.
- Include manual notes with h.manual(...). No imports, no file/network/process access, no print.
- Plain Python 3, 4-space indentation, short comments only where a step is non-obvious.

Return JSON only: {"body": "<statements of run(h), not indented, no def line>", "notes": ["..."]}"""

EXAMPLE = """Example (a different case) - operation map entry:
{"class": "com.example.cameratest.PermissionRevocationSecurityTest", "args": {"camera_id": "${REAR_PRIMARY_CAMERA_ID}"},
 "host_pre": ["adb shell pm grant com.example.cameratest android.permission.CAMERA"],
 "phases": [{"args": {"phase": "before"}}, {"host": ["adb shell pm revoke com.example.cameratest android.permission.CAMERA"]}, {"args": {"phase": "after"}}],
 "host_post": ["adb shell pm grant com.example.cameratest android.permission.CAMERA"],
 "combine": "revocation_enforced = before.metric_value == 1 and after.metric_value == 1"}
Example body:
h.host("adb shell pm grant com.example.cameratest android.permission.CAMERA")
try:
    before = h.op(
        "com.example.cameratest.PermissionRevocationSecurityTest",
        {"camera_id": "${REAR_PRIMARY_CAMERA_ID}", "phase": "before"},
        label="before",
    )
    h.host("adb shell pm revoke com.example.cameratest android.permission.CAMERA")
    after = h.op(
        "com.example.cameratest.PermissionRevocationSecurityTest",
        {"camera_id": "${REAR_PRIMARY_CAMERA_ID}", "phase": "after"},
        label="after",
    )
    h.derive("revocation_enforced", before.get("metric_value") == 1 and after.get("metric_value") == 1)
    res = h.combine(before, after)
    h.check_slas(res)
finally:
    h.host("adb shell pm grant com.example.cameratest android.permission.CAMERA")"""


def _llm_case_context(spec: dict[str, Any], tc: dict[str, Any], entry: dict[str, Any], contract: list[str]) -> str:
    procedure = [
        {k: step.get(k) for k in ("step_name", "action_type", "code_gen_hint") if step.get(k)}
        for step in tc.get("execution_procedure") or []
    ]
    steps = [s.get("action") for s in tc.get("steps") or [] if isinstance(s, dict)]
    ctx = {
        "case": {
            "ui_id": spec["ui_id"],
            "name": spec["name"],
            "category": spec["category"],
            "execution": spec["execution"],
            "objective": spec.get("objective"),
            "steps": steps or None,
            "expected_results": spec.get("expected_results"),
            "slas": spec.get("slas"),
            "execution_procedure": procedure or None,
        },
        "operation_map_entry": {
            k: v for k, v in entry.items()
            if k not in ("case_command", "source_id", "name", "execution")
        },
        "result_contract_fields": contract,
    }
    return json.dumps(ctx, indent=1, default=str)


def llm_body(
    spec: dict[str, Any], tc: dict[str, Any], entry: dict[str, Any], contract: list[str]
) -> tuple[str | None, list[str], list[str]]:
    """Return (body, notes, errors) from up to two LLM attempts."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": EXAMPLE + "\n\nNow write the body for this case:\n"
                                    + _llm_case_context(spec, tc, entry, contract)},
    ]
    errors: list[str] = []
    for _attempt in range(2):
        content, _usage = chat_completion(
            messages, temperature=0.0, response_format={"type": "json_object"}, max_tokens=2500,
        )
        data = parse_json_content(content) or {}
        body = data.get("body") if isinstance(data, dict) else None
        if not isinstance(body, str) or not body.strip():
            errors = ["LLM returned no body"]
        else:
            body = textwrap.dedent(body).strip("\n")
            errors, _warnings = validate_script(assemble_script(spec, body, "llm", "check"), spec, entry)
            if not errors:
                notes = [str(n) for n in data.get("notes") or []][:5]
                return body, notes, []
        messages += [
            {"role": "assistant", "content": content},
            {"role": "user", "content": "The body was rejected: " + "; ".join(errors)
                                        + ". Return corrected JSON only."},
        ]
    return None, [], errors


# ---------------------------------------------------------------- driver


def _generate_one(
    feature: str,
    ui_id: str,
    use_llm: bool,
    run_id: str,
    spec_values: dict[str, str] | None = None,
    spec_source: str | None = None,
) -> dict[str, Any]:
    op_map = load_operation_map()
    entry = (op_map.get("cases") or {}).get(ui_id)
    found = _find_case(feature, ui_id)
    if entry is None or found is None:
        return {
            "case_id": ui_id,
            "status": "error",
            "errors": [f"{ui_id}: " + ("no operation map entry" if entry is None else "test case not found")],
        }
    category, tc = found
    used = {k: v for k, v in (spec_values or {}).items() if k in placeholders_in([tc, entry])}
    if used:
        tc, entry = fill_placeholders(tc, used), fill_placeholders(entry, used)
    spec = build_case_spec(ui_id, category, tc, entry)
    if used:
        spec["spec_values"] = used
        spec["spec_source"] = spec_source or "product spec"
    contract = (op_map.get("contracts") or {}).get(entry.get("contract") or "", [])

    generator, notes, fallback_reason = "template", [], None
    body = None
    if use_llm:
        try:
            body, notes, llm_errors = llm_body(spec, tc, entry, contract)
            if body is not None:
                generator = "llm"
            else:
                fallback_reason = "LLM output rejected: " + "; ".join(llm_errors)
        except Exception as exc:
            logger.exception("LLM script generation failed for %s", ui_id)
            fallback_reason = f"LLM call failed: {exc}"
    if body is None:
        body = template_body(spec, entry)

    code = assemble_script(spec, body, generator, run_id)
    errors, warnings = validate_script(code, spec, entry)
    if fallback_reason:
        warnings.insert(0, fallback_reason + " (template used)")
    manual = [m for m in [entry.get("manual")] + [p.get("manual") for p in entry.get("phases") or []] if m]
    return {
        "case_id": ui_id,
        "source_id": spec["source_id"],
        "name": spec["name"],
        "category": category,
        "execution": spec["execution"],
        "harness_class": entry["class"],
        "filename": f"test_{ui_id}.py",
        "generator": generator,
        "status": "error" if errors else "ok",
        "errors": errors,
        "warnings": warnings,
        "notes": notes,
        "manual_steps": manual,
        "spec_values": used,
        "code": code,
    }


def _run_suite_source(filenames: list[str]) -> str:
    return (
        '#!/usr/bin/env python3\n'
        '"""Run every generated test script in this folder and summarise the verdicts."""\n\n'
        "import json\nimport subprocess\nimport sys\nfrom pathlib import Path\n\n"
        f"SCRIPTS = {_py(filenames)}\n\n\n"
        "def main() -> int:\n"
        "    here = Path(__file__).resolve().parent\n"
        "    summary = []\n"
        "    for name in SCRIPTS:\n"
        "        proc = subprocess.run([sys.executable, str(here / name), *sys.argv[1:]],\n"
        "                              capture_output=True, text=True, cwd=here)\n"
        "        sys.stderr.write(proc.stderr)\n"
        "        line = (proc.stdout.strip().splitlines() or ['{}'])[-1]\n"
        "        try:\n"
        "            summary.append(json.loads(line))\n"
        "        except json.JSONDecodeError:\n"
        "            summary.append({'script': name, 'verdict': 'ERROR', 'reason': line[:200]})\n"
        "        print(json.dumps(summary[-1]), flush=True)\n"
        "    (here / 'suite_summary.json').write_text(json.dumps(summary, indent=2))\n"
        "    return 0 if all(s.get('verdict') in ('PASS', 'MANUAL_REVIEW', 'NOT_APPLICABLE', 'SKIPPED')\n"
        "                    for s in summary) else 1\n\n\n"
        'if __name__ == "__main__":\n'
        "    raise SystemExit(main())\n"
    )


class FeatureDisabledError(Exception):
    """Script generation was requested for a feature that is turned off (ENABLED_TEST_FEATURES)."""


def generate_scripts(
    feature: str,
    case_ids: list[str],
    *,
    use_llm: bool = True,
    frameworks: list[str] | None = None,
    spec_features: list[dict[str, Any]] | None = None,
    product_name: str | None = None,
) -> dict[str, Any]:
    """Generate one script per case, write them with the runtime, return the bundle.

    spec_features are the UI feature cards of the current extraction; their values fill
    matching ${VAR} placeholders in the generated scripts only (catalog files are untouched).
    """
    if not is_feature_enabled(feature):
        raise FeatureDisabledError(f"Test script generation for '{feature}' is turned off")
    ids = list(dict.fromkeys(c.strip() for c in case_ids if c and c.strip()))
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    llm_ready = use_llm and is_azure_configured()
    derived = derive_spec_values(spec_features)
    values = {k: v["value"] for k, v in derived.items()}
    display = _is_display(feature)
    if display:
        from services.test_scripts import display_generator as dg

        def one(cid: str) -> dict[str, Any]:
            return dg.generate_one(cid, llm_ready, run_id, values, product_name)

        runtime_path, runtime_code = dg.RUNTIME_PATH, dg.runtime_source()
        harness_version, apk_dir = None, None
    else:
        def one(cid: str) -> dict[str, Any]:
            return _generate_one(feature, cid, llm_ready, run_id, values, product_name)

        runtime_path, runtime_code = RUNTIME_PATH, runtime_source()
        harness_version, apk_dir = load_operation_map().get("harness_version"), str(HARNESS_DIR)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS if llm_ready else 1) as pool:
        scripts = list(pool.map(one, ids))
    applied = sorted({k for s in scripts for k in s.get("spec_values") or {}})
    spec_profile = {
        "product_name": product_name,
        "derived": derived,
        "applied": {k: derived[k] for k in applied},
    }

    out_dir = OUTPUT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(runtime_path, out_dir / runtime_path.name)
    ok = [s for s in scripts if s["status"] == "ok"]
    for s in ok:
        (out_dir / s["filename"]).write_text(s["code"], encoding="utf-8")
    (out_dir / "run_suite.py").write_text(_run_suite_source([s["filename"] for s in ok]), encoding="utf-8")
    manifest = {
        "run_id": run_id,
        "feature": feature,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "frameworks": frameworks or [],
        "harness_version": harness_version,
        "apk_dir": apk_dir,
        "spec_profile": spec_profile,
        "scripts": [{k: v for k, v in s.items() if k != "code"} for s in scripts],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "run_id": run_id,
        "output_dir": str(out_dir),
        "apk_dir": apk_dir,
        "llm_used": llm_ready,
        "llm_configured": is_azure_configured(),
        "spec_profile": spec_profile,
        "summary": {
            "requested": len(ids),
            "generated": len(ok),
            "failed": len(scripts) - len(ok),
            "by_generator": {
                g: sum(1 for s in ok if s["generator"] == g) for g in ("llm", "template")
            },
        },
        "scripts": scripts,
        "runtime": {"filename": runtime_path.name, "code": runtime_code},
    }


def _is_display(feature: str) -> bool:
    return (feature or "").strip().lower().startswith("display")
