package com.example.cameratest

import android.graphics.BitmapFactory
import android.graphics.ImageFormat
import android.hardware.camera2.CameraAccessException
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CaptureRequest
import android.media.ImageReader
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

@RunWith(AndroidJUnit4::class)
class PhotoCaptureTest : BaseCamera2Test() {

    @Test
    fun capturePhoto() {
        val cameraId = requireCameraId() ?: return emitFail("camera_id required")
        val resolution = requireString("resolution") ?: return emitFail("resolution required")
        val format = optString("format", "JPEG").uppercase()
        val outputDirArg = requireString("output_dir")

        if (format != "JPEG" && format != "HEIC") {
            return emitFail("unsupported format: $format (use JPEG or HEIC)")
        }
        // HEIC is not universally available via ImageReader; fall back messaging.
        if (format == "HEIC") {
            return emitSkip("HEIC capture not supported by this harness build; use JPEG")
        }

        val (w, h) = parseResolution(resolution)
            ?: return emitFail("invalid resolution: $resolution")

        if (!assertJpegSizeSupported(cameraId, w, h)) {
            return emitSkip("resolution ${w}x${h} not supported for JPEG on camera $cameraId")
        }

        val outDir = resolveOutputDir(outputDirArg)
        val latch = CountDownLatch(1)
        val resultRef = AtomicReference<Map<String, Any?>?>()
        val startNs = System.nanoTime()

        try {
            val device = openCameraBlocking(cameraId)
            cameraDevice = device

            val chars = cameraManager.getCameraCharacteristics(cameraId)
            val map = chars.get(android.hardware.camera2.CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            val previewSize = choosePreviewSize(map)
            val preview = createPreviewSurface(previewSize.width, previewSize.height)

            imageReader = ImageReader.newInstance(w, h, ImageFormat.JPEG, /*maxImages*/ 2).apply {
                setOnImageAvailableListener({ reader ->
                    try {
                        val image = reader.acquireLatestImage()
                            ?: run {
                                resultRef.set(mapOf("__error" to "null image from reader"))
                                latch.countDown()
                                return@setOnImageAvailableListener
                            }
                        image.use { img ->
                            val buffer = img.planes[0].buffer
                            val bytes = ByteArray(buffer.remaining()).also { buffer.get(it) }
                            val file = File(outDir, "photo_${System.currentTimeMillis()}.jpg")
                            file.writeBytes(bytes)
                            val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                            BitmapFactory.decodeFile(file.absolutePath, opts)
                            resultRef.set(
                                mapOf(
                                    "image_path" to file.absolutePath,
                                    "width" to opts.outWidth,
                                    "height" to opts.outHeight,
                                    "format" to format,
                                    "latency_ms" to ((System.nanoTime() - startNs) / 1_000_000L).toInt(),
                                ),
                            )
                        }
                    } catch (e: Exception) {
                        resultRef.set(mapOf("__error" to (e.message ?: e.javaClass.simpleName)))
                    } finally {
                        latch.countDown()
                    }
                }, backgroundHandler)
            }

            val readerSurface = imageReader!!.surface
            val session = createSessionBlocking(device, listOf(preview, readerSurface))
            captureSession = session
            startRepeatingPreview(device, session, preview)

            // Brief warm-up so AF/AE settle before still capture.
            Thread.sleep(200)

            val still = device.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
                addTarget(readerSurface)
                set(
                    CaptureRequest.CONTROL_AF_MODE,
                    CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE,
                )
                set(CaptureRequest.JPEG_ORIENTATION, jpegOrientation(cameraId))
            }.build()

            try {
                session.stopRepeating()
            } catch (_: Exception) {
            }

            session.capture(
                still,
                object : CameraCaptureSession.CaptureCallback() {
                    override fun onCaptureFailed(
                        session: CameraCaptureSession,
                        request: CaptureRequest,
                        failure: android.hardware.camera2.CaptureFailure,
                    ) {
                        resultRef.set(mapOf("__error" to "capture failed reason=${failure.reason}"))
                        latch.countDown()
                    }
                },
                backgroundHandler,
            )
        } catch (e: SecurityException) {
            return emitFail("CAMERA permission not granted: ${e.message}")
        } catch (e: CameraAccessException) {
            return emitFail("CameraAccessException: ${e.message}")
        } catch (e: Exception) {
            return emitFail("Unexpected: ${e.message ?: e.javaClass.simpleName}")
        }

        if (!latch.await(30, TimeUnit.SECONDS)) {
            return emitFail("timeout waiting for capture")
        }

        val final = resultRef.get()
        when {
            final == null -> emitFail("no capture result")
            final["__error"] != null -> emitFail(final["__error"].toString())
            else -> emitPass(*final.toList().toTypedArray())
        }
    }
}
