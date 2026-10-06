package com.example.cameratest

import android.hardware.camera2.CaptureRequest
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * Resource usage.
 *
 * mode:
 *  - memory  capture `count` JPEGs while sampling process PSS every sample_interval_sec;
 *            reports baseline / peak / recovered PSS (no drop_caches). metric = growth MB.
 *  - cpu     record video for duration_sec while sampling system CPU busy % from /proc/stat.
 *            metric = average CPU %.
 * Args: camera_id, resolution, count (50), duration_sec (60), fps (30), sample_interval_sec (1).
 * latency_ms carries the mean capture time (memory) or the sampling interval (cpu).
 */
@RunWith(AndroidJUnit4::class)
open class ResourcePerfTest : VideoHarnessTest() {

    @Test
    fun resources() {
        val mode = optString("mode", "memory").lowercase()
        val cameraId = cameraArg() ?: return emitNotApplicable("no rear camera")
        try {
            when (mode) {
                "memory" -> memory(cameraId)
                "cpu" -> cpu(cameraId)
                else -> emitFail("mode must be memory|cpu")
            }
        } catch (e: Exception) {
            emitFailWith(describe(e), "mode" to mode, "camera_id" to cameraId)
        }
    }

    /** PSS in MB of a system process via dumpsys meminfo (null when unavailable). */
    private fun servicePssMb(process: String): Double? {
        val out = try {
            shell("dumpsys meminfo $process")
        } catch (_: Exception) {
            return null
        }
        val kb = Regex("TOTAL PSS:\\s+(\\d+)").find(out)?.groupValues?.get(1)?.toLongOrNull()
            ?: Regex("^\\s*TOTAL\\s+(\\d+)", RegexOption.MULTILINE).find(out)?.groupValues?.get(1)?.toLongOrNull()
        return kb?.let { it / 1024.0 }
    }

    private fun memory(cameraId: String) {
        val count = optInt("count", 50).coerceIn(1, 5000)
        val intervalMs = (optFloat("sample_interval_sec", 1f) * 1000).toLong().coerceAtLeast(200)
        val size = jpegSizeFor(cameraId, requireString("resolution"))
            ?: return emitNotApplicable("resolution ${requireString("resolution")} not supported", "camera_id" to cameraId)

        gcAndSettle()
        val baseline = pssMb()
        val serverBaseline = servicePssMb("cameraserver")
        val pss = ArrayList<Double>()
        val sampler = PeriodicSampler(intervalMs) { synchronized(pss) { pss += pssMb() } }
        val captureMs = ArrayList<Double>()
        var ok = 0
        var serverPeak: Double? = null
        try {
            val reader = newJpegReader(size, 2)
            val device = openCameraTracked(cameraId)
            val streamSink = createSink(cameraId)
            val session = startStream(device, streamSink, listOf(reader.surface))
            streamSink.awaitFirstFrame(5000) ?: error("no preview frame")
            for (i in 0 until count) {
                val shot = captureStill(device, session, reader) {
                    it.set(CaptureRequest.JPEG_ORIENTATION, jpegOrientation(cameraId))
                }
                if (shot.ok) {
                    ok++
                    captureMs += shot.shutterMs
                }
                if (i == count / 2) serverPeak = servicePssMb("cameraserver")
            }
        } finally {
            sampler.stop()
            closeStream()
        }
        gcAndSettle(2000)
        val recovered = pssMb()
        val peak = synchronized(pss) { pss.maxOrNull() } ?: recovered
        val growth = recovered - baseline
        val sampleCount = synchronized(pss) { pss.size }
        emitMetrics(
            growth,
            sampleCount,
            Stats.mean(captureMs),
            "memory_growth_mb" to growth,
            "baseline_pss_mb" to baseline,
            "peak_pss_mb" to peak,
            "recovered_pss_mb" to recovered,
            "peak_growth_mb" to peak - baseline,
            "cameraserver_pss_baseline_mb" to serverBaseline,
            "cameraserver_pss_mid_mb" to serverPeak,
            "cameraserver_pss_end_mb" to servicePssMb("cameraserver"),
            "captures_requested" to count,
            "captures_ok" to ok,
            "camera_id" to cameraId,
            "width" to size.width,
            "height" to size.height,
            "mode" to "memory",
            pass = ok == count,
        )
    }

    private fun cpu(cameraId: String) {
        val durationSec = optInt("duration_sec", 60).coerceIn(2, 3600)
        val fps = optInt("fps", 30)
        val intervalMs = (optFloat("sample_interval_sec", 1f) * 1000).toLong().coerceAtLeast(200)
        val size = videoSizeFor(cameraId, requireString("resolution"))
            ?: return emitNotApplicable("resolution ${requireString("resolution")} not offered for video", "camera_id" to cameraId)
        val thermalStart = thermalStatus()

        val cpu = CpuSampler(::shell)
        val busy = ArrayList<Double>()
        cpu.sample()
        val selfStart = selfCpuTicks()
        val wallStart = SystemClock.elapsedRealtime()
        val sampler = PeriodicSampler(intervalMs) { cpu.sample()?.let { v -> synchronized(busy) { busy += v } } }
        val file = File(appContext.cacheDir, "cpu_perf.mp4")
        var pipeline: VideoPipeline? = null
        try {
            val device = openCameraTracked(cameraId)
            pipeline = recordClip(device, cameraId, size, fps, file, durationSec * 1000L, keepTimestamps = false)
        } finally {
            sampler.stop()
            pipeline?.release()
            file.delete()
        }
        val wallMs = SystemClock.elapsedRealtime() - wallStart
        val selfCpuPct = selfCpuTicks()?.let { end ->
            selfStart?.let { start -> 100.0 * (end - start) * 10.0 / wallMs / Runtime.getRuntime().availableProcessors() }
        }
        val values = synchronized(busy) { ArrayList(busy) }
        val avg = Stats.mean(values)
        emitMetrics(
            avg,
            values.size,
            intervalMs.toDouble(),
            "average_cpu_percent" to avg,
            "peak_cpu_percent" to (values.maxOrNull() ?: Double.NaN),
            "p95_cpu_percent" to Stats.percentile(values, 95.0),
            "harness_process_cpu_percent" to selfCpuPct,
            "cpu_scope" to "system_wide_proc_stat",
            "duration_sec" to durationSec,
            "camera_id" to cameraId,
            "width" to size.width,
            "height" to size.height,
            "fps" to fps,
            "thermal_status_start" to thermalStart,
            "thermal_status_end" to thermalStatus(),
            "mode" to "cpu",
            pass = values.size >= (durationSec * 1000L / intervalMs / 2),
        )
    }

    /** utime + stime of this process in clock ticks (USER_HZ = 100 on Android). */
    private fun selfCpuTicks(): Long? =
        try {
            val fields = File("/proc/self/stat").readText().substringAfterLast(')').trim().split(' ')
            fields[11].toLong() + fields[12].toLong()
        } catch (_: Exception) {
            null
        }
}
