"""Generated script sets (one folder per generation run) and per-case execution readiness."""

from __future__ import annotations

import ast
import json
import re
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from services.test_cases import is_feature_enabled
from services.test_scripts.generator import OUTPUT_ROOT

_RUN_ID = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{6}$")
_PLACEHOLDER = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
_VARS_READ = re.compile(r"h\.vars(?:\.get\(|\[)\s*['\"]([A-Z][A-Z0-9_]*)['\"]")
_SECONDS_VAR = re.compile(r"_(SEC|SECS|SECONDS)$")
_COUNT_VAR = re.compile(r"(CYCLES|ITERATIONS|COUNT|SWEEPS|SESSIONS|REPEATS)$")
BASE_CASE_SECONDS = 15.0
SECONDS_PER_COUNT = 1.5

DEVICE_CHANGES = [
    (re.compile(r"locksettings\s+set-"), "sets a lock-screen credential"),
    (re.compile(r"\bsettings\s+put\s"), "changes system settings"),
    (re.compile(r"\bpm\s+clear\b"), "clears app data"),
    (re.compile(r"\bpm\s+revoke\b"), "revokes app permissions"),
    (re.compile(r"\bpm\s+uninstall\b"), "uninstalls packages"),
    (re.compile(r"\bappops\s+set\b"), "changes app-ops"),
    (re.compile(r"\bwm\s+(size|density)\s+\d"), "changes screen size / density"),
    (re.compile(r"\bcmd\s+uimode\b"), "changes the UI theme"),
    (re.compile(r"\badb\s+reboot\b|\breboot\b['\"]"), "reboots the device"),
    (re.compile(r"\bsvc\s+(wifi|data|bluetooth)\b"), "toggles radios"),
    (re.compile(r"\bdpm\s+"), "changes device policy"),
]


class ScriptSetNotFound(LookupError):
    """No generated script set with that run id."""


_REPEATED_LEAD = re.compile(r"^(\S+)(\s+\1)+(?=\s|$)", re.IGNORECASE)


def clean_product_name(name: str | None) -> str | None:
    """Collapse a repeated leading word ("Samsung Samsung Galaxy S25" -> "Samsung Galaxy S25")."""
    if not name:
        return name
    return _REPEATED_LEAD.sub(r"\1", " ".join(str(name).split()))


def run_dir(run_id: str) -> Path:
    if not _RUN_ID.match(run_id or ""):
        raise ScriptSetNotFound(run_id)
    path = OUTPUT_ROOT / run_id
    if not (path / "manifest.json").is_file():
        raise ScriptSetNotFound(run_id)
    return path


def _manifest(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _ok_scripts(path: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in manifest.get("scripts") or []
            if s.get("status") == "ok" and s.get("filename") and (path / s["filename"]).is_file()]


def list_script_sets() -> list[dict[str, Any]]:
    """Script sets of enabled features that contain at least one runnable script, newest first."""
    if not OUTPUT_ROOT.is_dir():
        return []
    out = []
    for path in sorted(OUTPUT_ROOT.iterdir(), reverse=True):
        manifest = _manifest(path) if _RUN_ID.match(path.name) else None
        if not manifest or not is_feature_enabled(manifest.get("feature") or ""):
            continue
        scripts = _ok_scripts(path, manifest)
        if not scripts:
            continue
        profile = manifest.get("spec_profile") or {}
        out.append({
            "run_id": path.name,
            "feature": manifest.get("feature"),
            "created_at": manifest.get("created_at"),
            "product_name": clean_product_name(profile.get("product_name")),
            "script_count": len(scripts),
            "by_generator": dict(Counter(s.get("generator") or "unknown" for s in scripts)),
            "by_category": dict(Counter(s.get("category") or "unknown" for s in scripts)),
            "execution_count": len(list((path / "executions").glob("*/execution.json"))),
        })
    return out


def load_case(script: Path) -> dict[str, Any]:
    """The CASE literal of a generated script."""
    tree = ast.parse(script.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "CASE" for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"{script.name}: CASE not found")


def runtime_constants(path: Path) -> dict[str, Any]:
    """Module-level literal constants of the runtime copied into the script set."""
    runtime = next((path / n for n in ("camharness.py", "dispharness.py") if (path / n).is_file()), None)
    if runtime is None:
        return {}
    out: dict[str, Any] = {"runtime": runtime.name}
    for node in ast.parse(runtime.read_text(encoding="utf-8")).body:
        target = node.target if isinstance(node, ast.AnnAssign) else (
            node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None)
        if not isinstance(target, ast.Name) or node.value is None:
            continue
        if target.id in ("DEFAULT_VARS", "APKS", "HARNESS_VERSION", "HARNESS_PKG", "PKG", "RUNTIME_VERSION"):
            try:
                out[target.id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    return out


def past_durations() -> dict[str, list[float]]:
    """Measured case durations (seconds) from every recorded result, keyed by case id."""
    durations: dict[str, list[float]] = {}

    def add(case_id: str | None, start: str | None, end: str | None) -> None:
        try:
            secs = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
        except (TypeError, ValueError):
            return
        if case_id and secs >= 0:
            durations.setdefault(case_id, []).append(secs)

    for result in OUTPUT_ROOT.glob("*/results/*/*_result.json"):
        try:
            r = json.loads(result.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        add(r.get("ui_id"), r.get("started_at"), r.get("finished_at"))
    for record in OUTPUT_ROOT.glob("*/executions/*/execution.json"):
        try:
            ex = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for c in ex.get("cases") or []:
            if c.get("verdict") not in (None, "STOPPED"):
                add(c.get("case_id"), c.get("started_at"), c.get("finished_at"))
    return durations


def _variables(case: dict[str, Any], text: str, defaults: dict[str, str]) -> list[dict[str, Any]]:
    names = sorted(set(_PLACEHOLDER.findall(text)) | set(_VARS_READ.findall(text)))
    spec = case.get("spec_values") or {}
    case_defaults = case.get("variable_defaults") or {}
    constants = case.get("constants") or {}
    out = []
    for name in names:
        if name in spec:
            value, source = spec[name], "product spec"
        elif name in case_defaults:
            value, source = case_defaults[name], "case default"
        elif name in constants:
            value, source = constants[name], "case constant"
        elif name in defaults:
            value, source = defaults[name], "runtime default"
        else:
            value, source = None, "device"
        kind = "seconds" if _SECONDS_VAR.search(name) else "count" if _COUNT_VAR.search(name) else None
        out.append({"name": name, "default": None if value is None else str(value), "source": source,
                    "kind": kind})
    return out


def estimate_seconds(variables: list[dict[str, Any]], overrides: dict[str, str] | None = None) -> float:
    total = BASE_CASE_SECONDS
    for v in variables:
        raw = (overrides or {}).get(v["name"], v["default"])
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if v["kind"] == "seconds":
            total += value
        elif v["kind"] == "count":
            total += value * SECONDS_PER_COUNT
    return total


def _readiness(case: dict[str, Any], consts: dict[str, Any], packages: dict[str, Any] | None,
               apk_dir: str | None) -> tuple[str, list[dict[str, str]]]:
    """(status, issues) with status one of ready | install | manual | lab | blocked | unknown."""
    issues: list[dict[str, str]] = []
    apks = consts.get("APKS") or {}
    want = consts.get("HARNESS_VERSION")
    for flavor in case.get("requires_apks") or []:
        pkg, apk = apks.get(flavor, (None, None))
        if not pkg:
            continue
        info = (packages or {}).get(pkg) or {}
        if packages is not None and info.get("installed") and (not want or info.get("version") == want):
            continue
        apk_path = Path(apk_dir) / apk if apk_dir and apk else None
        if apk_path and apk_path.is_file():
            have = f"version {info['version']}" if info.get("installed") else "not installed"
            issues.append({"level": "info", "text": f"{pkg} {have}; {apk} will be installed"
                           if packages is not None else f"{apk} is installed on demand"})
        else:
            issues.append({"level": "block", "text": f"{pkg} is not installed and {apk} is missing"})
    harness = case.get("harness") or {}
    if harness.get("required"):
        for pkg in [harness.get("package")] + list(harness.get("helper_apks") or []):
            if pkg and packages is not None and not (packages.get(pkg) or {}).get("installed"):
                issues.append({"level": "block", "text": f"{pkg} is not installed"})
    if harness.get("lab_equipment"):
        issues.append({"level": "lab", "text": "needs lab equipment: " + ", ".join(harness["lab_equipment"])})
    execution = (case.get("execution") or "").lower()
    if "manual" in execution or "semi" in execution:
        issues.append({"level": "manual", "text": f"{case.get('execution')}: includes tester checkpoints"})

    levels = {i["level"] for i in issues}
    status = ("blocked" if "block" in levels else "lab" if "lab" in levels else
              "manual" if "manual" in levels else "install" if "info" in levels else "ready")
    if packages is None and status in ("ready", "install"):
        status = "unknown"
    return status, issues


def _device_changes(text: str) -> list[str]:
    return sorted({label for regex, label in DEVICE_CHANGES if regex.search(text)})


def script_set_detail(run_id: str, packages: dict[str, Any] | None = None) -> dict[str, Any]:
    """Script set with per-case readiness for a device (packages from devices.harness_packages)."""
    path = run_dir(run_id)
    manifest = _manifest(path) or {}
    consts = runtime_constants(path)
    defaults = {k: str(v) for k, v in (consts.get("DEFAULT_VARS") or {}).items()}
    history = past_durations()
    cases = []
    for s in _ok_scripts(path, manifest):
        script = path / s["filename"]
        text = script.read_text(encoding="utf-8")
        try:
            case = load_case(script)
        except (SyntaxError, ValueError) as exc:
            cases.append({"case_id": s["case_id"], "filename": s["filename"], "name": s.get("name"),
                          "category": s.get("category"), "status": "blocked",
                          "issues": [{"level": "block", "text": f"script cannot be parsed: {exc}"}],
                          "variables": [], "estimate_s": BASE_CASE_SECONDS, "device_changes": []})
            continue
        status, issues = _readiness(case, consts, packages, manifest.get("apk_dir"))
        variables = _variables(case, text, defaults)
        past = history.get(case["ui_id"]) or []
        cases.append({
            "case_id": case["ui_id"],
            "source_id": case.get("source_id"),
            "name": case.get("name"),
            "category": case.get("category"),
            "execution": case.get("execution"),
            "objective": case.get("objective"),
            "filename": s["filename"],
            "generator": s.get("generator"),
            "status": status,
            "issues": issues,
            "variables": variables,
            "estimate_s": round(estimate_seconds(variables)),
            "history_s": round(statistics.median(past)) if past else None,
            "device_changes": _device_changes(text),
            "spec_values": case.get("spec_values") or {},
            "slas": case.get("slas") or [],
        })
    profile = manifest.get("spec_profile") or {}
    return {
        "run_id": run_id,
        "feature": manifest.get("feature"),
        "created_at": manifest.get("created_at"),
        "product_name": clean_product_name(profile.get("product_name")),
        "spec_applied": profile.get("applied") or {},
        "apk_dir": manifest.get("apk_dir"),
        "harness_version": manifest.get("harness_version") or consts.get("HARNESS_VERSION"),
        "runtime": consts.get("runtime"),
        "runtime_version": consts.get("RUNTIME_VERSION"),
        "cases": cases,
    }


def script_source(run_id: str, filename: str) -> str:
    path = run_dir(run_id)
    target = (path / filename).resolve()
    if target.parent != path.resolve() or target.suffix != ".py" or not target.is_file():
        raise ScriptSetNotFound(f"{run_id}/{filename}")
    return target.read_text(encoding="utf-8")
