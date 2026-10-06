package com.example.cameratest

import android.app.KeyguardManager
import android.app.UiAutomation
import android.content.Context
import android.os.PowerManager
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Camera recovery across app / device lifecycle transitions, with [ProbeActivity] as
 * the foreground screen.
 *
 * operation:
 *  - background_foreground  HOME → back to the probe screen
 *  - lock_unlock            screen off → on → dismiss keyguard (non-secure lock only)
 *  - orientation            rotate 0 → 90 → 180 → 270 (UiAutomation rotation freeze)
 * A cycle passes when preview frames flow after the transition (reopening the camera
 * if the platform disconnected it). metric = recovered cycles.
 * Args: camera_id, cycles, dwell_ms (500).
 */
@RunWith(AndroidJUnit4::class)
open class LifecycleEnduranceTest : HarnessTest() {

    @Test
    fun lifecycle() {
        val op = optString("operation", "background_foreground").lowercase()
        if (op !in setOf("background_foreground", "lock_unlock", "orientation")) {
            return emitFail("operation must be background_foreground|lock_unlock|orientation")
        }
        val cameraId = cameraArg() ?: return emitNotApplicable("no rear camera")
        val cycles = optInt("cycles", 500).coerceIn(1, 100_000)
        val dwellMs = optLong("dwell_ms", 500)
        val keyguard = appContext.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
        val power = appContext.getSystemService(Context.POWER_SERVICE) as PowerManager
        if (op == "lock_unlock" && keyguard.isDeviceSecure) {
            return emitNotApplicable("device has a secure lock; the harness cannot unlock it", "operation" to op)
        }
        val health = SystemHealthMonitor(::shell)
        val start = SystemClock.elapsedRealtime()
        if (!bringProbeToForeground()) return emitFail("probe screen could not be brought to the foreground")

        var completed = 0
        var failed = 0
        var consecutive = 0
        var reopened = 0
        var thermalAbort = false
        var lastError: String? = null
        val rotations = intArrayOf(
            UiAutomation.ROTATION_FREEZE_90,
            UiAutomation.ROTATION_FREEZE_180,
            UiAutomation.ROTATION_FREEZE_270,
            UiAutomation.ROTATION_FREEZE_0,
        )
        try {
            if (op == "orientation") uiAutomation().setRotation(UiAutomation.ROTATION_FREEZE_0)
            openAndStream(cameraId)
            for (i in 0 until cycles) {
                if (i % 10 == 0 && isThermalCritical()) {
                    thermalAbort = true
                    break
                }
                try {
                    when (op) {
                        "background_foreground" -> {
                            if (!sendHome()) error("probe screen did not leave the foreground")
                            Thread.sleep(dwellMs)
                            if (!bringProbeToForeground()) error("probe screen did not return")
                        }
                        "lock_unlock" -> {
                            shell("input keyevent KEYCODE_SLEEP")
                            if (!waitUntil(5000) { !power.isInteractive }) error("screen did not turn off")
                            Thread.sleep(dwellMs)
                            shell("input keyevent KEYCODE_WAKEUP")
                            if (!waitUntil(5000) { power.isInteractive }) error("screen did not turn on")
                            shell("wm dismiss-keyguard")
                            if (!waitUntil(5000) { !keyguard.isKeyguardLocked }) error("keyguard stayed locked")
                            if (!bringProbeToForeground()) error("probe screen did not return")
                        }
                        else -> {
                            uiAutomation().setRotation(rotations[i % rotations.size])
                            Thread.sleep(dwellMs.coerceAtLeast(700))
                            if (!ProbeActivity.foreground) error("probe screen lost foreground after rotation")
                        }
                    }
                    val flowing = sink?.awaitMoreFrames(3, 3000) == true
                    if (!flowing) {
                        closeStream()
                        openAndStream(cameraId)
                        reopened++
                    }
                    completed++
                    consecutive = 0
                } catch (e: Exception) {
                    failed++
                    consecutive++
                    lastError = describe(e)
                    closeStream()
                    try {
                        bringProbeToForeground()
                        openAndStream(cameraId)
                    } catch (_: Exception) {
                    }
                }
                if (consecutive >= 10) break
            }
        } catch (e: Exception) {
            lastError = describe(e)
        } finally {
            closeStream()
            if (op == "orientation") {
                try {
                    uiAutomation().setRotation(UiAutomation.ROTATION_FREEZE_0)
                    uiAutomation().setRotation(UiAutomation.ROTATION_UNFREEZE)
                } catch (_: Exception) {
                }
            }
            finishProbe()
        }

        val fields = arrayListOf<Pair<String, Any?>>(
            "operation" to op,
            "completed_cycles" to completed,
            "requested_cycles" to cycles,
            "camera_reopened_cycles" to reopened,
            "elapsed_sec" to (SystemClock.elapsedRealtime() - start) / 1000.0,
            "last_error" to lastError,
            "camera_id" to cameraId,
            "thermal_status_end" to thermalStatus(),
        )
        fields += cameraErrors.fields().toList()
        fields += health.fields(harnessPackages()).toList()
        emitEndurance(
            failed == 0 && completed == cycles && !thermalAbort,
            completed,
            failed,
            thermalAbort,
            *fields.toTypedArray(),
        )
    }
}
