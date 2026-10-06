# Camera Test Harness (`com.example.cameratest`)

Kotlin Camera2 instrumentation APK for host-driven device validation.
The APK performs hardware operations and emits **one JSON line** on stdout.
The Python host (`pytest` + `adbutils`) applies SLAs and collects evidence.

## Build

```bash
export ANDROID_HOME="$HOME/Android/Sdk"
cd cameratest-harness
./gradlew :app:assembleDebug
```

One source tree builds three APKs (product flavors, same test classes):

| Flavor | Package | APK | Purpose |
|---|---|---|---|
| `harness` | `com.example.cameratest` | `app/build/outputs/apk/harness/debug/app-harness-debug.apk` | The test harness |
| `unauthorized` | `com.example.cameraunauthorized` | `app/build/outputs/apk/unauthorized/debug/app-unauthorized-debug.apk` | Security helper **without** CAMERA permission |
| `secondary` | `com.example.camerasecondary` | `app/build/outputs/apk/secondary/debug/app-secondary-debug.apk` | Security helper with CAMERA but **no** media permissions |

Convenience copies: `cameratest.apk`, `cameratest-unauthorized.apk`, `cameratest-secondary.apk` at the project root.

## Install

```bash
adb install -r -g cameratest.apk
adb install -r cameratest-unauthorized.apk   # only for security cases
adb install -r cameratest-secondary.apk      # only for security cases
adb shell pm grant com.example.cameratest android.permission.CAMERA
adb shell pm grant com.example.cameratest android.permission.RECORD_AUDIO
```

`-g` grants runtime permissions at install when possible; `pm grant` covers Camera/Mic explicitly.

## JSON contract

Every operation produces **exactly one** single-line JSON result:

```json
{"result":"PASS"|"FAIL"|"NOT_APPLICABLE"|"SKIPPED"|"BLOCKED_PRECONDITION","error":"... optional ...", ...fields}
```

`am instrument -w` does not forward `System.out`, so the line is also sent as an instrumentation status:

- with `-r`: parse the line `INSTRUMENTATION_STATUS: harness_json=<json>`
- without `-r`: the JSON is printed verbatim as its own line (status `stream`)

Field order per suite (matches the case-file extraction regexes):

| Suite | Leading fields |
|---|---|
| Functional | `result`, `error`?, facts |
| Performance | `result`, `metric_value` (p95 ms / throughput / %), `samples`, `latency_ms`, then `p95_latency_ms`, … |
| Reliability | `result`, `metric_value`, `failures`, `thermal_abort`, then `completed_cycles`, `fatal_camera_errors`, `app_crash_count`, `anr_count`, `cameraserver_restarted`, … |
| Security | `result`, `metric_value` (1 = enforced), `unauthorized_access_count`, `crash_count`, evidence |

Rules:

- Single line, no pretty-print
- `error` / `reason` is present when `result != "PASS"`
- `NOT_APPLICABLE` when the DUT lacks the capability (never an invented value)
- SLAs are **not** judged in the APK; it reports facts and measurements
- All timing uses `SystemClock.elapsedRealtimeNanos`

## Case coverage

`operation_map.json` maps all 80 Camera cases (`cam_fun_*`, `cam_per_*`, `cam_rel_*`, `cam_sec_*`) to a
class, its arguments, host pre/post steps and multi-phase sequences.

The Performance / Reliability / Security case files name classes such as
`com.example.cameratest/.ColdLaunchPerfTest`. Every such name exists in the APK (`CaseAliases.kt`): each is
a one-line alias that presets the mode of a parameterized operation. Run them as:

```bash
adb shell am instrument -w -r -e iterations 10 \
  -e class com.example.cameratest.ColdLaunchPerfTest \
  com.example.cameratest/androidx.test.runner.AndroidJUnitRunner
```

Always pass `-e class`; running the package without it would execute every operation.

## Invoke operations

Package / runner:

```text
com.example.cameratest/androidx.test.runner.AndroidJUnitRunner
```

### CapabilityTest

```bash
adb shell am instrument -w -r \
  -e class com.example.cameratest.CapabilityTest \
  com.example.cameratest/androidx.test.runner.AndroidJUnitRunner
```

Optional filter: `-e camera_id 0`

### PhotoCaptureTest

```bash
adb shell am instrument -w -r \
  -e class com.example.cameratest.PhotoCaptureTest \
  -e camera_id 0 \
  -e resolution 1920x1080 \
  -e format JPEG \
  com.example.cameratest/androidx.test.runner.AndroidJUnitRunner
```

### VideoRecordTest

```bash
adb shell am instrument -w -r \
  -e class com.example.cameratest.VideoRecordTest \
  -e camera_id 0 \
  -e resolution 1920x1080 \
  -e fps 30 \
  -e duration_sec 5 \
  com.example.cameratest/androidx.test.runner.AndroidJUnitRunner
```

### CameraSwitchTest

```bash
adb shell am instrument -w -r \
  -e class com.example.cameratest.CameraSwitchTest \
  -e source_camera 0 \
  -e target_camera 1 \
  -e iterations 10 \
  com.example.cameratest/androidx.test.runner.AndroidJUnitRunner
```

### RepeatedPhotoStressTest

```bash
adb shell am instrument -w -r \
  -e class com.example.cameratest.RepeatedPhotoStressTest \
  -e camera_id 0 \
  -e count 10 \
  -e mode rapid \
  com.example.cameratest/androidx.test.runner.AndroidJUnitRunner
```

`mode`: `rapid` (keep session open) or `preview_dwell` (reopen each shot).

### ImageInspectTest

```bash
adb shell am instrument -w -r \
  -e class com.example.cameratest.ImageInspectTest \
  -e image_path /sdcard/Android/data/com.example.cameratest/files/CameraTest/photo.jpg \
  com.example.cameratest/androidx.test.runner.AndroidJUnitRunner
```

### VideoInspectTest

```bash
adb shell am instrument -w -r \
  -e class com.example.cameratest.VideoInspectTest \
  -e video_path /sdcard/Android/data/com.example.cameratest/files/CameraTest/video.mp4 \
  com.example.cameratest/androidx.test.runner.AndroidJUnitRunner
```

### ResolutionMatrixTest

```bash
adb shell am instrument -w -r \
  -e class com.example.cameratest.ResolutionMatrixTest \
  -e camera_id 0 \
  -e resolutions '["1920x1080","1280x720"]' \
  com.example.cameratest/androidx.test.runner.AndroidJUnitRunner
```

### DigitalZoomTest

```bash
adb shell am instrument -w -r \
  -e class com.example.cameratest.DigitalZoomTest \
  -e camera_id 0 \
  -e min_zoom 1.0 \
  -e max_zoom 2.0 \
  -e steps 5 \
  com.example.cameratest/androidx.test.runner.AndroidJUnitRunner
```

## Harness v2 operations

All take `-e camera_id` (default: first rear camera). Only the main arguments are listed; see the KDoc
at the top of each class for the rest.

| Class | Selector | Cases | Notes |
|---|---|---|---|
| `AspectRatioCaptureTest` | `aspect_ratios=4:3,16:9,1:1` | fun_006 | Largest JPEG per ratio, decoded ratio check |
| `FocusTest` | `mode=auto\|tap\|continuous`, `x`,`y` (0..1) | fun_007/008 | AF trigger → locked state, capture |
| `FlashTest` | `mode=on\|off\|auto\|torch` | fun_009–011 | Precapture, reports `FLASH_STATE`, `flash_required` |
| `OpticalZoomTest` | `target_camera` or `zoom_ratios` | fun_013/014 | Physical lens via zoom ratio or standalone id |
| `VideoProfileTest` | `profiles=1920x1080@30,…` / `resolutions` | fun_016/017 | MediaCodec recording, file + PTS-based FPS check |
| `CaptureModeTest` | `mode=hdr\|night\|portrait\|hdr_video` | fun_018–020 | Camera2 extensions → scene modes → NOT_APPLICABLE; HLG10 video |
| `LatencyPerfTest` | `mode=cold_launch\|warm_launch\|ttff\|shutter\|af\|switch\|lens_switch\|processing\|save` | per_001–012, 020 | `iterations`, p95 / mean |
| `BurstPerfTest` | `count` | per_013/014 | Throughput + inter-frame timing |
| `VideoPerfTest` | `mode=start\|finalize\|fps` | per_015–017 | First encoded sample, finalize + fsync, per-second FPS windows |
| `ResourcePerfTest` | `mode=memory\|cpu` | per_018/019 | PSS baseline/peak/recovered; `/proc/stat` CPU while recording |
| `EnduranceTest` | `operation=open_close\|capture\|switch\|lens_switch\|zoom\|af\|flash\|preview\|memory_leak\|resource_release\|cameraservice\|media_integrity\|mixed` | rel_001–004, 006–011, 013–015, 019, 020 | Bounded cycles / duration, thermal abort |
| `VideoEnduranceTest` | `operation=start_stop\|long` | rel_005, 012 | Clip cycles / segmented long recording |
| `LifecycleEnduranceTest` | `operation=background_foreground\|lock_unlock\|orientation` | rel_016–018 | Camera recovery after each transition |
| `SecurityProbeTest` | `scenario=…` (20 scenarios) | sec_001–015, 017–020 | Access classification + blank-frame detection |
| `MediaAccessProbeTest` | `mode=full\|read` | sec_016 | Seeds media, secondary helper tries to list/read |
| `HarnessInfoTest` | – | – | Version, role (flavor), operation list |

Existing v1 operations (`PhotoCaptureTest`, `CameraSwitchTest`, `ResolutionMatrixTest`, `DigitalZoomTest`,
`VideoRecordTest`, inspect tests) cover fun_001–005, 012, 015 unchanged. `CapabilityTest` now also reports
physical lenses + 35 mm-equivalent focal lengths, capabilities (burst, logical multi-camera, reprocessing),
ZSL support, AF regions, extensions, scene modes, HLG10, encoder video sizes, aspect ratios and camera
privacy-toggle support — the host uses these to fill case variables and decide NOT_APPLICABLE up front.

### Host responsibilities

- Permission grant / revoke / `pm clear`, reboot and OTA happen **between phases** (see `phases` in
  `operation_map.json`): revoking a runtime permission kills the app, so the APK cannot do it to itself.
- Semi-automated cases (`manual` in the map) need a tester: focus targets, lighting, privacy toggle,
  one-time permission dialog, secure lock screen.

### Caveats

- Operations that use the shell (`LatencyPerfTest` launch modes, `LifecycleEnduranceTest`, `EnduranceTest`,
  `SecurityProbeTest`, `ResourcePerfTest`) connect `UiAutomation`; do not run them concurrently with an
  Appium UiAutomator2 session.
- Security scenarios decide "image data reached the app" from preview luma, so point the camera at a lit
  scene (a covered lens looks like a privacy-blanked stream).
- Background / lock-screen security scenarios report `BLOCKED_PRECONDITION` when the instrumentation keeps
  the process in a foreground state (the restriction cannot be observed then).
- Helper-app scenarios start the helper's instrumentation from inside the harness (`am instrument` via the
  shell). If an OEM build refuses nested instrumentation, run the helper directly:
  `am instrument -w -r -e class com.example.cameratest.SecurityProbeTest -e scenario helper_probe com.example.cameraunauthorized/androidx.test.runner.AndroidJUnitRunner`.

## Design notes

- Pure **Camera2** (no CameraX / Compose / OEM camera Intent)
- v2 operations stream preview into a YUV `ImageReader` (exact first-frame time, frame count, luma for blank-frame detection)
- Video performance uses MediaCodec + MediaMuxer (first encoded sample, presentation timestamps)
- Cold / warm launch use `LaunchProbeActivity` in a separate `:launchprobe` process
- Output paths prefer the requested `output_dir`, then `/sdcard/DCIM/CameraTest`, then the app-specific files dir
- Camera IDs are **strings** (`-e camera_id 0`)

## Project layout

```
cameratest-harness/
├── operation_map.json                 # 80 cases → class, args, host steps
├── app/src/main/kotlin/com/example/cameratest/
│   ├── BaseCamera2Test.kt / HarnessTest.kt / VideoPipeline.kt   # shared base + helpers
│   ├── ProbeActivity.kt / LaunchProbeActivity.kt                # foreground + launch probes
│   ├── CapabilityTest.kt, HarnessInfoTest.kt
│   ├── PhotoCaptureTest.kt, CameraSwitchTest.kt, ResolutionMatrixTest.kt, AspectRatioCaptureTest.kt
│   ├── FocusTest.kt, FlashTest.kt, DigitalZoomTest.kt, OpticalZoomTest.kt, CaptureModeTest.kt
│   ├── VideoRecordTest.kt, VideoProfileTest.kt, ImageInspectTest.kt, VideoInspectTest.kt
│   ├── LatencyPerfTest.kt, BurstPerfTest.kt, VideoPerfTest.kt, ResourcePerfTest.kt
│   ├── EnduranceTest.kt, VideoEnduranceTest.kt, LifecycleEnduranceTest.kt, RepeatedPhotoStressTest.kt
│   ├── SecurityProbeTest.kt, MediaAccessProbeTest.kt
│   └── CaseAliases.kt                 # class names used by the case files
├── app/src/unauthorized/AndroidManifest.xml   # removes CAMERA / RECORD_AUDIO
└── app/src/secondary/AndroidManifest.xml      # removes media / storage permissions
```
