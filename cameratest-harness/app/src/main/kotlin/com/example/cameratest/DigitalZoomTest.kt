package com.example.cameratest

import android.graphics.ImageFormat
import android.graphics.Rect
import android.hardware.camera2.CameraAccessException
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CaptureResult
import android.hardware.camera2.TotalCaptureResult
import android.media.ImageReader
import android.os.Build
import android.util.Range
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.abs

@RunWith(AndroidJUnit4::class)
class DigitalZoomTest : BaseCamera2Test() {

    @Test
    fun zoomSweep() {
        val cameraId = requireCameraId() ?: return emitFail("camera_id required")
        val minZoom = requireString("min_zoom")?.toFloatOrNull()
            ?: return emitFail("min_zoom required")
        val maxZoom = requireString("max_zoom")?.toFloatOrNull()
            ?: return emitFail("max_zoom required")
        val steps = requireInt("steps") ?: return emitFail("steps required")
        val boundedSteps = steps.coerceIn(1, 64)

        if (maxZoom < minZoom) {
            return emitFail("max_zoom must be >= min_zoom")
        }

        try {
            val chars = cameraManager.getCameraCharacteristics(cameraId)
            val zoomRatioRange: Range<Float>? =
                if (Build.VERSION.SDK_INT >= 30) {
                    chars.get(CameraCharacteristics.CONTROL_ZOOM_RATIO_RANGE)
                } else {
                    null
                }
            val sensorRect = chars.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE)
                ?: return emitSkip("no active array size")
            val maxDigital = chars.get(CameraCharacteristics.SCALER_AVAILABLE_MAX_DIGITAL_ZOOM) ?: 1f

            if (zoomRatioRange == null && maxDigital <= 1.01f) {
                return emitSkip("digital zoom not supported on camera $cameraId")
            }

            val device = openCameraBlocking(cameraId)
            cameraDevice = device
            val map = chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            val previewSize = choosePreviewSize(map)
            val preview = createPreviewSurface(previewSize.width, previewSize.height)
            val jpegSize = map?.getOutputSizes(ImageFormat.JPEG)?.minByOrNull { it.width * it.height }
                ?: android.util.Size(640, 480)
            imageReader = ImageReader.newInstance(jpegSize.width, jpegSize.height, ImageFormat.JPEG, 2)
            val session = createSessionBlocking(device, listOf(preview, imageReader!!.surface))
            captureSession = session

            var requested = 0
            var applied = 0
            var failed = 0

            for (i in 0 until boundedSteps) {
                requested++
                val t = if (boundedSteps == 1) 0f else i.toFloat() / (boundedSteps - 1).toFloat()
                val requestedZoom = minZoom + (maxZoom - minZoom) * t
                val clamped = when {
                    zoomRatioRange != null -> requestedZoom.coerceIn(zoomRatioRange.lower, zoomRatioRange.upper)
                    else -> requestedZoom.coerceIn(1f, maxDigital)
                }

                val latch = CountDownLatch(1)
                val appliedFlag = AtomicInteger(0)

                val builder = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                    addTarget(preview)
                    if (Build.VERSION.SDK_INT >= 30 && zoomRatioRange != null) {
                        set(CaptureRequest.CONTROL_ZOOM_RATIO, clamped)
                    } else {
                        set(CaptureRequest.SCALER_CROP_REGION, cropForZoom(sensorRect, clamped))
                    }
                }

                session.setRepeatingRequest(
                    builder.build(),
                    object : android.hardware.camera2.CameraCaptureSession.CaptureCallback() {
                        override fun onCaptureCompleted(
                            session: android.hardware.camera2.CameraCaptureSession,
                            request: CaptureRequest,
                            result: TotalCaptureResult,
                        ) {
                            val ok = if (Build.VERSION.SDK_INT >= 30 && zoomRatioRange != null) {
                                val got = result.get(CaptureResult.CONTROL_ZOOM_RATIO)
                                got != null && abs(got - clamped) <= 0.15f
                            } else {
                                val crop = result.get(CaptureResult.SCALER_CROP_REGION)
                                crop != null && crop.width() > 0
                            }
                            if (ok) appliedFlag.set(1)
                            latch.countDown()
                        }

                        override fun onCaptureFailed(
                            session: android.hardware.camera2.CameraCaptureSession,
                            request: CaptureRequest,
                            failure: android.hardware.camera2.CaptureFailure,
                        ) {
                            latch.countDown()
                        }
                    },
                    backgroundHandler,
                )

                if (!latch.await(5, TimeUnit.SECONDS)) {
                    failed++
                } else if (appliedFlag.get() == 1) {
                    applied++
                } else {
                    failed++
                }
            }

            emitPass(
                "requested_steps" to requested,
                "applied_steps" to applied,
                "failed_steps" to failed,
            )
        } catch (e: SecurityException) {
            emitFail("CAMERA permission not granted: ${e.message}")
        } catch (e: CameraAccessException) {
            emitFail("CameraAccessException: ${e.message}")
        } catch (e: Exception) {
            emitFail("Unexpected: ${e.message ?: e.javaClass.simpleName}")
        }
    }

    private fun cropForZoom(sensor: Rect, zoom: Float): Rect {
        val z = zoom.coerceAtLeast(1f)
        val centerX = sensor.centerX()
        val centerY = sensor.centerY()
        val halfW = (sensor.width() / (2f * z)).toInt().coerceAtLeast(1)
        val halfH = (sensor.height() / (2f * z)).toInt().coerceAtLeast(1)
        return Rect(
            (centerX - halfW).coerceAtLeast(sensor.left),
            (centerY - halfH).coerceAtLeast(sensor.top),
            (centerX + halfW).coerceAtMost(sensor.right),
            (centerY + halfH).coerceAtMost(sensor.bottom),
        )
    }
}
