"""Connected Android devices, their health and installed test harness packages (via adb)."""

from __future__ import annotations

import re
import subprocess
from typing import Any

from services.test_execution.app_names import app_name

HARNESS_PACKAGES = {
    "com.example.cameratest": "Camera harness",
    "com.example.cameraunauthorized": "Camera harness (unauthorized helper)",
    "com.example.camerasecondary": "Camera harness (secondary helper)",
    "com.example.displaytest": "Display harness",
}
_PROPS = (
    "ro.product.manufacturer",
    "ro.product.model",
    "ro.build.version.release",
    "ro.build.version.sdk",
    "ro.kernel.qemu",
    "ro.boot.qemu",
    "ro.build.fingerprint",
)


class AdbUnavailable(RuntimeError):
    """adb is not installed or not on PATH."""


def _adb(serial: str | None, *args: str, timeout: float = 20) -> subprocess.CompletedProcess[str]:
    cmd = ["adb"] + (["-s", serial] if serial else []) + list(args)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
    except FileNotFoundError as exc:
        raise AdbUnavailable("adb not found on PATH") from exc
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"timeout after {timeout}s")


def _shell(serial: str, command: str, timeout: float = 20) -> str:
    return _adb(serial, "shell", command, timeout=timeout).stdout


def online_serials() -> list[str]:
    out = _adb(None, "devices").stdout
    return [l.split()[0] for l in out.splitlines()[1:] if l.strip().endswith("\tdevice")]


def list_devices() -> list[dict[str, Any]]:
    """Every device adb knows about; online ones include properties, health and harness packages."""
    out = _adb(None, "devices", "-l").stdout
    devices = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        entry: dict[str, Any] = {"serial": serial, "state": state}
        if state == "device":
            entry.update(device_info(serial))
        devices.append(entry)
    return devices


def device_info(serial: str) -> dict[str, Any]:
    values = _shell(serial, "; ".join(f"echo \"$(getprop {p})\"" for p in _PROPS)).splitlines()
    props = dict(zip(_PROPS, [v.strip() for v in values] + [""] * len(_PROPS)))
    is_emulator = "1" in (props["ro.kernel.qemu"], props["ro.boot.qemu"]) or serial.startswith("emulator-")
    sdk = props["ro.build.version.sdk"]
    return {
        "manufacturer": props["ro.product.manufacturer"],
        "model": props["ro.product.model"],
        "android_version": props["ro.build.version.release"],
        "sdk_int": int(sdk) if sdk.isdigit() else None,
        "fingerprint": props["ro.build.fingerprint"],
        "is_emulator": is_emulator,
        "health": health(serial),
        "packages": harness_packages(serial),
    }


def health(serial: str) -> dict[str, Any]:
    battery = _shell(serial, "dumpsys battery")
    thermal = _shell(serial, "dumpsys thermalservice")

    def num(regex: str, text: str) -> int | None:
        m = re.search(regex, text)
        return int(m.group(1)) if m else None

    temp = num(r"temperature:\s*(\d+)", battery)
    return {
        "battery_pct": num(r"level:\s*(\d+)", battery),
        "battery_temp_c": temp / 10 if temp is not None else None,
        "charging": bool(re.search(r"(AC|USB|Wireless) powered:\s*true", battery)),
        "thermal_status": num(r"Thermal Status:\s*(\d+)", thermal),
    }


def harness_packages(serial: str) -> dict[str, dict[str, Any]]:
    """Installed harness packages with their versionName."""
    listed = set(re.findall(r"package:(\S+)", _shell(serial, "pm list packages com.example.")))
    out: dict[str, dict[str, Any]] = {}
    for pkg, label in HARNESS_PACKAGES.items():
        version = None
        if pkg in listed:
            m = re.search(r"versionName=(\S+)", _shell(serial, f"dumpsys package {pkg} | grep versionName"))
            version = m.group(1) if m else None
        out[pkg] = {"label": label, "installed": pkg in listed, "version": version}
    return out


_PACKAGE_LINE = re.compile(r"^package:(?P<entry>\S+)(?:\s+versionCode:(?P<code>\d+))?(?:\s+installer=(?P<installer>\S+))?")

# Partition of the APK path -> who put the app on the phone.
_LOCATIONS = (
    ("/system/priv-app/", "System (privileged)"),
    ("/system/app/", "System"),
    ("/system_ext/", "System extension"),
    ("/product/", "Product (OEM / operator)"),
    ("/vendor/", "Vendor (OEM)"),
    ("/odm/", "ODM"),
    ("/apex/", "APEX module"),
    ("/data/", "User data"),
)


def _location(path: str) -> str:
    return next((label for prefix, label in _LOCATIONS if path.startswith(prefix)), "Other")


def parse_package_list(text: str) -> list[dict[str, Any]]:
    """Parse `pm list packages -f --show-versioncode -i` output."""
    apps = []
    for line in text.splitlines():
        m = _PACKAGE_LINE.match(line.strip())
        if not m:
            continue
        path, _, package = m.group("entry").rpartition("=")
        installer = m.group("installer")
        apps.append({
            "package": package,
            "path": path or None,
            "location": _location(path) if path else None,
            "version_code": int(m.group("code")) if m.group("code") else None,
            "installer": None if installer in (None, "null") else installer,
        })
    return apps


def parse_version_names(dumpsys: str) -> dict[str, str]:
    """versionName per package from `dumpsys package packages` (installed versions only)."""
    names: dict[str, str] = {}
    current = None
    for line in dumpsys.splitlines():
        if line.startswith("Hidden system packages:"):
            break
        m = re.match(r"\s*Package \[([^\]]+)\]", line)
        if m:
            current = m.group(1)
            continue
        m = re.match(r"\s*versionName=(.*)$", line)
        if m and current and current not in names:
            names[current] = m.group(1).strip()
    return names


LAUNCHER_QUERY = (
    "cmd package query-activities --brief "
    "-a android.intent.action.MAIN -c android.intent.category.LAUNCHER"
)
_COMPONENT = re.compile(r"^\s*([A-Za-z][\w.]*)/([\w.$]+)\s*$")


def parse_launcher_activities(text: str) -> dict[str, str]:
    """First launcher activity per package from `cmd package query-activities --brief` output."""
    activities: dict[str, str] = {}
    for line in text.splitlines():
        m = _COMPONENT.match(line)
        if not m:
            continue
        package, activity = m.groups()
        if activity.startswith("."):
            activity = package + activity
        activities.setdefault(package, activity)
    return activities


def installed_packages(serial: str) -> dict[str, Any]:
    """Every app on the device, split like `pm list packages -s` (system) and `-3` (third-party).

    Each app also carries a display name and whether it has a launcher (app drawer) icon.
    """
    flags = "-f --show-versioncode -i"
    system = parse_package_list(_shell(serial, f"pm list packages -s {flags}", timeout=60))
    third_party = parse_package_list(_shell(serial, f"pm list packages -3 {flags}", timeout=60))
    if not system and not third_party:
        # Older Android releases reject --show-versioncode / -i; fall back to the plain listing.
        system = parse_package_list(_shell(serial, "pm list packages -s -f", timeout=60))
        third_party = parse_package_list(_shell(serial, "pm list packages -3 -f", timeout=60))
    disabled = set(re.findall(r"package:(\S+)", _shell(serial, "pm list packages -d", timeout=60)))
    versions = parse_version_names(_shell(serial, "dumpsys package packages", timeout=90))
    launchers = parse_launcher_activities(_shell(serial, LAUNCHER_QUERY, timeout=60))
    for kind, apps in (("system", system), ("third_party", third_party)):
        for app in apps:
            app["type"] = kind
            app["name"], app["name_source"] = app_name(app["package"])
            app["enabled"] = app["package"] not in disabled
            app["version_name"] = versions.get(app["package"])
            app["updated"] = kind == "system" and bool(app["path"]) and app["path"].startswith("/data/")
            app["launch_activity"] = launchers.get(app["package"])
            app["launcher"] = app["launch_activity"] is not None
        apps.sort(key=lambda a: a["package"])
    return {
        "serial": serial,
        "system": system,
        "third_party": third_party,
        "counts": {
            "system": len(system),
            "third_party": len(third_party),
            "disabled": len(disabled),
            "system_launcher": sum(a["launcher"] for a in system),
            "third_party_launcher": sum(a["launcher"] for a in third_party),
        },
    }


def screenshot(serial: str) -> bytes:
    try:
        proc = subprocess.run(["adb", "-s", serial, "exec-out", "screencap", "-p"],
                              capture_output=True, timeout=20)
    except FileNotFoundError as exc:
        raise AdbUnavailable("adb not found on PATH") from exc
    if proc.returncode != 0 or not proc.stdout.startswith(b"\x89PNG"):
        raise RuntimeError(f"screencap failed on {serial}: {proc.stderr.decode(errors='replace')[:200]}")
    return proc.stdout
