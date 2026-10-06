package com.example.cameratest

import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CaptureResult
import android.os.Process
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONObject
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * Camera latency measurements (one sample per iteration, elapsedRealtimeNanos clock).
 *
 * mode:
 *  - cold_launch   launch request → first frame; the probe process is killed before every run
 *  - warm_launch   same, process kept alive (first run discarded as warm-up)
 *  - ttff          openCamera request → first preview frame
 *  - shutter       still request → JPEG available; zsl = true | false
 *  - af            AF trigger → FOCUSED_LOCKED / NOT_FOCUSED_LOCKED
 *  - switch        close source → first frame of target (source_camera, target_camera)
 *  - lens_switch   zoom request → first result on the target physical lens
 *  - processing    sensor exposure → JPEG available (request → JPEG if timestamps are not realtime)
 *  - save          JPEG bytes → durable file (fsync) in output_dir
 * Common args: camera_id, iterations (10), warmup (1; 0 for cold_launch), resolution.
 * Output: metric_value = p95 ms, samples, latency_ms = mean ms.
 */
@RunWith(AndroidJUnit4::class)
open class LatencyPerfTest : HarnessTest() {

    private val extras = LinkedHashMap<String, Any?>()
    private val componentSamples = LinkedHashMap<String, MutableList<Double>>()

    private fun component(name: String, ms: Double) {
        componentSamples.getOrPut(name) { ArrayList() } += ms
    }

    @Test
    fun latency() {
        val mode = optString("mode", "ttff").lowercase()
        val iterations = optInt("iterations", 10).coerceIn(1, 1000)
        val warmup = optInt("warmup", if (mode == "cold_launch") 0 else 1).coerceIn(0, 10)
        extras["mode"] = mode
        val sampler: (Int) -> Double = try {
            when (mode) {
                "cold_launch" -> launchSampler(cold = true)
                "warm_launch" -> launchSampler(cold = false)
                "ttff" -> ttffSampler()
                "shutter" -> shutterSampler()
                "af" -> afSampler()
                "switch" -> switchSampler()
                "lens_switch" -> lensSwitchSampler()
                "processing" -> processingSampler()
                "save" -> saveSampler()
                else -> return emitFail("unknown mode: $mode")
            }
        } catch (e: NotApplicable) {
            closeStream()
            return emitNotApplicable(e.message ?: "not applicable", "mode" to mode)
        } catch (e: Exception) {
            closeStream()
            return emitFailWith(describe(e), "mode" to mode)
        }

        val thermalStart = thermalStatus()
        val samples = ArrayList<Double>()
        var failures = 0
        var lastError: String? = null
        var thermalAbort = false
        for (i in 0 until warmup + iterations) {
            if (isThermalCritical()) {
                thermalAbort = true
                break
            }
            try {
                val v = sampler(i)
                if (i >= warmup) samples += v
            } catch (e: Exception) {
                if (i >= warmup) failures++
                lastError = describe(e)
                if (mode in setOf("ttff", "switch", "cold_launch", "warm_launch")) closeStream()
            }
        }
        closeStream()

        val p95 = Stats.percentile(samples, 95.0)
        val fields = arrayListOf<Pair<String, Any?>>(
            "p95_latency_ms" to p95,
            "p50_latency_ms" to Stats.percentile(samples, 50.0),
        )
        if (mode == "ttff") fields += "p95_ttff_ms" to p95
        fields += Stats.summary("latency", samples).toList()
        componentSamples.forEach { (name, v) -> fields += "${name}_p95_ms" to Stats.percentile(v, 95.0) }
        fields += listOf(
            "iterations_requested" to iterations,
            "warmup" to warmup,
            "failures" to failures,
            "last_error" to lastError,
            "thermal_abort" to thermalAbort,
            "thermal_status_start" to thermalStart,
            "thermal_status_end" to thermalStatus(),
        )
        extras.forEach { (k, v) -> fields += k to v }
        emitMetrics(
            p95,
            samples.size,
            Stats.mean(samples),
            *fields.toTypedArray(),
            pass = samples.size == iterations && !thermalAbort,
        )
    }

    private class NotApplicable(message: String) : Exception(message)

    // ------------------------------------------------------------------ launch

    private fun launchSampler(cold: Boolean): (Int) -> Double {
        val cameraId = cameraArg() ?: throw NotApplicable("no rear camera")
        extras["camera_id"] = cameraId
        val resultFile = File(appContext.filesDir, LaunchProbeActivity.RESULT_FILE)
        val component = "${appContext.packageName}/${LaunchProbeActivity::class.java.name}"
        var lastPid = -1
        if (cold) findProbePid()?.let { killProbe(it) }
        return { _ ->
            if (cold && lastPid > 0) killProbe(lastPid)
            resultFile.delete()
            val requestNs = SystemClock.elapsedRealtimeNanos()
            shell("am start -n $component --es ${LaunchProbeActivity.EXTRA_CAMERA_ID} $cameraId --el ${LaunchProbeActivity.EXTRA_REQUEST_NS} $requestNs")
            if (!waitUntil(15_000) { resultFile.exists() }) error("launch probe produced no result within 15s")
            val json = JSONObject(resultFile.readText())
            lastPid = json.optInt("pid", -1)
            json.optString("error").takeIf { it.isNotEmpty() }?.let { error(it) }
            val firstNs = json.getLong("first_frame_ns")
            val processStart = json.optLong("process_start_ns")
            if (processStart > 0 && processStart >= requestNs) {
                component("process_start_to_first_frame", (firstNs - processStart) / 1e6)
            }
            component("on_create_to_first_frame", (firstNs - json.getLong("on_create_ns")) / 1e6)
            extras["process_restarted_last_run"] = processStart >= requestNs
            waitUntil(3000) { !probeActivityResumed() }
            (firstNs - requestNs) / 1e6
        }
    }

    private fun findProbePid(): Int? {
        val am = appContext.getSystemService(android.app.ActivityManager::class.java)
        return am.runningAppProcesses
            ?.firstOrNull { it.processName.endsWith(":launchprobe") }?.pid
    }

    private fun killProbe(pid: Int) {
        Process.killProcess(pid)
        waitUntil(5000) { !File("/proc/$pid").exists() }
        Thread.sleep(300)
    }

    private fun probeActivityResumed(): Boolean =
        shell("dumpsys activity activities").lineSequence()
            .any { "LaunchProbeActivity" in it && ("mResumedActivity" in it || "topResumedActivity" in it) }

    // ------------------------------------------------------------------ open / switch

    private fun ttffSampler(): (Int) -> Double {
        val cameraId = cameraArg() ?: throw NotApplicable("no rear camera")
        extras["camera_id"] = cameraId
        return { _ ->
            try {
                val streamSink = createSink(cameraId)
                val t0 = SystemClock.elapsedRealtimeNanos()
                val device = openCameraTracked(cameraId)
                component("open", (SystemClock.elapsedRealtimeNanos() - t0) / 1e6)
                startStream(device, streamSink)
                val first = streamSink.awaitFirstFrame(5000) ?: error("no preview frame within 5s")
                (first - t0) / 1e6
            } finally {
                closeStream()
            }
        }
    }

    private fun switchSampler(): (Int) -> Double {
        val source = requireString("source_camera") ?: throw NotApplicable("source_camera required")
        val target = requireString("target_camera") ?: throw NotApplicable("target_camera required")
        if (!cameraExists(source) || !cameraExists(target)) throw NotApplicable("camera $source or $target not present")
        extras["source_camera"] = source
        extras["target_camera"] = target
        return { _ -> timedSwitch(source, target) }
    }

    private fun timedSwitch(source: String, target: String): Double {
        try {
            openAndStream(source)
            val t0 = SystemClock.elapsedRealtimeNanos()
            closeStream()
            val device = openCameraTracked(target)
            val targetSink = createSink(target)
            startStream(device, targetSink)
            val first = targetSink.awaitFirstFrame(5000) ?: error("no frame from $target within 5s")
            return (first - t0) / 1e6
        } finally {
            closeStream()
        }
    }

    private fun lensSwitchSampler(): (Int) -> Double {
        val source = requireString("source_camera") ?: cameraArg() ?: throw NotApplicable("no rear camera")
        val target = requireString("target_camera") ?: throw NotApplicable("target_camera required")
        val lens = resolveLensTarget(source, target) ?: throw NotApplicable("lens $target not reachable from $source")
        extras["source_camera"] = source
        extras["target_camera"] = target
        extras["switch_method"] = lens.method
        if (lens.method == LensTarget.CAMERA_ID) return { _ -> timedSwitch(source, target) }

        val ratio = lens.zoomRatio!!
        extras["zoom_ratio"] = ratio.toDouble()
        val monitor = ResultMonitor()
        val device = openCameraTracked(source)
        val streamSink = createSink(source)
        val session = startStream(device, streamSink, monitor = monitor)
        streamSink.awaitFirstFrame(5000) ?: error("no preview frame")
        val base = zoomTo(device, session, streamSink, monitor, 1f)?.first
        val basePhysical = activePhysicalId(base)
        extras["physical_id_reported"] = basePhysical != null
        return { _ ->
            zoomTo(device, session, streamSink, monitor, 1f, basePhysical, 3000)
                ?: error("did not return to base lens")
            Thread.sleep(300)
            val t0 = SystemClock.elapsedRealtimeNanos()
            val hit = zoomTo(device, session, streamSink, monitor, ratio, target, 3000)
                ?: error("active physical lens did not become $target within 3s")
            (hit.second - t0) / 1e6
        }
    }

    // ------------------------------------------------------------------ still capture

    private class StillRig(val device: CameraDevice, val session: android.hardware.camera2.CameraCaptureSession, val reader: android.media.ImageReader, val cameraId: String)

    private fun openStillRig(): StillRig {
        val cameraId = cameraArg() ?: throw NotApplicable("no rear camera")
        val size = jpegSizeFor(cameraId, requireString("resolution"))
            ?: throw NotApplicable("resolution ${requireString("resolution")} not supported by camera $cameraId")
        extras["camera_id"] = cameraId
        extras["width"] = size.width
        extras["height"] = size.height
        val reader = newJpegReader(size, 3)
        val device = openCameraTracked(cameraId)
        val streamSink = createSink(cameraId)
        val session = startStream(device, streamSink, listOf(reader.surface)) {
            it.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
        }
        streamSink.awaitFirstFrame(5000) ?: error("no preview frame")
        Thread.sleep(500)
        return StillRig(device, session, reader, cameraId)
    }

    private fun shutterSampler(): (Int) -> Double {
        val zsl = optBool("zsl", false)
        val rig = openStillRig()
        val c = chars(rig.cameraId)
        val zslKey = c.availableCaptureRequestKeys.contains(CaptureRequest.CONTROL_ENABLE_ZSL)
        var template = CameraDevice.TEMPLATE_STILL_CAPTURE
        if (zsl) {
            try {
                rig.device.createCaptureRequest(CameraDevice.TEMPLATE_ZERO_SHUTTER_LAG)
                template = CameraDevice.TEMPLATE_ZERO_SHUTTER_LAG
            } catch (_: Exception) {
            }
            if (template != CameraDevice.TEMPLATE_ZERO_SHUTTER_LAG && !zslKey) {
                throw NotApplicable("camera ${rig.cameraId} supports neither the ZSL template nor CONTROL_ENABLE_ZSL")
            }
        }
        extras["zsl_requested"] = zsl
        extras["zsl_template"] = template == CameraDevice.TEMPLATE_ZERO_SHUTTER_LAG
        return { _ ->
            val shot = captureStill(rig.device, rig.session, rig.reader, template, keepBytes = false) { b ->
                if (zslKey) b.set(CaptureRequest.CONTROL_ENABLE_ZSL, zsl)
            }
            if (!shot.ok) error(shot.error ?: "capture failed")
            shot.result?.get(CaptureResult.CONTROL_ENABLE_ZSL)?.let { extras["zsl_in_result"] = it }
            shot.shutterMs
        }
    }

    private fun afSampler(): (Int) -> Double {
        val cameraId = cameraArg() ?: throw NotApplicable("no rear camera")
        if (!supportsAfAuto(cameraId)) throw NotApplicable("camera $cameraId is fixed focus")
        extras["camera_id"] = cameraId
        val monitor = ResultMonitor()
        val device = openCameraTracked(cameraId)
        val streamSink = createSink(cameraId)
        val session = startStream(device, streamSink, monitor = monitor)
        streamSink.awaitFirstFrame(5000) ?: error("no preview frame")
        var focused = 0
        return { _ ->
            val af = runAutofocus(device, session, streamSink, monitor)
            if (af.error != null) error(af.error)
            if (af.focused) focused++
            extras["focused_count"] = focused
            af.latencyMs
        }
    }

    private fun processingSampler(): (Int) -> Double {
        val rig = openStillRig()
        val realtime = chars(rig.cameraId).get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE) ==
            CameraMetadata.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME
        extras["processing_basis"] = if (realtime) "sensor_timestamp_to_image" else "request_to_image"
        return { _ ->
            val shot = captureStill(rig.device, rig.session, rig.reader, keepBytes = false)
            if (!shot.ok) error(shot.error ?: "capture failed")
            component("request_to_image", shot.shutterMs)
            val sensorTs = shot.result?.get(CaptureResult.SENSOR_TIMESTAMP)
            if (realtime && sensorTs != null && sensorTs in 1 until shot.imageNs) {
                (shot.imageNs - sensorTs) / 1e6
            } else {
                shot.shutterMs
            }
        }
    }

    private fun saveSampler(): (Int) -> Double {
        val rig = openStillRig()
        val dir = resolveOutputDir(requireString("output_dir"))
        val keep = optBool("keep_files", false)
        extras["output_dir"] = dir.absolutePath
        return { i ->
            val shot = captureStill(rig.device, rig.session, rig.reader)
            if (!shot.ok) error(shot.error ?: "capture failed")
            val t0 = SystemClock.elapsedRealtimeNanos()
            val file = saveDurably(shot.bytes!!, dir, "save_perf_${i}_${System.currentTimeMillis()}.jpg")
            val t1 = SystemClock.elapsedRealtimeNanos()
            component("image_to_saved", (t1 - shot.imageNs) / 1e6)
            if (!keep) file.delete()
            (t1 - t0) / 1e6
        }
    }
}
