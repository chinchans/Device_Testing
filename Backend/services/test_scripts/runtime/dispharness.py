"""Display test-script runtime shared by every generated display test script.

Generated scripts contain a CASE dict and a run(h) function; everything else
(device checks, harness/helper/lab gating, capability discovery, settings
snapshot + restore, placeholder resolution, metrics, SLA evaluation, evidence,
verdict) lives here so every script behaves the same way.

Usage (from a generated script):  python3 test_dsp_fun_001.py [--serial X] [--out DIR]
                                  [--var NAME=VALUE ...] [--no-setup]
"""

from __future__ import annotations

import argparse
import json
import math
import operator
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

RUNTIME_VERSION = "1.1.0"
HARNESS_PKG = "com.example.displaytest"
JSON_PREFIX = "INSTRUMENTATION_STATUS: harness_json="

_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "==": operator.eq,
    "!=": operator.ne,
    "<=": operator.le,
    "<": operator.lt,
    ">=": operator.ge,
    ">": operator.gt,
}
_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)\}")
_WATCHED_PROCS = ("surfaceflinger", "com.android.systemui")


class Blocked(Exception):
    """Precondition not met (harness, helper APK, lab input, device state): BLOCKED_PRECONDITION."""


class NotApplicable(Exception):
    """Capability absent on this device or value unknown: NOT_APPLICABLE."""


class Vars(dict):
    """Resolved variables; reading an unknown one ends the case as NOT_APPLICABLE."""

    def __missing__(self, name: str) -> str:
        raise NotApplicable(f"variable {name} is not known (not in the product spec or on this device); "
                            f"pass --var {name}=VALUE")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", file=sys.stderr, flush=True)


def _num(v: Any) -> Any:
    if isinstance(v, bool) or v is None or isinstance(v, (int, float)):
        return v
    try:
        f = float(str(v).strip())
        return int(f) if f.is_integer() else f
    except ValueError:
        return v


_EXPECTED_IN_TEXT = re.compile(r"\b(?:matches|equals|is at least|is at most|within)\s+(.+?)\.?$", re.IGNORECASE)


def _expected_from(description: str) -> str | None:
    """'Refresh rate matches 120 Hz' -> '120 Hz'."""
    m = _EXPECTED_IN_TEXT.search(str(description))
    return m.group(1).strip() if m else None


class Harness:
    """Device session for one display test case."""

    def __init__(self, case: dict[str, Any], *, serial: str | None, out_dir: Path,
                 overrides: dict[str, str]) -> None:
        self.case = case
        self.serial = serial
        self.out_dir = out_dir
        self.overrides = overrides
        self.vars: Vars = Vars()
        self.metrics: dict[str, Any] = {}
        self.checks: list[dict[str, Any]] = []
        self.manual_steps: list[str] = []
        self.host_log: list[dict[str, Any]] = []
        self.instrumentations: list[dict[str, Any]] = []
        self.notes: list[str] = []
        self.last_rc = 0

    # ------------------------------------------------------------------ shell

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.serial:
            env["ANDROID_SERIAL"] = self.serial
        return env

    def _run(self, command: str, timeout: float) -> subprocess.CompletedProcess[str]:
        if not command.startswith("adb "):
            raise ValueError(f"host command must start with 'adb ': {command[:80]}")
        try:
            raw = subprocess.run(command, shell=True, capture_output=True,
                                 timeout=timeout, cwd=self.out_dir, env=self._env())
            proc = subprocess.CompletedProcess(command, raw.returncode,
                                               raw.stdout.decode(errors="replace"),
                                               raw.stderr.decode(errors="replace"))
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            proc = subprocess.CompletedProcess(command, 124, out, f"timeout after {timeout}s")
        self.last_rc = proc.returncode
        self.host_log.append({"command": command, "rc": proc.returncode})
        return proc

    def sh(self, command: str, *, timeout: float = 120, check: bool = False) -> str:
        """Run an 'adb ...' host command (placeholders resolved) and return stdout."""
        command = self.resolve(command).strip()
        _log(f"sh: {command[:200]}")
        proc = self._run(command, timeout)
        if check and proc.returncode != 0:
            raise Blocked(f"command failed ({proc.returncode}): {command[:120]}: {proc.stderr.strip()[:200]}")
        prop = re.fullmatch(r"adb shell getprop ro\.([\w.]+)", command)
        if prop and not proc.stdout.strip() and self.vars.get("IS_EMULATOR") == "true":
            alias = self.adb_shell(f"getprop qemu.{prop.group(1)}")
            if alias.strip():
                self.notes.append(f"emulator: ro.{prop.group(1)} unset, used qemu.{prop.group(1)}={alias.strip()}")
                return alias
        return proc.stdout

    def _mark_start(self) -> None:
        self.adb_shell("input keyevent KEYCODE_WAKEUP")
        self.adb_shell("wm dismiss-keyguard")
        for _ in range(20):
            if "mWakefulness=Awake" in self.adb_shell("dumpsys power"):
                break
            time.sleep(0.25)
        else:
            raise Blocked("device did not wake up (mWakefulness != Awake)")
        time.sleep(1.0)
        self._start_stamp = self.adb_shell("date '+%Y-%m-%d %H:%M:%S'").strip()
        self.adb_shell("logcat -b crash -c")
        self._pids = {p: self.adb_shell(f"pidof {p}").strip() for p in _WATCHED_PROCS}
        self._restarts = {p: 0 for p in _WATCHED_PROCS}

    def crash_counts(self) -> dict[str, int]:
        """Crashes/ANRs/tombstones logged since the case started, plus SurfaceFlinger/SystemUI restarts."""
        out = self.sh("adb shell dumpsys dropbox")
        since = getattr(self, "_start_stamp", "")
        tags: dict[str, int] = {}
        for m in re.finditer(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (\w+) \(", out, re.M):
            if m.group(1) >= since:
                tags[m.group(2)] = tags.get(m.group(2), 0) + 1
        for proc in _WATCHED_PROCS:
            pid = self.adb_shell(f"pidof {proc}").strip()
            if self._pids.get(proc) and pid != self._pids[proc]:
                self._restarts[proc] += 1
            self._pids[proc] = pid
        systemui_crashes = self.adb_shell("logcat -b crash -d").count("Process: com.android.systemui")
        return {
            "app_crash": sum(n for t, n in tags.items() if t.endswith("app_crash")),
            "native_crash": sum(n for t, n in tags.items() if t.endswith("native_crash")),
            "anr": sum(n for t, n in tags.items() if t.endswith("_anr")),
            "tombstone": tags.get("SYSTEM_TOMBSTONE", 0),
            "systemui_crash": systemui_crashes + self._restarts["com.android.systemui"],
            "systemui_restarts": self._restarts["com.android.systemui"],
            "surfaceflinger_restarts": self._restarts["surfaceflinger"],
        }

    def sf_modes(self) -> list[dict[str, Any]]:
        """Display modes as listed by SurfaceFlinger (ids are SurfaceFlinger's own, not DisplayManager's)."""
        out = self.sh("adb shell dumpsys SurfaceFlinger")
        return [{"id": int(i), "width": int(w), "height": int(hh), "fps": round(float(f), 2)}
                for i, w, hh, f in re.findall(
                    r"\{id=(\d+),[^}]*?resolution=(\d+)x(\d+), refreshRate=([0-9.]+) Hz", out)]

    def screen_luma(self, *, step: int = 16, settle_s: float = 2.0) -> float:
        """Mean luma (0-255, BT.601) of the screen after `settle_s` (animations, theme recreation)."""
        time.sleep(max(0.0, settle_s))
        _log("sh: adb exec-out screencap (raw)")
        proc = subprocess.run("adb exec-out screencap", shell=True, capture_output=True,
                              timeout=60, env=self._env())
        data = proc.stdout
        if proc.returncode != 0 or len(data) < 16:
            raise Blocked(f"screencap failed ({proc.returncode})")
        w, h, fmt = (int.from_bytes(data[i:i + 4], "little") for i in (0, 4, 8))
        header = len(data) - w * h * 4
        if fmt not in (1, 2) or header not in (12, 16):
            raise Blocked(f"unsupported screencap format {fmt} ({w}x{h}, header {header})")
        px = memoryview(data)[header:]
        total, n = 0.0, 0
        for i in range(0, w * h * 4, 4 * max(1, step)):
            total += 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2]
            n += 1
        return total / n

    def display_info(self) -> dict[str, Any]:
        """Parsed DisplayDeviceInfo of the built-in display from `dumpsys display`."""
        out = self.sh("adb shell dumpsys display")
        lines = [l for l in out.splitlines() if "DisplayDeviceInfo{" in l]
        line = next((l for l in lines if "type INTERNAL" in l), lines[0] if lines else "")
        if not line:
            raise Blocked("dumpsys display reported no DisplayDeviceInfo")

        def num(regex: str) -> float | None:
            m = re.search(regex, line)
            return float(m.group(1)) if m else None

        size = re.search(r"DisplayDeviceInfo\{\"[^\"]*\":[^,]*,\s*(\d+) x (\d+)", line)
        dpi = re.search(r"([0-9.]+) x ([0-9.]+) dpi", line)
        name = re.search(r"DisplayDeviceInfo\{\"([^\"]*)\"", line)
        hdr = re.search(r"mSupportedHdrTypes=\[([^\]]*)\]", line)
        cutout = re.search(r"cutout DisplayCutout\{insets=Rect\((\d+), (\d+) - (\d+), (\d+)\)", line)
        return {
            "name": name.group(1) if name else None,
            "type": "INTERNAL" if "type INTERNAL" in line else None,
            "width": int(size.group(1)) if size else None,
            "height": int(size.group(2)) if size else None,
            "density": num(r"density (\d+),"),
            "xdpi": float(dpi.group(1)) if dpi else None,
            "ydpi": float(dpi.group(2)) if dpi else None,
            "refresh_hz": num(r"renderFrameRate ([0-9.]+)"),
            "supported_refresh_hz": sorted({round(float(x), 2) for x in re.findall(r"fps=([0-9.]+)", line)}),
            "modes": [{"id": int(i), "width": int(w), "height": int(hh), "fps": round(float(f), 2)}
                      for i, w, hh, f in re.findall(
                          r"\{id=(\d+), width=(\d+), height=(\d+), fps=([0-9.]+)", line)],
            "active_mode_id": int(num(r"modeId (\d+)") or 0) or None,
            "default_mode_id": int(num(r"defaultModeId (\d+)") or 0) or None,
            "hdr_types": [int(x) for x in re.findall(r"\d+", hdr.group(1))] if hdr else [],
            "max_luminance": num(r"mMaxLuminance=([0-9.]+)"),
            "has_cutout": bool(cutout and any(int(g) for g in cutout.groups())),
            "state": (re.search(r"\bstate (\w+)", line) or [None, None])[1],
        }

    def adb_shell(self, command: str, *, timeout: float = 120) -> str:
        """Run a device shell command without placeholder resolution (internal use)."""
        return self._run(f"adb shell {command}", timeout).stdout

    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, float(seconds)))

    def now_ms(self) -> float:
        return time.monotonic() * 1000.0

    # --------------------------------------------------------------- parsing

    def extract(self, text: str, regex: str, *, group: int | None = 1,
                cast: Callable[[str], Any] | None = float, default: Any = None) -> Any:
        """First regex match in text (cast with `cast`), else default; group=None returns all groups."""
        m = re.search(regex, text or "", re.M)
        if not m:
            return default
        try:
            if group is None:
                return tuple(cast(g) if cast and g is not None else g for g in m.groups())
            raw = m.group(group) if m.groups() else m.group(0)
            return cast(raw) if cast else raw
        except (TypeError, ValueError, IndexError):
            return default

    def extract_all(self, text: str, regex: str, *, cast: Callable[[str], Any] | None = float) -> list[Any]:
        out = []
        for m in re.finditer(regex, text or "", re.M):
            raw = m.group(1) if m.groups() else m.group(0)
            try:
                out.append(cast(raw) if cast else raw)
            except (TypeError, ValueError):
                continue
        return out

    def poll(self, command: str, regex: str, *, interval_ms: float = 100, timeout_s: float = 10,
             until: Callable[[Any], bool] | None = None, cast: Callable[[str], Any] | None = float
             ) -> list[tuple[float, Any]]:
        """Sample command every interval_ms; returns [(t_ms, value)], stops early when until(value)."""
        samples: list[tuple[float, Any]] = []
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            t = self.now_ms()
            value = self.extract(self._run(self.resolve(command), 30).stdout, regex, cast=cast)
            samples.append((t, value))
            if until is not None and value is not None and until(value):
                break
            time.sleep(interval_ms / 1000.0)
        return samples

    def percentile(self, values: list[float], p: float) -> float | None:
        vals = sorted(float(v) for v in values if v is not None)
        if not vals:
            return None
        k = (len(vals) - 1) * p / 100.0
        lo, hi = math.floor(k), math.ceil(k)
        return vals[lo] if lo == hi else vals[lo] + (vals[hi] - vals[lo]) * (k - lo)

    def mean(self, values: list[float]) -> float | None:
        vals = [float(v) for v in values if v is not None]
        return sum(vals) / len(vals) if vals else None

    # ------------------------------------------------------------- variables

    def resolve(self, value: Any) -> str:
        """Substitute ${VAR}; an unknown variable means the case cannot run here (NOT_APPLICABLE)."""
        def sub(m: re.Match[str]) -> str:
            name = m.group(1)
            if name in self.vars:
                return str(self.vars[name])
            raise NotApplicable(f"${{{name}}} is not known (not in the product spec or on this device); "
                                f"pass --var {name}=VALUE")
        return _PLACEHOLDER.sub(sub, str(value))

    def resolve_soft(self, value: Any) -> str:
        return _PLACEHOLDER.sub(lambda m: str(self.vars.get(m.group(1), m.group(0))), str(value))

    def lab_value(self, name: str, description: str = "") -> float:
        """A value measured with lab equipment, supplied as --var NAME=VALUE."""
        if name not in self.vars:
            raise Blocked(f"lab measurement {name} required ({description or 'external instrument'}); "
                          f"pass --var {name}=VALUE")
        val = _num(self.vars[name])
        if not isinstance(val, (int, float)):
            raise Blocked(f"lab measurement {name}={self.vars[name]!r} is not numeric")
        return float(val)

    def discover(self) -> None:
        sdk = self.adb_shell("getprop ro.build.version.sdk").strip()
        self.vars = Vars({k: str(v) for k, v in (self.case.get("constants") or {}).items()})
        if sdk.isdigit():
            self.vars["ANDROID_SDK_INT"] = sdk
            for level in (30, 31, 33, 34):
                self.vars[f"SDK_GE_{level}"] = "true" if int(sdk) >= level else "false"
        self.vars["DISPLAY_HARNESS_INSTALLED"] = "true" if self.installed(HARNESS_PKG) else "false"
        qemu = self.adb_shell("getprop ro.kernel.qemu").strip() or self.adb_shell("getprop ro.boot.qemu").strip()
        self.vars["IS_EMULATOR"] = "true" if qemu == "1" else "false"
        for cap in self.case.get("capability_discovery") or []:
            name = cap.get("variable", "").strip("${}")
            if not name or name in self.vars:
                continue
            try:
                out = self._run(self.resolve_soft(cap["command"]), 60).stdout
            except Exception as exc:
                self.notes.append(f"discovery {name} failed: {exc}")
                continue
            if "REFRESH_RATES" in name:
                rates = sorted({round(float(x)) for x in re.findall(r"fps=([0-9.]+)", out)})
                if rates:
                    self.vars[name] = ",".join(str(r) for r in rates)
                continue
            m = re.search(cap.get("extraction_regex") or "(.+)", out, re.M | re.S)
            if m:
                self.vars[name] = (m.group(1) if m.groups() else m.group(0)).strip()
        self.vars.update(self.case.get("spec_values") or {})
        self.vars.update(self.overrides)
        for name, value in (self.case.get("parameters") or {}).items():
            if isinstance(value, (list, dict)):
                typed = json.loads(self.resolve_soft(json.dumps(value)))
                if not _PLACEHOLDER.search(json.dumps(typed)):
                    self.vars.setdefault(name, typed)
                continue
            text = self.resolve_soft(value)
            if not _PLACEHOLDER.search(text):
                self.vars.setdefault(name, text)

    # ------------------------------------------------------------- preflight

    def installed(self, pkg: str) -> bool:
        return f"package:{pkg}" in self.adb_shell(f"pm list packages {pkg}").split()

    def preflight(self) -> None:
        devices = subprocess.run(["adb", "devices"], capture_output=True, text=True).stdout
        online = [l.split()[0] for l in devices.splitlines()[1:] if l.strip().endswith("device")]
        if not online:
            raise Blocked("no adb device online")
        if self.serial and self.serial not in online:
            raise Blocked(f"device {self.serial} not online")
        if not self.serial and len(online) > 1:
            raise Blocked(f"multiple devices online {online}; pass --serial")
        self.serial = self.serial or online[0]

        harness = self.case.get("harness") or {}
        if harness.get("required"):
            for pkg in [harness.get("package")] + list(harness.get("helper_apks") or []):
                if pkg and not self.installed(pkg):
                    raise Blocked(f"{pkg} is not installed - {harness.get('reason') or 'required by this case'} "
                                  f"(status: {harness.get('status') or 'unknown'})")
        pre = self.case.get("prerequisites") or {}
        battery = self.adb_shell("dumpsys battery")
        level = re.search(r"level:\s*(\d+)", battery)
        temp = re.search(r"temperature:\s*(\d+)", battery)
        min_pct = (pre.get("battery_state") or {}).get("min_charge_pct")
        if min_pct is not None and level and int(level.group(1)) < int(min_pct):
            raise Blocked(f"battery {level.group(1)}% < {min_pct}%")
        max_c = (pre.get("thermal_limits") or {}).get("battery_temp_max_c")
        if max_c is not None and temp and int(temp.group(1)) / 10 > float(max_c):
            raise Blocked(f"battery temperature {int(temp.group(1)) / 10}C > {max_c}C")

    def setup(self) -> None:
        for step in self.case.get("setup_commands") or []:
            cmd = self.resolve_soft(step["command"])
            proc = self._run(cmd, 120)
            if "BASELINE" in (step.get("description") or ""):
                self._store_baseline(proc.stdout)
            if proc.returncode != 0 and not step.get("ignore_failure", True):
                raise Blocked(f"setup failed ({proc.returncode}): {cmd[:120]}: {proc.stderr.strip()[:200]}")

    def _store_baseline(self, out: str) -> None:
        for m in re.finditer(r"^(system|secure|global)\.(\w+)=(.*)$", out, re.M):
            self.vars[f"BASELINE_{m.group(2).upper()}"] = m.group(3).strip() or "null"
        night = re.search(r"Night mode:\s*(\w+)", out)
        if night:
            self.vars["BASELINE_UI_NIGHT_MODE"] = night.group(1)
        for label, key in (("Physical size", "WM_SIZE"), ("Override size", "WM_SIZE_OVERRIDE"),
                           ("Physical density", "WM_DENSITY"), ("Override density", "WM_DENSITY_OVERRIDE")):
            m = re.search(rf"{label}:\s*(\S+)", out)
            if m:
                self.vars[f"BASELINE_{key}"] = m.group(1)

    # ------------------------------------------------------------ operations

    def instrument(self, cls: str, args: dict[str, Any] | None = None, *, timeout: float = 900) -> dict[str, Any]:
        """Run one display-harness (or helper APK) operation; returns its harness_json dict."""
        if not cls.startswith(HARNESS_PKG + "."):
            raise ValueError(f"unknown harness class {cls}")
        pkg = ".".join(seg for seg in cls.split(".") if seg[:1].islower())
        if not self.installed(pkg):
            raise Blocked(f"{pkg} is not installed (needed for {cls.rsplit('.', 1)[-1]})")
        extras = " ".join(f"-e {k} {json.dumps(self.resolve(v))}" for k, v in (args or {}).items())
        runner = f"{pkg}/androidx.test.runner.AndroidJUnitRunner"
        cmd = f"adb shell am instrument -w -r {extras} -e class {cls} {runner}".replace("  ", " ")
        started = time.time()
        out = self._run(cmd, timeout).stdout
        res: dict[str, Any] = {"result": "HARNESS_ERROR", "error": "no harness_json in output", "raw": out[-1500:]}
        for line in reversed(out.splitlines()):
            if line.strip().startswith(JSON_PREFIX):
                try:
                    res = json.loads(line.strip()[len(JSON_PREFIX):])
                except json.JSONDecodeError:
                    pass
                break
        self.instrumentations.append({"class": cls, "args": args or {}, "duration_s": round(time.time() - started, 2),
                                      "result": res})
        _log(f"instrument {cls.rsplit('.', 1)[-1]}: {res.get('result')} {res.get('error') or ''}".rstrip())
        if res.get("result") == "NOT_APPLICABLE":
            raise NotApplicable(str(res.get("reason") or res.get("error") or cls))
        if res.get("result") == "BLOCKED_PRECONDITION":
            raise Blocked(str(res.get("error") or res.get("reason") or cls))
        return res

    def require_helper(self, pkg: str) -> None:
        if not self.installed(pkg):
            raise Blocked(f"helper APK {pkg} is not installed")

    # --------------------------------------------------------------- checks

    def metric(self, key: str, value: Any) -> Any:
        """Record a measured metric used by check_slas()."""
        self.metrics[key] = int(value) if isinstance(value, bool) else _num(value)
        _log(f"metric {key} = {self.metrics[key]}")
        return value

    def expect(self, condition: bool, description: str, actual: Any = None, *, expected: Any = None) -> bool:
        ok = bool(condition)
        description = self.resolve_soft(description)
        if expected is None:
            expected = _expected_from(description)
        self.checks.append({"type": "expect", "description": description, "passed": ok,
                            "expected": expected if expected is not None else "condition holds",
                            "actual": actual})
        return ok

    def check_slas(self, *, missing: str = "fail") -> bool:
        """Evaluate every CASE['slas'] entry against recorded metrics.

        missing="fail" fails unmeasured metrics; missing="manual" turns them into manual checkpoints.
        """
        all_ok = True
        for sla in self.case.get("slas") or []:
            key = sla["metric_key"]
            target = _num(self.resolve_soft(sla["target_value"]))
            actual = self.metrics.get(key)
            if actual is None and missing == "manual":
                self.manual(f"measure {key} {sla['operator']} {target} {sla.get('unit') or ''}".strip())
                continue
            fn = _OPS.get(sla["operator"])
            ok = (fn is not None and isinstance(actual, (int, float)) and isinstance(target, (int, float))
                  and fn(actual, target))
            entry = {"type": "sla", "description": f"{key} {sla['operator']} {target} {sla.get('unit') or ''}".strip(),
                     "metric_key": key, "expected": f"{sla['operator']} {target} {sla.get('unit') or ''}".strip(),
                     "actual": actual if actual is not None else "not measured",
                     "target": target, "operator": sla["operator"], "passed": bool(ok)}
            if not ok and sla.get("failure_classification"):
                entry["failure_classification"] = sla["failure_classification"]
            self.checks.append(entry)
            _log(f"sla: {key} = {entry['actual']} (target {sla['operator']} {target}) {'ok' if ok else 'FAIL'}")
            all_ok = all_ok and bool(ok)
        return all_ok

    def manual(self, message: str, *, wait: bool = False) -> None:
        text = self.resolve_soft(message)
        self.manual_steps.append(text)
        _log(f"MANUAL: {text}")
        if wait and sys.stdin.isatty():
            input("Press Enter when done... ")

    def not_applicable(self, reason: str) -> None:
        raise NotApplicable(reason)

    def blocked(self, reason: str) -> None:
        raise Blocked(reason)

    # -------------------------------------------------------------- evidence

    def collect_evidence(self) -> list[str]:
        files: list[str] = []
        ev = self.case.get("evidence") or {}
        cmds = [c for c in [ev.get("logcat")] + list(ev.get("dumps") or []) if c]
        if not cmds:
            cmds = [f"adb logcat -d -v threadtime > {self.case['ui_id']}_logcat.txt"]
        for c in cmds:
            try:
                self._run(self.resolve_soft(c), 180)
                m = re.search(r">\s*(\S+)\s*$", c)
                if m:
                    files.append(str(self.out_dir / m.group(1)))
            except Exception as exc:  # evidence must never mask the verdict
                self.notes.append(f"evidence '{c}' failed: {exc}")
        return files

    def teardown(self) -> None:
        for step in self.case.get("teardown_commands") or []:
            cmd = self.resolve_soft(step["command"])
            cmd = re.sub(r"settings put (system|secure|global) (\S+) null\b", r"settings delete \1 \2", cmd)
            if _PLACEHOLDER.search(cmd):
                self.notes.append(f"teardown skipped (value unknown): {cmd}")
                continue
            try:
                self._run(cmd, 120)
            except Exception as exc:
                self.notes.append(f"teardown '{cmd}' failed: {exc}")

    # --------------------------------------------------------------- verdict

    def verdict(self) -> tuple[str, str]:
        failed = [c for c in self.checks if not c["passed"]]
        if failed:
            return "FAIL", "; ".join(f"{c['description']} (actual {c.get('actual')})" for c in failed)[:1000]
        if self.manual_steps:
            return "MANUAL_REVIEW", f"{len(self.manual_steps)} manual checkpoint(s)"
        if not self.checks:
            return "ERROR", "run() recorded no checks"
        return "PASS", ""


def _parse_args(case: dict[str, Any]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=f"{case['ui_id']} - {case['name']}")
    p.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL"))
    p.add_argument("--out", default=None, help="evidence/result directory")
    p.add_argument("--var", action="append", default=[], metavar="NAME=VALUE")
    p.add_argument("--no-setup", action="store_true", help="skip CASE setup_commands")
    return p.parse_args()


def main(case: dict[str, Any], run: Callable[[Harness], None]) -> int:
    """Entry point used by every generated display script."""
    args = _parse_args(case)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out or f"results/{case['ui_id']}_{stamp}").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    overrides = dict(v.split("=", 1) for v in args.var if "=" in v)
    h = Harness(case, serial=args.serial, out_dir=out_dir, overrides=overrides)
    started = _now()
    verdict, reason = "ERROR", ""
    evidence: list[str] = []
    ran_setup = False
    try:
        h.preflight()
        h.discover()
        if not args.no_setup:
            ran_setup = True
            h.setup()
        h._mark_start()
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
            if ran_setup:
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
        "variables": h.vars,
        "spec_values": case.get("spec_values") or {},
        "spec_source": case.get("spec_source"),
        "metrics": h.metrics,
        "checks": h.checks,
        "instrumentations": h.instrumentations,
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
