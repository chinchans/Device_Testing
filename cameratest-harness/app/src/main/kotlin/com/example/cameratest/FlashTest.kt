package com.example.cameratest

import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CaptureResult
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Flash operation.
 *
 * Args: camera_id (first back camera with a flash unit), mode = on | off | auto | torch,
 * capture (true), output_dir.
 * Reports FLASH_STATE of the still capture and, for auto, whether AE asked for flash.
 */
@RunWith(AndroidJUnit4::class)
open class FlashTest : HarnessTest() {

    @Test
    fun flash() {
        val mode = optString("mode", optString("flash_mode", "on")).lowercase()
        if (mode !in setOf("on", "off", "auto", "torch")) return emitFail("mode must be on|off|auto|torch")
        val cameraId = requireString("camera_id") ?: flashCameraId()
            ?: return emitNotApplicable("no camera with a flash unit")
        if (chars(cameraId).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) != true) {
            return emitNotApplicable("camera $cameraId has no flash unit", "camera_id" to cameraId)
        }
        val capture = optBool("capture", mode != "torch")

        try {
            val shot = flashCapture(cameraId, mode, capture)
            val dir = resolveOutputDir(requireString("output_dir"))
            val path = shot.bytes?.let {
                saveDurably(it, dir, "flash_${mode}_${System.currentTimeMillis()}.jpg").absolutePath
            }
            emitResult(
                shot.error == null,
                shot.error,
                "camera_id" to cameraId,
                "mode" to mode,
                "flash_state" to flashStateName(shot.flashState),
                "flash_fired" to shot.fired,
                "ae_state_before_capture" to aeStateName(shot.aeStateBefore),
                "flash_required" to (shot.aeStateBefore == CameraMetadata.CONTROL_AE_STATE_FLASH_REQUIRED),
                "expected_fire" to when (mode) {
                    "on", "torch" -> true
                    "off" -> false
                    else -> null
                },
                "path" to path,
            )
        } catch (e: Exception) {
            emitFailWith(describe(e), "camera_id" to cameraId, "mode" to mode)
        }
    }

    class FlashShot(
        val flashState: Int?,
        val aeStateBefore: Int?,
        val bytes: ByteArray?,
        val error: String?,
    ) {
        val fired: Boolean
            get() = flashState == CameraMetadata.FLASH_STATE_FIRED ||
                flashState == CameraMetadata.FLASH_STATE_PARTIAL
    }

    protected fun flashCameraId(): String? =
        cameraManager.cameraIdList.firstOrNull { id ->
            val c = chars(id)
            c.get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true &&
                c.get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_BACK
        } ?: cameraManager.cameraIdList.firstOrNull { chars(it).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true }

    protected fun flashConfig(mode: String): (CaptureRequest.Builder) -> Unit = { b ->
        when (mode) {
            "on" -> b.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON_ALWAYS_FLASH)
            "auto" -> b.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON_AUTO_FLASH)
            "torch" -> {
                b.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON)
                b.set(CaptureRequest.FLASH_MODE, CaptureRequest.FLASH_MODE_TORCH)
            }
            else -> {
                b.set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON)
                b.set(CaptureRequest.FLASH_MODE, CaptureRequest.FLASH_MODE_OFF)
            }
        }
    }

    /** Opens, streams, runs precapture (on/auto), captures; closes the stream afterwards. */
    protected fun flashCapture(cameraId: String, mode: String, capture: Boolean): FlashShot {
        val configure = flashConfig(mode)
        val reader = if (capture) {
            newJpegReader(jpegSizeFor(cameraId, requireString("resolution")) ?: error("no JPEG size"))
        } else {
            null
        }
        val monitor = ResultMonitor()
        try {
            val device = openCameraTracked(cameraId)
            val streamSink = createSink(cameraId)
            val session = startStream(device, streamSink, listOfNotNull(reader?.surface), monitor, configure)
            streamSink.awaitFirstFrame(5000) ?: return FlashShot(null, null, null, "no preview frame")

            val aeBefore = if (mode == "on" || mode == "auto") {
                runPrecapture(device, session, streamSink, monitor, configure)
            } else {
                monitor.arm { true }
                monitor.await(1000)?.first?.get(CaptureResult.CONTROL_AE_STATE)
            }
            if (reader == null) {
                monitor.arm { r -> r.get(CaptureResult.FLASH_STATE) == CameraMetadata.FLASH_STATE_FIRED }
                val hit = monitor.await(2000)
                val state = hit?.first?.get(CaptureResult.FLASH_STATE)
                    ?: monitor.latest?.get(CaptureResult.FLASH_STATE)
                return FlashShot(state, aeBefore, null, null)
            }
            val shot = captureStill(device, session, reader) { b ->
                configure(b)
                b.set(CaptureRequest.JPEG_ORIENTATION, jpegOrientation(cameraId))
            }
            return FlashShot(
                shot.result?.get(CaptureResult.FLASH_STATE),
                aeBefore,
                shot.bytes,
                shot.error,
            )
        } finally {
            closeStream()
        }
    }
}
