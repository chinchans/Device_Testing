package com.example.cameratest

import android.Manifest
import android.accessibilityservice.AccessibilityServiceInfo
import android.app.ActivityManager
import android.app.KeyguardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.hardware.SensorPrivacyManager
import android.hardware.camera2.CameraAccessException
import android.os.Build
import android.os.PowerManager
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * Camera security / privacy probes. The harness reports machine-verifiable evidence; host
 * steps (pm grant/revoke/clear, reboot, OTA, privacy toggle) happen between phases.
 *
 * scenario: grant | deny | revoke | reset | one_time | while_in_use | background |
 *   privacy_indicator | privacy_toggle_block | privacy_toggle_restore | unauthorized_app |
 *   permission_isolation | resource_isolation | locked_device | secure_lockscreen | audit |
 *   persistence_reboot | post_ota | data_reset | helper_probe (runs inside helper APKs)
 * Common args: camera_id, phase, hold_sec, observation_sec, unauthorized_package,
 * secondary_package, audit_window_sec, indicator_confirmed, toggle_via_shell.
 *
 * Output order: result, metric_value (1 = enforced), unauthorized_access_count, crash_count.
 */
@RunWith(AndroidJUnit4::class)
open class SecurityProbeTest : HarnessTest() {

    class AccessProbe(
        val reason: String,
        val openMs: Double?,
        val frames: Int,
        val meanLuma: Double,
        val darkSamples: Int,
        val lumaSamples: Int,
        val disconnects: Int,
        val error: String?,
    ) {
        val granted: Boolean get() = reason == AccessReason.GRANTED

        /** Non-blank image data actually reached this app. */
        val imageData: Boolean get() = frames > 0 && lumaSamples > 0 && darkSamples < lumaSamples

        fun fields(prefix: String): Array<Pair<String, Any?>> = arrayOf(
            "${prefix}access" to reason,
            "${prefix}open_ms" to openMs,
            "${prefix}frames" to frames,
            "${prefix}mean_luma" to meanLuma.takeIf { it >= 0 },
            "${prefix}blank_frames" to (lumaSamples > 0 && darkSamples == lumaSamples),
            "${prefix}image_data" to imageData,
            "${prefix}error" to error,
        )
    }

    private var health: SystemHealthMonitor? = null
    private lateinit var scenario: String
    private lateinit var cameraId: String

    @Test
    fun security() {
        scenario = optString("scenario", "deny").lowercase()
        if (scenario != "helper_probe") health = SystemHealthMonitor(::shell)
        cameraId = cameraArg() ?: return report("NOT_APPLICABLE", 0, 0, "reason" to "no rear camera")
        try {
            when (scenario) {
                "grant" -> grant()
                "deny" -> deny()
                "revoke", "reset" -> phased()
                "one_time" -> oneTime()
                "while_in_use" -> whileInUse()
                "background" -> background()
                "privacy_indicator" -> privacyIndicator()
                "privacy_toggle_block" -> privacyToggle(expectBlocked = true)
                "privacy_toggle_restore" -> privacyToggle(expectBlocked = false)
                "unauthorized_app" -> unauthorizedApp()
                "permission_isolation" -> permissionIsolation()
                "resource_isolation" -> resourceIsolation()
                "locked_device" -> lockedDevice()
                "secure_lockscreen" -> secureLockscreen()
                "audit" -> audit()
                "persistence_reboot" -> persistenceReboot()
                "post_ota" -> postOta()
                "data_reset" -> dataReset()
                "helper_probe" -> helperProbe()
                else -> emitFail("unknown scenario: $scenario")
            }
        } catch (e: Exception) {
            report("FAIL", 0, 0, "error" to describe(e))
        } finally {
            closeStream()
        }
    }

    // ------------------------------------------------------------------ plumbing

    private fun crashCount(): Int {
        val m = health?.fields(harnessPackages())?.toMap() ?: return 0
        return ((m["app_crash_count"] as? Int) ?: 0) + ((m["anr_count"] as? Int) ?: 0) +
            if (m["cameraserver_restarted"] == true) 1 else 0
    }

    private fun report(result: String, metric: Int, unauthorized: Int, vararg extra: Pair<String, Any?>) {
        emitSecurity(
            result,
            metric,
            unauthorized,
            crashCount(),
            "scenario" to scenario,
            "phase" to requireString("phase"),
            "package" to appContext.packageName,
            "permission_granted" to hasCameraPermission(),
            "camera_id" to if (::cameraId.isInitialized) cameraId else null,
            "sdk_int" to Build.VERSION.SDK_INT,
            *extra,
        )
    }

    private fun verdict(enforced: Boolean, unauthorized: Int, vararg extra: Pair<String, Any?>) =
        report(if (enforced && unauthorized == 0) "PASS" else "FAIL", if (enforced) 1 else 0, unauthorized, *extra)

    private fun blocked(reason: String, vararg extra: Pair<String, Any?>) =
        report("BLOCKED_PRECONDITION", 0, 0, "reason" to reason, *extra)

    protected fun probeAccess(id: String = cameraId, holdMs: Long = 1500, openTimeoutSec: Long = 15): AccessProbe {
        val disconnectsBefore = cameraErrors.disconnectCount
        val t0 = SystemClock.elapsedRealtimeNanos()
        try {
            openCameraTracked(id, openTimeoutSec)
        } catch (e: CameraOpenException) {
            closeStream()
            return AccessProbe(e.reason, null, 0, -1.0, 0, 0, 0, e.message)
        } catch (e: Exception) {
            closeStream()
            return AccessProbe(AccessReason.ERROR, null, 0, -1.0, 0, 0, 0, describe(e))
        }
        val openMs = (SystemClock.elapsedRealtimeNanos() - t0) / 1e6
        return try {
            val s = createSink(id)
            startStream(cameraDevice!!, s)
            s.awaitFirstFrame(3000)
            if (holdMs > 0) Thread.sleep(holdMs)
            AccessProbe(
                AccessReason.GRANTED, openMs, s.frameCount(), s.meanLuma(), s.darkSampleCount(),
                s.lumaSampleCount(), cameraErrors.disconnectCount - disconnectsBefore, null,
            )
        } catch (e: CameraAccessException) {
            val s = sink
            AccessProbe(
                reasonForAccessException(e), openMs, s?.frameCount() ?: 0, s?.meanLuma() ?: -1.0,
                s?.darkSampleCount() ?: 0, s?.lumaSampleCount() ?: 0, 0, describe(e),
            )
        } catch (e: Exception) {
            val s = sink
            AccessProbe(
                AccessReason.GRANTED, openMs, s?.frameCount() ?: 0, s?.meanLuma() ?: -1.0,
                s?.darkSampleCount() ?: 0, s?.lumaSampleCount() ?: 0, 0, describe(e),
            )
        } finally {
            closeStream()
        }
    }

    private fun appOps(pkg: String = appContext.packageName): String =
        try {
            shell("appops get $pkg CAMERA").trim().lineSequence().firstOrNull { it.contains("CAMERA") } ?: ""
        } catch (_: Exception) {
            ""
        }

    private fun processImportance(): Int {
        val info = ActivityManager.RunningAppProcessInfo()
        ActivityManager.getMyMemoryState(info)
        return info.importance
    }

    private fun inForegroundState(): Boolean =
        processImportance() <= ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND_SERVICE

    private fun grantSelf() {
        uiAutomation().grantRuntimePermission(appContext.packageName, Manifest.permission.CAMERA)
        waitUntil(optLong("permission_timeout_sec", 15) * 1000) { hasCameraPermission() }
    }

    private fun runHelper(pkg: String, args: Map<String, String>): JSONObject? =
        runHelperInstrumentation(pkg, SecurityProbeTest::class.java.name, args)

    private fun helperFields(prefix: String, j: JSONObject): Array<Pair<String, Any?>> = arrayOf(
        "${prefix}result" to j.optString("result"),
        "${prefix}access" to j.optString("access").ifEmpty { null },
        "${prefix}image_data" to j.optBoolean("image_data", false),
        "${prefix}frames" to j.optInt("frames", 0),
        "${prefix}permission_declared" to j.opt("camera_permission_declared"),
        "${prefix}permission_granted" to j.opt("permission_granted"),
        "${prefix}raw" to j.optString("raw").ifEmpty { null },
    )

    // ------------------------------------------------------------------ permission scenarios

    private fun grant() {
        if (hasCameraPermission()) {
            return blocked("CAMERA already granted; host must run `pm revoke ${appContext.packageName} android.permission.CAMERA` first")
        }
        val before = probeAccess(holdMs = 500)
        grantSelf()
        val after = probeAccess()
        val enforced = !before.granted && !before.imageData && after.granted && after.imageData
        verdict(
            enforced,
            if (before.imageData) 1 else 0,
            *before.fields("before_"),
            *after.fields("after_"),
            "appops_after" to appOps(),
        )
    }

    private fun deny() {
        if (hasCameraPermission()) {
            return blocked("CAMERA is granted; host must revoke it before this scenario")
        }
        val p = probeAccess()
        verdict(!p.granted && !p.imageData, if (p.imageData) 1 else 0, *p.fields(""), "appops" to appOps())
    }

    /** revoke: before → (host pm revoke) → after.  reset: before → (host reset) → after → (host grant) → regrant. */
    private fun phased() {
        val phase = optString("phase", "before").lowercase()
        val expectGranted = phase != "after"
        if (expectGranted && !hasCameraPermission()) return blocked("phase=$phase needs CAMERA granted")
        if (!expectGranted && hasCameraPermission()) return blocked("phase=after but CAMERA is still granted; host step missing")
        val p = probeAccess()
        val ok = if (expectGranted) p.granted && p.imageData else !p.granted && !p.imageData
        verdict(
            ok,
            if (!expectGranted && p.imageData) 1 else 0,
            *p.fields(""),
            "expected" to if (expectGranted) "granted" else "denied",
            "appops" to appOps(),
        )
    }

    private fun oneTimeFlag(): Boolean =
        shell("dumpsys package ${appContext.packageName}").lineSequence()
            .any { it.contains("android.permission.CAMERA:") && it.contains("ONE_TIME") }

    private fun oneTime() {
        val phase = optString("phase", "before").lowercase()
        if (phase == "after") {
            if (hasCameraPermission()) return blocked("CAMERA still granted; one-time grant has not expired yet")
            val p = probeAccess()
            return verdict(!p.granted && !p.imageData, if (p.imageData) 1 else 0, *p.fields(""))
        }
        if (!hasCameraPermission()) {
            if (!bringProbeToForeground()) return blocked("probe screen could not be shown")
            val activity = ProbeActivity.current?.get() ?: return blocked("probe screen not available")
            InstrumentationRegistry.getInstrumentation().runOnMainSync {
                activity.requestPermissions(arrayOf(Manifest.permission.CAMERA), 1)
            }
            val timeout = optLong("grant_timeout_sec", 60) * 1000
            if (!waitUntil(timeout) { hasCameraPermission() }) {
                finishProbe()
                return blocked("tester did not choose 'Only this time' within ${timeout / 1000}s", "manual_step_required" to true)
            }
        }
        val flag = oneTimeFlag()
        val p = probeAccess()
        finishProbe()
        verdict(p.granted && p.imageData && flag, 0, *p.fields(""), "one_time_flag" to flag)
    }

    private fun dataReset() {
        val phase = optString("phase", "after").lowercase()
        val granted = hasCameraPermission()
        val p = probeAccess()
        val consistent = !(p.imageData && !granted)
        val ok = if (phase == "before") granted && p.imageData else consistent
        verdict(ok, if (p.imageData && !granted) 1 else 0, *p.fields(""), "appops" to appOps())
    }

    // ------------------------------------------------------------------ background

    private fun whileInUse() {
        if (!hasCameraPermission()) return blocked("CAMERA must be granted")
        val observationMs = optLong("background_observation_sec", optLong("observation_sec", 30)) * 1000
        if (!bringProbeToForeground()) return blocked("probe screen could not be shown")
        val foreground = probeAccess()

        openAndStream(cameraId)
        val disconnectsBefore = cameraErrors.disconnectCount
        sendHome()
        finishProbe()
        shell("am make-uid-idle ${appContext.packageName}")
        Thread.sleep(2000)
        val importance = processImportance()
        val framesAtStart = sink?.frameCount() ?: 0
        Thread.sleep(observationMs)
        val heldFrames = (sink?.frameCount() ?: 0) - framesAtStart
        val heldLuma = sink?.let { it.lumaSampleCount() > it.darkSampleCount() } ?: false
        val disconnected = cameraErrors.disconnectCount > disconnectsBefore
        closeStream()
        val fresh = probeAccess()

        val evidence = arrayOf(
            *foreground.fields("foreground_"),
            "background_importance" to importance,
            "held_stream_frames_in_background" to heldFrames,
            "held_stream_disconnected" to disconnected,
            *fresh.fields("background_"),
            "appops" to appOps(),
        )
        if (importance <= ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND_SERVICE) {
            return blocked("instrumentation kept the process in a foreground state; background restriction not observable", *evidence)
        }
        val heldLeak = heldFrames > 0 && heldLuma
        val unauthorized = (if (heldLeak) 1 else 0) + (if (fresh.imageData) 1 else 0)
        verdict(foreground.granted && foreground.imageData && !heldLeak && !fresh.imageData, unauthorized, *evidence)
    }

    private fun background() {
        if (!hasCameraPermission()) return blocked("CAMERA must be granted")
        val observationMs = optLong("observation_sec", 30) * 1000
        sendHome()
        finishProbe()
        shell("am make-uid-idle ${appContext.packageName}")
        Thread.sleep(2000)
        val importance = processImportance()
        if (importance <= ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND_SERVICE) {
            return blocked("instrumentation kept the process in a foreground state; background restriction not observable", "importance" to importance)
        }
        var attempts = 0
        var leaks = 0
        val reasons = LinkedHashSet<String>()
        val end = SystemClock.elapsedRealtime() + observationMs
        while (SystemClock.elapsedRealtime() < end) {
            val p = probeAccess(holdMs = 1000)
            attempts++
            reasons += p.reason
            if (p.imageData) leaks++
            Thread.sleep(4000)
        }
        verdict(leaks == 0, leaks, "attempts" to attempts, "access_results" to reasons.joinToString(","), "importance" to importance)
    }

    // ------------------------------------------------------------------ privacy

    private fun privacyChip(timeoutMs: Long): String? {
        val ua = uiAutomation()
        try {
            val info = ua.serviceInfo
            info.flags = info.flags or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS or
                AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS
            ua.serviceInfo = info
        } catch (_: Exception) {
        }
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            for (w in ua.windows) {
                val hit = findChip(w.root ?: continue)
                if (hit != null) return hit
            }
            Thread.sleep(250)
        }
        return null
    }

    private fun findChip(root: AccessibilityNodeInfo): String? {
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue += root
        var visited = 0
        while (queue.isNotEmpty() && visited < 3000) {
            val n = queue.removeFirst()
            visited++
            val id = n.viewIdResourceName ?: ""
            val desc = n.contentDescription?.toString() ?: ""
            if (id.contains("privacy_chip", true) || id.contains("privacy_dot", true) ||
                (id.contains("privacy", true) && desc.contains("camera", true))
            ) {
                return id.ifEmpty { desc }
            }
            for (i in 0 until n.childCount) n.getChild(i)?.let(queue::add)
        }
        return null
    }

    private fun privacyIndicator() {
        if (!hasCameraPermission()) return blocked("CAMERA must be granted")
        bringProbeToForeground()
        openAndStream(cameraId)
        Thread.sleep(1500)
        val ops = appOps()
        val cameraDump = try {
            shell("dumpsys media.camera")
        } catch (_: Exception) {
            ""
        }
        val active = ops.contains("running", true) || cameraDump.contains(appContext.packageName)
        val chip = privacyChip(optLong("indicator_timeout_ms", 5000))
        val frames = sink?.frameCount() ?: 0
        closeStream()
        finishProbe()
        val confirmed = optBool("indicator_confirmed", false)
        val evidence = arrayOf<Pair<String, Any?>>(
            "camera_active_evidence" to active,
            "appops" to ops,
            "frames" to frames,
            "privacy_chip_detected" to (chip != null),
            "privacy_chip_node" to chip,
            "indicator_confirmed" to confirmed,
        )
        when {
            !active -> report("FAIL", 0, 0, "error" to "no machine evidence of active camera use", *evidence)
            chip != null || confirmed -> report("PASS", 1, 0, *evidence)
            else -> blocked("indicator not found automatically; tester must confirm (indicator_confirmed=true)", "manual_confirmation_required" to true, *evidence)
        }
    }

    private fun privacyToggle(expectBlocked: Boolean) {
        if (Build.VERSION.SDK_INT < 31) return report("NOT_APPLICABLE", 0, 0, "reason" to "camera privacy toggle needs Android 12+")
        val spm = appContext.getSystemService(SensorPrivacyManager::class.java)
        if (spm == null || !spm.supportsSensorToggle(SensorPrivacyManager.Sensors.CAMERA)) {
            return report("NOT_APPLICABLE", 0, 0, "reason" to "device has no camera privacy toggle")
        }
        if (!hasCameraPermission()) return blocked("CAMERA must be granted")
        val viaShell = optBool("toggle_via_shell", false)
        var shellOut: String? = null
        if (viaShell) {
            shellOut = shell("cmd sensor_privacy ${if (expectBlocked) "enable" else "disable"} 0 camera").trim()
            Thread.sleep(1000)
        }
        bringProbeToForeground()
        val p = probeAccess(holdMs = 2500)
        finishProbe()
        if (viaShell && expectBlocked && optBool("restore", true)) shell("cmd sensor_privacy disable 0 camera")
        val state = try {
            shell("dumpsys sensor_privacy").lineSequence().filter { it.contains("camera", true) }.take(5).joinToString(" | ")
        } catch (_: Exception) {
            ""
        }
        val evidence = arrayOf(*p.fields(""), "toggle_via_shell" to viaShell, "shell_output" to shellOut, "sensor_privacy_state" to state)
        if (expectBlocked) {
            verdict(!p.imageData, if (p.imageData) 1 else 0, *evidence)
        } else {
            verdict(p.granted && p.imageData && health?.cameraserverRestarted() != true, 0, *evidence)
        }
    }

    // ------------------------------------------------------------------ other apps

    private fun unauthorizedApp() {
        val helper = optString("unauthorized_package", "com.example.cameraunauthorized")
        val j = runHelper(helper, mapOf("scenario" to "helper_probe", "camera_id" to cameraId))
            ?: return blocked("helper $helper is not installed (build the unauthorized flavor)")
        val helperImage = j.optBoolean("image_data", false)
        val helperGranted = j.optString("access") == AccessReason.GRANTED
        verdict(!helperGranted && !helperImage, if (helperImage) 1 else 0, *helperFields("helper_", j))
    }

    private fun permissionIsolation() {
        val helper = optString("unauthorized_package", "com.example.cameraunauthorized")
        if (!hasCameraPermission()) return blocked("authorized package needs CAMERA granted")
        bringProbeToForeground()
        openAndStream(cameraId)
        val before = sink?.frameCount() ?: 0
        val j = runHelper(helper, mapOf("scenario" to "helper_probe", "camera_id" to cameraId))
        val mainKept = (sink?.frameCount() ?: 0) > before
        closeStream()
        finishProbe()
        j ?: return blocked("helper $helper is not installed (build the unauthorized flavor)")
        val helperImage = j.optBoolean("image_data", false)
        val deniedByPermission = j.optString("access") == AccessReason.DENIED_SECURITY
        verdict(
            mainKept && deniedByPermission && !helperImage,
            if (helperImage) 1 else 0,
            "authorized_streaming_kept" to mainKept,
            *helperFields("unauthorized_", j),
        )
    }

    private fun resourceIsolation() {
        val helper = optString("secondary_package", "com.example.camerasecondary")
        if (!hasCameraPermission()) return blocked("primary package needs CAMERA granted")
        try {
            uiAutomation().grantRuntimePermission(helper, Manifest.permission.CAMERA)
        } catch (_: Exception) {
        }
        bringProbeToForeground()
        openAndStream(cameraId)
        val disconnectsBefore = cameraErrors.disconnectCount
        val framesBefore = sink?.frameCount() ?: 0
        val lastFrameBefore = sink?.lastFrameNs() ?: 0
        val j = runHelper(helper, mapOf("scenario" to "helper_probe", "camera_id" to cameraId, "hold_sec" to "3"))
        val primaryFrames = (sink?.frameCount() ?: 0) - framesBefore
        val primaryDisconnected = cameraErrors.disconnectCount > disconnectsBefore
        closeStream()
        finishProbe()
        j ?: return blocked("helper $helper is not installed (build the secondary flavor)")
        val helperAccess = j.optString("access")
        val helperImage = j.optBoolean("image_data", false)
        val consistent = when (helperAccess) {
            AccessReason.GRANTED -> primaryDisconnected
            AccessReason.BUSY -> !primaryDisconnected && primaryFrames > 0
            else -> false
        }
        val simultaneous = helperImage && !primaryDisconnected && primaryFrames > 0
        verdict(
            consistent && !simultaneous,
            if (simultaneous) 1 else 0,
            "primary_frames_during_helper" to primaryFrames,
            "primary_disconnected" to primaryDisconnected,
            "primary_last_frame_before_ns" to lastFrameBefore,
            *helperFields("secondary_", j),
        )
    }

    private fun helperProbe() {
        val declared = try {
            appContext.packageManager.getPackageInfo(appContext.packageName, PackageManager.GET_PERMISSIONS)
                .requestedPermissions?.contains(Manifest.permission.CAMERA) == true
        } catch (_: Exception) {
            null
        }
        val p = probeAccess(holdMs = optLong("hold_sec", 1) * 1000)
        emitSecurity(
            "PASS",
            if (p.imageData) 1 else 0,
            0,
            0,
            "scenario" to "helper_probe",
            "package" to appContext.packageName,
            "camera_permission_declared" to declared,
            "permission_granted" to hasCameraPermission(),
            *p.fields(""),
        )
    }

    // ------------------------------------------------------------------ lock screen

    private fun lockDevice(): Boolean {
        val power = appContext.getSystemService(Context.POWER_SERVICE) as PowerManager
        val keyguard = appContext.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
        shell("input keyevent KEYCODE_SLEEP")
        waitUntil(5000) { !power.isInteractive }
        return waitUntil(optLong("lock_timeout_sec", 10) * 1000) { keyguard.isKeyguardLocked }
    }

    private fun wakeScreen() {
        shell("input keyevent KEYCODE_WAKEUP")
        Thread.sleep(800)
    }

    private fun lockedDevice() {
        if (!hasCameraPermission()) return blocked("CAMERA must be granted")
        val keyguard = appContext.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
        val secure = keyguard.isDeviceSecure
        if (!lockDevice()) {
            wakeScreen()
            return blocked("keyguard did not lock after screen off (enable 'Power button instantly locks')", "device_secure" to secure)
        }
        Thread.sleep(1000)
        val importance = processImportance()
        val p = probeAccess()
        val lockedDuringProbe = keyguard.isKeyguardLocked
        wakeScreen()
        if (!secure) shell("wm dismiss-keyguard")
        val evidence = arrayOf(*p.fields(""), "device_secure" to secure, "keyguard_locked_during_probe" to lockedDuringProbe, "importance" to importance)
        if (importance <= ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND_SERVICE) {
            return blocked("instrumentation kept the process in a foreground state while locked", *evidence)
        }
        verdict(lockedDuringProbe && !p.imageData, if (p.imageData) 1 else 0, *evidence)
    }

    private fun secureLockscreen() {
        val keyguard = appContext.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
        if (!keyguard.isDeviceSecure) return blocked("device has no secure lock (PIN / pattern / password) set")
        if (!lockDevice()) {
            wakeScreen()
            return blocked("keyguard did not lock after screen off")
        }
        wakeScreen()
        val secureCamera = appContext.packageManager.resolveActivity(
            Intent("android.media.action.STILL_IMAGE_CAMERA_SECURE"),
            PackageManager.MATCH_DEFAULT_ONLY,
        )?.activityInfo?.let { "${it.packageName}/${it.name}" }
        var lockedWithSecureCamera: Boolean? = null
        if (secureCamera != null) {
            shell("am start -a android.media.action.STILL_IMAGE_CAMERA_SECURE")
            Thread.sleep(3000)
            lockedWithSecureCamera = keyguard.isKeyguardLocked
            shell("input keyevent KEYCODE_BACK")
            Thread.sleep(800)
            shell("input keyevent KEYCODE_HOME")
            Thread.sleep(800)
        }
        val lockedAfter = keyguard.isKeyguardLocked
        val p = if (hasCameraPermission()) probeAccess() else null
        val harnessLeak = p?.imageData == true
        val stayedLocked = lockedAfter && lockedWithSecureCamera != false
        verdict(
            stayedLocked && !harnessLeak,
            if (harnessLeak) 1 else 0,
            "secure_camera_activity" to secureCamera,
            "keyguard_locked_with_secure_camera" to lockedWithSecureCamera,
            "keyguard_locked_after" to lockedAfter,
            *(p?.fields("harness_") ?: emptyArray()),
            "note" to "device left locked; unlock manually",
        )
    }

    // ------------------------------------------------------------------ audit / persistence

    private fun durationSeconds(s: String): Double? {
        val m = Regex("time=\\+([0-9dhms]+)").find(s) ?: return null
        var total = 0.0
        Regex("(\\d+)(ms|d|h|m|s)").findAll(m.groupValues[1]).forEach {
            val v = it.groupValues[1].toDouble()
            total += when (it.groupValues[2]) {
                "d" -> v * 86400
                "h" -> v * 3600
                "m" -> v * 60
                "s" -> v
                else -> v / 1000
            }
        }
        return total
    }

    private fun audit() {
        if (!hasCameraPermission()) return blocked("CAMERA must be granted")
        val windowSec = optLong("audit_window_sec", 60)
        val startEpoch = System.currentTimeMillis() / 1000.0
        val p = probeAccess(holdMs = 2000)
        Thread.sleep(1000)
        val pkg = appContext.packageName
        val events = try {
            shell("dumpsys media.camera").lineSequence().filter { it.contains(pkg) }.toList()
        } catch (_: Exception) {
            emptyList()
        }
        val connectEvents = events.count { it.contains("CONNECT") && !it.contains("DISCONNECT") }
        val disconnectEvents = events.count { it.contains("DISCONNECT") }
        val ops = appOps()
        val opsAge = durationSeconds(ops)
        val logLines = try {
            shell("logcat -d -v epoch -s CameraService").lineSequence().count { line ->
                val t = line.trim().substringBefore(' ').toDoubleOrNull()
                t != null && t >= startEpoch - 1 && line.contains(pkg)
            }
        } catch (_: Exception) {
            0
        }
        val appopsRecent = opsAge != null && opsAge <= windowSec
        val evidence = connectEvents > 0 || appopsRecent || logLines > 0
        verdict(
            p.granted && evidence,
            0,
            *p.fields(""),
            "media_camera_connect_events" to connectEvents,
            "media_camera_disconnect_events" to disconnectEvents,
            "appops" to ops,
            "appops_last_access_sec_ago" to opsAge,
            "appops_recent_access" to appopsRecent,
            "cameraservice_log_lines" to logLines,
        )
    }

    private fun bootId(): String = try {
        File("/proc/sys/kernel/random/boot_id").readText().trim()
    } catch (_: Exception) {
        ""
    }

    private fun persistenceReboot() {
        val phase = optString("phase", "before").lowercase()
        val marker = File(appContext.filesDir, "reboot_marker.json")
        if (phase == "before") {
            if (!hasCameraPermission()) return blocked("CAMERA must be granted before reboot")
            val p = probeAccess()
            marker.writeText(JSONObject().put("boot_id", bootId()).put("granted", true).toString())
            return verdict(p.granted && p.imageData, 0, *p.fields(""), "boot_id" to bootId())
        }
        if (!marker.exists()) return blocked("no baseline; run phase=before first")
        val baseline = JSONObject(marker.readText())
        if (baseline.optString("boot_id") == bootId()) return blocked("device has not rebooted since phase=before")
        val granted = hasCameraPermission()
        val p = probeAccess()
        val persisted = granted == baseline.optBoolean("granted") && p.granted == granted && p.imageData == granted
        verdict(persisted, if (p.imageData && !granted) 1 else 0, *p.fields(""), "boot_id" to bootId(), "baseline_boot_id" to baseline.optString("boot_id"))
    }

    private fun postOta() {
        val phase = optString("phase", "before").lowercase()
        val marker = File(appContext.filesDir, "ota_baseline.json")
        val granted = hasCameraPermission()
        val p = probeAccess()
        val privacySupported = Build.VERSION.SDK_INT >= 31 &&
            appContext.getSystemService(SensorPrivacyManager::class.java)
                ?.supportsSensorToggle(SensorPrivacyManager.Sensors.CAMERA) == true
        val consistent = p.imageData == granted || (!granted && !p.imageData)
        val snapshot = JSONObject()
            .put("fingerprint", Build.FINGERPRINT)
            .put("security_patch", Build.VERSION.SECURITY_PATCH)
            .put("granted", granted)
            .put("image_data", p.imageData)
            .put("privacy_toggle_supported", privacySupported)
        if (phase == "before") {
            marker.writeText(snapshot.toString())
            return verdict(consistent, if (p.imageData && !granted) 1 else 0, *p.fields(""), "fingerprint" to Build.FINGERPRINT)
        }
        if (!marker.exists()) return blocked("no pre-OTA baseline; run phase=before on the old build")
        val base = JSONObject(marker.readText())
        if (base.optString("fingerprint") == Build.FINGERPRINT) return blocked("build fingerprint unchanged; OTA not applied")
        val regressions = ArrayList<String>()
        if (base.optBoolean("granted") != granted) regressions += "permission state changed"
        if (!consistent) regressions += "camera access does not match permission"
        if (base.optBoolean("privacy_toggle_supported") && !privacySupported) regressions += "privacy toggle support lost"
        verdict(
            regressions.isEmpty(),
            if (p.imageData && !granted) 1 else 0,
            *p.fields(""),
            "baseline_fingerprint" to base.optString("fingerprint"),
            "fingerprint" to Build.FINGERPRINT,
            "security_patch" to Build.VERSION.SECURITY_PATCH,
            "regressions" to regressions.joinToString("; "),
        )
    }
}
