package com.example.cameratest

import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CaptureResult
import android.hardware.camera2.params.MeteringRectangle
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Autofocus operation.
 *
 * Args: camera_id, mode = auto | tap | continuous, x / y (0..1, sensor-oriented
 * normalized coordinates, tap only; aliases focus_point_x / focus_point_y),
 * timeout_ms (5000), capture (true), output_dir.
 */
@RunWith(AndroidJUnit4::class)
open class FocusTest : HarnessTest() {

    @Test
    fun focus() {
        val cameraId = cameraArg() ?: return emitNotApplicable("no camera")
        val mode = optString("mode", "auto").lowercase()
        val timeoutMs = optLong("timeout_ms", 5000)
        val capture = optBool("capture", true)
        val c = chars(cameraId)
        val afModes = c.get(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES)?.toList() ?: emptyList()

        if (mode != "continuous" && !supportsAfAuto(cameraId)) {
            return emitNotApplicable("camera $cameraId has no AF_MODE_AUTO (fixed focus)", "camera_id" to cameraId)
        }
        if (mode == "continuous" && !afModes.contains(CameraMetadata.CONTROL_AF_MODE_CONTINUOUS_PICTURE)) {
            return emitNotApplicable("camera $cameraId has no CONTINUOUS_PICTURE AF", "camera_id" to cameraId)
        }
        val regions = if (mode == "tap") {
            val maxRegions = c.get(CameraCharacteristics.CONTROL_MAX_REGIONS_AF) ?: 0
            if (maxRegions < 1) {
                return emitNotApplicable("camera $cameraId does not support AF regions", "camera_id" to cameraId)
            }
            val x = optFloat("x", optFloat("focus_point_x", 0.5f)).coerceIn(0f, 1f)
            val y = optFloat("y", optFloat("focus_point_y", 0.5f)).coerceIn(0f, 1f)
            arrayOf(meteringRect(cameraId, x, y) ?: return emitFail("no active array size"))
        } else {
            null
        }

        try {
            val jpegSize = jpegSizeFor(cameraId, requireString("resolution"))
                ?: return emitFail("no JPEG size for camera $cameraId")
            val reader = if (capture) newJpegReader(jpegSize) else null
            val monitor = ResultMonitor()
            val device = openCameraTracked(cameraId)
            val streamSink = createSink(cameraId)
            val session = startStream(device, streamSink, listOfNotNull(reader?.surface), monitor)
            streamSink.awaitFirstFrame(5000) ?: return emitFail("no preview frame")

            val latencyMs: Double
            val terminal: Int?
            var error: String? = null
            if (mode == "continuous") {
                session.setRepeatingRequest(
                    previewRequest(device, streamSink) {
                        it.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                    },
                    monitor,
                    backgroundHandler,
                )
                val t0 = android.os.SystemClock.elapsedRealtimeNanos()
                monitor.arm { r ->
                    r.get(CaptureResult.CONTROL_AF_STATE) == CameraMetadata.CONTROL_AF_STATE_PASSIVE_FOCUSED
                }
                val hit = monitor.await(timeoutMs)
                latencyMs = hit?.let { (it.second - t0) / 1e6 } ?: timeoutMs.toDouble()
                terminal = hit?.first?.get(CaptureResult.CONTROL_AF_STATE)
                    ?: monitor.latest?.get(CaptureResult.CONTROL_AF_STATE)
                if (hit == null) error = "no PASSIVE_FOCUSED within ${timeoutMs}ms"
            } else {
                val af = runAutofocus(device, session, streamSink, monitor, regions, timeoutMs)
                latencyMs = af.latencyMs
                terminal = af.terminalState
                error = af.error
            }
            val focusDistance = monitor.latest?.get(CaptureResult.LENS_FOCUS_DISTANCE)

            var path: String? = null
            var captureOk: Boolean? = null
            if (reader != null) {
                val shot = captureStill(device, session, reader) { b ->
                    if (mode == "continuous") {
                        b.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                    } else {
                        b.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_AUTO)
                        if (regions != null) b.set(CaptureRequest.CONTROL_AF_REGIONS, regions)
                    }
                    b.set(CaptureRequest.JPEG_ORIENTATION, jpegOrientation(cameraId))
                }
                captureOk = shot.ok
                if (shot.ok) {
                    val dir = resolveOutputDir(requireString("output_dir"))
                    path = saveDurably(shot.bytes!!, dir, "focus_${mode}_${System.currentTimeMillis()}.jpg").absolutePath
                } else if (error == null) {
                    error = shot.error
                }
            }

            val focused = terminal == CameraMetadata.CONTROL_AF_STATE_FOCUSED_LOCKED ||
                terminal == CameraMetadata.CONTROL_AF_STATE_PASSIVE_FOCUSED
            emitResult(
                error == null,
                error,
                "camera_id" to cameraId,
                "mode" to mode,
                "af_state" to afStateName(terminal),
                "focused" to focused,
                "af_latency_ms" to latencyMs,
                "lens_focus_distance" to focusDistance?.toDouble(),
                "focus_point" to regions?.firstOrNull()?.let { "${it.x},${it.y},${it.width}x${it.height}" },
                "capture_ok" to captureOk,
                "path" to path,
            )
        } catch (e: Exception) {
            emitFailWith(describe(e), "camera_id" to cameraId, "mode" to mode)
        }
    }

    /** 10 % square around the normalized point, in active-array coordinates. */
    private fun meteringRect(cameraId: String, x: Float, y: Float): MeteringRectangle? {
        val array = chars(cameraId).get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE) ?: return null
        val half = (minOf(array.width(), array.height()) * 0.05f).toInt().coerceAtLeast(1)
        val cx = (array.width() * x).toInt()
        val cy = (array.height() * y).toInt()
        val left = (cx - half).coerceIn(0, array.width() - 2 * half)
        val top = (cy - half).coerceIn(0, array.height() - 2 * half)
        return MeteringRectangle(left, top, 2 * half, 2 * half, MeteringRectangle.METERING_WEIGHT_MAX)
    }
}
