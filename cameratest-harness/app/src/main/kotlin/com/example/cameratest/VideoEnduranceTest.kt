package com.example.cameratest

import android.hardware.camera2.CameraDevice
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * Video endurance.
 *
 * operation:
 *  - start_stop  `cycles` clips of clip_duration_sec (2); each file must be readable.
 *                metric = completed cycles.
 *  - long        (default when duration_sec is given without cycles)
 *                continuous recording for duration_sec in segment_sec (300) files; each
 *                segment is verified and checked for timestamp gaps > 1 s.
 *                metric = seconds recorded without failure.
 * Args: camera_id, resolution, fps (30), output_dir, keep_files (false).
 */
@RunWith(AndroidJUnit4::class)
open class VideoEnduranceTest : VideoHarnessTest() {

    @Test
    fun videoEndurance() {
        val defaultOp = if (requireString("duration_sec") != null && requireString("cycles") == null) "long" else "start_stop"
        val op = optString("operation", defaultOp).lowercase()
        val cameraId = cameraArg() ?: return emitNotApplicable("no rear camera")
        val fps = optInt("fps", 30)
        val size = videoSizeFor(cameraId, requireString("resolution"))
            ?: return emitNotApplicable("resolution ${requireString("resolution")} not offered for video", "camera_id" to cameraId)
        val keep = optBool("keep_files", false)
        val dir = if (keep) resolveOutputDir(requireString("output_dir")) else appContext.cacheDir
        val health = SystemHealthMonitor(::shell)
        val start = SystemClock.elapsedRealtime()

        var completed = 0
        var failed = 0
        var consecutive = 0
        var thermalAbort = false
        var lastError: String? = null
        var recordedSec = 0.0
        var healthySec = 0.0
        var gaps = 0
        var device: CameraDevice? = null
        val requestedCycles: Int?
        val durationSec: Long?

        fun device(): CameraDevice = device ?: openCameraTracked(cameraId).also { device = it }
        fun fail(e: Exception) {
            failed++
            consecutive++
            lastError = describe(e)
            closeStream()
            device = null
        }

        if (op == "start_stop") {
            val cycles = optInt("cycles", 1000).coerceIn(1, 100_000)
            val clipMs = (optFloat("clip_duration_sec", 2f) * 1000).toLong().coerceAtLeast(500)
            requestedCycles = cycles
            durationSec = null
            for (i in 0 until cycles) {
                if (i % 10 == 0 && isThermalCritical()) {
                    thermalAbort = true
                    break
                }
                val file = File(dir, "video_cycle_$i.mp4")
                try {
                    val pipeline = recordClip(device(), cameraId, size, fps, file, clipMs, keepTimestamps = false)
                    pipeline.release()
                    readableDurationMs(file)?.let { recordedSec += it / 1000.0 } ?: error("clip $i is not readable")
                    completed++
                    consecutive = 0
                } catch (e: Exception) {
                    fail(e)
                } finally {
                    if (!keep) file.delete()
                }
                if (consecutive >= 10) break
            }
        } else if (op == "long") {
            val total = optLong("duration_sec", 3600).coerceIn(1, 24 * 3600)
            val segmentSec = optLong("segment_sec", 300).coerceIn(10, 3600)
            requestedCycles = null
            durationSec = total
            var segment = 0
            while (SystemClock.elapsedRealtime() - start < total * 1000 && !thermalAbort) {
                val remainingMs = total * 1000 - (SystemClock.elapsedRealtime() - start)
                val file = File(dir, "video_long_$segment.mp4")
                val t0 = SystemClock.elapsedRealtime()
                var pipeline: VideoPipeline? = null
                try {
                    val d = device()
                    pipeline = VideoPipeline(size.width, size.height, fps, file)
                    val session = createVideoSession(d, cameraId, pipeline)
                    session.setRepeatingRequest(videoRequest(d, cameraId, pipeline, fps), null, backgroundHandler)
                    pipeline.awaitFirstSample(5000) ?: error("no encoded frame within 5s")
                    val segEnd = t0 + minOf(segmentSec * 1000, remainingMs)
                    while (SystemClock.elapsedRealtime() < segEnd) {
                        Thread.sleep(minOf(5000L, maxOf(1L, segEnd - SystemClock.elapsedRealtime())))
                        if (isThermalCritical()) {
                            thermalAbort = true
                            break
                        }
                        pipeline.error?.let { error(it) }
                    }
                    stopEncoderTarget(d, session, cameraId, fps)
                    if (!pipeline.stop()) error(pipeline.error ?: "encoder did not reach end of stream")
                    if (!pipeline.finalizeFile()) error(pipeline.error ?: "segment not finalized")
                    val ts = pipeline.timestampsUs().sorted()
                    gaps += ts.zipWithNext().count { (a, b) -> b - a > 1_000_000L }
                    readableDurationMs(file)?.let { recordedSec += it / 1000.0 } ?: error("segment $segment is not readable")
                    healthySec += (SystemClock.elapsedRealtime() - t0) / 1000.0
                    completed++
                    consecutive = 0
                } catch (e: Exception) {
                    fail(e)
                } finally {
                    closeSessionOnly()
                    pipeline?.release()
                    if (!keep) file.delete()
                }
                segment++
                if (consecutive >= 3) break
            }
        } else {
            return emitFail("operation must be start_stop|long")
        }
        closeStream()

        val metric: Any = if (op == "long") healthySec else completed
        val pass = failed == 0 && !thermalAbort &&
            (requestedCycles == null || completed == requestedCycles)
        val fields = arrayListOf<Pair<String, Any?>>(
            "operation" to op,
            "completed_cycles" to completed,
            "requested_cycles" to requestedCycles,
            "duration_sec" to durationSec,
            "recorded_media_sec" to recordedSec,
            "timestamp_gaps" to gaps,
            "elapsed_sec" to (SystemClock.elapsedRealtime() - start) / 1000.0,
            "last_error" to lastError,
            "camera_id" to cameraId,
            "width" to size.width,
            "height" to size.height,
            "fps" to fps,
            "thermal_status_end" to thermalStatus(),
        )
        fields += cameraErrors.fields().toList()
        fields += health.fields(harnessPackages()).toList()
        emitEndurance(pass, metric, failed, thermalAbort, *fields.toTypedArray())
    }
}
