package com.example.cameratest

import android.graphics.BitmapFactory
import android.graphics.ImageFormat
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CaptureRequest
import android.util.Size
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.abs

/**
 * Photo aspect ratios.
 *
 * Args: camera_id, aspect_ratios (default "4:3,16:9,1:1"), output_dir.
 * For each ratio the largest matching JPEG size is captured and the decoded file's
 * dimensions are compared with the ratio. Ratios with no matching size are reported
 * as supported=false (not a failure).
 */
@RunWith(AndroidJUnit4::class)
open class AspectRatioCaptureTest : HarnessTest() {

    @Test
    fun aspectRatios() {
        val cameraId = cameraArg() ?: return emitNotApplicable("no camera")
        val ratios = listArg("aspect_ratios").ifEmpty { listOf("4:3", "16:9", "1:1") }
        val sizes = chars(cameraId).get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            ?.getOutputSizes(ImageFormat.JPEG)?.toList()
            ?: return emitFail("no JPEG sizes for camera $cameraId")
        val dir = resolveOutputDir(requireString("output_dir"))

        val points = JSONArray()
        val unsupported = mutableListOf<String>()
        var tested = 0
        var passed = 0
        for (label in ratios) {
            val value = ratioValue(label)
            val p = JSONObject().put("aspect_ratio", label)
            points.put(p)
            if (value == null) {
                p.put("supported", false).put("error", "unparseable ratio")
                unsupported += label
                continue
            }
            val size = sizes.filter { abs(it.width.toDouble() / it.height - value) <= 0.02 * value }
                .maxByOrNull { it.width.toLong() * it.height }
            if (size == null) {
                p.put("supported", false)
                unsupported += label
                continue
            }
            p.put("supported", true).put("width", size.width).put("height", size.height)
            tested++
            try {
                val bytes = captureAt(cameraId, size)
                val file = saveDurably(bytes, dir, "aspect_${label.replace(':', 'x')}_${System.currentTimeMillis()}.jpg")
                val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeFile(file.absolutePath, opts)
                val w = maxOf(opts.outWidth, opts.outHeight)
                val h = minOf(opts.outWidth, opts.outHeight)
                val actual = if (h > 0) w.toDouble() / h else 0.0
                val expected = maxOf(value, 1.0 / value)
                val matches = abs(actual - expected) <= 0.02 * expected
                p.put("path", file.absolutePath)
                    .put("decoded_width", opts.outWidth)
                    .put("decoded_height", opts.outHeight)
                    .put("ratio_matches", matches)
                if (matches) passed++
            } catch (e: Exception) {
                p.put("error", describe(e))
            } finally {
                closeStream()
            }
        }
        if (tested == 0) {
            return emitNotApplicable(
                "no JPEG size matches any requested ratio; unsupported: ${unsupported.joinToString(", ")}",
                "camera_id" to cameraId,
                "points" to points,
            )
        }
        val ok = passed == tested && unsupported.isEmpty()
        emitResult(
            ok,
            listOfNotNull(
                unsupported.takeIf { it.isNotEmpty() }?.let { "unsupported: ${it.joinToString(", ")}" },
                (tested - passed).takeIf { it > 0 }?.let { "$it ratio(s) failed" },
            ).joinToString("; ").ifEmpty { null },
            "camera_id" to cameraId,
            "ratios_tested" to tested,
            "ratios_passed" to passed,
            "points" to points,
        )
    }

    private fun ratioValue(label: String): Double? {
        val parts = label.split(':', '/', 'x')
        if (parts.size != 2) return label.toDoubleOrNull()
        val a = parts[0].trim().toDoubleOrNull() ?: return null
        val b = parts[1].trim().toDoubleOrNull() ?: return null
        return if (b > 0) a / b else null
    }

    private fun captureAt(cameraId: String, size: Size): ByteArray {
        val reader = newJpegReader(size)
        val device = openCameraTracked(cameraId)
        val streamSink = createSink(cameraId)
        val session = startStream(device, streamSink, listOf(reader.surface))
        streamSink.awaitFirstFrame(5000) ?: error("no preview frame")
        val shot = captureStill(device, session, reader) {
            it.set(CaptureRequest.JPEG_ORIENTATION, jpegOrientation(cameraId))
        }
        if (!shot.ok) error(shot.error ?: "capture failed")
        return shot.bytes!!
    }
}
