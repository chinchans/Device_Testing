package com.example.cameratest

import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureFailure
import android.hardware.camera2.CaptureRequest
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * Burst capture: exactly `count` still requests submitted as one burst.
 *
 * Args: camera_id, resolution, count (30).
 * metric_value = throughput_fps (IMAGE_AVAILABLE events per second from submit to last image),
 * latency_ms = p95_inter_frame_ms.
 */
@RunWith(AndroidJUnit4::class)
open class BurstPerfTest : HarnessTest() {

    @Test
    fun burst() {
        val cameraId = cameraArg() ?: return emitNotApplicable("no rear camera")
        val count = optInt("count", 30).coerceIn(2, 500)
        val size = jpegSizeFor(cameraId, requireString("resolution"))
            ?: return emitNotApplicable("resolution ${requireString("resolution")} not supported", "camera_id" to cameraId)
        val burstCapable = chars(cameraId).get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES)
            ?.contains(CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_BURST_CAPTURE) == true
        val thermalStart = thermalStatus()
        try {
            val reader = newJpegReader(size, 8)
            val times = ArrayList<Long>(count)
            val latch = CountDownLatch(count)
            reader.setOnImageAvailableListener({ r ->
                val img = try {
                    r.acquireNextImage()
                } catch (_: Exception) {
                    null
                } ?: return@setOnImageAvailableListener
                val now = SystemClock.elapsedRealtimeNanos()
                img.close()
                synchronized(times) { times += now }
                latch.countDown()
            }, backgroundHandler)

            val device = openCameraTracked(cameraId)
            val streamSink = createSink(cameraId)
            val session = startStream(device, streamSink, listOf(reader.surface))
            streamSink.awaitFirstFrame(5000) ?: return emitFail("no preview frame")
            Thread.sleep(500)

            val requests = (1..count).map {
                device.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
                    addTarget(reader.surface)
                    set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                }.build()
            }
            val failures = AtomicInteger()
            val t0 = SystemClock.elapsedRealtimeNanos()
            session.captureBurst(
                requests,
                object : CameraCaptureSession.CaptureCallback() {
                    override fun onCaptureFailed(
                        session: CameraCaptureSession,
                        request: CaptureRequest,
                        failure: CaptureFailure,
                    ) {
                        failures.incrementAndGet()
                        latch.countDown()
                    }
                },
                backgroundHandler,
            )
            latch.await(count * 2000L + 5000L, TimeUnit.MILLISECONDS)
            val stamps = synchronized(times) { times.sorted() }
            val received = stamps.size
            val throughput = if (received > 0) received / ((stamps.last() - t0) / 1e9) else 0.0
            val inter = stamps.zipWithNext { a, b -> (b - a) / 1e6 }
            val p95Inter = Stats.percentile(inter, 95.0)
            emitMetrics(
                throughput,
                received,
                p95Inter,
                "throughput_fps" to throughput,
                "p95_inter_frame_ms" to p95Inter,
                *Stats.summary("inter_frame", inter),
                "first_image_ms" to stamps.firstOrNull()?.let { (it - t0) / 1e6 },
                "frames_requested" to count,
                "frames_received" to received,
                "capture_failures" to failures.get(),
                "burst_capture_capability" to burstCapable,
                "camera_id" to cameraId,
                "width" to size.width,
                "height" to size.height,
                "thermal_status_start" to thermalStart,
                "thermal_status_end" to thermalStatus(),
                pass = received == count && failures.get() == 0,
            )
        } catch (e: Exception) {
            emitFailWith(describe(e), "camera_id" to cameraId)
        }
    }
}
