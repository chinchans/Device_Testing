package com.example.cameratest

import android.content.Context
import android.graphics.ImageFormat
import android.hardware.camera2.CameraAccessException
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CaptureRequest
import android.media.ImageReader
import android.os.PowerManager
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

@RunWith(AndroidJUnit4::class)
class RepeatedPhotoStressTest : BaseCamera2Test() {

    @Test
    fun stressPhotos() {
        val cameraId = requireCameraId() ?: return emitFail("camera_id required")
        val count = requireInt("count") ?: return emitFail("count required")
        val mode = optString("mode", "rapid").lowercase()
        val bounded = count.coerceIn(1, 1000)

        if (mode != "rapid" && mode != "preview_dwell") {
            return emitFail("mode must be rapid or preview_dwell")
        }

        var completed = 0
        var failures = 0
        var thermalAbort = false

        try {
            val chars = cameraManager.getCameraCharacteristics(cameraId)
            val map = chars.get(android.hardware.camera2.CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
                ?: return emitSkip("no stream config for camera $cameraId")
            val jpegSize = map.getOutputSizes(ImageFormat.JPEG)?.maxByOrNull { it.width * it.height }
                ?: return emitSkip("no JPEG sizes for camera $cameraId")
            val previewSize = choosePreviewSize(map)

            if (mode == "rapid") {
                val device = openCameraBlocking(cameraId)
                cameraDevice = device
                val preview = createPreviewSurface(previewSize.width, previewSize.height)
                imageReader = ImageReader.newInstance(
                    jpegSize.width,
                    jpegSize.height,
                    ImageFormat.JPEG,
                    /*maxImages*/ 2,
                )
                val readerSurface = imageReader!!.surface
                val session = createSessionBlocking(device, listOf(preview, readerSurface))
                captureSession = session
                startRepeatingPreview(device, session, preview)
                Thread.sleep(150)

                for (i in 1..bounded) {
                    if (i % 50 == 0 && isThermalSevere()) {
                        thermalAbort = true
                        break
                    }
                    val ok = captureOnce(device, session, readerSurface, timeoutSec = 10)
                    if (ok) completed++ else failures++
                    if (mode == "preview_dwell") {
                        // Not used in rapid path.
                    }
                }
            } else {
                // preview_dwell: reopen session periodically to flush handles.
                for (i in 1..bounded) {
                    if (i % 50 == 0 && isThermalSevere()) {
                        thermalAbort = true
                        break
                    }
                    try {
                        safeClose()
                        val device = openCameraBlocking(cameraId, timeoutSec = 8)
                        cameraDevice = device
                        val preview = createPreviewSurface(previewSize.width, previewSize.height)
                        imageReader = ImageReader.newInstance(
                            jpegSize.width,
                            jpegSize.height,
                            ImageFormat.JPEG,
                            2,
                        )
                        val readerSurface = imageReader!!.surface
                        val session = createSessionBlocking(device, listOf(preview, readerSurface), 8)
                        captureSession = session
                        startRepeatingPreview(device, session, preview)
                        Thread.sleep(100)
                        val ok = captureOnce(device, session, readerSurface, timeoutSec = 10)
                        if (ok) completed++ else failures++
                    } catch (_: Exception) {
                        failures++
                        safeClose()
                    }
                }
            }

            emitPass(
                "metric_value" to completed,
                "failures" to failures,
                "thermal_abort" to thermalAbort,
            )
        } catch (e: SecurityException) {
            emitFail("CAMERA permission not granted: ${e.message}")
        } catch (e: CameraAccessException) {
            emitFail("CameraAccessException: ${e.message}")
        } catch (e: Exception) {
            emitFail("Unexpected: ${e.message ?: e.javaClass.simpleName}")
        }
    }

    private fun captureOnce(
        device: CameraDevice,
        session: CameraCaptureSession,
        readerSurface: android.view.Surface,
        timeoutSec: Long,
    ): Boolean {
        val latch = CountDownLatch(1)
        val ok = AtomicInteger(0)
        val err = AtomicReference<String?>()

        imageReader?.setOnImageAvailableListener({ reader ->
            try {
                reader.acquireLatestImage()?.close()
                ok.set(1)
            } catch (e: Exception) {
                err.set(e.message)
            } finally {
                latch.countDown()
            }
        }, backgroundHandler)

        try {
            try {
                session.stopRepeating()
            } catch (_: Exception) {
            }
            val still = device.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
                addTarget(readerSurface)
            }.build()
            session.capture(still, null, backgroundHandler)
            // Restart preview for next rapid shot.
            previewSurface?.let { startRepeatingPreview(device, session, it) }
        } catch (e: Exception) {
            return false
        }

        if (!latch.await(timeoutSec, TimeUnit.SECONDS)) {
            return false
        }
        return ok.get() == 1
    }

    private fun isThermalSevere(): Boolean {
        return try {
            val pm = appContext.getSystemService(Context.POWER_SERVICE) as PowerManager
            pm.currentThermalStatus >= PowerManager.THERMAL_STATUS_SEVERE
        } catch (_: Exception) {
            false
        }
    }
}
