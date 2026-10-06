package com.example.cameratest

import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.params.DynamicRangeProfiles
import android.hardware.camera2.params.OutputConfiguration
import android.hardware.camera2.params.SessionConfiguration
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaCodecList
import android.media.MediaFormat
import android.media.MediaMetadataRetriever
import android.media.MediaMuxer
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.util.Range
import android.util.Size
import android.view.Surface
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

/**
 * Camera → MediaCodec encoder (→ optional MP4 muxer).
 * Unlike MediaRecorder it exposes the first encoded sample time and every
 * presentation timestamp, which the video performance operations need.
 */
class VideoPipeline(
    val width: Int,
    val height: Int,
    val fps: Int,
    private val outFile: File?,
    val hdr: Boolean = false,
    private val keepTimestamps: Boolean = true,
) {
    private val thread = HandlerThread("video-pipeline").apply { start() }
    private val handler = Handler(thread.looper)
    private val encoder: MediaCodec
    val inputSurface: Surface
    private var muxer: MediaMuxer? = null
    private var track = -1

    @Volatile
    private var muxerStarted = false
    private val firstSampleNs = AtomicLong(0)
    private val firstLatch = CountDownLatch(1)
    private val eosLatch = CountDownLatch(1)
    private val timestamps = ArrayList<Long>()
    private val frames = AtomicInteger(0)
    private val errorRef = AtomicReference<String?>()
    private var released = false

    val encodedFrames: Int get() = frames.get()
    val error: String? get() = errorRef.get()

    init {
        val mime = if (hdr) MediaFormat.MIMETYPE_VIDEO_HEVC else MediaFormat.MIMETYPE_VIDEO_AVC
        val format = MediaFormat.createVideoFormat(mime, width, height).apply {
            setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
            setInteger(MediaFormat.KEY_BIT_RATE, bitRateFor(width, height, fps))
            setInteger(MediaFormat.KEY_FRAME_RATE, fps)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1)
            if (hdr) {
                setInteger(MediaFormat.KEY_PROFILE, MediaCodecInfo.CodecProfileLevel.HEVCProfileMain10)
                setInteger(MediaFormat.KEY_COLOR_STANDARD, MediaFormat.COLOR_STANDARD_BT2020)
                setInteger(MediaFormat.KEY_COLOR_TRANSFER, MediaFormat.COLOR_TRANSFER_HLG)
                setInteger(MediaFormat.KEY_COLOR_RANGE, MediaFormat.COLOR_RANGE_LIMITED)
            }
        }
        val codecName = MediaCodecList(MediaCodecList.REGULAR_CODECS).findEncoderForFormat(format)
            ?: throw UnsupportedOperationException("no encoder for $mime ${width}x$height@$fps")
        encoder = MediaCodec.createByCodecName(codecName)
        encoder.setCallback(
            object : MediaCodec.Callback() {
                override fun onInputBufferAvailable(codec: MediaCodec, index: Int) {}

                override fun onOutputBufferAvailable(
                    codec: MediaCodec,
                    index: Int,
                    info: MediaCodec.BufferInfo,
                ) {
                    try {
                        val isConfig = info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0
                        if (!isConfig && info.size > 0) {
                            if (firstSampleNs.compareAndSet(0, SystemClock.elapsedRealtimeNanos())) {
                                firstLatch.countDown()
                            }
                            frames.incrementAndGet()
                            if (keepTimestamps) {
                                synchronized(timestamps) { timestamps.add(info.presentationTimeUs) }
                            }
                            val m = muxer
                            if (m != null && muxerStarted) {
                                val buf = codec.getOutputBuffer(index)
                                if (buf != null) {
                                    buf.position(info.offset)
                                    buf.limit(info.offset + info.size)
                                    m.writeSampleData(track, buf, info)
                                }
                            }
                        }
                        codec.releaseOutputBuffer(index, false)
                        if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) {
                            eosLatch.countDown()
                        }
                    } catch (e: Exception) {
                        errorRef.compareAndSet(null, "encoder output: ${e.message ?: e.javaClass.simpleName}")
                        eosLatch.countDown()
                    }
                }

                override fun onError(codec: MediaCodec, e: MediaCodec.CodecException) {
                    errorRef.compareAndSet(null, "encoder error: ${e.diagnosticInfo}")
                    eosLatch.countDown()
                }

                override fun onOutputFormatChanged(codec: MediaCodec, format: MediaFormat) {
                    val m = muxer ?: return
                    track = m.addTrack(format)
                    m.start()
                    muxerStarted = true
                }
            },
            handler,
        )
        encoder.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        inputSurface = encoder.createInputSurface()
        if (outFile != null) {
            muxer = MediaMuxer(outFile.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
        }
        encoder.start()
    }

    /** Elapsed-realtime ns of the first encoded (non-config) sample, or null on timeout. */
    fun awaitFirstSample(timeoutMs: Long): Long? =
        if (firstLatch.await(timeoutMs, TimeUnit.MILLISECONDS)) firstSampleNs.get() else null

    /** Call after the camera stopped targeting [inputSurface]; drains to end-of-stream. */
    fun stop(timeoutMs: Long = 10_000): Boolean {
        try {
            encoder.signalEndOfInputStream()
        } catch (e: Exception) {
            errorRef.compareAndSet(null, "signalEndOfInputStream: ${e.message}")
            return false
        }
        return eosLatch.await(timeoutMs, TimeUnit.MILLISECONDS) && errorRef.get() == null
    }

    /** Stops the muxer so the MP4 is finalized. True when the file was written. */
    fun finalizeFile(): Boolean {
        val m = muxer ?: return false
        return try {
            if (muxerStarted) m.stop()
            muxerStarted
        } catch (e: Exception) {
            errorRef.compareAndSet(null, "muxer stop: ${e.message}")
            false
        } finally {
            try {
                m.release()
            } catch (_: Exception) {
            }
            muxer = null
        }
    }

    fun timestampsUs(): List<Long> = synchronized(timestamps) { ArrayList(timestamps) }

    fun release() {
        if (released) return
        released = true
        try {
            encoder.stop()
        } catch (_: Exception) {
        }
        try {
            encoder.release()
        } catch (_: Exception) {
        }
        try {
            inputSurface.release()
        } catch (_: Exception) {
        }
        try {
            muxer?.release()
        } catch (_: Exception) {
        }
        muxer = null
        thread.quitSafely()
    }

    companion object {
        fun bitRateFor(w: Int, h: Int, fps: Int): Int {
            val pixels = w.toLong() * h.toLong()
            return when {
                pixels >= 3840L * 2160L -> 35_000_000
                pixels >= 1920L * 1080L -> 12_000_000
                else -> 4_000_000
            }.coerceAtLeast(fps * 100_000)
        }
    }
}

/** Per-second FPS windows computed from presentation timestamps. */
class FpsAnalysis(timestampsUs: List<Long>, targetFps: Int, tolerancePct: Double) {
    val windowFps: List<Double>
    val withinTolerancePercent: Double
    val averageFps: Double

    init {
        val ts = timestampsUs.sorted()
        val windows = ArrayList<Double>()
        if (ts.size >= 2) {
            val start = ts.first()
            val completeWindows = ((ts.last() - start) / 1_000_000L).toInt()
            val counts = IntArray(completeWindows.coerceAtLeast(0))
            for (t in ts) {
                val w = ((t - start) / 1_000_000L).toInt()
                if (w < counts.size) counts[w]++
            }
            counts.forEach { windows.add(it.toDouble()) }
        }
        windowFps = windows
        val tol = targetFps * tolerancePct / 100.0
        withinTolerancePercent = if (windows.isEmpty()) Double.NaN
        else 100.0 * windows.count { kotlin.math.abs(it - targetFps) <= tol } / windows.size
        averageFps = if (ts.size < 2) Double.NaN
        else (ts.size - 1) * 1_000_000.0 / (ts.last() - ts.first()).coerceAtLeast(1)
    }
}

/** Shared camera-side setup for operations that record video. */
abstract class VideoHarnessTest : HarnessTest() {

    protected fun videoSizeFor(cameraId: String, resolution: String?): Size? {
        val sizes = chars(cameraId).get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            ?.getOutputSizes(MediaCodec::class.java)
        if (sizes.isNullOrEmpty()) return null
        val arg = resolution?.trim()?.lowercase()
        return when {
            arg.isNullOrEmpty() ->
                sizes.firstOrNull { it.width == 1920 && it.height == 1080 }
                    ?: sizes.filter { it.width.toLong() * it.height <= 1920L * 1080L }
                        .maxByOrNull { it.width.toLong() * it.height }
            arg == "max" -> sizes.maxByOrNull { it.width.toLong() * it.height }
            else -> {
                val (w, h) = parseResolution(arg) ?: return null
                sizes.firstOrNull { it.width == w && it.height == h }
            }
        }
    }

    /** Prefers a fixed [fps, fps] AE range; otherwise the narrowest range containing fps. */
    protected fun fpsRangeFor(cameraId: String, fps: Int): Range<Int>? {
        val ranges = chars(cameraId).get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES)
            ?: return null
        return ranges.firstOrNull { it.lower == fps && it.upper == fps }
            ?: ranges.filter { fps in it.lower..it.upper }.minByOrNull { it.upper - it.lower }
    }

    protected fun supportsHlg10(cameraId: String): Boolean {
        if (Build.VERSION.SDK_INT < 33) return false
        val profiles = chars(cameraId).get(CameraCharacteristics.REQUEST_AVAILABLE_DYNAMIC_RANGE_PROFILES)
            ?: return false
        return profiles.supportedProfiles.contains(DynamicRangeProfiles.HLG10)
    }

    /** Session with an optional low-res preview sink plus the encoder surface. */
    protected fun createVideoSession(
        device: CameraDevice,
        cameraId: String,
        pipeline: VideoPipeline,
        withPreview: Boolean = true,
    ): CameraCaptureSession {
        val configs = ArrayList<OutputConfiguration>()
        if (withPreview && !pipeline.hdr) {
            val s = createSink(cameraId)
            sink = s
            configs += OutputConfiguration(s.surface)
        }
        configs += OutputConfiguration(pipeline.inputSurface).also { cfg ->
            if (pipeline.hdr && Build.VERSION.SDK_INT >= 33) {
                cfg.dynamicRangeProfile = DynamicRangeProfiles.HLG10
            }
        }
        val latch = CountDownLatch(1)
        val sessionRef = AtomicReference<CameraCaptureSession?>()
        val executor = Executor { backgroundHandler.post(it) }
        device.createCaptureSession(
            SessionConfiguration(
                SessionConfiguration.SESSION_REGULAR,
                configs,
                executor,
                object : CameraCaptureSession.StateCallback() {
                    override fun onConfigured(session: CameraCaptureSession) {
                        sessionRef.set(session)
                        latch.countDown()
                    }

                    override fun onConfigureFailed(session: CameraCaptureSession) {
                        latch.countDown()
                    }
                },
            ),
        )
        if (!latch.await(10, TimeUnit.SECONDS)) throw IllegalStateException("video session timeout")
        val session = sessionRef.get() ?: throw IllegalStateException("video session configuration failed")
        captureSession = session
        return session
    }

    protected fun videoRequest(
        device: CameraDevice,
        cameraId: String,
        pipeline: VideoPipeline?,
        fps: Int,
    ): CaptureRequest =
        device.createCaptureRequest(CameraDevice.TEMPLATE_RECORD).apply {
            sink?.let { addTarget(it.surface) }
            pipeline?.let { addTarget(it.inputSurface) }
            set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO)
            set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_VIDEO)
            fpsRangeFor(cameraId, fps)?.let { set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, it) }
        }.build()

    /** Stops sending frames to the encoder (keeps preview if present). */
    protected fun stopEncoderTarget(
        device: CameraDevice,
        session: CameraCaptureSession,
        cameraId: String,
        fps: Int,
    ) {
        if (sink != null) {
            session.setRepeatingRequest(videoRequest(device, cameraId, null, fps), null, backgroundHandler)
        } else {
            session.stopRepeating()
        }
    }

    /** Closes the capture session and preview sink but keeps the camera device open. */
    protected fun closeSessionOnly() {
        try {
            captureSession?.stopRepeating()
        } catch (_: Exception) {
        }
        try {
            captureSession?.close()
        } catch (_: Exception) {
        }
        captureSession = null
        sink?.close()
        sink = null
    }

    /** One recording on an already open device; returns the finished pipeline (caller releases). */
    protected fun recordClip(
        device: CameraDevice,
        cameraId: String,
        size: Size,
        fps: Int,
        file: File?,
        durationMs: Long,
        keepTimestamps: Boolean = true,
    ): VideoPipeline {
        val pipeline = VideoPipeline(size.width, size.height, fps, file, keepTimestamps = keepTimestamps)
        try {
            val session = createVideoSession(device, cameraId, pipeline)
            session.setRepeatingRequest(videoRequest(device, cameraId, pipeline, fps), null, backgroundHandler)
            pipeline.awaitFirstSample(5000) ?: error("no encoded frame within 5s")
            Thread.sleep(durationMs)
            stopEncoderTarget(device, session, cameraId, fps)
            if (!pipeline.stop()) error(pipeline.error ?: "encoder did not reach end of stream")
            if (file != null && !pipeline.finalizeFile()) error(pipeline.error ?: "file not finalized")
            return pipeline
        } catch (e: Exception) {
            pipeline.release()
            throw e
        } finally {
            closeSessionOnly()
        }
    }

    /** Duration in ms reported by the container, or null when unreadable. */
    protected fun readableDurationMs(file: File): Long? {
        val retriever = MediaMetadataRetriever()
        return try {
            retriever.setDataSource(file.absolutePath)
            retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull()
        } catch (_: Exception) {
            null
        } finally {
            try {
                retriever.release()
            } catch (_: Exception) {
            }
        }
    }
}
