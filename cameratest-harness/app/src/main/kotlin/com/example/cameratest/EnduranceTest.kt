package com.example.cameratest

import android.graphics.BitmapFactory
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CaptureResult
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.concurrent.ConcurrentHashMap

/**
 * Bounded endurance loop with thermal abort.
 *
 * operation (cycles unless noted):
 *  open_close | capture | switch | lens_switch | zoom | af | flash |
 *  preview (duration_sec) | memory_leak | resource_release | cameraservice |
 *  media_integrity (capture_count) | mixed (duration_sec)
 * Args: camera_id, source_camera / target_camera, cycles (1000), duration_sec, resolution,
 * min_zoom / max_zoom, output_dir, keep_files (false), max_consecutive_failures (10).
 *
 * metric_value: completed cycles; preview = healthy seconds; memory_leak = PSS growth MB;
 * resource_release = cycles whose camera was not released; cameraservice = fatal camera
 * errors + cameraserver restarts; media_integrity = valid files; mixed = crashes + ANRs.
 */
@RunWith(AndroidJUnit4::class)
open class EnduranceTest : HarnessTest() {

    private class NotApplicable(message: String) : Exception(message)

    private inner class Rig(val cameraId: String, withJpeg: Boolean) {
        val monitor = ResultMonitor()
        val reader = if (withJpeg) {
            newJpegReader(
                jpegSizeFor(cameraId, requireString("resolution"))
                    ?: throw NotApplicable("resolution not supported by camera $cameraId"),
                2,
            )
        } else {
            null
        }
        val device = openCameraTracked(cameraId)
        val streamSink = createSink(cameraId)
        val session = startStream(device, streamSink, listOfNotNull(reader?.surface), monitor)

        init {
            streamSink.awaitFirstFrame(5000) ?: error("no preview frame from camera $cameraId")
        }
    }

    private abstract inner class Workload {
        open val timeBased = false
        val extras = LinkedHashMap<String, Any?>()
        private var rig: Rig? = null

        abstract fun cycle(i: Int)

        open fun metric(completed: Int, healthy: Double, health: Map<String, Any?>): Any? = completed

        fun rig(cameraId: String, withJpeg: Boolean): Rig =
            rig ?: Rig(cameraId, withJpeg).also { rig = it }

        open fun recover() {
            closeStream()
            rig = null
        }

        open fun finish() {
            closeStream()
            rig = null
        }
    }

    @Test
    fun endurance() {
        val op = optString("operation", "open_close").lowercase()
        val cycles = optInt("cycles", optInt("capture_count", 1000)).coerceIn(1, 1_000_000)
        val durationSec = optLong("duration_sec", 0)
        val maxConsecutive = optInt("max_consecutive_failures", 10)
        val health = SystemHealthMonitor(::shell)

        val workload = try {
            build(op)
        } catch (e: NotApplicable) {
            return emitNotApplicable(e.message ?: "not applicable", "operation" to op)
        } catch (e: IllegalArgumentException) {
            return emitFail(e.message ?: "bad arguments")
        }
        if (workload.timeBased && durationSec <= 0) return emitFail("duration_sec required for $op")

        val start = SystemClock.elapsedRealtime()
        var completed = 0
        var failed = 0
        var consecutive = 0
        var healthySec = 0.0
        var thermalAbort = false
        var abortedReason: String? = null
        var lastError: String? = null
        var i = 0
        while (true) {
            val elapsed = SystemClock.elapsedRealtime() - start
            if (workload.timeBased) {
                if (elapsed >= durationSec * 1000) break
            } else if (i >= cycles) {
                break
            }
            if (i % 10 == 0 && isThermalCritical()) {
                thermalAbort = true
                break
            }
            val c0 = SystemClock.elapsedRealtime()
            try {
                workload.cycle(i)
                completed++
                consecutive = 0
                healthySec += (SystemClock.elapsedRealtime() - c0) / 1000.0
            } catch (e: NotApplicable) {
                workload.finish()
                return emitNotApplicable(e.message ?: "not applicable", "operation" to op)
            } catch (e: Exception) {
                failed++
                consecutive++
                lastError = describe(e)
                workload.recover()
            }
            if (consecutive >= maxConsecutive) {
                abortedReason = "$consecutive consecutive failures"
                break
            }
            i++
        }
        workload.finish()

        val healthFields = health.fields(harnessPackages())
        val healthMap = healthFields.toMap()
        val metric = workload.metric(completed, healthySec, healthMap)
        val requested = if (workload.timeBased) null else cycles
        val pass = failed == 0 && !thermalAbort && abortedReason == null &&
            (requested == null || completed == requested)
        val fields = arrayListOf<Pair<String, Any?>>(
            "operation" to op,
            "completed_cycles" to completed,
            "requested_cycles" to requested,
            "duration_sec" to durationSec.takeIf { workload.timeBased },
            "elapsed_sec" to (SystemClock.elapsedRealtime() - start) / 1000.0,
            "last_error" to lastError,
            "aborted_reason" to abortedReason,
            "thermal_status_end" to thermalStatus(),
        )
        fields += cameraErrors.fields().toList()
        fields += healthFields.toList()
        workload.extras.forEach { (k, v) -> fields += k to v }
        emitEndurance(pass, metric, failed, thermalAbort, *fields.toTypedArray())
    }

    private fun build(op: String): Workload = when (op) {
        "open_close", "cameraservice" -> openClose(op)
        "capture" -> capture()
        "switch" -> switch()
        "lens_switch" -> lensSwitch()
        "zoom" -> zoom()
        "af" -> autofocus()
        "flash" -> flash()
        "preview" -> preview()
        "memory_leak" -> memoryLeak()
        "resource_release" -> resourceRelease()
        "media_integrity" -> mediaIntegrity()
        "mixed" -> mixed()
        else -> throw IllegalArgumentException("unknown operation: $op")
    }

    private fun requireCamera(): String = cameraArg() ?: throw NotApplicable("no rear camera")

    private fun openStreamClose(cameraId: String) {
        try {
            openAndStream(cameraId)
        } finally {
            closeStream()
        }
    }

    // ------------------------------------------------------------------ workloads

    private fun openClose(op: String): Workload {
        val cameraId = requireCamera()
        val stream = optBool("stream", true)
        return object : Workload() {
            init {
                extras["camera_id"] = cameraId
            }

            override fun cycle(i: Int) {
                if (stream) {
                    openStreamClose(cameraId)
                } else {
                    try {
                        openCameraTracked(cameraId)
                    } finally {
                        closeStream()
                    }
                }
            }

            override fun metric(completed: Int, healthy: Double, health: Map<String, Any?>): Any? =
                if (op == "cameraservice") {
                    cameraErrors.fatalCount + if (health["cameraserver_restarted"] == true) 1 else 0
                } else {
                    completed
                }
        }
    }

    private fun capture(): Workload {
        val cameraId = requireCamera()
        return object : Workload() {
            init {
                extras["camera_id"] = cameraId
            }

            override fun cycle(i: Int) {
                val r = rig(cameraId, withJpeg = true)
                val shot = captureStill(r.device, r.session, r.reader!!, timeoutSec = 10)
                if (!shot.ok || shot.bytes!!.isEmpty()) error(shot.error ?: "empty JPEG")
            }
        }
    }

    private fun switch(): Workload {
        val source = requireString("source_camera") ?: throw NotApplicable("source_camera required")
        val target = requireString("target_camera") ?: throw NotApplicable("target_camera required")
        if (!cameraExists(source) || !cameraExists(target)) throw NotApplicable("camera $source or $target not present")
        return object : Workload() {
            init {
                extras["source_camera"] = source
                extras["target_camera"] = target
            }

            override fun cycle(i: Int) = openStreamClose(if (i % 2 == 0) source else target)
        }
    }

    private fun lensSwitch(): Workload {
        val source = requireString("source_camera") ?: requireCamera()
        val target = requireString("target_camera") ?: throw NotApplicable("target_camera required")
        val lens = resolveLensTarget(source, target) ?: throw NotApplicable("lens $target not reachable from $source")
        return object : Workload() {
            private var basePhysical: String? = null
            private var physicalMismatch = 0

            init {
                extras["source_camera"] = source
                extras["target_camera"] = target
                extras["switch_method"] = lens.method
            }

            override fun cycle(i: Int) {
                if (lens.method == LensTarget.CAMERA_ID) return openStreamClose(if (i % 2 == 0) target else source)
                val r = rig(source, withJpeg = false)
                if (i == 0) basePhysical = activePhysicalId(zoomTo(r.device, r.session, r.streamSink, r.monitor, 1f)?.first)
                val toTarget = i % 2 == 0
                val ratio = if (toTarget) lens.zoomRatio!! else 1f
                val expect = if (toTarget) target else basePhysical
                val hit = zoomTo(r.device, r.session, r.streamSink, r.monitor, ratio, expect, 3000)
                    ?: error("lens did not switch to ${expect ?: "ratio $ratio"}")
                val physical = activePhysicalId(hit.first)
                if (expect != null && physical != null && physical != expect) physicalMismatch++
                extras["physical_mismatch"] = physicalMismatch
            }
        }
    }

    private fun zoom(): Workload {
        val cameraId = requireCamera()
        val range = zoomRange(cameraId) ?: throw NotApplicable("camera $cameraId has no CONTROL_ZOOM_RATIO_RANGE")
        val min = optFloat("min_zoom", 1f).coerceIn(range.lower, range.upper)
        val max = optFloat("max_zoom", range.upper).coerceIn(range.lower, range.upper)
        return object : Workload() {
            init {
                extras["camera_id"] = cameraId
                extras["min_zoom"] = min.toDouble()
                extras["max_zoom"] = max.toDouble()
            }

            override fun cycle(i: Int) {
                val r = rig(cameraId, withJpeg = false)
                zoomTo(r.device, r.session, r.streamSink, r.monitor, max) ?: error("zoom $max not applied")
                zoomTo(r.device, r.session, r.streamSink, r.monitor, min) ?: error("zoom $min not applied")
            }
        }
    }

    private fun autofocus(): Workload {
        val cameraId = requireCamera()
        if (!supportsAfAuto(cameraId)) throw NotApplicable("camera $cameraId is fixed focus")
        return object : Workload() {
            private var focused = 0

            init {
                extras["camera_id"] = cameraId
            }

            override fun cycle(i: Int) {
                val r = rig(cameraId, withJpeg = false)
                val af = runAutofocus(r.device, r.session, r.streamSink, r.monitor)
                if (af.error != null) error(af.error)
                if (af.focused) focused++
                extras["focused_count"] = focused
            }
        }
    }

    private fun flash(): Workload {
        val cameraId = requireString("camera_id")
            ?: cameraManager.cameraIdList.firstOrNull { chars(it).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true }
            ?: throw NotApplicable("no camera with a flash unit")
        if (chars(cameraId).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) != true) {
            throw NotApplicable("camera $cameraId has no flash unit")
        }
        val intervalMs = optLong("flash_interval_ms", 1000)
        val alwaysFlash: (CaptureRequest.Builder) -> Unit = {
            it.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON_ALWAYS_FLASH)
        }
        return object : Workload() {
            private var fired = 0

            init {
                extras["camera_id"] = cameraId
            }

            override fun cycle(i: Int) {
                val r = rig(cameraId, withJpeg = true)
                runPrecapture(r.device, r.session, r.streamSink, r.monitor, alwaysFlash)
                val shot = captureStill(r.device, r.session, r.reader!!, timeoutSec = 10, keepBytes = false, configure = alwaysFlash)
                if (!shot.ok) error(shot.error ?: "flash capture failed")
                val state = shot.result?.get(CaptureResult.FLASH_STATE)
                if (state == android.hardware.camera2.CameraMetadata.FLASH_STATE_FIRED ||
                    state == android.hardware.camera2.CameraMetadata.FLASH_STATE_PARTIAL
                ) {
                    fired++
                }
                extras["flash_fired_count"] = fired
                Thread.sleep(intervalMs)
            }
        }
    }

    private fun preview(): Workload {
        val cameraId = requireCamera()
        return object : Workload() {
            override val timeBased = true
            private var minWindowFps = Double.MAX_VALUE
            private var stalls = 0

            init {
                extras["camera_id"] = cameraId
            }

            override fun cycle(i: Int) {
                val r = rig(cameraId, withJpeg = false)
                val before = r.streamSink.frameCount()
                val t0 = SystemClock.elapsedRealtime()
                Thread.sleep(1000)
                val frames = r.streamSink.frameCount() - before
                val fps = frames * 1000.0 / (SystemClock.elapsedRealtime() - t0)
                if (frames == 0) {
                    stalls++
                    extras["preview_stalls"] = stalls
                    error("preview stalled (no frames for 1s)")
                }
                minWindowFps = minOf(minWindowFps, fps)
                extras["min_window_fps"] = minWindowFps
            }

            override fun metric(completed: Int, healthy: Double, health: Map<String, Any?>): Any? = healthy
        }
    }

    private fun memoryLeak(): Workload {
        val cameraId = requireCamera()
        val warmup = optInt("warmup_cycles", 5)
        return object : Workload() {
            private var baseline = Double.NaN
            private var fdBaseline = -1
            private var threadBaseline = -1

            init {
                extras["camera_id"] = cameraId
            }

            override fun cycle(i: Int) {
                if (i == warmup) {
                    gcAndSettle()
                    baseline = pssMb()
                    fdBaseline = fdCount()
                    threadBaseline = threadCount()
                }
                try {
                    val r = Rig(cameraId, withJpeg = true)
                    val shot = captureStill(r.device, r.session, r.reader!!, timeoutSec = 10, keepBytes = false)
                    if (!shot.ok) error(shot.error ?: "capture failed")
                } finally {
                    closeStream()
                }
            }

            override fun metric(completed: Int, healthy: Double, health: Map<String, Any?>): Any? {
                if (baseline.isNaN()) {
                    gcAndSettle()
                    baseline = pssMb()
                }
                gcAndSettle(2000)
                val end = pssMb()
                extras["baseline_pss_mb"] = baseline
                extras["end_pss_mb"] = end
                extras["fd_growth"] = if (fdBaseline >= 0) fdCount() - fdBaseline else null
                extras["thread_growth"] = if (threadBaseline >= 0) threadCount() - threadBaseline else null
                return end - baseline
            }
        }
    }

    private fun resourceRelease(): Workload {
        val cameraId = requireCamera()
        val available = ConcurrentHashMap<String, Boolean>()
        val callback = object : CameraManager.AvailabilityCallback() {
            override fun onCameraAvailable(id: String) {
                available[id] = true
            }

            override fun onCameraUnavailable(id: String) {
                available[id] = false
            }
        }
        cameraManager.registerAvailabilityCallback(callback, backgroundHandler)
        return object : Workload() {
            private var notReleased = 0
            private val fdBaseline = fdCount()

            init {
                extras["camera_id"] = cameraId
            }

            override fun cycle(i: Int) {
                openStreamClose(cameraId)
                if (!waitUntil(3000) { available[cameraId] == true }) {
                    notReleased++
                    extras["not_released_cycles"] = notReleased
                }
            }

            override fun metric(completed: Int, healthy: Double, health: Map<String, Any?>): Any? {
                cameraManager.unregisterAvailabilityCallback(callback)
                extras["fd_growth"] = fdCount() - fdBaseline
                return notReleased
            }
        }
    }

    private fun mediaIntegrity(): Workload {
        val cameraId = requireCamera()
        val dir = resolveOutputDir(requireString("output_dir"))
        val keep = optBool("keep_files", false)
        return object : Workload() {
            private var valid = 0
            private var corrupt = 0

            init {
                extras["camera_id"] = cameraId
                extras["output_dir"] = dir.absolutePath
            }

            override fun cycle(i: Int) {
                val r = rig(cameraId, withJpeg = true)
                val shot = captureStill(r.device, r.session, r.reader!!, timeoutSec = 10)
                if (!shot.ok) error(shot.error ?: "capture failed")
                val bytes = shot.bytes!!
                val file = saveDurably(bytes, dir, "integrity_${i}_${System.currentTimeMillis()}.jpg")
                try {
                    val problem = verifyJpeg(file, bytes.size, r.reader.width, r.reader.height)
                    if (problem != null) {
                        corrupt++
                        extras["corrupt_files"] = corrupt
                        error("corrupt media: $problem")
                    }
                    valid++
                } finally {
                    if (!keep) file.delete()
                }
            }

            override fun metric(completed: Int, healthy: Double, health: Map<String, Any?>): Any? = valid
        }
    }

    private fun verifyJpeg(file: File, expectedBytes: Int, w: Int, h: Int): String? {
        if (file.length() != expectedBytes.toLong()) return "size ${file.length()} != $expectedBytes"
        val data = file.readBytes()
        if (data.size < 4 || data[0] != 0xFF.toByte() || data[1] != 0xD8.toByte()) return "missing SOI marker"
        val tail = data.size
        val hasEoi = (maxOf(0, tail - 64) until tail - 1).any { data[it] == 0xFF.toByte() && data[it + 1] == 0xD9.toByte() }
        if (!hasEoi) return "missing EOI marker"
        val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(data, 0, data.size, opts)
        val dimsOk = (opts.outWidth == w && opts.outHeight == h) || (opts.outWidth == h && opts.outHeight == w)
        return if (dimsOk) null else "decoded ${opts.outWidth}x${opts.outHeight}, expected ${w}x$h"
    }

    private fun mixed(): Workload {
        val rear = requireCamera()
        val front = discoverCameraId(CameraCharacteristics.LENS_FACING_FRONT)
        return object : Workload() {
            override val timeBased = true

            init {
                extras["camera_id"] = rear
                extras["front_camera_id"] = front
            }

            override fun cycle(i: Int) {
                when (i % 3) {
                    0 -> openStreamClose(rear)
                    1 -> try {
                        val r = Rig(rear, withJpeg = true)
                        val shot = captureStill(r.device, r.session, r.reader!!, timeoutSec = 10, keepBytes = false)
                        if (!shot.ok) error(shot.error ?: "capture failed")
                    } finally {
                        closeStream()
                    }
                    else -> openStreamClose(front ?: rear)
                }
            }

            override fun metric(completed: Int, healthy: Double, health: Map<String, Any?>): Any? =
                ((health["app_crash_count"] as? Int) ?: 0) +
                    ((health["anr_count"] as? Int) ?: 0) +
                    (if (health["cameraserver_restarted"] == true) 1 else 0)
        }
    }
}
