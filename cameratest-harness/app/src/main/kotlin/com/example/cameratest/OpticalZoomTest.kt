package com.example.cameratest

import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CaptureResult
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Optical zoom / lens switching (telephoto, ultrawide).
 *
 * Args: camera_id (logical rear camera), and either
 *   target_camera = physical or standalone camera id to switch to, or
 *   zoom_ratios = list of ratios (default: 1.0 plus the ratio of every physical lens).
 * capture (true), output_dir.
 * Each point reports the applied zoom ratio and the active physical lens.
 */
@RunWith(AndroidJUnit4::class)
open class OpticalZoomTest : HarnessTest() {

    @Test
    fun opticalZoom() {
        val cameraId = cameraArg() ?: return emitNotApplicable("no rear camera")
        val target = requireString("target_camera")
        val capture = optBool("capture", true)
        try {
            if (target != null) switchToTarget(cameraId, target, capture) else zoomSweep(cameraId, capture)
        } catch (e: Exception) {
            emitFailWith(describe(e), "camera_id" to cameraId)
        }
    }

    private fun switchToTarget(cameraId: String, target: String, capture: Boolean) {
        val lens = resolveLensTarget(cameraId, target)
            ?: return emitNotApplicable("lens $target not reachable from camera $cameraId", "camera_id" to cameraId)
        if (lens.method == LensTarget.CAMERA_ID) {
            val point = capturePoint(target, null, null, capture)
            val ok = point.optBoolean("ok")
            return emitResult(
                ok,
                point.optString("error").ifEmpty { null },
                "camera_id" to cameraId,
                "target_camera" to target,
                "switch_method" to lens.method,
                "switched" to ok,
                "target_equivalent_focal_mm" to equivalentFocal(target),
                "source_equivalent_focal_mm" to equivalentFocal(cameraId),
                "points" to JSONArray().put(point),
            )
        }
        val point = capturePoint(cameraId, lens.zoomRatio, target, capture)
        val switched = point.optString("active_physical_id") == target
        emitResult(
            point.optBoolean("ok") && (switched || !point.has("active_physical_id")),
            point.optString("error").ifEmpty { if (!switched) "active physical lens did not become $target" else null },
            "camera_id" to cameraId,
            "target_camera" to target,
            "switch_method" to lens.method,
            "zoom_ratio" to lens.zoomRatio?.toDouble(),
            "switched" to switched,
            "physical_id_reported" to point.has("active_physical_id"),
            "target_equivalent_focal_mm" to equivalentFocal(target),
            "source_equivalent_focal_mm" to equivalentFocal(cameraId),
            "points" to JSONArray().put(point),
        )
    }

    private fun zoomSweep(cameraId: String, capture: Boolean) {
        val range = zoomRange(cameraId)
            ?: return emitNotApplicable("camera $cameraId has no CONTROL_ZOOM_RATIO_RANGE", "camera_id" to cameraId)
        val physical = try {
            chars(cameraId).physicalCameraIds
        } catch (_: Exception) {
            emptySet()
        }
        val requested = listArg("zoom_ratios").mapNotNull { it.removeSuffix("x").toFloatOrNull() }
        val inRange = { r: Float -> r >= range.lower - 0.01f && r <= range.upper + 0.01f }
        val unsupported = requested.filterNot(inRange).map { "${it.toBigDecimal().stripTrailingZeros().toPlainString()}x" }
        val ratios = (requested.ifEmpty {
            (listOf(1f) + physical.mapNotNull { zoomForPhysical(cameraId, it) })
        }).filter(inRange).map { it.coerceIn(range.lower, range.upper) }.distinct().sorted()

        val points = JSONArray()
        for (label in unsupported) {
            points.put(JSONObject().put("requested_ratio", label).put("supported", false)
                .put("reason", "outside zoom range ${range.lower}-${range.upper}"))
        }
        if (ratios.isEmpty()) {
            return emitNotApplicable(
                "requested zoom ratios are outside ${range.lower}-${range.upper}; unsupported: ${unsupported.joinToString(", ")}",
                "camera_id" to cameraId,
                "zoom_range" to "${range.lower}-${range.upper}",
                "points" to points,
            )
        }
        val lensesSeen = LinkedHashSet<String>()
        var allOk = unsupported.isEmpty()
        var pointsOk = true
        for (ratio in ratios) {
            val p = capturePoint(cameraId, ratio, null, capture)
            points.put(p)
            if (!p.optBoolean("ok")) {
                allOk = false
                pointsOk = false
            }
            p.optString("active_physical_id").takeIf { it.isNotEmpty() }?.let(lensesSeen::add)
        }
        emitResult(
            allOk,
            listOfNotNull(
                unsupported.takeIf { it.isNotEmpty() }?.let { "unsupported: ${it.joinToString(", ")}" },
                "one or more zoom points failed".takeIf { !pointsOk },
            ).joinToString("; ").ifEmpty { null },
            "camera_id" to cameraId,
            "zoom_range" to "${range.lower}-${range.upper}",
            "physical_cameras" to physical.joinToString(","),
            "lens_switch_observed" to (lensesSeen.size > 1),
            "active_physical_ids" to lensesSeen.joinToString(","),
            "points" to points,
        )
    }

    /** Opens [cameraId], optionally zooms, optionally captures; always closes. */
    private fun capturePoint(cameraId: String, ratio: Float?, expectPhysical: String?, capture: Boolean): JSONObject {
        val p = JSONObject().put("camera_id", cameraId)
        ratio?.let { p.put("requested_ratio", it.toDouble()) }
        try {
            val reader = if (capture) {
                newJpegReader(jpegSizeFor(cameraId, requireString("resolution")) ?: error("no JPEG size"))
            } else {
                null
            }
            val monitor = ResultMonitor()
            val device = openCameraTracked(cameraId)
            val streamSink = createSink(cameraId)
            val session = startStream(device, streamSink, listOfNotNull(reader?.surface), monitor)
            streamSink.awaitFirstFrame(5000) ?: error("no preview frame")
            val result = if (ratio != null) {
                zoomTo(device, session, streamSink, monitor, ratio, expectPhysical, 4000)?.first
                    ?: monitor.latest
            } else {
                monitor.arm { true }
                monitor.await(1000)?.first
            }
            result?.get(CaptureResult.CONTROL_ZOOM_RATIO)?.let { p.put("applied_ratio", it.toDouble()) }
            activePhysicalId(result)?.let { p.put("active_physical_id", it) }
            result?.get(CaptureResult.LENS_FOCAL_LENGTH)?.let { p.put("focal_length_mm", it.toDouble()) }
            if (reader != null) {
                val shot = captureStill(device, session, reader) { b ->
                    ratio?.let { b.set(CaptureRequest.CONTROL_ZOOM_RATIO, it) }
                    b.set(CaptureRequest.JPEG_ORIENTATION, jpegOrientation(cameraId))
                }
                if (!shot.ok) error(shot.error ?: "capture failed")
                val dir = resolveOutputDir(requireString("output_dir"))
                val name = "zoom_${cameraId}_${ratio ?: 1f}_${System.currentTimeMillis()}.jpg"
                p.put("path", saveDurably(shot.bytes!!, dir, name).absolutePath)
            }
            p.put("ok", true)
        } catch (e: Exception) {
            p.put("ok", false).put("error", describe(e))
        } finally {
            closeStream()
        }
        return p
    }
}
