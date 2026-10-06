"""Parsing of `pm list packages` / `dumpsys package` output for the Installed Apps scan."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.test_execution import devices  # noqa: E402

PM_SYSTEM = """\
package:/system/priv-app/Settings/Settings.apk=com.android.settings versionCode:34  installer=null
package:/product/app/Chrome/Chrome.apk=com.android.chrome versionCode:612000  installer=com.android.vending
package:/data/app/~~aGVsbG8==/com.google.android.youtube-d29ybGQ==/base.apk=com.google.android.youtube versionCode:1540  installer=com.android.vending
package:/vendor/app/OemCamera/OemCamera.apk=com.oem.camera versionCode:7  installer=null
"""

DUMPSYS = """\
Packages:
  Package [com.android.settings] (1a2b):
    versionCode=34 minSdk=34 targetSdk=34
    versionName=14
  Package [com.google.android.youtube] (3c4d):
    versionCode=1540 minSdk=26 targetSdk=34
    versionName=19.10.36
Hidden system packages:
  Package [com.google.android.youtube] (5e6f):
    versionName=17.0.0
"""


def test_parse_package_list_reads_path_version_and_installer():
    apps = {a["package"]: a for a in devices.parse_package_list(PM_SYSTEM)}
    assert set(apps) == {"com.android.settings", "com.android.chrome", "com.google.android.youtube", "com.oem.camera"}
    assert apps["com.android.settings"]["location"] == "System (privileged)"
    assert apps["com.android.settings"]["installer"] is None
    assert apps["com.android.chrome"]["location"] == "Product (OEM / operator)"
    assert apps["com.android.chrome"]["installer"] == "com.android.vending"
    youtube = apps["com.google.android.youtube"]
    assert youtube["path"].endswith("/base.apk") and "==" in youtube["path"]
    assert youtube["location"] == "User data"
    assert youtube["version_code"] == 1540
    assert apps["com.oem.camera"]["location"] == "Vendor (OEM)"


def test_parse_package_list_plain_format():
    apps = devices.parse_package_list("package:com.example.app\npackage:com.other\nError: junk\n")
    assert [a["package"] for a in apps] == ["com.example.app", "com.other"]
    assert apps[0]["path"] is None and apps[0]["version_code"] is None


def test_parse_version_names_ignores_hidden_system_copies():
    assert devices.parse_version_names(DUMPSYS) == {
        "com.android.settings": "14",
        "com.google.android.youtube": "19.10.36",
    }


def test_installed_packages_splits_system_and_third_party(monkeypatch):
    outputs = {
        "pm list packages -s -f --show-versioncode -i": PM_SYSTEM,
        "pm list packages -3 -f --show-versioncode -i":
            "package:/data/app/~~x==/com.whatsapp-y==/base.apk=com.whatsapp versionCode:9  installer=com.android.vending\n",
        "pm list packages -d": "package:com.oem.camera\n",
        "dumpsys package packages": DUMPSYS,
    }
    monkeypatch.setattr(devices, "_shell", lambda serial, cmd, timeout=20: outputs.get(cmd, ""))
    out = devices.installed_packages("emulator-5554")
    assert out["counts"] == {"system": 4, "third_party": 1, "disabled": 1,
                             "system_launcher": 0, "third_party_launcher": 0}
    system = {a["package"]: a for a in out["system"]}
    assert system["com.google.android.youtube"]["updated"] is True
    assert system["com.google.android.youtube"]["version_name"] == "19.10.36"
    assert system["com.android.settings"]["updated"] is False
    assert system["com.oem.camera"]["enabled"] is False
    assert out["third_party"][0]["package"] == "com.whatsapp"
    assert out["third_party"][0]["type"] == "third_party"


LAUNCHER = """\
priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=false
com.android.settings/.Settings
priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=false
com.android.chrome/com.google.android.apps.chrome.Main
com.android.settings/.Other
"""


def test_parse_launcher_activities_expands_relative_names_and_keeps_first():
    assert devices.parse_launcher_activities(LAUNCHER) == {
        "com.android.settings": "com.android.settings.Settings",
        "com.android.chrome": "com.google.android.apps.chrome.Main",
    }


def test_installed_packages_adds_names_and_launcher_flags(monkeypatch):
    outputs = {
        "pm list packages -s -f --show-versioncode -i": PM_SYSTEM,
        "pm list packages -3 -f --show-versioncode -i":
            "package:/data/app/~~x==/com.acme.trip_planner-y==/base.apk=com.acme.trip_planner versionCode:9  installer=null\n",
        devices.LAUNCHER_QUERY: LAUNCHER,
    }
    monkeypatch.setattr(devices, "_shell", lambda serial, cmd, timeout=20: outputs.get(cmd, ""))
    out = devices.installed_packages("emulator-5554")
    system = {a["package"]: a for a in out["system"]}
    assert system["com.android.settings"]["launcher"] is True
    assert system["com.android.settings"]["name"] == "Settings"
    assert system["com.oem.camera"]["launcher"] is False
    assert out["counts"]["system_launcher"] == 2
    third = out["third_party"][0]
    assert (third["name"], third["name_source"], third["launcher"]) == ("Trip Planner", "package", False)


def test_app_names_known_and_derived():
    from services.test_execution.app_names import app_name, derive_name

    assert app_name("com.google.android.dialer") == ("Phone", "known")
    assert app_name("com.google.android.apps.youtube.music") == ("YouTube Music", "known")
    assert app_name("com.example.cameratest") == ("Camera Test Harness", "known")
    assert derive_name("com.acme.fieldsurvey") == "Fieldsurvey"
    assert derive_name("com.acme.android.trip_planner") == "Trip Planner"
    assert derive_name("com.acme.android.app") == "Acme"
    assert derive_name("org.acme.mapViewer2") == "Map Viewer"
    assert derive_name("com.coloros.simsettings") == "Simsettings"
    assert derive_name("com.oplus.fm") == "FM"
