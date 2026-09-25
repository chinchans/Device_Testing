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

Output APK:

```
app/build/outputs/apk/debug/app-debug.apk
```

A convenience copy is also written as `cameratest.apk` at the project root after a successful build (re-copy with `cp` if needed).

## Install

```bash
adb install -r -g app/build/outputs/apk/debug/app-debug.apk
adb shell pm grant com.example.cameratest android.permission.CAMERA
adb shell pm grant com.example.cameratest android.permission.RECORD_AUDIO
```

`-g` grants runtime permissions at install when possible; `pm grant` covers Camera/Mic explicitly.

## JSON contract

Every operation prints **exactly one** stdout line:

```json
{"result":"PASS"|"FAIL"|"SKIPPED","error":"... optional ...", ...fields}
```

Rules:

- Single line, no pretty-print
- Host should parse the **last** line that starts with `{` and ends with `}`
- `error` is present when `result != "PASS"`
- Timing / thresholds are **not** judged in the APK

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

## Design notes

- Pure **Camera2** (no CameraX / Compose / OEM camera Intent)
- Headless preview via `SurfaceTexture` so still/video sessions configure on most HALs
- Output paths prefer the requested `output_dir`, then `/sdcard/DCIM/CameraTest`, then the app-specific files dir
- Camera IDs are **strings** (`-e camera_id 0`)

## Project layout

```
cameratest-harness/
├── app/src/main/kotlin/com/example/cameratest/
│   ├── BaseCamera2Test.kt
│   ├── PhotoCaptureTest.kt
│   ├── VideoRecordTest.kt
│   ├── CameraSwitchTest.kt
│   ├── RepeatedPhotoStressTest.kt
│   ├── ImageInspectTest.kt
│   ├── VideoInspectTest.kt
│   ├── ResolutionMatrixTest.kt
│   ├── DigitalZoomTest.kt
│   └── CapabilityTest.kt
└── app/build/outputs/apk/debug/app-debug.apk
```
