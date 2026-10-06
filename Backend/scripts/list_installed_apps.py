"""List the installed apps on a connected emulator (or phone) over adb and save them as JSON.

Uses the same adb scan as the Installed Apps tab (services/test_execution/devices.py): per app
its display name, whether it has a launcher icon and which activity opens it.

Run from Backend/:
    python scripts/list_installed_apps.py                     # first running emulator
    python scripts/list_installed_apps.py --serial emulator-5554
    python scripts/list_installed_apps.py --all               # print every package, not only launcher apps
    python scripts/list_installed_apps.py --out apps.json     # custom output file

Output: Backend/data/installed_apps/<serial>_<timestamp>.json unless --out is given.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from services.test_execution import devices  # noqa: E402

OUTPUT_DIR = BACKEND_ROOT / "data" / "installed_apps"


def pick_serial(requested: str | None) -> str:
    online = devices.online_serials()
    if requested:
        if requested not in online:
            sys.exit(f"Device {requested} is not connected. Online devices: {', '.join(online) or 'none'}")
        return requested
    emulators = [s for s in online if s.startswith("emulator-")]
    if emulators:
        return emulators[0]
    if online:
        sys.exit(f"No emulator running. Online devices: {', '.join(online)} (pass one with --serial)")
    sys.exit("No device connected. Start the emulator (e.g. `emulator @CameraHarness34`) and check `adb devices`.")


def collect(serial: str) -> dict[str, Any]:
    if devices._shell(serial, "getprop sys.boot_completed").strip() != "1":
        sys.exit(f"{serial} is still booting. Wait for the home screen and run again.")

    scan = devices.installed_packages(serial)
    info = devices.device_info(serial)
    scan["counts"]["launcher"] = scan["counts"]["system_launcher"] + scan["counts"]["third_party_launcher"]
    return {
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "device": {k: info.get(k) for k in ("manufacturer", "model", "android_version", "sdk_int",
                                            "fingerprint", "is_emulator")},
        **scan,
    }


def print_table(apps: list[dict[str, Any]], title: str) -> None:
    print(f"\n{title} ({len(apps)})")
    if not apps:
        return
    name_w = max(len(a["name"]) for a in apps)
    pkg_w = max(len(a["package"]) for a in apps)
    print(f"  {'NAME':<{name_w}}  {'PACKAGE':<{pkg_w}}  {'VERSION':<16}  {'LOCATION':<24}  STATUS")
    for a in apps:
        status = "enabled" if a["enabled"] else "disabled"
        if a.get("updated"):
            status += ", updated"
        version = a.get("version_name") or (str(a["version_code"]) if a.get("version_code") is not None else "-")
        print(f"  {a['name']:<{name_w}}  {a['package']:<{pkg_w}}  {version[:16]:<16}  "
              f"{(a.get('location') or '-')[:24]:<24}  {status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="List installed apps on the emulator over adb.")
    parser.add_argument("--serial", help="adb serial (default: first running emulator)")
    parser.add_argument("--out", type=Path, help="output JSON file")
    parser.add_argument("--all", action="store_true", help="print every package, not only apps with a launcher icon")
    args = parser.parse_args()

    try:
        serial = pick_serial(args.serial)
        result = collect(serial)
    except devices.AdbUnavailable as exc:
        sys.exit(f"{exc}. Add Android SDK platform-tools to PATH.")

    device = result["device"]
    counts = result["counts"]
    print(f"Device: {device['manufacturer']} {device['model']} · Android {device['android_version']} ({serial})")
    print(f"System apps: {counts['system']}  Third-party apps: {counts['third_party']}  "
          f"Disabled: {counts['disabled']}  With launcher icon: {counts['launcher']}")

    system = result["system"] if args.all else [a for a in result["system"] if a["launcher"]]
    print_table(system, "System (preinstalled) apps" if args.all else "System (preinstalled) apps with a launcher icon")
    print_table(result["third_party"], "Third-party apps")

    out = args.out or OUTPUT_DIR / f"{serial}_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nSaved {counts['system'] + counts['third_party']} apps to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
