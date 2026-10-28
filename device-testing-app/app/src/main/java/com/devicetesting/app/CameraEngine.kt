package com.devicetesting.app

import android.content.Context
import android.graphics.ImageFormat
import android.graphics.SurfaceTexture
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.media.ImageReader
import android.media.MediaRecorder
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.util.Size
import android.view.Surface
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * Camera2 operations that run inside the app process. Session setup uses the
 * API 21 capture-session call so Android 6 can run it.
 */
class CameraEngine(
    context: Context,
    private val previewSurface: AtomicReference<Surface?> = AtomicReference(null),
    private val onStatus: ((String) -> Unit)? = null,
    private val onStillSaved: ((String) -> Unit)? = null,
) : AutoCloseable {
    data class Still(
        val ok: Boolean,
        val width: Int = 0,
        val height: Int = 0,
        val bytes: Int = 0,
        val path: String? = null,
        val openMs: Long = 0,
        val captureMs: Long = 0,
        val saveMs: Long = 0,
        val error: String? = null,
    )

    data class Burst(val saved: Int, val failed: Int, val elapsedMs: Long, val error: String? = null)
    data class Video(val ok: Boolean, val path: String? = null, val startMs: Long = 0, val stopMs: Long = 0, val bytes: Long = 0, val error: String? = null)
    data class Facts(
        val id: String,
        val facing: String,
        val hardwareLevel: String,
        val jpegSizes: List<String>,
        val videoSizes: List<String>,
        val fpsRanges: List<String>,
        val hasFlash: Boolean,
        val maxDigitalZoom: Float,
        val focalLengths: List<Float>,
        val hasAutofocus: Boolean,
    )

    private val app = context.applicationContext
    private val manager = app.getSystemService(Context.CAMERA_SERVICE) as CameraManager
    private val thread = HandlerThread("device-testing-camera").apply { start() }
    private val handler = Handler(thread.looper)
    private val dir = File(app.filesDir, "shots").apply { mkdirs() }

    private fun status(text: String) {
        onStatus?.invoke(text)
    }

    private fun saved(path: String) {
        onStillSaved?.invoke(path)
    }

    fun rearId(): String? = idFor(CameraCharacteristics.LENS_FACING_BACK)
    fun frontId(): String? = idFor(CameraCharacteristics.LENS_FACING_FRONT)

    fun backCount(): Int = manager.cameraIdList.count {
        manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) ==
            CameraCharacteristics.LENS_FACING_BACK
    }

    fun facts(id: String): Facts {
        val c = manager.getCameraCharacteristics(id)
        val map = c.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
        val jpeg = map?.getOutputSizes(ImageFormat.JPEG)?.map { "${it.width}x${it.height}" }.orEmpty()
        val video = map?.getOutputSizes(MediaRecorder::class.java)?.map { "${it.width}x${it.height}" }.orEmpty()
        val fps = c.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES)
            ?.map { "${it.lower}-${it.upper}" }.orEmpty()
        val af = c.get(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES)?.toList().orEmpty()
        val level = when (c.get(CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL)) {
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_LEGACY -> "LEGACY"
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_LIMITED -> "LIMITED"
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_FULL -> "FULL"
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_3 -> "LEVEL_3"
            else -> "UNKNOWN"
        }
        val facing = when (c.get(CameraCharacteristics.LENS_FACING)) {
            CameraCharacteristics.LENS_FACING_BACK -> "back"
            CameraCharacteristics.LENS_FACING_FRONT -> "front"
            else -> "other"
        }
        return Facts(
            id = id,
            facing = facing,
            hardwareLevel = level,
            jpegSizes = jpeg,
            videoSizes = video,
            fpsRanges = fps,
            hasFlash = c.get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true,
            maxDigitalZoom = c.get(CameraCharacteristics.SCALER_AVAILABLE_MAX_DIGITAL_ZOOM) ?: 1f,
            focalLengths = c.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)?.toList().orEmpty(),
            hasAutofocus = af.any {
                it == CameraCharacteristics.CONTROL_AF_MODE_AUTO ||
                    it == CameraCharacteristics.CONTROL_AF_MODE_CONTINUOUS_PICTURE ||
                    it == CameraCharacteristics.CONTROL_AF_MODE_MACRO
            },
        )
    }

    fun capture(id: String, flashMode: Int? = null, aeMode: Int? = null, zoom: Boolean = false, largest: Boolean = false): Still {
        return useSession(id, largest) { device, session, reader, chars, openMs ->
            status("Capturing photo…")
            val start = SystemClock.elapsedRealtime()
            val bytes = takeStill(device, session, reader, chars, flashMode, aeMode, zoom)
            val captureMs = SystemClock.elapsedRealtime() - start
            if (bytes == null || bytes.size < 2 || bytes[0] != 0xFF.toByte() || bytes[1] != 0xD8.toByte()) {
                return@useSession Still(ok = false, openMs = openMs, error = "JPEG was not written")
            }
            val saveStart = SystemClock.elapsedRealtime()
            val file = File(dir, "photo_${System.currentTimeMillis()}.jpg")
            file.writeBytes(bytes)
            val saveMs = SystemClock.elapsedRealtime() - saveStart
            saved(file.absolutePath)
            status("Photo saved")
            Still(
                ok = true,
                width = reader.width,
                height = reader.height,
                bytes = bytes.size,
                path = file.absolutePath,
                openMs = openMs,
                captureMs = captureMs,
                saveMs = saveMs,
            )
        }
    }

    fun burst(id: String, count: Int, shouldStop: () -> Boolean): Burst {
        val started = SystemClock.elapsedRealtime()
        var savedCount = 0
        var failed = 0
        var error: String? = null
        val outcome = useSession(id, largest = false) { device, session, reader, chars, _ ->
            repeat(count) {
                if (shouldStop()) return@useSession Still(ok = true)
                status("Burst ${it + 1} of $count…")
                val bytes = takeStill(device, session, reader, chars, null, null, false)
                if (bytes != null && bytes.size > 2 && bytes[0] == 0xFF.toByte()) {
                    val file = File(dir, "burst_${System.currentTimeMillis()}_$it.jpg")
                    file.writeBytes(bytes)
                    saved(file.absolutePath)
                    savedCount++
                } else {
                    failed++
                    error = "capture failed"
                }
            }
            Still(ok = failed == 0)
        }
        if (!outcome.ok && savedCount == 0 && failed == 0) {
            return Burst(0, count, SystemClock.elapsedRealtime() - started, outcome.error)
        }
        return Burst(savedCount, failed, SystemClock.elapsedRealtime() - started, error)
    }

    fun openTimes(id: String, times: Int, shouldStop: () -> Boolean): Int {
        var ok = 0
        repeat(times) {
            if (shouldStop()) return ok
            try {
                val device = openCamera(id)
                device.close()
                ok++
            } catch (_: Exception) {
            }
        }
        return ok
    }

    fun holdPreview(id: String, ms: Long): Still {
        return useSession(id, largest = false) { _, _, _, _, openMs ->
            status("Holding live preview…")
            Thread.sleep(ms)
            Still(ok = true, openMs = openMs)
        }
    }

    fun switchLatency(fromId: String, toId: String): Still {
        val first = capture(fromId)
        if (!first.ok) return first
        val start = SystemClock.elapsedRealtime()
        val second = capture(toId)
        return second.copy(openMs = SystemClock.elapsedRealtime() - start)
    }

    fun record(id: String, seconds: Int): Video {
        val chars = manager.getCameraCharacteristics(id)
        val map = chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            ?: return Video(ok = false, error = "No stream configuration")
        val size = chooseVideo(map) ?: return Video(ok = false, error = "No video size")
        val previewSize = choosePreview(map)
        val file = File(dir, "video_${System.currentTimeMillis()}.mp4")
        val recorder = MediaRecorder()
        var device: CameraDevice? = null
        var session: CameraCaptureSession? = null
        var surface: Surface? = null
        var ownedTexture: SurfaceTexture? = null
        var ownedPreview: Surface? = null
        try {
            status("Recording video…")
            recorder.setVideoSource(MediaRecorder.VideoSource.SURFACE)
            recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            recorder.setVideoEncoder(MediaRecorder.VideoEncoder.H264)
            recorder.setVideoSize(size.width, size.height)
            recorder.setVideoFrameRate(15)
            recorder.setVideoEncodingBitRate(1_000_000)
            recorder.setOutputFile(file.absolutePath)
            recorder.prepare()
            surface = recorder.surface
            val uiPreview = previewSurface.get()?.takeIf { it.isValid }
            val previewTarget = if (uiPreview != null) {
                uiPreview
            } else {
                ownedTexture = SurfaceTexture(0).apply {
                    setDefaultBufferSize(previewSize.width, previewSize.height)
                }
                Surface(ownedTexture).also { ownedPreview = it }
            }
            device = openCamera(id)
            session = openSession(device, listOf(surface, previewTarget))
            val request = device.createCaptureRequest(CameraDevice.TEMPLATE_RECORD).apply {
                addTarget(surface)
                addTarget(previewTarget)
            }.build()
            session.setRepeatingRequest(request, null, handler)
            val startMark = SystemClock.elapsedRealtime()
            recorder.start()
            val startMs = SystemClock.elapsedRealtime() - startMark
            Thread.sleep(seconds * 1000L)
            val stopMark = SystemClock.elapsedRealtime()
            recorder.stop()
            val stopMs = SystemClock.elapsedRealtime() - stopMark
            status("Video saved")
            return Video(ok = file.length() > 0, path = file.absolutePath, startMs = startMs, stopMs = stopMs, bytes = file.length())
        } catch (e: Exception) {
            return Video(ok = false, error = e.message ?: e.javaClass.simpleName)
        } finally {
            try { session?.close() } catch (_: Exception) {}
            try { device?.close() } catch (_: Exception) {}
            try { surface?.release() } catch (_: Exception) {}
            try { ownedPreview?.release() } catch (_: Exception) {}
            try { ownedTexture?.release() } catch (_: Exception) {}
            try { recorder.reset() } catch (_: Exception) {}
            try { recorder.release() } catch (_: Exception) {}
        }
    }

    private fun idFor(facing: Int): String? =
        manager.cameraIdList.firstOrNull {
            manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) == facing
        }

    private fun useSession(
        id: String,
        largest: Boolean,
        block: (CameraDevice, CameraCaptureSession, ImageReader, CameraCharacteristics, Long) -> Still,
    ): Still {
        var device: CameraDevice? = null
        var session: CameraCaptureSession? = null
        var reader: ImageReader? = null
        var ownedTexture: SurfaceTexture? = null
        var ownedPreview: Surface? = null
        try {
            status("Opening camera…")
            val chars = manager.getCameraCharacteristics(id)
            val map = chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
                ?: return Still(ok = false, error = "No stream configuration")
            val jpeg = chooseJpeg(map, largest) ?: return Still(ok = false, error = "No JPEG size")
            val previewSize = choosePreview(map)
            reader = ImageReader.newInstance(jpeg.width, jpeg.height, ImageFormat.JPEG, 2)
            val uiPreview = previewSurface.get()?.takeIf { it.isValid }
            val previewTarget = if (uiPreview != null) {
                uiPreview
            } else {
                ownedTexture = SurfaceTexture(0).apply {
                    setDefaultBufferSize(previewSize.width, previewSize.height)
                }
                Surface(ownedTexture).also { ownedPreview = it }
            }
            val openedAt = SystemClock.elapsedRealtime()
            device = openCamera(id)
            val openMs = SystemClock.elapsedRealtime() - openedAt
            session = openSession(device, listOf(previewTarget, reader.surface))
            val previewRequest = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                addTarget(previewTarget)
                set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
            }.build()
            session.setRepeatingRequest(previewRequest, null, handler)
            status(if (uiPreview != null) "Live preview on" else "Camera open (no on-screen preview)")
            Thread.sleep(350)
            return block(device, session, reader, chars, openMs)
        } catch (e: Exception) {
            return Still(ok = false, error = e.message ?: e.javaClass.simpleName)
        } finally {
            status("Closing camera…")
            try { session?.stopRepeating() } catch (_: Exception) {}
            try { session?.close() } catch (_: Exception) {}
            try { device?.close() } catch (_: Exception) {}
            try { reader?.close() } catch (_: Exception) {}
            try { ownedPreview?.release() } catch (_: Exception) {}
            try { ownedTexture?.release() } catch (_: Exception) {}
        }
    }

    private fun takeStill(
        device: CameraDevice,
        session: CameraCaptureSession,
        reader: ImageReader,
        chars: CameraCharacteristics,
        flashMode: Int?,
        aeMode: Int?,
        zoom: Boolean,
    ): ByteArray? {
        val slot = Slot()
        reader.setOnImageAvailableListener({ imageReader ->
            try {
                val image = imageReader.acquireLatestImage()
                if (image == null) {
                    slot.error.compareAndSet(null, "no image")
                } else {
                    image.use {
                        val buffer = it.planes[0].buffer
                        val bytes = ByteArray(buffer.remaining())
                        buffer.get(bytes)
                        slot.bytes.set(bytes)
                    }
                }
            } catch (e: Exception) {
                slot.error.compareAndSet(null, e.message)
            } finally {
                slot.latch.countDown()
            }
        }, handler)
        val request = device.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
            addTarget(reader.surface)
            set(CaptureRequest.JPEG_QUALITY, 90.toByte())
            set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
            if (flashMode != null) set(CaptureRequest.FLASH_MODE, flashMode)
            if (aeMode != null) set(CaptureRequest.CONTROL_AE_MODE, aeMode)
            if (zoom) crop(chars)?.let { set(CaptureRequest.SCALER_CROP_REGION, it) }
        }.build()
        session.capture(request, object : CameraCaptureSession.CaptureCallback() {
            override fun onCaptureFailed(
                session: CameraCaptureSession,
                request: CaptureRequest,
                failure: android.hardware.camera2.CaptureFailure,
            ) {
                slot.error.compareAndSet(null, "capture failed")
                slot.latch.countDown()
            }
        }, handler)
        if (!slot.latch.await(20, TimeUnit.SECONDS)) return null
        return slot.bytes.get()
    }

    private fun crop(chars: CameraCharacteristics): android.graphics.Rect? {
        val zoom = chars.get(CameraCharacteristics.SCALER_AVAILABLE_MAX_DIGITAL_ZOOM) ?: 1f
        val active = chars.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE) ?: return null
        if (zoom <= 1.05f) return null
        val w = active.width() / 2
        val h = active.height() / 2
        val left = active.left + (active.width() - w) / 2
        val top = active.top + (active.height() - h) / 2
        return android.graphics.Rect(left, top, left + w, top + h)
    }

    private fun openCamera(id: String): CameraDevice {
        val latch = CountDownLatch(1)
        val opened = AtomicReference<CameraDevice?>(null)
        val error = AtomicReference<String?>(null)
        manager.openCamera(id, object : CameraDevice.StateCallback() {
            override fun onOpened(camera: CameraDevice) {
                opened.set(camera)
                latch.countDown()
            }

            override fun onDisconnected(camera: CameraDevice) {
                error.set("camera disconnected")
                camera.close()
                latch.countDown()
            }

            override fun onError(camera: CameraDevice, errorCode: Int) {
                error.set("camera error $errorCode")
                camera.close()
                latch.countDown()
            }
        }, handler)
        if (!latch.await(10, TimeUnit.SECONDS)) throw IllegalStateException("openCamera timed out")
        return opened.get() ?: throw IllegalStateException(error.get() ?: "openCamera failed")
    }

    @Suppress("DEPRECATION")
    private fun openSession(device: CameraDevice, surfaces: List<Surface>): CameraCaptureSession {
        val latch = CountDownLatch(1)
        val ready = AtomicReference<CameraCaptureSession?>(null)
        val error = AtomicReference<String?>(null)
        device.createCaptureSession(surfaces, object : CameraCaptureSession.StateCallback() {
            override fun onConfigured(session: CameraCaptureSession) {
                ready.set(session)
                latch.countDown()
            }

            override fun onConfigureFailed(session: CameraCaptureSession) {
                error.set("session configuration failed")
                latch.countDown()
            }
        }, handler)
        if (!latch.await(10, TimeUnit.SECONDS)) throw IllegalStateException("session timed out")
        return ready.get() ?: throw IllegalStateException(error.get() ?: "session failed")
    }

    private fun chooseJpeg(map: android.hardware.camera2.params.StreamConfigurationMap, largest: Boolean): Size? {
        val sizes = map.getOutputSizes(ImageFormat.JPEG)?.toList().orEmpty()
        if (sizes.isEmpty()) return null
        if (largest) {
            return sizes.filter { it.width.toLong() * it.height <= 8_000_000L }.maxByOrNull { it.width.toLong() * it.height }
                ?: sizes.minByOrNull { it.width.toLong() * it.height }
        }
        return sizes.filter { it.width <= 1280 && it.height <= 720 }.maxByOrNull { it.width.toLong() * it.height }
            ?: sizes.minByOrNull { it.width.toLong() * it.height }
    }

    private fun choosePreview(map: android.hardware.camera2.params.StreamConfigurationMap): Size {
        val sizes = map.getOutputSizes(SurfaceTexture::class.java)?.toList().orEmpty()
        return sizes.filter { it.width in 320..1280 }.minByOrNull { it.width.toLong() * it.height }
            ?: sizes.firstOrNull()
            ?: Size(640, 480)
    }

    private fun chooseVideo(map: android.hardware.camera2.params.StreamConfigurationMap): Size? {
        val sizes = map.getOutputSizes(MediaRecorder::class.java)?.toList().orEmpty()
        return sizes.firstOrNull { it.width == 640 && it.height == 480 }
            ?: sizes.filter { it.width <= 1280 }.minByOrNull { it.width.toLong() * it.height }
            ?: sizes.firstOrNull()
    }

    override fun close() {
        thread.quitSafely()
    }

    private class Slot {
        val latch = CountDownLatch(1)
        val bytes = AtomicReference<ByteArray?>(null)
        val error = AtomicReference<String?>(null)
    }
}
