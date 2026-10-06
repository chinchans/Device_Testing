package com.example.cameratest

import android.app.UiAutomation
import android.content.Context
import android.graphics.ImageFormat
import android.hardware.camera2.CameraAccessException
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureFailure
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CaptureResult
import android.hardware.camera2.TotalCaptureResult
import android.hardware.camera2.params.MeteringRectangle
import android.media.Image
import android.media.ImageReader
import android.os.Debug
import android.os.Handler
import android.os.ParcelFileDescriptor
import android.os.PowerManager
import android.os.SystemClock
import android.util.Range
import android.util.Size
import android.view.Surface
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.After
import org.junit.Before
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.sqrt

/** Stable classification of why a camera could not be opened. */
object AccessReason {
    const val GRANTED = "GRANTED"
    const val DENIED_SECURITY = "DENIED_SECURITY_EXCEPTION"
    const val DENIED_DISABLED = "DENIED_CAMERA_DISABLED"
    const val BUSY = "CAMERA_BUSY"
    const val ERROR = "CAMERA_ERROR"
    const val TIMEOUT = "OPEN_TIMEOUT"
}

class CameraOpenException(val reason: String, message: String) : Exception(message)

/** Counts CameraDevice error callbacks for the lifetime of one operation. */
class CameraErrorTracker {
    private val fatal = AtomicInteger()
    private val service = AtomicInteger()
    private val device = AtomicInteger()
    private val disconnects = AtomicInteger()
    private val other = AtomicInteger()

    @Volatile
    var last: String? = null
        private set

    val fatalCount: Int get() = fatal.get()
    val serviceCount: Int get() = service.get()
    val disconnectCount: Int get() = disconnects.get()

    fun onError(code: Int) {
        when (code) {
            CameraDevice.StateCallback.ERROR_CAMERA_SERVICE -> {
                service.incrementAndGet()
                fatal.incrementAndGet()
            }
            CameraDevice.StateCallback.ERROR_CAMERA_DEVICE -> {
                device.incrementAndGet()
                fatal.incrementAndGet()
            }
            else -> other.incrementAndGet()
        }
        last = "camera error code=$code"
    }

    fun onDisconnected() {
        disconnects.incrementAndGet()
        last = "camera disconnected"
    }

    fun fields(): Array<Pair<String, Any?>> = arrayOf(
        "fatal_camera_errors" to fatal.get(),
        "camera_service_errors" to service.get(),
        "camera_device_errors" to device.get(),
        "camera_disconnects" to disconnects.get(),
        "other_camera_errors" to other.get(),
    )
}

/**
 * YUV ImageReader used as the "preview" output. Gives the exact time the first buffer
 * reaches the harness output surface, a running frame count and the mean luma
 * (used to detect privacy-blanked frames).
 */
class FrameSink(width: Int, height: Int, handler: Handler) {
    val reader: ImageReader = ImageReader.newInstance(width, height, ImageFormat.YUV_420_888, 3)
    val surface: Surface get() = reader.surface
    val size = Size(width, height)

    private val frames = AtomicInteger(0)
    private val firstFrameNs = AtomicLong(0)
    private val lastFrameNs = AtomicLong(0)
    private val lumaSum = AtomicLong(0)
    private val lumaSamples = AtomicInteger(0)
    private val darkSamples = AtomicInteger(0)

    @Volatile
    private var firstLatch = CountDownLatch(1)

    init {
        reader.setOnImageAvailableListener({ r ->
            val image = try {
                r.acquireLatestImage()
            } catch (_: Exception) {
                null
            } ?: return@setOnImageAvailableListener
            try {
                val now = SystemClock.elapsedRealtimeNanos()
                if (firstFrameNs.compareAndSet(0, now)) firstLatch.countDown()
                lastFrameNs.set(now)
                val n = frames.incrementAndGet()
                if (n <= 5 || n % 15 == 0) {
                    val luma = meanLuma(image)
                    lumaSum.addAndGet(luma.toLong())
                    lumaSamples.incrementAndGet()
                    if (luma < DARK_LUMA) darkSamples.incrementAndGet()
                }
            } finally {
                image.close()
            }
        }, handler)
    }

    fun reset() {
        frames.set(0)
        firstFrameNs.set(0)
        lastFrameNs.set(0)
        lumaSum.set(0)
        lumaSamples.set(0)
        darkSamples.set(0)
        firstLatch = CountDownLatch(1)
    }

    /** Elapsed-realtime ns of the first frame, or null on timeout. */
    fun awaitFirstFrame(timeoutMs: Long): Long? =
        if (firstLatch.await(timeoutMs, TimeUnit.MILLISECONDS)) firstFrameNs.get() else null

    fun frameCount(): Int = frames.get()
    fun lastFrameNs(): Long = lastFrameNs.get()

    /** Waits until at least [extra] more frames arrive; false on timeout. */
    fun awaitMoreFrames(extra: Int, timeoutMs: Long): Boolean {
        val target = frames.get() + extra
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            if (frames.get() >= target) return true
            Thread.sleep(20)
        }
        return frames.get() >= target
    }

    fun meanLuma(): Double =
        if (lumaSamples.get() == 0) -1.0 else lumaSum.get().toDouble() / lumaSamples.get()

    fun darkSampleCount(): Int = darkSamples.get()
    fun lumaSampleCount(): Int = lumaSamples.get()

    fun close() {
        try {
            reader.setOnImageAvailableListener(null, null)
            reader.close()
        } catch (_: Exception) {
        }
    }

    private fun meanLuma(image: Image): Int {
        val plane = image.planes[0]
        val buf = plane.buffer
        val rowStride = plane.rowStride
        val pixelStride = plane.pixelStride
        var sum = 0L
        var count = 0
        var y = 0
        while (y < image.height) {
            var x = 0
            while (x < image.width) {
                val idx = y * rowStride + x * pixelStride
                if (idx < buf.limit()) {
                    sum += (buf.get(idx).toInt() and 0xFF)
                    count++
                }
                x += 16
            }
            y += 16
        }
        return if (count == 0) 0 else (sum / count).toInt()
    }

    companion object {
        /** Mean Y below this is treated as a blank / blocked frame. */
        const val DARK_LUMA = 8
    }
}

/** Repeating-request callback that can wait for a result matching a predicate. */
class ResultMonitor : CameraCaptureSession.CaptureCallback() {
    @Volatile
    var latest: TotalCaptureResult? = null
        private set

    private val lock = Any()
    private var predicate: ((TotalCaptureResult) -> Boolean)? = null
    private var latch: CountDownLatch? = null
    private var matched: TotalCaptureResult? = null
    private var matchedNs = 0L
    private val failures = AtomicInteger(0)

    val failureCount: Int get() = failures.get()

    fun arm(condition: (TotalCaptureResult) -> Boolean) {
        synchronized(lock) {
            predicate = condition
            latch = CountDownLatch(1)
            matched = null
            matchedNs = 0L
        }
    }

    /** Result + elapsed-realtime ns when it arrived, or null on timeout. */
    fun await(timeoutMs: Long): Pair<TotalCaptureResult, Long>? {
        val l = synchronized(lock) { latch } ?: return null
        if (!l.await(timeoutMs, TimeUnit.MILLISECONDS)) {
            synchronized(lock) { predicate = null }
            return null
        }
        return synchronized(lock) { matched?.let { it to matchedNs } }
    }

    override fun onCaptureCompleted(
        session: CameraCaptureSession,
        request: CaptureRequest,
        result: TotalCaptureResult,
    ) {
        val now = SystemClock.elapsedRealtimeNanos()
        latest = result
        synchronized(lock) {
            val p = predicate ?: return
            if (p(result)) {
                matched = result
                matchedNs = now
                predicate = null
                latch?.countDown()
            }
        }
    }

    override fun onCaptureFailed(
        session: CameraCaptureSession,
        request: CaptureRequest,
        failure: CaptureFailure,
    ) {
        failures.incrementAndGet()
    }
}

class LensTarget(val method: String, val sourceId: String, val targetId: String, val zoomRatio: Float?) {
    companion object {
        const val ZOOM_RATIO = "zoom_ratio"
        const val CAMERA_ID = "camera_id"
    }
}

/** Timing of one still capture on the elapsed-realtime clock. */
class StillCapture(
    val requestNs: Long,
    val completedNs: Long,
    val imageNs: Long,
    val bytes: ByteArray?,
    val result: TotalCaptureResult?,
    val error: String?,
) {
    val ok: Boolean get() = error == null && bytes != null

    /** CAPTURE_REQUEST → IMAGE_AVAILABLE. */
    val shutterMs: Double get() = (imageNs - requestNs) / 1e6

    /** CAPTURE_COMPLETED → IMAGE_AVAILABLE (0 when the image arrives first). */
    val processingMs: Double get() = maxOf(0L, imageNs - completedNs) / 1e6
}

class AfOutcome(val latencyMs: Double, val terminalState: Int?, val error: String?) {
    val focused: Boolean get() = terminalState == CameraMetadata.CONTROL_AF_STATE_FOCUSED_LOCKED
    val reachedTerminal: Boolean get() = error == null
}

object Stats {
    /** Nearest-rank percentile; NaN for an empty list. */
    fun percentile(values: List<Double>, p: Double): Double {
        if (values.isEmpty()) return Double.NaN
        val sorted = values.sorted()
        val rank = ceil(p / 100.0 * sorted.size).toInt().coerceIn(1, sorted.size)
        return sorted[rank - 1]
    }

    fun mean(values: List<Double>): Double =
        if (values.isEmpty()) Double.NaN else values.sum() / values.size

    fun round2(v: Double): Double = if (v.isFinite()) Math.round(v * 100.0) / 100.0 else v

    fun summary(prefix: String, values: List<Double>): Array<Pair<String, Any?>> = arrayOf(
        "${prefix}_p50_ms" to round2(percentile(values, 50.0)),
        "${prefix}_p95_ms" to round2(percentile(values, 95.0)),
        "${prefix}_mean_ms" to round2(mean(values)),
        "${prefix}_min_ms" to round2(values.minOrNull() ?: Double.NaN),
        "${prefix}_max_ms" to round2(values.maxOrNull() ?: Double.NaN),
    )
}

/** System-wide CPU busy % from /proc/stat deltas (read with shell privileges). */
class CpuSampler(private val shell: (String) -> String) {
    private var lastIdle = -1L
    private var lastTotal = -1L

    fun sample(): Double? {
        val line = shell("cat /proc/stat").lineSequence().firstOrNull { it.startsWith("cpu ") }
            ?: return null
        val v = line.trim().split(Regex("\\s+")).drop(1).mapNotNull { it.toLongOrNull() }
        if (v.size < 5) return null
        val idle = v[3] + v[4]
        val total = v.sum()
        val busy = if (lastTotal >= 0 && total > lastTotal) {
            100.0 * (1.0 - (idle - lastIdle).toDouble() / (total - lastTotal).toDouble())
        } else {
            null
        }
        lastIdle = idle
        lastTotal = total
        return busy
    }
}

/** Runs [action] every [intervalMs] on a single background thread until stopped. */
class PeriodicSampler(intervalMs: Long, action: () -> Unit) {
    private val executor: ScheduledExecutorService = Executors.newSingleThreadScheduledExecutor()

    init {
        executor.scheduleAtFixedRate({
            try {
                action()
            } catch (_: Exception) {
            }
        }, 0, intervalMs.coerceAtLeast(100), TimeUnit.MILLISECONDS)
    }

    fun stop() {
        executor.shutdownNow()
        executor.awaitTermination(2, TimeUnit.SECONDS)
    }
}

/**
 * Crash / ANR events (logcat events buffer) and cameraserver restarts during one
 * operation. The harness cannot observe its own crash; the host sees that as
 * "Process crashed" in the instrumentation result.
 */
class SystemHealthMonitor(private val shell: (String) -> String) {
    private val startEpochMs = System.currentTimeMillis()
    private val cameraserverPid = pidOf("cameraserver")

    private fun pidOf(name: String): String? =
        try {
            shell("pidof $name").trim().takeIf { it.isNotEmpty() }
        } catch (_: Exception) {
            null
        }

    private class Event(val kind: String, val pkg: String)

    private fun events(): List<Event> {
        val out = try {
            shell("logcat -d -b events -v epoch -s am_crash am_anr")
        } catch (_: Exception) {
            return emptyList()
        }
        val list = ArrayList<Event>()
        for (line in out.lineSequence()) {
            val t = line.trim().substringBefore(' ').toDoubleOrNull() ?: continue
            if (t * 1000.0 < startEpochMs) continue
            val kind = when {
                "am_crash" in line -> "crash"
                "am_anr" in line -> "anr"
                else -> continue
            }
            val body = line.substringAfter('[', "").substringBefore(']')
            list += Event(kind, body.split(',').getOrNull(2)?.trim() ?: "")
        }
        return list
    }

    fun cameraserverRestarted(): Boolean {
        val now = pidOf("cameraserver")
        return cameraserverPid != null && now != null && now != cameraserverPid
    }

    /**
     * Counts only camera-related processes ([ownPackages] or names containing "camera"),
     * so unrelated app crashes on the DUT do not fail camera tests.
     */
    fun fields(ownPackages: Set<String>): Array<Pair<String, Any?>> {
        val related = events().filter { e ->
            e.pkg in ownPackages || e.pkg.contains("camera", ignoreCase = true)
        }
        return arrayOf(
            "app_crash_count" to related.count { it.kind == "crash" },
            "anr_count" to related.count { it.kind == "anr" },
            "crashed_packages" to related.map { it.pkg }.distinct().joinToString(","),
            "cameraserver_restarted" to cameraserverRestarted(),
        )
    }
}

/**
 * Base for harness v2 operations: tracked camera open, frame sink streaming,
 * timed still capture, AF / AE helpers and host-style utilities.
 */
abstract class HarnessTest : BaseCamera2Test() {

    protected val cameraErrors = CameraErrorTracker()
    protected var sink: FrameSink? = null

    /** Arguments an alias class presets; explicit `-e` values always win. */
    protected open val aliasDefaults: Map<String, String> = emptyMap()

    @Before
    fun applyAliasDefaults() {
        for ((k, v) in aliasDefaults) {
            if (args.getString(k).isNullOrBlank()) args.putString(k, v)
        }
    }

    @After
    fun closeHarnessResources() {
        closeStream()
    }

    /** Closes session, device, JPEG reader and the frame sink. */
    protected fun closeStream() {
        safeClose()
        sink?.close()
        sink = null
    }

    // ---------------------------------------------------------------- arguments

    protected fun optBool(key: String, default: Boolean): Boolean =
        requireString(key)?.let { it.equals("true", true) || it == "1" } ?: default

    protected fun optLong(key: String, default: Long): Long =
        requireString(key)?.toLongOrNull() ?: default

    /** `-e key id`, else the first camera with [facing]. */
    protected fun cameraArg(
        key: String = "camera_id",
        facing: Int = CameraCharacteristics.LENS_FACING_BACK,
    ): String? = requireString(key) ?: discoverCameraId(facing)

    /** Comma list or JSON-style array: `a,b` or `["a","b"]`. */
    protected fun listArg(key: String): List<String> =
        requireString(key)
            ?.trim()?.removePrefix("[")?.removeSuffix("]")
            ?.split(",")
            ?.map { it.trim().trim('"', '\'') }
            ?.filter { it.isNotEmpty() }
            ?: emptyList()

    protected fun chars(cameraId: String): CameraCharacteristics =
        cameraManager.getCameraCharacteristics(cameraId)

    protected fun cameraExists(cameraId: String): Boolean =
        try {
            cameraManager.cameraIdList.contains(cameraId)
        } catch (_: Exception) {
            false
        }

    // ---------------------------------------------------------------- open / stream

    protected fun openCameraTracked(cameraId: String, timeoutSec: Long = 10): CameraDevice {
        val latch = CountDownLatch(1)
        val opened = AtomicReference<CameraDevice?>()
        val failure = AtomicReference<CameraOpenException?>()
        val abandoned = AtomicBoolean(false)
        try {
            cameraManager.openCamera(
                cameraId,
                object : CameraDevice.StateCallback() {
                    override fun onOpened(camera: CameraDevice) {
                        if (abandoned.get()) {
                            camera.close()
                            return
                        }
                        opened.set(camera)
                        latch.countDown()
                    }

                    override fun onDisconnected(camera: CameraDevice) {
                        cameraErrors.onDisconnected()
                        if (latch.count > 0) {
                            failure.set(CameraOpenException(AccessReason.BUSY, "camera disconnected during open"))
                        }
                        camera.close()
                        latch.countDown()
                    }

                    override fun onError(camera: CameraDevice, error: Int) {
                        cameraErrors.onError(error)
                        if (latch.count > 0) {
                            failure.set(CameraOpenException(reasonForErrorCode(error), "camera error code=$error"))
                        }
                        camera.close()
                        latch.countDown()
                    }
                },
                backgroundHandler,
            )
        } catch (e: SecurityException) {
            throw CameraOpenException(AccessReason.DENIED_SECURITY, "SecurityException: ${e.message}")
        } catch (e: CameraAccessException) {
            throw CameraOpenException(reasonForAccessException(e), "CameraAccessException(${e.reason}): ${e.message}")
        }
        if (!latch.await(timeoutSec, TimeUnit.SECONDS)) {
            abandoned.set(true)
            opened.getAndSet(null)?.close()
            throw CameraOpenException(AccessReason.TIMEOUT, "openCamera timeout after ${timeoutSec}s")
        }
        failure.get()?.let { throw it }
        val device = opened.get() ?: throw CameraOpenException(AccessReason.ERROR, "openCamera failed")
        cameraDevice = device
        return device
    }

    protected fun reasonForErrorCode(code: Int): String = when (code) {
        CameraDevice.StateCallback.ERROR_CAMERA_DISABLED -> AccessReason.DENIED_DISABLED
        CameraDevice.StateCallback.ERROR_CAMERA_IN_USE,
        CameraDevice.StateCallback.ERROR_MAX_CAMERAS_IN_USE -> AccessReason.BUSY
        else -> AccessReason.ERROR
    }

    protected fun reasonForAccessException(e: CameraAccessException): String = when (e.reason) {
        CameraAccessException.CAMERA_DISABLED -> AccessReason.DENIED_DISABLED
        CameraAccessException.CAMERA_IN_USE,
        CameraAccessException.MAX_CAMERAS_IN_USE -> AccessReason.BUSY
        else -> AccessReason.ERROR
    }

    /** YUV size close to VGA (at least 320x240) for the frame sink. */
    protected fun sinkSizeFor(cameraId: String): Size {
        val map = chars(cameraId).get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
        val sizes = map?.getOutputSizes(ImageFormat.YUV_420_888)
            ?.filter { it.width >= 320 && it.height >= 240 }
        return sizes?.minByOrNull { abs(it.width * it.height - 640 * 480) } ?: Size(640, 480)
    }

    protected fun createSink(cameraId: String): FrameSink {
        val s = sinkSizeFor(cameraId)
        return FrameSink(s.width, s.height, backgroundHandler)
    }

    protected fun previewRequest(
        device: CameraDevice,
        streamSink: FrameSink,
        configure: (CaptureRequest.Builder) -> Unit = {},
    ): CaptureRequest =
        device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
            addTarget(streamSink.surface)
            set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO)
            configure(this)
        }.build()

    /** Creates a session on the sink (+ extra outputs) and starts the repeating stream. */
    protected fun startStream(
        device: CameraDevice,
        streamSink: FrameSink,
        extraSurfaces: List<Surface> = emptyList(),
        monitor: CameraCaptureSession.CaptureCallback? = null,
        configure: (CaptureRequest.Builder) -> Unit = {},
    ): CameraCaptureSession {
        sink = streamSink
        streamSink.reset()
        val session = createSessionBlocking(device, listOf(streamSink.surface) + extraSurfaces)
        captureSession = session
        session.setRepeatingRequest(previewRequest(device, streamSink, configure), monitor, backgroundHandler)
        return session
    }

    /** Open + stream + wait for the first frame. Returns first-frame ns or throws. */
    protected fun openAndStream(
        cameraId: String,
        extraSurfaces: List<Surface> = emptyList(),
        monitor: CameraCaptureSession.CaptureCallback? = null,
        firstFrameTimeoutMs: Long = 5000,
        configure: (CaptureRequest.Builder) -> Unit = {},
    ): Long {
        val device = openCameraTracked(cameraId)
        val s = createSink(cameraId)
        startStream(device, s, extraSurfaces, monitor, configure)
        return s.awaitFirstFrame(firstFrameTimeoutMs)
            ?: throw IllegalStateException("no preview frame within ${firstFrameTimeoutMs}ms")
    }

    // ---------------------------------------------------------------- still capture

    /** Parses `WxH`, `max`, or picks the largest size ≤ 1080p when absent. Null if unsupported. */
    protected fun jpegSizeFor(cameraId: String, resolution: String?): Size? {
        val sizes = chars(cameraId).get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            ?.getOutputSizes(ImageFormat.JPEG)
        if (sizes.isNullOrEmpty()) return null
        val arg = resolution?.trim()?.lowercase()
        return when {
            arg.isNullOrEmpty() ->
                sizes.filter { it.width.toLong() * it.height <= 1920L * 1080L }
                    .maxByOrNull { it.width.toLong() * it.height }
                    ?: sizes.minByOrNull { it.width.toLong() * it.height }
            arg == "max" -> sizes.maxByOrNull { it.width.toLong() * it.height }
            else -> {
                val (w, h) = parseResolution(arg) ?: return null
                sizes.firstOrNull { it.width == w && it.height == h }
            }
        }
    }

    protected fun newJpegReader(size: Size, maxImages: Int = 2): ImageReader {
        try {
            imageReader?.close()
        } catch (_: Exception) {
        }
        return ImageReader.newInstance(size.width, size.height, ImageFormat.JPEG, maxImages)
            .also { imageReader = it }
    }

    protected fun captureStill(
        device: CameraDevice,
        session: CameraCaptureSession,
        reader: ImageReader,
        template: Int = CameraDevice.TEMPLATE_STILL_CAPTURE,
        timeoutSec: Long = 15,
        keepBytes: Boolean = true,
        configure: (CaptureRequest.Builder) -> Unit = {},
    ): StillCapture {
        val done = CountDownLatch(2)
        val imageNs = AtomicLong(0)
        val completedNs = AtomicLong(0)
        val bytesRef = AtomicReference<ByteArray?>()
        val resultRef = AtomicReference<TotalCaptureResult?>()
        val errorRef = AtomicReference<String?>()

        reader.setOnImageAvailableListener({ r ->
            val img = try {
                r.acquireNextImage()
            } catch (_: Exception) {
                null
            } ?: return@setOnImageAvailableListener
            try {
                if (imageNs.compareAndSet(0, SystemClock.elapsedRealtimeNanos())) {
                    if (keepBytes) {
                        val buf = img.planes[0].buffer
                        bytesRef.set(ByteArray(buf.remaining()).also { buf.get(it) })
                    } else {
                        bytesRef.set(ByteArray(0))
                    }
                    done.countDown()
                }
            } finally {
                img.close()
            }
        }, backgroundHandler)

        val request = device.createCaptureRequest(template).apply {
            addTarget(reader.surface)
            configure(this)
        }.build()
        val requestNs = SystemClock.elapsedRealtimeNanos()
        session.capture(
            request,
            object : CameraCaptureSession.CaptureCallback() {
                override fun onCaptureCompleted(
                    session: CameraCaptureSession,
                    request: CaptureRequest,
                    result: TotalCaptureResult,
                ) {
                    completedNs.set(SystemClock.elapsedRealtimeNanos())
                    resultRef.set(result)
                    done.countDown()
                }

                override fun onCaptureFailed(
                    session: CameraCaptureSession,
                    request: CaptureRequest,
                    failure: CaptureFailure,
                ) {
                    errorRef.set("capture failed reason=${failure.reason}")
                    done.countDown()
                    done.countDown()
                }
            },
            backgroundHandler,
        )
        if (!done.await(timeoutSec, TimeUnit.SECONDS)) {
            errorRef.compareAndSet(null, "timeout waiting for capture")
        }
        reader.setOnImageAvailableListener(null, null)
        return StillCapture(
            requestNs,
            completedNs.get(),
            imageNs.get(),
            bytesRef.get(),
            resultRef.get(),
            errorRef.get(),
        )
    }

    /** Writes bytes and syncs to storage; returns the file. */
    protected fun saveDurably(bytes: ByteArray, dir: File, name: String): File {
        val file = File(dir, name)
        FileOutputStream(file).use { out ->
            out.write(bytes)
            out.flush()
            out.fd.sync()
        }
        return file
    }

    // ---------------------------------------------------------------- AF / AE

    protected fun supportsAfAuto(cameraId: String): Boolean =
        chars(cameraId).get(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES)
            ?.contains(CameraMetadata.CONTROL_AF_MODE_AUTO) == true

    /**
     * AF_MODE_AUTO + AF_TRIGGER_START; measures trigger → FOCUSED_LOCKED / NOT_FOCUSED_LOCKED.
     * The stream's repeating request must use [monitor] as its callback.
     */
    protected fun runAutofocus(
        device: CameraDevice,
        session: CameraCaptureSession,
        streamSink: FrameSink,
        monitor: ResultMonitor,
        regions: Array<MeteringRectangle>? = null,
        timeoutMs: Long = 5000,
    ): AfOutcome {
        val afAuto: (CaptureRequest.Builder) -> Unit = { b ->
            b.set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_AUTO)
            if (regions != null) b.set(CaptureRequest.CONTROL_AF_REGIONS, regions)
        }
        session.setRepeatingRequest(previewRequest(device, streamSink, afAuto), monitor, backgroundHandler)

        monitor.arm { r ->
            val s = r.get(CaptureResult.CONTROL_AF_STATE)
            s == null || (s != CameraMetadata.CONTROL_AF_STATE_FOCUSED_LOCKED &&
                s != CameraMetadata.CONTROL_AF_STATE_NOT_FOCUSED_LOCKED &&
                s != CameraMetadata.CONTROL_AF_STATE_ACTIVE_SCAN)
        }
        session.capture(
            previewRequest(device, streamSink) {
                afAuto(it)
                it.set(CaptureRequest.CONTROL_AF_TRIGGER, CaptureRequest.CONTROL_AF_TRIGGER_CANCEL)
            },
            monitor,
            backgroundHandler,
        )
        monitor.await(1500)

        monitor.arm { r ->
            val s = r.get(CaptureResult.CONTROL_AF_STATE)
            s == CameraMetadata.CONTROL_AF_STATE_FOCUSED_LOCKED ||
                s == CameraMetadata.CONTROL_AF_STATE_NOT_FOCUSED_LOCKED
        }
        val t0 = SystemClock.elapsedRealtimeNanos()
        session.capture(
            previewRequest(device, streamSink) {
                afAuto(it)
                it.set(CaptureRequest.CONTROL_AF_TRIGGER, CaptureRequest.CONTROL_AF_TRIGGER_START)
            },
            monitor,
            backgroundHandler,
        )
        val hit = monitor.await(timeoutMs)
            ?: return AfOutcome(
                timeoutMs.toDouble(),
                monitor.latest?.get(CaptureResult.CONTROL_AF_STATE),
                "AF did not reach a terminal state within ${timeoutMs}ms",
            )
        return AfOutcome((hit.second - t0) / 1e6, hit.first.get(CaptureResult.CONTROL_AF_STATE), null)
    }

    /** AE precapture sequence under [configure]; returns the settled AE state (or last seen). */
    protected fun runPrecapture(
        device: CameraDevice,
        session: CameraCaptureSession,
        streamSink: FrameSink,
        monitor: ResultMonitor,
        configure: (CaptureRequest.Builder) -> Unit,
        timeoutMs: Long = 3000,
    ): Int? {
        session.setRepeatingRequest(previewRequest(device, streamSink, configure), monitor, backgroundHandler)
        var sawPrecapture = false
        monitor.arm { r ->
            val s = r.get(CaptureResult.CONTROL_AE_STATE)
            if (s == CameraMetadata.CONTROL_AE_STATE_PRECAPTURE) {
                sawPrecapture = true
                false
            } else {
                sawPrecapture && s != null
            }
        }
        session.capture(
            previewRequest(device, streamSink) {
                configure(it)
                it.set(
                    CaptureRequest.CONTROL_AE_PRECAPTURE_TRIGGER,
                    CaptureRequest.CONTROL_AE_PRECAPTURE_TRIGGER_START,
                )
            },
            monitor,
            backgroundHandler,
        )
        val hit = monitor.await(timeoutMs)
        return hit?.first?.get(CaptureResult.CONTROL_AE_STATE)
            ?: monitor.latest?.get(CaptureResult.CONTROL_AE_STATE)
    }

    // ---------------------------------------------------------------- zoom / lenses

    protected fun zoomRange(cameraId: String): Range<Float>? =
        chars(cameraId).get(CameraCharacteristics.CONTROL_ZOOM_RATIO_RANGE)

    protected fun activePhysicalId(result: TotalCaptureResult?): String? =
        result?.get(CaptureResult.LOGICAL_MULTI_CAMERA_ACTIVE_PHYSICAL_ID)

    /** 35 mm-equivalent focal length, used to order lenses across different sensors. */
    protected fun equivalentFocal(cameraId: String): Double? {
        val c = chars(cameraId)
        val f = c.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)?.firstOrNull()
            ?: return null
        val size = c.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE) ?: return f.toDouble()
        val diag = sqrt((size.width * size.width + size.height * size.height).toDouble())
        return if (diag > 0) f * 43.27 / diag else f.toDouble()
    }

    /**
     * How to reach lens [targetId] from [sourceId]: a zoom ratio on the logical camera when
     * the target is one of its physical lenses, else a plain camera-id switch.
     */
    protected fun resolveLensTarget(sourceId: String, targetId: String): LensTarget? {
        if (targetId == sourceId) return null
        val physical = try {
            chars(sourceId).physicalCameraIds
        } catch (_: Exception) {
            emptySet()
        }
        if (targetId in physical && zoomRange(sourceId) != null) {
            val ratio = zoomForPhysical(sourceId, targetId) ?: return null
            return LensTarget(LensTarget.ZOOM_RATIO, sourceId, targetId, ratio)
        }
        if (cameraExists(targetId)) return LensTarget(LensTarget.CAMERA_ID, sourceId, targetId, null)
        return null
    }

    /**
     * Applies [ratio] on the repeating request and waits until a result shows it applied
     * (and, when reported, the expected active physical lens). Returns result + arrival ns.
     */
    protected fun zoomTo(
        device: CameraDevice,
        session: CameraCaptureSession,
        streamSink: FrameSink,
        monitor: ResultMonitor,
        ratio: Float,
        expectPhysical: String? = null,
        timeoutMs: Long = 3000,
    ): Pair<TotalCaptureResult, Long>? {
        val tolerance = 0.05f * maxOf(1f, ratio)
        monitor.arm { r ->
            val z = r.get(CaptureResult.CONTROL_ZOOM_RATIO)
            val zoomOk = z == null || abs(z - ratio) <= tolerance
            val physical = activePhysicalId(r)
            zoomOk && (expectPhysical == null || physical == null || physical == expectPhysical)
        }
        session.setRepeatingRequest(
            previewRequest(device, streamSink) { it.set(CaptureRequest.CONTROL_ZOOM_RATIO, ratio) },
            monitor,
            backgroundHandler,
        )
        return monitor.await(timeoutMs)
    }

    /** Zoom ratio on [logicalId] that should select physical lens [physicalId]. */
    protected fun zoomForPhysical(logicalId: String, physicalId: String): Float? {
        val base = equivalentFocal(logicalId) ?: return null
        val target = try {
            equivalentFocal(physicalId)
        } catch (_: Exception) {
            null
        } ?: return null
        val ratio = (target / base).toFloat()
        val range = zoomRange(logicalId) ?: return ratio
        return ratio.coerceIn(range.lower, range.upper)
    }

    // ---------------------------------------------------------------- device state

    protected fun uiAutomation(): UiAutomation =
        InstrumentationRegistry.getInstrumentation()
            .getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES)

    /** Runs a shell command with shell-user privileges (UiAutomation). */
    protected fun shell(command: String): String {
        val pfd = uiAutomation().executeShellCommand(command)
        return ParcelFileDescriptor.AutoCloseInputStream(pfd).use {
            it.readBytes().toString(Charsets.UTF_8)
        }
    }

    protected fun thermalStatus(): Int =
        try {
            (appContext.getSystemService(Context.POWER_SERVICE) as PowerManager).currentThermalStatus
        } catch (_: Exception) {
            -1
        }

    protected fun isThermalCritical(): Boolean =
        thermalStatus() >= PowerManager.THERMAL_STATUS_CRITICAL

    protected fun pssMb(): Double = Debug.getPss() / 1024.0

    protected fun gcAndSettle(settleMs: Long = 1500) {
        Runtime.getRuntime().gc()
        System.runFinalization()
        Runtime.getRuntime().gc()
        Thread.sleep(settleMs)
    }

    protected fun waitUntil(timeoutMs: Long, condition: () -> Boolean): Boolean {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            if (condition()) return true
            Thread.sleep(50)
        }
        return condition()
    }

    // ---------------------------------------------------------------- foreground screen

    /** Starts [ProbeActivity] from the shell (exempt from background-start limits). */
    protected fun bringProbeToForeground(timeoutMs: Long = 8000): Boolean {
        shell("am start -W -n ${appContext.packageName}/${ProbeActivity::class.java.name}")
        return waitUntil(timeoutMs) { ProbeActivity.foreground }
    }

    protected fun sendHome(timeoutMs: Long = 5000): Boolean {
        shell("input keyevent KEYCODE_HOME")
        return waitUntil(timeoutMs) { !ProbeActivity.foreground }
    }

    protected fun finishProbe() {
        val activity = ProbeActivity.current?.get() ?: return
        try {
            InstrumentationRegistry.getInstrumentation().runOnMainSync { activity.finish() }
        } catch (_: Exception) {
        }
    }

    // ---------------------------------------------------------------- output

    /** Metric-style result: result, metric_value, samples, latency_ms first (host regex order). */
    protected fun emitMetrics(
        metricValue: Any?,
        samples: Int,
        latencyMs: Any?,
        vararg extra: Pair<String, Any?>,
        pass: Boolean = true,
    ) {
        val fields = LinkedHashMap<String, Any?>()
        fields["result"] = if (pass) "PASS" else "FAIL"
        fields["metric_value"] = if (metricValue is Double) Stats.round2(metricValue) else metricValue
        fields["samples"] = samples
        fields["latency_ms"] = if (latencyMs is Double) Stats.round2(latencyMs) else latencyMs
        for ((k, v) in extra) fields[k] = if (v is Double) Stats.round2(v) else v
        emit(fields)
    }

    protected fun emitFailWith(error: String, vararg extra: Pair<String, Any?>) {
        val fields = LinkedHashMap<String, Any?>()
        fields["result"] = "FAIL"
        fields["error"] = error
        for ((k, v) in extra) fields[k] = if (v is Double) Stats.round2(v) else v
        emit(fields)
    }

    /** Required capability absent on this DUT: never invent a value. */
    protected fun emitNotApplicable(reason: String, vararg extra: Pair<String, Any?>) {
        val fields = LinkedHashMap<String, Any?>()
        fields["result"] = "NOT_APPLICABLE"
        fields["reason"] = reason
        for ((k, v) in extra) fields[k] = if (v is Double) Stats.round2(v) else v
        emit(fields)
    }

    /** Functional result: PASS/FAIL first, then facts. */
    protected fun emitResult(pass: Boolean, error: String?, vararg extra: Pair<String, Any?>) {
        val fields = LinkedHashMap<String, Any?>()
        fields["result"] = if (pass) "PASS" else "FAIL"
        if (!pass && error != null) fields["error"] = error
        for ((k, v) in extra) fields[k] = if (v is Double) Stats.round2(v) else v
        emit(fields)
    }

    /** Reliability contract order: result, metric_value, failures, thermal_abort. */
    protected fun emitEndurance(
        pass: Boolean,
        metricValue: Any?,
        failures: Int,
        thermalAbort: Boolean,
        vararg extra: Pair<String, Any?>,
    ) {
        val fields = LinkedHashMap<String, Any?>()
        fields["result"] = if (pass) "PASS" else "FAIL"
        fields["metric_value"] = if (metricValue is Double) Stats.round2(metricValue) else metricValue
        fields["failures"] = failures
        fields["thermal_abort"] = thermalAbort
        for ((k, v) in extra) fields[k] = if (v is Double) Stats.round2(v) else v
        emit(fields)
    }

    /** Security contract order: result, metric_value, unauthorized_access_count, crash_count. */
    protected fun emitSecurity(
        result: String,
        metricValue: Int,
        unauthorizedAccessCount: Int,
        crashCount: Int,
        vararg extra: Pair<String, Any?>,
    ) {
        val fields = LinkedHashMap<String, Any?>()
        fields["result"] = result
        fields["metric_value"] = metricValue
        fields["unauthorized_access_count"] = unauthorizedAccessCount
        fields["crash_count"] = crashCount
        for ((k, v) in extra) fields[k] = if (v is Double) Stats.round2(v) else v
        emit(fields)
    }

    protected fun afStateName(s: Int?): String = when (s) {
        null -> "UNKNOWN"
        CameraMetadata.CONTROL_AF_STATE_INACTIVE -> "INACTIVE"
        CameraMetadata.CONTROL_AF_STATE_PASSIVE_SCAN -> "PASSIVE_SCAN"
        CameraMetadata.CONTROL_AF_STATE_PASSIVE_FOCUSED -> "PASSIVE_FOCUSED"
        CameraMetadata.CONTROL_AF_STATE_ACTIVE_SCAN -> "ACTIVE_SCAN"
        CameraMetadata.CONTROL_AF_STATE_FOCUSED_LOCKED -> "FOCUSED_LOCKED"
        CameraMetadata.CONTROL_AF_STATE_NOT_FOCUSED_LOCKED -> "NOT_FOCUSED_LOCKED"
        CameraMetadata.CONTROL_AF_STATE_PASSIVE_UNFOCUSED -> "PASSIVE_UNFOCUSED"
        else -> "STATE_$s"
    }

    protected fun aeStateName(s: Int?): String = when (s) {
        null -> "UNKNOWN"
        CameraMetadata.CONTROL_AE_STATE_INACTIVE -> "INACTIVE"
        CameraMetadata.CONTROL_AE_STATE_SEARCHING -> "SEARCHING"
        CameraMetadata.CONTROL_AE_STATE_CONVERGED -> "CONVERGED"
        CameraMetadata.CONTROL_AE_STATE_LOCKED -> "LOCKED"
        CameraMetadata.CONTROL_AE_STATE_FLASH_REQUIRED -> "FLASH_REQUIRED"
        CameraMetadata.CONTROL_AE_STATE_PRECAPTURE -> "PRECAPTURE"
        else -> "STATE_$s"
    }

    protected fun flashStateName(s: Int?): String = when (s) {
        null -> "UNKNOWN"
        CameraMetadata.FLASH_STATE_UNAVAILABLE -> "UNAVAILABLE"
        CameraMetadata.FLASH_STATE_CHARGING -> "CHARGING"
        CameraMetadata.FLASH_STATE_READY -> "READY"
        CameraMetadata.FLASH_STATE_FIRED -> "FIRED"
        CameraMetadata.FLASH_STATE_PARTIAL -> "PARTIAL"
        else -> "STATE_$s"
    }

    protected fun hasCameraPermission(): Boolean =
        appContext.checkSelfPermission(android.Manifest.permission.CAMERA) ==
            android.content.pm.PackageManager.PERMISSION_GRANTED

    /** Packages whose crashes count against camera tests. */
    protected fun harnessPackages(): Set<String> = setOf(
        appContext.packageName,
        "com.example.cameratest",
        "com.example.cameraunauthorized",
        "com.example.camerasecondary",
    )

    /**
     * Runs a helper APK's instrumentation (unauthorized / secondary flavor) through the shell
     * and returns its harness JSON; null when the helper is not installed.
     */
    protected fun runHelperInstrumentation(pkg: String, className: String, args: Map<String, String>): JSONObject? {
        val listed = shell("pm list instrumentation")
        if (!listed.contains("instrumentation:$pkg/")) return null
        val a = args.entries.joinToString(" ") { "-e ${it.key} ${it.value}" }
        val out = shell("am instrument -w -r -e class $className $a $pkg/androidx.test.runner.AndroidJUnitRunner")
        for (line in out.lineSequence()) {
            val t = line.trim()
            if (t.startsWith("INSTRUMENTATION_STATUS: harness_json=")) {
                return JSONObject(t.substringAfter("harness_json="))
            }
        }
        return JSONObject().put("result", "HARNESS_ERROR").put("raw", out.takeLast(1500))
    }

    protected fun fdCount(): Int = File("/proc/self/fd").list()?.size ?: -1

    protected fun threadCount(): Int = Thread.getAllStackTraces().size

    protected fun describe(t: Throwable): String = when (t) {
        is CameraOpenException -> "${t.reason}: ${t.message}"
        is SecurityException -> "CAMERA permission not granted: ${t.message}"
        is CameraAccessException -> "CameraAccessException(${t.reason}): ${t.message}"
        else -> "${t.javaClass.simpleName}: ${t.message}"
    }
}
