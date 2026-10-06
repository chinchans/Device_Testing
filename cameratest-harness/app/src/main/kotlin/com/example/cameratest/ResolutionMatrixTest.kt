package com.example.cameratest

import android.graphics.BitmapFactory
import android.graphics.ImageFormat
import android.hardware.camera2.CameraAccessException
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CaptureRequest
import android.media.ImageReader
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

@RunWith(AndroidJUnit4::class)
class ResolutionMatrixTest : BaseCamera2Test() {

    @Test
    fun matrix() {
        val cameraId = requireCameraId() ?: return emitFail("camera_id required")
        val resolutionsRaw = requireString("resolutions") ?: return emitFail("resolutions required")
        val format = optString("format", "JPEG").uppercase()
        if (format != "JPEG") {
            return emitSkip("only JPEG matrix supported in this harness build")
        }

        val sizes = parseResolutionsList(resolutionsRaw)
            ?: return emitFail("resolutions must be JSON array like [\"1920x1080\",\"1280x720\"]")
        if (sizes.isEmpty()) {
            return emitFail("resolutions list is empty")
        }
        if (sizes.size > 32) {
            return emitFail("too many resolutions (max 32)")
        }

        val outDir = resolveOutputDir(requireString("output_dir"))
        var tested = 0
        var passed = 0
        var failed = 0
        val details = JSONArray()

        try {
            val device = openCameraBlocking(cameraId)
            cameraDevice = device
            val chars = cameraManager.getCameraCharacteristics(cameraId)
            val map = chars.get(android.hardware.camera2.CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            val previewSize = choosePreviewSize(map)
            val preview = createPreviewSurface(previewSize.width, previewSize.height)

            for ((w, h) in sizes) {
                tested++
                val detail = JSONObject()
                detail.put("resolution", "${w}x${h}")
                if (!assertJpegSizeSupported(cameraId, w, h)) {
                    failed++
                    detail.put("result", "SKIPPED")
                    detail.put("error", "unsupported")
                    details.put(detail)
                    continue
                }

                val ok = captureAtSize(device, preview, cameraId, w, h, outDir, detail)
                if (ok) {
                    passed++
                    detail.put("result", "PASS")
                } else {
                    failed++
                    if (!detail.has("error")) detail.put("error", "capture failed")
                    detail.put("result", "FAIL")
                }
                details.put(detail)
                // Recreate reader each size; keep device open.
                try {
                    imageReader?.close()
                } catch (_: Exception) {
                }
                imageReader = null
            }

            val items = (0 until details.length()).map { details.getJSONObject(it) }
            val unsupported = items.filter { it.optString("result") == "SKIPPED" }.map { it.getString("resolution") }
            val broken = items.filter { it.optString("result") == "FAIL" }
                .map { "${it.getString("resolution")} (${it.optString("error", "capture failed")})" }
            val summary = listOfNotNull(
                unsupported.takeIf { it.isNotEmpty() }?.let { "unsupported: ${it.joinToString(", ")}" },
                broken.takeIf { it.isNotEmpty() }?.let { "failed: ${it.joinToString(", ")}" },
            ).joinToString("; ")
            val fields = mapOf("tested" to tested, "passed" to passed, "failed" to failed, "details" to details)
            when {
                failed == 0 -> emitPass(*fields.toList().toTypedArray())
                passed == 0 && broken.isEmpty() -> emit(mapOf("result" to "SKIPPED", "error" to summary) + fields)
                else -> emit(mapOf("result" to "FAIL", "error" to summary) + fields)
            }
        } catch (e: SecurityException) {
            emitFail("CAMERA permission not granted: ${e.message}")
        } catch (e: CameraAccessException) {
            emitFail("CameraAccessException: ${e.message}")
        } catch (e: Exception) {
            emitFail("Unexpected: ${e.message ?: e.javaClass.simpleName}")
        }
    }

    private fun parseResolutionsList(raw: String): List<Pair<Int, Int>>? {
        val trimmed = raw.trim()
        return try {
            when {
                trimmed.startsWith("[") -> {
                    val arr = JSONArray(trimmed)
                    (0 until arr.length()).mapNotNull { i ->
                        parseResolution(arr.getString(i))
                    }
                }
                trimmed.contains(",") && !trimmed.contains("x") -> null
                else -> {
                    // Also accept comma-separated WxH list without JSON brackets.
                    trimmed.split(",").map { it.trim() }.mapNotNull { parseResolution(it) }
                }
            }
        } catch (_: Exception) {
            null
        }
    }

    private fun captureAtSize(
        device: CameraDevice,
        preview: android.view.Surface,
        cameraId: String,
        w: Int,
        h: Int,
        outDir: File,
        detail: JSONObject,
    ): Boolean {
        val latch = CountDownLatch(1)
        val result = AtomicReference<Boolean>(false)

        try {
            try {
                captureSession?.close()
            } catch (_: Exception) {
            }
            captureSession = null

            imageReader = ImageReader.newInstance(w, h, ImageFormat.JPEG, 2).apply {
                setOnImageAvailableListener({ reader ->
                    try {
                        reader.acquireLatestImage()?.use { image ->
                            val buffer = image.planes[0].buffer
                            val bytes = ByteArray(buffer.remaining()).also { buffer.get(it) }
                            val file = File(outDir, "matrix_${w}x${h}_${System.currentTimeMillis()}.jpg")
                            file.writeBytes(bytes)
                            val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                            BitmapFactory.decodeFile(file.absolutePath, opts)
                            detail.put("image_path", file.absolutePath)
                            detail.put("width", opts.outWidth)
                            detail.put("height", opts.outHeight)
                            result.set(opts.outWidth > 0 && opts.outHeight > 0)
                        }
                    } catch (e: Exception) {
                        detail.put("error", e.message ?: "save failed")
                    } finally {
                        latch.countDown()
                    }
                }, backgroundHandler)
            }

            val readerSurface = imageReader!!.surface
            val session = createSessionBlocking(device, listOf(preview, readerSurface), timeoutSec = 10)
            captureSession = session
            startRepeatingPreview(device, session, preview)
            Thread.sleep(100)
            try {
                session.stopRepeating()
            } catch (_: Exception) {
            }
            val still = device.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
                addTarget(readerSurface)
                set(CaptureRequest.JPEG_ORIENTATION, jpegOrientation(cameraId))
            }.build()
            session.capture(still, null, backgroundHandler)
            if (!latch.await(15, TimeUnit.SECONDS)) {
                detail.put("error", "timeout")
                return false
            }
            return result.get()
        } catch (e: Exception) {
            detail.put("error", e.message ?: e.javaClass.simpleName)
            return false
        }
    }
}
