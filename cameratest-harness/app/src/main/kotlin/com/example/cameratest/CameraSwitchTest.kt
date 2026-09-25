package com.example.cameratest

import android.graphics.ImageFormat
import android.hardware.camera2.CameraAccessException
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CaptureRequest
import android.media.ImageReader
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class CameraSwitchTest : BaseCamera2Test() {

    @Test
    fun switchCameras() {
        val source = requireCameraId("source_camera")
            ?: return emitFail("source_camera required")
        val target = requireCameraId("target_camera")
            ?: return emitFail("target_camera required")
        val iterations = optInt("iterations", 10).coerceIn(1, 200)

        if (source == target) {
            return emitFail("source_camera and target_camera must differ")
        }

        var completed = 0
        var failed = 0
        val latencies = mutableListOf<Long>()

        try {
            // Validate both ids exist.
            cameraManager.getCameraCharacteristics(source)
            cameraManager.getCameraCharacteristics(target)
        } catch (e: Exception) {
            return emitSkip("camera not available: ${e.message}")
        }

        for (i in 1..iterations) {
            val from = if (i % 2 == 1) source else target
            val to = if (i % 2 == 1) target else source
            val t0 = System.nanoTime()
            try {
                warmCamera(from)
                safeClose()
                warmCamera(to)
                safeClose()
                latencies += (System.nanoTime() - t0) / 1_000_000L
                completed++
            } catch (e: Exception) {
                failed++
                safeClose()
            }
        }

        val meanLatency = if (latencies.isEmpty()) 0 else latencies.average().toInt()
        emitPass(
            "completed_iterations" to completed,
            "failed_iterations" to failed,
            "latency_ms" to meanLatency,
        )
    }

    /** Open camera, configure a tiny JPEG session, wait for one frame-ish settle. */
    private fun warmCamera(cameraId: String) {
        val device = openCameraBlocking(cameraId, timeoutSec = 8)
        cameraDevice = device
        val chars = cameraManager.getCameraCharacteristics(cameraId)
        val map = chars.get(android.hardware.camera2.CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
        val previewSize = choosePreviewSize(map)
        val preview = createPreviewSurface(previewSize.width, previewSize.height)
        val jpegSize = map?.getOutputSizes(ImageFormat.JPEG)?.minByOrNull { it.width * it.height }
            ?: android.util.Size(640, 480)
        imageReader = ImageReader.newInstance(jpegSize.width, jpegSize.height, ImageFormat.JPEG, 1)
        val session = createSessionBlocking(device, listOf(preview, imageReader!!.surface), timeoutSec = 8)
        captureSession = session
        startRepeatingPreview(device, session, preview)
        val latch = CountDownLatch(1)
        backgroundHandler.postDelayed({ latch.countDown() }, 150)
        latch.await(2, TimeUnit.SECONDS)
        try {
            session.stopRepeating()
        } catch (_: CameraAccessException) {
        }
    }
}
