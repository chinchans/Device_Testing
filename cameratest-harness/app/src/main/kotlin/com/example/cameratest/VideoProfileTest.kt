package com.example.cameratest

import android.media.MediaMetadataRetriever
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import kotlin.math.abs

/**
 * Video resolution / frame-rate profiles.
 *
 * Args: camera_id, profiles = list of "WxH@fps" (or resolutions = list of "WxH" with fps),
 * fps (30), duration_sec (5), fps_tolerance (percent, 10), output_dir, keep_files (true).
 * Each profile is recorded with MediaCodec; the file is re-opened to check dimensions and
 * duration, and the average FPS is computed from presentation timestamps.
 */
@RunWith(AndroidJUnit4::class)
open class VideoProfileTest : VideoHarnessTest() {

    @Test
    fun videoProfiles() {
        val cameraId = cameraArg() ?: return emitNotApplicable("no camera")
        val defaultFps = optInt("fps", 30)
        val durationSec = optInt("duration_sec", optInt("test_duration_sec", 5)).coerceIn(1, 600)
        val tolerancePct = optFloat("fps_tolerance", 10f).toDouble()
        val keepFiles = optBool("keep_files", true)
        val profiles = (listArg("profiles").ifEmpty { listArg("resolutions") }).ifEmpty {
            listOf(requireString("resolution") ?: "1920x1080")
        }.map { parseProfile(it, defaultFps) }

        val dir = resolveOutputDir(requireString("output_dir"))
        val points = JSONArray()
        val unsupported = mutableListOf<String>()
        var tested = 0
        var passed = 0
        for ((label, res, fps) in profiles) {
            val p = JSONObject().put("profile", label).put("fps", fps)
            points.put(p)
            val size = res?.let { videoSizeFor(cameraId, it) }
            val range = fpsRangeFor(cameraId, fps)
            if (size == null || range == null) {
                p.put("supported", false)
                    .put("reason", if (size == null) "resolution not offered for encoder" else "no AE fps range for $fps")
                unsupported += label
                continue
            }
            p.put("supported", true).put("width", size.width).put("height", size.height)
                .put("ae_fps_range", "${range.lower}-${range.upper}")
            tested++
            val file = File(dir, "video_${size.width}x${size.height}_${fps}_${System.currentTimeMillis()}.mp4")
            var pipeline: VideoPipeline? = null
            try {
                pipeline = VideoPipeline(size.width, size.height, fps, file)
                val device = openCameraTracked(cameraId)
                val session = createVideoSession(device, cameraId, pipeline)
                session.setRepeatingRequest(videoRequest(device, cameraId, pipeline, fps), null, backgroundHandler)
                pipeline.awaitFirstSample(5000) ?: error("no encoded frame within 5s")
                Thread.sleep(durationSec * 1000L)
                stopEncoderTarget(device, session, cameraId, fps)
                if (!pipeline.stop()) error(pipeline.error ?: "encoder did not reach end of stream")
                if (!pipeline.finalizeFile()) error(pipeline.error ?: "file not finalized")

                val analysis = FpsAnalysis(pipeline.timestampsUs(), fps, tolerancePct)
                val (w, h) = dimensions(file)
                val durationMs = readableDurationMs(file)
                val dimsOk = (w == size.width && h == size.height) || (w == size.height && h == size.width)
                val fpsOk = analysis.averageFps.isFinite() &&
                    abs(analysis.averageFps - fps) <= fps * tolerancePct / 100.0
                val ok = dimsOk && durationMs != null && fpsOk
                p.put("recorded", true)
                    .put("file_width", w)
                    .put("file_height", h)
                    .put("duration_ms", durationMs ?: JSONObject.NULL)
                    .put("encoded_frames", pipeline.encodedFrames)
                    .put("average_fps", Stats.round2(analysis.averageFps).takeIf { it.isFinite() } ?: JSONObject.NULL)
                    .put("fps_within_tolerance", fpsOk)
                    .put("ok", ok)
                    .put("path", if (keepFiles) file.absolutePath else JSONObject.NULL)
                if (ok) passed++
            } catch (e: Exception) {
                p.put("recorded", false).put("ok", false).put("error", describe(e))
            } finally {
                closeStream()
                pipeline?.release()
                if (!keepFiles) file.delete()
            }
        }
        if (tested == 0) {
            return emitNotApplicable(
                "none of the requested video profiles is supported; unsupported: ${unsupported.joinToString(", ")}",
                "camera_id" to cameraId,
                "points" to points,
            )
        }
        val ok = passed == tested && unsupported.isEmpty()
        emitResult(
            ok,
            listOfNotNull(
                unsupported.takeIf { it.isNotEmpty() }?.let { "unsupported: ${it.joinToString(", ")}" },
                (tested - passed).takeIf { it > 0 }?.let { "$it profile(s) failed" },
            ).joinToString("; ").ifEmpty { null },
            "camera_id" to cameraId,
            "profiles_tested" to tested,
            "profiles_passed" to passed,
            "duration_sec" to durationSec,
            "points" to points,
        )
    }

    private data class Profile(val label: String, val resolution: String?, val fps: Int)

    private fun parseProfile(raw: String, defaultFps: Int): Profile {
        val res = parseResolution(raw)?.let { "${it.first}x${it.second}" }
        val fps = Regex("@\\s*(\\d+)").find(raw)?.groupValues?.get(1)?.toIntOrNull() ?: defaultFps
        return Profile(raw, res, fps)
    }

    private fun dimensions(file: File): Pair<Int?, Int?> {
        val r = MediaMetadataRetriever()
        return try {
            r.setDataSource(file.absolutePath)
            r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)?.toIntOrNull() to
                r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)?.toIntOrNull()
        } catch (_: Exception) {
            null to null
        } finally {
            try {
                r.release()
            } catch (_: Exception) {
            }
        }
    }
}
