"""Camera test-script runtime shared by every generated camera test script.

Generated scripts contain a CASE dict and a run(h) function; everything else
(device checks, harness install, variable resolution, instrumentation, result
parsing, SLA evaluation, evidence, verdict) lives here so every script behaves
the same way.

Usage (from a generated script):  python3 test_cam_fun_001.py [--serial X] [--out DIR]
                                  [--var NAME=VALUE ...] [--apk-dir DIR] [--no-setup]
"""

from __future__ import annotations

import argparse
import json
import operator
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

RUNTIME_VERSION = "1.3.0"
HARNESS_VERSION = "2.0.1"
PKG = "com.example.cameratest"
RUNNER = "androidx.test.runner.AndroidJUnitRunner"
JSON_PREFIX = "INSTRUMENTATION_STATUS: harness_json="

APKS = {
    "harness": ("com.example.cameratest", "cameratest.apk"),
    "unauthorized": ("com.example.cameraunauthorized", "cameratest-unauthorized.apk"),
    "secondary": ("com.example.camerasecondary", "cameratest-secondary.apk"),
}

DEFAULT_VARS: dict[str, str] = {
    "CAMERA_TEST_PACKAGE": "com.example.cameratest",
    "UNAUTHORIZED_TEST_PACKAGE": "com.example.cameraunauthorized",
    "SECONDARY_TEST_PACKAGE": "com.example.camerasecondary",
    "DEFAULT_IMAGE_FORMAT": "JPEG",
    "HDR_CAPTURE_TYPE": "photo",
    "FOCUS_POINT_X": "0.5",
    "FOCUS_POINT_Y": "0.5",
    "PERF_ITERATIONS": "10",
    "HIGH_RES_ITERATIONS": "5",
    "BURST_CAPTURE_COUNT": "10",
    "MEMORY_CAPTURE_COUNT": "20",
    "MEDIA_INTEGRITY_CAPTURE_COUNT": "20",
    "MEDIA_TEST_FILE_COUNT": "3",
    "RESOURCE_SAMPLE_INTERVAL_SEC": "1",
    "CPU_TEST_DURATION_SEC": "60",
    "ENDURANCE_CYCLES": "1000",
    "AF_CYCLES": "20",
    "FLASH_CYCLES": "10",
    "ZOOM_CYCLES": "20",
    "SWITCH_ITERATIONS": "20",
    "LENS_SWITCH_CYCLES": "20",
    "ORIENTATION_CYCLES": "20",
    "LOCK_UNLOCK_CYCLES": "50",
    "BACKGROUND_FOREGROUND_CYCLES": "50",
    "CAMERASERVICE_SESSION_CYCLES": "100",
    "MEMORY_LEAK_CYCLES": "100",
    "RESOURCE_RELEASE_CYCLES": "100",
    "VIDEO_FPS": "30",
    "FPS_TOLERANCE": "2",
    "FPS_TEST_DURATION_SEC": "10",
    "FPS_STABILITY_DURATION_SEC": "60",
    "RECORDING_DURATION_SEC": "10",
    "VIDEO_SHORT_DURATION_SEC": "5",
    "VIDEO_RESOLUTION_TEST_DURATION_SEC": "5",
    "LONG_PREVIEW_DURATION_SEC": "3600",
    "LONG_VIDEO_DURATION_SEC": "3600",
    "ENDURANCE_MONITOR_DURATION_SEC": "3600",
    "BACKGROUND_OBSERVATION_SEC": "30",
    "AUDIT_LOG_WINDOW_SEC": "60",
    # Lab scene set-up shown in tester checkpoints; override per lab.
    "FOCUS_TEST_TARGET": "a high-contrast focus chart about 50 cm away",
    "AMBIENT_LIGHT_LUX": "20",
    "LIGHT_CONDITION": "dim indoor light",
    "HDR_TEST_SCENE": "backlit scene (subject in front of a bright window)",
    "PORTRAIT_TEST_SCENE": "a person or mannequin head in front of a textured background",
    "PORTRAIT_SUBJECT_DISTANCE": "1.5 m",
    "LOW_LIGHT_LUX": "5",
    "LOW_LIGHT_TEST_SCENE": "a colour chart in a darkened room",
    "LOW_LIGHT_CONDITION": "a darkened room",
}

MEDIA_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".dng", ".mp4", ".3gp", ".webm")
MAX_MEDIA_FILES = 12
MAX_MEDIA_BYTES = 50 * 1024 * 1024

VERDICT_ORDER = [
    "PASS",
    "MANUAL_REVIEW",
    "SKIPPED",
    "NOT_APPLICABLE",
    "BLOCKED_PRECONDITION",
    "FAIL",
    "ERROR",
]

_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "==": operator.eq,
    "!=": operator.ne,
    "<=": operator.le,
    "<": operator.lt,
    ">=": operator.ge,
    ">": operator.gt,
}


class Blocked(Exception):
    """Precondition not met; the case is reported as BLOCKED_PRECONDITION."""


class NotApplicable(Exception):
    """Capability absent on this device; the case is reported as NOT_APPLICABLE."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", file=sys.stderr, flush=True)


_EXPECTED_IN_TEXT = re.compile(r"\b(?:matches|equals|is at least|is at most|within)\s+(.+?)\.?$", re.IGNORECASE)


def _expected_from(description: str) -> str | None:
    """'Saved image resolution matches 8160x6120' -> '8160x6120'."""
    m = _EXPECTED_IN_TEXT.search(str(description))
    return m.group(1).strip() if m else None


def _area(res: str) -> int:
    m = re.match(r"^(\d+)x(\d+)$", str(res).strip())
    return int(m.group(1)) * int(m.group(2)) if m else 0


def _num(v: Any) -> Any:
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return v
    try:
        f = float(str(v))
        return int(f) if f.is_integer() else f
    except ValueError:
        return v


def _item_label(item: dict[str, Any]) -> str:
    for key in ("resolution", "aspect_ratio", "profile"):
        if item.get(key):
            return str(item[key])
    ratio = item.get("requested_ratio")
    if isinstance(ratio, (int, float)):
        return f"{ratio:g}x"
    return str(ratio or "item")


def _item_outcomes(args: dict[str, str], res: dict[str, Any]) -> tuple[list[str], list[str], int] | None:
    """(unsupported labels, failed labels, passed count) of a per-item result (details / points)."""
    items = next((res[k] for k in ("details", "points") if isinstance(res.get(k), list)), None)
    if items is None:
        return None
    unsupported: list[str] = []
    failed: list[str] = []
    passed = 0
    for item in (i for i in items if isinstance(i, dict)):
        label = _item_label(item)
        if item.get("result") == "SKIPPED" or item.get("supported") is False:
            unsupported.append(label)
        elif (item.get("result") == "FAIL" or item.get("ok") is False or item.get("ratio_matches") is False
              or (item.get("error") and item.get("ok") is not True and item.get("result") != "PASS")):
            failed.append(f"{label} ({item.get('error') or 'mismatch'})")
        else:
            passed += 1
    # Harness 2.0.0 clamps out-of-range zoom ratios instead of reporting them.
    applied = [_num(i.get("applied_ratio")) for i in items if isinstance(i, dict)]
    for raw in re.split(r"[,\s]+", str(args.get("zoom_ratios") or "").strip("[]")):
        want = _num(raw.strip().rstrip("x"))
        if isinstance(want, (int, float)) and f"{want:g}x" not in unsupported and not any(
                isinstance(a, (int, float)) and abs(a - want) < 0.05 for a in applied):
            unsupported.append(f"{want:g}x")
    return unsupported, failed, passed


def _judge_items(args: dict[str, str], res: dict[str, Any]) -> dict[str, Any]:
    """Make a per-item result's verdict reflect its items and name the unsupported ones."""
    outcome = _item_outcomes(args, res)
    if not outcome or not (outcome[0] or outcome[1]) or res.get("result") not in ("PASS", "FAIL", "NOT_APPLICABLE"):
        return res
    unsupported, failed, passed = outcome
    summary = "; ".join(
        ([f"unsupported: {', '.join(unsupported)}"] if unsupported else [])
        + ([f"failed: {', '.join(failed)}"] if failed else []))
    if res["result"] == "PASS":
        return {**res, "harness_result": "PASS", "result": "FAIL" if failed or passed else "SKIPPED", "error": summary}
    key = "reason" if res["result"] == "NOT_APPLICABLE" else "error"
    if "unsupported:" in str(res.get(key) or ""):
        return res
    return {**res, key: "; ".join(filter(None, [str(res.get(key) or ""), summary]))}


class Harness:
    """Device + harness session for one test case."""

    def __init__(
        self,
        case: dict[str, Any],
        *,
        serial: str | None,
        out_dir: Path,
        apk_dir: Path | None,
        overrides: dict[str, str],
    ) -> None:
        self.case = case
        self.serial = serial
        self.out_dir = out_dir
        self.apk_dir = apk_dir
        self.overrides = overrides
        self.vars: dict[str, str] = {}
        self.capabilities: dict[str, Any] = {}
        self.operations: list[dict[str, Any]] = []
        self.checks: list[dict[str, Any]] = []
        self.manual_steps: list[str] = []
        self.host_log: list[dict[str, Any]] = []
        self.derived: dict[str, Any] = {}
        self.notes: list[str] = []

    # ------------------------------------------------------------------ adb

    def _adb_prefix(self) -> list[str]:
        return ["adb", "-s", self.serial] if self.serial else ["adb"]

    def adb(self, *args: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
        cmd = self._adb_prefix() + list(args)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def shell(self, command: str, timeout: float = 120) -> str:
        return self.adb("shell", command, timeout=timeout).stdout

    def host(self, command: str, *, ignore_failure: bool = True, timeout: float = 600) -> str:
        """Run one host step from the case ("adb ...", "sleep N" or "<manual step>")."""
        command = self.resolve(command).strip()
        if command.startswith("<") and command.endswith(">"):
            self.manual(command.strip("<>"), wait=True)
            return ""
        m = re.match(r"^sleep\s+(\d+(?:\.\d+)?)$", command)
        if m:
            _log(f"host: sleep {m.group(1)}s")
            time.sleep(float(m.group(1)))
            self.host_log.append({"command": command, "rc": 0})
            return ""
        if not command.startswith("adb "):
            raise ValueError(f"host step must start with 'adb ', 'sleep' or '<': {command}")
        prefix = " ".join(shlex.quote(p) for p in self._adb_prefix())
        full = prefix + command[3:]
        _log(f"host: {command}")
        proc = subprocess.run(
            full, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=self.out_dir,
        )
        self.host_log.append({"command": command, "rc": proc.returncode})
        if re.search(r"\badb\s+reboot\b", command):
            self._wait_for_boot()
        if proc.returncode != 0 and not ignore_failure:
            raise Blocked(f"host step failed ({proc.returncode}): {command}: {proc.stderr.strip()[:300]}")
        return proc.stdout

    def _wait_for_boot(self, timeout: float = 300) -> None:
        self.adb("wait-for-device", timeout=timeout)
        end = time.time() + timeout
        while time.time() < end:
            if self.shell("getprop sys.boot_completed").strip() == "1":
                return
            time.sleep(2)
        raise Blocked("device did not finish booting")

    # ------------------------------------------------------------- preflight

    def preflight(self, run_setup: bool) -> None:
        devices = subprocess.run(["adb", "devices"], capture_output=True, text=True).stdout
        online = [l.split()[0] for l in devices.splitlines()[1:] if l.strip().endswith("device")]
        if not online:
            raise Blocked("no adb device online")
        if self.serial and self.serial not in online:
            raise Blocked(f"device {self.serial} not online")
        if not self.serial and len(online) > 1:
            raise Blocked(f"multiple devices online {online}; pass --serial")
        self.serial = self.serial or online[0]

        for flavor in self.case.get("requires_apks") or ["harness"]:
            self.ensure_apk(flavor)
        # Security cases manage the CAMERA grant themselves (host_pre / phases).
        if self.case.get("contract") != "security":
            self.adb("shell", "pm", "grant", PKG, "android.permission.CAMERA")
        self.check_prerequisites(self.case.get("prerequisites") or {})
        if run_setup:
            for step in self.case.get("setup_commands") or []:
                self.host(step["command"], ignore_failure=bool(step.get("ignore_failure", True)))
        self.adb("logcat", "-c")

    def ensure_apk(self, flavor: str) -> None:
        """Install the flavor when missing or not at HARNESS_VERSION."""
        pkg, apk = APKS[flavor]
        listed = self.shell("pm list instrumentation")
        m = re.search(r"versionName=(\S+)", self.shell(f"dumpsys package {pkg}"))
        installed = m.group(1) if m else None
        if f"instrumentation:{pkg}/" in listed and installed == HARNESS_VERSION:
            return
        path = (self.apk_dir / apk) if self.apk_dir else None
        if not path or not path.is_file():
            state = f"version {installed}" if installed else "not installed"
            raise Blocked(f"{apk} {state}, need {HARNESS_VERSION}; pass --apk-dir with the built APKs")
        _log(f"installing {apk} (installed: {installed or 'none'}, need {HARNESS_VERSION})")
        res = self.adb("install", "-r", "-g", str(path), timeout=300)
        if "Success" not in (res.stdout + res.stderr):
            raise Blocked(f"install {apk} failed: {(res.stdout + res.stderr).strip()[:300]}")

    def check_prerequisites(self, pre: dict[str, Any]) -> None:
        if not isinstance(pre, dict):
            return
        battery = self.shell("dumpsys battery")
        level = re.search(r"level:\s*(\d+)", battery)
        temp = re.search(r"temperature:\s*(\d+)", battery)
        min_pct = (pre.get("battery_state") or {}).get("min_charge_pct")
        if min_pct is not None and level and int(level.group(1)) < int(min_pct):
            raise Blocked(f"battery {level.group(1)}% < {min_pct}%")
        max_c = (pre.get("thermal_limits") or {}).get("battery_temp_max_c")
        if max_c is not None and temp and int(temp.group(1)) / 10 > float(max_c):
            raise Blocked(f"battery temperature {int(temp.group(1)) / 10}C > {max_c}C")

    # ------------------------------------------------------------ variables

    def load_capabilities(self) -> None:
        res = self.run_instrumentation(f"{PKG}.CapabilityTest", {})
        if res.get("result") != "PASS":
            raise Blocked(f"CapabilityTest failed: {res.get('error') or res.get('result')}")
        self.capabilities = res
        self.vars = {**DEFAULT_VARS, **self._derive_vars(res)}
        self.vars.update(self.case.get("spec_values") or {})
        self.vars.update(self.case.get("variable_defaults") or {})
        self.vars.update(self.overrides)

    def _derive_vars(self, caps: dict[str, Any]) -> dict[str, str]:
        cams = caps.get("cameras") or []
        back = [c for c in cams if c.get("facing") == "BACK"]
        front = [c for c in cams if c.get("facing") == "FRONT"]
        rear = back[0] if back else None
        fr = front[0] if front else None
        target = rear or fr
        v: dict[str, str] = {}

        def res_list(cam: dict[str, Any] | None, key: str) -> list[str]:
            return sorted((cam or {}).get(key) or [], key=_area, reverse=True)

        if rear:
            v["REAR_PRIMARY_CAMERA_ID"] = str(rear["id"])
            if res_list(rear, "resolutions"):
                v["REAR_PRIMARY_PHOTO_RESOLUTION"] = res_list(rear, "resolutions")[0]
        if fr:
            v["FRONT_PRIMARY_CAMERA_ID"] = str(fr["id"])
            if res_list(fr, "resolutions"):
                v["FRONT_PRIMARY_PHOTO_RESOLUTION"] = res_list(fr, "resolutions")[0]
        if target:
            v["TARGET_CAMERA_ID"] = str(target["id"])
            photo = res_list(target, "resolutions")
            if photo:
                v["PHOTO_RESOLUTION"] = photo[0]
                v["MAX_SUPPORTED_PHOTO_RESOLUTION"] = photo[0]
                v["SUPPORTED_PHOTO_RESOLUTIONS"] = ",".join(photo[:8])
            if target.get("aspectRatios"):
                v["SUPPORTED_PHOTO_ASPECT_RATIOS"] = ",".join(target["aspectRatios"])
            video = res_list(target, "encoderVideoSizes") or res_list(target, "videoSizes")
            common = [r for r in ("3840x2160", "1920x1080", "1280x720") if r in video]
            if video:
                v["VIDEO_RESOLUTION"] = "1920x1080" if "1920x1080" in video else next(
                    (r for r in video if _area(r) <= 1920 * 1080), video[-1]
                )
                v["SUPPORTED_VIDEO_RESOLUTIONS"] = ",".join(common or video[:3])
                fps = [f for f in (30, 60) if any(
                    str(r).endswith(f"-{f}") for r in target.get("fpsRanges") or []
                )] or [30]
                v["SUPPORTED_VIDEO_PROFILES"] = ",".join(
                    f"{r}@{f}" for r in (common or video[:2]) for f in fps
                )
            zoom = str(target.get("zoomRatioRange") or "")
            if "-" in zoom:
                lo, hi = zoom.split("-", 1)
                v["MIN_ZOOM_RATIO"], v["MAX_ZOOM_RATIO"], v["MAX_DIGITAL_ZOOM_RATIO"] = lo, hi, hi
        flash = next((c for c in cams if c.get("hasFlash")), None)
        if flash:
            v["FLASH_SUPPORTED_CAMERA_ID"] = str(flash["id"])
        for key, names in (("NIGHT_MODE_SUPPORTED_CAMERA_ID", {"NIGHT"}),
                           ("PORTRAIT_SUPPORTED_CAMERA_ID", {"PORTRAIT", "BOKEH"})):
            cam = next((c for c in cams if names & set(
                (c.get("extensions") or []) + (c.get("sceneModes") or [])
            )), None)
            if cam:
                v[key] = str(cam["id"])

        base = (rear or {}).get("equivalentFocalMm")
        if base:
            lenses = [(str(c["id"]), c.get("equivalentFocalMm")) for c in back[1:]]
            for c in back:
                lenses += [(str(p["id"]), p.get("equivalentFocalMm")) for p in c.get("physicalCameras") or []]
            lenses = [(i, f) for i, f in lenses if f]
            tele = [(i, f) for i, f in lenses if f >= 1.8 * base]
            wide = [(i, f) for i, f in lenses if f <= 0.8 * base]
            if tele:
                v["TELEPHOTO_CAMERA_ID"] = min(tele, key=lambda t: t[1])[0]
            if wide:
                v["ULTRAWIDE_CAMERA_ID"] = max(wide, key=lambda t: t[1])[0]
            ratios = sorted({round(f / base, 1) for _, f in tele})
            if ratios:
                v["SUPPORTED_OPTICAL_ZOOM_RATIOS"] = ",".join(f"{r:g}" for r in ratios)
        return v

    def resolve(self, value: Any) -> str:
        """Substitute ${VAR}; raise NotApplicable when a capability variable is unknown."""
        text = str(value)

        def sub(m: re.Match[str]) -> str:
            name = m.group(1)
            if name in self.vars:
                return self.vars[name]
            raise NotApplicable(f"${{{name}}} is not available on this device")

        return re.sub(r"\$\{([A-Z0-9_]+)\}", sub, text)

    # ------------------------------------------------------------ operations

    def run_instrumentation(self, cls: str, args: dict[str, str], timeout: float = 7200) -> dict[str, Any]:
        cmd = ["shell", "am", "instrument", "-w", "-r"]
        for k, val in args.items():
            cmd += ["-e", k, shlex.quote(str(val))]
        cmd += ["-e", "class", cls, f"{PKG}/{RUNNER}"]
        try:
            proc = self.adb(*cmd, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"result": "HARNESS_ERROR", "error": f"timeout after {timeout}s"}
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.startswith(JSON_PREFIX):
                try:
                    return json.loads(line[len(JSON_PREFIX):])
                except json.JSONDecodeError:
                    break
        return {"result": "HARNESS_ERROR", "error": "no harness_json in output", "raw": proc.stdout[-1500:]}

    def op(self, cls: str, args: dict[str, Any] | None = None, *, label: str = "main",
           timeout: float = 7200) -> dict[str, Any]:
        """Run one harness operation and record its JSON result."""
        if not cls.startswith(PKG + "."):
            raise ValueError(f"unknown harness class {cls}")
        resolved = {k: self.resolve(val) for k, val in (args or {}).items()}
        _log(f"op[{label}]: {cls.rsplit('.', 1)[-1]} {resolved}")
        started = time.time()
        res = _judge_items(resolved, self.run_instrumentation(cls, resolved, timeout=timeout))
        self.operations.append({
            "label": label,
            "class": cls,
            "args": resolved,
            "duration_s": round(time.time() - started, 2),
            "result": res,
        })
        _log(f"op[{label}]: {res.get('result')} {res.get('error') or res.get('reason') or ''}".rstrip())
        return res

    def verify_op(self, cls: str, args: dict[str, Any], source: dict[str, Any], *,
                  label: str = "verify") -> dict[str, Any]:
        """Run a follow-up operation; "<result.key>" placeholders read from source."""
        filled: dict[str, Any] = {}
        for k, val in args.items():
            m = re.fullmatch(r"<result\.([a-zA-Z0-9_]+)>", str(val))
            if m:
                if source.get(m.group(1)) in (None, ""):
                    self.expect(False, f"{label}: previous result has no '{m.group(1)}'",
                                actual="not returned", expected=f"'{m.group(1)}' from the previous step")
                    return {"result": "SKIPPED", "error": f"missing {m.group(1)}"}
                filled[k] = source[m.group(1)]
            else:
                filled[k] = val
        return self.op(cls, filled, label=label)

    # --------------------------------------------------------------- checks

    def expect(self, condition: bool, description: str, actual: Any = None, *, expected: Any = None) -> bool:
        ok = bool(condition)
        description = self.resolve_soft(description)
        if expected is None:
            expected = _expected_from(description)
        self.checks.append({
            "type": "expect",
            "description": description,
            "passed": ok,
            "expected": expected if expected is not None else "condition holds",
            "actual": actual,
        })
        return ok

    def expect_pass(self, res: dict[str, Any], expected: list[str] | str) -> bool:
        """Mark expected results as satisfied when the operation reported PASS."""
        items = [expected] if isinstance(expected, str) else list(expected)
        ok = res.get("result") == "PASS"
        detail = res.get("error") or res.get("reason")
        for item in items:
            description = self.resolve_soft(item)
            self.checks.append({
                "type": "expect",
                "description": description,
                "passed": ok,
                "expected": _expected_from(description) or "PASS",
                "actual": res.get("result") if ok else f"{res.get('result')}: {detail}",
            })
        return ok

    def resolve_soft(self, text: str) -> str:
        return re.sub(r"\$\{([A-Z0-9_]+)\}", lambda m: self.vars.get(m.group(1), m.group(0)), str(text))

    def derive(self, key: str, value: Any) -> Any:
        """Record a host-computed metric (e.g. combined multi-phase result) for SLA checks."""
        self.derived[key] = value
        return value

    def metric(self, res: dict[str, Any], key: str) -> Any:
        if key in self.derived:
            val = self.derived[key]
        elif key in res:
            val = res[key]
        else:
            val = res.get("metric_value")
        return int(val) if isinstance(val, bool) else _num(val)

    def check_slas(self, res: dict[str, Any]) -> bool:
        """Evaluate every CASE['slas'] entry against res (derived values win)."""
        all_ok = True
        for sla in self.case.get("slas") or []:
            key = sla["metric_key"]
            actual = self.metric(res, key)
            fn = _OPS.get(sla["operator"])
            target = _num(self.resolve_soft(sla["target_value"]))
            ok = fn is not None and actual is not None and not isinstance(actual, str) and fn(actual, target)
            entry = {
                "type": "sla",
                "description": f"{key} {sla['operator']} {target}{sla.get('unit') and ' ' + sla['unit'] or ''}",
                "metric_key": key,
                "expected": f"{sla['operator']} {target}{sla.get('unit') and ' ' + sla['unit'] or ''}",
                "actual": actual if actual is not None else "not measured",
                "target": target,
                "operator": sla["operator"],
                "passed": bool(ok),
            }
            crit = sla.get("critical_threshold")
            if not ok and crit is not None and isinstance(actual, (int, float)) and fn is not None:
                entry["critical"] = not fn(actual, _num(crit))
            if not ok and sla.get("failure_classification"):
                entry["failure_classification"] = sla["failure_classification"]
            self.checks.append(entry)
            _log(f"sla: {key} = {actual} (target {sla['operator']} {target}) {'ok' if ok else 'FAIL'}")
            all_ok = all_ok and bool(ok)
        return all_ok

    def combine(self, *results: dict[str, Any]) -> dict[str, Any]:
        """Merge multi-phase results: worst result, summed *_count fields, last phase facts."""
        merged: dict[str, Any] = {}
        for r in results:
            merged.update(r)
        rank = {"PASS": 0, "NOT_APPLICABLE": 1, "SKIPPED": 2, "BLOCKED_PRECONDITION": 3, "FAIL": 4, "HARNESS_ERROR": 5}
        merged["result"] = max((r.get("result", "HARNESS_ERROR") for r in results), key=lambda x: rank.get(x, 5))
        for key in {k for r in results for k in r if k.endswith("_count")}:
            merged[key] = sum(_num(r.get(key) or 0) for r in results if isinstance(_num(r.get(key) or 0), (int, float)))
        return merged

    def manual(self, message: str, *, wait: bool = False) -> None:
        """Record a manual checkpoint; with wait=True pause for Enter on an interactive terminal."""
        text = self.resolve_soft(message)
        self.manual_steps.append(text)
        _log(f"MANUAL: {text}")
        if wait and sys.stdin.isatty():
            input("Press Enter when done... ")

    def not_applicable(self, reason: str) -> None:
        raise NotApplicable(reason)

    # -------------------------------------------------------------- evidence

    def collect_evidence(self) -> list[str]:
        files: list[str] = []
        ev = self.case.get("evidence") or {}
        cmds = []
        logcat = ev.get("logcat_config") or {}
        if logcat.get("dump_command"):
            cmds.append(logcat["dump_command"])
        cmds += [d["command"] for d in ev.get("subsystem_dumps") or [] if d.get("command")]
        if not cmds:
            cmds = [f"adb logcat -d -v threadtime > {self.case['ui_id']}_logcat.txt"]
        for c in cmds:
            try:
                self.host(c)
                m = re.search(r">\s*(\S+)\s*$", c)
                if m:
                    files.append(str(self.out_dir / m.group(1)))
            except Exception as exc:  # evidence must never mask the verdict
                self.notes.append(f"evidence '{c}' failed: {exc}")
        try:
            files += self.collect_media()
        except Exception as exc:
            self.notes.append(f"copying captured media failed: {exc}")
        return files

    def _media_paths(self) -> list[str]:
        found: list[str] = []

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for v in value.values():
                    walk(v)
            elif isinstance(value, list):
                for v in value:
                    walk(v)
            elif (isinstance(value, str) and value.startswith("/") and value.lower().endswith(MEDIA_EXTENSIONS)
                  and value not in found):
                found.append(value)

        for o in self.operations:
            walk(o["result"])
        return found

    def collect_media(self) -> list[str]:
        """Copy photos / videos the operations saved on the device into the evidence folder."""
        paths = self._media_paths()
        files: list[str] = []
        for remote in paths[:MAX_MEDIA_FILES]:
            size = _num(self.shell(f"stat -c %s {shlex.quote(remote)} 2>/dev/null").strip())
            if not isinstance(size, int):
                continue  # removed by the operation (keep_files=false)
            if size > MAX_MEDIA_BYTES:
                self.notes.append(f"{remote} left on the device ({size // 1048576} MB is over the copy limit)")
                continue
            local = self.out_dir / Path(remote).name
            self.host(f"adb pull {shlex.quote(remote)} {shlex.quote(local.name)}")
            if local.is_file():
                files.append(str(local))
        if len(paths) > MAX_MEDIA_FILES:
            self.notes.append(f"{len(paths) - MAX_MEDIA_FILES} more captured file(s) left on the device")
        return files

    def teardown(self) -> None:
        for step in self.case.get("teardown_commands") or []:
            try:
                self.host(step["command"])
            except Exception as exc:
                self.notes.append(f"teardown '{step['command']}' failed: {exc}")

    # --------------------------------------------------------------- verdict

    def verdict(self) -> tuple[str, str]:
        results = [o["result"].get("result") for o in self.operations if o["label"] != "capabilities"]
        if not results:
            return "ERROR", "run() executed no harness operation"
        main = self.operations[0]["result"]
        mismatch = self._spec_mismatch(main)
        if mismatch:
            return "FAIL", mismatch
        if main.get("result") == "NOT_APPLICABLE":
            return "NOT_APPLICABLE", str(main.get("reason") or main.get("error") or "")
        if main.get("result") == "SKIPPED":
            return "SKIPPED", str(main.get("error") or "")
        if main.get("result") == "BLOCKED_PRECONDITION":
            return "BLOCKED_PRECONDITION", str(main.get("error") or main.get("reason") or "")
        bad_ops = [o for o in self.operations if o["result"].get("result") in ("FAIL", "HARNESS_ERROR")]
        failed = [c for c in self.checks if not c["passed"]]
        if bad_ops or failed:
            reasons = [f"{o['label']}: {o['result'].get('error') or o['result'].get('result')}" for o in bad_ops]
            reasons += [f"{c['description']} (actual {c.get('actual')})" for c in failed]
            return "FAIL", "; ".join(reasons)[:1000]
        if self.manual_steps:
            return "MANUAL_REVIEW", f"{len(self.manual_steps)} manual checkpoint(s)"
        return "PASS", ""

    def _spec_mismatch(self, main: dict[str, Any]) -> str:
        """A product-spec value the device rejects is a spec failure, not an absent capability."""
        result = main.get("result")
        if result not in ("NOT_APPLICABLE", "SKIPPED", "FAIL"):
            return ""
        reason = str(main.get("reason") or main.get("error") or "")
        listed = re.search(r"unsupported: ([^;]*)", reason)
        unsupported = {t.strip().lower().rstrip("x") for t in listed.group(1).split(",")} if listed else set()
        if result == "FAIL" and not unsupported:
            return ""

        def rejected(item: str) -> bool:
            key = item.lower().rstrip("x")
            return any(key == u or u.startswith(key + "@") or key.startswith(u + "@") for u in unsupported)

        for name, value in (self.case.get("spec_values") or {}).items():
            text = str(value)
            if text in ("true", "false"):
                continue
            hit = ", ".join(p.strip() for p in text.split(",") if p.strip() and rejected(p.strip())) or None
            if hit is None and result != "FAIL" and len(text) >= 3 and text in reason:
                hit = text
            if hit:
                return (f"Spec mismatch: device does not support {name}={hit} from "
                        f"{self.case.get('spec_source') or 'the product spec'} (harness: {reason})")
        return ""


def _parse_args(case: dict[str, Any]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=f"{case['ui_id']} - {case['name']}")
    p.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL"))
    p.add_argument("--out", default=None, help="evidence/result directory")
    p.add_argument("--apk-dir", default=os.environ.get("CAMERATEST_APK_DIR"))
    p.add_argument("--var", action="append", default=[], metavar="NAME=VALUE")
    p.add_argument("--no-setup", action="store_true", help="skip CASE setup_commands")
    return p.parse_args()


def main(case: dict[str, Any], run: Callable[[Harness], None]) -> int:
    """Entry point used by every generated script."""
    args = _parse_args(case)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out or f"results/{case['ui_id']}_{stamp}").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    overrides = dict(v.split("=", 1) for v in args.var if "=" in v)
    apk_dir = args.apk_dir
    manifest = Path(sys.argv[0]).resolve().parent / "manifest.json"
    if not apk_dir and manifest.is_file():
        apk_dir = json.loads(manifest.read_text(encoding="utf-8")).get("apk_dir")
    h = Harness(
        case,
        serial=args.serial,
        out_dir=out_dir,
        apk_dir=Path(apk_dir).resolve() if apk_dir else None,
        overrides=overrides,
    )
    started = _now()
    verdict, reason = "ERROR", ""
    evidence: list[str] = []
    try:
        h.preflight(run_setup=not args.no_setup)
        h.load_capabilities()
        run(h)
        verdict, reason = h.verdict()
    except Blocked as exc:
        verdict, reason = "BLOCKED_PRECONDITION", str(exc)
    except NotApplicable as exc:
        verdict, reason = "NOT_APPLICABLE", str(exc)
    except KeyboardInterrupt:
        verdict, reason = "ERROR", "interrupted before a verdict (SIGINT)"
    except Exception as exc:
        verdict, reason = "ERROR", f"{type(exc).__name__}: {exc}"
    finally:
        if h.serial:
            evidence = h.collect_evidence()
            h.teardown()

    report = {
        "ui_id": case["ui_id"],
        "source_id": case.get("source_id"),
        "name": case["name"],
        "category": case.get("category"),
        "verdict": verdict,
        "reason": reason,
        "started_at": started,
        "finished_at": _now(),
        "serial": h.serial,
        "device": {k: h.capabilities.get(k) for k in ("manufacturer", "model", "sdk_int", "fingerprint")},
        "variables": {k: v for k, v in h.vars.items() if k not in DEFAULT_VARS or k in overrides},
        "spec_values": case.get("spec_values") or {},
        "spec_source": case.get("spec_source"),
        "operations": h.operations,
        "checks": h.checks,
        "derived": h.derived,
        "manual_steps": h.manual_steps,
        "host_steps": h.host_log,
        "evidence_files": evidence,
        "notes": h.notes,
        "runtime_version": RUNTIME_VERSION,
    }
    (out_dir / f"{case['ui_id']}_result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"ui_id": case["ui_id"], "verdict": verdict, "reason": reason,
                      "result_file": str(out_dir / f"{case['ui_id']}_result.json")}))
    return {"PASS": 0, "MANUAL_REVIEW": 0, "NOT_APPLICABLE": 0, "SKIPPED": 0}.get(verdict, 1)
