"""Every recorded check must say what it expected, so the report's Expected column is never blank."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
RUNTIME = BACKEND / "services" / "test_scripts" / "runtime"
for p in (BACKEND, RUNTIME):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import camharness  # noqa: E402
import dispharness  # noqa: E402
from services.test_execution.reports import check_actual, check_expected  # noqa: E402
from services.test_scripts import display_generator, generator  # noqa: E402


def _cam(tmp_path):
    return camharness.Harness({"slas": []}, serial=None, out_dir=tmp_path, apk_dir=None, overrides={})


def _disp(tmp_path):
    return dispharness.Harness({"slas": []}, serial=None, out_dir=tmp_path, overrides={})


def test_expect_accepts_positional_actual_and_infers_expected(tmp_path):
    for h in (_cam(tmp_path), _disp(tmp_path)):
        h.expect(False, "Image resolution matches 4000x3000", "640x480")
        h.expect(True, "Display is on", actual="ON", expected="ON")
        h.expect(True, "Something happened")
        first, second, third = h.checks
        assert (first["expected"], first["actual"]) == ("4000x3000", "640x480")
        assert second["expected"] == "ON"
        assert third["expected"] == "condition holds"


def test_expect_pass_and_missing_input_record_expected(tmp_path):
    h = _cam(tmp_path)
    h.expect_pass({"result": "SKIPPED", "error": "resolution not supported"},
                  ["Camera opens successfully", "Saved image resolution matches 8160x6120"])
    h.verify_op(camharness.PKG + ".ImageInspectTest", {"image_path": "<result.image_path>"}, {})
    opens, resolution, missing = h.checks
    assert opens["expected"] == "PASS"
    assert opens["actual"] == "SKIPPED: resolution not supported"
    assert resolution["expected"] == "8160x6120"
    assert missing["expected"] == "'image_path' from the previous step"
    assert missing["actual"] == "not returned"


def test_check_expected_infers_for_old_results():
    assert check_expected({"description": "Camera opens", "actual": "SKIPPED: res not supported"}) == "PASS"
    assert check_expected({"description": "Camera opens", "actual": "PASS"}) == "PASS"
    assert check_expected({"description": "verify: previous result has no 'image_path'", "actual": None}) \
        == "'image_path' from the previous step"
    assert check_expected({"description": "Saved image resolution matches 8160x6120", "actual": "x"}) == "8160x6120"
    assert check_expected({"description": "Recorded resolution matches 7680x4320",
                           "actual": "SKIPPED: missing video_path"}) == "7680x4320"
    assert check_expected({"description": "Step 1: wake (command ran)", "actual": ""}) == "exit code 0"
    assert check_expected({"description": "p95 <= 50", "operator": "<=", "target": 50, "actual": 70}) == "<= 50"
    assert check_expected({"description": "x", "expected": "ON", "actual": "OFF"}) == "ON"
    assert check_actual({"description": "verify: previous result has no 'image_path'", "actual": None}) \
        == "not returned"


def _run(body: str) -> str:
    return "def run(h):\n" + "\n".join("    " + line for line in body.splitlines()) + "\n"


def test_validators_reject_bad_expect_calls():
    entry = {"class": camharness.PKG + ".PhotoCaptureTest", "args": {}}
    ok = _run(f"res = h.op({entry['class']!r}, {{}})\nh.expect(True, 'd', res.get('a'), expected='b')")
    bad = _run(f"res = h.op({entry['class']!r}, {{}})\nh.expect(True, 'd', 1, 2)\nh.expect(True, 'd', want=1)")
    assert not [e for e in generator.validate_script(ok, {}, entry)[0] if "h.expect" in e]
    assert len([e for e in generator.validate_script(bad, {}, entry)[0] if "h.expect" in e]) == 2

    spec = {"harness": {"classes": []}}
    assert not [e for e in display_generator.validate_script(_run("h.expect(True, 'd', 1, expected=1)"), spec)[0]
                if "h.expect" in e]
    assert len([e for e in display_generator.validate_script(_run("h.expect(True, 'd', 1, 2)"), spec)[0]
                if "h.expect" in e]) == 1
