package com.example.cameratest

import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.io.RandomAccessFile

/**
 * Video performance.
 *
 * mode:
 *  - start     record request → first encoded sample (iterations)
 *  - finalize  stop request → MP4 finalized and synced (iterations × duration_sec clips)
 *  - fps       one duration_sec recording; per-second FPS windows from presentation timestamps
 * Args: camera_id, resolution, fps (30), duration_sec, iterations (10), fps_tolerance_pct (5).
 */
@RunWith(AndroidJUnit4::class)
open class VideoPerfTest : VideoHarnessTest() {

    @Test
    fun videoPerf() {
        val mode = optString("mode", "start").lowercase()
        val cameraId = cameraArg() ?: return emitNotApplicable("no rear camera")
        val fps = optInt("fps", 30)
        val size = videoSizeFor(cameraId, requireString("resolution"))
            ?: return emitNotApplicable("resolution ${requireString("resolution")} not offered for video", "camera_id" to cameraId)
        if (fpsRangeFor(cameraId, fps) == null) {
            return emitNotApplicable("camera $cameraId has no AE range containing $fps fps", "camera_id" to cameraId)
        }
        val common = arrayOf<Pair<String, Any?>>(
            "mode" to mode,
            "camera_id" to cameraId,
            "width" to size.width,
            "height" to size.height,
            "fps" to fps,
        )
        try {
            when (mode) {
                "start" -> startLatency(cameraId, size, fps, common)
                "finalize" -> finalizeLatency(cameraId, size, fps, common)
                "fps" -> fpsStability(cameraId, size, fps, common)
                else -> emitFail("mode must be start|finalize|fps")
            }
        } catch (e: Exception) {
            emitFailWith(describe(e), *common)
        }
    }

    private fun emitLatency(samples: List<Double>, iterations: Int, lastError: String?, common: Array<Pair<String, Any?>>, thermalStart: Int) {
        val p95 = Stats.percentile(samples, 95.0)
        emitMetrics(
            p95,
            samples.size,
            Stats.mean(samples),
            "p95_latency_ms" to p95,
            *Stats.summary("latency", samples),
            "iterations_requested" to iterations,
            "failures" to iterations - samples.size,
            "last_error" to lastError,
            "thermal_status_start" to thermalStart,
            "thermal_status_end" to thermalStatus(),
            *common,
            pass = samples.size == iterations,
        )
    }

    private fun startLatency(cameraId: String, size: android.util.Size, fps: Int, common: Array<Pair<String, Any?>>) {
        val iterations = optInt("iterations", 10).coerceIn(1, 200)
        val thermalStart = thermalStatus()
        val device = openCameraTracked(cameraId)
        val samples = ArrayList<Double>()
        var lastError: String? = null
        for (i in 0 until iterations + 1) {
            val file = File(appContext.cacheDir, "start_perf_$i.mp4")
            var pipeline: VideoPipeline? = null
            try {
                pipeline = VideoPipeline(size.width, size.height, fps, file, keepTimestamps = false)
                val session = createVideoSession(device, cameraId, pipeline)
                session.setRepeatingRequest(videoRequest(device, cameraId, null, fps), null, backgroundHandler)
                sink?.awaitFirstFrame(5000) ?: error("no preview frame")
                val t0 = SystemClock.elapsedRealtimeNanos()
                session.setRepeatingRequest(videoRequest(device, cameraId, pipeline, fps), null, backgroundHandler)
                val first = pipeline.awaitFirstSample(5000) ?: error("no encoded frame within 5s")
                if (i > 0) samples += (first - t0) / 1e6
                Thread.sleep(500)
                stopEncoderTarget(device, session, cameraId, fps)
                pipeline.stop()
                pipeline.finalizeFile()
            } catch (e: Exception) {
                lastError = describe(e)
            } finally {
                closeSessionOnly()
                pipeline?.release()
                file.delete()
            }
        }
        emitLatency(samples, iterations, lastError, common, thermalStart)
    }

    private fun finalizeLatency(cameraId: String, size: android.util.Size, fps: Int, common: Array<Pair<String, Any?>>) {
        val iterations = optInt("iterations", 10).coerceIn(1, 200)
        val durationSec = optInt("duration_sec", 10).coerceIn(1, 600)
        val thermalStart = thermalStatus()
        val device = openCameraTracked(cameraId)
        val samples = ArrayList<Double>()
        var lastError: String? = null
        var unreadable = 0
        for (i in 0 until iterations) {
            val file = File(appContext.cacheDir, "finalize_perf_$i.mp4")
            var pipeline: VideoPipeline? = null
            try {
                pipeline = VideoPipeline(size.width, size.height, fps, file, keepTimestamps = false)
                val session = createVideoSession(device, cameraId, pipeline)
                session.setRepeatingRequest(videoRequest(device, cameraId, pipeline, fps), null, backgroundHandler)
                pipeline.awaitFirstSample(5000) ?: error("no encoded frame within 5s")
                Thread.sleep(durationSec * 1000L)
                val t0 = SystemClock.elapsedRealtimeNanos()
                stopEncoderTarget(device, session, cameraId, fps)
                if (!pipeline.stop()) error(pipeline.error ?: "encoder did not reach end of stream")
                if (!pipeline.finalizeFile()) error(pipeline.error ?: "file not finalized")
                RandomAccessFile(file, "rw").use { it.fd.sync() }
                val t1 = SystemClock.elapsedRealtimeNanos()
                if (readableDurationMs(file) == null) {
                    unreadable++
                    error("finalized file is not readable")
                }
                samples += (t1 - t0) / 1e6
            } catch (e: Exception) {
                lastError = describe(e)
            } finally {
                closeSessionOnly()
                pipeline?.release()
                file.delete()
            }
        }
        emitLatency(samples, iterations, lastError, common + arrayOf("duration_sec" to durationSec, "unreadable_files" to unreadable), thermalStart)
    }

    private fun fpsStability(cameraId: String, size: android.util.Size, fps: Int, common: Array<Pair<String, Any?>>) {
        val durationSec = optInt("duration_sec", 60).coerceIn(2, 3600)
        val tolerancePct = optFloat("fps_tolerance_pct", 5f).toDouble()
        val thermalStart = thermalStatus()
        val device = openCameraTracked(cameraId)
        val file = File(appContext.cacheDir, "fps_perf.mp4")
        val pipeline = recordClip(device, cameraId, size, fps, file, durationSec * 1000L)
        try {
            val analysis = FpsAnalysis(pipeline.timestampsUs(), fps, tolerancePct)
            val windows = analysis.windowFps
            emitMetrics(
                analysis.withinTolerancePercent,
                windows.size,
                if (analysis.averageFps > 0) 1000.0 / analysis.averageFps else Double.NaN,
                "fps_within_tolerance_percent" to analysis.withinTolerancePercent,
                "average_fps" to analysis.averageFps,
                "min_window_fps" to (windows.minOrNull() ?: Double.NaN),
                "max_window_fps" to (windows.maxOrNull() ?: Double.NaN),
                "fps_tolerance_pct" to tolerancePct,
                "encoded_frames" to pipeline.encodedFrames,
                "duration_sec" to durationSec,
                "thermal_status_start" to thermalStart,
                "thermal_status_end" to thermalStatus(),
                *common,
                pass = windows.size >= durationSec - 1,
            )
        } finally {
            pipeline.release()
            file.delete()
        }
    }
}
