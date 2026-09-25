# Device testing analysis
_Exported on 25/09/2026 at 12:31:03 GMT+5:30 from Cursor (3.0.13)_

---

**User**

JUST ANALYZE THS INFORMATON 
DONT MAKE ANY CODE CHANGES

**Device Testing** is an Electron + FastAPI POC that turns product-spec PDFs into a guided device-validation pipeline: extract grounded features → classify them → attach test cases → (later) generate scripts, run tests, RCA, and report.

---

## What it is

A **device-agnostic Agentic RAG** platform: upload a product-spec PDF, discover sections from the document (not hard-coded phone categories), extract features/specs with grounding against evidence, map them to a mobile checklist, and continue into test-case / framework selection. Downstream automation (codegen, execution, RCA, reports) is mostly scaffolding.

| Layer | Stack |
|--------|--------|
| Frontend | Electron + vanilla HTML/CSS/JS |
| Backend | FastAPI, Pydantic, Azure OpenAI (chat + embeddings) |
| PDF / RAG | PyMuPDF (+ OCR), dense vectors + BM25 → RRF → rerank |
| Config | `Backend/config/default.yaml` + `.env` |

---

## End-to-end workflow (intended pipeline)

```
Splash → Device Selection → Feature Extraction → Device Classification
      → Test Case Generation → Framework Selection → Script Generation
      → Test Execution → RCA → Reports
```

**What actually runs today (happy path):**

1. **Device Selection** — pick device type (`mobile` / `laptop` / `tablet` / `wearable`) and test focus; gates Feature Extraction.
2. **Feature Extraction** — browse/upload a PDF → `POST /api/extract-from-path` or `/api/extract-features`.
3. **Backend indexing** — load → parse (OCR if needed) → clean → chrome strip → RAG normalize → structure → chunk → embed → vector + BM25 indexes (content-hash cache).
4. **Agentic extraction** — QueryUnderstanding → ExtractionPlanner → hybrid retrieve → RRF → rerank → expand → structured extract → grounding → reconcile → coverage → optional rewrite/retry.
5. **Classification** — map onto mobile standards (Camera, Connectivity, Cellular, Display, Battery, Sensors, Audio, USB) + testable extras; fill **Device Classification** (OS, manufacturer, model, storage, CPU, RAM).
6. **Test Case Generation** — load curated catalogs per feature (`GET /api/test-cases/{feature}`); **Camera only** is fully populated.
7. **Framework Selection** — multi-select (ADB, Appium, UiAutomator2, etc.).
8. **Generate Test Scripts onward** — UI placeholders / older mocks; not wired to real LLM codegen or device runners.

---

## Current functionalities

**Backend (strong)**
- PDF upload/path indexing with hash dedupe
- OCR retry when standard features are missing
- Hybrid retrieval + tracing under `data/traces/`
- Grounded extraction with anti-hallucination (evidence-only + grounding validator)
- Feature classification + extra-testability filtering
- Device profile for the classification table
- Curated **Camera** test-case catalogs (Functionality / Performance / Reliability / Security) with full codegen-oriented fields
- APIs: health, documents, extract, extract-features, extract-from-path, test-cases

**Frontend (implemented through frameworks)**
- Splash / Home, Device Selection, Feature Extraction, Device Classification
- Test Case Generation tree (live for Camera)
- Framework Selection, Settings (API base URL)
- Older mock script/execution UI still present but not the main path

---

## Not yet implemented / stubbed

| Area | Status |
|------|--------|
| **LLM test-script generation** | Placeholder (“later step”); catalogs ready as the next surface |
| **Real test execution** | Nav: “Available in a later release”; mock scoring only |
| **RCA** | Placeholder only |
| **Reports** | Placeholder only |
| **Non-camera default catalogs** | Only `data/test_cases/camera/` |
| **Laptop / tablet / wearable checklists** | Explicitly reserved / empty |
| **Non–feature-testing focus areas** | UI only (hardware bring-up, OS/kernel, app compat, OTA) — don’t change extraction |
| **Test-suite PDF ingestion** | Upload UI exists; not wired to backend |
| **DOCX/XLSX** | Dialog may allow them; API is PDF-only |

---

## Maturity snapshot

| Stage | Maturity |
|-------|----------|
| Spec PDF → grounded features | Strong |
| Mobile checklist + device profile | Strong |
| Camera test catalogs + API | Strong |
| Framework selection UX | Ready |
| Script gen / execution / RCA / reports | Not implemented |
| Non-mobile taxonomies & non-camera suites | Not started |

**Bottom line:** The product is real and usable through **extract → classify → Camera test cases → pick frameworks**. Everything after that is planned scaffolding; Camera catalogs are the natural next integration point for LLM script generation.

DONT MAKE ANY CODE CHANGES

---

**Cursor**

I'll analyze the product description against the actual codebase—read-only, no code changes—so the assessment is grounded in what is implemented versus stubbed.

The workspace looks like catalogs and source docs, not the Electron/FastAPI app. I'll read those artifacts so the analysis can map the brief to what is actually here.

I have enough to analyze the brief against this workspace. No code changes.

---

## What this information actually describes

The brief describes a **POC validation platform**, not a finished device-test product. The working slice is:

**product-spec PDF → grounded features → mobile classification → attach Camera catalogs → pick frameworks**

Everything after that (script gen, execution, RCA, reports) is UI/navigation scaffolding.

This workspace is **not that Electron + FastAPI app**. It is the **content pack** the pipeline would consume:

| Folder | Role |
|--------|------|
| `Product_Spec/` | Sample input: Galaxy S24 press PDF |
| `CDD/` | Reference standards: Android 12 CDD + Android 17 CDD |
| `Test_Cases/Moble/` | Curated schemas + Camera catalogs (Display is schema-only) |

That matches the brief’s claim that Camera catalogs are the next integration surface — those catalogs already live here, in a more complete form than the brief lists.

---

## What is real vs what is aspirational

```
Intended:  Splash → Device → Extract → Classify → Test cases → Frameworks → Scripts → Run → RCA → Reports
Today:     Splash → Device → Extract → Classify → Camera catalogs → Frameworks
           [scripts / run / RCA / reports are placeholders]
```

| Layer | Reality |
|--------|---------|
| Spec PDF → grounded features | Strong (per brief; app is elsewhere) |
| Mobile checklist + device profile | Strong |
| Camera test catalogs | Strong — and **broader here than the brief says** |
| Framework selection | UX only |
| Script gen / execution / RCA / reports | Not implemented |
| Laptop / tablet / wearable | Reserved / empty |
| Non-camera suites | Not started in the app; Display **schemas** exist here |

The “device-agnostic Agentic RAG” claim is the **architecture**, not the current product. Runtime taxonomies and catalogs are mobile-first, Camera-first.

---

## This workspace vs the brief

The brief lists Camera catalogs as **Functionality / Performance / Reliability / Security**.  
Here there are **nine** Camera suites, ~20 cases each (~180 cases):

| Suite | File | Shape |
|--------|------|--------|
| Functional | `camera_functonal_test_cases_OPENA.json` | Older, simpler schema |
| Functional (manual outlier) | `..._DEEPSEEK.json` | One lab case, different schema |
| Performance, Stress, Reliability, Power/Thermal, Negative, Security, Compatibility, Regression/OTA | `*_OPENA.json` | Codegen-ready schema |

Later suites already include what LLM codegen would need:

- `codegen_eligible`, `feasibility`, `priority`
- `capability_discovery` (ADB + regex)
- `setup_commands` / `execution_procedure`
- `verification_slas` with operators and thresholds
- `evidence_collection`
- target stack: **Python + pytest + adbutils + uiautomator2**, plus a placeholder harness `com.example.cameratest`

So catalogs are **ahead of the product**. The app stops at “show Camera cases and pick frameworks.” The JSON already assumes a runner and a codegen contract.

Display is the next feature on paper, not in catalogs:

- `Dsplay_requrements.json` and `Requrements.json` (schema v2, with runtime ADB sources)
- **No** Display test-case suites

`Complete_requrements.json` is a full Android device-spec baseline meant to feed applicability, codegen, execution, RCA, and reporting — those engines do not exist yet.

---

## Architecture reading

Two systems, loosely coupled:

1. **Agentic extraction (app)** — PDF → chunks → hybrid retrieve → grounded structured extract → classify. Goal: do not invent specs.
2. **Curated catalogs (this repo)** — human/LLM-authored templates with `${VARIABLE}` slots, applicability rules, and codegen hints.

The join is: extracted features / device profile → fill variables → select applicable Camera cases → (later) generate scripts.

That is a sound split. Extraction stays evidence-bound; catalogs stay reviewable. The risk is the **unbuilt join**: codegen will be the first place the model can invent behavior again, unless it is constrained to catalog fields only.

Framework selection in the UI (ADB, Appium, UiAutomator2, …) does **not** match the catalogs. Catalogs already lock to ADB + instrumentation + pytest. Multi-select frameworks is not wired into generation.

---

## Gaps and tensions

**1. Device-agnostic vs mobile-only**  
Device types and non-feature focus areas (bring-up, kernel, app compat, OTA) are UI gates. Extraction is not supposed to change for those. Users can pick paths that go nowhere.

**2. Input quality vs extraction ambition**  
The sample spec is a **press PDF**, not an engineering spec. Marketing copy will under-specify Camera2 IDs, modes, thermal limits, etc. CDD (Android 12 vs 17) is a standard, not a device spec. Grounding can be correct and still leave many `${VARS}` unresolved.

**3. Schema drift**  
Functional OPENAI cases use `test_case_id` / `steps` / `expected_results`. Later suites use `test_metadata` / `execution_procedure` / `verification_slas`. DEEPSEEK is a third shape (`NOT_SUPPORTED_BY_FRAMEWORK`). One `GET /api/test-cases/{feature}` cannot treat these uniformly without a mapper.

**4. Path / naming drift**  
Brief: `data/test_cases/camera/`.  
Here: `Test_Cases/Moble/Camera/` (and `Dsplay`, `functonal`, `requrements`). Any API that keys on folder names will miss files.

**5. Two ingest paths, one wired**  
Product-spec PDF is the real path. Test-suite PDF upload and DOCX/XLSX look available in UI but are not backend-backed.

**6. Catalogs assume a missing harness**  
`com.example.cameratest`, `ColdLaunchPerfTest`, unauthorized/secondary packages, golden-build JSON for OTA — none of that is in this tree. Codegen against these files would emit scripts that cannot run.

**7. Downstream is a cliff**  
After Framework Selection the happy path ends. Script/execution/RCA/report screens can look like a product and are not.

---

## Maturity, restated

| Stage | Brief | This workspace |
|--------|--------|----------------|
| Spec → grounded features | Strong | Not present (app lives elsewhere) |
| Mobile profile / checklist | Strong | `Complete_requrements.json` is the target schema |
| Camera catalogs | Strong (4 types) | Stronger (9 types, codegen-shaped) |
| Display | Not started | Requirements only |
| Framework UX | Ready | Catalogs already chose a stack |
| Script / run / RCA / report | Not implemented | Catalogs already describe them |

**Bottom line:** The usable product is extract → classify → **attach Camera catalogs** → pick frameworks. This folder is the Camera (and Display-schema) knowledge pack for that join. The next real product step is not more UI stages — it is binding extracted device profile → these catalog variables → constrained script generation, against a harness that does not exist yet.

No code was changed.

---

**User**

the letter "i" is not working n ths PC so if there's any spellng mstake or missing "i" add t yourself

---

**Cursor**

Understood. I’ll treat missing **i** as a keyboard problem, not as your intent.

When you type, I’ll fill in **i** (and obvious knock-on spelling) before I interpret the request. Examples from how this shows up:

- `ths` → this  
- `spellng` → spelling  
- `mstake` → mistake  
- `add t yourself` → add it yourself  
- `INFORMATON` → INFORMATION  

I will not change project files or rename folders just to fix typos unless you ask for that. This is only how I read your messages.

---

**User**

so the complete workgn framework s n dfferent PC, only the test cases and test harness tasks are to be fnshed n ths PC, so our man goal s to buld a test harness for the CAMERA based on the exstng test sutes

so just analyse ths and dont make any code changes

---

**Cursor**

I’ll analyze the Camera suites as the spec for a test harness on this PC—contracts, gaps, and what “done” would mean—without changing any code.

The working product (Electron + FastAPI + RAG) stays on the other PC. This PC’s job is the **Camera execution layer**: take the existing suites and make them runnable. No code was changed.

---

## Split of work

| PC | Owns |
|----|------|
| Other PC | PDF extract, classify, attach catalogs, framework picker, later codegen/RCA UI |
| **This PC** | Camera **test cases** (already here) + **test harness** (not here yet) |

The suites are not just documentation. They already specify the harness: package name, transport, stdout contract, class names, SLAs, and evidence. Building the harness means **implementing that contract**, not inventing a new test design.

---

## What “harness” means here

The JSON describes **two layers**, not one APK:

```
Host (pytest + adbutils [+ uiautomator2])
    → ADB setup / capability discovery / evidence
    → adb shell am instrument …
Device APK  com.example.cameratest
    → Camera2 / MediaRecorder / permission workloads
    → one JSON line on stdout
Host evaluator
    → parse JSON, apply verification_slas, classify result
```

`camera_suite_metadata.target_language.json` locks the host side:

- Python 3.10–3.12, **pytest**, **adbutils**, **uiautomator2**
- Fixture: `device` → `adbutils.AdbDevice`
- Outcomes: `DutFirmwareDefect`, `AppCrash`, `HardwareThrottle`, `TestArtifact`, `NotApplicable`

Later suites lock the device side:

- Package: `com.example.cameratest`
- Transport: `adb shell am instrument`
- Stdout: **single-line JSON** with at least `result`, plus suite-specific keys (`metric_value`, `samples`, `latency_ms`, `failures`, `thermal_abort`, …)
- Missing capability → `NOT_APPLICABLE`, never invent a value

This workspace has **no APK, no Android project, no pytest runner**. Only JSON.

---

## What you already have (the spec)

Nine Camera suites, ~20 cases each:

| Suite | Schema | Ready for a harness? |
|--------|--------|----------------------|
| Functional (`..._OPENA.json`) | Old: `steps` / `expected_results` / `${VARS}` | Spec only — no class names, no JSON contract |
| Functional DEEPSEEK | One night-mode lab case | Explicitly **not** framework-supported |
| Performance, Stress, Reliability, Power/Thermal, Negative, Security, Compatibility, Regression/OTA | Codegen schema | Yes — named instrumentation classes |

Inventory from those files:

- **141** unique instrumentation classes (160 class references)
- Helper packages: `com.example.cameraunauthorized`, `com.example.camerasecondary`
- Feasibility: 134 fully automated, 19 semi-automated, 7 `AUTO_LAB` (power), 1 not supported
- Almost all later cases are `codegen_eligible: true`
- Procedure pattern: `shell_command` (preflight) then `instrumentation` (workload)

So the harness backlog is essentially: **implement ~141 Camera2/instrumentation tests + a Python host that drives them**.

---

## What the host vs the APK must do

**APK (`com.example.cameratest`)** must implement the named tests, for example:

- Perf: `ColdLaunchPerfTest`, `WarmLaunchPerfTest`, `ShutterLatencyPerfTest`, `PreviewTtffPerfTest`, …
- Stress: `RepeatedPhotoStressTest`, `ContinuousVideoStressTest`, 500-cycle open/close/switch/zoom, …
- Reliability: endurance + crash/ANR + media integrity
- Power/thermal: `PowerPreviewTest`, `ThermalThrottleVideoTest`, battery drain
- Negative: invalid zoom/AF/flash/id, storage full, permission denied
- Security: grant/deny/revoke, privacy toggle, lock screen, isolation
- Compatibility: Camera2 availability, formats, codecs, MediaStore, third-party packages
- OTA: `PostOta*` plus golden-baseline compare (host must **not** overwrite golden)

Workloads need Camera2 timestamps (`elapsedRealtimeNanos`), not UiAutomator click times. That is written into the performance rules.

**Python host** must:

1. Discover capabilities (`dumpsys media.camera`, `getprop`, …) and fill `${REAR_PRIMARY_CAMERA_ID}` etc.
2. Skip with `NOT_APPLICABLE` when hardware is missing
3. Run setup (wake, keyguard, `pm grant`, logcat clear)
4. Launch instrumentation and parse one JSON line
5. Evaluate `verification_slas` (`<= 1500 ms`, etc.)
6. Collect evidence (logcat, meminfo, thermal, images)
7. Teardown (`force-stop`, restore privacy/storage filler)

`uiautomator2` is listed but almost unused in the later suites. Most work is ADB + instrumentation. UIAutomator matters more if you later automate the **old functional** suite (OEM camera app).

---

## Hard constraints in the suites

These are product rules, not optional polish:

- Bounded cycles/durations only (stress: 200–1000 cycles, video up to 60 min)
- Abort on critical thermal; do not `drop_caches`
- Low-storage tests use an isolated filler dir and always delete it
- Security: dedicated DUT, dedicated apps, no privilege-escalation, no user-data fishing
- OTA: save pre-OTA golden JSON; compare after; never silently refresh golden
- Power: several cases are `AUTO_LAB` (need a power monitor, not just ADB)
- Semi-automated: flash illumination, privacy indicator, lock screen, third-party apps, incoming call — host can run the APK, a human or extra fixture still has to confirm

---

## Gaps that will block a “complete” harness

**1. Functional suite is a different product**  
`camera_functonal_test_cases_OPENA.json` talks about `${CAMERA_TEST_APP}` and UI steps. It does not name `com.example.cameratest` classes. A Camera2 harness will not automatically cover it unless you rewrite those 20 cases into the later schema.

**2. Device profile is missing on this PC**  
Applicability depends on `Camera_requrements.json` + extracted S24 (or live `dumpsys`). This PC has the schema and a press PDF, not a filled device profile from the other PC’s extractor.

**3. Placeholder names are the real API**  
`com.example.cameratest` and `com.example.cameratest/.ColdLaunchPerfTest` are what generated scripts will call. If the APK uses another package/class map, the other PC’s codegen will miss.

**4. No golden-build / lab / third-party apps here**  
OTA, power lab, `${THIRD_PARTY_CAMERA_PACKAGE}`, video-call packages, lock-screen PIN — all external.

**5. Display / other features are out of scope**  
Display is requirements-only. Stay on Camera.

---

## Sensible definition of “done” on this PC

Not “all 180 cases green on day one.” A realistic harness milestone:

1. **Host skeleton** — pytest + device fixture, variable resolver, JSON parser, SLA eval, evidence folder, five result classes  
2. **APK skeleton** — installable instrumentation, one JSON-line emitter, Camera2 open/preview/capture  
3. **First vertical slice** — a few fully automated, no-lab cases (e.g. rear/front capture, Camera2 availability, permission grant/deny, cold launch)  
4. **Then fill classes by suite** — Performance → Negative → Compatibility → Reliability/Stress → Security → Power → OTA  
5. **Leave aside** — DEEPSEEK night mode, `AUTO_LAB` power, semi-automated UX, old functional UI suite until someone maps them

That is enough for the other PC to treat catalogs as executable: codegen or a thin runner can call this harness without owning Camera2.

---

## Bottom line

This PC is the **Camera runtime**. The suites already are the spec: ~141 instrumentation tests, a pytest host, and a strict JSON/SLA/evidence contract. Nothing in this tree implements that yet. The other PC can extract and attach cases; it cannot run them until this harness exists.

No code was changed. When you want to start, the clean first build is host + APK skeleton + a small fully-automated Camera slice, not all nine suites at once.

---

**User**

# Prompt: Generate a Plan for Building the Camera Test Harness

## Role

You are a **Principal Android Camera Test Architect** specializing in designing **device-side test harnesses** for automated validation frameworks. Your task is not to write test cases, but to produce an **executable engineering plan** for building a standardized Camera Test Harness APK.

---

## Background & Constraints

Existing framework architecture:

- **Host layer**: Python (pytest + adbutils) handles orchestration, SLA evaluation, and evidence collection.
- **Device layer**: Kotlin Instrumentation APK (the Harness) performs Camera2 hardware operations.
- **Communication protocol**: `adb shell am instrument -w -e key value`, with the Harness returning a **single-line JSON** to stdout.

Hard contract the Harness must satisfy:

```json
{
  "harness_standard": {
    "invocation": "adb shell am instrument -w -e <key> <value> ... <pkg>/.<Class>",
    "stdout_format": "single-line JSON",
    "required_fields": {
      "result": "PASS | FAIL | SKIPPED"
    },
    "optional_fields": {
      "metric_value": "float — primary measurement",
      "latency_ms": "int — operation latency",
      "failures": "int — non-fatal failure count",
      "image_path": "string — saved photo path",
      "video_path": "string — saved video path",
      "width": "int",
      "height": "int",
      "fps": "float",
      "duration_ms": "int",
      "error": "string — populated when result=FAIL"
    }
  }
}
```

**Core principle**: The Harness **only performs hardware operations, it does not make test judgments**. It does not know SLAs, does not know PASS thresholds, does not know test names. It accepts parameters, performs an operation, and returns JSON.

---

## Camera Operations to Support

Based on the existing Camera test suites, the Harness must expose the following operations (each maps to an Instrumentation test class):

| Operation Class | Purpose | Key Parameters | Return Fields |
|-----------------|---------|----------------|---------------|
| `PhotoCaptureTest` | Single photo capture | camera_id, resolution, format, output_dir | image_path, width, height, format, latency_ms |
| `VideoRecordTest` | Video recording | camera_id, resolution, fps, duration_sec, output_dir | video_path, width, height, fps, duration_ms |
| `CameraSwitchTest` | Front/rear camera switching | source_camera, target_camera, iterations | completed_iterations, failed_iterations, latency_ms |
| `RepeatedPhotoStressTest` | Rapid burst stress | camera_id, count, mode | metric_value (completed), failures, thermal_abort |
| `ImageInspectTest` | Image metadata verification | image_path | width, height, format |
| `VideoInspectTest` | Video metadata verification | video_path | width, height, fps, duration_ms |
| `ResolutionMatrixTest` | Iterate all photo resolutions | camera_id, resolutions, format | tested, passed, failed |
| `DigitalZoomTest` | Digital zoom sweep | camera_id, min_zoom, max_zoom, steps | requested_steps, applied_steps, failed_steps |
| `CapabilityTest` | Camera capability discovery | camera_id (optional) | all supported sizes, formats, FPS, focus modes |

---

## Reference Resources

### Primary References (Must Read)

**1. Google's Official Camera2 Sample — `Camera2TakeAPhotoController.kt`**
URL: `https://github.com/android/camera-samples/blob/main/samples/camera2-takeaphoto/src/main/java/com/android/camera2/takeaphoto/Camera2TakeAPhotoController.kt`

**Why reference it**:
- Demonstrates the standard Camera2 open/configure/capture/close lifecycle
- Correct `ImageReader` usage (`newInstance` + `setOnImageAvailableListener`)
- How to build a `CaptureRequest.TEMPLATE_STILL_CAPTURE` request
- How to set focus mode (`CONTROL_AF_MODE_CONTINUOUS_PICTURE`)
- The `session.capture()` callback pattern

**What to modify**:
- Change the `onPhotoCaptured: (Image, Int) -> Unit` callback into **save to a specified path + return JSON**
- Change the fixed `PREVIEW_WIDTH/HEIGHT` to **read from parameters**
- Remove Compose dependencies, convert into a **pure Instrumentation test class**
- Remove the `BaseCamera2Controller` inheritance, make it a **self-contained test class**

**2. `android/camera-samples` Repository Overview**
URL: `https://github.com/android/camera-samples/tree/main/samples`

**Why reference it**:
- Demonstrates the `:core-camera` module's `BaseCamera2Controller` design (background thread, open/close, session creation)
- Each sample is an independent Gradle library module (`samples/{api}-{feature}/`)
- Unified architecture pattern: `UiState` → `ViewModel` → `Controller` → `Screen`

**What to modify**:
- Ignore the UI layer (Compose, ViewModel)
- Keep only the `Controller` layer's Camera2 logic
- Convert the `Controller` into a subclass of `InstrumentationTestCase`

**3. Jetpack Camera App Testing Framework (reference for test structure)**
URL: `https://deepwiki.com/google/jetpack-camera-app/7-testing-framework`

**Why reference it**:
- Demonstrates `AndroidJUnit4` + `GrantPermissionRule` + `UiAutomator` combined usage
- Permission handling patterns: `grantPermissionDialog`, `denyPermissionDialog`
- Media cleanup pattern: `runMediaStoreAutoDeleteScenarioTest`
- Test isolation pattern: each test is independent, no dependency on prior test state

**4. CTS Camera Test Compilation and Execution Method**
URL: `https://blog.csdn.net/theojames/article/details/124303161`

**Why reference it**:
- Shows how to compile `CtsCameraTestCases.apk`
- Shows the `adb shell am instrument -e class ... -w android.camera.cts/androidx.test.runner.AndroidJUnitRunner` invocation pattern
- This is the direct reference for how our Harness should be invoked

---

## Required Sections of the Engineering Plan

Your output plan must include the following sections:

### 1. Project Structure

```
cameratest-harness/
├── settings.gradle.kts
├── build.gradle.kts                    # root build config
├── gradle.properties                   # SDK versions, Kotlin version
├── gradlew / gradlew.bat
├── app/
│   ├── build.gradle.kts                # module build config
│   └── src/main/
│       ├── AndroidManifest.xml         # declare CAMERA/RECORD_AUDIO permissions
│       └── kotlin/com/example/cameratest/
│           ├── BaseCamera2Test.kt      # shared logic: open/close/threads/JSON output
│           ├── JsonResult.kt           # JSON serialization helper
│           ├── PhotoCaptureTest.kt
│           ├── VideoRecordTest.kt
│           ├── CameraSwitchTest.kt
│           ├── RepeatedPhotoStressTest.kt
│           ├── ImageInspectTest.kt
│           ├── VideoInspectTest.kt
│           ├── ResolutionMatrixTest.kt
│           ├── DigitalZoomTest.kt
│           └── CapabilityTest.kt
└── README.md
```

### 2. Gradle Build Configuration

Must specify:
- `compileSdk` / `targetSdk` / `minSdk` versions (recommend 34/34/30 — Camera2 is available from API 21+, but production devices are mostly ≥30)
- Kotlin version (recommend 2.0+)
- Dependencies:
  - `androidx.test:runner`
  - `androidx.test.ext:junit`
  - `androidx.test:rules`
  - Do NOT include CameraX (stay pure Camera2 to minimize dependencies)
- `testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"`
- `testApplicationId = "com.example.cameratest"` (must match the package name Python scripts expect)

### 3. BaseCamera2Test Design

This is the base class for all operation classes, and must handle:

**Initialization**:
```kotlin
@get:Rule val permissionRule = GrantPermissionRule.grant(
    Manifest.permission.CAMERA,
    Manifest.permission.RECORD_AUDIO
)
```

**Parameter reading**:
```kotlin
val args = InstrumentationRegistry.getArguments()
val cameraId = args.getString("camera_id")?.toInt() ?: fail("camera_id required")
```

**Background thread**:
```kotlin
val backgroundHandler = Handler(HandlerThread("camera-test-bg").apply { start() }.looper)
```

**JSON output**:
```kotlin
protected fun emitResult(json: Map<String, Any?>) {
    val clean = json.filterValues { it != null }
    println(clean.toJson())   // single-line output
}

protected fun emitFail(error: String) {
    emitResult(mapOf("result" to "FAIL", "error" to error))
}
```

**Safe teardown**:
```kotlin
override fun onDestroy() {
    session?.close(); device?.close(); reader?.close()
    backgroundHandler?.looper?.quitSafely()
    super.onDestroy()
}
```

**Timeout protection**:
Each operation must have a `CountDownLatch` + `await(timeout, TimeUnit.SECONDS)`. On timeout, emit a FAIL JSON — never hang.

### 4. Full Implementation of PhotoCaptureTest

Must demonstrate:
- Read `camera_id`, `resolution`, `format`, `output_dir` from args
- Parse `resolution` into `width x height`
- Create reader via `ImageReader.newInstance(width, height, ImageFormat.JPEG, 2)`
- Build capture request via `CameraDevice.TEMPLATE_STILL_CAPTURE`
- In `onImageAvailable`:
  - Read `ByteBuffer`
  - Write to `/sdcard/DCIM/CameraTest/photo_<timestamp>.jpg`
  - Verify width/height via `BitmapFactory`
  - Emit JSON
- Compute `latency_ms` using `System.nanoTime()` (the equivalent of `time.monotonic_ns()`)
- **Reference the `takePicture()` logic in `Camera2TakeAPhotoController.kt`**

### 5. Full Implementation of VideoRecordTest

- Use `MediaRecorder` + `Camera2`
- Configure `CamcorderProfile` or manually set resolution/FPS
- After `MediaRecorder.start()`, schedule `Handler.postDelayed(stopRecording, duration_ms)`
- After stopping, verify the file exists and emit JSON

### 6. Full Implementation of RepeatedPhotoStressTest

- Loop `count` times calling the single-capture logic
- Immediately release resources after each capture to avoid handle leaks
- Monitor camera errors via `ActivityManager` or logcat
- Every 50 iterations, check thermal status; if over threshold, set `thermal_abort=true` and exit early
- Output: `{"result":"PASS","metric_value":500,"failures":0,"thermal_abort":false}`

### 7. Build and Verification Workflow

```bash
# Build
cd cameratest-harness
./gradlew :app:assembleDebug

# Install to DUT
adb install -r -g app/build/outputs/apk/debug/app-debug.apk

# Manually verify each operation
adb shell am instrument -w -e camera_id 0 -e resolution 4032x3024 com.example.cameratest/.PhotoCaptureTest
adb shell am instrument -w -e camera_id 0 -e count 10 -e mode rapid com.example.cameratest/.RepeatedPhotoStressTest
adb shell am instrument -w com.example.cameratest/.CapabilityTest
```

### 8. Development Roadmap

**Phase 1 (Week 1)**: Project skeleton + `BaseCamera2Test` + `PhotoCaptureTest` + `CapabilityTest`
**Phase 2 (Week 2)**: `VideoRecordTest` + `CameraSwitchTest` + `RepeatedPhotoStressTest`
**Phase 3 (Week 3)**: `ImageInspectTest` + `VideoInspectTest` + `ResolutionMatrixTest` + `DigitalZoomTest`
**Phase 4 (Week 4)**: Integrate with Python test scripts, end-to-end validate TC_CAM_FUNC_001 through TC_CAM_STRESS_001

---

## Key Cautions

1. **Never use `Intent.ACTION_IMAGE_CAPTURE`** — it launches the OEM camera app, which is uncontrollable and non-automatable.
2. **Never depend on UI elements** — the Harness is a headless Instrumentation test; it cannot click any button.
3. **Never assume a fixed resolution** — all resolutions must be read from args or `CameraCharacteristics`.
4. **Never wait indefinitely** — every `CountDownLatch.await()` must have a timeout.
5. **Never fail silently** — any exception must emit `{"result":"FAIL","error":"..."}`.
6. **Always clean up resources** — close camera, session, ImageReader, HandlerThread.

---

## Final Output Format

Produce an engineering plan in **Markdown format** that includes:
- Project structure (directory tree)
- Gradle configuration code blocks
- For each Instrumentation test class: **signature + key logic snippets** (not full implementation, but the core API calls)
- Build and verification commands
- 4-week development roadmap
- Risk list with mitigations

---

**Now produce the plan.**

---

**Cursor**

I’ll read the Camera2 sample and related references first, then produce the harness plan (no implementation in the repo).

# Camera Test Harness APK — Engineering Plan

**Role of this APK:** device-side Camera2 worker. It opens hardware, runs one operation, prints **one JSON line**, and exits.  
**Not in this APK:** SLA thresholds, test IDs, PASS/FAIL against catalogs, pytest, RAG, or OEM UI.

Host (other PC / later Python) decides `PASS` vs firmware defect. The harness only reports whether the **operation completed**, **could not run** (`SKIPPED`), or **failed in hardware/API** (`FAIL`).

---

## 0. Architecture decisions (read first)

These resolve conflicts between the official Camera2 samples, AndroidX test, and the existing Camera suites on this PC.

| Topic | Decision | Why |
|--------|----------|-----|
| Invocation | Each operation is an `android.app.Instrumentation` registered in the manifest as `com.example.cameratest/.<Class>` | Matches catalogs and your verify lines: `am instrument -w -e … com.example.cameratest/.PhotoCaptureTest`. CTS/JUnit style (`…/AndroidJUnitRunner -e class …`) is **optional** for Studio only. |
| JUnit rules | Do **not** depend on `GrantPermissionRule` for the contract path | That rule needs `AndroidJUnitRunner`. Permissions come from `adb install -g`, host `pm grant`, and `UiAutomation.grantRuntimePermission` in `onCreate`. |
| Camera IDs | `camera_id` is a **String** (`"0"`, `"1"`, logical IDs) | Camera2 IDs are not ints. Do not `.toInt()`. |
| Preview | Headless: `SurfaceTexture` + JPEG `ImageReader` | Samples use a Compose viewfinder. The harness must not click UI. Many HALs still need a preview stream. |
| Storage | App-specific dir first: `/sdcard/Android/data/com.example.cameratest/files/CameraTest/` | `/sdcard/DCIM/…` is unreliable on API 30+ scoped storage. Host `adb pull`s the returned path. |
| Teardown | `try/finally` in `onStart()`, not Activity `onDestroy()` | Instrumentation is not an Activity. |
| Existing 141 classes | **Do not implement them in v1** | Catalogs name `ColdLaunchPerfTest`, `PostOtaRearCaptureTest`, etc. v1 exposes **9 generic ops**. Python maps suite steps → these 9. Thin aliases come in Phase 4 if codegen still emits old class names. |

**Reference used:** [`Camera2TakeAPhotoController.kt`](https://github.com/android/camera-samples/blob/main/samples/camera2-takeaphoto/src/main/java/com/android/camera2/takeaphoto/Camera2TakeAPhotoController.kt) — JPEG `ImageReader`, `TEMPLATE_PREVIEW` repeating request, `TEMPLATE_STILL_CAPTURE` + `session.capture()`, AF `CONTINUOUS_PICTURE`, close reader on camera close. **Strip:** Compose, `BaseCamera2Controller`, fixed `1920x1080`, `onPhotoCaptured` callback. **Keep:** open → session(preview + reader) → repeating → still capture → save → JSON.

Jetpack Camera App tests are a **negative** reference for this APK: they drive Compose/UiAutomator. We take only isolation, permission grant, and media cleanup ideas — no UI.

---

## 1. Project structure

```
cameratest-harness/
├── settings.gradle.kts
├── build.gradle.kts
├── gradle.properties
├── gradle/wrapper/gradle-wrapper.properties
├── gradlew
├── gradlew.bat
├── app/
│   ├── build.gradle.kts
│   └── src/main/
│       ├── AndroidManifest.xml
│       └── kotlin/com/example/cameratest/
│           ├── BaseCamera2Test.kt
│           ├── JsonResult.kt
│           ├── ArgParser.kt
│           ├── HeadlessSurfaces.kt
│           ├── ThermalGuard.kt
│           ├── PhotoCaptureTest.kt
│           ├── VideoRecordTest.kt
│           ├── CameraSwitchTest.kt
│           ├── RepeatedPhotoStressTest.kt
│           ├── ImageInspectTest.kt
│           ├── VideoInspectTest.kt
│           ├── ResolutionMatrixTest.kt
│           ├── DigitalZoomTest.kt
│           └── CapabilityTest.kt
└── README.md
```

`app` is a **self-instrumenting** APK: `applicationId ==` instrumentation package `com.example.cameratest`. There is no separate app-under-test.

---

## 2. Gradle build configuration

**`gradle.properties`**

```properties
org.gradle.jvmargs=-Xmx2g
android.useAndroidX=true
android.nonTransitiveRClass=true
kotlin.code.style=official
```

**Root `build.gradle.kts`**

```kotlin
plugins {
    id("com.android.application") version "8.7.2" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
}
```

**`settings.gradle.kts`** — standard `google()` + `mavenCentral()` plugin/dependency repos; `include(":app")`.

**`app/build.gradle.kts`**

```kotlin
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.example.cameratest"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.example.cameratest"
        minSdk = 30
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"
        // Studio-only. Contract path does not use this runner.
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        debug {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    // Optional Studio debug only — not required on the am instrument contract path
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:rules:1.6.1")
    // No CameraX. No Compose. No org.json extra — use android's JSONObject.
}
```

`testApplicationId` is **not** set separately. For a harness APK, `applicationId = "com.example.cameratest"` is what Python must install and invoke. Setting `testApplicationId` only matters if tests live in `androidTest` against another app.

**`AndroidManifest.xml` (contract)**

```xml
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.CAMERA" />
    <uses-permission android:name="android.permission.RECORD_AUDIO" />
    <uses-feature android:name="android.hardware.camera.any" android:required="true" />

    <application
        android:label="CameraTestHarness"
        android:allowBackup="false"
        android:supportsRtl="true">
        <activity
            android:name=".HarnessActivity"
            android:exported="true"
            android:theme="@android:style/Theme.Translucent.NoTitleBar" />
    </application>

    <instrumentation android:name=".PhotoCaptureTest" android:targetPackage="com.example.cameratest" />
    <instrumentation android:name=".VideoRecordTest" android:targetPackage="com.example.cameratest" />
    <instrumentation android:name=".CameraSwitchTest" android:targetPackage="com.example.cameratest" />
    <instrumentation android:name=".RepeatedPhotoStressTest" android:targetPackage="com.example.cameratest" />
    <instrumentation android:name=".ImageInspectTest" android:targetPackage="com.example.cameratest" />
    <instrumentation android:name=".VideoInspectTest" android:targetPackage="com.example.cameratest" />
    <instrumentation android:name=".ResolutionMatrixTest" android:targetPackage="com.example.cameratest" />
    <instrumentation android:name=".DigitalZoomTest" android:targetPackage="com.example.cameratest" />
    <instrumentation android:name=".CapabilityTest" android:targetPackage="com.example.cameratest" />
</manifest>
```

A 1×1 translucent `HarnessActivity` is allowed only as a **token** if a HAL refuses a fully headless session. It has no buttons. Prefer `SurfaceTexture` first.

---

## 3. `BaseCamera2Test` design

```kotlin
open class BaseCamera2Test : Instrumentation() {

    protected lateinit var bgThread: HandlerThread
    protected lateinit var bgHandler: Handler
    protected var camera: CameraDevice? = null
    protected var session: CameraCaptureSession? = null
    protected var jpegReader: ImageReader? = null
    protected var previewSurface: Surface? = null
    protected var previewTexture: SurfaceTexture? = null

    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        grantRuntime("android.permission.CAMERA")
        grantRuntime("android.permission.RECORD_AUDIO")
        start()
    }

    override fun onStart() {
        super.onStart()
        bgThread = HandlerThread("camera-harness-bg").also { it.start() }
        bgHandler = Handler(bgThread.looper)
        try {
            runOperation(arguments ?: Bundle.EMPTY)
        } catch (t: Throwable) {
            emitFail(t.message ?: t.javaClass.simpleName)
        } finally {
            releaseCamera()
            bgThread.quitSafely()
            finish(Activity.RESULT_OK, Bundle.EMPTY)
        }
    }

    protected open fun runOperation(args: Bundle) = Unit
}
```

**Parameter reading** (`ArgParser.kt`)

```kotlin
fun Bundle.reqString(key: String): String =
    getString(key)?.takeIf { it.isNotBlank() }
        ?: throw Skip("missing required arg: $key")

fun Bundle.optInt(key: String, default: Int) =
    getString(key)?.toIntOrNull() ?: getInt(key, default)

fun parseWxH(resolution: String): Pair<Int, Int> {
    val parts = resolution.lowercase().split("x")
    require(parts.size == 2) { "resolution must be WIDTHxHEIGHT, got $resolution" }
    return parts[0].toInt() to parts[1].toInt()
}
```

Missing required args → `{"result":"SKIPPED","error":"missing required arg: camera_id"}`.  
That is **not** an SLA judgment; the operation cannot start.

**JSON** (`JsonResult.kt`) — `android.util.JsonWriter` or `JSONObject`; **one line**, no pretty print, drop nulls.

```kotlin
protected fun emitResult(fields: Map<String, Any?>) {
    val obj = JSONObject()
    fields.forEach { (k, v) -> if (v != null) obj.put(k, v) }
    println(obj.toString()) // the only stdout contract line
}

protected fun emitPass(extra: Map<String, Any?> = emptyMap()) =
    emitResult(mapOf("result" to "PASS") + extra)

protected fun emitFail(error: String) =
    emitResult(mapOf("result" to "FAIL", "error" to error))

protected fun emitSkip(error: String) =
    emitResult(mapOf("result" to "SKIPPED", "error" to error))
```

Print **exactly one** of PASS / FAIL / SKIPPED. Logcat uses `Log.*`, never extra `println`.

**Open camera (timeout, never hang)**

```kotlin
protected fun openCamera(cameraId: String, timeoutSec: Long = 10): CameraDevice {
    val mgr = context.getSystemService(CameraManager::class.java)
    val latch = CountDownLatch(1)
    var opened: CameraDevice? = null
    var error: String? = null
    mgr.openCamera(cameraId, object : CameraDevice.StateCallback() {
        override fun onOpened(d: CameraDevice) { opened = d; latch.countDown() }
        override fun onDisconnected(d: CameraDevice) { error = "disconnected"; d.close(); latch.countDown() }
        override fun onError(d: CameraDevice, e: Int) { error = "open_error_$e"; d.close(); latch.countDown() }
    }, bgHandler)
    if (!latch.await(timeoutSec, TimeUnit.SECONDS)) throw IllegalStateException("openCamera timeout")
    return opened ?: throw IllegalStateException(error ?: "openCamera failed")
}
```

**Headless session** — same shape as the sample (`preview Surface` + `imageReader.surface`):

```kotlin
previewTexture = SurfaceTexture(false).apply { setDefaultBufferSize(w, h) }
previewSurface = Surface(previewTexture)
jpegReader = ImageReader.newInstance(stillW, stillH, imageFormat, /*maxImages*/ 2)
createSession(camera, listOf(previewSurface!!, jpegReader!!.surface), timeoutSec = 10)
```

`createCaptureSession` (or `SessionConfiguration` on API 30+) also uses a `CountDownLatch`.

**Repeating preview** — from the sample, without Compose:

```kotlin
val preview = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
    addTarget(previewSurface!!)
    set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
}.build()
session.setRepeatingRequest(preview, null, bgHandler)
```

**Safe teardown**

```kotlin
protected fun releaseCamera() {
    runCatching { session?.stopRepeating() }
    runCatching { session?.close() }
    runCatching { camera?.close() }
    runCatching { jpegReader?.close() }
    runCatching { previewSurface?.release() }
    runCatching { previewTexture?.release() }
    session = null; camera = null; jpegReader = null
}
```

**Thermal** (`ThermalGuard.kt`): `PowerManager.currentThermalStatus >= THERMAL_STATUS_SEVERE` → stop loops, set `thermal_abort=true`. Do not decide DUT pass/fail.

---

## 4. `PhotoCaptureTest` — full design

**Signature:** `class PhotoCaptureTest : BaseCamera2Test()`

**Args**

| Arg | Required | Example |
|-----|----------|---------|
| `camera_id` | yes | `0` |
| `resolution` | yes | `4032x3024` |
| `format` | no | `JPEG` (default). Map `JPEG`→`ImageFormat.JPEG`, `YUV`→`YUV_420_888` |
| `output_dir` | no | default app files `CameraTest/` |

**Core flow** (sample `takePicture()` + save + JSON)

```kotlin
override fun runOperation(args: Bundle) {
    val cameraId = args.reqString("camera_id")
    val (w, h) = parseWxH(args.reqString("resolution"))
    val format = parseImageFormat(args.getString("format") ?: "JPEG")
    val outDir = resolveOutDir(args.getString("output_dir"))

    assertSizeSupported(cameraId, w, h, format) // else SKIPPED

    val device = openCamera(cameraId)
    prepareHeadlessSession(device, previewSizeFor(w, h), w, h, format)

    val imageLatch = CountDownLatch(1)
    var saved: File? = null
    var decodeW = 0; var decodeH = 0
    jpegReader!!.setOnImageAvailableListener({ reader ->
        reader.acquireLatestImage()?.use { image ->
            val file = File(outDir, "photo_${System.currentTimeMillis()}.jpg")
            writeJpeg(image, file)
            BitmapFactory.decodeFile(file.absolutePath, BitmapFactory.Options().apply {
                inJustDecodeBounds = true
            })
            decodeW = BitmapFactory.Options().outWidth // use the same Options instance
            saved = file
        }
        imageLatch.countDown()
    }, bgHandler)

    val t0 = System.nanoTime()
    val still = device.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
        addTarget(jpegReader!!.surface)
        set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
        set(CaptureRequest.JPEG_ORIENTATION, jpegOrientation(cameraId))
    }
    runCatching { session!!.stopRepeating() }
    session!!.capture(still.build(), object : CameraCaptureSession.CaptureCallback() {
        override fun onCaptureFailed(...) { /* set error; countDown */ }
    }, bgHandler)

    if (!imageLatch.await(15, TimeUnit.SECONDS)) {
        emitFail("image callback timeout"); return
    }
    val latencyMs = (System.nanoTime() - t0) / 1_000_000
    val file = saved ?: run { emitFail("no image saved"); return }
    emitPass(
        mapOf(
            "image_path" to file.absolutePath,
            "width" to decodeW,
            "height" to decodeH,
            "format" to (args.getString("format") ?: "JPEG"),
            "latency_ms" to latencyMs,
        )
    )
}
```

**From the sample — keep:** `ImageReader.newInstance` + listener, `TEMPLATE_STILL_CAPTURE`, `addTarget(reader.surface)`, `session.capture`, AF mode, close reader on teardown.  
**From the sample — drop:** `onPhotoCaptured`, fixed `PREVIEW_WIDTH/HEIGHT`, Compose `remember*`, inherit `BaseCamera2Controller`.

**Host mapping:** `TC_CAM_FUNC_001` / `PostOtaRearCaptureTest` become this class + args. Host checks file exists and resolution vs SLA — harness does not.

---

## 5. `VideoRecordTest`

**Signature:** `class VideoRecordTest : BaseCamera2Test()`

**Args:** `camera_id`, `resolution` (`1920x1080`), `fps` (default 30), `duration_sec` (required), `output_dir`, optional `audio` (`true`/`false`).

**Logic (Camera2 + `MediaRecorder`, not CameraX Recorder)**

```kotlin
val recorder = MediaRecorder(context)
val out = File(outDir, "video_${System.currentTimeMillis()}.mp4")
recorder.apply {
    setAudioSource(MediaRecorder.AudioSource.MIC) // skip if audio=false
    setVideoSource(MediaRecorder.VideoSource.SURFACE)
    setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
    setOutputFile(out.absolutePath)
    setVideoEncoder(MediaRecorder.VideoEncoder.H264)
    setVideoSize(w, h)
    setVideoFrameRate(fps)
    setVideoEncodingBitRate(bitRateFor(w, h, fps))
    prepare()
}
val recSurface = recorder.surface
openCamera → session(listOf(previewSurface, recSurface))
repeating TEMPLATE_RECORD targeting recSurface (+ preview)

val t0 = System.nanoTime()
recorder.start()
if (!CountDownLatch(1).await(durationSec + 5L, SECONDS)) { /* stop anyway */ }
// Better: bgHandler.postDelayed({ stopLatch.countDown() }, durationSec * 1000L)
recorder.stop(); recorder.reset(); recorder.release()
val durationMs = (System.nanoTime() - t0) / 1_000_000
if (!out.exists() || out.length() == 0L) emitFail("empty video")
else emitPass(mapOf("video_path" to out.absolutePath, "width" to w, "height" to h,
                    "fps" to fps.toFloat(), "duration_ms" to durationMs))
```

If `CamcorderProfile.hasProfile` matches the size, use it; otherwise set size/fps manually. Unsupported size → `SKIPPED`, not `FAIL`.

---

## 6. `RepeatedPhotoStressTest`

**Signature:** `class RepeatedPhotoStressTest : BaseCamera2Test()`

**Args:** `camera_id`, `count` (default 10), `mode` (`rapid` \| `settled`), optional `resolution`.

**Logic**

- Resolve size: arg, else largest JPEG from `SCALER_STREAM_CONFIGURATION_MAP`.
- Loop `i in 1..count`:
  - `mode=rapid`: keep session open; capture; `acquireLatestImage`; close `Image`; do not recreate the camera every shot (faster, still close the `Image`).
  - `mode=settled`: close session/device every N shots (e.g. every 1–5) to flush handles — use this if leak hunting.
- After each capture, increment `completed` or `failures`.
- Every 50 iterations: `ThermalGuard.isAbort()` → set `thermal_abort=true`, break.
- Timeouts per shot: 10s. Do not hang the whole `count`.
- **Harness `result`:** `PASS` if the loop finished or aborted thermally **without an unhandled crash**. `failures` is a count, not an SLA. Host maps `failures` / `metric_value` to catalog SLAs.

```json
{"result":"PASS","metric_value":500,"failures":0,"thermal_abort":false}
```

Do not parse logcat inside the APK as a judge. Optional: `CameraDevice.StateCallback.onError` increments `failures`.

---

## 7. Remaining operation classes (signature + core calls)

### `CameraSwitchTest`

Args: `source_camera`, `target_camera`, `iterations`.

Per iteration: open source → session → 3 repeating frames (latch on preview `ImageReader`) → close → open target → same → close. Record per-switch `System.nanoTime()` deltas; return `latency_ms` as last or mean (document: **mean**).  
Return: `completed_iterations`, `failed_iterations`, `latency_ms`.

### `ImageInspectTest`

No camera. Args: `image_path`.  
`BitmapFactory.decodeFile(..., inJustDecodeBounds=true)` + optional `ExifInterface`.  
Missing file → `FAIL`. Return `width`, `height`, `format`.

### `VideoInspectTest`

No camera. Args: `video_path`.  
`MediaMetadataRetriever` → `METADATA_KEY_VIDEO_WIDTH/HEIGHT/DURATION`, frame-rate if present.  
Return `width`, `height`, `fps`, `duration_ms`.

### `ResolutionMatrixTest`

Args: `camera_id`, `resolutions` (`4032x3024,1920x1080` or empty = all JPEG sizes), `format`.  
For each size: same capture as `PhotoCaptureTest` (reuse a package-private `captureStill()`).  
Return `tested`, `passed`, `failed` (**passed = file written and bounds decode**, not SLA). One JSON at the end. Per-size timeout.

### `DigitalZoomTest`

Args: `camera_id`, `min_zoom`, `max_zoom`, `steps`.  
Clamp to `CONTROL_ZOOM_RATIO_RANGE` (API 30+) or crop region.  
Each step: `CaptureRequest.CONTROL_ZOOM_RATIO` + still or one preview frame.  
Compare requested vs `TotalCaptureResult.CONTROL_ZOOM_RATIO`.  
Return `requested_steps`, `applied_steps`, `failed_steps`. Unsupported zoom → `SKIPPED`.

### `CapabilityTest`

Args: optional `camera_id`.  
`CameraManager.cameraIdList` + `getCameraCharacteristics`.  
Emit JSON (still one line): ids, facing, JPEG/YUV sizes, FPS ranges, AF modes, zoom range, flash, logical/physical ids.  
This is the device-side twin of host `dumpsys media.camera`. No PASS threshold.

---

## 8. Build and verification workflow

```bash
cd cameratest-harness
./gradlew :app:assembleDebug

adb install -r -g app/build/outputs/apk/debug/app-debug.apk
adb shell pm grant com.example.cameratest android.permission.CAMERA
adb shell pm grant com.example.cameratest android.permission.RECORD_AUDIO
```

**Contract invocations (must work)**

```bash
adb shell am instrument -w \
  -e camera_id 0 -e resolution 1920x1080 -e format JPEG \
  com.example.cameratest/.PhotoCaptureTest

adb shell am instrument -w \
  -e camera_id 0 -e count 10 -e mode rapid \
  com.example.cameratest/.RepeatedPhotoStressTest

adb shell am instrument -w com.example.cameratest/.CapabilityTest

adb shell am instrument -w \
  -e camera_id 0 -e resolution 1920x1080 -e fps 30 -e duration_sec 5 \
  com.example.cameratest/.VideoRecordTest
```

**Pass bar for a command:** process exits; **exactly one** JSON line on instrumentation stdout; `result` is `PASS`, `FAIL`, or `SKIPPED`; camera is closed (`dumpsys media.camera` shows no leaked client after a few seconds).

**Host parse sketch (later, not this APK)**

```
stdout → last line matching \{.*\} → json.loads → require "result"
```

---

## 9. Four-week roadmap

| Phase | Week | Deliverable | Exit criteria |
|--------|------|-------------|---------------|
| **1** | 1 | Gradle skeleton, manifest instrumentations, `JsonResult`, `BaseCamera2Test`, `CapabilityTest`, `PhotoCaptureTest` | `CapabilityTest` lists cameras; one JPEG file + JSON on a DUT (or emulator with virtual camera) |
| **2** | 2 | `VideoRecordTest`, `CameraSwitchTest`, `RepeatedPhotoStressTest` + thermal abort | 5s 1080p file; 10 switches; 10 rapid shots; severe thermal sets `thermal_abort` |
| **3** | 3 | Inspect + matrix + zoom | Inspect works on Phase 1/2 artifacts; matrix over 3 sizes; zoom sweep clamped to HAL range |
| **4** | 4 | Python adapter (this PC or host scripts): map `TC_CAM_FUNC_001`…`TC_CAM_STRESS_001` → the 9 classes | One functional capture + one stress case end-to-end: host fills args, parses JSON, applies **host** SLAs, pulls evidence |

Phase 4 does **not** implement 141 Kotlin classes. It implements a **table**:

| Catalog class / case | Harness class | Args |
|----------------------|---------------|------|
| `TC_CAM_FUNC_001` | `PhotoCaptureTest` | `camera_id`, `resolution`, `format` |
| `TC_CAM_STRESS_001` | `RepeatedPhotoStressTest` | `count=500`, `mode=rapid` |
| `PostOtaRearCaptureTest` | `PhotoCaptureTest` | same |
| `ColdLaunchPerfTest` | **not v1** (needs process-cold + TTFF) | backlog |
| `PowerPreviewTest` | **not v1** (lab power) | backlog |

---

## 10. Risks and mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Headless HAL rejects session without a real viewfinder | Photo/video `FAIL` on some OEMs | Fallback: translucent `HarnessActivity` + `SurfaceView`; still no clicks |
| Scoped storage / `DCIM` write fails | Empty `image_path` | App files dir + return absolute path; host `adb pull` |
| `camera_id` as int | Logical/OEM IDs break | String IDs only |
| `AndroidJUnitRunner` vs `pkg/.Class` mismatch | Python catalogs miss the APK | Manifest `<instrumentation android:name=".<Op>"/>`; runner is Studio-only |
| One-class-per-catalog (141) vs 9 ops | Phase 4 looks “incomplete” | Document mapping; add aliases only if codegen cannot change |
| `session.capture` without AF converge | Black/blurred frames | Continuous AF + short preview warm-up (N frames) before still; still no SLA on sharpness |
| ImageReader backlog / `acquireLatestImage` vs `acquireNextImage` | Stress leaks or stalls | `maxImages=2`, always `image.close()`, drain reader between shots (Camera2Basic pattern) |
| Video `MediaRecorder.stop` on short clips | `RuntimeException` | Minimum duration ~1s; `FAIL` with error string, never swallow |
| Thermal false abort | Stress ends early | Use `PowerManager` thresholds; host interprets `thermal_abort` |
| Multiple JSON lines from AndroidX runner | Host parse breaks | Contract path avoids JUnit runner; only `emitResult` uses `println` |
| Emulator ≠ DUT | False confidence | Phase 1 may use emulator; Phase 2+ needs a physical Android 11+ phone |
| `RECORD_AUDIO` on denied mic | Video `FAIL` | `audio=false` default for CI; grant in verify script |
| Concurrent tests | Camera in use | Host serializes; harness `FAIL` `error=camera_in_use` |

---

## 11. Non-negotiables (implementation checklist)

1. No `Intent.ACTION_IMAGE_CAPTURE` / OEM camera package.  
2. No UiAutomator clicks, no Compose, no CameraX.  
3. No hard-coded 1920×1080 (sample constant stays in Google’s app, not here).  
4. Every latch `await` has a timeout → `FAIL` JSON.  
5. Every exception → `FAIL` JSON with `error`.  
6. Always close session, device, reader, recorder, surfaces, `HandlerThread`.  
7. One stdout JSON object; `result` ∈ `PASS|FAIL|SKIPPED`.  
8. No SLA numbers in Kotlin.

---

**Bottom line:** Build a self-instrumenting `com.example.cameratest` APK whose nine Instrumentation classes are generic Camera2 operations. Lift lifecycle from `Camera2TakeAPhotoController.takePicture()`, delete UI, parameterize size/format/path, and emit one JSON line. Python remains the judge; this APK is only the hands on the camera.

This is the plan only — no project files or code were added to the repo. Say when you want Phase 1 scaffolded.

---

**User**

what are the thngs we need to nstall for ths?

---

**Cursor**

I’ll check what’s already on this PC, then list only what you still need to install for the Camera harness.

Here is what this PC already has, and what you still need to install to **build and run** the Camera harness.

---

## Already on this PC

| Thing | Status |
|--------|--------|
| **JDK 17** (`openjdk 17.0.20`) | Enough. Do not install another Java unless you want Temurin explicitly. |
| **Python 3.10.12** | Matches the suite (`>=3.10,<3.13`). |
| **adb** `37.0.1` at `/home/tcs/platform-tools/adb` | Enough for install/run. |
| **git, unzip, curl, wget** | Enough. |

**Not present:** Android Studio, Gradle, `sdkmanager`, Android compile SDK / build-tools, pytest/adbutils, a connected phone.

`/usr/lib/android-sdk` is incomplete (old platform-tools only). Treat it as unused. Point a new SDK at something like `~/Android/Sdk`.

---

## Must install to **build** the APK (Phase 1)

You need an **Android SDK**, not a system `gradle` package. The project will use the **Gradle Wrapper** (`./gradlew`).

### 1. Android command-line tools (or Android Studio)

**Easier path:** install [Android Studio](https://developer.android.com/studio) (Linux). First-run wizard installs the SDK.

**CLI-only path** (no Studio):

1. Download **Command line tools only** (Linux) from the same Android Studio page.
2. Unpack to `~/Android/Sdk/cmdline-tools/latest/`.
3. Set:

```bash
export ANDROID_HOME="$HOME/Android/Sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$HOME/platform-tools:$PATH"
```

4. Install the packages the plan uses (`compileSdk` / `targetSdk` **34**, `minSdk` **30**):

```bash
sdkmanager --sdk_root="$ANDROID_HOME" \
  "platform-tools" \
  "platforms;android-34" \
  "build-tools;34.0.0"
```

Accept licenses:

```bash
sdkmanager --sdk_root="$ANDROID_HOME" --licenses
```

You do **not** need to `apt install gradle`. Wrapper downloads Gradle 8.x on first `./gradlew`.

You do **not** install Kotlin separately. The Android Gradle Plugin pulls it.

### 2. Create `local.properties` later (when the project exists)

```
sdk.dir=/home/tcs/Android/Sdk
```

---

## Must have to **run** the APK on a device

| Thing | Why |
|--------|-----|
| **Physical Android phone, API 30+** (Android 11+) | Camera2 + thermal + video. Emulator camera is only a Phase 1 smoke test. |
| **USB cable** + **USB debugging** (Developer options) | `adb devices` must show the phone. Right now the list is **empty**. |
| **adb udev access** | If the phone shows `unauthorized` or missing: unlock, accept the RSA prompt, or add a udev rule. |

On the phone, also allow:

- Camera (and mic if you test video with audio)
- Stay awake while charging (for long stress runs)

Install command once the APK exists:

```bash
adb install -r -g app/build/outputs/apk/debug/app-debug.apk
```

`-g` grants runtime permissions at install.

---

## Install later for **Python host** (Phase 4, not needed to compile the APK)

```bash
python3 -m pip install --user "pytest>=7" "adbutils>=2" "uiautomator2>=3"
```

Optional: a venv in the harness/host folder so packages stay isolated.

`uiautomator2` is in the suite metadata. The v1 harness is headless Camera2, so **pytest + adbutils** is enough to call `am instrument` and parse JSON.

---

## Do **not** install

- CameraX / Compose libraries (keep the APK on Camera2)
- System Gradle from `apt` (too old)
- A second JDK 21 unless Studio insists (17 is correct for this plan)
- The other PC’s Electron/FastAPI stack — not required here

---

## Minimum order

1. **Android SDK 34 + build-tools 34** (Studio **or** `sdkmanager`)  
2. **Set `ANDROID_HOME`**  
3. Plug in a phone and confirm `adb devices` shows it  
4. After the project exists: `./gradlew :app:assembleDebug` then `adb install -r -g …`  
5. Phase 4: `pip install pytest adbutils`

If you want, next step can be the exact download/unpack commands for the command-line tools on this Ubuntu machine (still no harness code until you ask).

---

**User**

can we mplement ths wthout a physcal phone?

---

**Cursor**

Yes — you can **build and develop** the harness without a physical phone. You cannot **fully prove** Camera behavior without one.

## What works without a phone

| Work | On this PC only |
|------|------------------|
| Gradle project, Kotlin classes, manifest, JSON contract | Yes |
| Compile `assembleDebug` | Yes (needs Android SDK 34, not a phone) |
| Unit-test arg parsing, JSON emit, resolution parse, zoom step math | Yes (JVM) |
| Run the APK on an **Android Emulator** | Yes, for a thin smoke path |

So Phase 1 (skeleton + `CapabilityTest` + `PhotoCaptureTest`) can be implemented and smoke-tested with an emulator **or** even just compile + host-side JSON tests.

## What the emulator can do

Use an AVD with a virtual camera (webcam or emulated scene):

- `adb install -g`
- `am instrument …/.CapabilityTest` — usually lists camera `"0"` / `"1"`
- `PhotoCaptureTest` — often returns a JPEG (synthetic frames)
- `ImageInspectTest` / `VideoInspectTest` — no camera needed (files only)
- `ResolutionMatrixTest` — maybe a few small sizes
- Short `VideoRecordTest` — sometimes works, often flaky

Create an AVD after SDK install, for example:

- Image: **Android 14 (API 34)** x86_64 / Google APIs  
- Enable a back camera in AVD settings (Webcam0 or `Emulated`)

That is enough to check: one JSON line, no hang, files written, teardown.

## What the emulator cannot stand in for

These need a real HAL, sensors, or OEM policy. Treat emulator results as **non-evidence**:

- Stress / thermal abort (`PowerManager` thermal is not a phone)
- Power/battery (`AUTO_LAB`)
- Flash, OIS, real zoom, ultrawide / tele / logical multi-camera
- AF quality, shutter/TTFF SLAs
- Permission / privacy indicator / lock screen
- OTA golden compare
- Concurrent camera, storage-full, incoming call
- Camera2 quirks (headless session rejected, stream configs)

The catalogs assume a **DUT**. An emulator `PASS` only means “the harness API ran,” not “the device camera is valid.”

## Practical way to work on this PC

1. **No device at all:** write and compile the APK; test `JsonResult` / `ArgParser` on the JVM.  
2. **Emulator:** verify the 9 operations’ **contract** (args in, one JSON out, no leak/hang).  
3. **Phone later:** run the same commands on hardware before you trust Camera results.

Host Python (`pytest` + `adbutils`) also works against an emulator: `adb` is the same.

**Bottom line:** implement without a physical phone — use SDK + emulator (or compile-only) for the harness. Bring a phone only when you need real Camera2 / suite sign-off.

